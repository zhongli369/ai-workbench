"""BATTLE SCENARIO 3 — Agent pretending to finish (boundary probing).

The completion gate `can_claim_done` is a MECHANICAL CLI-internal state: it
is only computed when someone actually calls `harness verify status` (or
reads it from a `verify run` result). The harness ships NO hook that forces
a model to consult it (the only PreToolUse hook is harness_gate.py, which
gates Bash commands, not completion). So this scenario tests every branch
the gate CAN control, then honestly marks the lines it cannot.

Branches exercised (all with real exit codes):
  (a) no verification attempted      -> exit 1, can_claim_done=false
  (b) verification fails             -> exit 1, can_claim_done=false
  (c) verification skipped (no cfg)  -> verify run exit 3 (NOT pass),
                                        verify status exit 1, can_claim_done=false
  (d) verification times out         -> exit 1, timed_out true, can_claim_done=false
  (e) genuine pass                   -> exit 0, can_claim_done=true
  (f) reflections exhausted          -> exit 1, can_claim_done=false
  (g) bad config (timeout_s=0)       -> exit 2 bad_input (distinct code)
  (h) evidence log tampered (deleted after a pass)
                                     -> verify status exit 1, can_claim_done=false
  (i) stale-pass-after-config-removed -> can_claim_done STAYS true (boundary gap
        to report: skip appends no record, so the last pass survives)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from battle_util import (  # noqa: E402
    commit_all, git_repo, run_cli, run_cli_json, write,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="git not installed")


def _cfg(task_dir: Path, py: str, commands, timeout_s=30, max_reflections=1):
    write(task_dir / ".harness-verify.json",
          json.dumps({"commands": commands, "timeout_s": timeout_s,
                      "max_reflections": max_reflections}).encode())


def test_s3a_no_verification_yet_blocks_done(tmp_path):
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    commit_all(repo)
    data = tmp_path / "data"
    rc, out, err = run_cli(data, "verify", "status", "--exec", "s3a")
    assert rc == 1, out
    st = json.loads(out)
    assert st["can_claim_done"] is False
    assert st["latest"] is None


def test_s3b_failing_verification_blocks_done(tmp_path):
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    _cfg(repo, sys.executable, [[sys.executable, "-c",
                                 "import sys; sys.exit(1)"]], max_reflections=0)
    commit_all(repo)
    data = tmp_path / "data"
    rc, out, err = run_cli(data, "verify", "run", "--exec", "s3b",
                           "--stage", "t", "--cwd", str(repo))
    assert rc == 1, out + err
    assert json.loads(out)["status"] == "fail"
    rc, out, err = run_cli(data, "verify", "status", "--exec", "s3b")
    assert rc == 1, out
    assert json.loads(out)["can_claim_done"] is False


def test_s3c_skipped_is_not_pass(tmp_path):
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    commit_all(repo)
    data = tmp_path / "data"
    # run without any config -> skipped, exit 3 (neither 0 nor 1)
    rc, out, err = run_cli(data, "verify", "run", "--exec", "s3c",
                           "--stage", "t", "--cwd", str(repo))
    assert rc == 3, out + err
    assert json.loads(out)["status"] == "skipped"
    assert json.loads(out)["can_claim_done"] is False
    # status still refuses to claim done (no record exists)
    rc, out, err = run_cli(data, "verify", "status", "--exec", "s3c")
    assert rc == 1, out
    assert json.loads(out)["can_claim_done"] is False


def test_s3d_timeout_blocks_done(tmp_path):
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    _cfg(repo, sys.executable, [[sys.executable, "-c",
                                 "import time; time.sleep(30)"]],
         timeout_s=1, max_reflections=0)
    commit_all(repo)
    data = tmp_path / "data"
    rc, out, err = run_cli(data, "verify", "run", "--exec", "s3d",
                           "--stage", "t", "--cwd", str(repo))
    assert rc == 1, out + err
    v = json.loads(out)
    assert v["status"] == "fail"
    assert v["verdicts"][0]["timed_out"] is True, json.dumps(v, indent=2)
    rc, out, err = run_cli(data, "verify", "status", "--exec", "s3d")
    assert rc == 1, out
    assert json.loads(out)["can_claim_done"] is False


def test_s3e_genuine_pass_allows_done(tmp_path):
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    _cfg(repo, sys.executable, [[sys.executable, "-c",
                                 "print('ok')"]], max_reflections=0)
    commit_all(repo)
    data = tmp_path / "data"
    rc, out, err = run_cli(data, "verify", "run", "--exec", "s3e",
                           "--stage", "t", "--cwd", str(repo))
    assert rc == 0, out + err
    assert json.loads(out)["status"] == "pass"
    rc, out, err = run_cli(data, "verify", "status", "--exec", "s3e")
    assert rc == 0, out
    assert json.loads(out)["can_claim_done"] is True


def test_s3f_reflections_exhausted_blocks_done(tmp_path):
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    _cfg(repo, sys.executable, [[sys.executable, "-c",
                                 "import sys; sys.exit(1)"]],
         max_reflections=1)          # attempt 1,2 run; attempt 3 exhausted
    commit_all(repo)
    data = tmp_path / "data"
    for i in range(2):
        rc, out, err = run_cli(data, "verify", "run", "--exec", "s3f",
                               "--stage", "t", "--cwd", str(repo))
        assert rc == 1, out + err
        assert json.loads(out)["status"] == "fail"
    rc, out, err = run_cli(data, "verify", "run", "--exec", "s3f",
                           "--stage", "t", "--cwd", str(repo))
    assert rc == 1, out + err
    v = json.loads(out)
    assert v["status"] == "reflections-exhausted", json.dumps(v)
    assert v["reflections_exhausted"] is True
    rc, out, err = run_cli(data, "verify", "status", "--exec", "s3f")
    assert rc == 1, out
    assert json.loads(out)["can_claim_done"] is False


def test_s3g_bad_config_is_a_distinct_exit_2(tmp_path):
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    _cfg(repo, sys.executable, [[sys.executable, "-c", "pass"]],
         timeout_s=0)                # invalid: must be > 0
    commit_all(repo)
    data = tmp_path / "data"
    rc, out, err = run_cli(data, "verify", "run", "--exec", "s3g",
                           "--stage", "t", "--cwd", str(repo))
    assert rc == 2, out + err        # bad input, NOT a verification fail
    e = json.loads(err or out)
    assert e["error"] == "bad_input"


def test_s3h_tampered_evidence_never_reads_as_pass(tmp_path):
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    _cfg(repo, sys.executable, [[sys.executable, "-c", "print('ok')"]],
         max_reflections=0)
    commit_all(repo)
    data = tmp_path / "data"
    rc, _, _ = run_cli(data, "verify", "run", "--exec", "s3h",
                       "--stage", "t", "--cwd", str(repo))
    assert rc == 0
    rc, out, err = run_cli(data, "verify", "status", "--exec", "s3h")
    assert rc == 0 and json.loads(out)["can_claim_done"] is True
    # damage: wipe the evidence log -> status must fail closed, exit 1
    log = data / "verify" / "s3h.jsonl"
    assert log.is_file()
    log.unlink()
    rc, out, err = run_cli(data, "verify", "status", "--exec", "s3h")
    assert rc == 1, out
    assert json.loads(out)["can_claim_done"] is False


def test_s3i_stale_pass_survives_config_removal(tmp_path):
    """BOUNDARY GAP to report honestly.

    After a genuine pass, removing .harness-verify.json and re-running
    verify yields 'skipped' (exit 3), which appends NO record, so the last
    PASS stays latest and can_claim_done remains TRUE. The gate cannot see
    the config is gone because can_claim_done only reads the evidence log
    keyed by execution id, not the task cwd. Not a silent failure of the
    mechanism -- it is an explicit boundary: skip is a no-op, not a revoke.
    """
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    _cfg(repo, sys.executable, [[sys.executable, "-c", "print('ok')"]],
         max_reflections=0)
    commit_all(repo)
    data = tmp_path / "data"
    rc, out, err = run_cli(data, "verify", "run", "--exec", "s3i",
                           "--stage", "t", "--cwd", str(repo))
    assert rc == 0
    (repo / ".harness-verify.json").unlink()       # operator removes config
    rc, out, err = run_cli(data, "verify", "run", "--exec", "s3i",
                           "--stage", "t", "--cwd", str(repo))
    assert rc == 3, out + err                      # skipped
    rc, out, err = run_cli(data, "verify", "status", "--exec", "s3i")
    assert json.loads(out)["can_claim_done"] is True   # stale pass survives


def test_s3_boundary_claim_guard_is_cli_internal(tmp_path):
    """Honesty check: can_claim_done requires someone to CALL it.

    The harness wiring ships no PostToolUse/Stop hook that auto-runs
    `verify status` (verified in the repo: the only PreToolUse hook is
    hooks/harness_gate.py, plus the SessionEnd observability hook
    hooks/session_metrics.py — neither consults verify). We assert the
    observable fact that WITHOUT a CLI invocation there is no record and no
    gate effect -- i.e. the gate is consultative, not coercive. A model that
    never calls the CLI cannot be mechanically stopped by this component.
    """
    hooks_dir = Path(__file__).resolve().parents[2] / "hooks"
    hook_names = sorted(p.name for p in hooks_dir.glob("*.py"))
    assert hook_names == ["harness_gate.py", "session_metrics.py"], \
        f"unexpected hook set: {hook_names}"
    for name in hook_names:
        src = (hooks_dir / name).read_text(encoding="utf-8")
        assert "verify" not in src, f"{name} unexpectedly consults verify"
    # can_claim_done has no persistence of its own: freshly computed each call
    repo = git_repo(tmp_path / "repo")
    write(repo / "x.txt", b"hi\n")
    commit_all(repo)
    data = tmp_path / "data"
    rc, out, err = run_cli(data, "verify", "status", "--exec", "fresh-exec")
    assert rc == 1 and json.loads(out)["can_claim_done"] is False