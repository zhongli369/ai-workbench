"""Incident replay contracts (P1.4).

Each INC-* entry in docs/incidents/registry.json names a real dated failure;
this module replays the incident CLASS against the live tree so the failure
can never silently come back. The registry itself is also validated: an
incident without regression tests, or naming tests that do not exist, fails.

Incident A — permission-pattern probing (bench arms): symmetric allowlist,
             no bare wildcards, no allowlist in the product settings,
             bypassPermissions stays bench-only.
Incident B — verifier anchoring: verify scripts resolve cwd, not __file__;
             they FAIL on the pristine seed with the VERIFY FAIL marker (a
             crash has no marker, so crash != verification failure); the
             driver hashes the verifier pre/post agent run.
Incident C — __pycache__ provenance pollution: caches skipped, real files
             still scanned.
Incident D — user-path leakage: publish set (git ls-files) and the release
             zipapp are clean; placeholders are not false-positived.
"""
import ast
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import check_hygiene  # noqa: E402

REGISTRY = json.loads(
    (REPO / "docs" / "incidents" / "registry.json").read_text(encoding="utf-8"))
TASKS = sorted((REPO / "tools" / "bench" / "tasks").glob("t*/verify.py"))


# ---- registry integrity -------------------------------------------------------

def test_registry_integrity():
    assert len(REGISTRY["incidents"]) >= 4
    ids = {i["id"] for i in REGISTRY["incidents"]}
    assert ids == {"INC-A-permission-probing", "INC-B-verify-wrong-root",
                   "INC-C-pycache-provenance", "INC-D-user-path-leakage"}
    for inc in REGISTRY["incidents"]:
        for field in ("title", "source", "root_cause", "fix", "reproduce",
                      "regression_tests", "commits", "verified_in_payload"):
            assert inc.get(field) not in (None, "", []), f"{inc['id']}.{field}"
        for t in inc["regression_tests"]:
            assert t.startswith("test_incident_replay.py::test_"), t
            name = t.split("::", 1)[1]
            assert name in globals(), f"{inc['id']} names missing test {name}"


# ---- Incident A -----------------------------------------------------------------

def _allowed_list() -> list[str]:
    tree = ast.parse((REPO / "tools" / "bench" / "run_arm.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "ALLOWED" for t in node.targets):
            return [e.value for e in node.value.elts]
    raise AssertionError("ALLOWED not found in run_arm.py")


def test_a_allowed_tools_bash_powershell_symmetric():
    """Cross-shell commands must exist under BOTH tool names — an arm that
    has Bash(git:*) but not PowerShell(git:*) pays denial-probing turns on
    Windows (the incident). Unix-only and Windows-native entries are exempt
    by explicit sets so the exemption list itself is reviewable."""
    allowed = _allowed_list()
    bash = {a[5:-1] for a in allowed if a.startswith("Bash(")}
    ps = {a[11:-1] for a in allowed if a.startswith("PowerShell(")}
    unix_only = {"cat:*", "ls:*", "find:*"}
    native_ps = {"Get-Content:*", "Get-ChildItem:*", "Set-Location:*",
                 "Test-Path:*", "cmd:*"}
    for b in bash - unix_only:
        assert b in ps, f"Bash({b}) has no PowerShell counterpart"
    for p in ps - native_ps:
        assert p in bash, f"PowerShell({p}) has no Bash counterpart and is not native"


def test_a_no_bare_wildcards_in_allowed():
    for a in _allowed_list():
        assert a not in ("Bash(*)", "PowerShell(*)", "*"), a
        inner = a[a.find("(") + 1:-1] if "(" in a else a
        assert inner.strip(), a


def test_a_product_settings_have_no_permissions_key():
    sys.path.insert(0, str(REPO / "tools"))
    import workbench
    assert "permissions" not in workbench.SETTINGS_TMPL
    assert "permissions" not in workbench.LAUNCH_SETTINGS_TMPL


def test_a_bypass_permissions_is_bench_only():
    for rel in ("tools/workbench.py", "hooks/harness_gate.py"):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "bypassPermissions" not in text, rel
    # where it IS used (bench), it must be documented as bench-only
    sdk = (REPO / "tools" / "bench" / "run_sdk_arm.py").read_text(encoding="utf-8")
    assert "bypassPermissions" in sdk
    assert "bench" in sdk.split("bypassPermissions")[0].lower() or \
        "Fairness" in sdk[:2000]


# ---- Incident B -----------------------------------------------------------------

def test_b_verifiers_use_cwd_not_file():
    assert len(TASKS) >= 5, "bench task set shrank unexpectedly"
    for vf in TASKS:
        text = vf.read_text(encoding="utf-8")
        assert "Path.cwd()" in text, f"{vf} does not anchor on cwd"
        assert not re.search(r"__file__\s*\)", text) or "Path(__file__)" not in text, \
            f"{vf} anchors on __file__ (incident B class)"


def test_b_verifiers_fail_on_pristine_seed_with_marker(tmp_path):
    """A verifier that passes on the untouched seed proves nothing; a crash
    (traceback) must never read as a controlled VERIFY FAIL. Seeds are
    copied to tmp first — running in-place would drop __pycache__ caches
    with absolute paths into the task dirs (incident C self-inflicted)."""
    import shutil
    for vf in TASKS:
        ws = tmp_path / vf.parent.name
        shutil.copytree(vf.parent / "seed", ws)
        out = subprocess.run([sys.executable, str(vf)], cwd=ws,
                             capture_output=True, text=True, timeout=300)
        combined = out.stdout + out.stderr
        assert out.returncode != 0, f"{vf.parent.name}: passes on pristine seed"
        # the failure must be announced via the marker protocol — a verifier's
        # own crash (unhandled traceback, no marker line) is not a controlled
        # verification failure. NB: the marker line may legitimately QUOTE the
        # seed app's traceback as evidence, so we assert the marker line, not
        # the absence of the word 'Traceback'.
        assert any(line.startswith("VERIFY FAIL:") for line in combined.splitlines()), \
            f"{vf.parent.name}: pristine-seed run produced no VERIFY FAIL marker " \
            f"(crash, not controlled failure?):\n{combined[-400:]}"


def test_b_driver_hashes_verifier_pre_post():
    src = (REPO / "tools" / "bench" / "run_sdk_arm.py").read_text(encoding="utf-8")
    assert "_sha256(verify_path)" in src
    assert "verify_tampered" in src
    assert "verify_hash_pre" in src and "verify_hash_post" in src
    # tampering must void the result, not just be noted
    assert re.search(r"if verify_tampered:\s*\n\s*success", src)


# ---- Incident C -----------------------------------------------------------------

def test_c_skip_dirs_cover_caches():
    assert "__pycache__" in check_hygiene.SKIP_DIRS
    assert ".pytest_cache" in check_hygiene.SKIP_DIRS


def test_c_pycache_skipped_but_real_files_scanned(tmp_path, monkeypatch):
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.py").write_text(
        r"path = 'C:\Users\cacheperson\proj'", encoding="utf-8")
    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(check_hygiene, "RC", tmp_path)
    assert check_hygiene.scan() == [], "cache dir polluted the scan"
    (tmp_path / "real.py").write_text(
        r"path = 'C:\Users\realperson\proj'", encoding="utf-8")
    bad = check_hygiene.scan()
    assert len(bad) == 1 and bad[0][0] == "real.py", \
        "real unauthorized change was not detected"


# ---- Incident D -----------------------------------------------------------------

def test_d_publish_set_clean_on_real_tree():
    bad = check_hygiene.scan()
    assert bad == [], "\n".join(f"{p}:{ln} {lbl}" for p, lbl, ln in bad)


def test_d_placeholders_not_false_positived(tmp_path, monkeypatch):
    (tmp_path / "doc.md").write_text(
        "clone it to `C:\\Users\\...\\project` or /path/to/install and run\n",
        encoding="utf-8")
    monkeypatch.setattr(check_hygiene, "RC", tmp_path)
    assert check_hygiene.scan() == []
    (tmp_path / "leak.md").write_text(r"built at C:\Users\14679\dev", encoding="utf-8")
    assert len(check_hygiene.scan()) == 1


def test_d_release_archive_scanned(tmp_path):
    """The packaged zipapp (the other artifact users receive) must be as
    clean as the git publish set."""
    out = tmp_path / "workbench.pyz"
    r = subprocess.run(
        [sys.executable, "-m", "zipapp", "tools", "-m", "workbench:main",
         "-o", str(out), "-p", "/usr/bin/env python3"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    bad = []
    with zipfile.ZipFile(out) as z:
        for name in z.namelist():
            if Path(name).suffix.lower() not in check_hygiene.TEXT_SUFFIXES:
                continue
            if Path(name).name in check_hygiene.SELF_REFS:
                continue
            text = z.read(name).decode("utf-8", errors="replace")
            for pat, label in check_hygiene.PATTERNS:
                if re.search(pat, text):
                    bad.append(f"{name}: {label}")
    assert bad == [], "\n".join(bad)
