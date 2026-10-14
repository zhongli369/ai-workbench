"""Validation rules — copy A (used by the load/normalize path).

This is the OLDER copy. It enforces strict ports and absolute paths.
"""
from pathlib import PurePath

RESERVED_KEYS = {"__meta__", "__comment__"}


class ConfigError(ValueError):
    pass


def _check_port(port):
    if not isinstance(port, int) or isinstance(port, bool):
        raise ConfigError(f"port must be an int, got {type(port).__name__}")
    if not (1 <= port <= 65535):
        raise ConfigError(f"port out of range: {port}")


def _check_path(path):
    if not isinstance(path, str) or not path:
        raise ConfigError("path must be a non-empty string")
    if not PurePath(path).is_absolute():
        raise ConfigError(f"path must be absolute: {path!r}")


def validate_config(cfg: dict) -> list[str]:
    """Validate a config dict. Returns a sorted list of field names that
    failed validation (empty = valid). Raises ConfigError on type errors."""
    bad = []
    if not isinstance(cfg, dict):
        raise ConfigError("config must be a mapping")
    for key in RESERVED_KEYS & set(cfg):
        bad.append(key)
    for section in ("server", "backup"):
        if section not in cfg:
            continue
        sub = cfg[section]
        if not isinstance(sub, dict):
            raise ConfigError(f"{section} must be a mapping")
        if "port" in sub:
            try:
                _check_port(sub["port"])
            except ConfigError:
                bad.append(f"{section}.port")
        if "path" in sub:
            try:
                _check_path(sub["path"])
            except ConfigError:
                bad.append(f"{section}.path")
    return sorted(bad)
