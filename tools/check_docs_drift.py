"""Docs drift gate — release claims verified against live sources.

Idea adapted from SystemKernel's drift_detector (CLAUDE.md prose vs tree
truth), reimplemented lightweight: no prose parsing, only structured claims
declared in docs/claims.json, each bound to a deterministic live source
(pytest collection counts, ECC payload counts, argparse AST surface,
VERSION constant, capability registry). Wording changes that keep numbers
right do not fail; wrong numbers do.

Checks:
  numeric  — doc regex captures must equal the live source value
  figure   — every performance figure (×, 倍, $, %) in the READMEs must be
             whitelisted in claims.json AND carry an evidence qualifier
             (e.g. "N=1", "controlled", "受控") in the same paragraph block
  cli      — documented `workbench.py ...` / `harness/cli.py ...` invocations
             must exist in the real argparse surface (AST, no execution)
  link     — relative markdown links must resolve to files in the tree
  removed  — deleted-feature strings must not appear in any doc
  version  — tools/workbench.py VERSION == first CHANGELOG ## [x.y.z]

Exit 0 = no drift. A missing optional claim is INFO, never FAIL.
Run:  python tools/check_docs_drift.py [--json] [--root DIR]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from cli_surface import extract_cli_surface, check_invocation  # noqa: E402

_FIGURE_PATTERNS = [
    re.compile(r"(\d+\.\d+)[×x](?![.\d])"),
    re.compile(r"(\d+\.\d+)\s*倍"),
    re.compile(r"\$(\d+\.\d+)"),
    re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%"),
]
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_INLINE_CMD = re.compile(
    r"`python ((?:tools/)?(?:harness-core/)?(?:workbench\.py|harness/cli\.py))([^`]*)`")
_FENCED_CMD = re.compile(
    r"^\s*python ((?:tools/)?(?:harness-core/)?(?:workbench\.py|harness/cli\.py))([^\n`]*)$",
    re.MULTILINE)


class _Sources:
    """Live values; each computed once per run. Tests may override."""

    def __init__(self, root: Path, overrides: dict | None):
        self.root = root
        self.overrides = overrides or {}
        self._cache: dict[str, str] = {}

    def get(self, key: str) -> str:
        if key in self.overrides:
            return str(self.overrides[key])
        if key not in self._cache:
            self._cache[key] = str(self._compute(key))
        return self._cache[key]

    def _compute(self, key: str):
        if key.startswith("pytest:"):
            target = key.split(":", 1)[1]
            dirs = ["tests", "harness-core/tests"] if target == "all" else [target]
            return sum(self._pytest_count(d) for d in dirs)
        if key.startswith("ecc:"):
            kind = key.split(":", 1)[1]
            base = self.root / "workbench" / ".claude"
            if kind == "skills":
                return sum(1 for d in (base / "skills").iterdir()
                           if d.is_dir() and (d / "SKILL.md").is_file())
            return len(list((base / kind).glob("*.md")))
        if key == "version:workbench":
            text = (self.root / "tools" / "workbench.py").read_text(encoding="utf-8")
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if not m:
                raise RuntimeError("VERSION constant not found in tools/workbench.py")
            return m.group(1)
        raise RuntimeError(f"unknown source: {key}")

    def _pytest_count(self, subdir: str) -> int:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", subdir, "--collect-only", "-q"],
            cwd=self.root, capture_output=True, text=True, timeout=180)
        m = re.search(r"(\d+) tests? collected", out.stdout)
        if not m:
            raise RuntimeError(f"pytest collection failed for {subdir}:\n{out.stdout[-400:]}\n{out.stderr[-400:]}")
        return int(m.group(1))


def _blocks(text: str) -> list[str]:
    return re.split(r"\n\s*\n", text)


def run(root: Path, *, scripts_root: Path | None = None,
        source_overrides: dict | None = None) -> dict:
    root = Path(root)
    scripts_root = Path(scripts_root) if scripts_root else root
    claims = json.loads((root / "docs" / "claims.json").read_text(encoding="utf-8"))
    src = _Sources(scripts_root, source_overrides)
    failures: list[str] = []
    infos: list[str] = []
    checked: list[str] = []

    docs_cache: dict[str, str | None] = {}

    def doc_text(rel: str):
        if rel not in docs_cache:
            p = root / rel
            docs_cache[rel] = p.read_text(encoding="utf-8") if p.is_file() else None
        return docs_cache[rel]

    # 1. numeric claims -----------------------------------------------------
    for c in claims.get("numeric_claims", []):
        text = doc_text(c["doc"])
        if text is None:
            infos.append(f"{c['id']}: doc {c['doc']} missing, skipped")
            continue
        expect = src.get(c["source"])
        claim_text = text
        if c.get("scope") == "first_entry":
            # only the top `## [` section: historical changelog entries keep
            # their historical numbers by design — that is not drift
            starts = [m.start() for m in re.finditer(r"^## \[", text, re.MULTILINE)]
            if starts:
                end = starts[1] if len(starts) > 1 else len(text)
                claim_text = text[starts[0]:end]
        matches = re.findall(c["regex"], claim_text)
        if not matches:
            msg = f"{c['id']}: claim not found in {c['doc']} (expected value {expect})"
            (failures if c.get("required") else infos).append(
                msg if c.get("required") else msg + " [optional]")
            continue
        for m in matches:
            value = m if isinstance(m, str) else m[0]
            if value != expect:
                failures.append(
                    f"{c['id']}: {c['doc']} says {value}, live source "
                    f"{c['source']} says {expect}")
        checked.append(c["id"])

    # 2. performance figures -------------------------------------------------
    approved = {f["figure"]: f for f in claims.get("approved_figures", [])}
    for rel in claims.get("figure_docs", []):
        text = doc_text(rel)
        if text is None:
            continue
        blocks = _blocks(text)
        for pat in _FIGURE_PATTERNS:
            for m in pat.finditer(text):
                value = m.group(1)
                if value not in approved:
                    failures.append(
                        f"figure {value} in {rel} not whitelisted in "
                        f"claims.json approved_figures (evidence required)")
                    continue
                quals = approved[value].get("qualifiers", [])
                block = next((b for b in blocks if m.group(0) in b), "")
                if quals and not any(q.lower() in block.lower() for q in quals):
                    failures.append(
                        f"figure {value} in {rel} lacks evidence qualifier "
                        f"{quals} in its paragraph (N=1 results must not read "
                        f"as stable claims)")
        checked.append(f"figures:{rel}")

    # 3. documented CLI invocations ------------------------------------------
    surfaces = {}
    if claims.get("cli_docs"):
        surfaces = {
            "workbench.py": extract_cli_surface(scripts_root / "tools" / "workbench.py"),
            "harness/cli.py": extract_cli_surface(scripts_root / "harness-core" / "harness" / "cli.py"),
        }
    for name, surf in surfaces.items():
        if not surf["commands"]:
            failures.append(f"cli surface extraction yielded no commands for {name}")
    seen: set[str] = set()
    for rel in claims.get("cli_docs", []):
        text = doc_text(rel)
        if text is None:
            continue
        invocations = []
        for regex in (_INLINE_CMD, _FENCED_CMD):
            for m in regex.finditer(text):
                script, rest = m.group(1), m.group(2)
                toks = rest.split()
                toks = [t for t in toks if not t.startswith("#")]
                while toks and toks[-1] == "\\":
                    toks.pop()
                key = (script, tuple(toks))
                if key in seen:
                    continue
                seen.add(key)
                invocations.append((script, toks))
        for script, toks in invocations:
            surf = surfaces["workbench.py" if script.endswith("workbench.py")
                            else "harness/cli.py"]
            for prob in check_invocation(surf, toks):
                failures.append(f"{rel}: documented invocation `{script} "
                                f"{' '.join(toks)}` invalid: {prob}")
        checked.append(f"cli:{rel}")

    # 4. relative markdown links ---------------------------------------------
    for rel in claims.get("link_docs", []):
        text = doc_text(rel)
        if text is None:
            continue
        for m in _MD_LINK.finditer(text):
            target = m.group(1)
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            target = target.split("#", 1)[0]
            if target and not (root / target).exists():
                failures.append(f"{rel}: dead relative link {m.group(1)}")
        checked.append(f"links:{rel}")

    # 5. removed features must not be advertised ------------------------------
    removed = claims.get("removed_features", {})
    for rel in removed.get("docs", []):
        text = doc_text(rel)
        if text is None:
            continue
        for s in removed.get("strings", []):
            if s in text:
                failures.append(f"{rel}: removed feature still advertised: {s}")

    # 6. version consistency ---------------------------------------------------
    vcfg = claims.get("version")
    if vcfg:
        version = src.get("version:workbench")
        chlog = doc_text(vcfg["changelog"])
        if chlog is None:
            failures.append(f"changelog {vcfg['changelog']} missing")
        else:
            m = re.search(vcfg["changelog_pattern"], chlog, re.MULTILINE)
            if not m:
                failures.append("no version entry found in CHANGELOG")
            elif m.group(1) != version:
                failures.append(
                    f"VERSION {version} != top CHANGELOG entry {m.group(1)}")
        checked.append("version")

    return {"ok": not failures, "failures": failures, "infos": infos,
            "checked": checked}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="docs drift gate")
    ap.add_argument("--root", default=str(REPO))
    ap.add_argument("--scripts-root", default=None,
                    help="where the live scripts/payloads are (default: --root)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rep = run(Path(args.root),
              scripts_root=Path(args.scripts_root) if args.scripts_root else None)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        for f in rep["failures"]:
            print(f"DRIFT FAIL: {f}")
        for i in rep["infos"]:
            print(f"info: {i}")
        print(f"docs drift gate: {'PASS' if rep['ok'] else 'FAIL'} "
              f"({len(rep['checked'])} check groups, {len(rep['failures'])} failures)")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
