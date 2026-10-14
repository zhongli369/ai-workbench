"""confcfg — tiny config loader/validator package."""
from .loader import load_config, dump_config
from .validators_a import validate_config

__all__ = ["load_config", "dump_config", "validate_config"]
__version__ = "1.4.0"
