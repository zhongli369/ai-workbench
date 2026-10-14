"""T8 long-horizon engineering — two-session resume driver (real model calls).

Task: t8-log-pipeline-resume. Session A implements pipeline stages 1–2 and
records them in PIPELINE_STATE.json; session B — a FRESH agent with no
memory of session A — must resume from the workspace checkpoint, trust
completed stages (not redo them), and finish stage 3 + integration.

Every arm runs the SAME two-session protocol (fairness):

  native — bare workspace
  ecc    — ECC payload, no harness
  fusion — harness installed (empty store; oracle may only fast-negative)

What this measures (directive 2.2):
  - session-B turns/cost: does the agent actually resume from workspace
    state, or does it re-investigate / redo everything?
  - redone flags: stage outputs whose sha256 CHANGED during session B
    even though they were complete and checkpointed after session A
    (redoing finished work = checkpoint contract not honored);
  - final verify: golden-exact stage outputs + truthful checkpoint.

The per-session budget is 0.4 USD (task.toml) so one arm costs at most
0.8 USD; --batch-cap still bounds the whole batch against the ledger.

--dry-run prints the plan without any API call.
"""
import argparse
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_sdk_arm as drv  # noqa: E402

TASKS = Path(__file__).resolve().parent / "tasks"
ARMS = ["native", "ecc", "fusion"]
STAGE_OUTPUTS = ["out/records.jsonl", "out/stats.json"]


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


def _oracle_query_count(ws: Path) -> int:
    tele = ws / "harness-data" / "telemetry.jsonl"
    if not tele.is_file():
        return 0
    return sum(1 for line in tele.read_text(encoding="utf-8").splitlines()
               if "query" in line and "feedback" in line)


def _stage_snapshot(ws: Path) -> dict:
    snap = {}
    for rel in STAGE_OUTPUTS:
        p = ws / rel
        snap[rel] = drv._sha256(p) if p.is_file() else None
    return snap


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=drv.DEFAULT_MODEL)
    ap.add_argument("--ledger", type=Path, default=None)
    ap.add_argument("--batch-cap", type=float, default=3.0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    task_dir = (TASKS / "t8-log-pipeline-resume").resolve()
    task = drv.load_task(task_dir)
    task_a = {**task, "_instruction": (task_dir / "instruction_a.md").read_text(encoding="utf-8")}
    task_b = {**task, "_instruction": (task_dir / "instruction_b.md").read_text(encoding="utf-8")}

    if args.dry_run:
        print(json.dumps({
            "task": task["name"],
            "protocol": "two sequential sessions per arm (A: stages 1-2 + "
                        "checkpoint; B: fresh agent resumes from checkpoint)",
            "per_session_budget_usd": task.get("max_budget_usd", 0.4),
            "arms": [{"arm": a, "store": ("empty" if a == "fusion" else "none"),
                      "purpose": p} for a, p in zip(ARMS, (
                          "baseline", "policy-overhead isolation",
                          "harness mechanism present"))],
            "metrics": ["session A/B turns+cost", "redone stage flags",
                        "final golden verify", "checkpoint truthfulness"],
            "model": args.model, "batch_cap": args.batch_cap,
        }, ensure_ascii=False, indent=2))
        return 0

    results = {}
    verify_path = (task["_dir"] / task["verify"]).resolve()
    for arm in ARMS:
        _cap_guard(args.ledger, args.batch_cap)
        ws = drv.prepare_workspace(task, arm)
        verify_hash_pre = drv._sha256(verify_path)

        agent_a = drv.asyncio.run(drv.run_agent(task_a, ws, _args(args.model, arm)))
        _append_ledger(args.ledger, task["name"], f"{arm}-A",
                       agent_a.get("total_cost_usd"))
        snap_after_a = _stage_snapshot(ws)
        print(f"[t8] {arm} session A: cost=${agent_a.get('total_cost_usd')} "
              f"turns={agent_a.get('num_turns')} stages_done="
              f"{[k for k, v in snap_after_a.items() if v]}")

        agent_b = drv.asyncio.run(drv.run_agent(task_b, ws, _args(args.model, arm)))
        _append_ledger(args.ledger, task["name"], f"{arm}-B",
                       agent_b.get("total_cost_usd"))
        snap_after_b = _stage_snapshot(ws)
        redone = {rel: (snap_after_a[rel] is not None
                        and snap_after_b[rel] is not None
                        and snap_after_a[rel] != snap_after_b[rel])
                  for rel in STAGE_OUTPUTS}

        verify_tampered = verify_hash_pre != drv._sha256(verify_path)
        if verify_tampered:
            success, tail = False, "verify script modified during agent run — result void"
        else:
            success, tail = drv.run_verify(task, ws)

        results[arm] = {
            "success": success,
            "cost_a": agent_a.get("total_cost_usd"),
            "cost_b": agent_b.get("total_cost_usd"),
            "cost_total": (agent_a.get("total_cost_usd") or 0)
                          + (agent_b.get("total_cost_usd") or 0),
            "turns_a": agent_a.get("num_turns"),
            "turns_b": agent_b.get("num_turns"),
            "stages_done_after_a": [k for k, v in snap_after_a.items() if v],
            "redone_in_b": redone,
            "oracle_queries": _oracle_query_count(ws),
            "skill_tool_calls": (agent_a.get("skill_tool_calls") or [])
                                + (agent_b.get("skill_tool_calls") or []),
            "verify_tampered": verify_tampered,
            "verify_tail": tail,
        }
        print(f"[t8] {arm}: success={success} "
              f"cost_total=${results[arm]['cost_total']:.4f} "
              f"turns_b={agent_b.get('num_turns')} redone={redone}")

    summary = {"ts": datetime.now(timezone.utc).isoformat(),
               "model": args.model, "exploratory": True,
               "task": task["name"], "protocol": "two-session resume",
               "arms": results}
    blob = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob + "\n", encoding="utf-8")
    print(blob)
    return 0 if all(r["success"] for r in results.values()) else 2


if __name__ == "__main__":
    sys.exit(main())
