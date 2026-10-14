"""Validation rules — copy B (used by the report path).

This copy DRIFTED from copy A during a hotfix:
  - port 0 is accepted "for compat with embedded mode"
  - relative paths are accepted (resolved against cwd)
  - reserved keys are NOT rejected
That hotfix was never reconciled with spec.md.
"""

RESERVED_KEYS = {"__meta__", "__comment__"}


class ReportValidationError(ValueError):
    pass


def _port_ok(port) -> bool:
    if not isinstance(port, int) or isinstance(port, bool):
        return False
    return 0 <= port <= 65535  # drift: 0 accepted


def _path_ok(path) -> bool:
    return isinstance(path, str) and len(path) > 0  # drift: relative accepted


def validate_report_config(cfg: dict) -> list[str]:
    """Like validate_config, but for the report path. Returns sorted bad
    field names. Raises ReportValidationError on type errors."""
    bad = []
    if not isinstance(cfg, dict):
        raise ReportValidationError("config must be a mapping")
    for section in ("server", "backup"):
        if section not in cfg:
            continue
        sub = cfg[section]
        if not isinstance(sub, dict):
            raise ReportValidationError(f"{section} must be a mapping")
        if "port" in sub and not _port_ok(sub["port"]):
            bad.append(f"{section}.port")
        if "path" in sub and not _path_ok(sub["path"]):
            bad.append(f"{section}.path")
    return sorted(bad)
