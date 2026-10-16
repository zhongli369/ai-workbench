#!/usr/bin/env python3
"""Skill quality gate — static verification of the workbench skill CORPUS and
its wiring/registry consistency. stdlib only, deterministic, offline, no
network, Windows-compatible, runs in well under a second.

Zero-cost static-checking ideas are adapted from the skill-creator plugin
(metadata/schema validity, name uniqueness, safe entry references). Nothing
else from that plugin is reimplemented: no eval server, no model API, no HTML
viewer, no network calls.

What this gate catches that existing gates do NOT:
  A1  frontmatter `name` diverges from the mount directory name
      (the Skill tool mounts by directory; a differing frontmatter name is an
      invisible wiring split)
  A2  duplicate skill names across the mountable pool
      (workbench/.claude/skills + aiwb-* capability templates)
  A3  a directory under .claude/skills that is NOT a valid skill slot
      (no SKILL.md, or broken frontmatter)
  A4  empty / degenerate `description` (unmatchable by trigger routing)
  A5  dead relative markdown links inside skill bodies
      (fenced templates and the literal `url` slot are exempt)
  C1  hook auto-run injection directives inside skill files
      (guards the "ships no SessionStart injection" claim of the ported
      superpowers-systematic-debugging skill)
  C2  registry `name` prose that claims a skill count differing from the
      live mounted count ("Curated ECC skills (27)" vs 30 mounted)
  C3  registry wiring templates: template exists AND template frontmatter
      name == 'aiwb-<id>' == wiring_action.dest dir basename
  C4  registry mutex references: every mutex id resolves AND is symmetric
  B1  static metadata routing: authored trigger cases (task -> expected
      skill candidates) must hold against the declared name/description.
      Wording is explicit: STATIC METADATA ROUTING ONLY — this never claims
      to prove the model will trigger anything.

Exit 0 = clean, 1 = real defects. Duplication pairs are WARNs only (never
fail) and are allowlisted, seeded from the registry's own mutex mechanism.

Run:  python tools/check_skills.py [--json] [--root DIR]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SKILLS_ROOT = "workbench/.claude/skills"
WIRING_DIR = "capabilities/wiring"
REGISTRY_REL = "capabilities/registry.json"

# Words too connective to carry routing signal.
_STOP = {
    "the", "a", "an", "this", "that", "these", "those", "for", "and", "or",
    "with", "use", "used", "when", "using", "you", "your", "yours", "to",
    "of", "in", "on", "at", "by", "is", "are", "be", "been", "it", "its",
    "as", "from", "how", "what", "why", "which", "where", "who", "can",
    "will", "would", "should", "must", "may", "do", "does", "did", "have",
    "has", "had", "there", "their", "they", "we", "not", "no", "any", "all",
    "if", "then", "else", "than", "that", "into", "out", "per", "each",
    "also", "but", "so", "very", "just", "like", "such", "one", "two",
    "three", "etc", "i.e", "e.g", "eg", "ie", "via", "over", "under",
    "again", "more", "most", "less", "few", "many", "other", "same", "some",
    "being", "been", "within", "without", "across", "between", "against",
    "about", "after", "before", "during", "while", "until", "toward",
}
_HOOK_DIRECTIVE = re.compile(r"#!\[hook[:\s]")
_FENCED = re.compile(r"```")
_MD_LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_COUNT_CLAIM = re.compile(r"skills?[ (]+(\d+)\)")


# --------------------------------------------------------------------------- data

# Static metadata routing cases. Authorship rule from the real, declared
# name/description metadata of the mountable pool — verified against the tree
# before shipping. Field meanings:
# `task`             — the operator request text (tokenized)
# `expect_top`       — ids that must rank within the top-K candidates
# `expect_not_top`   — ids that must NOT rank within top-K (robust negative)
# `expect_absent`    — ids that must score exactly zero (strict; used only
#                      where the descriptions guarantee zero shared vocabulary)
# `no_cross_project` — the first expect_top id (the workbench skill) must be
#                      the STRICT sole #1: cross-project tasks route
#                      unambiguously and never to a peer skill
# Report wording everywhere: STATIC METADATA ROUTING ONLY — this proves
# keyword overlap against declared metadata, never real model triggering.
ROUTING_CASES: list[dict] = [
    {
        "id": "codebase-onboarding-vs-debugging",
        "task": "analyze an unfamiliar codebase and generate a structured "
                "onboarding guide with an architecture map and key entry points",
        "expect_top": ["codebase-onboarding"],
        "expect_not_top": ["gateguard", "tdd-workflow"],
    },
    {
        "id": "tdd-red-green-refactor",
        "task": "Python unit test failing, red green refactor, coverage requirement",
        "expect_top": ["tdd-workflow"],
        "expect_not_top": ["ecc-guide", "github-ops"],
    },
    {
        "id": "benchmark-regression",
        "task": "measure performance baselines, detect regressions after a pull request",
        "expect_top": ["benchmark"],
        "expect_not_top": ["github-ops", "context-budget"],
    },
    {
        "id": "trivial-copyedit-not-debugging",
        "task": "README typo, copyediting, documentation line wrapping, cosmetic",
        "expect_not_top": ["aiwb-superpowers-systematic-debugging",
                           "tdd-workflow", "error-handling"],
        "expect_absent": ["aiwb-superpowers-systematic-debugging",
                          "tdd-workflow"],
    },
    {
        "id": "cross-project-routes-to-workbench",
        "task": "目标项目B的项目规则如何加载, 用工作台操作目标项目, project_id 隔离",
        "expect_top": ["workbench"],
        "no_cross_project": True,
    },
]

# Semantic-duplicate WARN allowlist. Seeded from the registry's OWN mutex
# mechanism (a mutex pair declares two capabilities that must not be active
# together — strong evidence the pair is "the same space", so an overlap WARN
# is noise) plus documented known-overlap pairs below.
# mutex pairs are read live from registry.json; add only pairs that are NOT
# covered by registry mutex.
DUP_ALLOWLIST: set[tuple[str, str]] = {
    ("tdd-workflow", "python-testing"),      # TDD/coverage is the shared idiom
    ("python-testing", "frontend-patterns"),  # both teaching-pattern sets
}


# ------------------------------------------------------------------ frontmatter

def parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the leading YAML frontmatter block (name/description + extras).

    Handles `key: scalar` and block scalars for `description` (`>-`, `|`).
    stdlib-only, intentionally minimal — the Skill loader's requirement is
    `name` + `description` presence.
    """
    out: dict[str, str] = {}
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return out
    body = m.group(1)
    lines = body.splitlines()
    key: str | None = None      # current key awaiting a block scalar body
    block_lines: list[str] = []
    for raw in lines:
        km = re.match(r"^([A-Za-z][A-Za-z0-9_-]*)\s*:\s*(.*)$", raw)
        if km:
            # flush any pending block scalar
            if key is not None and block_lines:
                out[key] = " ".join(block_lines).strip()
            key = None
            block_lines = []
            k, v = km.group(1), km.group(2).strip()
            if v.startswith(("|", ">")):
                key = k              # block scalar body starts on next lines
            else:
                v = v.strip("\"'") if v.startswith(("\"", "'")) else v
                if v:
                    out[k] = v
            continue
        # not a key line: a block-scalar continuation (or stray content)
        if key is not None:
            block_lines.append(raw.strip())
    if key is not None and block_lines:
        out[key] = " ".join(block_lines).strip()
    return out


def skill_token_set(frontmatter: dict) -> set[str]:
    """Term set used by the static router and the duplication WARN."""
    tokens: set[str] = set()
    text = frontmatter.get("name", "") + "\n" + frontmatter.get("description", "")
    tokens |= {t for t in re.findall(r"[a-z][a-z0-9]*", text.lower())
               if t not in _STOP and not t.isdigit()}
    cjk = re.findall(r"[一-鿿]", text)
    tokens |= {a + b for a, b in zip(cjk, cjk[1:])}
    return tokens


def task_token_set(task: str, keywords: list[str] | None) -> set[str]:
    toks = set(keywords or []) | skill_token_set({"name": "", "description": task})
    return {t for t in toks if t}


# ----------------------------------------------------------------------- corpus

class Skill:
    """One mountable skill slot (dir under skills root, or aiwb-* template)."""

    __slots__ = ("id", "mount", "path", "frontmatter", "source")

    def __init__(self, id_: str, mount: str, path: Path, source: str):
        self.id = id_
        self.mount = mount          # dir name the Skill tool mounts by
        self.path = path            # SKILL.md file
        self.frontmatter = parse_frontmatter(path.read_text(encoding="utf-8",
                                                            errors="replace"))
        self.source = source        # "workbench" | "aiwb-template"


def discover(root: Path) -> list[Skill]:
    """Mountable pool: workbench/.claude/skills/*/SKILL.md plus the aiwb-*
    capability templates (their installed mount dir comes from registry
    wiring_action.dest)."""
    skills: list[Skill] = []
    base = root / SKILLS_ROOT
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if d.is_dir():
                fm = d / "SKILL.md"
                if fm.is_file():
                    skills.append(Skill(d.name, d.name, fm, "workbench"))
    reg = load_registry(root)
    for cap in reg.get("capabilities", []):
        wa = cap.get("wiring_action") or {}
        if wa and wa.get("dest"):
            tpl = root / WIRING_DIR / wa["template"]
            if tpl.is_file():
                mount = Path(wa["dest"]).parent.name
                skills.append(Skill(mount, mount, tpl, "aiwb-template"))
    return skills


def load_registry(root: Path) -> dict:
    p = root / REGISTRY_REL
    if not p.is_file():
        return {"capabilities": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"capabilities": []}


# ----------------------------------------------------------------------- checks

def _outside_fence(text: str) -> str:
    """Blind the contents of fenced code blocks so link checks skip templates."""
    parts = _FENCED.split(text)
    return " ".join(parts[i] for i in range(0, len(parts), 2))


def check_frontmatter(skills: list[Skill]) -> list[str]:
    bad: list[str] = []
    for s in skills:
        if not s.frontmatter:
            bad.append(f"A3 {s.mount}: SKILL.md has no parseable frontmatter "
                       f"(must start with ---)")
            continue
        name = s.frontmatter.get("name", "").strip()
        desc = s.frontmatter.get("description", "").strip()
        if name != s.mount:
            bad.append(f"A1 {s.mount}: frontmatter name {name!r} != mount dir "
                       f"{s.mount!r} — Skill tool mounts by directory, so the "
                       f"listing and the trigger metadata diverge")
        if not desc:
            bad.append(f"A4 {s.mount}: empty description (unmatchable by "
                       f"static routing)")
        elif len(desc) < 20:
            bad.append(f"A4 {s.mount}: description too short ({len(desc)} chars)")
    return bad


def check_name_conflicts(skills: list[Skill]) -> list[str]:
    """Duplicate FRONTMATTER `name` across the pool: two skills presenting the
    same listing name (even under different mount dirs) make Skill-tool
    routing ambiguous — the model sees two identically-named candidates."""
    seen: dict[str, str] = {}
    bad: list[str] = []
    for s in skills:
        nm = s.frontmatter.get("name", "").strip()
        if not nm:
            continue
        if nm in seen:
            bad.append(f"A2 duplicate skill name {nm!r}: {seen[nm]} "
                       f"and {s.path}")
        seen[nm] = str(s.path)
    return bad


def check_skill_dirs(root: Path) -> list[str]:
    base = root / SKILLS_ROOT
    if not base.is_dir():
        return []
    bad: list[str] = []
    for d in sorted(base.iterdir()):
        if d.is_dir():
            if not (d / "SKILL.md").is_file():
                bad.append(f"A3 {d.name}: directory under {SKILLS_ROOT} has no "
                           f"SKILL.md — broken skill slot")
        elif d.name not in {".DS_Store", "README.md"}:
            bad.append(f"A3 {d.name}: unexpected non-directory entry directly "
                       f"under {SKILLS_ROOT}")
    return bad


def check_dead_links(skills: list[Skill]) -> list[str]:
    bad: list[str] = []
    for s in skills:
        text = s.path.read_text(encoding="utf-8", errors="replace")
        for m in _MD_LINK.finditer(_outside_fence(text)):
            target = m.group(1)
            if (target.startswith(("http://", "https://", "mailto:", "#", "tel:"))
                    or target == "url"):          # literal template slot
                continue
            target = target.split("#", 1)[0]
            if not target:
                continue
            if not (s.path.parent / target).exists():
                bad.append(f"A5 {s.mount}: dead relative link [{target}] in "
                           f"{s.path.name} (target {target!r} not found)")
    return bad


def check_no_hook_injection(skills: list[Skill]) -> list[str]:
    """No auto-run hook directives: a skill that re-imports the upstream
    superpowers-style `#![hook:...]` directive, or declares a `hooks:`
    frontmatter mapping, silently starts running hooks at session start.
    Passing prose mentioning "injection" is exempt."""
    bad: list[str] = []
    for s in skills:
        text = s.path.read_text(encoding="utf-8", errors="replace")
        for m in _HOOK_DIRECTIVE.finditer(text):
            bad.append(f"C1 {s.mount}: hook auto-run directive "
                       f"{m.group(0).strip()!r} in {s.path.name} — skills must "
                       f"be passive static markdown")
        if "hooks" in s.frontmatter:
            bad.append(f"C1 {s.mount}: frontmatter declares `hooks:` — auto-run "
                       f"hook injection in a skill file is forbidden here")
    return bad


def check_registry_counts(root: Path, skills: list[Skill]) -> list[str]:
    """Registry `name` prose that claims a skill count must match the live
    mounted count (registry<->files consistency)."""
    reg = load_registry(root)
    live = sum(1 for s in skills if s.source == "workbench")
    bad: list[str] = []
    for cap in reg.get("capabilities", []):
        name = cap.get("name", "")
        m = _COUNT_CLAIM.search(name)
        if m and int(m.group(1)) != live:
            bad.append(
                f"C2 {cap['id']}: registry name claims {m.group(1)} skills "
                f"({name!r}) but {live} skill slots are mounted under "
                f"{SKILLS_ROOT}")
    return bad


def check_registry_wiring(root: Path, skills: list[Skill]) -> list[str]:
    reg = load_registry(root)
    mounted = {s.mount: s for s in skills}
    bad: list[str] = []
    for cap in reg.get("capabilities", []):
        wa = cap.get("wiring_action")
        if not wa:
            continue
        tpl = root / WIRING_DIR / wa["template"]
        if not tpl.is_file():
            bad.append(f"C3 {cap['id']}: wiring template missing: "
                       f"{WIRING_DIR}/{wa['template']}")
            continue
        fm = parse_frontmatter(tpl.read_text(encoding="utf-8", errors="replace"))
        expect_name = (Path(wa["dest"]).parent.name
                       if wa.get("dest") else f"aiwb-{cap['id']}")
        if fm.get("name") != expect_name:
            bad.append(f"C3 {cap['id']}: template frontmatter name "
                       f"{fm.get('name')!r} != expected mount {expect_name!r}")
        slot = mounted.get(expect_name)
        if slot is None:
            bad.append(f"C3 {cap['id']}: wiring dest {wa['dest']} is not in the "
                       f"mountable pool")
    # dest uniqueness + no collision with workbench skill dirs
    seen_dest: set[str] = set()
    for cap in reg.get("capabilities", []):
        wa = cap.get("wiring_action") or {}
        dest = wa.get("dest")
        if not dest:
            continue
        if dest in seen_dest:
            bad.append(f"C3 duplicate wiring_action.dest: {dest}")
        seen_dest.add(dest)
    return bad


def check_mutex(root: Path) -> list[str]:
    reg = load_registry(root)
    ids = {c["id"] for c in reg.get("capabilities", [])}
    by_id = {c["id"]: c for c in reg.get("capabilities", [])}
    bad: list[str] = []
    for c in reg.get("capabilities", []):
        for mx in c.get("mutex", []):
            if mx not in ids:
                bad.append(f"C4 {c['id']}: mutex target {mx!r} is not a "
                           f"registered capability id")
                continue
            other = by_id.get(mx)
            if c["id"] not in other.get("mutex", []):
                bad.append(f"C4 mutex is not symmetric: {c['id']} -> {mx} but "
                           f"{mx} has no reciprocal entry")
    return bad


def _route(skills: list[Skill], case: dict) -> list[str]:
    """Static-metadata routing assertions for one case. Returns violations."""
    k = int(case.get("k", 3))
    tset = task_token_set(case["task"], case.get("keywords"))
    scores = {s.mount: len(tset & skill_token_set(s.frontmatter))
              for s in skills}
    ranked = sorted(skills, key=lambda s: (-scores[s.mount], s.mount))
    top = [s.mount for s in ranked[:k]]
    viols: list[str] = []
    for want in case.get("expect_top", []):
        if scores.get(want, -1) <= 0:
            viols.append(f"B1 [{case['id']}] {want!r} scores 0 for task "
                         f"{case['task']!r} (no metadata overlap)")
        elif want not in top:
            viols.append(f"B1 [{case['id']}] {want!r} not in top-{k} "
                         f"(top: {top})")
    for absent in case.get("expect_not_top", []):
        if absent in top:
            viols.append(f"B1 [{case['id']}] {absent!r} must NOT be a top-{k} "
                         f"candidate for task {case['task']!r} but ranks there "
                         f"(top: {top})")
    for absent in case.get("expect_absent", []):
        if scores.get(absent, 0) > 0:
            viols.append(f"B1 [{case['id']}] {absent!r} must NOT route for task "
                         f"{case['task']!r} but scores {scores[absent]}")
    if case.get("no_cross_project"):
        pivot = (case.get("expect_top") or [None])[0]
        others = [(s.mount, scores[s.mount]) for s in skills if s.mount != pivot]
        top_score = scores.get(pivot, 0)
        if top_score <= 0:
            viols.append(f"B1 [{case['id']}] cross-project task must route to "
                         f"{pivot!r} but scores 0")
        else:
            tied = sorted((sc, m) for m, sc in others if sc >= top_score)
            if tied:
                viols.append(f"B1 [{case['id']}] cross-project task not "
                             f"unambiguous: {pivot!r} ties with {tied}")
    return viols


def check_routing(root: Path, skills: list[Skill]) -> list[str]:
    viols: list[str] = []
    mounts = {s.mount for s in skills}
    for case in ROUTING_CASES:
        for ref in (case.get("expect_top", []) + case.get("expect_not_top", [])
                    + case.get("expect_absent", [])):
            if ref not in mounts:
                viols.append(f"B1 [{case['id']}] dangling routing reference "
                             f"{ref!r} (not in mountable pool)")
        viols += _route(skills, case)
    return viols


DUP_MIN_SHARED = 5       # distinct shared terms required
DUP_MIN_DENSITY = 0.30   # ... as a fraction of the smaller term set

# ROUTING_CASES are authored for the FULL mounted corpus (30 workbench +
# aiwb-* templates). A pool below this size is a test fixture or an
# intentionally minimal kit, and corpus-level routing assertions would only
# drown in dangling-reference noise — so routing validation runs only on a
# full-size pool. The real installed corpus always exceeds this.
ROUTING_MIN_POOL = 20


def check_duplication(skills: list[Skill],
                      allowlist: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """Semantic-overlap WARNs (never hard failures). Allowlist seed comes from
    the registry mutex mechanism (reuse, not a new mutex system) plus the
    constant allowlist above."""
    allowed = set(allowlist)
    for i, s in enumerate(skills):
        for o in skills[i + 1:]:
            a_set = skill_token_set(s.frontmatter)
            b_set = skill_token_set(o.frontmatter)
            shared = a_set & b_set
            shared = {t for t in shared if len(t) >= 4}
            denom = min(len(a_set), len(b_set))
            if len(shared) >= DUP_MIN_SHARED and denom \
                    and len(shared) / denom >= DUP_MIN_DENSITY \
                    and (s.mount, o.mount) not in allowed \
                    and (o.mount, s.mount) not in allowed:
                yield (s.mount, o.mount)


def _mutex_allowlist(root: Path) -> set[tuple[str, str]]:
    """Pairs already declared mutually exclusive — treat an overlap WARN as
    expected (the pair IS the same space by declaration)."""
    reg = load_registry(root)
    out: set[tuple[str, str]] = set()
    for c in reg.get("capabilities", []):
        for mx in c.get("mutex", []):
            pair = tuple(sorted(("aiwb-" + c["id"], "aiwb-" + mx)))
            if len(pair[0]) > 4 and len(pair[1]) > 4 and pair[0] != pair[1]:
                out.add(pair)
    return out


# ------------------------------------------------------------------ orchestrator

def run(root: Path) -> dict:
    root = Path(root).resolve() if Path(root).is_dir() else REPO
    skills = discover(root)
    failures: list[str] = []
    warnings: list[tuple[str, str]] = []

    failures += check_skill_dirs(root)
    failures += check_frontmatter(skills)
    failures += check_name_conflicts(skills)
    failures += check_dead_links(skills)
    failures += check_no_hook_injection(skills)
    failures += check_registry_counts(root, skills)
    failures += check_registry_wiring(root, skills)
    failures += check_mutex(root)
    if len(skills) >= ROUTING_MIN_POOL:
        failures += check_routing(root, skills)

    allow = DUP_ALLOWLIST | _mutex_allowlist(root)
    warnings += list(check_duplication(skills, allow))

    metrics = {
        "skills_mounted": len(skills),
        "workbench_skills": sum(1 for s in skills if s.source == "workbench"),
        "aiwb_templates": sum(1 for s in skills if s.source == "aiwb-template"),
    }
    return {"ok": not failures, "failures": failures, "warnings": warnings,
            "metrics": metrics}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="skill quality gate")
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = run(Path(args.root))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if rep["ok"] else 1
    if rep["failures"]:
        print("skill quality FAIL:")
        for f in sorted(set(rep["failures"])):
            print(f"  {f}")
    if rep["warnings"]:
        print("skill quality WARN (semantic duplication, not a failure):")
        for a, b in sorted(rep["warnings"]):
            print(f"  ~ {a} <-> {b}")
    m = rep["metrics"]
    note = (" (static metadata routing only — proves nothing about live "
            "triggering)" if rep["metrics"] else "")
    print(f"skill quality {'PASS' if rep['ok'] else 'FAIL'} "
          f"({m['skills_mounted']} mounted: {m['workbench_skills']} workbench, "
          f"{m['aiwb_templates']} aiwb-templates; "
          f"{len(rep['failures'])} failures, {len(rep['warnings'])} warns)"
          f"{note}")
    if rep["failures"]:
        print("  static metadata routing only; not a live-trigger guarantee")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())