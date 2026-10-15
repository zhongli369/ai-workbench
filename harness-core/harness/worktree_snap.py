"""Workspace file snapshots: Git-backed snapshot/restore for one work tree.

Companion to state.py (task-state checkpoints). state.py tracks task STATE;
this module tracks workspace FILES. A snapshot is a Git commit object whose
first parent is the HEAD at save time, whose tree is the tracked work-tree
state (via a `git stash create`-style temporary index: the real index
copied, then `git update-index --add --remove -u`), and whose optional
second parent is a commit whose tree holds untracked-but-present files via
a persistent scratch index (data_dir/snap-index). The commit is pinned
under a GC-safe ref (refs/harness/snaps/<safe_execution_id>/<seq>) and
described by an append-only manifest in the harness data dir.

ABSOLUTE SAFETY BOUNDARY (the mission: agent damage never loses unrelated
user data):
  1. restore() defaults to dry_run=True -- writes only with approve=True.
  2. Only managed (snapshot-recorded) files are ever written or deleted.
  3. Unknown untracked files are NEVER deleted or overwritten.
  4. Concurrent-modification conflict -> fail closed (no write to that file).
  5. A rescue ref is always created before the first write.
  6. An interrupted restore leaves a journal that later restore() calls
     report explicitly and refuse to silently continue past.
  7. Corrupt/missing snapshot data -> explicit error, never silent success.
  8. Paths with spaces, CJK content, CRLF/LF fixtures round-trip byte-exact
     (NUL-terminated pathlists; argv arrays; git hash-object byte semantics).
  9. Every git call is an argv array (no shell=True), git -C <cwd> qualified
     (a hostile worktree cannot redirect GIT_DIR/GIT_WORK_TREE), pinned
     `-c core.ignorestat=false`, timeout set, non-zero exit -> GitError.
  10. A non-git directory -> {status: "skipped"} without raising.
This module NEVER issues `git reset --hard` or `git clean -fd` (a gated CLI
may admin them; this module never uses them as any code path); restore
rewrites only the recorded paths, one atomic os.replace each.

Hash semantics: every hash is the blob that `git` would store (`git
hash-object <path>` default), so comparing hash_then/hash_now is CRLF/LF
neutral wherever the repo declares normalization (.gitattributes).
Documented choice: snapshot hashes use the same command.

Zero LLM. Zero dependencies beyond stdlib. Deterministic except for
timestamps and the rescue-tx ref name (uuid); both are non-comparison.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
GIT_TIMEOUT = 60.0
SNAP_REF_PREFIX = "refs/harness/snaps"
RESCUE_REF_PREFIX = "refs/harness/restore-tx"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_MAX_GIT_ARGS = 40_000
_RESERVED_TYPES = "BCDMU?"  # collapse-status X/Y letters we never trust blindly


class GitError(Exception):
    """A git subprocess failed or returned a non-zero exit code."""


class CorruptSnapError(Exception):
    """Snapshot data exists but is unusable (manifest/ref/commit chain)."""


class SnapStoreError(Exception):
    """Manifest store cannot be read/written."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(execution_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", execution_id)
    return safe[:120] or "unnamed"


def payload_hash(payload: dict) -> str:
    """Deterministic sha256 over the payload (key-sorted, pure ASCII).
    Same discipline as state.payload_hash, reimplemented locally."""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def _is_git_worktree(cwd: str) -> bool:
    """True iff cwd is inside a git work tree (boundary #10)."""
    try:
        out = Git(cwd).run("rev-parse", "--is-inside-work-tree").strip()
        return out == "true"
    except GitError:
        return False


class Git:
    """argv-array git runner pinned to one work tree. No shell interpolation.

    Every invocation is `git -C <cwd>` qualified so a hostile work tree
    (committed GIT_DIR/GIT_WORK_TREE redirect) cannot redirect us, and every
    command is prefixed with `-c core.ignorestat=false` (we always resubmit
    pathspecs, so the stat cache must never be trusted). A non-zero exit
    raises GitError with stderr included -- corrupt/missing data never reads
    as silent success.
    """

    def __init__(self, cwd: str):
        self.cwd = os.path.abspath(cwd)

    def run(self, *argv: str, input_data: bytes | None = None,
            index: str | None = None) -> str:
        return self.run_bytes(*argv, input_data=input_data,
                              index=index).decode("utf-8", errors="replace")

    def run_bytes(self, *argv: str, input_data: bytes | None = None,
                  index: str | None = None) -> bytes:
        if not argv or not argv[0]:
            raise GitError("empty git argv")
        if len(argv) > _MAX_GIT_ARGS:
            raise GitError(f"git argv too large ({len(argv)} args)")
        cmd = ["git", "-C", self.cwd, "-c", "core.ignorestat=false"] + list(argv)
        env = None
        if index:
            index = os.path.abspath(index)
            parent_dir = os.path.dirname(index)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            env = dict(os.environ)
            env["GIT_INDEX_FILE"] = index
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=GIT_TIMEOUT,
                                  input=input_data, env=env)
        except FileNotFoundError as e:
            raise GitError("git executable not found") from e
        except subprocess.SubprocessError as e:
            raise GitError(f"git subprocess error: {e}") from e
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise GitError(f"git {' '.join(argv)} exit {proc.returncode}: {err}")
        return proc.stdout


# ---------------------------------------------------------------- plumbing


def _head_sha(git: Git) -> str | None:
    try:
        return git.run("rev-parse", "--verify", "HEAD^{commit}").strip()
    except GitError:
        return None


def _resolve_ref(git: Git, ref: str) -> str | None:
    try:
        return git.run("rev-parse", "--verify", ref).strip()
    except GitError:
        return None


def _commit_exists(git: Git, sha: str) -> bool:
    try:
        git.run("cat-file", "-e", sha + "^{commit}")
    except GitError:
        return False
    return True


def _branch(git: Git) -> str:
    try:
        return git.run("symbolic-ref", "--quiet", "--short", "HEAD").strip()
    except GitError:
        return ""


def _is_ancestor(git: Git, ancestor: str, descendant: str) -> bool:
    try:
        git.run("merge-base", "--is-ancestor", ancestor, descendant)
    except GitError:
        return False
    return True


def _ls_tree_recursive(git: Git, treeish: str) -> tuple[dict[str, str],
                                                        dict[str, str]]:
    """({path: blob_sha}, {path: mode}) for one treeish, NUL-terminated
    (paths with spaces and CJK round-trip). Subdirectory/unmerged/submodule
    entries are skipped: query format gives a 'tree'/'commit' type token for
    those, and only 'blob' lines are kept."""
    moves: dict[str, str] = {}
    modes: dict[str, str] = {}
    try:
        out = git.run_bytes("ls-tree", "-r", treeish, "-z")
    except GitError as e:
        raise CorruptSnapError(f"ls-tree {treeish} failed: {e}") from e
    for chunk in out.split(b"\0"):
        if not chunk:
            continue
        text = chunk.decode("utf-8", errors="replace")
        meta, sep, path = text.partition("\t")
        if not sep or not path:
            raise CorruptSnapError(f"unparseable ls-tree line: {text!r}")
        mode, typ, sha = meta.split(" ")
        if typ != "blob":
            continue
        moves[path] = sha
        modes[path] = mode
    return moves, modes


def _commit_parents(git: Git, commit: str) -> list[str]:
    try:
        out = git.run("cat-file", "-p", commit)
    except GitError as e:
        raise CorruptSnapError(f"cat-file -p {commit} failed: {e}") from e
    parents: list[str] = []
    for line in out.splitlines():
        if line.startswith("parent "):
            parents.append(line.split()[1].strip())
        elif line == "":
            break
    return parents


def _real_index_path(git: Git) -> str | None:
    try:
        return git.run("rev-parse", "--git-path", "index").strip() or None
    except GitError:
        return None


def _tracked_tree(git: Git, scratch: str) -> str:
    """Tracked work-tree state as a tree: the real index (which already
    holds staged additions) copied to a scratch index, then
    `git update-index --add --remove -u` applies every work-tree change to
    tracked paths (modifications, deletions, renames). `git stash create`
    builds the same intermediate index; we build it deterministically here.
    """
    real = _real_index_path(git)
    if real and os.path.isfile(real):
        shutil.copyfile(real, scratch)
    else:
        git.run("read-tree", "HEAD", index=scratch)
    git.run("add", "-u", index=scratch)
    return git.run("write-tree", index=scratch).strip()


def _read_untracked_files(git: Git) -> list[str]:
    """Untracked (non-ignored) file paths, NUL-terminated, individual files."""
    try:
        out = git.run_bytes("-c", "core.quotepath=false", "ls-files", "-z",
                            "--others", "--exclude-standard")
    except GitError as e:
        raise CorruptSnapError(f"ls-files --others failed: {e}") from e
    return [p for p in out.decode("utf-8", errors="replace").split("\0") if p]


def _untracked_tree(git: Git, scratch: str, untracked: list[str]) -> str | None:
    """Untracked-but-present files as a tree on the (persistent) scratch
    index, or None when there is nothing to add. Only files still present
    are added; a file that vanished since capture cannot fail the save."""
    present = [p for p in untracked if _on_disk(git, p)]
    if not present:
        return None
    git.run("read-tree", "--empty", index=scratch)
    for batch in _batched(present):
        git.run("add", "--", *batch, index=scratch)
    return git.run("write-tree", index=scratch).strip()


def _on_disk(git: Git, rel: str) -> bool:
    return os.path.lexists(os.path.join(git.cwd, rel.replace("/", os.sep)))


def _make_commit(git: Git, tree: str, parents: list[str], message: str) -> str:
    """Create (and write) a commit object; returns its SHA-1."""
    headers = [f"tree {tree}"]
    for p in parents:
        headers.append(f"parent {p}")
    headers += ["author Harness <harness@localhost> 0 +0000",
                "committer Harness <harness@localhost> 0 +0000"]
    payload = ("\n".join(headers) + "\n\n" + message + "\n").encode("utf-8")
    try:
        out = git.run_bytes("hash-object", "-t", "commit", "-w", "--stdin",
                            input_data=payload)
    except GitError as e:
        raise GitError(f"commit object failed: {e}") from e
    sha = out.decode("ascii").strip()
    if not _SHA_RE.fullmatch(sha):
        raise CorruptSnapError(f"commit object not a SHA-1: {sha!r}")
    if not _commit_exists(git, sha):
        raise CorruptSnapError(f"commit {sha} not readable after write")
    return sha


def _create_snapshot_commit(git: Git, head_sha: str, tracked_tree: str,
                            untracked_tree: str | None) -> str:
    """Snapshot commit: tree = tracked work-tree state; first parent = HEAD;
    optional second parent = a commit whose tree holds untracked files (the
    shape `git stash push -u` produces)."""
    if not _SHA_RE.fullmatch(head_sha) or not _commit_exists(git, head_sha):
        raise CorruptSnapError(f"HEAD not a usable commit: {head_sha!r}")
    parents = [head_sha]
    if untracked_tree:
        parents.append(_make_commit(git, untracked_tree, [],
                                    "harness untracked files"))
    return _make_commit(git, tracked_tree, parents,
                        "harness workspace snapshot\n"
                        "tracked work-tree = first parent\n"
                        "untracked files = second parent")


def _managed_files(git: Git, commit: str) -> tuple[dict[str, str],
                                                   dict[str, str],
                                                   set[str]]:
    """(files {path: blob_sha}, modes {path: mode}, untracked set) managed by
    a snapshot commit. Managed = files present in the commit tree
    (first/tracked side) plus files in the second parent (untracked side)."""
    snap_tree = git.run("rev-parse", f"{commit}^{{tree}}").strip()
    files, modes = _ls_tree_recursive(git, snap_tree)
    untracked: set[str] = set()
    parents = _commit_parents(git, commit)
    if len(parents) > 1:
        try:
            second = git.run("rev-parse", f"{parents[1]}^{{tree}}").strip()
            second_files, second_modes = _ls_tree_recursive(git, second)
            files.update(second_files)
            modes.update(second_modes)
            untracked = set(second_files)
        except GitError as e:
            raise CorruptSnapError("untracked parent not readable: "
                                   f"{e}") from e
    return files, modes, untracked


def _current_hash(git: Git, rel: str) -> str | None:
    """git hash-object of the work-tree file (None when missing)."""
    if not _on_disk(git, rel):
        return None
    try:
        return git.run("hash-object", "--", rel.replace("/", os.sep)).strip()
    except GitError:
        return None


def _batched(iterable: list[str], size: int = 500) -> list[list[str]]:
    return [iterable[i:i + size] for i in range(0, len(iterable), size)]


class WorktreeSnapper:
    """Git-backed workspace snapshot/restore for one data directory.

    Layout (data_dir):
      snaps/<safe_execution_id>.jsonl       — append-only manifest
      snap-index/<safe_execution_id>.idx    — persistent untracked scratch index
      restore-journals/<safe_execution_id>.tx.<txid>.json — restore txn journal
    Refs (in the repo): refs/harness/snaps/<exec>/<seq> and
    refs/harness/restore-tx/<txid>.
    """

    def __init__(self, data_dir: str | Path):
        self._data_dir = Path(data_dir)

    # -------------------------------------------------- data_dir paths

    def _snap_dir(self) -> Path:
        return self._data_dir / "snaps"

    def _snap_log(self, execution_id: str) -> Path:
        return self._snap_dir() / f"{_safe_id(execution_id)}.jsonl"

    def _scratch_index(self, execution_id: str) -> Path:
        return self._data_dir / "snap-index" / f"{_safe_id(execution_id)}.idx"

    def _journal_dir(self, execution_id: str) -> Path:
        return self._data_dir / "restore-journals" / _safe_id(execution_id)

    # -------------------------------------------------- manifest read

    def _read_manifest(self, execution_id: str) -> tuple[list[dict], dict]:
        """Tolerant parse of one manifest log. Returns (valid_records,
        health). Every anomaly is enumerated (state.py discipline): a torn
        last line is dropped and reported, a corrupt middle line or a hash
        failure surfaces, and a log that exists but has no usable record
        raises CorruptSnapError -- damage never reads as absence."""
        health = {"ok": True, "dropped_tail": 0, "corrupt_lines": [],
                  "hash_failures": [], "bad_schema_lines": []}
        path = self._snap_log(execution_id)
        if not path.is_file():
            return [], health
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as e:
            raise SnapStoreError(f"manifest unreadable: {e}") from e
        lines = text.split("\n")
        records: list[dict] = []
        n_lines = len([ln for ln in lines if ln.strip()])
        for i, ln in enumerate(lines):
            ln = ln.strip().rstrip("\r")
            if not ln:
                continue
            line_no = i + 1
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                if line_no == n_lines:
                    health["dropped_tail"] += 1
                    health["ok"] = False
                else:
                    health["corrupt_lines"].append(line_no)
                    health["ok"] = False
                continue
            if rec.get("schema") != SCHEMA_VERSION:
                health["bad_schema_lines"].append(line_no)
                health["ok"] = False
                continue
            if rec.get("payload_sha256") != payload_hash(rec.get("payload", {})):
                health["hash_failures"].append(line_no)
                health["ok"] = False
                continue
            records.append(rec)
        if not records and (health["corrupt_lines"] or health["hash_failures"]
                            or health["bad_schema_lines"]):
            raise CorruptSnapError(
                f"manifest for {execution_id!r} exists but every line is "
                f"unusable: {health}")
        return records, health

    def _append_manifest(self, execution_id: str, rec: dict) -> None:
        path = self._snap_log(execution_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=True) + "\n"
        assert line.isascii(), "manifest line must be pure ASCII"
        with open(path, "a", encoding="ascii", newline="\n") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def _find_entry(self, snap_id: str) -> dict:
        """Locate a manifest record by snap_id across all executions."""
        logs = self._snap_dir()
        if not logs.is_dir():
            raise CorruptSnapError(f"no manifest store in {logs}")
        for path in sorted(logs.glob("*.jsonl")):
            execution_id = path.stem
            records, _health = self._read_manifest(execution_id)
            for rec in records:
                if rec.get("snap_id") == snap_id:
                    return rec
        raise CorruptSnapError(f"snapshot {snap_id!r} not found in manifest store")

    # ---------------------------------------------------------------- save

    def save(self, cwd: str, execution_id: str, note: str = "") -> dict:
        """Snapshot the current work tree. Non-git -> skipped (never raises).

        Returns {"status": "ok", ...entry} or {"status": "skipped",
        "reason": ...}. Deterministic except snap_id/ts (non-comparison).
        """
        cwd = os.path.abspath(cwd)
        if not _is_git_worktree(cwd):
            return {"status": "skipped", "reason": "not-a-git-repo"}
        git = Git(cwd)
        head_sha = _head_sha(git)
        if head_sha is None:
            return {"status": "skipped", "reason": "no-commits",
                    "detail": "the work tree has no HEAD commit yet"}
        # collect manifest entries (health tolerated for reads)
        records, _health = self._read_manifest(execution_id)
        seq = (records[-1]["payload"]["seq"] + 1 if records else 1)
        scratch = self._scratch_index(execution_id)
        # a throwaway index for the tracked side
        fd, tmp_index = tempfile.mkstemp(suffix=".idx")
        os.close(fd)
        try:
            tracked_tree = _tracked_tree(git, tmp_index)
            untracked_files = _read_untracked_files(git)
            untracked_tree = _untracked_tree(git, str(scratch), untracked_files)
            commit = _create_snapshot_commit(git, head_sha, tracked_tree,
                                             untracked_tree)
        except GitError as e:
            raise SnapStoreError(f"snapshot capture failed: {e}") from e
        finally:
            try:
                os.unlink(tmp_index)
            except OSError:
                pass
        ref = f"{SNAP_REF_PREFIX}/{_safe_id(execution_id)}/{seq}"
        try:
            git.run("update-ref", ref, commit)
        except GitError as e:
            raise SnapStoreError(f"update-ref {ref} failed: {e}") from e
        files, _modes, _untracked = _managed_files(git, commit)
        payload = {
            "cwd": cwd,
            "branch": _branch(git),
            "head_sha": head_sha,
            "seq": seq,
            "ref": ref,
            "tracked_commit": commit,
            "untracked_commit": _commit_parents(git, commit)[1]
                if len(_commit_parents(git, commit)) > 1 else None,
            "file_count": len(files),
            "note": note[:500],
            "method": "index-synthesis+scratch-index",
        }
        rec = {"schema": SCHEMA_VERSION, "record": "snap",
               "snap_id": "snap-" + secrets.token_hex(8),
               "execution_id": _safe_id(execution_id),
               "ts": _now_iso(),
               "payload": payload,
               "payload_sha256": payload_hash(payload)}
        self._append_manifest(execution_id, rec)
        return {"status": "ok", "snap_id": rec["snap_id"],
                "ref": ref, "seq": seq, "tracked_commit": commit,
                "untracked_commit": payload["untracked_commit"],
                "file_count": payload["file_count"]}

    # ---------------------------------------------------------------- list

    def list(self, cwd: str, execution_id: str | None = None) -> list[dict]:
        """Manifest entries. All executions when execution_id is None."""
        del cwd  # the manifest store is the source of truth; cwd reserved
        if execution_id is not None:
            records, health = self._read_manifest(execution_id)
            out = [dict(r) for r in records]
            if not health["ok"]:
                out.append({"manifest_health": health})
            return out
        rows: list[dict] = []
        logs = self._snap_dir()
        if logs.is_dir():
            for path in sorted(logs.glob("*.jsonl")):
                try:
                    records, _health = self._read_manifest(path.stem)
                except CorruptSnapError as e:
                    rows.append({"execution_id": path.stem, "error": str(e)})
                    continue
                for r in records:
                    rows.append(r)
        return rows

    # ---------------------------------------------------------------- diff

    def diff(self, cwd: str, snap_id: str) -> dict:
        """Structured per-file delta of the snapshot vs the current work tree.

        Only changed files are listed; change is one of: modified / deleted
        / added-untracked-at-snap / missing-now. Hashes use git hash-object
        byte semantics (CRLF/LF neutral where the repo declares it).
        """
        cwd = os.path.abspath(cwd)
        if not _is_git_worktree(cwd):
            return {"status": "skipped", "reason": "not-a-git-repo"}
        git = Git(cwd)
        entry = self._find_entry(snap_id)
        commit = _resolve_ref(git, entry["payload"]["ref"])
        if commit != entry["payload"]["tracked_commit"]:
            raise CorruptSnapError(
                f"ref {entry['payload']['ref']} did not resolve to the "
                f"recorded commit (dangling or tampered)")
        files, _modes, untracked = _managed_files(git, commit)
        head_files, _head_modes = _ls_tree_recursive(
            git, entry["payload"]["head_sha"])
        changes: list[dict] = []
        for path, s_sha in sorted(files.items()):
            c_sha = _current_hash(git, path)
            in_head = path in head_files
            if path in untracked:
                change = ("missing-now" if c_sha is None
                          else "added-untracked-at-snap")
            elif in_head and c_sha is None:
                change = "deleted"
            elif in_head and c_sha != s_sha:
                change = "modified"
            else:
                continue
            changes.append({"path": path, "change": change,
                            "hash_then": s_sha, "hash_now": c_sha})
        return {"status": "ok", "snap_id": snap_id, "ref": entry["payload"]["ref"],
                "cwd": cwd, "changes": changes}

    # -------------------------------------------------------------- verify

    def verify(self, cwd: str, snap_id: str) -> dict:
        """Full integrity report: ref, commits, manifest chain, and whether
        every recorded file is hashable in the current work tree. Damaged
        data sets ok=False; callers map that to a non-zero exit.
        """
        cwd = os.path.abspath(cwd)
        if not _is_git_worktree(cwd):
            return {"status": "skipped", "reason": "not-a-git-repo"}
        git = Git(cwd)
        errors: list[str] = []
        try:
            entry = self._find_entry(snap_id)
        except CorruptSnapError as e:
            return {"status": "corrupt", "snap_id": snap_id, "ok": False,
                    "errors": [str(e)]}
        payload = entry["payload"]
        ref_commit = _resolve_ref(git, payload["ref"])
        if ref_commit != payload["tracked_commit"]:
            errors.append(
                f"ref {payload['ref']} expected {payload['tracked_commit']} "
                f"got {ref_commit}")
        if not _commit_exists(git, payload["tracked_commit"]):
            errors.append(f"tracked commit {payload['tracked_commit']} missing")
        if payload.get("untracked_commit") and not _commit_exists(
                git, payload["untracked_commit"]):
            errors.append(f"untracked commit {payload['untracked_commit']} missing")
        ok = not errors
        files_report: list[dict] = []
        if ref_commit == payload["tracked_commit"]:
            try:
                files, _modes, untracked = _managed_files(
                    git, payload["tracked_commit"])
                for path, s_sha in sorted(files.items()):
                    c_sha = _current_hash(git, path)
                    files_report.append({
                        "path": path, "in_snapshot": True,
                        "untracked_at_snap": path in untracked,
                        "present_now": c_sha is not None,
                        "hash_now": c_sha,
                        "matches": c_sha == s_sha,
                    })
            except CorruptSnapError as e:
                errors.append(f"file list unreadable: {e}")
                ok = False
        return {"status": "ok" if ok else "damaged", "snap_id": snap_id,
                "ok": ok, "ref": payload["ref"], "errors": errors,
                "files": files_report}

    # ------------------------------------------------------------- restore

    def restore(self, cwd: str, snap_id: str, *,
                dry_run: bool = True, approve: bool = False) -> dict:
        """Restore a snapshot's managed files. dry_run=True by default:
        compute and return the plan WITHOUT touching the workspace. An
        actual restore requires approve=True.

        Guards (fail closed — any failure => no writes, explicit reason):
          1. HEAD divergence: current HEAD != snapshot head AND histories
             diverged (merge-base --is-ancestor) -> refuse.
          2. Per-file concurrency (single-sided vs three-way): let S be the
             snapshot blob and H the pre-snapshot baseline (HEAD) blob.
             - current content == S -> noop (already matches).
             - current file missing -> write S (recreate a deleted file).
             - S == H (file was untouched at snapshot): the only change is
               post-snapshot (single-sided) -> write S. This is the flagship
               "undo agent damage to a file the agent had not touched".
             - S != H and current == H (session change reverted): write S.
             - S != H and current differs from BOTH S and H: both the
               snapshot and the worktree moved relative to baseline
               (three-way) -> concurrent modification -> conflict, the file
               is never written and no data is guessed away.
             - Added files (H unknown): deleted when still equal to S; any
               later modification of an added file -> conflict.
          3. Only the recorded managed set is touched; unknown untracked
             files are never deleted or overwritten.
        Before any write a rescue ref of the CURRENT state is created; a
        journal records the transaction and is marked done on completion.
        """
        cwd = os.path.abspath(cwd)
        if not _is_git_worktree(cwd):
            return {"status": "skipped", "reason": "not-a-git-repo"}
        git = Git(cwd)
        if not approve and not dry_run:
            return {"status": "blocked", "reason": "approve required"}
        entry = self._find_entry(snap_id)
        payload = entry["payload"]
        execution_id = entry["execution_id"]

        # ---- interrupted-restore journal (boundary #6)
        unfinished = self._unfinished_journals(execution_id)
        if unfinished:
            return {"status": "blocked", "reason": "interrupted-restore",
                    "detail": "a previous restore did not complete; its "
                              "rescue ref preserves the pre-restore state",
                    "journals": unfinished}

        # ---- HEAD divergence guard (guard #1)
        current_head = _head_sha(git)
        if current_head != payload["head_sha"]:
            if not _is_ancestor(git, payload["head_sha"], current_head):
                return {"status": "blocked", "reason": "head-diverged",
                        "snapshot_head": payload["head_sha"],
                        "current_head": current_head}

        # ---- resolve snapshot data (explicit errors, never silent)
        commit = _resolve_ref(git, payload["ref"])
        if commit != payload["tracked_commit"]:
            raise CorruptSnapError(
                f"ref {payload['ref']} did not resolve to recorded commit")
        files, modes, untracked = _managed_files(git, commit)
        head_files, _head_modes = _ls_tree_recursive(git,
                                                     payload["head_sha"])

        plan: list[dict] = []
        conflicts: list[dict] = []
        for path, s_sha in sorted(files.items()):
            c_sha = _current_hash(git, path)
            h_sha = head_files.get(path)
            row = {"path": path, "hash_then": s_sha, "hash_now": c_sha}
            if h_sha is None:
                # added by the session and captured in the snapshot
                if c_sha is None:
                    row["action"] = "noop"
                elif c_sha == s_sha:
                    row["action"] = "delete"
                else:
                    row["action"] = "conflict"
                    row["reason"] = "added file modified after snapshot"
            elif c_sha is None:
                row["action"] = "write"  # recreate a deleted managed file
            elif c_sha == s_sha:
                row["action"] = "noop"
            elif h_sha == s_sha or c_sha == h_sha:
                # single-sided: clean at snapshot (or reverted to baseline)
                # with only a post-snapshot change -> undo agent damage
                row["action"] = "write"
            else:
                # snapshot moved the file AND the worktree moved again:
                # three-way concurrent modification -> refuse to guess
                row["action"] = "conflict"
                row["reason"] = "three-way concurrent modification"
            if row["action"] == "conflict":
                conflicts.append(row)
            else:
                plan.append(row)

        plan_result = {
            # dry-run must never claim "restored" — nothing was written.
            # "planned" = the plan applies cleanly; "conflict" = fail closed.
            "status": "conflict" if conflicts else ("planned" if dry_run else "restored"),
            "snap_id": snap_id,
            "execution_id": execution_id,
            "ref": payload["ref"],
            "cwd": cwd,
            "conflicts": conflicts,
            "plan": plan,
        }
        if dry_run:
            plan_result["dry_run"] = True
            return plan_result

        # ---- approved execution: rescue ref + journal first
        tx_id = uuid.uuid4().hex
        rescue_ref = f"{RESCUE_REF_PREFIX}/{tx_id}"
        try:
            self._write_rescue(git, rescue_ref, execution_id, tx_id)
        except (GitError, CorruptSnapError) as e:
            raise SnapStoreError(f"rescue snapshot failed: {e}") from e
        journal = {
            "schema": SCHEMA_VERSION, "status": "started", "tx_id": tx_id,
            "execution_id": execution_id, "snap_id": snap_id,
            "rescue_ref": rescue_ref, "ts": _now_iso(),
            "files": [row["path"] for row in plan if row["action"] != "noop"],
        }
        self._write_journal(execution_id, journal)
        written: list[str] = []
        errors: list[str] = []
        write_paths = [row["path"] for row in plan
                       if row["action"] == "write"]
        delete_paths = [row["path"] for row in plan
                        if row["action"] == "delete"]
        completed = False
        try:
            if write_paths:
                self._materialize_index_restore(
                    git, str(self._scratch_index(execution_id)),
                    write_paths, files, modes)
                written.extend(write_paths)
            for del_path in delete_paths:
                full = os.path.join(git.cwd, del_path.replace("/", os.sep))
                os.unlink(full)
                written.append(del_path)
            completed = True
        except (GitError, OSError) as e:
            errors.append(str(e))
            return {"status": "blocked", "reason": "write-error",
                    "detail": "restore was interrupted; journal left in "
                              "started state, rescue ref preserves evidence",
                    "journal": journal, "rescue_ref": rescue_ref,
                    "written": written, "errors": errors}
        finally:
            if completed:
                journal["status"] = "done"
                self._write_journal(execution_id, journal)
        plan_result["status"] = "conflict" if conflicts else "restored"
        plan_result["written"] = written
        plan_result["rescue_ref"] = rescue_ref
        plan_result["tx_id"] = tx_id
        return plan_result

    def _write_rescue(self, git: Git, ref: str, execution_id: str,
                      tx_id: str) -> None:
        """Snapshot the CURRENT state under a guard value rescued ref."""
        fd, tmp_index = tempfile.mkstemp(suffix=".idx")
        os.close(fd)
        try:
            tracked_tree = _tracked_tree(git, tmp_index)
            untracked = _read_untracked_files(git)
            scratch = self._scratch_index("rescue-" + tx_id)
            untracked_tree = _untracked_tree(git, str(scratch), untracked)
            head = _head_sha(git)
            if head is None:
                head = tracked_tree  # no commits yet: tree as parent
            commit = _create_snapshot_commit(git, head, tracked_tree,
                                             untracked_tree)
        finally:
            try:
                os.unlink(tmp_index)
            except OSError:
                pass
        git.run("update-ref", ref, commit)

    # ------------------------------------------------- journal helpers

    def _unfinished_journals(self, execution_id: str) -> list[dict]:
        rows: list[dict] = []
        jdir = self._journal_dir(execution_id)
        if not jdir.is_dir():
            return rows
        for path in sorted(jdir.glob(f"{_safe_id(execution_id)}.tx.*.json")):
            try:
                journal = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                rows.append({"path": str(path), "unreadable": True})
                continue
            if journal.get("status") != "done":
                rows.append(journal)
        return rows

    def _write_journal(self, execution_id: str, journal: dict) -> None:
        jdir = self._journal_dir(execution_id)
        jdir.mkdir(parents=True, exist_ok=True)
        path = jdir / f"{_safe_id(execution_id)}.tx.{journal['tx_id']}.json"
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(journal, ensure_ascii=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except OSError as e:
            raise SnapStoreError(f"journal write failed: {e}") from e

    @staticmethod
    def _materialize_index_restore(git: Git, scratch: str,
                                   write_paths: list[str],
                                   files: dict[str, str],
                                   modes: dict[str, str]) -> None:
        """Restore ONLY the given managed paths from their recorded blobs,
        using git's own write path (checkout-index) so .gitattributes /
        autocrlf eol conversion is byte-for-byte what git checkout would
        produce. The scratch index is loaded via --index-info from the
        recorded (sha, mode) pairs -- no real-index mutation, no reset."""
        git.run("read-tree", "--empty", index=scratch)
        for batch in _batched(write_paths):
            lines = "".join(
                f"{modes.get(p, '100644')} {files[p]} 0\t{p}\n"
                for p in batch
            )
            git.run_bytes("update-index", "--index-info",
                          input_data=lines.encode("utf-8"), index=scratch)
        for path in write_paths:
            parent = os.path.dirname(os.path.join(git.cwd,
                                                  path.replace("/", os.sep)))
            if parent:
                os.makedirs(parent, exist_ok=True)
        git.run("checkout-index", "-f", "--", *write_paths, index=scratch)

    # --------------------------------------------------------------- prune

    def prune(self, cwd: str, execution_id: str, keep: int = 5) -> dict:
        """Delete oldest refs + manifest lines beyond the newest `keep`.
        Never prunes the newest. Requires a git work tree (refs live there).
        """
        cwd = os.path.abspath(cwd)
        if keep < 1:
            return {"status": "blocked", "reason": "keep must be >= 1"}
        if not _is_git_worktree(cwd):
            return {"status": "skipped", "reason": "not-a-git-repo"}
        git = Git(cwd)
        records, health = self._read_manifest(execution_id)
        if not records:
            return {"status": "ok", "removed": []}
        doomed = records[: max(0, len(records) - keep)]
        removed: list[dict] = []
        for rec in doomed:
            ref = rec.get("payload", {}).get("ref")
            if ref:
                try:
                    git.run("update-ref", "-d", ref)
                except GitError as e:
                    removed.append({"snap_id": rec["snap_id"],
                                    "ref": ref, "error": str(e)})
                    continue
            removed.append({"snap_id": rec["snap_id"], "ref": ref,
                            "removed": True})
        # rewrite the manifest WITHOUT the pruned lines (explicit admin op;
        # the only non-append-only path in this module)
        kept = records[len(doomed):]
        path = self._snap_log(execution_id)
        if kept:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="ascii", newline="\n") as f:
                for rec in kept:
                    f.write(json.dumps(rec, ensure_ascii=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
        else:
            try:
                path.unlink()
            except OSError:
                pass
        return {"status": "ok", "kept": len(kept), "removed": removed,
                "manifest_health": health}