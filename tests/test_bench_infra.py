"""Bench infrastructure contracts (offline, no model, no network).

Guards the M5 harness itself: task schema validity, canary discipline,
verify scripts that are NOT vacuous (must fail on pristine seed), dry-run
plan output, and the batch cost cap that stops paid runs.
"""
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

RC_ROOT = Path(__file__).resolve().parent.parent
TASKS = RC_ROOT / "tools" / "bench" / "tasks"
DRIVER = RC_ROOT / "tools" / "bench" / "run_sdk_arm.py"


def _task_dirs():
    return sorted(p for p in TASKS.iterdir() if p.is_dir() and (p / "task.toml").is_file())


def test_task_schema_and_canary_discipline():
    dirs = _task_dirs()
    assert len(dirs) >= 3, "batch-1 expects at least 3 tasks"
    for d in dirs:
        meta = tomllib.loads((d / "task.toml").read_text(encoding="utf-8"))
        for key in ("name", "tier", "canary", "instruction_file", "verify"):
            assert key in meta, f"{d.name}: missing {key}"
        assert meta["canary"].startswith("canary:AIWB-")
        assert (d / meta["instruction_file"]).is_file()
        assert (d / meta["verify"]).is_file()
        assert (d / "seed").is_dir()
        instr = (d / meta["instruction_file"]).read_text(encoding="utf-8")
        assert meta["canary"] in instr, f"{d.name}: canary not embedded in instruction"
        raw = "".join(p.read_text(encoding="utf-8", errors="ignore")
                      for p in d.rglob("*") if p.is_file())
        for bad in ("F:\\", "C:\\Users", "/Users/", "/home/", "14679"):
            assert bad not in raw, f"{d.name}: machine-specific fragment {bad}"


@pytest.mark.parametrize("task_dir", _task_dirs(), ids=lambda p: p.name)
def test_verify_is_not_vacuous_fails_on_pristine_seed(tmp_path, task_dir):
    """A verify.py that passes on the untouched seed proves nothing."""
    ws = tmp_path / "ws"
    shutil.copytree(task_dir / "seed", ws)
    meta = tomllib.loads((task_dir / "task.toml").read_text(encoding="utf-8"))
    r = subprocess.run([sys.executable, str(task_dir / meta["verify"])],
                       capture_output=True, text=True, timeout=180, cwd=ws)
    assert r.returncode != 0, f"{task_dir.name}: verify passed on pristine seed (vacuous!)"
    # ...and it must fail for the RIGHT reason (a crash traceback proves nothing either)
    assert "VERIFY FAIL" in r.stdout, (
        f"{task_dir.name}: pristine failure was not a genuine check failure:\n"
        f"{r.stdout[-300:]}\n{r.stderr[-300:]}")


def test_driver_dry_run_both_arms(tmp_path):
    task = _task_dirs()[0]
    for arm in ("native", "fusion"):
        r = subprocess.run([sys.executable, str(DRIVER), "--task", str(task),
                            "--arm", arm, "--dry-run"],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        plan = json.loads(r.stdout)
        assert plan["arm"] == arm and plan["task"] == task.name
        assert plan["permission_mode"] == "bypassPermissions"
        assert plan["setting_sources"] == ["project"]
        assert plan["model"].startswith("claude-")


def test_driver_refuses_when_batch_cap_reached(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps({"total_cost_usd": 99.0}) + "\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(DRIVER), "--task", str(_task_dirs()[0]),
                        "--arm", "native", "--ledger", str(ledger),
                        "--batch-cap", "3.0"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "[STOP]" in r.stdout
    # no workspace was prepared, no ledger growth
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1
