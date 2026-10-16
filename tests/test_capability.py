"""Capability registry contracts (offline, no model, no network).

Covers: registry schema validity, license policy, hygiene (no machine paths),
enable/disable round-trip isolation, mutex enforcement, doctor exit codes,
and the anti-context-pollution guarantee (registry never injected into
workbench CLAUDE.md).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

RC_ROOT = Path(__file__).resolve().parent.parent
WB = RC_ROOT / "tools" / "workbench.py"
REGISTRY = RC_ROOT / "capabilities" / "registry.json"

OSI_ALLOWED = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}


def run_wb(*args, target=None, env_extra=None):
    import os
    cmd = [sys.executable, str(WB)]
    if target is not None:
        cmd += ["--target", str(target)]
    cmd += list(args)
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    # 180s: CI Windows runners have real Node, so enabling playwright-mcp runs
    # npx readiness probing against the npm registry; under load this exceeds 60s.
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180, env=env)


@pytest.fixture()
def reg():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_registry_schema_and_unique_ids(reg):
    assert reg["schema"] == 1
    caps = reg["capabilities"]
    assert len(caps) >= 5
    ids = [c["id"] for c in caps]
    assert len(set(ids)) == len(ids), f"duplicate ids: {ids}"


def test_registry_required_fields(reg):
    required = {"id", "name", "origin", "license", "cost_hint", "trigger",
                "security", "health", "wiring", "default_enabled", "mutex",
                "applies_to", "evidence"}
    for c in reg["capabilities"]:
        missing = required - set(c)
        assert not missing, f"{c.get('id')}: missing {missing}"
        assert c["health"].get("type") in {"file", "dir", "cli", "env", "cli-version", "manual"}


def test_registry_licenses_are_osi(reg):
    for c in reg["capabilities"]:
        assert c["license"] in OSI_ALLOWED, f"{c['id']}: non-OSI license {c['license']}"


def test_registry_has_no_machine_specific_paths(reg):
    raw = REGISTRY.read_text(encoding="utf-8")
    for bad in ("F:\\", "F:/", "C:\\", "C:/", "/Users/", "/home/", "14679"):
        assert bad not in raw, f"machine-specific path fragment in registry: {bad}"


def test_registry_not_injected_into_workbench_context():
    claude_md = (RC_ROOT / "workbench" / "CLAUDE.md").read_text(encoding="utf-8")
    assert "registry.json" not in claude_md
    assert "capabilities/registry" not in claude_md


def test_capability_list_json_valid(reg):
    r = run_wb("capability", "list", "--json", target=RC_ROOT)
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert {row["id"] for row in rows} == {c["id"] for c in reg["capabilities"]}


def test_enable_disable_roundtrip_isolated(tmp_path):
    (tmp_path / "capabilities").mkdir()
    (tmp_path / "capabilities" / "registry.json").write_text(
        REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    r = run_wb("capability", "disable", "harness-oracle", target=tmp_path)
    assert r.returncode == 0, r.stderr
    state = json.loads((tmp_path / "harness-data" / "capability-state.json")
                       .read_text(encoding="utf-8"))
    assert state["harness-oracle"] is False
    out = run_wb("capability", "list", "--json", target=tmp_path)
    rows = {row["id"]: row for row in json.loads(out.stdout)}
    assert rows["harness-oracle"]["enabled"] is False
    assert rows["harness-gate"]["enabled"] is True  # 互不影响
    r = run_wb("capability", "enable", "harness-oracle", target=tmp_path)
    assert r.returncode == 0
    rows = {row["id"]: row for row in
            json.loads(run_wb("capability", "list", "--json", target=tmp_path).stdout)}
    assert rows["harness-oracle"]["enabled"] is True
    # 状态只写目标内: 仓库自身 harness-data 不得出现
    assert not (RC_ROOT / "harness-data" / "capability-state.json").exists()


def test_mutex_enforced_on_enable(tmp_path):
    import os
    import shutil as _sh
    (tmp_path / "capabilities").mkdir()
    (tmp_path / "capabilities" / "registry.json").write_text(
        REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    _sh.copytree(RC_ROOT / "capabilities" / "wiring",
                 tmp_path / "capabilities" / "wiring")
    # wiring v1.1: agent-browser has wiring_action, so enable requires its
    # health check — provide a fake user-installed CLI on PATH.
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    if os.name == "nt":
        (bin_dir / "agent-browser.exe").write_text("@echo off\r\n", encoding="utf-8")
    else:
        f = bin_dir / "agent-browser"
        f.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        f.chmod(0o755)
    env = {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
    assert run_wb("capability", "enable", "agent-browser",
                  target=tmp_path, env_extra=env).returncode == 0
    r = run_wb("capability", "enable", "playwright-mcp", target=tmp_path, env_extra=env)
    assert r.returncode == 1
    assert "互斥" in r.stdout
    assert run_wb("capability", "disable", "agent-browser",
                  target=tmp_path, env_extra=env).returncode == 0
    # mutex released: playwright-mcp (v1.2 mcp-config wiring) now reaches its
    # readiness gate — the fake env has no node/npm/browser, so it fails on
    # readiness (not on mutex) with the never-auto-install message.
    r = run_wb("capability", "enable", "playwright-mcp",
               target=tmp_path, env_extra=env)
    assert r.returncode == 1
    assert "互斥" not in r.stdout and "未就绪" in r.stdout


def test_unknown_capability_rejected(tmp_path):
    (tmp_path / "capabilities").mkdir()
    (tmp_path / "capabilities" / "registry.json").write_text(
        REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    r = run_wb("capability", "enable", "no-such-cap", target=tmp_path)
    assert r.returncode == 1
    assert "未知能力" in r.stdout


def test_doctor_passes_on_full_install(tmp_path):
    # 模拟完整安装: 内建 health 目标全部存在
    (tmp_path / "capabilities").mkdir()
    (tmp_path / "capabilities" / "registry.json").write_text(
        REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "harness-core" / "harness").mkdir(parents=True)
    (tmp_path / "harness-core" / "harness" / "feedback.py").write_text("# stub", encoding="utf-8")
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "harness_gate.py").write_text("# stub", encoding="utf-8")
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    (tmp_path / ".claude" / "agents").mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text("# stub", encoding="utf-8")
    r = run_wb("capability", "doctor", target=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "内建能力缺失" not in r.stdout


def test_doctor_fails_when_builtin_missing(tmp_path):
    (tmp_path / "capabilities").mkdir()
    (tmp_path / "capabilities" / "registry.json").write_text(
        REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    # 内建 health 目标全缺 → FAIL (exit 1)
    r = run_wb("capability", "doctor", target=tmp_path)
    assert r.returncode == 1
    assert "内建能力缺失" in r.stdout


def test_corrupt_state_fails_closed(tmp_path):
    (tmp_path / "capabilities").mkdir()
    (tmp_path / "capabilities" / "registry.json").write_text(
        REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "harness-data").mkdir()
    (tmp_path / "harness-data" / "capability-state.json").write_text("{not json", encoding="utf-8")
    r = run_wb("capability", "list", target=tmp_path)
    assert r.returncode == 1
    assert "损坏" in r.stdout


# ---- cli-version health type (codex decoy guard) ------------------------------

def _cap_mod():
    tools_dir = str(RC_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    import capability
    return capability


def test_cli_version_health_ok_with_prefix():
    cap = _cap_mod()
    h = {"type": "cli-version", "path": sys.executable, "prefix": "Python"}
    status, detail = cap.check_health({"health": h}, Path("."))
    assert status == "ok", detail
    assert "Python" in detail


def test_cli_version_health_rejects_decoy_prefix():
    # Same-shaped binary answering --version with a DIFFERENT product name
    # must not satisfy the check (real case: PATH `codex` is an unrelated
    # npm static-site generator, not the OpenAI codex-cli).
    cap = _cap_mod()
    h = {"type": "cli-version", "path": sys.executable, "prefix": "codex-cli"}
    status, detail = cap.check_health({"health": h}, Path("."))
    assert status == "missing"
    assert "codex-cli" in detail


def test_cli_version_health_missing_file():
    cap = _cap_mod()
    h = {"type": "cli-version", "path": "no-such-dir-zzz/bin/x.exe", "prefix": "x"}
    status, detail = cap.check_health({"health": h}, Path("."))
    assert status == "missing"
    assert detail == "no-such-dir-zzz/bin/x.exe"


def test_cli_version_health_expands_env_var(monkeypatch):
    import os
    monkeypatch.setenv("AIWB_TEST_PYEXE", sys.executable)
    form = "%AIWB_TEST_PYEXE%" if os.name == "nt" else "$AIWB_TEST_PYEXE"
    cap = _cap_mod()
    h = {"type": "cli-version", "path": form, "prefix": "Python"}
    status, _ = cap.check_health({"health": h}, Path("."))
    assert status == "ok"
