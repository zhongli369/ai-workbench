"""BATTLE SCENARIO 2 — Agent writes a broken config; verify catches it.

Flow with REAL exit codes at each step:
  1. legal JSON config + a config-checker, committed;
  2. snap save;
  3. agent writes an INVALID config;
  4. verify run  -> FAILS (exit 1)  can_claim_done=false;
  5. verify status -> exit 1, can_claim_done=false;
  6. snap restore --apply -> config back to legal bytes;
  7. verify run  -> PASSES (exit 0) can_claim_done=true;
  8. verify status -> exit 0.

Also records the exit codes explicitly (the evidence for the battle report).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from battle_util import (  # noqa: E402  (branch marker)
    commit_all, git_repo, run_cli, run_cli_json, write,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="git not installed")


def _verify_config(task_dir: Path, py: str):
    """Write .harness-verify.json that validates config.json with the python."""
    cfg = {"commands": [[py, "check_config.py"]], "timeout_s": 30,
           "max_reflections": 1}
    write(task_dir / ".harness-verify.json",
          json.dumps(cfg).encode("utf-8"))
    check = (
        "import json, sys\n"
        "try:\n"
        "    json.load(open('config.json', encoding='utf-8'))\n"
        "    print('config OK')\n"
        "    sys.exit(0)\n"
        "except Exception as e:\n"
        "    print('config BROKEN:', e)\n"
        "    sys.exit(1)\n"
    )
    write(task_dir / "check_config.py", check.encode("utf-8"))


def test_s2_broken_config_is_caught_and_recovered(tmp_path):
    import sys as _sys

    repo = git_repo(tmp_path / "repo")
    good = b'{"model": "claude", "max_tokens": 1024, "retries": 3}\n'
    write(repo / "config.json", good)
    write(repo / "app.py", b"config = __import__('json').load(open('config.json'))\n")
    _verify_config(repo, _sys.executable)
    commit_all(repo)

    data = tmp_path / "data"
    snap = run_cli_json(data, "snap", "save", "--cwd", str(repo),
                        "--exec", "battle-s02")
    assert snap["status"] == "ok"

    # ---- agent writes an INVALID config
    write(repo / "config.json", b'{ "model": "claude", }')   # trailing comma -> invalid

    # verify must FAIL (real exit code 1), can_claim_done false
    rc, out, err = run_cli(data, "verify", "run", "--exec", "battle-s02",
                           "--stage", "config-check", "--cwd", str(repo))
    assert rc == 1, out + err
    v = json.loads(out)
    assert v["status"] == "fail"
    assert v["can_claim_done"] is False
    assert v["failed_cmd"] is not None
    assert "config BROKEN" in v["verdicts"][0]["tail"], json.dumps(v, indent=2)
    exit_run_fail = rc

    rc, out, err = run_cli(data, "verify", "status", "--exec", "battle-s02")
    assert rc == 1, out          # status exit 1 when done is NOT claimable
    st = json.loads(out)
    assert st["can_claim_done"] is False
    assert st["health"]["latest_status"] == "fail"
    exit_status_fail = rc

    # ---- restore the good config, re-verify -> pass
    rc, out, err = run_cli(data, "snap", "restore", snap["snap_id"],
                           "--cwd", str(repo), "--apply")
    assert rc == 0, out + err
    assert json.loads(out)["status"] == "restored"
    assert (repo / "config.json").read_bytes() == good
    exit_restore = rc

    rc, out, err = run_cli(data, "verify", "run", "--exec", "battle-s02",
                           "--stage", "config-check", "--cwd", str(repo))
    assert rc == 0, out + err
    v2 = json.loads(out)
    assert v2["status"] == "pass"
    assert v2["can_claim_done"] is True
    exit_run_pass = rc

    rc, out, err = run_cli(data, "verify", "status", "--exec", "battle-s02")
    assert rc == 0, out
    assert json.loads(out)["can_claim_done"] is True
    exit_status_pass = rc

    # record the real exit codes as evidence for the battle report
    print(f"\n[exit-codes] run_fail={exit_run_fail} status_fail={exit_status_fail} "
          f"restore={exit_restore} run_pass={exit_run_pass} "
          f"status_pass={exit_status_pass}")


def test_s2_verify_cannot_pass_without_config_file(tmp_path):
    """A project that never had a config: verify run exits 3 (skipped),
    verify status stays can_claim_done=false with exit 1 (no fake pass)."""
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    commit_all(repo)
    data = tmp_path / "data"
    rc, out, err = run_cli(data, "verify", "run", "--exec", "e-no-config",
                           "--stage", "s", "--cwd", str(repo))
    assert rc == 3, out + err          # skipped is NOT pass: distinct exit 3
    assert json.loads(out)["status"] == "skipped"
    rc, out, err = run_cli(data, "verify", "status", "--exec", "e-no-config")
    assert rc == 1, out
    assert json.loads(out)["can_claim_done"] is False