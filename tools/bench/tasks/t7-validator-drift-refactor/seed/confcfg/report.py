"""Config report. The report path validates with the DRIFTED copy B."""
import json

from .validators_b import validate_report_config


def report_config(path) -> str:
    """Read a JSON config file and render a one-line health report.
    Invalid fields are reported, not raised."""
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    bad = validate_report_config(cfg)
    if bad:
        return "INVALID: " + ", ".join(bad)
    return "OK"
