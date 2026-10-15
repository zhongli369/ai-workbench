"""CASE C — snap/verify 作用域 (workspace snapshot & verification stay in A).

  * snap save captures proj-a's working tree into proj-a's git refs +
    shared manifest; proj-b untouched throughout.
  * a three-way corrupt edit fails closed (dry-run reports conflict, exit 1);
    a single-sided revert is restored by `snap restore --apply` (rescue ref
    + done journal), still with proj-b untouched.
  * `verify run --stage X --cwd proj-a` writes evidence into the shared
    data dir only; proj-b gains no .harness-verify file and no bytes change.
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


def test_case_c_snap_restore_scoped_to_a(tmp_path, two_projects, data_dir):
    proj_a, proj_b = two_projects
    b_before = tree_fingerprint(proj_b)

    calc = proj_a / "src" / "calc.py"
    original = calc.read_text(encoding="utf-8")          # HEAD baseline
    mid = original + "# work in progress\n"              # agent's mid-edit
    calc.write_text(mid, encoding="utf-8", newline="\n")

    # -- snapshot the mid-edit state
    snap = run_cli_json(data_dir, "snap", "save", "--cwd", str(proj_a),
                        "--exec", "pa-c1", "--note", "case C", cwd=proj_a)
    assert snap["status"] == "ok"
    snap_id = snap["snap_id"]
    assert tree_fingerprint(proj_b) == b_before

    # -- three-way corrupt edit: fail closed, nothing written.
    calc.write_text("CORRUPTED-BYTES!\n", encoding="utf-8", newline="\n")
    rc, out, err = run_cli(data_dir, "snap", "restore", snap_id,
                           "--cwd", str(proj_a), cwd=proj_a)
    assert rc == 1, err + out
    plan = json.loads(out)
    assert plan["status"] == "conflict"
    assert calc.read_text(encoding="utf-8") == "CORRUPTED-BYTES!\n"
    assert tree_fingerprint(proj_b) == b_before

    # -- single-sided revert to baseline: restore writes the snapshot state.
    calc.write_text(original, encoding="utf-8", newline="\n")
    rc, out, err = run_cli(data_dir, "snap", "restore", snap_id,
                           "--cwd", str(proj_a), "--apply", cwd=proj_a)
    assert rc == 0, err + out
    res = json.loads(out)
    assert res["status"] == "restored"
    assert calc.read_text(encoding="utf-8") == mid
    assert tree_fingerprint(proj_b) == b_before
    assert unexpected_harness_artifacts(proj_b) == []

    # -- safety artifacts: rescue ref + done journal live in A / data dir.
    refs = git(proj_a, "for-each-ref", "refs/harness").stdout
    assert "refs/harness/restore-tx/" in refs
    journals = list((data_dir / "restore-journals" / "pa-c1").glob("*.tx.*.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["status"] == "done"
    # no junk refs in proj-b
    assert git(proj_b, "for-each-ref", "refs/harness").stdout == ""

    # -- readers on the snapshot are consistent.
    verify_r = run_cli_json(data_dir, "snap", "verify", snap_id,
                            "--cwd", str(proj_a), cwd=proj_a)
    assert verify_r["ok"] is True
    diff_r = run_cli_json(data_dir, "snap", "diff", snap_id,
                          "--cwd", str(proj_a), cwd=proj_a)
    assert diff_r["status"] == "ok"


def test_case_c_verify_state_stays_in_a_and_data_dir(
        tmp_path, two_projects, data_dir):
    proj_a, proj_b = two_projects
    b_before = tree_fingerprint(proj_b)

    cfg = {"commands": [[str(sys.executable), "-c", "import sys; sys.exit(0)"]],
           "timeout_s": 60}
    (proj_a / ".harness-verify.json").write_text(
        json.dumps(cfg), encoding="utf-8")

    rc, out, err = run_cli(data_dir, "verify", "run", "--exec", "pa-v1",
                           "--stage", "build", "--cwd", str(proj_a),
                           cwd=proj_a)
    assert rc == 0, err + out
    res = json.loads(out)
    assert res["status"] == "pass"
    assert res["can_claim_done"] is True

    # evidence + checkpoint landed in the shared data dir under exec id.
    assert (data_dir / "verify" / "pa-v1.jsonl").is_file()
    cp_text = (data_dir / "checkpoints" / "pa-v1.jsonl").read_text(encoding="utf-8")
    assert '"status": "done"' in cp_text
    assert '{"verify": "ok"}' in cp_text

    # proj-b: no config, no bytes, nothing to claim.
    assert not (proj_b / ".harness-verify.json").exists()
    assert tree_fingerprint(proj_b) == b_before

    # proj-a: only the operator-created identity + config files (never
    # auto-created harness files beyond what the session operator wrote).
    assert unexpected_harness_artifacts(proj_a) == []
    assert (proj_a / ".harness-verify.json").is_file()
    assert git(proj_b, "for-each-ref", "refs/harness").stdout == ""

    # verify status is a reader and reports can_claim_done still true.
    rc, out, _ = run_cli(data_dir, "verify", "status", "--exec", "pa-v1",
                         cwd=proj_a)
    assert rc == 0 and json.loads(out)["can_claim_done"] is True