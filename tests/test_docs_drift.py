"""Contracts for the docs drift gate (tools/check_docs_drift.py).

Positive contract: the real tree must pass (this is the README regression —
the gate's first live catch was 79-vs-85 contract drift). Negative contracts
run against synthetic tmp roots with source overrides so they never spawn
pytest subprocesses.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import check_docs_drift as gate  # noqa: E402
from cli_surface import extract_cli_surface, check_invocation  # noqa: E402


def _mkroot(tmp_path: Path, claims: dict, docs: dict[str, str]) -> Path:
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "claims.json").write_text(
        json.dumps(claims), encoding="utf-8")
    for rel, text in docs.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def _claims(**kw):
    base = {"numeric_claims": [], "figure_docs": [], "approved_figures": [],
            "cli_docs": [], "link_docs": [],
            "removed_features": {"docs": [], "strings": []}, "version": None}
    base.update(kw)
    return base


# ---- positive: real tree ---------------------------------------------------

def test_real_tree_has_no_drift():
    rep = gate.run(REPO)
    assert rep["ok"], "\n".join(rep["failures"])


def test_gate_is_not_vacuous():
    rep = gate.run(REPO)
    claims = json.loads((REPO / "docs" / "claims.json").read_text(encoding="utf-8"))
    assert len(claims["numeric_claims"]) >= 15
    assert len(claims["approved_figures"]) >= 15
    assert len(rep["checked"]) >= 10


# ---- numeric claims --------------------------------------------------------

def test_numeric_drift_detected(tmp_path):
    root = _mkroot(tmp_path, _claims(numeric_claims=[
        {"id": "c", "doc": "README.md", "regex": r"(\d+) offline contracts",
         "source": "pytest:all", "required": True}]),
        {"README.md": "There are 79 offline contracts."})
    rep = gate.run(root, source_overrides={"pytest:all": "85"})
    assert not rep["ok"]
    assert any("79" in f and "85" in f for f in rep["failures"])


def test_numeric_claim_passes_when_equal(tmp_path):
    root = _mkroot(tmp_path, _claims(numeric_claims=[
        {"id": "c", "doc": "README.md", "regex": r"(\d+) offline contracts",
         "source": "pytest:all", "required": True}]),
        {"README.md": "There are 85 offline contracts."})
    rep = gate.run(root, source_overrides={"pytest:all": "85"})
    assert rep["ok"], rep["failures"]


def test_missing_required_claim_fails(tmp_path):
    root = _mkroot(tmp_path, _claims(numeric_claims=[
        {"id": "c", "doc": "README.md", "regex": r"(\d+) offline contracts",
         "source": "pytest:all", "required": True}]),
        {"README.md": "no numbers here"})
    rep = gate.run(root, source_overrides={"pytest:all": "85"})
    assert not rep["ok"]
    assert any("not found" in f for f in rep["failures"])


def test_missing_optional_claim_is_info_not_fail(tmp_path):
    root = _mkroot(tmp_path, _claims(numeric_claims=[
        {"id": "c", "doc": "README.md", "regex": r"(\d+) offline contracts",
         "source": "pytest:all", "required": False}]),
        {"README.md": "no numbers here"})
    rep = gate.run(root, source_overrides={"pytest:all": "85"})
    assert rep["ok"]
    assert rep["infos"]


# ---- figures ---------------------------------------------------------------

def test_unwhitelisted_figure_fails(tmp_path):
    root = _mkroot(tmp_path, _claims(
        figure_docs=["README.md"], approved_figures=[]),
        {"README.md": "We measured a 3.50× speedup, trust us."})
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("3.50" in f and "whitelisted" in f for f in rep["failures"])


def test_approved_figure_without_qualifier_fails(tmp_path):
    root = _mkroot(tmp_path, _claims(
        figure_docs=["README.md"],
        approved_figures=[{"figure": "0.85", "qualifiers": ["N=1"]}]),
        {"README.md": "Fusion cost ratio 0.85× across the board.\n\nNext paragraph."})
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("qualifier" in f for f in rep["failures"])


def test_approved_figure_with_qualifier_in_block_passes(tmp_path):
    root = _mkroot(tmp_path, _claims(
        figure_docs=["README.md"],
        approved_figures=[{"figure": "0.85", "qualifiers": ["N=1"]}]),
        {"README.md": "Exploratory bench (N=1 per cell): ratio 0.85×.\n\nUnrelated text."})
    rep = gate.run(root)
    assert rep["ok"], rep["failures"]


def test_figure_wording_change_without_number_change_passes(tmp_path):
    """Wording edits that keep numbers+qualifiers must not trip the gate."""
    root = _mkroot(tmp_path, _claims(
        figure_docs=["README.md"],
        approved_figures=[{"figure": "1.22", "qualifiers": ["controlled"]}]),
        {"README.md": "Completely reworded sentence: controlled rerun 1.22×."})
    rep = gate.run(root)
    assert rep["ok"], rep["failures"]


# ---- documented CLI --------------------------------------------------------

def test_documented_invalid_command_fails(tmp_path):
    root = _mkroot(tmp_path, _claims(cli_docs=["README.md"]), {
        "README.md": "Run `python tools/workbench.py frobnicate --yes` now."})
    rep = gate.run(root, scripts_root=REPO)
    assert not rep["ok"]
    assert any("frobnicate" in f for f in rep["failures"])


def test_documented_invalid_flag_fails(tmp_path):
    root = _mkroot(tmp_path, _claims(cli_docs=["README.md"]), {
        "README.md": "Run `python tools/workbench.py doctor --definitely-not-a-flag`."})
    rep = gate.run(root, scripts_root=REPO)
    assert not rep["ok"]
    assert any("--definitely-not-a-flag" in f for f in rep["failures"])


def test_documented_valid_invocations_pass(tmp_path):
    root = _mkroot(tmp_path, _claims(cli_docs=["README.md"]), {
        "README.md": ("`python tools/workbench.py install --yes`\n\n"
                      "```\npython harness-core/harness/cli.py gate check \"git push origin main\"\n```")})
    rep = gate.run(root, scripts_root=REPO)
    assert rep["ok"], rep["failures"]


# ---- links / removed / version ----------------------------------------------

def test_dead_relative_link_fails(tmp_path):
    root = _mkroot(tmp_path, _claims(link_docs=["README.md"]), {
        "README.md": "See [the docs](docs/NOPE.md) and [ok](https://example.com/x)."})
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("NOPE.md" in f for f in rep["failures"])


def test_removed_feature_still_advertised_fails(tmp_path):
    root = _mkroot(tmp_path, _claims(removed_features={
        "docs": ["README.md"], "strings": ["auto-deploy"]}),
        {"README.md": "This product does auto-deploy on Fridays."})
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("auto-deploy" in f for f in rep["failures"])


def test_version_mismatch_fails(tmp_path):
    root = _mkroot(tmp_path, _claims(version={
        "source_file": "tools/workbench.py", "changelog": "CHANGELOG.md",
        "changelog_pattern": r"^## \[([^\]]+)\]"}),
        {"CHANGELOG.md": "# Changelog\n\n## [0.2.0] — today\n\nstuff\n"})
    rep = gate.run(root, source_overrides={"version:workbench": "0.1.0-preview.1"})
    assert not rep["ok"]
    assert any("0.2.0" in f for f in rep["failures"])


def test_version_match_passes(tmp_path):
    root = _mkroot(tmp_path, _claims(version={
        "source_file": "tools/workbench.py", "changelog": "CHANGELOG.md",
        "changelog_pattern": r"^## \[([^\]]+)\]"}),
        {"CHANGELOG.md": "# Changelog\n\n## [0.1.0-preview.1] — today\n\nstuff\n"})
    rep = gate.run(root, source_overrides={"version:workbench": "0.1.0-preview.1"})
    assert rep["ok"], rep["failures"]


# ---- cli_surface unit contracts ---------------------------------------------

def test_workbench_surface_contains_all_commands():
    surf = extract_cli_surface(REPO / "tools" / "workbench.py")
    for cmd in ["doctor", "install", "launch", "status", "capability",
                "uninstall", "benchmark"]:
        assert cmd in surf["commands"], cmd
    assert "--yes" in surf["commands"]["install"]["flags"]
    assert surf["commands"]["install"]["flags"]["--scope"]["choices"] == \
        ["standalone", "project", "user"]


def test_harness_surface_contains_nested_commands():
    surf = extract_cli_surface(REPO / "harness-core" / "harness" / "cli.py")
    for cmd in ["feedback record", "feedback query", "feedback stats",
                "report", "gate mode", "gate approve", "gate check", "telemetry"]:
        assert cmd in surf["commands"], cmd


def test_surface_without_subparsers_is_empty_not_silent(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("import argparse\np = argparse.ArgumentParser()\n"
                 "p.add_argument('--x')\n", encoding="utf-8")
    surf = extract_cli_surface(p)
    assert surf["commands"] == {}
    # run() must refuse to treat that as a valid documented CLI
    root = _mkroot(tmp_path, _claims(cli_docs=["README.md"]),
                   {"README.md": "`python tools/workbench.py doctor`"})
    (root / "tools").mkdir()
    (root / "harness-core" / "harness").mkdir(parents=True)
    (root / "tools" / "workbench.py").write_text(p.read_text(), encoding="utf-8")
    (root / "harness-core" / "harness" / "cli.py").write_text(
        p.read_text(), encoding="utf-8")
    rep = gate.run(root, scripts_root=root)
    assert not rep["ok"]
    assert any("no commands" in f for f in rep["failures"])


def test_check_invocation_positional_choices():
    surf = {"global_flags": {},
            "commands": {"capability": {"flags": {"--json": {"choices": None}},
                                        "positionals": {"cap_cmd": {"choices": ["list", "inspect"]}}}}}
    assert check_invocation(surf, ["capability", "list"]) == []
    assert check_invocation(surf, ["capability", "bogus"]) != []
