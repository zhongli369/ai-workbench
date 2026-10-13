"""Stable, privacy-friendly, migrateable project identity.

Precedence:
  1. CLI --project-id flag
  2. HARNESS_PROJECT_ID env
  3. `.harness-project` file at project root (self-declared, machine-independent)
  4. git-derived: normalized origin remote URL (credentials stripped), else first
     normalized remote sorted, prefixed `git:`
  5. path hash: `path:<sha1(realpath.casefold())[:16]>` (non-reversible, local-only)

The .harness-project file exists so a project can keep ONE id across machines and
across git remotes; failure-hash identity leaks nothing reversible.
"""
import hashlib
import os
import re
import subprocess
from pathlib import Path

_CONFIG_FILENAME = ".harness-project"
_CRED_RE = re.compile(r"^(?P<scheme>[a-z]+://)[^/@]*@", re.IGNORECASE)


def _norm_git_url(url: str) -> str:
    url = _CRED_RE.sub(r"\g<scheme>", url.strip())  # strip user:pass@
    url = url.removesuffix(".git")
    return url.lower()  # host case-insensitive; path sacrificed simplicity+stability


def _git_remote_urls(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "remote", "-v"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    urls: dict[str, str] = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            urls.setdefault(parts[0], parts[1])
    if "origin" in urls:
        return [urls["origin"]]
    return sorted(urls.values())


def _in_git(root: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return r.returncode == 0 and "true" in r.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def _path_hash(root: Path) -> str:
    key = str(Path(root).resolve()).casefold()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def resolve_project_id(
    cwd: Path | None = None,
    flag: str | None = None,
    env: str | None = None,
) -> tuple[str, str]:
    """Return (project_id, source). source in {flag, env, file, git, path}."""
    root = Path(cwd).resolve() if cwd else Path.cwd().resolve()
    if flag:
        return flag, "flag"
    if env:
        return env, "env"
    config = root / _CONFIG_FILENAME
    if config.is_file():
        declared = config.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        if declared:
            return declared, "file"
    if _in_git(root):
        urls = _git_remote_urls(root)
        if urls:
            return "git:" + _norm_git_url(urls[0]), "git"
        return "git:local:" + _path_hash(root), "git"
    return "path:" + _path_hash(root), "path"