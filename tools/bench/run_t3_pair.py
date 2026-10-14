"""T3 oracle cross-task transfer — two-phase pair driver (real model calls).

Phase 1: fusion arm solves t3a independently (find/fix/verify). Only on a
verified success do we mint an experience record from the REVIEWED static
template below (source=experiment-seed — synthetic fixtures are never labeled
human-verified).

Phase 2: t3b (same root-cause class, different surface) runs twice —
  treatment: fusion arm whose harness store is pre-seeded with the record
  control:   native arm, empty store
We then compare cost/turns/success and read the treatment workspace's
telemetry to count actual oracle queries.

Anti-leak rules (binding): the template names NO t3b file, field, command,
or value — only the failure CLASS and its generic mitigation. A contract in
tests/test_bench_infra.py enforces the ban list over this template.

--dry-run prints the plan without any API call.
"""
import argparse
import json
import os
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_sdk_arm as drv  # noqa: E402

TASKS = Path(__file__).resolve().parent / "tasks"

# REVIEWED 2026-10-14: class-level cause + generic mitigation only.
# Must NOT mention t3b's file names, field names, commands, or values.
T3_RECORD = {
    "project_id": "bench-t3",
    "cause": "legacy_json_state_schema",
    "summary": ("A shipped CLI crashed on a missing top-level schema marker in "
                "its JSON state file. Durable fix: migrate the STATE file to "
                "the current schema (add the marker with the current schema id, "
                "keep the payload intact). Do not patch the reader — the "
                "verifier hash-pins it, so reader edits are rejected."),
    "source": "experiment-seed",
    "confidence": 0.7,
}


def _args(model: str, arm: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(model=model, arm=arm)


def _cap_guard(ledger: Path | None, cap: float):
    if ledger and drv.ledger_spent(ledger) >= cap:
        print(f"[STOP] batch cap reached ({cap} USD) — ledger {ledger}")
        sys.exit(1)


def _append_ledger(ledger: Path | None, task: str, arm: str, cost: float):
    if not ledger:
        return
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps({"task": task, "arm": arm,
                            "total_cost_usd": cost or 0.0}) + "\n")


def _run_one(task: dict, arm: str, model: str, ws=None):
    ws = ws or drv.prepare_workspace(task, arm)
    agent = drv.asyncio.run(drv.run_agent(task, ws, _args(model, arm)))
    success, tail = drv.run_verify(task, ws)
    return {"ws": ws, "agent": agent, "success": success, "verify_tail": tail}


def _seed_experience(ws: Path) -> dict:
    env = {**os.environ, "HARNESS_DATA_DIR": str(ws / "harness-data"),
           "HARNESS_BENCH": "1"}  # seeded-experience writes are bench traffic
    cmd = [sys.executable, str(ws / drv.HARNESS_CLI_REL), "feedback", "record",
           "--project-id", T3_RECORD["project_id"],
           "--cause", T3_RECORD["cause"],
           "--summary", T3_RECORD["summary"],
           "--source", T3_RECORD["source"],
           "--confidence", str(T3_RECORD["confidence"])]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    if r.returncode != 0:
        raise SystemExit(f"seeding experience failed:\n{r.stdout}\n{r.stderr}")
    return env


def _oracle_query_count(ws: Path) -> int:
    tele = ws / "harness-data" / "telemetry.jsonl"
    if not tele.is_file():
        return 0
    n = 0
    for line in tele.read_text(encoding="utf-8").splitlines():
        if "query" in line and "feedback" in line:
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=drv.DEFAULT_MODEL)
    ap.add_argument("--ledger", type=Path, default=None)
    ap.add_argument("--batch-cap", type=float, default=3.0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    t3a = drv.load_task((TASKS / "t3a-legacy-state").resolve())
    t3b = drv.load_task((TASKS / "t3b-legacy-state-variant").resolve())

    if args.dry_run:
        print(json.dumps({
            "phase1": {"task": t3a["name"], "arm": "fusion",
                       "purpose": "independent solve -> verified experience"},
            "experience_record": T3_RECORD,
            "phase2": [
                {"task": t3b["name"], "arm": "fusion+seeded-store",
                 "purpose": "treatment"},
                {"task": t3b["name"], "arm": "native", "purpose": "control"},
            ],
            "model": args.model, "batch_cap": args.batch_cap,
        }, ensure_ascii=False, indent=2))
        return 0

    _cap_guard(args.ledger, args.batch_cap)
    p1 = _run_one(t3a, "fusion", args.model)
    _append_ledger(args.ledger, t3a["name"], "fusion",
                   p1["agent"].get("total_cost_usd"))
    if not p1["success"]:
        print(json.dumps({"aborted": "phase-1 t3a failed — no experience minted",
                          "verify_tail": p1["verify_tail"]}, ensure_ascii=False))
        return 2

    _cap_guard(args.ledger, args.batch_cap)
    ws_treat = drv.prepare_workspace(t3b, "fusion")
    _seed_experience(ws_treat)
    treat = _run_one(t3b, "fusion", args.model, ws=ws_treat)
    _append_ledger(args.ledger, t3b["name"], "fusion-seeded",
                   treat["agent"].get("total_cost_usd"))
    treat_queries = _oracle_query_count(ws_treat)

    _cap_guard(args.ledger, args.batch_cap)
    ctrl = _run_one(t3b, "native", args.model)
    _append_ledger(args.ledger, t3b["name"], "native",
                   ctrl["agent"].get("total_cost_usd"))

    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "exploratory": True,
        "phase1": {"task": t3a["name"], "success": p1["success"],
                   "cost": p1["agent"].get("total_cost_usd"),
                   "turns": p1["agent"].get("num_turns")},
        "experience_record": T3_RECORD,
        "treatment": {"task": t3b["name"], "success": treat["success"],
                      "cost": treat["agent"].get("total_cost_usd"),
                      "turns": treat["agent"].get("num_turns"),
                      "oracle_queries": treat_queries},
        "control": {"task": t3b["name"], "success": ctrl["success"],
                    "cost": ctrl["agent"].get("total_cost_usd"),
                    "turns": ctrl["agent"].get("num_turns")},
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if (treat["success"] and ctrl["success"]) else 2


if __name__ == "__main__":
    sys.exit(main())
