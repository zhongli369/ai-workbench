"""Post-edit verification loop - a mechanical gate on the way to "done".

ALGORITHM ORIGIN (Apache-2.0, aider pinned 5dc9490b): the mechanism below is
extracted from aider's `base_coder.py:send_message` auto_lint / auto_test
section, `linter.py:Linter.lint`, `commands.py:cmd_test`, and the
`max_reflections` reflection bound. What is kept is the machinery: run a
trusted command -> capture the REAL exit code -> fold stdout+stderr into a
structured failure feedback record -> retry a bounded number of times
(mechanically counted, no judgement) -> write append-only, integrity-checked
evidence. Every LLM repair connection is OUT OF SCOPE this round: failing
output is recorded AS feedback for a future model-based repairer; this module
never reads it to fix anything.

Fail-closed authorization model:
  - A verify command is always an ARGV list executed by subprocess in list
    form, never a shell string and never through a shell.
  - Commands come from exactly two sources:
      (a) `.harness-verify.json` in the task cwd  - the operator's explicit
          pre-authorization. May run in ANY gate mode without consultation.
      (b) an explicit `--cmd` passed by the operator - requires gate
          consultation: DISABLED refuses (fail closed), AUDIT logs and
          allows, ENFORCE requires a valid one-shot approval token.
      (c) neither present -> {status: "skipped", reason: "no-verify-config"},
          never an error (preserves the lightweight default of "no tests").

Deterministic. stdlib only. py3.10+. No shell invocation anywhere. A timeout
on every subprocess. ASCII source; every persisted line is pure ASCII.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from harness import gate, state
from harness.state import CheckpointStore

SCHEMA_VERSION = 1
CONFIG_FILENAME = ".harness-verify.json"
DEFAULT_TIMEOUT_S = 120
DEFAULT_MAX_OUTPUT = 8192
DEFAULT_MAX_REFLECTIONS = 3
HARD_MAX_REFLECTIONS = 10
REFUSED = "refused"
EXHAUSTED = "reflections-exhausted"


# --------------------------------------------------------------------------- #
# small shared helpers
# --------------------------------------------------------------------------- #

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_exec_id(execution_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", execution_id)
    return safe[:120] or "unnamed"


def _payload_hash(payload: dict) -> str:
    """Deterministic sha256 over the payload (key-sorted, pure ASCII).

    Mirrors state.payload_hash so verify evidence is tamper-evident the same
    way checkpoints are: a re-read that re-hashes reports a mismatch.
    """
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def _display(argv: list[str]) -> str:
    """Quoted argv join for logs/UI. NEVER executed; not a shell string."""
    out = []
    for tok in argv:
        if any(ch.isspace() for ch in tok) or '"' in tok or "'" in tok:
            out.append('"' + tok.replace('"', '\\"') + '"')
        else:
            out.append(tok)
    return " ".join(out)


def clamp_reflections(n: int) -> int:
    """max_reflections clamped to [0, HARD_MAX_REFLECTIONS] (fail closed low).

    0 is legal: it means "first attempt only, no retries". Non-numeric input
    falls back to the DEFAULT_MAX_REFLECTIONS so a garbage config value can
    never silently widen the retry budget.
    """
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = DEFAULT_MAX_REFLECTIONS
    return max(0, min(v, HARD_MAX_REFLECTIONS))


# --------------------------------------------------------------------------- #
# command representation
# --------------------------------------------------------------------------- #

class VerifyCommand:
    """One authorized command: an argv list, never a shell string.

    Accept a list of argv tokens directly (recommended). A plain string is
    `shlex.split` into argv tokens (posix=False on Windows to keep paths and
    quotes local). Either way the subprocess is spawned in LIST form with no
    shell, so shell metacharacters (| ; > &) stay literal argv and can never
    become pipes or redirects. Empty argv is rejected.
    """

    def __init__(self, cmd: str | list[str]):
        if isinstance(cmd, str):
            self.argv = shlex.split(cmd, posix=(os.name != "nt"))
            if not self.argv:
                raise ValueError("verify command split to empty argv")
        elif isinstance(cmd, (list, tuple)):
            self.argv = [str(a) for a in cmd]
            if not self.argv:
                raise ValueError("verify command must not be empty")
        else:
            raise TypeError(
                f"verify command must be str or list, got {type(cmd).__name__}")
        if any(not a for a in self.argv):
            raise ValueError("verify command contains an empty argv token")

    def __iter__(self):
        return iter(self.argv)

    @property
    def display(self) -> str:
        return _display(self.argv)


# --------------------------------------------------------------------------- #
# low-level runner
# --------------------------------------------------------------------------- #

def _verdict(*, ok: bool, exit_code, timed_out: bool, output_tail: str,
             cmd_display: str, duration_ms: int, spawn_error: bool = False) -> dict:
    out = {
        "schema": SCHEMA_VERSION,
        "ok": bool(ok) and not bool(spawn_error),
        "exit_code": exit_code,
        "duration_ms": int(duration_ms),
        "timed_out": bool(timed_out),
        "output_tail": output_tail,
        "cmd_display": cmd_display,
        "ts": _now_iso(),
    }
    if spawn_error:
        out["spawn_error"] = True
    return out


def run_verification(argv, *, cwd, timeout_s: int = DEFAULT_TIMEOUT_S,
                     max_output: int = DEFAULT_MAX_OUTPUT) -> dict:
    """Run ONE verify command (argv list, list-form subprocess, no shell).

    stdout and stderr are MERGED, truncated to the TAIL `max_output` bytes,
    then decoded utf-8 with errors="replace" - non-UTF-8 output never crashes
    and never inflates a record. The return value is a Verdict dict:

      ok, exit_code, duration_ms, timed_out, output_tail, cmd_display, ts

    ok is True ONLY when the command finished in time AND exited 0.
    """
    cmd = VerifyCommand(argv)
    if timeout_s <= 0:
        raise ValueError("timeout_s must be > 0")
    if max_output <= 0:
        raise ValueError("max_output must be > 0")
    start = time.perf_counter()
    try:
        proc = subprocess.Popen(
            list(cmd), cwd=str(cwd), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        ms = int((time.perf_counter() - start) * 1000)
        return _verdict(ok=False, exit_code=None, timed_out=False,
                        output_tail=f"spawn error: {e}",
                        cmd_display=cmd.display, duration_ms=ms,
                        spawn_error=True)
    try:
        out, _ = proc.communicate(timeout=timeout_s)
        timed_out = False
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            out, _ = proc.communicate(timeout=5.0)
        except subprocess.TimeoutExpired:
            out = None
        timed_out = True
    rc = proc.returncode
    ms = int((time.perf_counter() - start) * 1000)
    tail_b = (out or b"")[-max_output:]
    text = tail_b.decode("utf-8", errors="replace")
    return _verdict(ok=(not timed_out and rc == 0),
                    exit_code=None if timed_out else rc,
                    timed_out=timed_out, output_tail=text,
                    cmd_display=cmd.display, duration_ms=ms)


# --------------------------------------------------------------------------- #
# append-only, integrity-checked evidence log
# --------------------------------------------------------------------------- #

class _VerifyLog:
    """<data_dir>/verify/<safe_exec_id>.jsonl - append+fsync, pure ASCII.

    Read is tolerant-but-never-silent, mirroring CheckpointStore: every
    anomaly (torn tail, corrupt line, bad schema, hash mismatch) is
    enumerated in a health dict; a corrupt log can never be read as a clean
    empty one.
    """

    def __init__(self, data_dir: Path):
        self._root = Path(data_dir) / "verify"

    def _path(self, execution_id: str) -> Path:
        return self._root / f"{_safe_exec_id(execution_id)}.jsonl"

    def append(self, record: dict) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=True) + "\n"
        assert line.isascii(), "verify record must be pure ASCII (locale-proof)"
        with open(self._path(record["execution_id"]), "a",
                  encoding="ascii", newline="\n") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def read(self, execution_id: str) -> tuple[list[dict], dict]:
        """(valid_records, health). Absent log is NOT damage."""
        health = {"ok": True, "corrupt_lines": [], "hash_failures": [],
                  "bad_schema_lines": [], "dropped_tail": 0}
        path = self._path(execution_id)
        if not path.is_file():
            return [], health
        try:
            raw = path.read_bytes()
        except OSError as e:
            health["ok"] = False
            health["corrupt_lines"].append(-1)
            return [], health
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
                    health["dropped_tail"] += 1
                else:
                    health["corrupt_lines"].append(line_no)
                health["ok"] = False
                continue
            if rec.get("schema") != SCHEMA_VERSION:
                health["bad_schema_lines"].append(line_no)
                health["ok"] = False
                continue
            if rec.get("payload_sha256") != _payload_hash(rec.get("payload", {})):
                health["hash_failures"].append(line_no)
                health["ok"] = False
                continue
            records.append(rec)
        return records, health

    def latest(self, execution_id: str) -> dict | None:
        records, _health = self.read(execution_id)
        return records[-1] if records else None


# --------------------------------------------------------------------------- #
# record factory
# --------------------------------------------------------------------------- #

def _make_record(execution_id: str, stage: str, attempt: int, status: str,
                 *, commands: list[str], verdicts: list[dict],
                 max_reflections: int, reason: str | None = None,
                 failed_cmd: str | None = None,
                 output_preview: str = "", exhausted: bool = False) -> dict:
    payload = {
        "result": status,
        "commands": commands,
        "verdicts": verdicts,
        "failed_cmd": failed_cmd,
        "output_preview": output_preview,
        "reason": reason,
    }
    rec = {
        "schema": SCHEMA_VERSION,
        "record_id": "vr-" + secrets.token_hex(8),
        "execution_id": execution_id,
        "ts": _now_iso(),
        "stage": stage,
        "attempt": int(attempt),
        "status": status,
        "reflections_exhausted": bool(exhausted),
        "max_reflections": int(max_reflections),
        "payload": payload,
        "payload_sha256": _payload_hash(payload),
    }
    return rec


# --------------------------------------------------------------------------- #
# the loop
# --------------------------------------------------------------------------- #

class VerificationLoop:
    """Bounded-retry verification with a fail-closed completion gate.

    Integration contract (checkpoint store):
      - every attempt appends a verdict record to the verify evidence log;
      - all-pass  -> CheckpointStore.save(status="done",   payload {"verify": "ok"});
      - run-fail  -> IF a checkpoint for that stage already exists,
                     CheckpointStore.save(status="failed", payload {verify: summary}).
      - can_claim_done(execution_id) is the mechanical gate: True ONLY when
        the latest evidened record is all-pass, the evidence log is healthy,
        and the retries used are within the recorded max_reflections.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._log = _VerifyLog(self.data_dir)
        self.checkpoints = CheckpointStore(self.data_dir)

    # ---------------------------------------------------------- config

    @staticmethod
    def load_config(task_cwd: Path) -> dict | None:
        """Read .harness-verify.json. Absent -> None (must not be an error).

        Schema: {"commands": [[argv...], ...], "timeout_s": N,
                 "max_reflections": M}. Strict validation: a malformed config
        raises ValueError - a config that LOOKS present but is broken must
        never silently fall through to "skipped".
        """
        path = Path(task_cwd) / CONFIG_FILENAME
        if not path.is_file():
            return None
        try:
            obj = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise ValueError(f"{CONFIG_FILENAME} is not valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"{CONFIG_FILENAME} must be a JSON object")
        commands = obj.get("commands")
        if not isinstance(commands, list) or not commands:
            raise ValueError(f"{CONFIG_FILENAME} requires a non-empty commands list")
        parsed: list[list[str]] = []
        for item in commands:
            parsed.append(list(VerifyCommand(item)))  # ValueError on bad entry
        timeout_s = obj.get("timeout_s", DEFAULT_TIMEOUT_S)
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            raise ValueError("timeout_s must be a positive number")
        max_reflections = clamp_reflections(
            obj.get("max_reflections", DEFAULT_MAX_REFLECTIONS))
        return {"commands": parsed, "timeout_s": int(timeout_s),
                "max_reflections": max_reflections}

    # ---------------------------------------------------------- authorization

    def authorize(self, *, task_cwd: Path, explicit_cmd=None,
                  token: str | None = None) -> dict:
        """Fail-closed command resolution.

        Returns one of:
          {"status": "ok",     "commands": [[argv...], ...],
           "timeout_s", "max_reflections", "source": "config"|"operator", "gate"}
          {"status": "skipped","reason": "no-verify-config"}
          {"status": "refused","reason", "cmd_display", "max_reflections"}
        """
        cfg = self.load_config(task_cwd)
        if cfg is not None:
            return {"status": "ok", "commands": cfg["commands"],
                    "timeout_s": cfg["timeout_s"],
                    "max_reflections": cfg["max_reflections"],
                    "source": "config", "gate": None}
        if explicit_cmd is None:
            return {"status": "skipped", "reason": "no-verify-config"}

        cmd = VerifyCommand(explicit_cmd)   # ValueError -> caller reports bad input
        display = cmd.display
        try:
            gcfg = gate.load_config(self.data_dir)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            return {"status": REFUSED,
                    "reason": f"gate config unreadable, fail closed: {e}",
                    "cmd_display": display,
                    "max_reflections": DEFAULT_MAX_REFLECTIONS}
        mode = gcfg.get("mode", "disabled")
        if mode == "disabled":
            # DISABLED is NOT a pass: an arbitrary operator --cmd must fail
            # closed. Use .harness-verify.json for gate-free pre-authorization.
            return {"status": REFUSED,
                    "reason": "arbitrary --cmd refused when gate is DISABLED "
                              "(fail closed); pre-authorize via "
                              f"{CONFIG_FILENAME} instead",
                    "cmd_display": display,
                    "max_reflections": DEFAULT_MAX_REFLECTIONS}

        decision = gate.evaluate(self.data_dir, display, token=token,
                                 mode_override=mode)
        if mode == "audit":
            gate.log_decision(self.data_dir, mode="audit",
                              decision=decision["decision"],
                              command=display, matched=decision.get("matched"))
            return {"status": "ok", "commands": [list(cmd)],
                    "timeout_s": DEFAULT_TIMEOUT_S,
                    "max_reflections": DEFAULT_MAX_REFLECTIONS,
                    "source": "operator", "gate": decision}
        # enforce - gate.evaluate already consumed the one-shot token.
        if decision["decision"] in ("block", "block-error"):
            return {"status": REFUSED,
                    "reason": decision.get("reason") or "no valid approval token",
                    "cmd_display": display,
                    "max_reflections": DEFAULT_MAX_REFLECTIONS}
        return {"status": "ok", "commands": [list(cmd)],
                "timeout_s": DEFAULT_TIMEOUT_S,
                "max_reflections": DEFAULT_MAX_REFLECTIONS,
                "source": "operator", "gate": decision}

    # ---------------------------------------------------------- attempt

    def _prior_count(self, execution_id: str) -> int:
        records, _health = self._log.read(execution_id)
        return len(records)

    def _result_of(self, rec: dict) -> dict:
        """Return dict for an already-persisted record (never appends)."""
        return {"status": rec["status"], "execution_id": rec["execution_id"],
                "stage": rec["stage"], "attempt": rec["attempt"],
                "record_id": rec["record_id"],
                "reason": rec["payload"].get("reason"),
                "verdicts": rec["payload"].get("verdicts"),
                "failed_cmd": rec["payload"].get("failed_cmd"),
                "reflections_exhausted": rec["reflections_exhausted"]}

    def attempt(self, execution_id: str, stage: str, *, task_cwd: Path,
                explicit_cmd=None, token: str | None = None,
                max_output: int = DEFAULT_MAX_OUTPUT) -> dict:
        """Run all configured commands (in order, stop at first failure).

        Returns {"status", "execution_id", "stage", "attempt", "record_id",
                 "reason", "verdicts", "failed_cmd", "reflections_exhausted"}
        with status in pass | fail | refused | skipped | reflections-exhausted.
        """
        auth = self.authorize(task_cwd=task_cwd, explicit_cmd=explicit_cmd,
                              token=token)
        attempt_no = self._prior_count(execution_id) + 1

        if auth["status"] == "skipped":
            return {"status": "skipped", "reason": auth["reason"],
                    "execution_id": execution_id, "stage": stage,
                    "attempt": attempt_no, "record_id": None, "verdicts": [],
                    "failed_cmd": None, "reflections_exhausted": False}

        max_ref = auth.get("max_reflections", DEFAULT_MAX_REFLECTIONS)

        if auth["status"] == REFUSED:
            rec = _make_record(execution_id, stage, attempt_no, REFUSED,
                               commands=[auth["cmd_display"]], verdicts=[],
                               max_reflections=max_ref, reason=auth["reason"])
            self._log.append(rec)
            return self._result_of(rec)

        # Mechanical reflection bound: first attempt is NOT a reflection.
        if attempt_no - 1 > max_ref:
            rec = _make_record(execution_id, stage, attempt_no, EXHAUSTED,
                               commands=[], verdicts=[], max_reflections=max_ref,
                               reason=f"max_reflections={max_ref} exceeded",
                               exhausted=True)
            self._log.append(rec)
            return self._result_of(rec)

        authored_commands = auth["commands"]           # list[list[str]]
        timeout_s = auth.get("timeout_s", DEFAULT_TIMEOUT_S)
        verdicts: list[dict] = []
        failed: dict | None = None
        for argv in authored_commands:
            v = run_verification(list(argv), cwd=task_cwd,
                                 timeout_s=timeout_s, max_output=max_output)
            verdicts.append({"ok": v["ok"], "exit_code": v["exit_code"],
                             "timed_out": v["timed_out"], "cmd": v["cmd_display"],
                             "tail": v["output_tail"][-400:]})
            if not v["ok"]:
                failed = verdicts[-1]
                break
        status = "fail" if failed else "pass"
        rec = _make_record(
            execution_id, stage, attempt_no, status,
            commands=[_display(c) for c in authored_commands],
            verdicts=verdicts, max_reflections=max_ref,
            failed_cmd=failed["cmd"] if failed else None,
            output_preview=failed["tail"] if failed else "")
        self._log.append(rec)
        self._update_checkpoint(execution_id, stage, rec, status)
        return self._result_of(rec)

    # ---------------------------------------------------------- checkpoint link

    def _update_checkpoint(self, execution_id: str, stage: str, rec: dict,
                           status: str) -> None:
        """Attach the verify outcome to the task checkpoint store."""
        try:
            records, _health = self.checkpoints.replay(execution_id)
        except state.CorruptStateError:
            records = []
        idx = max((r.get("stage_index", 0) for r in records), default=-1) + 1
        try:
            if status == "pass":
                self.checkpoints.save(execution_id, stage,
                                      {"verify": "ok"}, stage_index=idx,
                                      status="done")
            elif any(r.get("stage") == stage for r in records):
                summary = {
                    "result": "fail",
                    "attempt": rec["attempt"],
                    "failed_cmd": rec["payload"].get("failed_cmd"),
                    "output_preview": (rec["payload"].get("output_preview")
                                       or "")[:500],
                }
                self.checkpoints.save(execution_id, stage,
                                      {"verify": summary}, stage_index=idx,
                                      status="failed")
        except ValueError:
            pass  # never let a checkpoint write failure mask the verdict

    # ---------------------------------------------------------- completion gate

    def can_claim_done(self, execution_id: str) -> bool:
        """THE completion gate. True ONLY when:
          1. the evidence log is healthy (no corruption that would hide a fail),
          2. the LATEST record exists and is all-pass,
          3. retries used (attempt-1) are within the record's max_reflections.
        Anything else - absent evidence, a fail, a refusal, exhaustion, or
        damage - returns False. Failure to verify means "cannot claim done".
        """
        records, health = self._log.read(execution_id)
        if not health["ok"] or not records:
            return False
        latest = records[-1]
        if latest.get("status") != "pass":
            return False
        if latest.get("reflections_exhausted"):
            return False
        attempt_no = latest.get("attempt", 1)
        used = max(0, int(attempt_no) - 1)
        return used <= int(latest.get("max_reflections",
                                      DEFAULT_MAX_REFLECTIONS))

    # ---------------------------------------------------------- inspection

    def latest(self, execution_id: str) -> dict | None:
        return self._log.latest(execution_id)

    def health(self, execution_id: str) -> dict:
        """Explicit evidence health: damage is flagged, never silent."""
        records, health = self._log.read(execution_id)
        health["records"] = len(records)
        health["latest_status"] = records[-1].get("status") if records else None
        return health