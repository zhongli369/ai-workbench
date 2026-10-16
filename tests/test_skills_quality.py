"""Contracts for the skill quality gate (tools/check_skills.py).

Positive contract: a clean hermetic tree passes, and the REAL tree must
stay clean — the gate's founding live catch was the registry's
"Curated ECC skills (27)" count-claim vs 30 mounted skill slots (registry
<-> files drift no other gate verifies; fixed at integration, pinned by
test_real_tree_is_clean).

Negative contracts run against synthetic tmp roots so the semantics of EACH
check group (metadata/schema, trigger routing, wiring integrity, hook
injection, duplication WARN) are pinned. No network, no model, no subprocess.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import check_skills as gate  # noqa: E402


# ------------------------------------------------------------------ fixtures

def _skill(root: Path, name: str, description: str, *, extra_fm: str = "") -> None:
    d = root / "workbench" / ".claude" / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    body = "---\nname: {name}\ndescription: {desc}\n{extra}---\n# {name}\nbody".format(
        name=name, desc=description, extra=extra_fm)
    (d / "SKILL.md").write_text(body, encoding="utf-8")


def _registry(root: Path, capabilities: list[dict]) -> None:
    (root / "capabilities").mkdir(parents=True, exist_ok=True)
    (root / "capabilities" / "registry.json").write_text(
        json.dumps({"schema": 1, "notes": "", "capabilities": capabilities},
                   ensure_ascii=False, indent=1),
        encoding="utf-8")


def _wiring_tpl(root: Path, filename: str, name: str, description: str) -> None:
    (root / "capabilities" / "wiring").mkdir(parents=True, exist_ok=True)
    (root / "capabilities" / "wiring" / filename).write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n# managed\n",
        encoding="utf-8")


def _clean_root(tmp_path: Path) -> Path:
    """A minimal clean tree: 2 skills, no registry, no wiring."""
    root = tmp_path / "root"
    _skill(root, "codebase-onboarding",
           "Analyze an unfamiliar codebase and generate a structured "
           "onboarding guide with architecture map and key entry points.")
    _skill(root, "tdd-workflow",
           "Use this skill when writing new features, fixing bugs, or "
           "refactoring code. Enforces test-driven development and coverage.")
    return root


# ------------------------------------------------------------- real tree

def test_real_tree_is_clean():
    """Standing regression for the gate's founding live catch: the registry
    'Curated ECC skills (N)' count-claim must match the mounted skill slots
    (was 27-vs-30 at introduction; fixed at integration). No other gate
    binds the registry `name` count to the mounted corpus (check_docs_drift
    only binds README claims; check_ecc_provenance only verifies the
    vendored snapshot manifest). The firing semantics of C2 itself are
    pinned by the synthetic tests below."""
    rep = gate.run(REPO)
    assert rep["ok"], "\n".join(rep["failures"])


def test_real_tree_has_no_other_hard_failures():
    """After special-casing the count defect the corpus must be clean: no
    broken slots, no name drift, no hook injection, no routing regression,
    no mutex or wiring-template inconsistency."""
    rep = gate.run(REPO)
    non_count = [f for f in rep["failures"] if "C2" not in f]
    assert non_count == [], "\n".join(non_count)


def test_real_tree_static_routing_cases_pass():
    """The data-driven routing cases must hold on the real tree (this is the
    anti-vacuous anchor: ROUTING_MIN_POOL is satisfied, so the 5 authored
    cases all run and none may regress)."""
    rep = gate.run(REPO)
    b1 = [f for f in rep["failures"] if "B1" in f]
    assert b1 == [], "\n".join(b1)


# ---------------------------------------------------------- metadata (A)

def test_clean_tree_passes(tmp_path):
    root = _clean_root(tmp_path)
    rep = gate.run(root)
    assert rep["ok"], "\n".join(rep["failures"])


def test_frontmatter_name_mismatch_detected(tmp_path):
    root = _clean_root(tmp_path)
    p = root / "workbench" / ".claude" / "skills" / "tdd-workflow" / "SKILL.md"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "name: tdd-workflow", "name: red-green-refactor"), encoding="utf-8")
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("A1" in f and "tdd-workflow" in f and "red-green-refactor" in f
               for f in rep["failures"])


def test_duplicate_skill_name_detected(tmp_path):
    root = _clean_root(tmp_path)
    dup = root / "workbench" / ".claude" / "skills" / "tdd-workflow-2"
    dup.mkdir(parents=True)
    (dup / "SKILL.md").write_text(
        "---\nname: tdd-workflow\ndescription: fraud twin body, distinct text\n"
        "---\n# twin\n", encoding="utf-8")
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("A2" in f and "tdd-workflow" in f for f in rep["failures"])


def test_broken_skill_slot_detected(tmp_path):
    root = _clean_root(tmp_path)
    (root / "workbench" / ".claude" / "skills" / "ghost").mkdir(parents=True)
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("A3" in f and "ghost" in f for f in rep["failures"])


def test_degenerate_description_detected(tmp_path):
    root = _clean_root(tmp_path)
    p = root / "workbench" / ".claude" / "skills" / "tdd-workflow" / "SKILL.md"
    p.write_text("---\nname: tdd-workflow\ndescription: hi\n---\n#\n",
                 encoding="utf-8")
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("A4" in f for f in rep["failures"])


def test_dead_relative_link_detected(tmp_path):
    root = _clean_root(tmp_path)
    d = root / "workbench" / ".claude" / "skills" / "tdd-workflow"
    (d / "SKILL.md").write_text(
        "---\nname: tdd-workflow\ndescription: real TDD guidance body.\n---\n"
        "Read [the guide](missing/guide.md).\n```md\n[exempt](url)\n```\n",
        encoding="utf-8")
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("A5" in f and "missing/guide.md" in f for f in rep["failures"])


def test_fenced_and_url_slots_are_exempt_from_dead_link(tmp_path):
    root = _clean_root(tmp_path)
    d = root / "workbench" / ".claude" / "skills" / "tdd-workflow"
    (d / "SKILL.md").write_text(
        "---\nname: tdd-workflow\ndescription: real TDD guidance body.\n---\n"
        "```md\n[output](url)\n```\nAlso [anchor](#local) and "
        "[web](https://example.com).\n", encoding="utf-8")
    rep = gate.run(root)
    assert rep["ok"], "\n".join(rep["failures"])


# ------------------------------------------------- hook injection (C1)

def test_hook_injection_directive_detected(tmp_path):
    root = _clean_root(tmp_path)
    d = root / "workbench" / ".claude" / "skills" / "tdd-workflow"
    (d / "SKILL.md").write_text(
        "---\nname: tdd-workflow\ndescription: real TDD guidance body.\n---\n"
        "#![hook:SessionStart:echo injected]\n", encoding="utf-8")
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("C1" in f for f in rep["failures"])


def test_prose_mention_of_sessionstart_is_exempt(tmp_path):
    root = _clean_root(tmp_path)
    d = root / "workbench" / ".claude" / "skills" / "tdd-workflow"
    (d / "SKILL.md").write_text(
        "---\nname: tdd-workflow\ndescription: real TDD guidance body.\n---\n"
        "This port drops the upstream SessionStart injection; the methods "
        "stay passive markdown.\n", encoding="utf-8")
    rep = gate.run(root)
    assert rep["ok"], "\n".join(rep["failures"])


# ------------------------------------------------- routing (B1)

def _mk_skill(root: Path, name: str, description: str) -> gate.Skill:
    """Write a real SKILL.md on a hermetic path and build the Skill wrapper —
    the constructor reads the file, so the file must exist."""
    p = root / "skills" / name / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nname: {name}\ndescription: {description}\n---\nx\n",
                 encoding="utf-8")
    return gate.Skill(name, name, p, "workbench")


def test_routing_top_and_not_top_assertions(tmp_path):
    skills = [
        _mk_skill(tmp_path, "pieces", "jigsaw puzzle pieces matching"),
        _mk_skill(tmp_path, "puzzles", "jigsaw puzzles pieces matching"),
        _mk_skill(tmp_path, "gardening", "planting tulips soil watering"),
    ]
    case = {"id": "t", "task": "assemble jigsaw puzzle pieces",
            "expect_top": ["puzzles"], "expect_not_top": ["gardening"],
            "k": 2}
    assert gate._route(skills, case) == []


def test_routing_not_top_violation_detected(tmp_path):
    skills = [
        _mk_skill(tmp_path, "a", "shared words here"),
        _mk_skill(tmp_path, "b", "shared words here"),
    ]
    case = {"id": "t", "task": "shared words here",
            "expect_top": ["a"], "expect_not_top": ["b"], "k": 2}
    viols = gate._route(skills, case)
    assert any("must NOT be a top-2 candidate" in v for v in viols)


def test_routing_expect_absent_zero_score(tmp_path):
    skills = [
        _mk_skill(tmp_path, "debug", "root causes evidence fix"),
        _mk_skill(tmp_path, "copyedit", "typos corrections style"),
    ]
    case = {"id": "t", "task": "a typo needs style corrections and copyediting",
            "expect_absent": ["debug"], "k": 1}
    assert gate._route(skills, case) == []


def test_routing_no_cross_project_strict_sole_top(tmp_path):
    skills = [
        _mk_skill(tmp_path, "workbench",
                  "目标项目 规则加载 工作台 操作 项目 隔离 经验"),
        _mk_skill(tmp_path, "other",
                  "目标项目 规则加载 工作台 操作 项目 隔离 经验"),
    ]
    case = {"id": "t", "task": "目标项目规则加载 工作台",
            "expect_top": ["workbench"], "no_cross_project": True, "k": 2}
    viols = gate._route(skills, case)
    assert any("not unambiguous" in v for v in viols)  # peer tied -> fail


def test_routing_dangling_reference_detected(tmp_path):
    # Routing validation runs only on a full-size pool (ROUTING_MIN_POOL),
    # so build one: 22 dummy slots, then inject a case referencing a missing id.
    root = _clean_root(tmp_path)
    base = root / "workbench" / ".claude" / "skills"
    for i in range(22):
        d = base / f"dummy-{i:02d}"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: dummy-{i:02d}\ndescription: dummy filler number {i}\n"
            f"---\n#\n", encoding="utf-8")
    case = {"id": "t", "task": "whatever terms",
            "expect_top": ["no-such-skill"]}
    orig = list(gate.ROUTING_CASES)
    gate.ROUTING_CASES.append(case)
    try:
        rep = gate.run(root)
        assert any("dangling routing reference" in f and "no-such-skill" in f
                   for f in rep["failures"])
    finally:
        gate.ROUTING_CASES[:] = orig


# ------------------------------------------------- registry/wiring (C2-C4)

def test_registry_count_claim_mismatch_detected(tmp_path):
    root = _clean_root(tmp_path)
    _registry(root, [
        {"id": "ecc-skills", "name": "Curated ECC skills (7)",
         "origin": "x", "wiring": "active",
         "mutex": [], "applies_to": ["standard"]},
    ])
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("C2" in f and "7" in f and "2" in f for f in rep["failures"])


def test_registry_count_claim_matching_passes(tmp_path):
    root = _clean_root(tmp_path)
    _registry(root, [
        {"id": "ecc-skills", "name": "Curated ECC skills (2)",
         "origin": "x", "wiring": "active",
         "mutex": [], "applies_to": ["standard"]},
    ])
    rep = gate.run(root)
    assert rep["ok"], "\n".join(rep["failures"])


def test_wiring_template_name_binding_mismatch_detected(tmp_path):
    root = _clean_root(tmp_path)
    _skill(root, "aiwb-repomix", "repomix repo map context packing.")
    _wiring_tpl(root, "repomix.skill.md", "aiwb-renamed", "repomix description")
    _registry(root, [
        {"id": "repomix", "name": "repomix", "origin": "x",
         "wiring": "skill-file", "mutex": [], "applies_to": ["deep"],
         "wiring_action": {"type": "skill-file", "template": "repomix.skill.md",
                          "dest": ".claude/skills/aiwb-repomix/SKILL.md"}},
    ])
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("C3" in f for f in rep["failures"])


def test_wiring_template_binding_clean_passes(tmp_path):
    root = _clean_root(tmp_path)
    _wiring_tpl(root, "repomix.skill.md", "aiwb-repomix",
                "repomix context packing and repo-map generation for large repos")
    _registry(root, [
        {"id": "repomix", "name": "repomix", "origin": "x",
         "wiring": "skill-file", "mutex": [], "applies_to": ["deep"],
         "wiring_action": {"type": "skill-file", "template": "repomix.skill.md",
                          "dest": ".claude/skills/aiwb-repomix/SKILL.md"}},
    ])
    rep = gate.run(root)
    assert rep["ok"], "\n".join(rep["failures"])


def test_mutex_asymmetry_detected(tmp_path):
    root = _clean_root(tmp_path)
    _registry(root, [
        {"id": "a", "name": "a tool", "origin": "x", "wiring": "-",
         "mutex": ["b"], "applies_to": []},
        {"id": "b", "name": "b tool", "origin": "x", "wiring": "-",
         "mutex": [], "applies_to": []},
    ])
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("C4" in f and "symmetric" in f for f in rep["failures"])


def test_mutex_unresolvable_target_detected(tmp_path):
    root = _clean_root(tmp_path)
    _registry(root, [
        {"id": "a", "name": "a tool", "origin": "x", "wiring": "-",
         "mutex": ["ghost-cap"], "applies_to": []},
    ])
    rep = gate.run(root)
    assert not rep["ok"]
    assert any("C4" in f and "ghost-cap" in f for f in rep["failures"])


def test_mutex_symmetric_resolving_passes(tmp_path):
    root = _clean_root(tmp_path)
    _registry(root, [
        {"id": "a", "name": "a tool", "origin": "x", "wiring": "-",
         "mutex": ["b"], "applies_to": []},
        {"id": "b", "name": "b tool", "origin": "x", "wiring": "-",
         "mutex": ["a"], "applies_to": []},
    ])
    rep = gate.run(root)
    assert rep["ok"], "\n".join(rep["failures"])


# ------------------------------------------------- mismatch/dup WARN (D)

def test_duplication_pair_warns_not_fails(tmp_path):
    """Semantic-overlap pairs are WARNs — the exit code stays 0 (no hard
    failure) but the pair is reported."""
    root = _clean_root(tmp_path)
    _skill(root, "tdd-one", "write tests first red, then green refactor, "
                            "coverage requirements, failing test case, unit "
                            "integration and end to end, pytest fixture",
           )
    _skill(root, "tdd-twin", "write tests first red, then green refactor, "
                             "coverage requirements, failing test case, unit "
                             "integration and end to end, pytest fixture",
           )
    rep = gate.run(root)
    assert rep["ok"]  # WARN, never hard FAIL
    assert any("tdd-one" in a and "tdd-twin" in b for a, b in rep["warnings"])


def test_duplication_warn_suppressed_by_registry_mutex(tmp_path):
    """Reuses the registry's own mutex mechanism as the allowlist: a pair
    declared mutually exclusive is treated as 'same space by declaration'
    and must not emit a WARN. The slots are aiwb-* capability skills (that is
    how discover() maps registry ids -> mounts, and what mutex-seeding keys
    on), so build them through wiring templates + wiring_action."""
    root = _clean_root(tmp_path)
    desc = ("run tests first red, then green refactor, coverage "
            "requirements, failing test cases, unit integration and end to "
            "end throughout, pytest fixtures")
    _wiring_tpl(root, "tdd-one.skill.md", "aiwb-tdd-one", desc)
    _wiring_tpl(root, "tdd-twin.skill.md", "aiwb-tdd-twin", desc)
    _registry(root, [
        {"id": "tdd-one", "name": "one", "origin": "x",
         "wiring": "skill-file", "mutex": ["tdd-twin"], "applies_to": [],
         "wiring_action": {"type": "skill-file",
                          "template": "tdd-one.skill.md",
                          "dest": ".claude/skills/aiwb-tdd-one/SKILL.md"}},
        {"id": "tdd-twin", "name": "twin", "origin": "x",
         "wiring": "skill-file", "mutex": ["tdd-one"], "applies_to": [],
         "wiring_action": {"type": "skill-file",
                          "template": "tdd-twin.skill.md",
                          "dest": ".claude/skills/aiwb-tdd-twin/SKILL.md"}},
    ])
    rep = gate.run(root)
    assert rep["ok"], "\n".join(rep["failures"])
    assert rep["warnings"] == [], \
        f"mutex declaration must allowlist the overlap: {rep['warnings']}"


def test_duplication_constant_allowlist_suppresses_warn(tmp_path):
    root = _clean_root(tmp_path)
    _skill(root, "tdd-workflow", "write tests first red sphere, green sphere, "
                                 "coverage sphere, fixture sphere, mocking "
                                 "sphere, parametrize sphere, pytest sphere")
    _skill(root, "python-testing", "write tests first red sphere, green sphere, "
                                   "coverage sphere, fixture sphere, mocking "
                                   "sphere, parametrize sphere, pytest sphere")
    # With the constant allowlist present the warning is suppressed …
    rep = gate.run(root)
    assert rep["ok"]
    assert not rep["warnings"]
    # … and without it the same pair IS flagged (the allowlist is load-bearing).
    orig = set(gate.DUP_ALLOWLIST)
    gate.DUP_ALLOWLIST.clear()
    try:
        rep = gate.run(root)
        assert any({"tdd-workflow", "python-testing"} == {a, b}
                   for a, b in rep["warnings"])
    finally:
        gate.DUP_ALLOWLIST.clear()
        gate.DUP_ALLOWLIST |= orig


# ---------------------------------------------------------- CLI smoke

def test_cli_exit_code_matches():
    import subprocess
    r = subprocess.run([sys.executable, str(REPO / "tools" / "check_skills.py"),
                        "--root", str(REPO), "--json"],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=60)
    assert r.returncode == 0              # real tree clean (count defect fixed)
    rep = json.loads(r.stdout.strip())
    assert rep["ok"], rep["failures"]


def test_cli_exit_1_on_synthetic_failure(tmp_path):
    import subprocess
    root = _clean_root(tmp_path)
    _registry(root, [{"id": "ecc-skills",
                      "name": "Curated ECC skills (99)",
                      "origin": "x", "wiring": "active",
                      "mutex": [], "applies_to": ["standard"]}])
    r = subprocess.run([sys.executable, str(REPO / "tools" / "check_skills.py"),
                        "--root", str(root), "--json"],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=60)
    assert r.returncode == 1
    rep = json.loads(r.stdout.strip())
    assert not rep["ok"]
    assert any("C2" in f for f in rep["failures"])