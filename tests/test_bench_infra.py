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
        # __pycache__/.pytest_cache are runtime artifacts, never publishable
        # (gitignored) — scanning them is the incident-C mistake
        raw = "".join(p.read_text(encoding="utf-8", errors="ignore")
                      for p in d.rglob("*") if p.is_file()
                      and not {"__pycache__", ".pytest_cache"}.intersection(p.parts))
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
    for arm in ("native", "fusion", "ecc"):
        r = subprocess.run([sys.executable, str(DRIVER), "--task", str(task),
                            "--arm", arm, "--dry-run"],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        plan = json.loads(r.stdout)
        assert plan["arm"] == arm and plan["task"] == task.name
        assert plan["permission_mode"] == "bypassPermissions"
        assert plan["setting_sources"] == ["project"]
        assert plan["model"].startswith("claude-")


def test_no_harness_install_is_ecc_only(tmp_path):
    """--no-harness (the ecc bench arm): ECC payload, zero harness traces."""
    target = tmp_path / "ecc_ws"
    r = subprocess.run([sys.executable, str(RC_ROOT / "tools" / "workbench.py"),
                        "--target", str(target), "install", "--scope", "project",
                        "--no-harness", "--yes"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (target / ".claude").is_dir(), "ECC payload missing"
    assert not (target / "harness-core").exists(), "harness-core leaked into ecc arm"
    assert not (target / "hooks").exists(), "gate hooks leaked into ecc arm"
    assert not (target / "harness-data" / "gate.json").exists()
    settings = json.loads((target / ".claude" / "settings.json").read_text(
        encoding="utf-8"))
    assert "hooks" not in settings, "ecc arm settings must not reference gate hooks"
    assert "env" not in settings, "ecc arm settings must not set HARNESS_DATA_DIR"
    # uninstall still owns-only sweeps the ecc payload
    u = subprocess.run([sys.executable, str(RC_ROOT / "tools" / "workbench.py"),
                        "--target", str(target), "uninstall", "--yes"],
                       capture_output=True, text=True, timeout=120)
    assert u.returncode == 0, u.stdout + u.stderr
    assert not (target / ".claude").exists()


def test_t3_record_template_has_no_answer_leak():
    """The seeded experience must carry the failure CLASS only — nothing that
    names t3b's files, fields, commands, or values (anti-cheat, §7)."""
    import importlib.util
    import re
    spec = importlib.util.spec_from_file_location(
        "run_t3_pair", RC_ROOT / "tools" / "bench" / "run_t3_pair.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    blob = json.dumps(mod.T3_RECORD, ensure_ascii=False).lower()
    for banned in (r"\binv\b", r"inv_state", r"\brevision\b", r"\bsku\b",
                   r"\btotal\b", r"\bnotes\b", r"\bversion\b", r"app\.py",
                   r"inv\.py", r"state\.json", r"t3a", r"t3b"):
        assert not re.search(banned, blob), f"answer leak in T3_RECORD: {banned}"
    # synthetic experience is never labeled human-verified
    assert mod.T3_RECORD["source"] == "experiment-seed"
    assert mod.T3_RECORD["confidence"] < 1.0


def _load_bench_module(name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        name, RC_ROOT / "tools" / "bench" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_t6_record_template_has_no_answer_leak():
    """The t6 seed must carry the failure CLASS and its generic diagnostic
    path only — nothing that names t6's files, ports, addresses, commands,
    or values (anti-cheat, PHASE P §1.3)."""
    import re
    mod = _load_bench_module("run_t6_quad")
    blob = json.dumps(mod.T6_RECORD, ensure_ascii=False).lower()
    # NB: project_id "bench-t6" is a store partition label (same class as
    # bench-t3), not answer content — the ban targets the workspace's
    # answer-bearing markers: file names, ports, addresses, banner.
    for banned in (r"deploy\.conf", r"endpoints\.json", r"server\.log",
                   r"mock_fleet", r"app\.py", r"19411", r"8443",
                   r"t6-external", r"fleet-ok", r"127\.0\.0\.1"):
        assert not re.search(banned, blob), f"answer leak in T6_RECORD: {banned}"
    # synthetic experience is never labeled human-verified
    assert mod.T6_RECORD["source"] == "experiment-seed"
    assert mod.T6_RECORD["confidence"] < 1.0


def test_t6_quad_dry_run():
    r = subprocess.run([sys.executable, str(RC_ROOT / "tools" / "bench" / "run_t6_quad.py"),
                        "--dry-run"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    assert [a["arm"] for a in plan["arms"]] == ["native", "ecc", "fusion",
                                                "fusion-seeded"]
    # seeding is the ONLY difference the treatment arm introduces
    stores = {a["arm"]: a["store"] for a in plan["arms"]}
    assert stores == {"native": "none", "ecc": "none", "fusion": "empty",
                      "fusion-seeded": "seeded"}
    assert plan["experience_record"]["source"] == "experiment-seed"


def test_t6_fairness_same_instruction_all_arms():
    """All four arms run the SAME task dict (instruction, budget, verify) —
    the only permitted differences are the workspace flavor (prepare_workspace
    arm) and the treatment's store seeding."""
    src = (RC_ROOT / "tools" / "bench" / "run_t6_quad.py").read_text(encoding="utf-8")
    assert src.count("drv.load_task(") == 1, "per-arm task loading risks drift"
    assert 'max_budget_usd' not in src.replace('task.get("max_budget_usd"', ""), \
        "driver must not override the per-run budget"


def test_t3_pair_dry_run(tmp_path):
    r = subprocess.run([sys.executable, str(RC_ROOT / "tools" / "bench" / "run_t3_pair.py"),
                        "--dry-run"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    plan = json.loads(r.stdout)
    assert plan["phase1"]["arm"] == "fusion"
    assert plan["experience_record"]["source"] == "experiment-seed"
    assert [p["purpose"] for p in plan["phase2"]] == ["treatment", "control"]


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
