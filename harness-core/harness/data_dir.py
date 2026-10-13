"""Resolve the harness data directory.

Precedence: --data-dir flag > HARNESS_DATA_DIR env > platform default.
Defaults: Windows %LOCALAPPDATA%\\harness, POSIX $XDG_DATA_HOME/harness or ~/.local/share/harness.
"""
import os
from pathlib import Path


def default_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "harness" if base else Path.home() / ".local" / "share" / "harness"
    base = os.environ.get("XDG_DATA_HOME")
    return Path(base) / "harness" if base else Path.home() / ".local" / "share" / "harness"


def resolve_data_dir(flag: str | None = None, env: str | None = None) -> Path:
    """flag wins over env wins over default. Never None."""
    if flag:
        return Path(flag).expanduser()
    if env:
        return Path(env).expanduser()
    return default_data_dir()