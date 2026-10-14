"""Invocation telemetry. The reader must never produce a count of itself.

Ledger: telemetry.jsonl, one line per observed CLI command.
Event: {ts, cmd, project_id, argv, source} — argv logged as given; secrets
belong in env, argv is safe by convention (same convention as WorkFlow
deploy_cli: token via env, never argv).

Self-exclusion (P1.5, WorkFlow reader-outside-dispatch pattern):
  - reader commands (telemetry / feedback.stats / report / gate.check) are
    never logged — a stats system that counts its own reads inflates itself
  - every row carries a source label: "cli" (real user invocation, the only
    adoption signal), "bench" (paid experiments, HARNESS_BENCH=1), or
    "synthetic" (fixtures). Legacy rows without a source count as "cli".
  - summarize() reports by_source plus an adoption view filtered to
    source == "cli", so bench/synthetic traffic can never masquerade as
    product usage. summarize is a pure read: it appends nothing.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_LEDGER = "telemetry.jsonl"

# Pure readers: invoking them must never append a row.
_READER_COMMANDS = {"telemetry", "feedback.stats", "report", "gate.check"}

_SOURCES = {"cli", "reader", "bench", "synthetic"}
_DEFAULT_SOURCE = "cli"  # also the implied source of legacy rows


def log(data_dir: Path, *, cmd: str, project_id: str, argv: list[str],
        source: str | None = None) -> None:
    """Append one row. Never raises (telemetry must not break the tool)."""
    try:
        if cmd in _READER_COMMANDS:
            return
        src = source or ("bench" if os.environ.get("HARNESS_BENCH") == "1" else "cli")
        if src not in _SOURCES:
            raise ValueError(f"bad telemetry source: {src}")
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "cmd": cmd,
            "project_id": project_id,
            "argv": argv[1:] if argv else [],
            "source": src,
        }
        path = Path(data_dir) / _LEDGER
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — best-effort by design
        pass


def summarize(data_dir: Path) -> dict:
    """Read-only aggregate. Appends nothing; calling it twice must yield the
    same result (query-induced pollution is a self-exclusion violation)."""
    path = Path(data_dir) / _LEDGER
    if not path.is_file():
        return {"total": 0, "by_cmd": {}, "by_project": {}, "by_source": {},
                "adoption": {"total": 0, "by_cmd": {}}}
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    by_cmd: dict[str, int] = {}
    by_project: dict[str, int] = {}
    by_source: dict[str, int] = {}
    adopt_cmd: dict[str, int] = {}
    adopt_total = 0
    for r in rows:
        by_cmd[r["cmd"]] = by_cmd.get(r["cmd"], 0) + 1
        by_project[r["project_id"]] = by_project.get(r["project_id"], 0) + 1
        src = r.get("source") or _DEFAULT_SOURCE
        by_source[src] = by_source.get(src, 0) + 1
        if src == "cli":
            adopt_total += 1
            adopt_cmd[r["cmd"]] = adopt_cmd.get(r["cmd"], 0) + 1
    return {"total": len(rows), "by_cmd": by_cmd, "by_project": by_project,
            "by_source": by_source,
            "adoption": {"total": adopt_total, "by_cmd": adopt_cmd}}


def print_summary(data_dir: Path) -> None:
    s = summarize(data_dir)
    print(f"invocations: {s['total']} (adoption: {s['adoption']['total']})")
    for cmd, n in sorted(s["by_cmd"].items()):
        print(f"  {cmd}: {n}")
    for src, n in sorted(s["by_source"].items()):
        print(f"  source {src}: {n}")
    for pid, n in sorted(s["by_project"].items()):
        print(f"  project {pid}: {n}", file=sys.stderr)
