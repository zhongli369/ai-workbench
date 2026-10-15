"""mcp-config wiring contracts (offline, no model, no network, no npm).

Covers the four-state verdict, works-only-on-our-entry mutation (unknown user
config is never touched), idempotent re-enable, clean disable/uninstall, and
fail-closed behaviour on corrupt or foreign config.

The runtime probe and the MCP handshake are monkeypatched: the unit tests must
be hermetic (they may run on a machine without node, without the package, and
without network). The REAL handshake was executed separately against
@playwright/mcp@0.0.83 — see docs/decisions/2026-10-15-playwright.md.
"""
import json
import os
import sys
from pathlib import Path

import pytest

RC_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RC_ROOT / "tools"))

import wiring_mcp as w  # noqa: E402

WB = RC_ROOT / "tools" / "workbench.py"

CAP = {"id": "playwright-mcp", "wiring_action": {"type": "mcp-config"}}


# ---------------------------------------------------------------- helpers

def _runtime(*, ok=True, browser=True, mode="local", missing=None):
    return {
        "node": {"ok": ok, "path": "node", "version": "v24.15.0" if ok else ""},
        "npm": {"ok": ok, "path": "npm", "version": "10.9.0" if ok else ""},
        "package": {"ok": ok, "mode": mode, "version": w.PIN_DEFAULT if ok else None,
                    "detail": "stub"},
        "browser": {"ok": browser, "detail": "stub", "dirs": []},
        "local_cli": None,
        "ready": ok,
        "missing": missing if missing is not None else ([] if ok else ["node", "npm"]),
        "package_name": w.PACKAGE_DEFAULT,
        "pin": w.PIN_DEFAULT,
    }


@pytest.fixture()
def env(monkeypatch):
    """Ready runtime + passing handshake; individual tests override as needed."""
    monkeypatch.setattr(w, "probe_runtime", lambda root, cap, **kw: _runtime())
    monkeypatch.setattr(w, "mcp_handshake",
                        lambda argv, **kw: {"ok": True, "detail": "stub handshake ok",
                                            "tools": ["browser_navigate"], "stderr": ""})
    return monkeypatch


def _write(p: Path, obj) -> None:
    p.write_text(json.dumps(obj, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")


def _user_config() -> dict:
    return {
        "mcpServers": {
            "user-notes": {"command": "node", "args": ["/opt/notes.js"]},
        },
        "someUserKey": {"keep": ["me", 1, True]},
    }


def run_wb(*args, target=None, env_extra=None):
    import subprocess
    cmd = [sys.executable, str(WB)]
    if target is not None:
        cmd += ["--target", str(target)]
    cmd += list(args)
    e = dict(os.environ)
    if env_extra:
        e.update(env_extra)
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          timeout=120, env=e)


# ---------------------------------------------------------------- default OFF

def test_install_never_writes_mcp_config(tmp_path):
    """Default OFF at the installer level: install alone wires no browser."""
    target = tmp_path / "wb"
    r = run_wb("install", "--scope", "project", target=target)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (target / ".mcp.json").exists()
    assert not (target / "harness-data" / "mcp-wiring.json").exists()


def test_canonical_entry_is_pinned_and_os_correct():
    entry = w.canonical_entry(CAP)
    joined = " ".join([entry["command"], *entry["args"]])
    assert f"@playwright/mcp@{w.PIN_DEFAULT}" in joined
    assert "latest" not in joined
    assert "--isolated" in entry["args"] and "--headless" in entry["args"]
    assert entry["args"].count("-y") == 1
    if os.name == "nt":
        assert entry["command"] == "cmd" and entry["args"][:2] == ["/c", "npx"]
    else:
        assert entry["command"] == "npx"


# ---------------------------------------------------------------- four states

def test_state_1_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "probe_runtime",
                        lambda root, cap, **kw: _runtime(ok=False, browser=True))
    st = w.wire_status(tmp_path, CAP)
    assert st["state"] == w.STATE_NOT_INSTALLED
    assert "node" in st["detail"]


def test_state_1_not_installed_also_when_package_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "probe_runtime",
                        lambda root, cap, **kw: _runtime(ok=False, browser=True,
                                                         missing=["包 @playwright/mcp@0.0.83"]))
    st = w.wire_status(tmp_path, CAP)
    assert st["state"] == w.STATE_NOT_INSTALLED
    assert "包" in st["detail"]


def test_state_2_installed_not_enabled(tmp_path, env):
    st = w.wire_status(tmp_path, CAP)
    assert st["state"] == w.STATE_INSTALLED_NOT_ENABLED
    assert not (tmp_path / ".mcp.json").exists()


def test_state_3_enabled_not_connected(tmp_path, env):
    monkeypatch = env
    ok, _ = w.wire_enable(None, tmp_path, CAP, probe=False)
    assert ok
    monkeypatch.setattr(w, "mcp_handshake",
                        lambda argv, **kw: {"ok": False, "detail": "handshake 超时",
                                            "tools": [], "stderr": "boom"})
    st = w.wire_status(tmp_path, CAP)
    assert st["state"] == w.STATE_ENABLED_NOT_CONNECTED
    assert "超时" in st["detail"]


def test_state_4_connected_tested(tmp_path, env):
    assert w.wire_enable(None, tmp_path, CAP, probe=False)[0]
    st = w.wire_status(tmp_path, CAP)
    assert st["state"] == w.STATE_CONNECTED_TESTED
    assert st["probed"] is True
    assert st["tools"] == ["browser_navigate"]


def test_full_four_state_transition_sequence(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "mcp_handshake",
                        lambda argv, **kw: {"ok": False, "detail": "no server",
                                            "tools": [], "stderr": ""})
    monkeypatch.setattr(w, "probe_runtime",
                        lambda root, cap, **kw: _runtime(ok=False, browser=True))
    assert w.wire_status(tmp_path, CAP)["state"] == w.STATE_NOT_INSTALLED
    monkeypatch.setattr(w, "probe_runtime", lambda root, cap, **kw: _runtime())
    assert w.wire_status(tmp_path, CAP)["state"] == w.STATE_INSTALLED_NOT_ENABLED
    assert w.wire_enable(None, tmp_path, CAP, probe=False)[0]
    assert w.wire_status(tmp_path, CAP)["state"] == w.STATE_ENABLED_NOT_CONNECTED
    monkeypatch.setattr(w, "mcp_handshake",
                        lambda argv, **kw: {"ok": True, "detail": "ok", "tools": ["t"],
                                            "stderr": ""})
    assert w.wire_status(tmp_path, CAP)["state"] == w.STATE_CONNECTED_TESTED


def test_no_probe_is_labelled_unprobed_not_connected(tmp_path, env):
    assert w.wire_enable(None, tmp_path, CAP, probe=False)[0]
    st = w.wire_status(tmp_path, CAP, probe=False)
    assert st["state"] == w.STATE_ENABLED_UNPROBED
    assert st["probed"] is False
    assert st["state"] != w.STATE_CONNECTED_TESTED


def test_entry_present_but_env_missing_still_reports_not_installed(tmp_path, env):
    assert w.wire_enable(None, tmp_path, CAP, probe=False)[0]
    env.setattr(w, "probe_runtime", lambda root, cap, **kw: _runtime(ok=False))
    st = w.wire_status(tmp_path, CAP)
    assert st["state"] == w.STATE_NOT_INSTALLED
    assert "托管条目已写入" in st["detail"]


# ---------------------------------------------------------------- enable gate

def test_enable_fails_closed_and_writes_nothing_when_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "probe_runtime", lambda root, cap, **kw: _runtime(ok=False))
    ok, msgs = w.wire_enable(None, tmp_path, CAP)
    assert ok is False
    assert any("从不自动安装" in m for m in msgs)
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / "harness-data" / "mcp-wiring.json").exists()


def test_enable_requires_browser_unless_explicitly_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "probe_runtime",
                        lambda root, cap, **kw: _runtime(browser=False))
    monkeypatch.setattr(w, "mcp_handshake",
                        lambda argv, **kw: {"ok": True, "detail": "ok", "tools": ["t"],
                                            "stderr": ""})
    ok, msgs = w.wire_enable(None, tmp_path, CAP)
    assert ok is False and any("playwright install chromium" in m for m in msgs)
    assert not (tmp_path / ".mcp.json").exists()
    ok, msgs = w.wire_enable(None, tmp_path, CAP, allow_missing_browser=True)
    assert ok is True
    assert any("WARN" in m for m in msgs)
    assert (tmp_path / ".mcp.json").is_file()


def test_enable_reports_handshake_failure_but_still_wires(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "probe_runtime", lambda root, cap, **kw: _runtime())
    monkeypatch.setattr(w, "mcp_handshake",
                        lambda argv, **kw: {"ok": False, "detail": "握手失败: 超时",
                                            "tools": [], "stderr": ""})
    ok, msgs = w.wire_enable(None, tmp_path, CAP)
    assert ok is True
    assert any("WARN" in m and "超时" in m for m in msgs)
    assert len(json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]) == 1


# ---------------------------------------------------------------- owns-only

def test_enable_preserves_unknown_user_config(tmp_path, env):
    cfg = tmp_path / ".mcp.json"
    _write(cfg, _user_config())
    before = json.loads(cfg.read_text(encoding="utf-8"))
    ok, msgs = w.wire_enable(None, tmp_path, CAP, probe=False)
    assert ok, msgs
    after = json.loads(cfg.read_text(encoding="utf-8"))
    assert after["mcpServers"]["user-notes"] == before["mcpServers"]["user-notes"]
    assert after["someUserKey"] == before["someUserKey"]
    assert w.SERVER_KEY_DEFAULT in after["mcpServers"]
    raw = cfg.read_text(encoding="utf-8")
    assert '\n    "mcpServers"' in raw, "4-space indentation of the user file must survive"


def test_enable_is_idempotent(tmp_path, env):
    cfg = tmp_path / ".mcp.json"
    _write(cfg, _user_config())
    assert w.wire_enable(None, tmp_path, CAP, probe=False)[0]
    first = cfg.read_text(encoding="utf-8")
    ok, msgs = w.wire_enable(None, tmp_path, CAP, probe=False)
    assert ok and any("幂等" in m for m in msgs)
    assert cfg.read_text(encoding="utf-8") == first
    assert list(json.loads(first)["mcpServers"]).count(w.SERVER_KEY_DEFAULT) == 1


def test_enable_refreshes_a_stale_managed_entry(tmp_path, env):
    cfg = tmp_path / ".mcp.json"
    _write(cfg, {"mcpServers": {w.SERVER_KEY_DEFAULT:
                                {"command": "npx", "args": ["@playwright/mcp@latest"]}}})
    ok, msgs = w.wire_enable(None, tmp_path, CAP, probe=False)
    assert ok and any("更新托管条目" in m for m in msgs)
    assert json.loads(cfg.read_text(encoding="utf-8"))["mcpServers"][w.SERVER_KEY_DEFAULT] \
        == w.canonical_entry(CAP)


def test_disable_removes_only_managed_entry(tmp_path, env):
    cfg = tmp_path / ".mcp.json"
    _write(cfg, _user_config())
    assert w.wire_enable(None, tmp_path, CAP, probe=False)[0]
    ok, msgs = w.wire_disable(tmp_path, CAP)
    assert ok
    doc = json.loads(cfg.read_text(encoding="utf-8"))
    assert w.SERVER_KEY_DEFAULT not in doc["mcpServers"]
    assert doc["mcpServers"]["user-notes"] == _user_config()["mcpServers"]["user-notes"]
    assert doc["someUserKey"] == _user_config()["someUserKey"]
    assert w.wire_status(tmp_path, CAP)["state"] == w.STATE_INSTALLED_NOT_ENABLED


def test_disable_drops_a_file_we_created_and_keeps_a_users_file(tmp_path, env):
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    assert w.wire_enable(None, fresh, CAP, probe=False)[0]
    assert (fresh / ".mcp.json").is_file()
    assert w.wire_disable(fresh, CAP)[0]
    assert not (fresh / ".mcp.json").exists(), "file we created, and which is now empty, goes"

    kept = tmp_path / "kept"
    kept.mkdir()
    _write(kept / ".mcp.json", _user_config())
    assert w.wire_enable(None, kept, CAP, probe=False)[0]
    assert w.wire_disable(kept, CAP)[0]
    assert (kept / ".mcp.json").is_file(), "a user's file is never deleted"
    assert (kept / ".mcp.json").read_text(encoding="utf-8") == \
        json.dumps(_user_config(), indent=4, ensure_ascii=False) + "\n"


def test_disable_on_missing_config_is_a_no_op(tmp_path, env):
    ok, msgs = w.wire_disable(tmp_path, CAP)
    assert ok and any("无可移除" in m for m in msgs)
    assert not (tmp_path / ".mcp.json").exists()


def test_disable_reports_when_it_does_not_find_our_key(tmp_path, env):
    _write(tmp_path / ".mcp.json", _user_config())
    ok, msgs = w.wire_disable(tmp_path, CAP)
    assert ok and any("无托管条目" in m and "未触碰" in m for m in msgs)
    assert (tmp_path / ".mcp.json").read_text(encoding="utf-8") == \
        json.dumps(_user_config(), indent=4, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- fail closed

def test_corrupt_json_is_never_rewritten(tmp_path, env):
    cfg = tmp_path / ".mcp.json"
    cfg.write_text('{"mcpServers": {"x": }', encoding="utf-8")
    before = cfg.read_text(encoding="utf-8")
    ok, msgs = w.wire_enable(None, tmp_path, CAP, probe=False)
    assert ok is False and any("拒绝改写用户配置" in m for m in msgs)
    assert cfg.read_text(encoding="utf-8") == before
    ok, _ = w.wire_disable(tmp_path, CAP)
    assert ok is False
    assert cfg.read_text(encoding="utf-8") == before
    st = w.wire_status(tmp_path, CAP)
    assert st["state"] == w.STATE_ENABLED_NOT_CONNECTED and "合法 JSON" in st["detail"]


def test_foreign_shapes_are_refused(tmp_path, env):
    for bad in ([1, 2, 3], {"mcpServers": ["not", "an", "object"]}):
        cfg = tmp_path / ".mcp.json"
        _write(cfg, bad)
        before = cfg.read_text(encoding="utf-8")
        ok, msgs = w.wire_enable(None, tmp_path, CAP, probe=False)
        assert ok is False, bad
        assert cfg.read_text(encoding="utf-8") == before


def test_illegal_server_key_prefix_fails_closed(tmp_path, env):
    cap = {"id": "x", "wiring_action": {"type": "mcp-config", "server_key": "playwright"}}
    ok, msgs = w.wire_enable(None, tmp_path, cap, probe=False)
    assert ok is False and any("aiwb-" in m for m in msgs)
    assert not (tmp_path / ".mcp.json").exists()


def test_path_traversal_in_file_field_fails_closed(tmp_path, env):
    cap = {"id": "x", "wiring_action": {"type": "mcp-config", "file": "../escape.json"}}
    ok, msgs = w.wire_enable(None, tmp_path, cap, probe=False)
    assert ok is False and any("非法配置文件名" in m for m in msgs)
    assert not (tmp_path.parent / "escape.json").exists()


def test_corrupt_wiring_state_fails_closed(tmp_path, env):
    (tmp_path / "harness-data").mkdir()
    (tmp_path / "harness-data" / "mcp-wiring.json").write_text("{oops", encoding="utf-8")
    st = w.wire_status(tmp_path, CAP)
    assert st["state"] == w.STATE_NOT_INSTALLED and "损坏" in st["detail"]
    ok, msgs = w.wire_enable(None, tmp_path, CAP, probe=False)
    assert ok is False and any("状态文件损坏" in m for m in msgs)
    assert not (tmp_path / ".mcp.json").exists()
    ok, msgs = w.wire_disable(tmp_path, CAP)
    assert ok is False and any("状态文件损坏" in m for m in msgs)


def test_status_never_raises_on_unusable_target(tmp_path, env):
    st = w.wire_status(tmp_path / "does-not-exist", CAP)
    assert st["state"] == w.STATE_NOT_INSTALLED
    assert "不存在" in st["detail"]


# ---------------------------------------------------------------- misc

def test_server_key_is_namespaced_and_configurable(tmp_path, env):
    cap = {"id": "playwright-mcp", "wiring_action": {"type": "mcp-config",
                                                     "server_key": "aiwb-pw-2"}}
    assert w.wire_enable(None, tmp_path, cap, probe=False)[0]
    assert "aiwb-pw-2" in json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]


def test_state_records_project_root_and_ownership(tmp_path, env):
    sub = tmp_path / "project"
    sub.mkdir()
    assert w.wire_enable(None, tmp_path, CAP, project_root=sub, probe=False)[0]
    assert (sub / ".mcp.json").is_file()
    assert not (tmp_path / ".mcp.json").exists()
    rec = json.loads((tmp_path / "harness-data" / "mcp-wiring.json").read_text(encoding="utf-8"))
    assert rec["playwright-mcp"]["project_root"] == str(sub)
    assert rec["playwright-mcp"]["created_file"] is True
    assert w.wire_status(tmp_path, CAP)["state"] in (w.STATE_CONNECTED_TESTED,
                                                     w.STATE_ENABLED_UNPROBED)
    assert w.wire_disable(tmp_path, CAP)[0]
    assert not (sub / ".mcp.json").exists()


def test_entry_hash_recorded_matches_written_entry(tmp_path, env):
    assert w.wire_enable(None, tmp_path, CAP, probe=False)[0]
    rec = json.loads((tmp_path / "harness-data" / "mcp-wiring.json").read_text(encoding="utf-8"))
    entry = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][w.SERVER_KEY_DEFAULT]
    assert rec["playwright-mcp"]["entry_hash"] == w._entry_hash(entry)


def test_uninstall_sweep_removes_managed_entry_only(tmp_path, env):
    cfg = tmp_path / ".mcp.json"
    _write(cfg, _user_config())
    assert w.wire_enable(None, tmp_path, CAP, probe=False)[0]
    ok, msgs = w.wire_uninstall_sweep(tmp_path)
    assert ok and any("移除托管条目" in m for m in msgs)
    doc = json.loads(cfg.read_text(encoding="utf-8"))
    assert w.SERVER_KEY_DEFAULT not in doc["mcpServers"]
    assert doc["mcpServers"]["user-notes"]["command"] == "node"


def test_paths_with_spaces_and_cjk(tmp_path, monkeypatch):
    """Windows + CJK + spaces: the whole lifecycle must survive."""
    monkeypatch.setattr(w, "probe_runtime", lambda root, cap, **kw: _runtime())
    monkeypatch.setattr(w, "mcp_handshake",
                        lambda argv, **kw: {"ok": True, "detail": "ok", "tools": ["t"],
                                            "stderr": ""})
    target = tmp_path / "工作台 目标 目录"
    project = tmp_path / "我的 项目 dir"
    target.mkdir()
    project.mkdir()
    ok, msgs = w.wire_enable(None, target, CAP, project_root=project, probe=False)
    assert ok, msgs
    assert (project / ".mcp.json").is_file()
    assert w.wire_status(target, CAP)["state"] == w.STATE_CONNECTED_TESTED
    assert w.wire_disable(target, CAP)[0]
    assert not (project / ".mcp.json").exists()


# ---------------------------------------------------------------- browser probe

def test_browser_channel_read_from_args():
    assert w.browser_channel(CAP) == "chromium"
    assert w.browser_channel({"wiring_action": {"type": "mcp-config",
                                                "args": ["--headless", "--browser", "msedge"]}}) == "msedge"
    assert w.browser_channel({"wiring_action": {"type": "mcp-config", "args": []}}) is None


def test_channel_probe_checks_system_browser_not_the_cache(tmp_path, monkeypatch):
    """A `--browser chrome` entry needs no Playwright download — the readiness
    gate must look at the system browser, or it would refuse a working setup."""
    fake = tmp_path / "chrome.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setitem(w._SYSTEM_CHANNEL_CANDIDATES, "chrome", {"win32": [str(fake)],
                                                                 "darwin": [str(fake)],
                                                                 "linux": [str(fake)]})
    monkeypatch.setattr(w, "chromium_probe", lambda: pytest.fail("cache must not be consulted"))
    cap = {"id": "playwright-mcp",
           "wiring_action": {"type": "mcp-config", "args": ["--headless", "--browser", "chrome"]}}
    got = w.browser_probe(cap)
    assert got["ok"] is True and got["channel"] == "chrome"


def test_chromium_entry_falls_back_to_the_playwright_cache(monkeypatch):
    monkeypatch.setattr(w, "chromium_probe",
                        lambda: {"ok": True, "detail": "stub cache", "dirs": ["chromium-1247"]})
    got = w.browser_probe(CAP)
    assert got["ok"] is True and got["channel"] == "chromium"


def test_channel_entry_passes_the_browser_gate_without_allow_flag(tmp_path, monkeypatch):
    fake = tmp_path / "msedge.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setitem(w._SYSTEM_CHANNEL_CANDIDATES, "msedge", {"win32": [str(fake)],
                                                                 "darwin": [str(fake)],
                                                                 "linux": [str(fake)]})
    monkeypatch.setattr(w, "probe_runtime", lambda root, cap, **kw: _runtime())
    monkeypatch.setattr(w, "mcp_handshake",
                        lambda argv, **kw: {"ok": True, "detail": "ok", "tools": ["t"],
                                            "stderr": ""})
    cap = {"id": "playwright-mcp",
           "wiring_action": {"type": "mcp-config", "args": ["--headless", "--browser", "msedge"]}}
    ok, msgs = w.wire_enable(None, tmp_path, cap, probe=False)
    assert ok is True, msgs
    assert json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][w.SERVER_KEY_DEFAULT]["args"][-1] == "msedge"


# ---------------------------------------------------------------- dispatch hook

def test_dispatch_returns_none_for_other_wiring_types(tmp_path, env):
    assert w.dispatch("enable", None, tmp_path,
                      {"id": "x", "wiring_action": {"type": "skill-file"}}) is None
    assert w.dispatch("enable", None, tmp_path, {"id": "y"}) is None


def test_dispatch_contract_for_capability_py(tmp_path, env):
    ok, msgs = w.dispatch("enable", None, tmp_path, CAP, probe=False)
    assert ok is True and isinstance(msgs, list)
    ok, msgs = w.dispatch("status", None, tmp_path, CAP)
    assert ok is True and any(m.startswith("status=") for m in msgs)
    ok, msgs = w.dispatch("disable", None, tmp_path, CAP)
    assert ok is True and isinstance(msgs, list)
    assert not (tmp_path / ".mcp.json").exists()


# ---------------------------------------------------------------- CLI

def test_cli_status_json_shape(tmp_path):
    import subprocess
    r = subprocess.run([sys.executable, str(RC_ROOT / "tools" / "wiring_mcp.py"),
                        "status", "--target", str(tmp_path), "--no-probe", "--json"],
                       capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    st = json.loads(r.stdout)
    assert st["state"] in (w.STATE_NOT_INSTALLED, w.STATE_INSTALLED_NOT_ENABLED,
                           w.STATE_ENABLED_NOT_CONNECTED, w.STATE_CONNECTED_TESTED,
                           w.STATE_ENABLED_UNPROBED)
    assert set(st) >= {"id", "state", "detail", "probed", "project_root", "config"}


def test_cli_enable_fails_closed_with_an_empty_path(tmp_path):
    """Hermetic CLI check of the readiness gate: no node on PATH -> refuse."""
    import subprocess
    bin_dir = tmp_path / "emptybin"
    bin_dir.mkdir()
    target = tmp_path / "t"
    target.mkdir()
    r = subprocess.run([sys.executable, str(RC_ROOT / "tools" / "wiring_mcp.py"),
                        "enable", "--target", str(target),
                        "--no-probe"],
                       capture_output=True, text=True, encoding="utf-8", timeout=180,
                       env={**os.environ, "PATH": str(bin_dir)})
    assert r.returncode == 1, r.stdout + r.stderr
    assert "未就绪" in r.stdout and "node" in r.stdout
    assert not (tmp_path / "t" / ".mcp.json").exists()
    assert not (tmp_path / "t" / "harness-data" / "mcp-wiring.json").exists()


# ---------------------------------------------------------------- skill half

SKILL_CAP = {"id": "playwright-mcp", "wiring_action": {
    "type": "mcp-config", "template": "playwright-mcp.skill.md",
    "dest": ".claude/skills/aiwb-playwright-mcp/SKILL.md"}}


def test_shipped_skill_template_exists_and_is_hygienic():
    """The template the registry will point at must exist and stay generic."""
    t = RC_ROOT / "capabilities" / "wiring" / "playwright-mcp.skill.md"
    assert t.is_file()
    raw = t.read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    assert "\nname: aiwb-" in raw and "\ndescription: " in raw
    for frag in ("F:\\", "F:/", "C:\\", "C:/", "/Users/", "/home/", "14679"):
        assert frag not in raw, f"机器相关片段: {frag}"


def test_enable_writes_skill_file_with_marker(tmp_path, env):
    target = tmp_path / "t"
    target.mkdir()
    ok, msgs = w.wire_enable(RC_ROOT, target, SKILL_CAP, project_root=target,
                             probe=False)
    assert ok, msgs
    dest = target / ".claude" / "skills" / "aiwb-playwright-mcp" / "SKILL.md"
    assert dest.is_file()
    assert dest.read_text(encoding="utf-8").startswith(
        "<!-- aiwb-managed:playwright-mcp -->\n")
    assert any("SKILL.md" in m for m in msgs)
    st = w.wire_status(target, SKILL_CAP, project_root=target, probe=False)
    assert st["skill"] == ".claude/skills/aiwb-playwright-mcp/SKILL.md"
    assert st["skill_present"] is True


def test_enable_is_idempotent_for_the_skill_file(tmp_path, env):
    target = tmp_path / "t"
    target.mkdir()
    w.wire_enable(RC_ROOT, target, SKILL_CAP, project_root=target, probe=False)
    dest = target / ".claude" / "skills" / "aiwb-playwright-mcp" / "SKILL.md"
    first = dest.read_text(encoding="utf-8")
    ok, msgs = w.wire_enable(RC_ROOT, target, SKILL_CAP, project_root=target,
                             probe=False)
    assert ok and dest.read_text(encoding="utf-8") == first
    assert any("幂等" in m for m in msgs), msgs


def test_enable_refuses_when_template_is_missing(tmp_path, env):
    """Declared-but-absent template = broken install -> nothing is written."""
    rc = tmp_path / "rc"
    (rc / "capabilities" / "wiring").mkdir(parents=True)
    target = tmp_path / "t"
    target.mkdir()
    ok, msgs = w.wire_enable(rc, target, SKILL_CAP, project_root=target, probe=False)
    assert not ok
    assert any("接线模板缺失" in m for m in msgs), msgs
    assert not (target / ".mcp.json").exists()
    assert not (target / ".claude").exists()


def test_disable_removes_the_managed_skill_file(tmp_path, env):
    target = tmp_path / "t"
    target.mkdir()
    w.wire_enable(RC_ROOT, target, SKILL_CAP, project_root=target, probe=False)
    ok, msgs = w.wire_disable(target, SKILL_CAP, project_root=target)
    assert ok, msgs
    assert not (target / ".claude" / "skills" / "aiwb-playwright-mcp" / "SKILL.md").exists()
    assert not (target / ".mcp.json").exists()


def test_disable_keeps_a_skill_file_the_user_edited(tmp_path, env):
    """Marker gone = not ours any more; never delete someone's edited file."""
    target = tmp_path / "t"
    target.mkdir()
    w.wire_enable(RC_ROOT, target, SKILL_CAP, project_root=target, probe=False)
    dest = target / ".claude" / "skills" / "aiwb-playwright-mcp" / "SKILL.md"
    dest.write_text("# my own notes\n", encoding="utf-8")
    ok, msgs = w.wire_disable(target, SKILL_CAP, project_root=target)
    assert ok, msgs
    assert dest.is_file() and dest.read_text(encoding="utf-8") == "# my own notes\n"
    assert any("保留" in m for m in msgs), msgs


def test_skill_dest_outside_claude_is_refused(tmp_path, env):
    bad = {"id": "playwright-mcp", "wiring_action": {
        "type": "mcp-config", "template": "playwright-mcp.skill.md",
        "dest": "../../etc/SKILL.md"}}
    target = tmp_path / "t"
    target.mkdir()
    ok, msgs = w.wire_enable(RC_ROOT, target, bad, project_root=target, probe=False)
    assert not ok and any(".claude/" in m for m in msgs), msgs
    assert not (target / ".mcp.json").exists()
    assert w.skill_template({"id": "x", "wiring_action": {"type": "mcp-config"}}) is None


def test_status_reports_missing_skill_without_touching_it(tmp_path, env):
    target = tmp_path / "t"
    target.mkdir()
    w.wire_enable(RC_ROOT, target, SKILL_CAP, project_root=target, probe=False)
    (target / ".claude" / "skills" / "aiwb-playwright-mcp" / "SKILL.md").unlink()
    st = w.wire_status(target, SKILL_CAP, project_root=target, probe=False)
    assert st["skill_present"] is False
    assert st["state"] == w.STATE_ENABLED_UNPROBED
