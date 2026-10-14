"""T6 oracle value verdict — four-arm discriminative driver (real model calls).

Task: t6-external-config-drift. The client fails with 'upstream refused';
the root cause lives in EXTERNAL state (a stale deploy config after an ops
endpoint rotation), NOT in the code. All information needed to solve it is
present in the workspace for EVERY arm (service log names the loaded config
file and the endpoint in use; the endpoints registry names the active one) —
the oracle is never the only source of truth, it can only be a SHORTCUT.

Arms (identical instruction, identical budget):
  native        — bare workspace
  ecc           — ECC payload, no harness (policy overhead on this task)
  fusion        — harness with an EMPTY store (query fires, fast-negative)
  fusion-seeded — harness store pre-seeded with the reviewed record below

The verdict reads: fusion-seeded vs fusion isolates the oracle; the seeded
arm's telemetry shows whether the agent actually QUERIED (layer-2 trigger)
and the turn/cost delta shows whether the answer helped (layer-3 benefit).

Anti-leak rules (binding): the record names NO t6 file, port, command or
value — only the failure CLASS and its generic diagnostic path. A contract
in tests/test_bench_infra.py enforces the ban list over this template.
Synthetic fixtures are never labeled human-verified.

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

# REVIEWED 2026-10-14: class-level cause + generic diagnostic path only.
# Must NOT mention t6's file names, ports, addresses, commands, or values.
T6_RECORD = {
    "project_id": "bench-t6",
    "cause": "external_config_drift",
    "summary": ("A client failed with 'upstream refused' / 'connection "
                "refused' while its code was correct: an external config it "
                "loads still pointed at a decommissioned endpoint after an "
                "ops rotation. Diagnostic path: the service log names the "
                "loaded config file and the endpoint value in use; validate "
                "that value against the current endpoint registry (the ops "
                "source of truth) and update the config — never patch "
                "hash-pinned code, and retry/timeout tuning does not help: "
                "the old endpoint is gone, not slow."),
    "source": "experiment-seed",
    "confidence": 0.7,
}

ARMS = ["native", "ecc", "fusion", "fusion-seeded"]


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


def _seed_experience(ws: Path) -> None:
    env = {**os.environ, "HARNESS_DATA_DIR": str(ws / "harness-data"),
           "HARNESS_BENCH": "1"}  # seeded-experience writes are bench traffic
    cmd = [sys.executable, str(ws / drv.HARNESS_CLI_REL), "feedback", "record",
           "--project-id", T6_RECORD["project_id"],
           "--cause", T6_RECORD["cause"],
           "--summary", T6_RECORD["summary"],
           "--source", T6_RECORD["source"],
           "--confidence", str(T6_RECORD["confidence"])]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    if r.returncode != 0:
        raise SystemExit(f"seeding experience failed:\n{r.stdout}\n{r.stderr}")


def _oracle_query_count(ws: Path) -> int:
    tele = ws / "harness-data" / "telemetry.jsonl"
    if not tele.is_file():
        return 0
    return sum(1 for line in tele.read_text(encoding="utf-8").splitlines()
               if "query" in line and "feedback" in line)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=drv.DEFAULT_MODEL)
    ap.add_argument("--ledger", type=Path, default=None)
    ap.add_argument("--batch-cap", type=float, default=3.0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    task = drv.load_task((TASKS / "t6-external-config-drift").resolve())

    if args.dry_run:
        print(json.dumps({
            "task": task["name"],
            "arms": [{"arm": a,
                      "store": ("seeded" if a == "fusion-seeded"
                                else "empty" if a == "fusion" else "none"),
                      "purpose": p} for a, p in zip(ARMS, (
                          "baseline", "policy-overhead isolation",
                          "mechanism control (empty store)",
                          "treatment (oracle shortcut available)"))],
            "experience_record": T6_RECORD,
            "model": args.model, "batch_cap": args.batch_cap,
        }, ensure_ascii=False, indent=2))
        return 0

    results = {}
    verify_path = (task["_dir"] / task["verify"]).resolve()
    for arm in ARMS:
        _cap_guard(args.ledger, args.batch_cap)
        real_arm = "fusion" if arm == "fusion-seeded" else arm
        ws = drv.prepare_workspace(task, real_arm)
        if arm == "fusion-seeded":
            _seed_experience(ws)
        # Incident-B lock: hash the independent verifier pre/post the agent
        # run — an agent that rewrites its own examiner voids the result.
        verify_hash_pre = drv._sha256(verify_path)
        agent = drv.asyncio.run(drv.run_agent(task, ws, _args(args.model, real_arm)))
        verify_tampered = verify_hash_pre != drv._sha256(verify_path)
        if verify_tampered:
            success, tail = False, "verify script modified during agent run — result void"
        else:
            success, tail = drv.run_verify(task, ws)
        _append_ledger(args.ledger, task["name"], arm,
                       agent.get("total_cost_usd"))
        results[arm] = {"success": success,
                        "cost": agent.get("total_cost_usd"),
                        "turns": agent.get("num_turns"),
                        "oracle_queries": _oracle_query_count(ws),
                        "skill_tool_calls": agent.get("skill_tool_calls"),
                        "verify_tampered": verify_tampered,
                        "verify_tail": tail}
        print(f"[t6] {arm}: success={success} "
              f"cost=${agent.get('total_cost_usd')} "
              f"turns={agent.get('num_turns')} "
              f"queries={results[arm]['oracle_queries']}")

    summary = {"ts": datetime.now(timezone.utc).isoformat(),
               "model": args.model, "exploratory": True,
               "task": task["name"], "experience_record": T6_RECORD,
               "arms": results}
    blob = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob + "\n", encoding="utf-8")
    print(blob)
    return 0 if all(r["success"] for r in results.values()) else 2


if __name__ == "__main__":
    sys.exit(main())
