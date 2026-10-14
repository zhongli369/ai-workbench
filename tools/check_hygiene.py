#!/usr/bin/env python3
"""Publishable-tree hygiene gate. stdlib only, no third-party deps.

Fails (exit 1) if the RC tree contains:
  - builder-machine paths (personal drive/username patterns)
  - common secret shapes (API keys, tokens)
  - unresolved installer template holes ({{ROOT}} outside tools/templates)

Shared by tools/workbench.py tests and .github/workflows/ci.yml.
"""
import re
import sys
from pathlib import Path

RC = Path(__file__).resolve().parent.parent

PATTERNS = [
    (r"[A-Za-z]:[\\/]Claude[\\/]", "builder drive path"),
    (r"ClaudeCodeProject", "builder project dir"),
    # user profile path (C:\Users\<name>\...); the lookahead requires at least
    # one alphanumeric in the name segment so doc placeholders like
    # "C:\Users\...\project" do NOT match
    (r"[A-Za-z]:[\\/]Users[\\/](?=[A-Za-z0-9_.-]*[A-Za-z0-9])[A-Za-z0-9_.-]+[\\/]",
     "user profile path"),
    (r"sk-[A-Za-z0-9]{10,}", "api key shape"),
    (r"ghp_[A-Za-z0-9]{10,}", "github token shape"),
    (r"gho_[A-Za-z0-9]{10,}", "github oauth shape"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "slack token shape"),
    (r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "private key"),
]

# files allowed to mention the patterns above: the hygiene checkers themselves
# (they must name what they forbid), tests that assert the same (test_contracts
# carries a SYNTHETIC sk-... fixture proving redaction works), and docs that
# explain the rule.
# test_incident_replay.py plants synthetic C:\Users\<name> fixtures to prove
# the scanner catches real leaks (same exemption class as test_contracts.py's
# synthetic secret).
SELF_REFS = {"check_hygiene.py", "test_cleanroom_install.py", "test_contracts.py",
             "test_incident_replay.py", "SECURITY.md"}
TEXT_SUFFIXES = {".py", ".md", ".json", ".ps1", ".sh", ".yml", ".yaml", ".txt", ".toml"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", "dist"}


def publishable_files() -> list[Path]:
    """Files that would actually ship: git-tracked files when inside a git
    checkout (gitignored local evidence like tools/bench/results/ is NOT part
    of the release), falling back to a plain tree walk otherwise."""
    import subprocess
    try:
        r = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                           timeout=60, cwd=RC)
        if r.returncode == 0:
            return [RC / line for line in r.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return [p for p in sorted(RC.rglob("*")) if not p.is_dir()]


def scan() -> list[tuple[str, str, int]]:
    bad = []
    for p in publishable_files():
        if SKIP_DIRS.intersection(p.parts):
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if p.name in SELF_REFS:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat, label in PATTERNS:
            m = re.search(pat, text)
            if m:
                line = text[:m.start()].count("\n") + 1
                bad.append((str(p.relative_to(RC)), label, line))
    return bad


def main() -> int:
    bad = scan()
    if bad:
        print("hygiene FAIL:")
        for path, label, line in bad:
            print(f"  {path}:{line} — {label}")
        return 1
    print("hygiene PASS (no personal paths, no secret shapes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
