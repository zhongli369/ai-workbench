"""Shared helpers for the battle tests (tests/battle).

Battle tests exercise the REAL harness CLI end-to-end: real filesystem,
real git repos, real subprocesses, real exit codes. They complement (never
duplicate) the harness-core unit contracts.

Every CLI invocation is a fresh subprocess of
`python harness-core/harness/cli.py <args>` with an isolated HARNESS_DATA_DIR
so test data never leaks into the user's ~/.local/share/harness (or
%LOCALAPPDATA%\\harness on Windows).

Constraints honoured here:
  * only files under the test's own tmp_path / data dir are ever touched;
  * git runs are argv-array subprocesses (no shell);
  * all file writes are BYTE-mode so eol translation never corrupts fixtures.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "harness-core" / "harness" / "cli.py"

_PROJECT_ID = "battle-test"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_cli(data_dir, *args, cwd=None, project_id=_PROJECT_ID,
            env_extra=None, timeout=180):
    """Run the real harness CLI as a subprocess. Returns (rc, stdout, stderr)."""
    env = dict(os.environ)
    env["HARNESS_DATA_DIR"] = str(data_dir)
    env["HARNESS_PROJECT_ID"] = project_id
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(cwd) if cwd else None, env=env, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_cli_json(data_dir, *args, cwd=None, **kw):
    """run_cli that asserts rc==0 and returns the parsed stdout JSON."""
    rc, out, err = run_cli(data_dir, *args, cwd=cwd, **kw)
    assert rc == 0, f"cli {args} rc={rc}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
    return json.loads(out)


def run_git(cwd, *args, check=True, timeout=120):
    proc = subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {args} exit {proc.returncode}: {proc.stderr}")
    return proc


def git_repo(directory, *, autocrlf=False):
    """Hermetic repo: deterministic branch, identity, eol handling."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    run_git(root, "init", "-q", "-b", "main")
    run_git(root, "config", "user.email", "battle@harness")
    run_git(root, "config", "user.name", "Battle Tester")
    run_git(root, "config", "core.autocrlf", "true" if autocrlf else "false")
    return root


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def commit_all(repo: Path, message: str = "c") -> None:
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)


def safe_id(execution_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", execution_id)
    return safe[:120] or "unnamed"


def snapshot_paths(repo: Path, ref: str) -> list[str]:
    """Files (paths) in a snapshot ref's tree, first + untracked parents."""
    out = run_git(repo, "ls-tree", "-r", ref).stdout
    paths = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 2:
            paths.append(parts[1])
    return paths