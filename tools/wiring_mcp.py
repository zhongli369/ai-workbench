#!/usr/bin/env python3
"""mcp-config wiring (v1.2): a third wiring type for the capability registry.

Existing wiring types (tools/capability.py):
  - "active"          wired by install itself
  - "skill-file"      enable writes a managed SKILL.md into the target
  - "recorded-intent" enable only records operator intent
This module adds:
  - "mcp-config"      enable writes ONE managed entry into the target project's
                      native Claude Code project-level MCP config (.mcp.json),
                      disable removes exactly that entry. The same
                      wiring_action may also declare `template` + `dest` to get
                      the skill-file half (a marked SKILL.md under .claude/),
                      so one dispatch call wires both.

Contract (all four points are tested in tests/test_wiring_mcp.py):

  1. Default OFF. Importing this module starts nothing, spawns nothing, and
     writes nothing. Only an explicit enable()/`enable` CLI call mutates disk.
  2. Readiness gate, never auto-install. enable() refuses unless node + npm +
     the pinned package are already resolvable WITHOUT network
     (`npx --no-install <pkg>@<pin>`); the browser is checked the same way by
     default (--allow-missing-browser relaxes that one). The workbench never
     downloads a package or a browser on its own.
  3. Owns-only mutation. The managed entry lives under a reserved server key
     (default "aiwb-playwright"). Every other key in .mcp.json — other MCP
     servers, other top-level keys — is preserved byte-for-byte in value, and
     an unparsable or foreign-shaped .mcp.json is never repaired, only refused.
  4. Four-state status, honestly labelled:
       not-installed         node/npm/pinned package (/browser) not ready
       installed-not-enabled  ready, but no managed entry in .mcp.json
       enabled-not-connected  entry present, MCP handshake failed
       connected-tested       entry present, handshake passed (initialize +
                              tools/list answered by the real server process)
     connected-tested means "this command line spoke MCP just now" — it is a
     wiring verdict, not a promise that a page will render.

CLI (also importable as functions — see wire_enable/wire_disable/wire_status/
dispatch at the bottom):
  python tools/wiring_mcp.py status  --target <dir> [--json] [--no-probe]
  python tools/wiring_mcp.py enable  --target <dir> [--no-probe]
                                     [--allow-missing-browser] [--project-root <dir>]
  python tools/wiring_mcp.py disable --target <dir> [--project-root <dir>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------- constants

WIRING_TYPE = "mcp-config"
SERVER_KEY_DEFAULT = "aiwb-playwright"
PACKAGE_DEFAULT = "@playwright/mcp"
# Pinned 2026-10-15 via `npm view @playwright/mcp version` -> 0.0.83.
# Never "latest": an unpinned browser server is an unpinned attack surface.
PIN_DEFAULT = "0.0.83"
CONFIG_FILE_DEFAULT = ".mcp.json"
STATE_NAME = "mcp-wiring.json"
# --isolated: profile stays in memory (no real browser profile, no imported
# cookies); --browser chromium: the Playwright-downloaded browser, not the
# user's installed Chrome; --headless: no window pops up during agent runs.
SERVER_ARGS_DEFAULT = ["--headless", "--isolated", "--browser", "chromium"]

STATE_NOT_INSTALLED = "not-installed"
STATE_INSTALLED_NOT_ENABLED = "installed-not-enabled"
STATE_ENABLED_NOT_CONNECTED = "enabled-not-connected"
STATE_CONNECTED_TESTED = "connected-tested"
# Escape hatch only (`--no-probe`): NOT one of the four canonical verdicts,
# because "we did not ask" is not the same claim as "it did not answer".
STATE_ENABLED_UNPROBED = "enabled-unprobed"

MCP_PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "aiwb-wiring-probe"
CLIENT_VERSION = "1.0.0"

CMD_TIMEOUT_DEFAULT = 40.0
PROBE_TIMEOUT_DEFAULT = 90.0
_BARE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# Same literal as tools/capability.py so a skill file written by either wiring
# type is recognisable (and removable) by both.
_MARKER = "<!-- aiwb-managed:{id} -->"


class WiringError(Exception):
    """Fail-closed condition: something is not ours to touch or not safe to guess."""


# ---------------------------------------------------------------- npx launcher

def npx_argv(*args: str) -> list[str]:
    """Prefix an npx invocation for the CURRENT OS.

    On Windows the npm shims are .cmd files and CreateProcess cannot exec them,
    so a bare ["npx", ...] fails with WinError 2 (verified 2026-10-15 on
    node v24.15.0 / npm 10.9.0). `cmd /c npx ...` is also the spelling that
    works when Claude Code spawns the same argv from .mcp.json.
    """
    if os.name == "nt":
        return ["cmd", "/c", "npx", *args]
    return ["npx", *args]


def _no_window() -> dict:
    """Keep probe subprocesses from flashing a console window on Windows."""
    if os.name == "nt":
        return {"creationflags": 0x08000000}
    return {}


def _run(argv: list[str], *, cwd: Path | None = None, timeout: float = CMD_TIMEOUT_DEFAULT) -> dict:
    """Run a short command, never raise: {rc, out, err, timeout}."""
    try:
        p = subprocess.run(argv, cwd=str(cwd) if cwd else None, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, **_no_window())
        return {"rc": p.returncode, "out": p.stdout.strip(), "err": p.stderr.strip(),
                "timeout": False}
    except subprocess.TimeoutExpired:
        return {"rc": None, "out": "", "err": f"超时 ({timeout:.0f}s)", "timeout": True}
    except OSError as e:
        return {"rc": None, "out": "", "err": f"{type(e).__name__}: {e}", "timeout": False}


# ---------------------------------------------------------------- wiring_action

def _wa(cap: dict) -> dict:
    wa = cap.get("wiring_action") or {}
    if not isinstance(wa, dict):
        raise WiringError("wiring_action 必须是对象")
    return wa


def server_key(cap: dict) -> str:
    key = str(_wa(cap).get("server_key", SERVER_KEY_DEFAULT))
    if not key.startswith("aiwb-"):
        raise WiringError(f"server_key 必须以 aiwb- 前缀保留命名空间: {key!r}")
    return key


def config_relname(cap: dict) -> str:
    """Config file name, constrained to a bare file name at the project root."""
    name = str(_wa(cap).get("file", CONFIG_FILE_DEFAULT))
    if not _BARE_NAME_RE.match(name) or ".." in name:
        raise WiringError(f"非法配置文件名: {name!r} (只允许项目根下的简单文件名)")
    return name


def canonical_entry(cap: dict) -> dict:
    """The exact MCP server entry this workbench owns for the capability."""
    wa = _wa(cap)
    package = str(wa.get("package", PACKAGE_DEFAULT))
    pin = str(wa.get("pin", PIN_DEFAULT))
    extra = list(wa.get("args", SERVER_ARGS_DEFAULT))
    argv = npx_argv("-y", f"{package}@{pin}", *extra)
    return {"command": argv[0], "args": argv[1:]}


def skill_template(cap: dict) -> str | None:
    """Optional SKILL.md template declared alongside the MCP entry.

    Enabling a browser server without telling the model how to drive it is a
    half-wire: the same wiring_action may therefore carry `template` + `dest`,
    exactly like the skill-file wiring type, and this module wires both.
    """
    wa = _wa(cap)
    tmpl, dest = wa.get("template"), wa.get("dest")
    if tmpl and dest:
        if not str(dest).startswith(".claude/"):
            raise WiringError(f"skill dest 必须位于 .claude/ 之下: {dest!r}")
        return str(tmpl)
    return None


def _manifest_path(target: Path) -> Path:
    return Path(target) / "install-manifest.json"


def _manifest_update(target: Path, path: Path, *, add: bool) -> None:
    """Keep the installer manifest in sync so owns-only uninstall sweeps the
    SKILL.md we wrote. Absent manifest (bare registry target) is a no-op."""
    mpath = _manifest_path(target)
    if not mpath.is_file():
        return
    try:
        m = json.loads(mpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    files = m.setdefault("files", [])
    entry = str(path)
    if add and entry not in files:
        files.append(entry)
    elif not add and entry in files:
        files.remove(entry)
    else:
        return
    mpath.write_text(json.dumps(m, indent=2), encoding="utf-8")


def wire_skill_file(rc_root, target: Path, cap: dict) -> tuple[bool, str]:
    tmpl = skill_template(cap)
    if not tmpl:
        return False, "未声明 skill 模板"
    src = Path(rc_root) / "capabilities" / "wiring" / tmpl
    if not src.is_file():
        return False, f"接线模板缺失: capabilities/wiring/{tmpl} (安装包不完整)"
    dest = Path(target) / str(_wa(cap)["dest"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.read_text(encoding="utf-8") if dest.is_file() else ""
    body = _MARKER.format(id=cap["id"]) + "\n" + src.read_text(encoding="utf-8")
    if existing == body:
        _manifest_update(target, dest, add=True)
        return True, f"{_wa(cap)['dest']} 已存在且一致 — 幂等, 未改动"
    dest.write_text(body, encoding="utf-8")
    _manifest_update(target, dest, add=True)
    return True, f"已接线: {_wa(cap)['dest']}"


def unwire_skill_file(target: Path, cap: dict) -> tuple[bool, str]:
    tmpl = skill_template(cap)
    if not tmpl:
        return True, "未声明 skill 模板 — 无需解除"
    dest = Path(target) / str(_wa(cap)["dest"])
    rel = _wa(cap)["dest"]
    if not dest.is_file():
        _manifest_update(target, dest, add=False)
        return True, f"{rel} (已不存在)"
    head = dest.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
    if head and head[0].strip() == _MARKER.format(id=cap["id"]):
        dest.unlink()
        _manifest_update(target, dest, add=False)
        try:
            dest.parent.rmdir()
        except OSError:
            pass
        return True, rel
    return False, f"{rel} 标记已被移除(可能被用户修改) — 保留, 请人工确认后删除"


def _entry_hash(entry: dict) -> str:
    return hashlib.sha256(
        json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


# ---------------------------------------------------------------- config file IO

def config_path(project_root: Path, cap: dict) -> Path:
    return Path(project_root) / config_relname(cap)


def load_config(path: Path) -> tuple[dict, str, bool]:
    """Return (doc, indent, existed_nonempty). Fail closed on anything unusual."""
    if not path.exists():
        return {}, "  ", False
    raw = path.read_text(encoding="utf-8")
    if raw.strip() == "":
        return {}, "  ", False
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise WiringError(f"{path.name} 不是合法 JSON ({e}) — 拒绝改写用户配置, 请先人工修复") from e
    if not isinstance(doc, dict):
        raise WiringError(f"{path.name} 顶层不是对象 — 拒绝改写用户配置")
    servers = doc.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        raise WiringError(f'{path.name} 的 "mcpServers" 不是对象 — 拒绝改写用户配置')
    return doc, _detect_indent(raw), True


def _detect_indent(raw: str) -> str:
    for line in raw.splitlines():
        m = re.match(r"^([ \t]+)\S", line)
        if m:
            return "\t" if m.group(1).startswith("\t") else m.group(1)
    return "  "


def save_config(path: Path, doc: dict, indent: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")


def upsert_entry(path: Path, cap: dict) -> tuple[bool, str]:
    """Insert/refresh ONLY the managed key. Returns (changed, message)."""
    doc, indent, _ = load_config(path)
    key = server_key(cap)
    entry = canonical_entry(cap)
    servers = doc.setdefault("mcpServers", {})
    current = servers.get(key)
    if current == entry:
        return False, f"{path.name} 已存在等价条目 {key} — 幂等, 未改动"
    servers[key] = entry
    save_config(path, doc, indent)
    if current is None:
        return True, f"{path.name}: 新增托管条目 {key}"
    return True, f"{path.name}: 更新托管条目 {key} (旧值已被用户或旧版本修改)"


def remove_entry(path: Path, cap: dict, *, drop_empty_file: bool = False) -> tuple[bool, str]:
    """Remove ONLY the managed key. Everything else in the file is untouched."""
    if not path.exists():
        return False, f"{path.name} 不存在 — 无可移除"
    doc, indent, _ = load_config(path)
    key = server_key(cap)
    servers = doc.get("mcpServers") or {}
    if key not in servers:
        return False, f"{path.name} 中无托管条目 {key} — 未触碰任何用户配置"
    entry = servers.pop(key)
    modified = entry != canonical_entry(cap)
    doc["mcpServers"] = servers
    emptied = not servers and set(doc.keys()) == {"mcpServers"}
    if emptied and drop_empty_file:
        path.unlink()
        return True, f"{path.name}: 移除托管条目 {key}; 文件已空且由本工作台创建 → 一并删除"
    save_config(path, doc, indent)
    note = " (条目曾被用户改过参数 — 仍在 aiwb- 保留命名空间内, 按约定移除)" if modified else ""
    return True, f"{path.name}: 移除托管条目 {key}{note}"


def managed_entry_of(project_root: Path, cap: dict) -> dict | None:
    try:
        doc, _, _ = load_config(config_path(project_root, cap))
    except WiringError:
        return None
    servers = doc.get("mcpServers") or {}
    got = servers.get(server_key(cap))
    return got if isinstance(got, dict) else None


# ---------------------------------------------------------------- runtime probe

def browsers_dir() -> Path:
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def chromium_probe() -> dict:
    """Heuristic (offline): a chromium*/chromium_headless_shell* dir in the cache."""
    d = browsers_dir()
    if not d.is_dir():
        return {"ok": False, "detail": f"浏览器缓存目录不存在: {d}", "dirs": []}
    found = sorted(p.name for p in d.iterdir()
                   if p.is_dir() and p.name.startswith(("chromium-", "chromium_headless_shell-")))
    if not found:
        return {"ok": False, "detail": f"{d} 内无 chromium*/chromium_headless_shell*", "dirs": []}
    return {"ok": True, "detail": f"{d}: {', '.join(found)}", "dirs": found}


_SYSTEM_CHANNEL_CANDIDATES = {
    # channel -> typical install locations (per OS). A channel entry never needs
    # the Playwright browser download, so the readiness check must look here.
    "chrome": {
        "win32": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
        "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
        "linux": ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"],
    },
    "msedge": {
        "win32": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                  r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
        "darwin": ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
        "linux": ["/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable"],
    },
}


def browser_channel(cap: dict) -> str | None:
    """The `--browser` value the managed entry would use, if any."""
    args = list(_wa(cap).get("args", SERVER_ARGS_DEFAULT))
    if "--browser" in args and args.index("--browser") + 1 < len(args):
        return str(args[args.index("--browser") + 1])
    return None


def browser_probe(cap: dict) -> dict:
    """Readiness of whichever browser the entry is configured to drive."""
    channel = browser_channel(cap)
    plat = "win32" if os.name == "nt" else ("darwin" if sys.platform == "darwin" else "linux")
    if channel in _SYSTEM_CHANNEL_CANDIDATES:
        for cand in _SYSTEM_CHANNEL_CANDIDATES[channel].get(plat, []):
            if Path(cand).is_file():
                return {"ok": True, "dirs": [cand], "channel": channel,
                        "detail": f"系统 {channel}: {cand}"}
        if plat == "win32":
            for name in ("chrome.exe", "msedge.exe"):
                found = shutil.which(name)
                if found and name.startswith(channel[:4]):
                    return {"ok": True, "dirs": [found], "channel": channel,
                            "detail": f"系统 {channel}: {found} (PATH)"}
        return {"ok": False, "dirs": [], "channel": channel,
                "detail": f"未找到系统 {channel} (channel 模式不需要 Playwright 下载)"}
    out = chromium_probe()
    out["channel"] = channel or "chromium"
    return out


def _local_package(project_root: Path, package: str, pin: str) -> tuple[Path | None, str]:
    """A pinned local install inside the project, if any (fast + offline)."""
    pkgdir = Path(project_root) / "node_modules" / Path(*package.split("/"))
    meta = pkgdir / "package.json"
    cli = pkgdir / "cli.js"
    if not meta.is_file() or not cli.is_file():
        return None, ""
    try:
        version = str(json.loads(meta.read_text(encoding="utf-8")).get("version", ""))
    except (json.JSONDecodeError, OSError):
        return None, ""
    return (cli, version) if version == pin else (None, version)


def probe_runtime(project_root: Path, cap: dict, *, timeout: float = CMD_TIMEOUT_DEFAULT) -> dict:
    """Offline readiness of node / npm / pinned package / browser."""
    wa = _wa(cap)
    package = str(wa.get("package", PACKAGE_DEFAULT))
    pin = str(wa.get("pin", PIN_DEFAULT))
    node_path = shutil.which("node")
    npm_path = shutil.which("npm") or shutil.which("npm.cmd")
    node_v = _run(["node", "--version"], timeout=timeout)["out"] if node_path else ""
    npm_v = ""
    if npm_path:
        npm_v = (_run(npx_argv("--version") if os.name == "nt" else ["npm", "--version"],
                      timeout=timeout)["out"]) or ""
    local_cli, local_ver = _local_package(project_root, package, pin)
    pkg = {"ok": False, "mode": "missing", "version": None, "detail": ""}
    if local_cli:
        pkg.update(ok=True, mode="local", version=pin, detail=f"项目内 node_modules 已装 {pin}")
    else:
        r = _run(npx_argv("--no-install", f"{package}@{pin}", "--version"), timeout=timeout)
        if r["rc"] == 0:
            pkg.update(ok=True, mode="npx-cache", version=pin,
                       detail=f"npx 缓存可离线解析 {package}@{pin}")
        else:
            stale = f" (项目内装的是 {local_ver}, 不是 pin {pin})" if local_ver else ""
            pkg.update(detail=f"未解析到 {package}@{pin}{stale}: {r['err'][:160]}")
    missing = []
    if not node_path:
        missing.append("node")
    if not npm_path:
        missing.append("npm")
    if not pkg["ok"]:
        missing.append(f"包 {package}@{pin}")
    browser = browser_probe(cap)
    return {
        "node": {"ok": bool(node_path), "path": node_path or "", "version": node_v},
        "npm": {"ok": bool(npm_path), "path": npm_path or "", "version": npm_v},
        "package": pkg,
        "browser": browser,
        "local_cli": str(local_cli) if local_cli else None,
        "ready": bool(node_path and npm_path and pkg["ok"]),
        "missing": missing,
        "package_name": package,
        "pin": pin,
    }


# ---------------------------------------------------------------- MCP handshake

class _LineReader:
    """Line reader with deadlines (pipes are not selectable on Windows)."""

    def __init__(self, stream):
        self._q: queue.Queue = queue.Queue()
        self._t = threading.Thread(target=self._pump, args=(stream,), daemon=True)
        self._t.start()

    def _pump(self, stream):
        try:
            for line in stream:
                self._q.put(line)
        except Exception:  # pragma: no cover - stream torn down mid-read
            pass
        finally:
            self._q.put(None)

    def read_until(self, pred, deadline: float) -> tuple[dict | None, str, str]:
        """First decoded JSON object matching pred -> (obj, 'ok', '')."""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, "timeout", "等待响应超时"
            try:
                line = self._q.get(timeout=remaining)
            except queue.Empty:
                return None, "timeout", "等待响应超时"
            if line is None:
                return None, "eof", "服务进程已退出 (stdout EOF)"
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # non-JSON noise on stdout is not ours to interpret
            if isinstance(obj, dict) and pred(obj):
                return obj, "ok", ""


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, **_no_window())
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()


def mcp_handshake(argv: list[str], *, cwd: Path, timeout: float = PROBE_TIMEOUT_DEFAULT,
                  env: dict | None = None) -> dict:
    """Spawn the server over stdio; run initialize + tools/list; kill the tree.

    Returns {"ok", "detail", "tools", "stderr"} — never raises.
    """
    deadline = time.monotonic() + timeout
    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            bufsize=1, env=env, **_no_window())
    except OSError as e:
        return {"ok": False, "detail": f"无法启动 MCP 服务进程: {type(e).__name__}: {e}",
                "tools": [], "stderr": ""}
    reader = _LineReader(proc.stdout)
    errbuf = _LineReader(proc.stderr)
    try:
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": MCP_PROTOCOL_VERSION, "capabilities": {},
                           "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION}}}
        proc.stdin.write(json.dumps(init) + "\n")
        proc.stdin.flush()
        resp, why, msg = reader.read_until(lambda o: o.get("id") == 1, deadline)
        if resp is None:
            return _probe_fail(errbuf, f"initialize 未完成: {msg}", why, proc)
        if "error" in resp:
            return _probe_fail(errbuf, f"initialize 返回错误: {resp['error']}", "error", proc)
        server = (resp.get("result") or {}).get("serverInfo") or {}
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                                     "params": {}}) + "\n")
        proc.stdin.flush()
        resp2, why2, msg2 = reader.read_until(lambda o: o.get("id") == 2, deadline)
        if resp2 is None:
            return _probe_fail(errbuf, f"tools/list 未完成: {msg2}", why2, proc)
        if "error" in resp2:
            return _probe_fail(errbuf, f"tools/list 返回错误: {resp2['error']}", "error", proc)
        tools = [t.get("name") for t in (resp2.get("result") or {}).get("tools", [])
                 if isinstance(t, dict)]
        if not tools:
            return _probe_fail(errbuf, "tools/list 返回 0 个工具 — 视为未连接", "empty", proc)
        name = server.get("name", "?")
        ver = server.get("version", "?")
        return {"ok": True, "tools": tools, "stderr": _drain(errbuf),
                "detail": f"MCP 握手通过: {name} {ver}, tools/list -> {len(tools)} 个工具"}
    except (OSError, ValueError, BrokenPipeError) as e:
        return _probe_fail(errbuf, f"握手过程异常: {type(e).__name__}: {e}", "exception", proc)
    finally:
        _kill_tree(proc)


def _drain(errbuf: _LineReader, limit: int = 3) -> str:
    lines = []
    while len(lines) < limit:
        try:
            line = errbuf._q.get_nowait()
        except queue.Empty:
            break
        if line is None:
            break
        if line.strip():
            lines.append(line.strip())
    return " | ".join(lines)[:400]


def _probe_fail(errbuf: _LineReader, detail: str, why: str, proc) -> dict:
    stderr = _drain(errbuf)
    extra = f" | stderr: {stderr}" if stderr else ""
    return {"ok": False, "detail": detail + extra, "tools": [], "stderr": stderr, "why": why}


def entry_argv(project_root: Path, cap: dict) -> list[str] | None:
    """The actual command+args written in the managed entry, if well-formed.

    `status` must reflect what is really configured, not what the registry
    derives: a user-edited entry (still under the reserved aiwb- key) is
    probed as written. Returns None when the entry is absent or malformed.
    """
    try:
        doc, _, _ = load_config(config_path(project_root, cap))
    except WiringError:
        return None
    entry = (doc.get("mcpServers") or {}).get(server_key(cap))
    if not isinstance(entry, dict):
        return None
    cmd, args = entry.get("command"), entry.get("args")
    if isinstance(cmd, str) and isinstance(args, list) and all(isinstance(a, str) for a in args):
        return [cmd, *args]
    return None


def probe_argv(project_root: Path, cap: dict) -> list[str]:
    """Prefer a pinned local copy (fast, offline); else the pinned npx form."""
    wa = _wa(cap)
    package = str(wa.get("package", PACKAGE_DEFAULT))
    pin = str(wa.get("pin", PIN_DEFAULT))
    extra = list(wa.get("args", SERVER_ARGS_DEFAULT))
    local_cli, _ = _local_package(project_root, package, pin)
    if local_cli:
        return ["node", str(local_cli), *extra]
    return npx_argv("-y", f"{package}@{pin}", *extra)


# ---------------------------------------------------------------- own state file

def _state_path(target: Path) -> Path:
    return Path(target) / "harness-data" / STATE_NAME


def load_state(target: Path) -> dict:
    p = _state_path(target)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_corrupt": True}
    return data if isinstance(data, dict) else {"_corrupt": True}


def _save_state(target: Path, state: dict) -> None:
    p = _state_path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- public API

def _resolve_project(target: Path, project_root: Path | None) -> Path:
    root = Path(project_root) if project_root else Path(target)
    if not root.is_dir():
        raise WiringError(f"项目根目录不存在: {root}")
    return root


def wire_enable(rc_root, target: Path, cap: dict, *, project_root: Path | None = None,
                probe: bool = True, allow_missing_browser: bool = False,
                timeout: float = PROBE_TIMEOUT_DEFAULT) -> tuple[bool, list[str]]:
    """Enable the capability by writing the managed MCP entry. Never installs."""
    msgs: list[str] = []
    try:
        target = Path(target)
        root = _resolve_project(target, project_root)
        rel = config_relname(cap)
        key = server_key(cap)
        # State corruption is checked BEFORE the first write: a broken bookkeeping
        # file must never cost the user a half-applied edit to their MCP config.
        state = load_state(target)
        if state.get("_corrupt"):
            msgs.append(f"[FAIL] 状态文件损坏: {_state_path(target)} — 拒绝覆盖, 请人工检查")
            return False, msgs
        # Same fail-closed precheck for the optional SKILL.md half of the wiring:
        # a declared-but-missing template is a broken install, not a warning.
        _tmpl = skill_template(cap)
        if _tmpl and not (Path(rc_root) / "capabilities" / "wiring" / _tmpl).is_file():
            msgs.append(f"[FAIL] 接线模板缺失: capabilities/wiring/{_tmpl} (安装包不完整)")
            return False, msgs
        rt = probe_runtime(root, cap)
        msgs.append(f"就绪检查: node={rt['node']['version'] or '缺失'} "
                    f"npm={rt['npm']['version'] or '缺失'} "
                    f"包={rt['package']['mode']} 浏览器={'ok' if rt['browser']['ok'] else '缺失'}")
        if not rt["ready"]:
            msgs.append(f"[FAIL] 未就绪: 缺 {', '.join(rt['missing'])}")
            msgs.append(f"       请先自行安装: npm install {rt['package_name']}@{rt['pin']} "
                        f"(或让 npx 缓存预热: npx -y {rt['package_name']}@{rt['pin']} --version)")
            msgs.append("       本工具从不自动安装外部软件 (与 skill-file 接线同一约定)")
            return False, msgs
        if not rt["browser"]["ok"] and not allow_missing_browser:
            msgs.append(f"[FAIL] 浏览器未就绪: {rt['browser']['detail']}")
            msgs.append(f"       请先自行安装: npx playwright install chromium "
                        f"(或加 --allow-missing-browser 明确接受无浏览器)")
            return False, msgs
        if not rt["browser"]["ok"]:
            msgs.append(f"[WARN] 浏览器缺失但已明确放行: {rt['browser']['detail']}")
        path = config_path(root, cap)
        created_file = not path.exists()
        changed, msg = upsert_entry(path, cap)
        msgs.append(("[OK] " if changed else "[OK] ") + msg)
        entry = canonical_entry(cap)
        state[cap["id"]] = {
            "project_root": str(root), "file": rel, "server_key": key,
            "package": rt["package_name"], "pin": rt["pin"],
            "entry_hash": _entry_hash(entry), "enabled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "created_file": created_file,
            "skill_dest": str(_wa(cap)["dest"]) if _tmpl else None,
        }
        _save_state(target, state)
        msgs.append(f"     配置: {path}")
        msgs.append(f"     条目: {key} -> {json.dumps(entry, ensure_ascii=False)}")
        if _tmpl:
            ok_skill, msg_skill = wire_skill_file(rc_root, target, cap)
            msgs.append(("[OK] " if ok_skill else "[WARN] ") + msg_skill)
        if probe:
            h = mcp_handshake(probe_argv(root, cap), cwd=root, timeout=timeout)
            msgs.append(("[OK] " if h["ok"] else "[WARN] ") + h["detail"])
            if not h["ok"]:
                msgs.append("       status 现在应为 enabled-not-connected; "
                            "工具调用会在首次连接时重试")
        else:
            msgs.append("[INFO] 跳过握手探测 (--no-probe): 连接性未验证")
        msgs.append("     注意: 项目级 MCP 服务器需在 Claude Code 会话中批准后方可生效 (/mcp)")
        return True, msgs
    except WiringError as e:
        msgs.append(f"[FAIL] {e}")
        return False, msgs


def wire_disable(target: Path, cap: dict, *, project_root: Path | None = None) -> tuple[bool, list[str]]:
    """Remove ONLY the managed entry; unknown user config is never touched."""
    msgs: list[str] = []
    try:
        target = Path(target)
        state = load_state(target)
        if state.get("_corrupt"):
            return False, [f"[FAIL] 状态文件损坏: {_state_path(target)} — 拒绝猜测, 请人工检查"]
        rec = state.get(cap["id"]) or {}
        root = Path(project_root) if project_root else Path(rec.get("project_root") or target)
        path = config_path(root, cap)
        changed, msg = remove_entry(path, cap, drop_empty_file=bool(rec.get("created_file")))
        msgs.append(("[OK] " if changed else "[OK] ") + msg)
        if not changed:
            msgs.append("       未触碰任何未托管条目 (owns-only)")
        if skill_template(cap):
            ok_skill, msg_skill = unwire_skill_file(target, cap)
            msgs.append(("[OK] " if ok_skill else "[WARN] ") + msg_skill)
        state.pop(cap["id"], None)
        _save_state(target, state)
        msgs.append("     registry 侧 intent 由 capability disable 记录 (harness-data/capability-state.json)")
        return True, msgs
    except WiringError as e:
        msgs.append(f"[FAIL] {e}")
        return False, msgs


def wire_status(target: Path, cap: dict, *, project_root: Path | None = None,
                probe: bool = True, timeout: float = PROBE_TIMEOUT_DEFAULT) -> dict:
    """Four-state verdict. Never raises; unusable input lands in not-installed."""
    target = Path(target)
    out = {"id": cap.get("id", "?"), "state": STATE_NOT_INSTALLED, "detail": "",
           "probed": False, "project_root": "", "config": "", "server_key": "",
           "skill": "", "skill_present": False, "tools": [], "runtime": {}}
    try:
        state = load_state(target)
        if state.get("_corrupt"):
            out.update(state=STATE_NOT_INSTALLED,
                       detail=f"状态文件损坏: {_state_path(target)} — 拒绝猜测")
            return out
        rec = state.get(cap.get("id")) or {}
        root = Path(project_root) if project_root else Path(rec.get("project_root") or target)
        out["project_root"] = str(root)
        out["server_key"] = server_key(cap)
        out["config"] = str(config_path(root, cap))
        if not root.is_dir():
            out.update(detail=f"项目根目录不存在: {root} — 尚未接线或目标已移动")
            return out
        if skill_template(cap):
            dest = Path(target) / str(_wa(cap)["dest"])
            out["skill"] = str(_wa(cap)["dest"])
            out["skill_present"] = dest.is_file()
            if out["skill_present"]:
                head = dest.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
                out["skill_present"] = bool(head and head[0].strip() == _MARKER.format(id=cap["id"]))
        rt = probe_runtime(root, cap)
        out["runtime"] = {
            "node": rt["node"]["version"], "npm": rt["npm"]["version"],
            "package": rt["package"]["mode"], "browser": rt["browser"]["ok"],
        }
        present, broken = _managed_state(root, cap)
        if not rt["ready"] or not rt["browser"]["ok"]:
            lack = list(rt["missing"])
            if not rt["browser"]["ok"]:
                lack.append("浏览器")
            suffix = " (托管条目已写入, 但环境仍不完整)" if present else ""
            out.update(state=STATE_NOT_INSTALLED,
                       detail=f"缺 {', '.join(lack)}; {rt['package']['detail']}{suffix}")
            return out
        if not present:
            out.update(state=STATE_INSTALLED_NOT_ENABLED,
                       detail=f"环境就绪; {Path(out['config']).name} 中无托管条目 {out['server_key']}")
            return out
        if broken:
            out.update(state=STATE_ENABLED_NOT_CONNECTED, detail=broken)
            return out
        if not probe:
            out.update(state=STATE_ENABLED_UNPROBED, probed=False,
                       detail="条目存在; 未探测连接性 (--no-probe) — 非四态判定")
            return out
        derived = probe_argv(root, cap)
        argv = entry_argv(root, cap) or derived
        entry_edited = argv != derived
        h = mcp_handshake(argv, cwd=root, timeout=timeout)
        out["probed"] = True
        out["tools"] = h["tools"]
        note = " (按 .mcp.json 实际条目探测)" if entry_edited else ""
        out.update(state=STATE_CONNECTED_TESTED if h["ok"] else STATE_ENABLED_NOT_CONNECTED,
                   detail=h["detail"] + note)
        return out
    except WiringError as e:
        out.update(state=STATE_NOT_INSTALLED, detail=f"{e}")
        return out


def _managed_state(root: Path, cap: dict) -> tuple[bool, str]:
    """(entry_present_and_parsable, broken_reason)."""
    path = config_path(root, cap)
    try:
        doc, _, _ = load_config(path)
    except WiringError as e:
        return True, f"{e}"
    entry = (doc.get("mcpServers") or {}).get(server_key(cap))
    if entry is None:
        return False, ""
    if not isinstance(entry, dict) or "command" not in entry:
        return True, f"{path.name} 的 {server_key(cap)} 不是合法 server 条目 (缺 command)"
    return True, ""


def wire_uninstall_sweep(target: Path) -> tuple[bool, list[str]]:
    """Optional 1-line hook for `workbench uninstall`: drop every managed entry."""
    target = Path(target)
    state = load_state(target)
    if not state or state.get("_corrupt"):
        return True, ["无 mcp-config 接线记录 — 未触碰任何配置"]
    msgs = []
    for cap_id, rec in list(state.items()):
        if not isinstance(rec, dict):
            continue
        root = Path(rec.get("project_root", target))
        path = root / str(rec.get("file", CONFIG_FILE_DEFAULT))
        key = str(rec.get("server_key", SERVER_KEY_DEFAULT))
        cap = {"id": cap_id, "wiring_action": {"type": WIRING_TYPE, "server_key": key,
                                               "file": str(rec.get("file", CONFIG_FILE_DEFAULT)),
                                               "package": rec.get("package", PACKAGE_DEFAULT),
                                               "pin": rec.get("pin", PIN_DEFAULT)}}
        try:
            ok, msg = remove_entry(path, cap, drop_empty_file=bool(rec.get("created_file")))
            msgs.append(("OK" if ok else "INFO") + f": {msg}")
        except WiringError as e:
            msgs.append(f"WARN: {e}")
        # SKILL.md half of the wiring: same owns-only rule — marker intact or kept.
        dest_rel = rec.get("skill_dest")
        if dest_rel:
            dest = target / str(dest_rel)
            if dest.is_file():
                head = dest.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
                if head and head[0].strip() == _MARKER.format(id=cap_id):
                    dest.unlink()
                    _manifest_update(target, dest, add=False)
                    msgs.append(f"OK: {dest_rel} (托管 skill 文件)")
                else:
                    msgs.append(f"WARN: {dest_rel} 标记已被移除 — 保留, 请人工确认")
    _save_state(target, {k: v for k, v in state.items() if k == "schema"})
    return True, msgs


# ---------------------------------------------------------------- capability.py hook

def dispatch(sub: str, rc_root, target: Path, cap: dict, **kw) -> tuple[bool, list[str]] | None:
    """One-call hook for tools/capability.py. Returns None when not our wiring type.

    capability.py 接线 (5 行以内):
        rl = wiring_mcp.dispatch(sub, rc_root, target, cap)
        if rl is not None:
            ok, msgs = rl
            for m in msgs: print("     " + m)
            if sub == "enable" and not ok: return 1
    """
    wa = cap.get("wiring_action") or {}
    if wa.get("type") != WIRING_TYPE:
        return None
    if sub == "enable":
        return wire_enable(rc_root, target, cap, **kw)
    if sub == "disable":
        return wire_disable(target, cap, **{k: v for k, v in kw.items()
                                            if k in ("project_root",)})
    if sub == "status":
        st = wire_status(target, cap, **{k: v for k, v in kw.items()
                                        if k in ("project_root", "probe", "timeout")})
        return True, [f"status={st['state']} — {st['detail']}"]
    return None


# ---------------------------------------------------------------- CLI

def _cap_from_args(args) -> dict:
    wa = {"type": WIRING_TYPE, "server_key": args.server_key,
          "package": args.package, "pin": args.pin, "file": args.file}
    if args.template:
        wa["template"], wa["dest"] = args.template, args.dest
    return {"id": args.id, "wiring_action": wa}


def _force_utf8_stdio() -> None:
    """Same guard as tools/workbench.py: CJK output must never crash print()
    on a cp1252 console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv=None) -> int:
    _force_utf8_stdio()
    ap = argparse.ArgumentParser(prog="wiring_mcp",
                                 description="mcp-config wiring (stdlib only): enable/disable/status")
    ap.add_argument("cmd", choices=["enable", "disable", "status"])
    ap.add_argument("--target", required=True, help="workbench 安装目标 (状态/项目解析基准)")
    ap.add_argument("--project-root", default=None, help="写入 .mcp.json 的项目根 (默认 = --target)")
    ap.add_argument("--id", default="playwright-mcp")
    ap.add_argument("--server-key", default=SERVER_KEY_DEFAULT)
    ap.add_argument("--package", default=PACKAGE_DEFAULT)
    ap.add_argument("--pin", default=PIN_DEFAULT)
    ap.add_argument("--file", default=CONFIG_FILE_DEFAULT)
    ap.add_argument("--template", default="playwright-mcp.skill.md",
                    help="capabilities/wiring/ 下的 SKILL.md 模板名 (空串=不写 skill)")
    ap.add_argument("--dest", default=".claude/skills/aiwb-playwright-mcp/SKILL.md")
    ap.add_argument("--rc-root", default=None, help="workbench 仓库根 (默认从本文件推断)")
    ap.add_argument("--no-probe", action="store_true", help="跳过 MCP 握手探测")
    ap.add_argument("--allow-missing-browser", action="store_true")
    ap.add_argument("--timeout", type=float, default=PROBE_TIMEOUT_DEFAULT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.template:
        args.template, args.dest = "", ""
    cap = _cap_from_args(args)
    rc_root = Path(args.rc_root) if args.rc_root else Path(__file__).resolve().parent.parent
    target = Path(args.target)
    root = Path(args.project_root) if args.project_root else None
    if args.cmd == "status":
        st = wire_status(target, cap, project_root=root, probe=not args.no_probe,
                         timeout=args.timeout)
        if args.json:
            print(json.dumps(st, ensure_ascii=False, indent=2))
        else:
            print(f"[{st['state']}] {st['id']} — {st['detail']}")
            if st["skill"]:
                print(f"     skill : {st['skill']} "
                      f"({'已接线' if st['skill_present'] else '缺失'})")
            if st["state"] in (STATE_NOT_INSTALLED, STATE_INSTALLED_NOT_ENABLED):
                print(f"     下一步: python {Path(__file__).name} enable --target \"{target}\"")
            elif st["state"] in (STATE_CONNECTED_TESTED, STATE_ENABLED_NOT_CONNECTED):
                print(f"     关闭  : python {Path(__file__).name} disable --target \"{target}\"")
        return 0
    fn = wire_enable if args.cmd == "enable" else wire_disable
    kw = {"project_root": root}
    if args.cmd == "enable":
        kw.update(probe=not args.no_probe, allow_missing_browser=args.allow_missing_browser,
                  timeout=args.timeout)
        ok, msgs = fn(rc_root, target, cap, **kw)
    else:
        ok, msgs = fn(target, cap, **kw)
    for m in msgs:
        print(m)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
