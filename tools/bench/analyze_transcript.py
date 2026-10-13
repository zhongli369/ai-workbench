#!/usr/bin/env python3
"""Transcript forensics for bench arms — behavioral evidence, not vibes.

For each experiment result JSON (produced by run_arm.py), locate the full
session transcript (~/.claude/projects/**/<session_id>.jsonl) and count
what the model ACTUALLY did:

  - assistant turns
  - tool calls by tool name
  - Task (sub-agent) invocations          -> agent-theater detector
  - Skill invocations                     -> on-demand capability usage
  - harness CLI invocations (Bash/PS)     -> failure-oracle / gate usage
  - permission denials (from result JSON)

This is the evidence layer for the FAST/STANDARD/DEEP policy claim:
the tiers live in the prompt, so the proof is transcript-level behavior.

Usage:
  python bench/analyze_transcript.py bench/exp-*.json
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter
from pathlib import Path

PROJECTS_DIR = Path(os.path.expanduser("~")) / ".claude" / "projects"

# session-id -> transcript path cache (built lazily, once)
_index: dict[str, Path] | None = None


def _find_transcript(session_id: str) -> Path | None:
    global _index
    if _index is None:
        _index = {}
        for p in PROJECTS_DIR.rglob("*.jsonl"):
            _index[p.stem] = p
    return _index.get(session_id)


def analyze(result_json: Path) -> dict:
    d = json.loads(result_json.read_text(encoding="utf-8"))
    sid = d.get("session_id", "")
    row = {
        "file": result_json.name,
        "cost": d.get("total_cost_usd"),
        "denials": len(d.get("permission_denials", [])),
        "turns": 0,
        "tools": Counter(),
        "task_calls": 0,
        "skill_calls": 0,
        "harness_calls": 0,
        "transcript_found": False,
    }
    tp = _find_transcript(sid)
    if not tp:
        return row
    row["transcript_found"] = True
    for line in tp.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "assistant":
            continue
        row["turns"] += 1
        for block in (rec.get("message") or {}).get("content", []):
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name", "?")
            row["tools"][name] += 1
            if name == "Task":
                row["task_calls"] += 1
            elif name == "Skill":
                row["skill_calls"] += 1
            elif name in ("Bash", "PowerShell"):
                cmd = (block.get("input") or {}).get("command", "")
                if "harness" in cmd and "cli.py" in cmd:
                    row["harness_calls"] += 1
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="+", help="experiment result JSONs (glob ok)")
    a = ap.parse_args()
    files: list[str] = []
    for pat in a.results:
        files.extend(sorted(glob.glob(pat)) or [pat])

    rows = [analyze(Path(f)) for f in files]
    hdr = (f"{'file':<34} {'cost':>7} {'den':>3} {'turns':>5} "
           f"{'Task':>4} {'Skill':>5} {'hCLI':>4}  tools")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        tools = ",".join(f"{k}x{v}" for k, v in r["tools"].most_common())
        flag = "" if r["transcript_found"] else "  [NO TRANSCRIPT]"
        print(f"{r['file']:<34} {r['cost']:>7.4f} {r['denials']:>3} "
              f"{r['turns']:>5} {r['task_calls']:>4} {r['skill_calls']:>5} "
              f"{r['harness_calls']:>4}  {tools}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
