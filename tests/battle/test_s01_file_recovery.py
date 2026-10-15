"""BATTLE SCENARIO 1 — real-file accidental-deletion recovery.

Real git repo + real `snap save` + real damage (edit / delete / new
untracked) + dry-run restore (must write NOTHING) + authorized restore
(--apply) + per-file SHA-256 byte comparison. Covers:

  * tracked edit        -> byte-exact undo
  * tracked delete      -> byte-exact recreate
  * unknown untracked   -> NEVER deleted or overwritten
  * three-way conflict  -> fail closed, file untouched, exit 1
  * added-then-modified -> fail closed
  * head divergence     -> fail closed (head-diverged), exit 1
  * fast-forward HEAD   -> restore still allowed
  * interrupted restore -> blocked by journal, exit 1, diagnosable
  * unknown snap_id     -> exit 1, "not found", never silent
  * tampered ref        -> exit 1, "did not resolve", never silent
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from battle_util import (  # noqa: E402
    commit_all, git_repo, run_cli, run_cli_json, run_git, safe_id, sha256_file, write,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="git not installed")


def _start_repo(tmp_path):
    repo = git_repo(tmp_path / "repo")
    write(repo / "src" / "app.py", b"version one\n")
    write(repo / "src" / "util.py", b"def helper(): pass\n")
    write(repo / "README.md", b"# demo repo\n")
    write(repo / "data" / "untracked.dat", b"untracked payload\n")
    commit_all(repo, "baseline")
    # an untracked file PRESENT at snapshot time is "managed-added":
    # unchanged on restore it is removed (undo of a session addition), per the
    # module's documented semantics.
    write(repo / "agent_new.txt", b"session artifact\n")
    baseline = {}
    for name in ("src/app.py", "src/util.py", "README.md", "data/untracked.dat"):
        baseline["/".join(name.split("/"))] = sha256_file(repo / name)
    return repo, baseline


def test_s1_damage_undo_and_unknown_untracked_preserved(tmp_path):
    data = tmp_path / "data"
    repo, baseline = _start_repo(tmp_path)
    snap = run_cli_json(data, "snap", "save", "--cwd", str(repo),
                        "--exec", "battle-s01")
    assert snap["status"] == "ok"
    snap_id = snap["snap_id"]

    # ---- agent damage (ALL post-snapshot)
    write(repo / "src" / "app.py", b"version two (agent edited)\n")
    (repo / "src" / "util.py").unlink()
    new_untracked = write(repo / "notes" / "newfile.txt", b"brand new file\n")

    # ---- dry-run: computes the plan, writes NOTHING, exit 0
    rc, out, err = run_cli(data, "snap", "restore", snap_id, "--cwd", str(repo))
    assert rc == 0, err
    plan = json.loads(out)
    assert plan["status"] == "planned"
    assert plan["dry_run"] is True
    assert plan["conflicts"] == []
    acts = {r["path"]: r["action"] for r in plan["plan"]}
    assert acts["src/app.py"] == "write"
    assert acts["src/util.py"] == "write"
    assert acts["data/untracked.dat"] == "noop"     # untouched managed -> noop
    assert acts["README.md"] == "noop"
    assert acts.get("agent_new.txt") == "delete"    # unchanged managed-added
    assert "notes/newfile.txt" not in {r["path"] for r in plan["plan"]}
    # zero writes happened
    assert (repo / "src/app.py").read_bytes() == b"version two (agent edited)\n"
    assert not (repo / "src/util.py").exists()
    assert new_untracked.read_bytes() == b"brand new file\n"

    # ---- authorized restore
    rc, out, err = run_cli(data, "snap", "restore", snap_id, "--cwd",
                           str(repo), "--apply")
    assert rc == 0, out + err
    res = json.loads(out)
    assert res["status"] == "restored"
    assert res["rescue_ref"]

    # ---- byte-for-byte SHA-256 comparison
    for name, want in baseline.items():
        assert sha256_file(repo / name) == want, f"{name} not byte-exact"
    # unchanged managed-added file was removed (undo of session addition) --
    # its content is preserved in the snapshot + rescue ref, never lost
    assert not (repo / "agent_new.txt").exists()
    # unknown untracked file (created AFTER snapshot) is still there, untouched
    assert sha256_file(repo / "notes/newfile.txt") == \
        sha256_file(new_untracked)


def test_s1_three_way_conflict_fails_closed(tmp_path):
    data = tmp_path / "data"
    repo = git_repo(tmp_path / "repo")
    write(repo / "f.txt", b"v1\n")
    commit_all(repo)
    snap_a = run_cli_json(data, "snap", "save", "--cwd", str(repo),
                          "--exec", "e-conflict")["snap_id"]

    # session changes f to v2, snapshot captures it (S != H)
    write(repo / "f.txt", b"v2\n")
    snap_b = run_cli_json(data, "snap", "save", "--cwd", str(repo),
                          "--exec", "e-conflict")["snap_id"]

    # concurrent change moves f to v3 (differs from BOTH S and H)
    write(repo / "f.txt", b"v3\n")

    # restoring snap_b sees a three-way concurrent modification.
    # dry-run REPORTS the conflict and exits 1 (P2-1 fixed: the exit code now
    # distinguishes a clean plan from conflict/blocked, JSON has the detail).
    rc, out, err = run_cli(data, "snap", "restore", snap_b, "--cwd", str(repo))
    assert rc == 1, out + err
    r = json.loads(out)
    assert r["status"] == "conflict"
    assert any(c["path"] == "f.txt" and "three-way" in c.get("reason", "")
               for c in r["conflicts"]), json.dumps(r, indent=2)
    # fail closed: NOTHING was written
    assert (repo / "f.txt").read_bytes() == b"v3\n"
    # --apply path fail-closes with a REAL non-zero exit
    rc, out, err = run_cli(data, "snap", "restore", snap_b, "--cwd",
                           str(repo), "--apply")
    assert rc == 1
    assert json.loads(out)["status"] == "conflict"
    assert (repo / "f.txt").read_bytes() == b"v3\n"   # still untouched
    # restoring snap_a is single-sided (S == H) -> allowed, undoes to v1
    rc, out, err = run_cli(data, "snap", "restore", snap_a, "--cwd",
                           str(repo), "--apply")
    assert rc == 0, out + err
    assert (repo / "f.txt").read_bytes() == b"v1\n"


def test_s1_added_then_modified_conflicts(tmp_path):
    data = tmp_path / "data"
    repo = git_repo(tmp_path / "repo")
    write(repo / "base.txt", b"base\n")
    commit_all(repo)
    # untracked file captured in snapshot
    write(repo / "u.txt", b"added-a\n")
    snap = run_cli_json(data, "snap", "save", "--cwd", str(repo),
                        "--exec", "e-added")["snap_id"]
    # agent modifies the added file after the snapshot
    write(repo / "u.txt", b"added-b\n")
    rc, out, err = run_cli(data, "snap", "restore", snap, "--cwd", str(repo))
    assert rc == 1, out + err            # dry-run reports conflict, exit 1 (P2-1)
    r = json.loads(out)
    assert r["status"] == "conflict"
    assert r["conflicts"][0]["path"] == "u.txt"
    assert (repo / "u.txt").read_bytes() == b"added-b\n"   # untouched
    rc, out, err = run_cli(data, "snap", "restore", snap, "--cwd",
                           str(repo), "--apply")
    assert rc == 1, out                  # --apply fail-closes with exit 1
    assert (repo / "u.txt").read_bytes() == b"added-b\n"


def test_s1_head_divergence_fails_closed_but_fast_forward_allows(tmp_path):
    data = tmp_path / "data"

    # ---- divergent HEAD (amend) -> blocked
    repo = git_repo(tmp_path / "div")
    write(repo / "f.txt", b"v1\n")
    commit_all(repo, "c1")
    snap = run_cli_json(data, "snap", "save", "--cwd", str(repo),
                        "--exec", "e-head")["snap_id"]
    write(repo / "f.txt", b"wip\n")
    run_git(repo, "commit", "-q", "--amend", "-m", "amended")
    # dry-run: reports blocked and exits 1 (P2-1 fixed, same as conflict)
    rc, out, err = run_cli(data, "snap", "restore", snap, "--cwd", str(repo))
    assert rc == 1, out
    assert json.loads(out)["status"] == "blocked"
    # --apply fail-closes with a REAL non-zero exit
    rc, out, err = run_cli(data, "snap", "restore", snap, "--cwd",
                           str(repo), "--apply")
    assert rc == 1, out
    r = json.loads(out)
    assert r["status"] == "blocked" and r["reason"] == "head-diverged", out
    assert (repo / "f.txt").read_bytes() == b"wip\n"       # untouched

    # ---- fast-forward new commit -> restore still allowed
    repo2 = git_repo(tmp_path / "ff")
    write(repo2 / "f.txt", b"v1\n")
    commit_all(repo2)
    snap2 = run_cli_json(data, "snap", "save", "--cwd", str(repo2),
                         "--exec", "e-ff")["snap_id"]
    write(repo2 / "f.txt", b"agent broke it\n")
    commit_all(repo2, "next commit on top")
    rc, out, err = run_cli(data, "snap", "restore", snap2, "--cwd",
                           str(repo2), "--apply")
    assert rc == 0, out + err
    assert (repo2 / "f.txt").read_bytes() == b"v1\n"


def test_s1_interrupted_restore_journal_blocks_and_diagnoses(tmp_path):
    data = tmp_path / "data"
    repo = git_repo(tmp_path / "repo")
    write(repo / "f.txt", b"v1\n")
    commit_all(repo)
    snap = run_cli_json(data, "snap", "save", "--cwd", str(repo),
                        "--exec", "e-jrnl")["snap_id"]
    # simulate a crash mid-restore: a journal stuck in "started"
    sid = safe_id("e-jrnl")
    jdir = data / "restore-journals" / sid
    fake = {"schema": 1, "status": "started", "tx_id": "deadbeef",
            "execution_id": "e-jrnl", "snap_id": snap,
            "rescue_ref": "refs/harness/restore-tx/deadbeef",
            "files": ["f.txt"]}
    write(jdir / f"{sid}.tx.deadbeef.json", json.dumps(fake).encode())
    rc, out, err = run_cli(data, "snap", "restore", snap, "--cwd",
                           str(repo), "--apply")
    assert rc == 1, out
    r = json.loads(out)
    assert r["status"] == "blocked" and r["reason"] == "interrupted-restore"
    assert r["journals"], json.dumps(r, indent=2)
    assert (repo / "f.txt").read_bytes() == b"v1\n"        # no write happened


def test_s1_diagnosability_unknown_and_tampered(tmp_path):
    data = tmp_path / "data"
    repo = git_repo(tmp_path / "repo")
    write(repo / "f.txt", b"v1\n")
    commit_all(repo)
    snap = run_cli_json(data, "snap", "save", "--cwd", str(repo),
                        "--exec", "e-diag")["snap_id"]

    # unknown snap_id -> corrupt_snap + "not found", exit 1
    rc, out, err = run_cli(data, "snap", "restore", "snap-deadbeef",
                           "--cwd", str(repo))
    assert rc == 1, out
    r = json.loads(err or out)   # error routes to stderr
    assert r["error"] == "corrupt_snap"
    assert "not found" in r["detail"]

    # tampered ref -> explicit corrupt_snap, exit 1
    ref = f"refs/harness/snaps/{safe_id('e-diag')}/1"
    run_git(repo, "update-ref", "-d", ref)
    rc, out, err = run_cli(data, "snap", "restore", snap, "--cwd", str(repo))
    assert rc == 1, out
    r = json.loads(err or out)
    assert r["error"] == "corrupt_snap"
    assert "resolve" in r["detail"]
    # snap verify reports damaged, exit 1
    rc, out, err = run_cli(data, "snap", "verify", snap, "--cwd", str(repo))
    assert rc == 1, out
    assert json.loads(out)["ok"] is False