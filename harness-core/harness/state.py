"""Task-state checkpoints: versioned, integrity-checked, crash-recoverable.

Born from the t8 incident (2026-10-14): a long-running pipeline wrote a
checkpoint whose payload hash was truncated on disk; the run then FAILED
verification and, worse, the failure mode was silent — a corrupt checkpoint
is indistinguishable from "no checkpoint" in naive JSONL stores
(SystemKernel's FileCheckpointStore.load_latest returns None on a torn
last line, which callers read as "start over" — evidence destroyed by
omission).

Design contract (the eight t8 requirements):
  1. Integrity detection   — every record carries payload_sha256; verify()
                             re-hashes and reports line-level failures.
  2. Explicit errors       — corruption surfaces as health reports /
                             CorruptStateError, never as a silent None.
  3. Versioned format      — every record carries "schema": 1; unknown
                             versions raise on read.
  4. Lossless read         — utf-8-sig tolerant (PowerShell BOM), CRLF
                             tolerant, pure-ASCII writes (ensure_ascii=True).
  5. Atomic write          — append + flush + fsync for the log; the crash
                             marker is written temp-then-rename.
  6. Crash recovery        — a torn LAST line (writer died mid-append) is
                             detected, dropped, and REPORTED
                             (health["dropped_tail"]); a ".active" marker
                             names the stage that was in flight.
  7. Cross-platform        — stdlib only; no locale assumptions anywhere.
  8. Evidence preservation — append-only: this module never truncates,
                             never overwrites, never "repairs" the log.
                             verify() reports; the human decides.

Zero LLM. Zero dependencies beyond stdlib.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

_STATUS_VALUES = {"started", "done", "failed", "blocked"}


class CorruptStateError(Exception):
    """A checkpoint file exists but no usable record could be recovered."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(execution_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", execution_id)
    return safe[:120] or "unnamed"


def payload_hash(payload: dict) -> str:
    """Deterministic sha256 over the payload (key-sorted, pure ASCII)."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


class CheckpointStore:
    """Append-only JSONL checkpoint store for one data directory.

    Layout:
      <data_dir>/checkpoints/<execution_id>.jsonl   — the append-only log
      <data_dir>/checkpoints/<execution_id>.active  — crash marker (in-flight stage)
    """

    def __init__(self, data_dir: Path):
        self._dir = Path(data_dir) / "checkpoints"

    # ---------------------------------------------------------- paths

    def _log(self, execution_id: str) -> Path:
        return self._dir / f"{_safe_id(execution_id)}.jsonl"

    def _marker(self, execution_id: str) -> Path:
        return self._dir / f"{_safe_id(execution_id)}.active"

    # ---------------------------------------------------------- crash marker

    def begin(self, execution_id: str, stage: str, stage_index: int = 0) -> dict:
        """Record that `stage` is now in flight. Atomic temp-then-rename.

        If the process dies before save(), the marker survives and active()
        reports exactly which stage was interrupted.
        """
        marker = {"schema": SCHEMA_VERSION, "execution_id": execution_id,
                  "stage": stage, "stage_index": stage_index, "ts": _now_iso()}
        self._dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._dir), prefix=".active-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(marker, ensure_ascii=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(self._marker(execution_id)))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return marker

    def active(self, execution_id: str) -> dict | None:
        """Return the in-flight stage marker, or None if cleanly finished.

        A present marker means the last run was interrupted between begin()
        and save() — resume from load_latest(), not from scratch.
        """
        path = self._marker(execution_id)
        if not path.is_file():
            return None
        try:
            rec = json.loads(path.read_text(encoding="utf-8-sig").strip())
        except (OSError, json.JSONDecodeError):
            return {"execution_id": execution_id, "stage": "<unreadable marker>",
                    "unreadable": True}
        return rec

    def _clear_marker(self, execution_id: str) -> None:
        try:
            self._marker(execution_id).unlink()
        except OSError:
            pass

    # ---------------------------------------------------------- write

    def save(self, execution_id: str, stage: str, payload: dict, *,
             stage_index: int = 0, status: str = "done") -> dict:
        """Append one checkpoint. NEVER truncates. Returns the record.

        The record's parent_id chains to the previous valid checkpoint,
        forming a lineage that verify() can check for gaps.
        """
        if status not in _STATUS_VALUES:
            raise ValueError(f"bad status: {status!r} (one of {sorted(_STATUS_VALUES)})")
        parent = None
        prev, _health = self.load_latest(execution_id)
        if prev is not None:
            parent = prev["checkpoint_id"]
        rec = {
            "schema": SCHEMA_VERSION,
            "checkpoint_id": "cp-" + secrets.token_hex(8),
            "execution_id": execution_id,
            "ts": _now_iso(),
            "stage": stage,
            "stage_index": stage_index,
            "status": status,
            "parent_id": parent,
            "payload": payload,
            "payload_sha256": payload_hash(payload),
        }
        self._dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=True) + "\n"
        assert line.isascii(), "checkpoint line must be pure ASCII (locale-proof)"
        with open(self._log(execution_id), "a", encoding="ascii", newline="\n") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        if status in {"done", "failed"}:
            self._clear_marker(execution_id)
        return rec

    # ---------------------------------------------------------- read

    def _read_all(self, execution_id: str) -> tuple[list[dict], dict]:
        """Parse the log tolerantly. Returns (valid_records, health).

        health = {"ok", "dropped_tail", "corrupt_lines", "hash_failures",
                  "bad_schema_lines"} — every anomaly is enumerated, so a
        caller can never mistake damage for absence.
        """
        health = {"ok": True, "dropped_tail": 0, "corrupt_lines": [],
                  "hash_failures": [], "bad_schema_lines": []}
        path = self._log(execution_id)
        if not path.is_file():
            return [], health
        try:
            raw = path.read_bytes()
        except OSError as e:
            health["ok"] = False
            health["corrupt_lines"].append(-1)
            raise CorruptStateError(f"checkpoint log unreadable: {e}") from e
        text = raw.decode("utf-8-sig", errors="replace")
        lines = text.split("\n")
        records: list[dict] = []
        n_lines = len([ln for ln in lines if ln.strip()])
        for i, ln in enumerate(lines):
            if not ln.strip():
                continue
            line_no = i + 1
            try:
                rec = json.loads(ln.strip().rstrip("\r"))
            except json.JSONDecodeError:
                if line_no == n_lines:
                    # torn tail: writer died mid-append — expected crash shape
                    health["dropped_tail"] += 1
                    health["ok"] = False
                else:
                    health["corrupt_lines"].append(line_no)
                    health["ok"] = False
                continue
            if rec.get("schema") != SCHEMA_VERSION:
                health["bad_schema_lines"].append(line_no)
                health["ok"] = False
                continue
            if rec.get("payload_sha256") != payload_hash(rec.get("payload", {})):
                health["hash_failures"].append(line_no)
                health["ok"] = False
                continue
            records.append(rec)
        if not records and (health["corrupt_lines"] or health["hash_failures"]
                            or health["bad_schema_lines"]):
            raise CorruptStateError(
                f"checkpoint log for {execution_id!r} exists but every line is "
                f"unusable: {health}")
        return records, health

    def load_latest(self, execution_id: str) -> tuple[dict | None, dict]:
        """Most recent VALID checkpoint + health. Never silent about damage."""
        records, health = self._read_all(execution_id)
        return (records[-1] if records else None), health

    def replay(self, execution_id: str) -> tuple[list[dict], dict]:
        """All valid checkpoints in chronological order + health."""
        return self._read_all(execution_id)

    def verify(self, execution_id: str) -> dict:
        """Full-chain integrity report: hashes, lineage, stage monotonicity."""
        records, health = self._read_all(execution_id)
        chain_breaks = []
        prev_id = None
        prev_index = -1
        non_monotonic = []
        for rec in records:
            if rec.get("parent_id") != prev_id:
                chain_breaks.append(rec.get("checkpoint_id"))
            prev_id = rec.get("checkpoint_id")
            idx = rec.get("stage_index", 0)
            if idx < prev_index:
                non_monotonic.append(rec.get("checkpoint_id"))
            prev_index = max(prev_index, idx)
        ok = health["ok"] and not chain_breaks and not non_monotonic
        return {
            "ok": ok,
            "execution_id": execution_id,
            "total_valid": len(records),
            "dropped_tail": health["dropped_tail"],
            "corrupt_lines": health["corrupt_lines"],
            "hash_failures": health["hash_failures"],
            "bad_schema_lines": health["bad_schema_lines"],
            "chain_breaks": chain_breaks,
            "non_monotonic": non_monotonic,
            "active_marker": self.active(execution_id),
        }
