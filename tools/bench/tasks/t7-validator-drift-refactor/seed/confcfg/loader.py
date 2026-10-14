"""Load/dump configs. The load path validates with copy A."""
import json

from .validators_a import validate_config, ConfigError

DEFAULTS = {
    "server": {"host": "127.0.0.1", "port": 8080},
    "backup": {"path": "/var/backups", "interval_hours": 24},
}


def load_config(path) -> dict:
    """Read a JSON config file, apply defaults for missing sections, and
    validate. Raises ConfigError if the merged result is invalid."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    cfg = {**DEFAULTS, **raw}
    bad = validate_config(cfg)
    if bad:
        raise ConfigError(f"invalid fields: {', '.join(bad)}")
    return cfg


def dump_config(cfg: dict, path) -> None:
    """Write a config dict as JSON (no validation — dumping is trusted)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, sort_keys=True)
