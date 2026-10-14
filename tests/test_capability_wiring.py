"""Capability wiring v1.1 contracts (offline, no model, no network).

Managed skill-file integration: enable requires a passing health check (the
external tool must already be user-installed — we NEVER auto-install), then
writes a marked SKILL.md registered in the install manifest so owns-only
uninstall sweeps it. Disable removes only files whose marker is intact.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RC_ROOT = Path(__file__).resolve().parent.parent
WB = RC_ROOT / "tools" / "workbench.py"
REGISTRY = RC_ROOT / "capabilities" / "registry.json"
WIRING_DIR = RC_ROOT / "capabilities" / "wiring"


def run_wb(*args, target=None, env_extra=None):
    cmd = [sys.executable, str(WB)]
    if target is not None:
        cmd += ["--target", str(target)]
    cmd += list(args)
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)


def _bare_target(tmp_path):
    """Registry-only target (no install) — registry + wiring templates, as
    an install payload would provide."""
    import shutil
    (tmp_path / "capabilities").mkdir(exist_ok=True)
    (tmp_path / "capabilities" / "registry.json").write_text(
        REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    shutil.copytree(WIRING_DIR, tmp_path / "capabilities" / "wiring", dirs_exist_ok=True)
    return tmp_path


def _fake_cli(tmp_path, name="repomix"):
    """Create a fake executable on a private PATH dir; return env override.
    Platform-aware: shutil.which() resolves name.exe via PATHEXT on Windows,
    but on POSIX the file must be named exactly `name` with the exec bit."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    if os.name == "nt":
        (bin_dir / f"{name}.exe").write_text("@echo off\r\n", encoding="utf-8")
    else:
        f = bin_dir / name
        f.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        f.chmod(0o755)
    return {"PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}


def _empty_path_env(tmp_path):
    bin_dir = tmp_path / "emptybin"
    bin_dir.mkdir(exist_ok=True)
    return {"PATH": str(bin_dir)}


# ---------- template hygiene / registry consistency ----------

def test_wiring_templates_exist_and_are_clean():
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for cap in reg["capabilities"]:
        wa = cap.get("wiring_action")
        if not wa:
            continue
        assert wa["type"] == "skill-file"
        assert wa["dest"].startswith(".claude/skills/aiwb-")
        tpl = WIRING_DIR / wa["template"]
        assert tpl.is_file(), f"missing template {tpl}"
        text = tpl.read_text(encoding="utf-8")
        assert text.startswith("---"), "SKILL.md needs frontmatter"
        assert "\nname: aiwb-" in text and "\ndescription: " in text
        for bad in ("F:\\", "F:/", "C:\\", "C:/", "/Users/", "/home/", "14679"):
            assert bad not in text, f"machine-specific fragment in {tpl.name}: {bad}"


# ---------- enable ----------

def test_enable_with_healthy_cli_wires_skill_file(tmp_path):
    _bare_target(tmp_path)
    env = _fake_cli(tmp_path)
    r = run_wb("capability", "enable", "repomix", target=tmp_path, env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "已接线" in r.stdout
    dest = tmp_path / ".claude" / "skills" / "aiwb-repomix" / "SKILL.md"
    assert dest.is_file()
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "<!-- aiwb-managed:repomix -->"
    assert "name: aiwb-repomix" in dest.read_text(encoding="utf-8")
    state = json.loads((tmp_path / "harness-data" / "capability-state.json")
                       .read_text(encoding="utf-8"))
    assert state["repomix"] is True
    assert state["_wired"]["repomix"] == [".claude/skills/aiwb-repomix/SKILL.md"]


def test_enable_without_cli_fails_closed_and_writes_nothing(tmp_path):
    _bare_target(tmp_path)
    r = run_wb("capability", "enable", "repomix", target=tmp_path,
               env_extra=_empty_path_env(tmp_path))
    assert r.returncode == 1
    assert "从不自动安装" in r.stdout
    assert not (tmp_path / ".claude").exists()
    state_path = tmp_path / "harness-data" / "capability-state.json"
    if state_path.exists():
        assert json.loads(state_path.read_text(encoding="utf-8")).get("repomix") is not True


def test_mutex_blocks_wiring_of_second_browser_tool(tmp_path):
    _bare_target(tmp_path)
    env = _fake_cli(tmp_path, "agent-browser")
    assert run_wb("capability", "enable", "agent-browser",
                  target=tmp_path, env_extra=env).returncode == 0
    r = run_wb("capability", "enable", "playwright-mcp", target=tmp_path, env_extra=env)
    assert r.returncode == 1 and "互斥" in r.stdout


# ---------- disable / uninstall (owns-only) ----------

def _full_install_with_repomix(tmp_path):
    target = tmp_path / "wb"
    env = _fake_cli(tmp_path)
    r = run_wb("install", "--scope", "project", target=target, env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr
    r = run_wb("capability", "enable", "repomix", target=target, env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return target, env


def test_disable_removes_managed_file_and_manifest_entry(tmp_path):
    target, env = _full_install_with_repomix(tmp_path)
    dest = target / ".claude" / "skills" / "aiwb-repomix" / "SKILL.md"
    manifest = json.loads((target / "install-manifest.json").read_text(encoding="utf-8"))
    assert str(dest) in manifest["files"]
    r = run_wb("capability", "disable", "repomix", target=target, env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not dest.exists()
    manifest = json.loads((target / "install-manifest.json").read_text(encoding="utf-8"))
    assert str(dest) not in manifest["files"]


def test_disable_preserves_file_whose_marker_was_stripped(tmp_path):
    target, env = _full_install_with_repomix(tmp_path)
    dest = target / ".claude" / "skills" / "aiwb-repomix" / "SKILL.md"
    text = dest.read_text(encoding="utf-8")
    dest.write_text("\n".join(text.splitlines()[1:]), encoding="utf-8")  # user edit
    r = run_wb("capability", "disable", "repomix", target=target, env_extra=env)
    assert r.returncode == 0
    assert "WARN" in r.stdout and "保留" in r.stdout
    assert dest.is_file()  # owns-only: not ours anymore, leave it


def test_uninstall_sweeps_wired_file(tmp_path):
    target, env = _full_install_with_repomix(tmp_path)
    dest = target / ".claude" / "skills" / "aiwb-repomix" / "SKILL.md"
    assert dest.is_file()
    r = run_wb("uninstall", "--yes", target=target, env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not dest.exists()
    assert not (target / ".claude" / "skills" / "aiwb-repomix").exists()
