"""Invocation telemetry. The reader must never produce a count of itself.

Ledger: telemetry.jsonl, one line per observed CLI command.
Event: {ts, cmd, project_id, argv} — argv already stripped of --data-dir? no:
argv logged as given minus nothing secret; secrets belong in env, argv is safe by
convention (same convention as WorkFlow deploy_cli: token via env, never argv).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_LEDGER = "telemetry.jsonl"

# Commands counted as pure reads — invoking them must not append a row.
_READER_COMMANDS = {"telemetry"}


def log(data_dir: Path, *, cmd: str, project_id: str, argv: list[str]) -> None:
    """Append one row. Never raises (telemetry must not break the tool)."""
    try:
        if cmd in _READER_COMMANDS:
            return
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "cmd": cmd,
            "project_id": project_id,
            "argv": argv[1:] if argv else [],
        }
        path = Path(data_dir) / _LEDGER
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — best-effort by design
        pass


def summarize(data_dir: Path) -> dict:
    """Read-only aggregate. Callers must route before log()."""
    path = Path(data_dir) / _LEDGER
    if not path.is_file():
        return {"total": 0, "by_cmd": {}, "by_project": {}}
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    by_cmd: dict[str, int] = {}
    by_project: dict[str, int] = {}
    for r in rows:
        by_cmd[r["cmd"]] = by_cmd.get(r["cmd"], 0) + 1
        by_project[r["project_id"]] = by_project.get(r["project_id"], 0) + 1
    return {"total": len(rows), "by_cmd": by_cmd, "by_project": by_project}


def print_summary(data_dir: Path) -> None:
    s = summarize(data_dir)
    print(f"invocations: {s['total']}")
    for cmd, n in sorted(s["by_cmd"].items()):
        print(f"  {cmd}: {n}")
    for pid, n in sorted(s["by_project"].items()):
        print(f"  project {pid}: {n}", file=sys.stderr)