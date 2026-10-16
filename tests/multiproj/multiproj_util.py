"""Shared helpers for the multi-project workbench tests (tests/multiproj).

MODEL UNDER TEST — one AI Workbench workspace, many target projects:

  workbench install --target <wb>   ->  <wb>/harness-data  is the SHARED data
    dir for every harness CLI invocation under that workspace (wired by the
    installed .claude/settings.json `env.HARNESS_DATA_DIR`), plus the default
    gate.json (mode "audit"). Projects live OUTSIDE <wb> as normal git repos.

Real layering the tests pin down (verified against the code):
  * harness CLI data (checkpoints/verify/snap-manifests/feedback/telemetry/
    gate) all live in the DATA DIR, never inside a project dir.
  * the only project-side effects are git refs `refs/harness/**` (written by
    snap save/restore *into the repo that --cwd names*) and the *.harness*
    *operator-created* files (.harness-project / .harness-verify.json).
  * cross-project isolation therefore rests on three keys:
      - data_dir is shared (one workbench)      -> keyed per-execution_id and
        per-project_id,
      - git refs are per-repo                   -> --cwd targets the repo,
      - project identity (.harness-project)     -> per-project tagging.

Every CLI/hook/git invocation is a fresh subprocess (list-argv, no shell).
No network, no Claude Code, no global git config, nothing outside tmp_path.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS_CLI = REPO / "harness-core" / "harness" / "cli.py"
WORKBENCH_CLI = REPO / "tools" / "workbench.py"
GATE_HOOK = REPO / "hooks" / "harness_gate.py"

# replay-safe exec ids used across tests (see tests for detail)
EXEC_A = "pa-build-1"
EXEC_B = "pb-build-1"

# ---------------------------------------------------------------- env


def base_env() -> dict:
    """Hermetic env: caller's vars minus anything that would redirect state."""
    env = dict(os.environ)
    for key in ("HARNESS_DATA_DIR", "HARNESS_PROJECT_ID", "HARNESS_GATE_MODE",
                "HARNESS_GATE_TOKEN", "HARNESS_BENCH"):
        env.pop(key, None)
    return env


# ---------------------------------------------------------------- harness CLI


def run_cli(data_dir, *args, cwd=None, env_extra=None, timeout=180):
    """Run the REAL harness CLI. Returns (rc, stdout, stderr)."""
    env = base_env()
    env["HARNESS_DATA_DIR"] = str(data_dir)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(HARNESS_CLI), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(cwd) if cwd is not None else None, env=env, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_cli_ok(data_dir, *args, **kw):
    """run_cli asserting rc == 0. Returns (stdout, stderr)."""
    rc, out, err = run_cli(data_dir, *args, **kw)
    assert rc == 0, \
        f"cli {args} rc={rc}\n--- stdout ---\n{out}\n--- stderr ---\n{err}"
    return out, err


def run_cli_json(data_dir, *args, **kw):
    """run_cli asserting rc == 0 and stdout parses as JSON."""
    out, err = run_cli_ok(data_dir, *args, **kw)
    return json.loads(out)


# ---------------------------------------------------------------- gate hook


def run_hook(data_dir, payload, env_extra=None, timeout=60):
    """Feed one PreToolUse JSON payload to hooks/harness_gate.py."""
    env = base_env()
    env["HARNESS_DATA_DIR"] = str(data_dir)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(GATE_HOOK)], input=payload,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def bash_payload(command: str) -> str:
    return json.dumps({"tool_name": "Bash",
                       "tool_input": {"command": command}})


# ---------------------------------------------------------------- git


def git(repo, *args, check=True, timeout=180):
    """Hermetic git: local identity injected per-command (no global config)."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} exit {proc.returncode}: {proc.stderr}")
    return proc


# ---------------------------------------------------------------- files


def write_text(path: Path, text: str, *, newline="\n") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=newline)
    return path


def write_bytes(path: Path, data: bytes) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def tree_fingerprint(root) -> list[tuple[str, str]]:
    """Deterministic (relpath, sha256) list for a whole directory tree."""
    root = Path(root)
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        # git's own background maintenance (gc --auto, spawned by the fixture's
        # commits) holds transient *.lock files under .git/; they are not harness
        # writes and vanish on their own, so they must not affect bit-identity.
        if rel.startswith(".git/") and rel.endswith(".lock"):
            continue
        out.append((rel, hashlib.sha256(p.read_bytes()).hexdigest()))
    return out


# Operator-authored harness files every project MAY legitimately carry;
# anything else under a `.harness*` name is the leakage signal.
KNOWN_HARNESS_FILES = {".harness-project", ".harness-verify.json"}


def unexpected_harness_artifacts(root) -> list[str]:
    """`.harness*` files NOT authored by the operator (auto-created state).

    The harness CLI never fabricates project-local state of its own; when it
    does, that is exactly the cross-project leakage we must catch.
    """
    return sorted(p.name for p in Path(root).rglob(".harness*")
                  if p.name not in KNOWN_HARNESS_FILES)


# ---------------------------------------------------------------- fixtures' builders


def mk_project(root: Path, project_id: str, *, typehints: bool = True) -> Path:
    """A real git project with its own CLAUDE.md and .harness-project.

    proj-a and proj-b receive DELIBERATELY CONFLICTING rules (typehints
    required vs forbidden) so any cross-project rule bleed is caught.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if typehints:
        claude = (
            f"# {project_id} 项目\n\n"
            "## 规则（必须遵守）\n"
            "- 所有函数必须带 type hints。\n"
            "- 矛盾声明：type hints 强制。\n\n"
            "## 测试\n"
            "python -m pytest tests/ -q\n"
        )
        calc = "def add(a: int, b: int) -> int:\n    return a + b\n"
    else:
        claude = (
            f"# {project_id} 项目\n\n"
            "## 规则（必须遵守）\n"
            "- 禁止 type hints，保持鸭子类型。\n"
            "- 矛盾声明：type hints 禁止。\n\n"
            "## 测试\n"
            "python -m pytest tests/ -q\n"
        )
        calc = "def add(a, b):\n    return a + b\n"
    write_text(root / "CLAUDE.md", claude)
    write_text(root / "src" / "calc.py", calc)
    write_text(root / "tests" / "test_calc.py",
               "import sys\n"
               "from pathlib import Path\n"
               "sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))\n"
               "from calc import add\n\n"
               "def test_add():\n"
               "    assert add(1, 2) == 3\n")
    write_text(root / ".harness-project", project_id + "\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "core.autocrlf", "false")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"init: {project_id}")
    return root


def mk_plain_project(root: Path) -> Path:
    """An ordinary project with NO workbench/harness installed."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    write_text(root / "CLAUDE.md",
               "# 普通项目\n\n无 workbench、无 hooks、无 harness。\n")
    write_text(root / "src" / "calc.py",
               "def sub(a, b):\n    return a - b\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "core.autocrlf", "false")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init: plain")
    return root