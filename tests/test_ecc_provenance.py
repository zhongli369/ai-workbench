"""ECC snapshot provenance contracts (offline, CI-safe)."""
import json
import subprocess
import sys
from pathlib import Path

RC = Path(__file__).resolve().parent.parent
TOOL = RC / "tools" / "check_ecc_provenance.py"


def test_snapshot_matches_recorded_manifest():
    """Bundled skills/agents/commands must equal the RC-recorded hashes."""
    r = subprocess.run([sys.executable, str(TOOL)], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


def test_version_declares_traceable_pin():
    v = json.loads((RC / "vendor" / "ecc" / "VERSION").read_text(encoding="utf-8"))
    assert v["version"] == "2.0.0-rc.1"
    assert len(v["commit"]) == 40
    assert v["license"] == "MIT"
    assert (RC / "vendor" / "ecc" / "LICENSE").is_file()


def test_self_developed_skills_are_exactly_three():
    recorded = json.loads((RC / "vendor" / "ecc" / "MANIFEST.sha256").read_text(
        encoding="utf-8"))
    self_dev = [r for r in recorded if r.startswith("skills/") and
                r.split("/")[1] in {"experience-capture", "failure-oracle", "workbench"}]
    assert sorted(self_dev) == sorted([
        "skills/experience-capture/SKILL.md",
        "skills/failure-oracle/SKILL.md",
        "skills/workbench/SKILL.md"])
