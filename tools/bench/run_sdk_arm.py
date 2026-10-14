"""Drive ONE bench arm on ONE task via claude-agent-sdk (real model calls).

Fairness (binding, see README.md): same model, fresh workspace copy per arm,
same instruction text, same permission mode, same setting_sources=["project"]
(no user-global config on either arm), per-arm isolated HARNESS_DATA_DIR,
hard budget gate via max_budget_usd, batch cap via --ledger/--batch-cap.

Arms:
  native — bare workspace + instruction
  fusion — workspace with the full workbench installed (ECC pinned +
           harness-core + gate AUDIT + capability registry)
  ecc    — workspace with the ECC-only workbench payload (install
           --no-harness: skills/agents/commands + policy CLAUDE.md, but no
           harness-core, no gate hook). Distinguishes "ECC rules did it"
           from "harness did it". The record captures which Skill tool
           calls actually happened — directory existence is NOT proof.

--dry-run resolves and prints the run plan WITHOUT any API call.
"""
import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path

RC_ROOT = Path(__file__).resolve().parents[2]
WORKBENCH = RC_ROOT / "tools" / "workbench.py"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
HARNESS_CLI_REL = Path("harness-core") / "harness" / "cli.py"


def load_task(task_dir: Path) -> dict:
    meta = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    for key in ("name", "canary", "instruction_file", "verify"):
        if key not in meta:
            raise SystemExit(f"task.toml missing {key}: {task_dir}")
    meta["_dir"] = task_dir
    meta["_instruction"] = (task_dir / meta["instruction_file"]).read_text(encoding="utf-8")
    return meta


def prepare_workspace(task: dict, arm: str) -> Path:
    ws = Path(tempfile.mkdtemp(prefix=f"bench_{task['name']}_{arm}_")) / "ws"
    if arm in ("fusion", "ecc"):
        # install into an EMPTY dir first (installer refuses foreign non-empty
        # dirs by design), then lay the task seed over it
        ws.mkdir(parents=True)
        install_cmd = [sys.executable, str(WORKBENCH), "--target", str(ws),
                       "install", "--scope", "project"]
        if arm == "ecc":
            install_cmd.append("--no-harness")
        r = subprocess.run(install_cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise SystemExit(f"workbench install failed:\n{r.stdout}\n{r.stderr}")
        if arm == "fusion":
            env = {**os.environ, "HARNESS_DATA_DIR": str(ws / "harness-data")}
            g = subprocess.run([sys.executable, str(ws / HARNESS_CLI_REL),
                                "gate", "mode", "--set", "audit"],
                               capture_output=True, text=True, timeout=60, env=env)
            if g.returncode != 0:
                raise SystemExit(f"gate set audit failed:\n{g.stdout}\n{g.stderr}")
    shutil.copytree(task["_dir"] / "seed", ws, dirs_exist_ok=True)
    return ws


def ledger_spent(path: Path) -> float:
    if not path.is_file():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            total += float(json.loads(line).get("total_cost_usd") or 0.0)
    return total


async def run_agent(task: dict, ws: Path, args) -> dict:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    env = dict(os.environ)
    env["HARNESS_BENCH"] = "1"  # bench traffic is labeled, never adoption
    if args.arm == "fusion":
        env["HARNESS_DATA_DIR"] = str(ws / "harness-data")
    opts = ClaudeAgentOptions(
        cwd=str(ws),
        model=args.model,
        permission_mode="bypassPermissions",
        setting_sources=["project"],
        max_turns=40,
        max_budget_usd=float(task.get("max_budget_usd", 0.75)),
        env=env,
    )
    result: dict = {"is_error": None}
    skill_calls: list[str] = []
    async for msg in query(prompt=task["_instruction"], options=opts):
        # Skill-tool invocations = what ECC actually loaded (directory
        # existence on disk proves nothing)
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            for block in content:
                if getattr(block, "name", None) == "Skill":
                    skill = (getattr(block, "input", None) or {}).get("skill")
                    if skill:
                        skill_calls.append(str(skill))
        if isinstance(msg, ResultMessage):
            for f in dataclasses.fields(msg):
                try:
                    result[f.name] = getattr(msg, f.name)
                except AttributeError:
                    pass
    result["skill_tool_calls"] = skill_calls
    return result


def run_verify(task: dict, ws: Path) -> tuple[bool, str]:
    out = subprocess.run([sys.executable, str(task["_dir"] / task["verify"])],
                         capture_output=True, text=True, timeout=300, cwd=ws)
    tail = "\n".join((out.stdout + out.stderr).splitlines()[-8:])
    return out.returncode == 0, tail


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task", required=True, type=Path)
    ap.add_argument("--arm", required=True, choices=["native", "fusion", "ecc"])
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--ledger", type=Path, default=None,
                    help="batch cost ledger (JSONL); refuses to run past --batch-cap")
    ap.add_argument("--batch-cap", type=float, default=3.0)
    ap.add_argument("--dry-run", action="store_true", help="print plan, no API call")
    args = ap.parse_args()

    task = load_task(args.task.resolve())
    plan = {"task": task["name"], "tier": task.get("tier"), "arm": args.arm,
            "model": args.model, "max_budget_usd": task.get("max_budget_usd", 0.75),
            "setting_sources": ["project"], "permission_mode": "bypassPermissions"}

    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    if args.ledger and ledger_spent(args.ledger) >= args.batch_cap:
        print(f"[STOP] batch cap reached ({args.batch_cap} USD) — ledger {args.ledger}")
        return 1

    ws = prepare_workspace(task, args.arm)
    # Incident-B lock: the verifier is the independent judge — hash it before
    # and after the agent run. An agent (bypassPermissions, repo reachable)
    # that rewrites its own examiner voids the result even if it restores
    # content afterwards (final-state hash; documented residual).
    verify_path = (task["_dir"] / task["verify"]).resolve()
    verify_hash_pre = _sha256(verify_path)
    agent = asyncio.run(run_agent(task, ws, args))
    verify_hash_post = _sha256(verify_path)
    verify_tampered = verify_hash_pre != verify_hash_post
    if verify_tampered:
        success, verify_tail = False, "verify script modified during agent run — result void"
    else:
        success, verify_tail = run_verify(task, ws)

    record = {
        **plan,
        "ts": datetime.now(timezone.utc).isoformat(),
        "success": success,
        "verify_tail": verify_tail,
        "verify_sha256": verify_hash_post,
        "verify_tampered": verify_tampered,
        "total_cost_usd": agent.get("total_cost_usd"),
        "num_turns": agent.get("num_turns"),
        "duration_ms": agent.get("duration_ms"),
        "is_error": agent.get("is_error"),
        "skill_tool_calls": agent.get("skill_tool_calls", []),
        "workspace": str(ws),
        "exploratory": True,  # N=1 cells are never generalizable claims
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    if args.ledger:
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(args.ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps({"task": task["name"], "arm": args.arm,
                                "total_cost_usd": record["total_cost_usd"] or 0.0}) + "\n")
    print(json.dumps({k: record[k] for k in
                      ("task", "arm", "success", "total_cost_usd", "num_turns",
                       "duration_ms", "is_error")}, ensure_ascii=False))
    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
