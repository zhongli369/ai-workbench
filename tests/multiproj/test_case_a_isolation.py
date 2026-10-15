"""CASE A — 双项目隔离 (dual-project isolation).

In proj-a, run harness writes (checkpoint save / snap save / feedback
record) and assert, against the REAL layering (shared data_dir + per-repo
git refs + per-project identity):
  * proj-b's working tree and git refs stay bit-for-bit untouched;
  * proj-a's snapshot manifest never references proj-b's path;
  * each project's own data lands where it belongs (checkpoint keyed by
    exec, snap refs in its own repo, feedback keyed by its project id).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from multiproj_util import (  # noqa: E402
    run_cli, run_cli_json, run_cli_ok, git, tree_fingerprint,
    unexpected_harness_artifacts,
)


def _write_payload(tmp_path, obj: dict, name: str) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def _manifest_cwd(manifest_text: str) -> Path:
    """Resolved `payload.cwd` of the last snap record in a manifest log.

    The JSON-encoded manifest escapes Windows backslashes, so comparing the
    decoded field (not the raw text) is the correct way to read the recorded
    project path.
    """
    rec = json.loads(manifest_text.strip().splitlines()[-1])
    return Path(rec["payload"]["cwd"]).resolve()


def test_case_a_ops_in_a_leave_b_pristine(tmp_path, two_projects, data_dir):
    proj_a, proj_b = two_projects
    b_before = tree_fingerprint(proj_b)

    exec_id = "pa-build-1"
    pa_abs = str(proj_a.resolve())
    pb_abs = str(proj_b.resolve())

    # -- harness writes, all in proj-a (project id from .harness-project)
    payload = _write_payload(tmp_path, {"x": 1}, "a-payload.json")
    run_cli_ok(data_dir, "checkpoint", "save", "--exec", exec_id,
               "--stage", "build", "--payload-file", str(payload),
               cwd=proj_a)
    snap = run_cli_json(data_dir, "snap", "save", "--cwd", str(proj_a),
                        "--exec", exec_id, "--note", "proj-a snapshot",
                        cwd=proj_a)
    assert snap["status"] == "ok"
    rc, out, err = run_cli(data_dir, "feedback", "record",
                           "--cause", "bad add", "--summary", "case A records",
                           cwd=proj_a)
    assert rc == 0, err

    # 1) the OTHER project is untouched: same bytes, no harness files,
    #    no snap refs in its repo.
    assert tree_fingerprint(proj_b) == b_before
    assert unexpected_harness_artifacts(proj_b) == []
    assert git(proj_b, "for-each-ref", "refs/harness").stdout == ""

    # 2) proj-a's snapshot manifest records proj-a's own path, never B's.
    manifest = (data_dir / "snaps" / f"{exec_id}.jsonl")
    text = manifest.read_text(encoding="utf-8")
    assert _manifest_cwd(text) == proj_a.resolve()   # recorded path is A
    assert _manifest_cwd(text) != proj_b.resolve()   # and not B
    assert pb_abs not in text and pb_abs.replace("\\", "/") not in text

    # 3) the snapshot git ref lives in proj-a, not proj-b.
    refs_a = git(proj_a, "for-each-ref", "refs/harness").stdout
    assert "refs/harness/snaps/" in refs_a

    # 4) checkpoint + feedback landed under the correct keys.
    cp_line = (data_dir / "checkpoints" / f"{exec_id}.jsonl").read_text(
        encoding="utf-8").strip().splitlines()[0]
    cp = json.loads(cp_line)
    assert cp["payload"] == {"x": 1}
    assert cp["execution_id"] == exec_id

    fb_lines = [ln for ln in (data_dir / "feedback.jsonl").read_text(
        encoding="utf-8").splitlines() if ln.strip()]
    fb = [json.loads(ln) for ln in fb_lines]
    assert any(r["project_id"] == "proj-a-id"
               and r["failure_cause"] == "bad add" for r in fb)

    # 5) proj-a path is not the identity of proj-b and vice versa.
    assert (proj_a / ".harness-project").read_text(encoding="utf-8").strip() \
        == "proj-a-id"
    assert (proj_b / ".harness-project").read_text(encoding="utf-8").strip() \
        == "proj-b-id"


def test_case_a_both_projects_keep_own_data_attributed(
        tmp_path, two_projects, data_dir):
    proj_a, proj_b = two_projects
    b_before = tree_fingerprint(proj_b)

    def _ops(root: Path, exec_id: str, payload: dict):
        p = _write_payload(tmp_path, payload, f"{exec_id}.json")
        run_cli_ok(data_dir, "checkpoint", "save", "--exec", exec_id,
                   "--stage", "s1", "--payload-file", str(p), cwd=root)
        snap = run_cli_json(data_dir, "snap", "save", "--cwd", str(root),
                            "--exec", exec_id, cwd=root)
        assert snap["status"] == "ok"
        run_cli_ok(data_dir, "feedback", "record",
                   "--cause", "only-" + root.name,   # proj-a / proj-b distinct
                   "--summary", "attribution", cwd=root)

    # A operates first (A's own snap save legitimately adds git objects/refs
    # to A's .git)...
    _ops(proj_a, "pa-001", {"proj": "a"})
    assert tree_fingerprint(proj_b) == b_before     # A never wrote to B
    a_after_a = tree_fingerprint(proj_a)            # baseline A leaves itself in
    a_manifest = (data_dir / "snaps" / "pa-001.jsonl").read_text(encoding="utf-8")

    # ...then B operates.
    _ops(proj_b, "pb-001", {"proj": "b"})
    assert tree_fingerprint(proj_a) == a_after_a    # B never rewrote A's repo
    b_manifest = (data_dir / "snaps" / "pb-001.jsonl").read_text(encoding="utf-8")

    # 1) no cross-referenced paths between manifests (recorded cwd is the
    #    project that owns the snapshot).
    assert _manifest_cwd(a_manifest) == proj_a.resolve()
    assert _manifest_cwd(b_manifest) == proj_b.resolve()

    # 2) each repo holds only its own refs.
    refs_a = git(proj_a, "for-each-ref", "refs/harness").stdout
    assert "refs/harness/snaps/pa-001/" in refs_a
    assert "pb-001" not in refs_a
    refs_b = git(proj_b, "for-each-ref", "refs/harness").stdout
    assert "refs/harness/snaps/pb-001/" in refs_b
    assert "pa-001" not in refs_b

    # 3) feedback is attributed per project, never mixed.
    rc, out, _ = run_cli(data_dir, "feedback", "query", "--project-id",
                         "proj-a-id", "--json", cwd=proj_a)
    assert rc == 0
    assert [r["failure_cause"] for r in json.loads(out)] == ["only-proj-a"]
    rc, out, _ = run_cli(data_dir, "feedback", "query", "--project-id",
                         "proj-b-id", "--json", cwd=proj_b)
    assert rc == 0
    assert [r["failure_cause"] for r in json.loads(out)] == ["only-proj-b"]

    # 4) checkpoint list surfaces both, each under its own exec id.
    rc, out, _ = run_cli(data_dir, "checkpoint", "list", cwd=proj_a)
    assert rc == 0
    execs = {row["execution_id"] for row in json.loads(out)}
    assert {"pa-001", "pb-001"} == execs
    assert (data_dir / "checkpoints" / "pb-001.jsonl").read_text(
        encoding="utf-8") != (data_dir / "checkpoints" / "pa-001.jsonl").read_text(
        encoding="utf-8")