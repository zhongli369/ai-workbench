#!/usr/bin/env python3
"""Capability registry commands for AI Workbench. stdlib only.

Subcommands (wired into tools/workbench.py):
  list      declared capabilities + effective on/off + health
  inspect   full declaration of one capability
  enable    record operator intent: on
  disable   record operator intent: off
  doctor    health-check every capability against the install target

Design rules:
  - The registry is a CLI surface. It is NEVER injected into model context.
  - enable/disable writes only <target>/harness-data/capability-state.json.
    v1 semantics are per-capability (`wiring` field): "active" capabilities are
    wired by install itself; "recorded-intent" capabilities keep invocation
    manual — enable never auto-installs anything, never runs remote scripts.
  - Nothing here touches global ~/.claude configuration.
"""
import json
import os
import shutil
import sys
from pathlib import Path

STATE_NAME = "capability-state.json"
REGISTRY_REL = Path("capabilities") / "registry.json"


class RegistryError(Exception):
    pass


def load_registry(rc_root: Path) -> dict:
    p = rc_root / REGISTRY_REL
    if not p.is_file():
        raise RegistryError(f"registry 缺失: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RegistryError(f"registry 不可解析: {e}") from e
    if data.get("schema") != 1:
        raise RegistryError(f"不支持的 registry schema: {data.get('schema')!r}")
    caps = data.get("capabilities")
    if not isinstance(caps, list) or not caps:
        raise RegistryError("registry 无 capabilities")
    ids = [c.get("id") for c in caps]
    if len(set(ids)) != len(ids):
        raise RegistryError("registry 含重复 id")
    return data


def _state_path(target: Path) -> Path:
    return target / "harness-data" / STATE_NAME


def load_state(target: Path) -> dict:
    p = _state_path(target)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_corrupt": True}
    return data if isinstance(data, dict) else {}


def _save_state(target: Path, state: dict) -> None:
    p = _state_path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def effective_enabled(cap: dict, state: dict) -> bool:
    return bool(state.get(cap["id"], cap.get("default_enabled", False)))


# ---------- wiring v1.1: managed skill-file integration ----------

# Same literal as tools/workbench.py MANIFEST (importing it here would be circular).
_MANIFEST_NAME = "install-manifest.json"
_WIRE_MARKER = "<!-- aiwb-managed:{id} -->"


def _manifest_add(target: Path, path: Path) -> None:
    """Register a wired file in the install manifest so owns-only uninstall sweeps it."""
    mpath = target / _MANIFEST_NAME
    if not mpath.is_file():
        return  # bare registry target (tests / non-installed) — nothing to update
    m = json.loads(mpath.read_text(encoding="utf-8"))
    files = m.setdefault("files", [])
    if str(path) not in files:
        files.append(str(path))
        mpath.write_text(json.dumps(m, indent=2), encoding="utf-8")


def _manifest_remove(target: Path, path: Path) -> None:
    mpath = target / _MANIFEST_NAME
    if not mpath.is_file():
        return
    m = json.loads(mpath.read_text(encoding="utf-8"))
    files = m.get("files", [])
    if str(path) in files:
        files.remove(str(path))
        mpath.write_text(json.dumps(m, indent=2), encoding="utf-8")


def _wire_skill_file(reg_root: Path, target: Path, cap: dict) -> tuple[bool, str]:
    """Write the managed SKILL.md for a capability. Returns (ok, dest-or-error)."""
    wa = cap["wiring_action"]
    template = reg_root / "capabilities" / "wiring" / wa["template"]
    if not template.is_file():
        return False, f"接线模板缺失: capabilities/wiring/{wa['template']} (安装包不完整)"
    dest = target / wa["dest"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    marker = _WIRE_MARKER.format(id=cap["id"])
    dest.write_text(marker + "\n" + template.read_text(encoding="utf-8"), encoding="utf-8")
    _manifest_add(target, dest)
    return True, wa["dest"]


def _unwire_skill_file(target: Path, cap: dict, rel: str) -> tuple[bool, str]:
    """Remove a managed SKILL.md — owns-only: refuse when the marker was stripped."""
    dest = target / rel
    if not dest.is_file():
        _manifest_remove(target, dest)
        return True, f"{rel} (已不存在)"
    head = dest.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
    if head and head[0].strip() == _WIRE_MARKER.format(id=cap["id"]):
        dest.unlink()
        _manifest_remove(target, dest)
        try:
            dest.parent.rmdir()  # only succeeds when empty
        except OSError:
            pass
        return True, rel
    return False, f"{rel} 标记已被移除(可能被用户修改) — 保留, 请人工确认后删除"


def check_health(cap: dict, target: Path) -> tuple[str, str]:
    """Return (status, detail): status in ok / missing / unknown."""
    h = cap.get("health") or {}
    t = h.get("type")
    if t == "file":
        ok = (target / h.get("path", "")).is_file()
        return ("ok" if ok else "missing"), h.get("path", "")
    if t == "dir":
        ok = (target / h.get("path", "")).is_dir()
        return ("ok" if ok else "missing"), h.get("path", "")
    if t == "cli":
        found = shutil.which(h.get("bin", ""))
        return ("ok" if found else "missing"), found or h.get("bin", "")
    if t == "env":
        val = os.environ.get(h.get("var", ""), "")
        if val and Path(val).is_file():
            return "ok", val
        return "missing", f"{h.get('var', '')} 未设置或路径不存在"
    return "unknown", "manual (见 inspect 说明)"


def _rows(reg: dict, state: dict, target: Path) -> list[dict]:
    out = []
    for cap in reg["capabilities"]:
        hs, hd = check_health(cap, target)
        out.append({
            "id": cap["id"],
            "enabled": effective_enabled(cap, state),
            "health": hs,
            "health_detail": hd,
            "origin": cap.get("origin", ""),
            "license": cap.get("license", ""),
            "wiring": cap.get("wiring", ""),
        })
    return out


def cmd_capability(args, target: Path, rc_root: Path) -> int:
    try:
        reg = load_registry(rc_root)
    except RegistryError as e:
        print(f"[FAIL] {e}")
        return 1
    state = load_state(target)
    if state.get("_corrupt"):
        print(f"[FAIL] 状态文件损坏: {_state_path(target)} — 拒绝猜测, 请人工检查后删除重建")
        return 1

    sub = args.cap_cmd
    if sub == "list":
        rows = _rows(reg, state, target)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for r in rows:
                mark = "on " if r["enabled"] else "off"
                print(f"[{mark}] {r['id']:<16} health={r['health']:<8} {r['origin']}")
            print(f"\n目标: {target}  (状态文件: harness-data/{STATE_NAME})")
        return 0

    if sub == "inspect":
        cap = next((c for c in reg["capabilities"] if c["id"] == args.id), None)
        if not cap:
            print(f"[FAIL] 未知能力: {args.id} (见 capability list)")
            return 1
        detail = dict(cap)
        detail["enabled"] = effective_enabled(cap, state)
        hs, hd = check_health(cap, target)
        detail["health_status"] = hs
        detail["health_detail"] = hd
        print(json.dumps(detail, ensure_ascii=False, indent=2))
        return 0

    if sub in ("enable", "disable"):
        cap = next((c for c in reg["capabilities"] if c["id"] == args.id), None)
        if not cap:
            print(f"[FAIL] 未知能力: {args.id} (见 capability list)")
            return 1
        if sub == "enable":
            for mx in cap.get("mutex", []):
                other = next((c for c in reg["capabilities"] if c["id"] == mx), None)
                if other and effective_enabled(other, state):
                    print(f"[FAIL] 与已启用能力互斥: {mx} — 先 disable {mx}")
                    return 1
        wired: list[str] = []
        if sub == "enable" and cap.get("wiring_action"):
            # wiring v1.1: real integration, but only onto tooling the user
            # already installed — health must pass; we NEVER auto-install.
            hs, hd = check_health(cap, target)
            if hs != "ok":
                print(f"[FAIL] 健康检查未过 ({cap.get('health', {}).get('type')}: {hd})\n"
                      f"       请先自行安装 {cap['id']}, 再 enable — 本工具从不自动安装外部软件")
                return 1
            if cap["wiring_action"].get("type") == "skill-file":
                ok, msg = _wire_skill_file(rc_root, target, cap)
                if not ok:
                    print(f"[FAIL] {msg}")
                    return 1
                wired.append(msg)
        if sub == "disable":
            for rel in state.get("_wired", {}).get(cap["id"], []):
                if cap.get("wiring_action", {}).get("type") == "skill-file":
                    ok, msg = _unwire_skill_file(target, cap, rel)
                    print(f"[{'OK' if ok else 'WARN'}] 解除接线: {msg}")
            state.get("_wired", {}).pop(cap["id"], None)
        state[cap["id"]] = (sub == "enable")
        if wired:
            state.setdefault("_wired", {})[cap["id"]] = wired
        _save_state(target, state)
        wiring = cap.get("wiring", "")
        print(f"[OK] {cap['id']} -> {'enabled' if sub == 'enable' else 'disabled'} "
              f"(记录于 harness-data/{STATE_NAME})")
        for rel in wired:
            print(f"     已接线: {rel} (卸载时随清单自动移除)")
        if wiring.startswith("recorded-intent"):
            print("     v1 语义: 记录运维意图; 外部能力的安装/调用仍为手动步骤 (capability inspect 查看)")
        return 0

    if sub == "doctor":
        rows = _rows(reg, state, target)
        worst = 0
        for r in rows:
            level = "PASS" if r["health"] == "ok" else ("WARN" if r["health"] == "missing" else "INFO")
            if r["health"] == "missing" and r["enabled"]:
                level = "WARN"
            print(f"[{level:4}] {r['id']:<16} {'on ' if r['enabled'] else 'off'} — {r['health_detail']}")
        enabled_missing = [r["id"] for r in rows if r["enabled"] and r["health"] == "missing"]
        if enabled_missing:
            print(f"\n已启用但健康检查缺失: {', '.join(enabled_missing)} (WARN, 不阻断)")
            worst = 0  # 外部可选能力缺失不视为失败; 内建能力缺失才失败
            builtin_missing = [r["id"] for r in rows
                               if r["enabled"] and r["health"] == "missing" and r["origin"] == "self"]
            if builtin_missing:
                print(f"内建能力缺失: {', '.join(builtin_missing)} — 安装损坏?")
                worst = 1
        return worst

    print(f"[FAIL] 未知子命令: {sub}")
    return 1


def add_subparser(sub, rc_root_default=None):
    c = sub.add_parser("capability", help="能力注册中心: list/inspect/enable/disable/doctor")
    c.add_argument("cap_cmd", choices=["list", "inspect", "enable", "disable", "doctor"])
    c.add_argument("id", nargs="?", default=None)
    c.add_argument("--json", action="store_true")
    return c
