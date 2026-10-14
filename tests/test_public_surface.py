"""Frozen public surface contracts (P1.2).

Positive: the real tree matches docs/surface.json. Negatives exercise the
superset rule on synthetic surfaces — additive is free, removal/retype/
choice-shrink is breaking. The 7-vs-8 lesson is encoded as: every count in
this file is computed from the frozen document itself, never hand-written.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import check_public_surface as cps  # noqa: E402


@pytest.fixture(scope="module")
def frozen():
    return json.loads((REPO / "docs" / "surface.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def current():
    return cps.current_surface(REPO)


def _mini_surface():
    cli = {"global_flags": {"--verbose": {"choices": None}},
           "commands": {
               "install": {"flags": {"--scope": {"choices": ["a", "b"]},
                                     "--force": {"choices": None}},
                           "positionals": {}}}}
    return {"cli": {"x.py": cli},
            "jsonl_schemas": {"fb.jsonl:record": {"ts": "str", "cause": "str"}},
            "settings_template": {"top_level_keys": ["env"], "env_keys": ["X"],
                                  "pre_tool_use_matchers": ["Bash"]}}


# ---- positive -----------------------------------------------------------------

def test_real_tree_matches_frozen_surface(frozen, current):
    rep = cps.compare(frozen, current)
    assert rep["ok"], "\n".join(rep["breaking"])


def test_frozen_surface_is_not_vacuous(frozen):
    n_commands = sum(len(s["commands"]) for s in frozen["cli"].values())
    n_flags = sum(len(c["flags"]) for s in frozen["cli"].values()
                  for c in s["commands"].values())
    assert len(frozen["cli"]) == 2
    assert n_commands >= 15
    assert n_flags >= 30
    assert len(frozen["jsonl_schemas"]) >= 6
    assert len(frozen["jsonl_schemas"]["feedback.jsonl:record"]) >= 8
    # 7-vs-8 rule: these counts were computed from the document, not written
    # into the document — surface.json itself must carry no count fields
    assert "counts" not in json.dumps(frozen)


def test_emit_is_deterministic(current):
    a = cps.emit(current)
    b = cps.emit(current)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# ---- superset rule: CLI ---------------------------------------------------------

def test_command_removal_is_breaking():
    cur = _mini_surface()
    del cur["cli"]["x.py"]["commands"]["install"]
    rep = cps.compare(_mini_surface(), cur)
    assert not rep["ok"] and any("command removed: install" in b for b in rep["breaking"])


def test_flag_removal_is_breaking():
    cur = _mini_surface()
    del cur["cli"]["x.py"]["commands"]["install"]["flags"]["--force"]
    rep = cps.compare(_mini_surface(), cur)
    assert any("flag removed: --force" in b for b in rep["breaking"])


def test_choice_removal_is_breaking():
    cur = _mini_surface()
    cur["cli"]["x.py"]["commands"]["install"]["flags"]["--scope"]["choices"] = ["a"]
    rep = cps.compare(_mini_surface(), cur)
    assert any("choice removed: b" in b for b in rep["breaking"])


def test_choices_retype_is_breaking():
    cur = _mini_surface()
    cur["cli"]["x.py"]["commands"]["install"]["flags"]["--scope"]["choices"] = None
    rep = cps.compare(_mini_surface(), cur)
    assert any("choices retyped" in b for b in rep["breaking"])


def test_additions_are_free():
    cur = _mini_surface()
    cur["cli"]["x.py"]["commands"]["install"]["flags"]["--new"] = {"choices": None}
    cur["cli"]["x.py"]["commands"]["status"] = {"flags": {}, "positionals": {}}
    cur["cli"]["x.py"]["commands"]["install"]["flags"]["--scope"]["choices"] = ["a", "b", "c"]
    cur["jsonl_schemas"]["fb.jsonl:record"]["new_field"] = "str"
    cur["jsonl_schemas"]["new.jsonl:entry"] = {"x": "int"}
    cur["settings_template"]["env_keys"] = ["X", "Y"]
    rep = cps.compare(_mini_surface(), cur)
    assert rep["ok"], rep["breaking"]
    assert len(rep["additive"]) >= 5


# ---- superset rule: schemas / settings -------------------------------------------

def test_schema_field_removal_is_breaking():
    cur = _mini_surface()
    del cur["jsonl_schemas"]["fb.jsonl:record"]["cause"]
    rep = cps.compare(_mini_surface(), cur)
    assert any("field removed: cause" in b for b in rep["breaking"])


def test_schema_field_retype_is_breaking():
    cur = _mini_surface()
    cur["jsonl_schemas"]["fb.jsonl:record"]["ts"] = "float"
    rep = cps.compare(_mini_surface(), cur)
    assert any("field retyped: ts str -> float" in b for b in rep["breaking"])


def test_settings_key_removal_is_breaking():
    cur = _mini_surface()
    cur["settings_template"]["env_keys"] = []
    rep = cps.compare(_mini_surface(), cur)
    assert any("env_keys removed: X" in b for b in rep["breaking"])


# ---- accept-new upgrade path -------------------------------------------------------

def test_accept_new_breaking_requires_major(tmp_path):
    old = cps.emit(cps.current_surface(REPO))
    old["cli"]["workbench.py"]["commands"]["frobnicate"] = {"flags": {}, "positionals": {}}
    surf = tmp_path / "surface.json"
    surf.write_text(json.dumps(old), encoding="utf-8")
    rc = cps.main(["--root", str(REPO), "--surface", str(surf),
                   "--accept-new", "--bump", "minor", "--rationale", "sneaky"])
    assert rc == 2
    rc = cps.main(["--root", str(REPO), "--surface", str(surf),
                   "--accept-new", "--bump", "major", "--rationale", "intentional removal"])
    assert rc == 0
    doc = json.loads(surf.read_text(encoding="utf-8"))
    assert doc["history"][-1]["bump"] == "major"
    assert "frobnicate" not in doc["cli"]["workbench.py"]["commands"]


def test_accept_new_appends_history(tmp_path):
    surf = tmp_path / "surface.json"
    rc = cps.main(["--root", str(REPO), "--surface", str(surf),
                   "--accept-new", "--bump", "minor", "--rationale", "baseline"])
    assert rc == 0
    rc = cps.main(["--root", str(REPO), "--surface", str(surf),
                   "--accept-new", "--bump", "minor", "--rationale", "additive change"])
    assert rc == 0
    doc = json.loads(surf.read_text(encoding="utf-8"))
    assert [h["rationale"] for h in doc["history"]] == ["baseline", "additive change"]


def test_accept_new_requires_bump_and_rationale(tmp_path):
    surf = tmp_path / "surface.json"
    rc = cps.main(["--root", str(REPO), "--surface", str(surf), "--accept-new"])
    assert rc == 2
    assert not surf.exists()


def test_missing_frozen_surface_is_loud(tmp_path):
    rc = cps.main(["--root", str(REPO), "--surface", str(tmp_path / "nope.json")])
    assert rc == 2
