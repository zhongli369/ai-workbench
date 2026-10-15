"""BATTLE SCENARIO 4 — interrupted multi-stage task resumes.

A real three-stage task driven entirely through the harness CLI:
    stage 1 build-module   : create src/mod.py skeleton
    stage 2 add-function   : append add() and mul()           (sensitive op,
                              logged once in oplog.txt — must NOT repeat)
    stage 3 write-tests    : pytest test for add()

The model crashes between `checkpoint begin --stage write-tests` and
`checkpoint save` (a killed subprocess). We then:
  * checkpoint load  -> reports LAST VALID checkpoint + active marker;
  * checkpoint verify-> integrity ok;
  * resume EXACTLY at stage 3 (stage 1/2 files untouched, no re-execution
    of the sensitive oplog append);
  * verify run -> pass; checkpoint save done -> marker cleared.

PROVEN here: deterministic CLI resume (durable, integrity-checked state and
an exact resume point). NOT proven here: model-owned autonomous resume —
that requires the agent to read `checkpoint load` and CHOOSE the right stage;
the CLI supplies the mechanism, not the decision.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from battle_util import (  # noqa: E402
    commit_all, git_repo, run_cli, run_cli_json, write,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="git not installed")

EXEC = "battle-s04"
STAGES = ["build-module", "add-function", "write-tests"]


def _plan(data):
    """plan -> phases + checkpoint hint (deterministic scaffold)."""
    result = run_cli_json(data, "plan",
                          "implement a calculator module and write passing tests",
                          "--archetype", "feature-generic")
    assert result["archetype"] == "feature-generic"
    assert len(result["phases"]) >= 3
    assert result["checkpoint_hint"]["execution_id"]
    return result


def _begin(data, repo, stage):
    rc, out, err = run_cli(data, "checkpoint", "begin", "--exec", EXEC,
                           "--stage", stage)
    assert rc == 0, err


def _save(data, repo, stage, payload, status="done", index=0):
    rc, out, err = run_cli(data, "checkpoint", "save", "--exec", EXEC,
                           "--stage", stage, "--status", status,
                           "--index", str(index),
                           "--payload", json.dumps(payload))
    assert rc == 0, err
    return json.loads(out)


def test_s4_interrupted_resume(tmp_path):
    repo = git_repo(tmp_path / "repo")
    data = tmp_path / "data"

    plan = _plan(data)
    write(repo / "oplog.txt", b"")     # sensitive-op ledger

    # ---------------- stage 1: build module
    _begin(data, repo, STAGES[0])
    write(repo / "src" / "__init__.py", b"")
    write(repo / "src" / "mod.py", b'"""calculator module"""\nVERSION = "0.1.0"\n')
    commit_all(repo, "stage1")
    _save(data, repo, STAGES[0], {"files": ["src/mod.py"]}, index=0)

    # ---------------- stage 2: add function (sensitive op)
    _begin(data, repo, STAGES[1])
    snap = run_cli_json(data, "snap", "save", "--cwd", str(repo),
                        "--exec", EXEC)
    with open(repo / "oplog.txt", "a", encoding="utf-8") as f:
        f.write("SENSITIVE-OP-2\n")     # must NOT run again on resume
    mod = repo / "src" / "mod.py"
    mod.write_text(mod.read_text(encoding="utf-8") +
                   "\ndef add(a, b):\n    return a + b\n\n"
                   "def mul(a, b):\n    return a * b\n", encoding="utf-8")
    commit_all(repo, "stage2")
    _save(data, repo, STAGES[1], {"files": ["src/mod.py"], "snap": snap["snap_id"]},
          index=1)

    # ---------------- crash at the START of stage 3
    _begin(data, repo, STAGES[2])       # marker written, then process dies

    # ---- resume: read state
    load = run_cli_json(data, "checkpoint", "load", "--exec", EXEC)
    assert load["checkpoint"]["stage"] == STAGES[1]       # last VALID = stage 2
    assert load["checkpoint"]["status"] == "done"
    assert load["active_marker"] is not None              # stage 3 was in flight
    assert load["active_marker"]["stage"] == STAGES[2]
    assert load["health"]["ok"] is True

    v = run_cli_json(data, "checkpoint", "verify", "--exec", EXEC)
    assert v["ok"] is True

    # stage-2 artifacts intact and SENSITIVE op NOT re-executed
    assert "def add" in (repo / "src/mod.py").read_text(encoding="utf-8")
    assert "def mul" in (repo / "src/mod.py").read_text(encoding="utf-8")
    assert (repo / "oplog.txt").read_text(encoding="utf-8") == "SENSITIVE-OP-2\n"

    # ---------------- resume completes stage 3 only
    write(repo / "tests" / "test_add.py",
          ("from src.mod import add, mul\n"
           "def test_add():\n"
           "    assert add(2, 3) == 5\n"
           "def test_mul():\n"
           "    assert mul(2, 3) == 6\n").encode())
    commit_all(repo, "stage3")
    cfg = {"commands": [[sys.executable, "-m", "pytest", "tests/test_add.py",
                         "-q"]], "timeout_s": 60, "max_reflections": 0}
    write(repo / ".harness-verify.json", json.dumps(cfg).encode())
    rc, out, err = run_cli(data, "verify", "run", "--exec", EXEC,
                           "--stage", STAGES[2], "--cwd", str(repo))
    assert rc == 0, out + err
    assert json.loads(out)["status"] == "pass"
    assert json.loads(out)["can_claim_done"] is True
    rc, out, err = run_cli(data, "verify", "status", "--exec", EXEC)
    assert rc == 0 and json.loads(out)["can_claim_done"] is True

    # marker cleared, chain healthy, sensitive op still single
    load2 = run_cli_json(data, "checkpoint", "load", "--exec", EXEC)
    assert load2["active_marker"] is None
    assert load2["checkpoint"]["stage"] == STAGES[2]
    v2 = run_cli_json(data, "checkpoint", "verify", "--exec", EXEC)
    assert v2["ok"] is True
    assert v2["non_monotonic"] == [] and v2["chain_breaks"] == []
    assert (repo / "oplog.txt").read_text(encoding="utf-8") == "SENSITIVE-OP-2\n"

    # the crash marker path is durable: replay sees a healthy chain
    replay = run_cli_json(data, "checkpoint", "replay", "--exec", EXEC)
    assert replay["health"]["ok"] is True
    assert len(replay["checkpoints"]) == 3