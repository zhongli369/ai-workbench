"""CASE E — 简单任务零开销 (plain project, zero harness overhead).

In an ordinary project with NO workbench installed, run the everyday
operations (git status, write a file, `python -m pytest` on a dummy test)
and prove none of them fabricate .harness* artifacts, snap refs, or writes
outside the project. Then prove the harness READ-ONLY commands against such
a project are readers: they exit cleanly, fail open where configured, write
nothing to the project and do not even create their data directory.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from multiproj_util import (  # noqa: E402
    base_env, git, run_cli, tree_fingerprint, unexpected_harness_artifacts,
    mk_plain_project, write_text,
)


def test_case_e_plain_ops_leave_zero_harness_trace(tmp_path):
    plain = mk_plain_project(tmp_path / "plain")

    # 1) everyday git op
    assert git(plain, "status", "--porcelain").returncode == 0
    # 2) an ordinary file write
    write_text(plain / "notes.txt", "no harness here\n")
    # 3) a real pytest run on a dummy test
    write_text(plain / "test_dummy.py", "def test_dummy():\n    assert True\n")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(plain / "test_dummy.py"),
         "-q", "-p", "no:cacheprovider"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(plain), env=base_env(), timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout

    # 4) no harness artifacts, no snap refs, nothing else outside plain.
    assert unexpected_harness_artifacts(plain) == []
    assert git(plain, "for-each-ref", "refs/harness").stdout == ""
    leftovers = sorted(p.name for p in tmp_path.iterdir()
                       if not p.samefile(plain))
    assert leftovers == [], f"writes leaked outside the project: {leftovers}"


def test_case_e_harness_readers_on_plain_project_write_nothing(tmp_path):
    plain = mk_plain_project(tmp_path / "plain")
    b_plain = tree_fingerprint(plain)
    probe_data = tmp_path / "harness-data"    # deliberately OUTSIDE plain
    assert not probe_data.exists()

    # read-only probes, data dir pointing at a place that must NOT appear.
    readers = [
        ("gate", "check", "ls -la"),
        ("gate", "check", "git push origin main"),
        ("snap", "list", "--cwd", str(plain)),
        ("checkpoint", "list"),
        ("feedback", "stats", "--project-id", "plain"),
        ("report", "--project-id", "plain"),
        ("telemetry",),
    ]
    for argv in readers:
        rc, out, err = run_cli(probe_data, *argv, cwd=plain, timeout=120)
        assert rc == 0, (argv, rc, out, err)

    # no data dir was created, project bit-identical, no harness files.
    assert not probe_data.exists()
    assert tree_fingerprint(plain) == b_plain
    assert unexpected_harness_artifacts(plain) == []
    # a benign gate check on an unconfigured (disabled) store is fail-open.
    rc, out, err = run_cli(probe_data, "gate", "check", "git push origin main",
                           cwd=plain, timeout=120)
    assert rc == 0
    assert json.loads(out)["decision"] == "allow"
    assert not probe_data.exists()