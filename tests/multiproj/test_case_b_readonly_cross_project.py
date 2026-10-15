"""CASE B — 跨项目只读 + 单项目写.

"Read B to analyze, change only A": B gets READ-ONLY harness probes, A gets
the writes. The byte-exact tree comparison proves read commands never touch
the project repo, and the data-dir comparison proves they do not even create
store directories. Writes to A never bleed into B.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from multiproj_util import (  # noqa: E402
    run_cli, run_cli_ok, tree_fingerprint, unexpected_harness_artifacts,
)


def test_case_b_readonly_probes_write_nothing(tmp_path, two_projects, data_dir):
    _ = tmp_path
    proj_a, proj_b = two_projects
    b_before = tree_fingerprint(proj_b)
    dd_before = tree_fingerprint(data_dir)

    # read-only probes scoped to proj-b (all self-excluded readers: no
    # telemetry, no store creation, no repo writes).
    probes = [
        ("snap", "list", "--cwd", str(proj_b)),
        ("checkpoint", "list"),
        ("checkpoint", "load", "--exec", "missing-exec"),
        ("gate", "check", "ls -la"),
        ("feedback", "stats", "--project-id", "proj-b-id"),
        ("report", "--project-id", "proj-b-id"),
        ("telemetry",),
    ]
    for argv in probes:
        rc, out, err = run_cli(data_dir, *argv, cwd=proj_b)
        assert rc == 0, (argv, rc, out, err)

    # proj-b bit-identical afterwards, including its .git.
    assert tree_fingerprint(proj_b) == b_before
    # and the shared data dir was not even lazily extended.
    assert tree_fingerprint(data_dir) == dd_before

    # a reader on a bogus snapshot is honest (exit 1, explicit error), but
    # still writes nothing anywhere.
    rc, out, err = run_cli(data_dir, "snap", "diff", "nope",
                           "--cwd", str(proj_b), cwd=proj_b)
    assert rc == 1
    assert "corrupt_snap" in err or "not found" in err
    assert tree_fingerprint(proj_b) == b_before
    assert tree_fingerprint(data_dir) == dd_before

    assert unexpected_harness_artifacts(proj_b) == []
    assert proj_a is not None  # silence unused-var lint


def test_case_b_write_only_to_a_never_touches_b(tmp_path, two_projects, data_dir):
    proj_a, proj_b = two_projects
    b_before = tree_fingerprint(proj_b)

    payload = tmp_path / "b-payload.json"
    payload.write_text('{"v": 2}', encoding="utf-8")
    run_cli_ok(data_dir, "checkpoint", "save", "--exec", "pa-w1",
               "--stage", "s", "--payload-file", str(payload), cwd=proj_a)
    run_cli_ok(data_dir, "feedback", "record", "--cause", "write-a",
               "--summary", "only a", cwd=proj_a)

    # B is still untouched by A's writes.
    assert tree_fingerprint(proj_b) == b_before
    assert unexpected_harness_artifacts(proj_b) == []

    # B's perspective sees none of A's records.
    rc, out, _ = run_cli(data_dir, "feedback", "query", "--project-id",
                         "proj-b-id", "--json", cwd=proj_b)
    assert rc == 0 and out.strip() in {"[]", ""}
    rc, out, _ = run_cli(data_dir, "feedback", "query", "--project-id",
                         "proj-a-id", "--json", cwd=proj_a)
    assert rc == 0 and "write-a" in out