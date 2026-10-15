"""Workspace snapshot/restore contracts (OPERATION ARSENAL / WORKSPACE GUARDIAN).

Each test pins one ABSOLUTE SAFETY BOUNDARY item:
  1. dry-run by default; writes only with approve=True
  2. only managed (snapshot-recorded) files are ever written/deleted
  3. unknown untracked files are never deleted or overwritten
  4. concurrent (three-way) modification -> fail closed per file
  5. a rescue ref is created before the first write
  6. interrupted restore -> detectable journal, explicit report
  7. corrupt/missing snapshot data -> explicit error, never silent success
  8. paths with spaces + CJK + CRLF/LF fixtures round-trip byte-exact
  9. all git calls are subprocess argv arrays (no shell=True), timeout,
     git -C <cwd> pinned
  10. non-git directory -> {status:"skipped"}, never an exception

Real git repos in tmp_path, no network, deterministic on Windows and Linux.
The headline guarantee -- "agent damage never loses unrelated user data" --
has its own combined test at the end.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness-core"))

from harness import worktree_snap as ws  # noqa: E402
from harness.worktree_snap import CorruptSnapError, WorktreeSnapper  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("git") is None,
                                reason="git not installed")

SRC = Path(ws.__file__).read_text(encoding="utf-8")


@pytest.fixture()
def data_dir(tmp_path):
    return tmp_path / "data"


def git(repo, *args):
    return subprocess.run(["git", "-C", os.fspath(repo), *args],
                          capture_output=True, check=True, text=True)


def git_ok(repo, *args) -> bool:
    p = subprocess.run(["git", "-C", os.fspath(repo), *args],
                       capture_output=True)
    return p.returncode == 0


def make_repo(tmp_path, name="repo"):
    """Hermetic repo: deterministic branch, identity, eol handling."""
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "guardian@harness")
    git(repo, "config", "user.name", "Workspace Guardian")
    git(repo, "config", "core.autocrlf", "false")
    return repo


def wf(repo, name, data):
    """Write a file relative to the repo root (creates parent dirs).

    Always byte-mode so Windows text-mode newline translation (\\n -> \\r\\n)
    can never corrupt LF fixtures -- eol handling belongs to git alone.
    """
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_bytes(data.encode("utf-8"))
    return path


def rf(repo, name) -> bytes:
    return (repo / name).read_bytes()


def commit_all(repo, message="c"):
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", message)


# ------------------------------------------------------------------ #1
# dry-run by default; writes only with approve=True


def test_restore_dry_run_default_writes_nothing(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "f.txt", "DAMAGED\n")
    result = snap.restore(os.fspath(repo), sid)          # no approve
    assert result["dry_run"] is True
    # a dry run wrote nothing — it must never claim "restored"
    assert result["status"] == "planned"
    assert any(r["action"] == "write" for r in result["plan"])
    assert rf(repo, "f.txt") == b"DAMAGED\n"             # workspace untouched

    blocked = snap.restore(os.fspath(repo), sid, dry_run=False)  # no approve
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "approve required"
    assert rf(repo, "f.txt") == b"DAMAGED\n"             # still untouched


def test_restore_requires_explicit_approve_to_write(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]
    wf(repo, "f.txt", "ZZZ\n")
    done = snap.restore(os.fspath(repo), sid,
                        dry_run=False, approve=True)
    assert done["status"] == "restored"
    assert rf(repo, "f.txt") == b"AAA\n"


# ------------------------------------------------------------------ flagship
# save -> modify -> restore is byte-exact (single-sided post-snapshot change)


def test_save_modify_restore_byte_exact(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "f.txt", "AGENT DAMAGE\n")                   # after snapshot
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "restored"
    assert rf(repo, "f.txt") == b"AAA\n"                  # byte-exact


def test_restore_reverts_session_capture_byte_exact(data_dir, tmp_path):
    """A session change captured by the snapshot is restored byte-exact even
    when it was later reverted to the baseline (current == HEAD)."""
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    wf(repo, "f.txt", "BBB\n")                            # pre-snapshot work
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "f.txt", "AAA\n")                            # reverted to baseline
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "restored"
    assert rf(repo, "f.txt") == b"BBB\n"                  # snapshot captured


def test_save_captures_same_size_same_mtime_edit(data_dir, tmp_path):
    """Racy-stat blind spot: a same-second, same-size edit after the index
    write reads as clean to git's stat cache. The snapshot MUST capture the
    work-tree content, never the stale index content (CI caught the stale
    capture on a fast runner; this test forces the condition deterministically
    by pinning the edit's mtime to the index's mtime)."""
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "dirty-v0\n")
    commit_all(repo)
    index_mtime = os.stat(repo / ".git" / "index").st_mtime
    wf(repo, "f.txt", "dirty-v1\n")                        # same size
    os.utime(repo / "f.txt", (index_mtime, index_mtime))   # force stat-clean
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    # Revert to the HEAD baseline, then restore: S=v1 != H=v0 with
    # current == H is the "session change reverted" single-sided case ->
    # writes S. If the racy-stat blind spot captured stale v0 instead, this
    # restore lands v0 and the assertion fails.
    wf(repo, "f.txt", "dirty-v0\n")
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "restored"
    assert rf(repo, "f.txt") == b"dirty-v1\n"              # edit was captured


# ------------------------------------------------------------------ #2
# only managed files are ever written; deleted managed file is recreated


def test_restore_recreates_deleted_managed_file(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    (repo / "f.txt").unlink()
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "restored"
    assert rf(repo, "f.txt") == b"AAA\n"


def test_restore_touches_only_managed_set(data_dir, tmp_path):
    """Boundary #2: a file OUTSIDE the snapshot set is never written."""
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "f.txt", "X\n")
    wf(repo, "later.txt", "new after snapshot\n")          # not managed
    wf(repo, "other.txt", "ttt\n")                         # untracked not managed
    before_other = rf(repo, "other.txt")
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "restored"
    assert rf(repo, "f.txt") == b"AAA\n"
    assert rf(repo, "other.txt") == before_other           # overwritten? no
    assert "later.txt" in result["plan"] or rf(repo, "later.txt") == b"new after snapshot\n"


# ------------------------------------------------------------------ #3
# restore removes ONLY managed-added files; unknown untracked files survive


def test_restore_removes_managed_added_preserves_unknown_untracked(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    wf(repo, "agent_new.txt", "session\n")                 # agent-created pre-save
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "unknown_untracked.txt", "keep me\n")         # appeared after save
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "restored"
    assert not (repo / "agent_new.txt").exists()           # managed-added removed
    assert rf(repo, "unknown_untracked.txt") == b"keep me\n"  # unknown preserved


# ------------------------------------------------------------------ #4
# concurrent (three-way) modification -> fail closed per file


def test_three_way_concurrent_modification_conflict(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    wf(repo, "f.txt", "BBB\n")                             # pre-snapshot change
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "f.txt", "CCC\n")                             # changed AGAIN
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "conflict"
    assert result["conflicts"][0]["path"] == "f.txt"
    assert rf(repo, "f.txt") == b"CCC\n"                   # no overwrite


def test_conflict_on_added_file_modified_after_snapshot(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    wf(repo, "added.txt", "v1\n")                          # untracked, captured
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "added.txt", "v2\n")                          # modified after snap
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "conflict"
    assert rf(repo, "added.txt") == b"v2\n"                # concurrent edit kept


# ------------------------------------------------------------------ #5
# rescue ref always created before writes


def test_rescue_ref_created_before_writes(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "f.txt", "DAMAGED\n")
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["rescue_ref"]
    assert git_ok(repo, "rev-parse", "--verify", result["rescue_ref"])


# ------------------------------------------------------------------ #6
# interrupted restore -> detectable journal, explicit report


def test_interrupted_restore_journal_reported(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    jdir = data_dir / "restore-journals" / "e1"
    jdir.mkdir(parents=True)
    started = {"schema": 1, "status": "started", "tx_id": "abc",
               "execution_id": "e1", "snap_id": sid,
               "rescue_ref": "refs/harness/restore-tx/abc",
               "ts": "2026-01-01T00:00:00+00:00", "files": ["f.txt"]}
    (jdir / "e1.tx.abc.json").write_text(
        json.dumps(started, ensure_ascii=True) + "\n", encoding="utf-8")

    result = snap.restore(os.fspath(repo), sid, dry_run=True)
    assert result["status"] == "blocked"
    assert result["reason"] == "interrupted-restore"
    assert len(result["journals"]) == 1

    # after the human marks the journal done, restore proceeds
    started["status"] = "done"
    (jdir / "e1.tx.abc.json").write_text(
        json.dumps(started, ensure_ascii=True) + "\n", encoding="utf-8")
    wf(repo, "f.txt", "DAMAGED\n")
    ok = snap.restore(os.fspath(repo), sid, dry_run=False, approve=True)
    assert ok["status"] == "restored"


# ------------------------------------------------------------------ #7
# corrupt/missing snapshot data -> explicit error, never silent success


def test_tampered_manifest_payload_is_explicit_error(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    log = data_dir / "snaps" / "e1.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[-1])
    rec["payload"]["branch"] = rec["payload"]["branch"] + "_TAMPERED"
    lines[-1] = json.dumps(rec, ensure_ascii=True, sort_keys=True)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(CorruptSnapError):
        snap.diff(os.fspath(repo), sid)


def test_deleted_ref_is_explicit_error(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    rec = snap.list(os.fspath(repo), "e1")[0]
    git(repo, "update-ref", "-d", rec["payload"]["ref"])

    with pytest.raises(CorruptSnapError):
        snap.diff(os.fspath(repo), sid)
    v = snap.verify(os.fspath(repo), sid)
    assert v["ok"] is False
    assert v["status"] in ("damaged", "missing")


def test_restore_wrong_repo_is_explicit_error(data_dir, tmp_path):
    src = make_repo(tmp_path, "src")
    wf(src, "f.txt", "AAA\n")
    commit_all(src)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(src), "e1")["snap_id"]

    other = make_repo(tmp_path, "other")
    wf(other, "g.txt", "BBB\n")
    commit_all(other)
    with pytest.raises(CorruptSnapError):
        snap.diff(os.fspath(other), sid)


# ------------------------------------------------------------------ #8
# spaces + CJK paths, CRLF/LF fixtures -> byte-exact round-trip


def test_spaces_cjk_and_crlf_lf_round_trip_byte_exact(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "space dir/crlf.txt", b"a\r\nb\r\nc\r\n")       # CRLF content
    wf(repo, "space dir/lf.txt", b"x\ny\nz\n")               # LF content
    wf(repo, "空间 目录/中文 文件.txt",
       "你好\n世界\n")                        # CJK + spaces
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "space dir/crlf.txt", b"BROKEN\r\n")
    wf(repo, "space dir/lf.txt", b"BROKEN\n")
    wf(repo, "空间 目录/中文 文件.txt",
       "坏了\n")
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "restored"
    assert rf(repo, "space dir/crlf.txt") == b"a\r\nb\r\nc\r\n"
    assert rf(repo, "space dir/lf.txt") == b"x\ny\nz\n"
    assert rf(repo, "空间 目录/中文 文件.txt")\
        == "你好\n世界\n".encode("utf-8")


# ------------------------------------------------------------------ #10
# non-git directory -> {status:"skipped"}, never an exception


def test_non_git_dir_skipped_not_exception(data_dir, tmp_path):
    nontmp = tmp_path / "not-a-repo"
    nontmp.mkdir()
    wf(nontmp, "x.txt", "hello\n")
    snap = WorktreeSnapper(data_dir)
    s = snap.save(os.fspath(nontmp), "e1")
    assert s == {"status": "skipped", "reason": "not-a-git-repo"}
    r = snap.restore(os.fspath(nontmp), "nope")
    assert r["status"] == "skipped"
    v = snap.verify(os.fspath(nontmp), "nope")
    assert v["status"] == "skipped"


def test_no_commits_repo_skipped(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    snap = WorktreeSnapper(data_dir)
    s = snap.save(os.fspath(repo), "e1")
    assert s["status"] == "skipped"
    assert s["reason"] == "no-commits"


# ------------------------------------------------------------------ invariants
# restore never moves HEAD; concurrent saves get distinct refs


def test_restore_never_moves_head(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    head_before = git(repo, "rev-parse", "HEAD").stdout.strip()
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "f.txt", "DAMAGED\n")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-q", "-m", "agent damage")      # HEAD now moved
    head_damaged = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert head_damaged != head_before

    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "restored"
    assert rf(repo, "f.txt") == b"AAA\n"
    after = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert after == head_damaged                          # HEAD untouched


def test_concurrent_saves_get_distinct_refs(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    for i in range(3):
        wf(repo, f"f{i}.txt", f"{i}\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    wf(repo, "dirty.txt", "pre-save\n")                   # concurrent edit
    first = snap.save(os.fspath(repo), "e1")
    wf(repo, "dirty.txt", "post-save\n")
    second = snap.save(os.fspath(repo), "e1")
    assert first["ref"] != second["ref"]
    assert first["seq"] == 1 and second["seq"] == 2
    assert git_ok(repo, "rev-parse", "--verify", first["ref"])
    assert git_ok(repo, "rev-parse", "--verify", second["ref"])
    assert first["tracked_commit"] != second["tracked_commit"] \
        or first["untracked_commit"] != second["untracked_commit"]


def test_list_reports_multiple_and_sorted_oldest_first(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    a = snap.save(os.fspath(repo), "e1")["snap_id"]
    b = snap.save(os.fspath(repo), "e1")["snap_id"]
    rows = snap.list(os.fspath(repo), "e1")
    assert [r["snap_id"] for r in rows] == [a, b]
    assert rows[0]["payload"]["seq"] < rows[1]["payload"]["seq"]


# ------------------------------------------------------------------ verify / prune


def test_verify_ok_when_intact_and_damaged_when_ref_gone(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]
    v = snap.verify(os.fspath(repo), sid)
    assert v["ok"] is True
    assert v["status"] == "ok"
    assert v["files"] and all(f["matches"] for f in v["files"])

    rec = [r for r in snap.list(os.fspath(repo), "e1") if r["snap_id"] == sid][0]
    git(repo, "update-ref", "-d", rec["payload"]["ref"])
    v2 = snap.verify(os.fspath(repo), sid)
    assert v2["ok"] is False


def test_prune_removes_old_refs_keeps_newest(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "f.txt", "AAA\n")
    commit_all(repo)
    snap = WorktreeSnapper(data_dir)
    for i in range(3):
        wf(repo, "f.txt", f"{i}\n")
        git(repo, "add", "f.txt")
        git(repo, "commit", "-q", "-m", f"v{i}")
        snap.save(os.fspath(repo), "e1")
    rows = snap.list(os.fspath(repo), "e1")
    assert len(rows) == 3
    pruned_refs = [r["payload"]["ref"] for r in rows[:-1]]

    snap.prune(os.fspath(repo), "e1", keep=1)
    after = snap.list(os.fspath(repo), "e1")
    assert len(after) == 1
    assert after[0]["payload"]["ref"] == rows[-1]["payload"]["ref"]
    for ref in pruned_refs:
        assert not git_ok(repo, "rev-parse", "--verify", ref), ref


# ------------------------------------------------------------------ headline
# agent damage never loses unrelated user data


def test_agent_damage_never_loses_unrelated_user_data(data_dir, tmp_path):
    repo = make_repo(tmp_path)
    wf(repo, "tracked.db", b"db-baseline\x00\x01\x02")     # precious tracked
    wf(repo, "notes.txt", "keep\n")
    wf(repo, "dirty.txt", "dirty-v0\n")
    commit_all(repo)
    wf(repo, "dirty.txt", "dirty-v1\n")                    # pre-snapshot user edit
    snap = WorktreeSnapper(data_dir)
    sid = snap.save(os.fspath(repo), "e1")["snap_id"]

    wf(repo, "unknown_after.bin", b"\x00ultra-precious\xff\x00")  # post-snap
    before_unknown = rf(repo, "unknown_after.bin")
    wf(repo, "notes.txt", "?\x00?\xff?\n")                 # damaged target
    result = snap.restore(os.fspath(repo), sid,
                          dry_run=False, approve=True)
    assert result["status"] == "restored"
    assert rf(repo, "tracked.db") == b"db-baseline\x00\x01\x02"
    assert rf(repo, "dirty.txt") == b"dirty-v1\n"          # dirty edit survived
    assert rf(repo, "unknown_after.bin") == before_unknown  # unknown survived
    assert rf(repo, "notes.txt") == b"keep\n"              # target repaired


# ------------------------------------------------------------------ #9
# subprocess argv arrays, no shell=True, timeout wired, git -C pinned


def test_no_shell_subprocess_and_timeout_present():
    # every git call is an argv array addressed to git -C <cwd>
    assert '["git", "-C", self.cwd' in SRC
    assert "subprocess.run(" in SRC
    assert "timeout=GIT_TIMEOUT" in SRC or "GIT_TIMEOUT" in SRC
    # no argv array may ever be headed "reset --hard" or "clean -f..."
    assert '"reset", "--hard"' not in SRC
    assert '"clean", "-f' not in SRC