#!/usr/bin/env python3
"""AI Workbench installer/CLI. stdlib only, Windows + POSIX.

Commands:
  doctor     environment preflight (PASS/WARN/FAIL, never mutates)
  install    install workbench into a target dir (idempotent, dry-run, manifest)
  launch     print (or run) the exact claude launch command
  status     what is installed where, data stats
  capability capability registry: list/inspect/enable/disable/doctor
  uninstall  remove ONLY files this distribution owns (manifest-driven)
  benchmark  structural resident-context estimate (no model needed)

Design rules:
  - standalone install writes NOTHING outside --target. No global config edits.
  - user-scope changes are printed as manual steps, never applied silently.
  - uninstall never deletes user data unless --purge-data; never touches
    files not listed in install-manifest.json.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability import cmd_capability  # noqa: E402

RC_ROOT = Path(__file__).resolve().parent.parent
RC_VERSION = "0.1.0-rc.1"
ECC_PIN = "928076cc08cbb31e8549cea2883b4f51811de1c8"
ECC_PIN_VERSION = "2.0.0-rc.1"
MANIFEST = "install-manifest.json"

# ---------------------------------------------------------------- templates

SETTINGS_TMPL = {
    "env": {"HARNESS_DATA_DIR": "{{ROOT}}/harness-data"},
    "claudeMdExcludes": ["**/.claude/rules/ecc/**"],
    "hooks": {
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "python {{ROOT}}/hooks/harness_gate.py"}]}
        ]
    },
}

LAUNCH_SETTINGS_TMPL = {"claudeMdExcludes": ["**/.claude/rules/ecc/**"]}

PS1_TMPL = """# AI Workbench launcher (generated {{TS}})
Set-Location {{ROOT_Q}}
$env:CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD = '1'
claude --settings {{ROOT_Q}}\\launch\\vnext.settings.json @args
"""

SH_TMPL = """#!/usr/bin/env sh
# AI Workbench launcher (generated {{TS}})
cd "{{ROOT}}" || exit 1
export CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1
exec claude --settings "{{ROOT}}/launch/vnext.settings.json" "$@"
"""

GATE_DEFAULT = {
    "mode": "audit",
    "enforce_patterns": [
        "\\bgit\\s+push\\b", "\\bgit\\s+reset\\s+--hard\\b",
        "\\bgit\\s+clean\\s+-[a-zA-Z]*f", "\\brm\\s+-[a-zA-Z]*r[a-zA-Z]*f",
        "\\brm\\s+-[a-zA-Z]*f[a-zA-Z]*r", "\\bdel\\b.*\\s/[fs]\\b",
        "\\b(npm|pip|yarn|pnpm)\\s+publish\\b",
        "\\b(kubectl|helm|terraform)\\s+(apply|delete|destroy)\\b",
    ],
    "audit_patterns": [
        "\\bgit\\s+push\\b", "\\bgit\\s+reset\\s+--hard\\b",
        "\\bgit\\s+clean\\s+-[a-zA-Z]*f", "\\brm\\s+-[a-zA-Z]*r[a-zA-Z]*f",
        "\\brm\\s+-[a-zA-Z]*f[a-zA-Z]*r", "\\bdel\\b.*\\s/[fs]\\b",
        "\\b(npm|pip|yarn|pnpm)\\s+publish\\b",
        "\\b(kubectl|helm|terraform)\\s+(apply|delete|destroy)\\b",
    ],
}

# ---------------------------------------------------------------- helpers


def _root_posix(target: Path) -> str:
    return str(target.resolve()).replace("\\", "/")


def _render(text: str, target: Path) -> str:
    root = _root_posix(target)
    return (text.replace("{{ROOT}}", root)
                .replace("{{ROOT_Q}}", str(target.resolve()))
                .replace("{{TS}}", time.strftime("%Y-%m-%d")))


def _default_target() -> Path:
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ai-workbench"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "ai-workbench"


def _claude_version() -> str | None:
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=15)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else None
    except (OSError, subprocess.TimeoutExpired):
        return None


class Reporter:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []

    def add(self, level: str, item: str, detail: str = ""):
        self.rows.append((level, item, detail))
        print(f"[{level:4}] {item}" + (f" — {detail}" if detail else ""))

    @property
    def failed(self) -> bool:
        return any(lv == "FAIL" for lv, _, _ in self.rows)


# ---------------------------------------------------------------- doctor


def cmd_doctor(args) -> int:
    rep = Reporter()
    print("== AI Workbench doctor ==\n-- 运行时 --")
    v = sys.version_info
    rep.add("PASS" if v >= (3, 10) else "FAIL", f"Python {v.major}.{v.minor}.{v.micro}",
            "需要 >= 3.10")
    cv = _claude_version()
    rep.add("PASS" if cv else "WARN", f"Claude Code: {cv or '未找到'}",
            "" if cv else "PATH 上无 claude; 启动功能不可用, harness-core 仍可用")
    gv = shutil.which("git")
    rep.add("PASS" if gv else "WARN", f"git: {'可用' if gv else '未找到'}",
            "" if gv else "project_id 将退化为路径哈希")
    rep.add("PASS", f"OS: {platform.system()} {platform.release()}",
            "Windows 已实测; Linux/macOS 走 POSIX 路径(见 CI)")
    if platform.system() == "Windows":
        try:
            ep = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-ExecutionPolicy -Scope CurrentUser"],
                capture_output=True, text=True, timeout=15).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            ep = ""
        ok = ep in ("RemoteSigned", "Unrestricted", "Bypass")
        rep.add("PASS" if ok else "WARN", f"PowerShell 执行策略 (CurrentUser): {ep or '未知'}",
                "" if ok else "workbench.ps1 可能被拦截; 自行执行: "
                "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned")

    print("\n-- 目标目录 --")
    target = Path(args.target) if args.target else _default_target()
    if target.exists() and (target / MANIFEST).is_file():
        rep.add("PASS", f"已安装: {target}", "可幂等重装或 uninstall")
    elif target.exists() and any(target.iterdir()):
        rep.add("WARN", f"目标非空且无清单: {target}", "install 将拒绝, 除非 --force 备份后安装")
    else:
        rep.add("PASS", f"目标可用: {target}")

    print("\n-- 现有配置 (只读检查) --")
    home = Path.home()
    ecc_rules = home / ".claude" / "rules" / "ecc"
    rep.add("PASS" if ecc_rules.is_dir() else "PASS",
            f"全局 ECC rules: {'存在 (工作台会话将豁免, 全局不受影响)' if ecc_rules.is_dir() else '未安装 (无豁免需求)'}")
    usettings = home / ".claude" / "settings.json"
    if usettings.is_file():
        try:
            hooks = json.loads(usettings.read_text(encoding="utf-8")).get("hooks", {})
            pre = [h.get("command", "") for m in hooks.get("PreToolUse", []) for h in m.get("hooks", [])]
            bash_pre = [c for c in pre if c]
            rep.add("WARN" if bash_pre else "PASS",
                    f"用户级 PreToolUse hooks: {len(bash_pre)} 个",
                    "; ".join(c[:60] for c in bash_pre[:3]) + (" — 每个 Bash 调用都会经过全部 hooks(累加延迟)" if bash_pre else ""))
            dups = [c for c in bash_pre if "harness_gate" in c]
            if dups:
                rep.add("WARN", "用户级已配置 harness_gate (重复安装?)",
                        "工作台会话自带项目级 gate hook; 全局那份会与之叠加执行")
        except (json.JSONDecodeError, OSError) as e:
            rep.add("WARN", "用户 settings.json 不可解析", str(e)[:80])
    else:
        rep.add("PASS", "用户 settings.json: 不存在 (无冲突面)")
    print()
    return 1 if rep.failed else 0


# ---------------------------------------------------------------- install


def _write(path: Path, content: str, written: list[str], dry: bool):
    written.append(str(path))
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".git", ".hypothesis"}


def _copytree(src: Path, dst: Path, written: list[str], dry: bool):
    for p in sorted(src.rglob("*")):
        if p.is_dir() or _SKIP_DIRS.intersection(p.parts):
            continue
        rel = p.relative_to(src)
        written.append(str(dst / rel))
        if not dry:
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / rel)


def cmd_install(args) -> int:
    target = Path(args.target).resolve() if args.target else _default_target()
    if args.scope == "project" and not args.target:
        target = (Path.cwd() / ".ai-workbench").resolve()
    dry = args.dry_run
    print(f"== AI Workbench install {'(DRY-RUN) ' if dry else ''}== target={target} scope={args.scope}")

    manifest_path = target / MANIFEST
    if manifest_path.is_file():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"[INFO] 已安装 v{old.get('version')} ({old.get('installed_at')}) — 幂等刷新文件")
    elif target.exists() and any(target.iterdir()):
        if not args.force:
            print(f"[FAIL] 目标非空且无安装清单: {target}\n"
                  f"       用 --force 将其备份为 {target.name}.bak-<ts> 后安装, 或换 --target")
            return 1
        bak = target.with_name(f"{target.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        print(f"[INFO] 备份现有目录 -> {bak}")
        if not dry:
            shutil.move(str(target), str(bak))

    written: list[str] = []
    # 1) static trees from RC
    _copytree(RC_ROOT / "harness-core", target / "harness-core", written, dry)
    _copytree(RC_ROOT / "hooks", target / "hooks", written, dry)
    _copytree(RC_ROOT / "workbench" / ".claude", target / ".claude", written, dry)
    _copytree(RC_ROOT / "vendor" / "ecc", target / "vendor" / "ecc", written, dry)
    _write(target / "CLAUDE.md", (RC_ROOT / "workbench" / "CLAUDE.md").read_text(encoding="utf-8"), written, dry)
    _write(target / "capabilities" / "registry.json",
           (RC_ROOT / "capabilities" / "registry.json").read_text(encoding="utf-8"), written, dry)
    _copytree(RC_ROOT / "capabilities" / "wiring", target / "capabilities" / "wiring", written, dry)
    # 2) rendered configs
    _write(target / ".claude" / "settings.json",
           _render(json.dumps(SETTINGS_TMPL, indent=2), target), written, dry)
    _write(target / "launch" / "vnext.settings.json",
           json.dumps(LAUNCH_SETTINGS_TMPL, indent=2), written, dry)
    _write(target / "launch" / "workbench.ps1", _render(PS1_TMPL, target), written, dry)
    _write(target / "launch" / "workbench.sh", _render(SH_TMPL, target), written, dry)
    _write(target / "VERSION", RC_VERSION + "\n", written, dry)
    # 3) data dir + gate default (never overwrite existing gate.json on reinstall)
    gate_path = target / "harness-data" / "gate.json"
    if dry or not gate_path.is_file():
        _write(gate_path, json.dumps(GATE_DEFAULT, indent=2), written, dry)
    # 4) manifest last
    manifest = {"version": RC_VERSION, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "scope": args.scope, "target": str(target), "ecc_pin": ECC_PIN,
                "files": written}
    if not dry:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[{'DRY' if dry else 'OK'}] {len(written)} 个文件")
    if args.scope == "user":
        print("\n[手动步骤 — 本安装器不自动改全局配置]\n"
              "  若要在任意目录的会话豁免全局 ECC 规则, 自行向 ~/.claude/settings.json 添加:\n"
              '  "claudeMdExcludes": ["**/.claude/rules/ecc/**"]\n'
              "  (工作台会话已自动豁免, 通常无需此步)")
    print(f"\n启动: python {Path(__file__).name} launch --target \"{target}\"")
    return 0


# ---------------------------------------------------------------- launch/status/uninstall/benchmark


def cmd_launch(args) -> int:
    target = Path(args.target).resolve() if args.target else _default_target()
    if not (target / MANIFEST).is_file():
        print(f"[FAIL] 未安装: {target} (先 install)"); return 1
    ps1 = target / "launch" / "workbench.ps1"
    sh = target / "launch" / "workbench.sh"
    if platform.system() == "Windows":
        cmd = f'powershell -File "{ps1}"'
    else:
        cmd = f'sh "{sh}"'
    print(cmd)
    if args.run:
        return subprocess.call(str(ps1 if platform.system() == "Windows" else sh), shell=True)
    return 0


def cmd_status(args) -> int:
    target = Path(args.target).resolve() if args.target else _default_target()
    m = target / MANIFEST
    if not m.is_file():
        print(f"未安装: {target}"); return 1
    manifest = json.loads(m.read_text(encoding="utf-8"))
    data = target / "harness-data"
    fb = data / "feedback.jsonl"
    n_fb = sum(1 for line in fb.read_text(encoding="utf-8").splitlines() if line.strip()) if fb.is_file() else 0
    gate_mode = "?"
    gj = data / "gate.json"
    if gj.is_file():
        try:
            gate_mode = json.loads(gj.read_text(encoding="utf-8")).get("mode", "?")
        except json.JSONDecodeError:
            gate_mode = "corrupt!"
    caps = {}
    try:
        from capability import load_registry, load_state, effective_enabled
        reg = load_registry(target)  # 安装后的 registry 在目标内
        st = load_state(target)
        caps = {"total": len(reg["capabilities"]),
                "enabled": sum(1 for c in reg["capabilities"] if effective_enabled(c, st))}
    except Exception:
        caps = {"total": "?", "enabled": "?"}
    print(json.dumps({
        "installed": True, "version": manifest.get("version"),
        "target": str(target), "scope": manifest.get("scope"),
        "installed_at": manifest.get("installed_at"), "ecc_pin": manifest.get("ecc_pin"),
        "files_owned": len(manifest.get("files", [])),
        "feedback_records": n_fb, "gate_mode": gate_mode, "capabilities": caps,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_uninstall(args) -> int:
    target = Path(args.target).resolve() if args.target else _default_target()
    m = target / MANIFEST
    if not m.is_file():
        print(f"[FAIL] 无安装清单: {target} — 拒绝删除任何内容"); return 1
    manifest = json.loads(m.read_text(encoding="utf-8"))
    files = [Path(f) for f in manifest.get("files", [])]
    outside = [f for f in files if target not in f.resolve().parents and f.resolve() != target]
    if outside:
        print(f"[FAIL] 清单含目标外路径, 中止 (可能损坏): {outside[:3]}"); return 1
    print(f"== 卸载 {target} (v{manifest.get('version')}) ==")
    if not args.yes:
        print("加 --yes 确认; 数据默认保留, --purge-data 才删除 harness-data/")
        return 0
    removed = 0
    for f in files:
        if f.is_file() and (args.purge_data or "harness-data" not in f.parts):
            f.unlink(); removed += 1
    if args.purge_data:
        (target / MANIFEST).unlink(missing_ok=True)
    # manifest is kept when data is preserved, so a later --purge-data still works
    # clean empty dirs bottom-up, keep harness-data unless purged
    for d in sorted((p for p in target.rglob("*") if p.is_dir()),
                    key=lambda p: -len(p.parts)):
        if d.name == "harness-data" and not args.purge_data:
            continue
        try:
            d.rmdir()
        except OSError:
            pass
    if args.purge_data:
        shutil.rmtree(target, ignore_errors=True)
    print(f"[OK] 移除 {removed} 个文件; 数据{'已清除' if args.purge_data else '保留于 harness-data/ (若存在)'}")
    print("未触碰: 全局 ~/.claude 配置、用户自有 ECC/skills/hooks、其他任何目录")
    return 0


def cmd_benchmark(args) -> int:
    target = Path(args.target).resolve() if args.target else _default_target()
    rows = {}
    l0 = target / "CLAUDE.md"
    rows["workbench L0 (CLAUDE.md)"] = len(l0.read_text(encoding="utf-8")) if l0.is_file() else 0
    idx = 0
    sk_dir = target / ".claude" / "skills"
    if sk_dir.is_dir():
        for sm in sk_dir.rglob("SKILL.md"):
            t = sm.read_text(encoding="utf-8", errors="replace")
            parts = t.split("---")
            idx += len(parts[1]) if t.startswith("---") and len(parts) > 2 else 200
    rows["skills 索引 (frontmatter 合计)"] = idx
    ecc = Path.home() / ".claude" / "rules" / "ecc"
    rows["全局 ECC rules (对照)"] = (
        sum(len(p.read_text(encoding="utf-8", errors="replace"))
            for p in ecc.rglob("*.md")) if ecc.is_dir() else 0)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    vnext_total = rows["workbench L0 (CLAUDE.md)"] + idx
    ecc_total = rows["全局 ECC rules (对照)"]
    if ecc_total:
        print(f"常驻估算: vnext≈{vnext_total // 3} tok vs ecc≈{ecc_total // 3} tok "
              f"({100 * (1 - vnext_total / ecc_total):.0f}% 减)" if vnext_total < ecc_total else "")
    return 0


# ---------------------------------------------------------------- main


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="workbench", description=__doc__)
    p.add_argument("--target", default=None, help="安装目标目录 (默认: 平台数据目录/ai-workbench)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    i = sub.add_parser("install")
    i.add_argument("--scope", choices=["standalone", "project", "user"], default="standalone")
    i.add_argument("--dry-run", action="store_true")
    i.add_argument("--force", action="store_true", help="目标非空且无清单时备份后安装")
    i.add_argument("--yes", action="store_true")
    l = sub.add_parser("launch")
    l.add_argument("--run", action="store_true", help="直接启动而非仅打印命令")
    sub.add_parser("status")
    c = sub.add_parser("capability", help="能力注册中心: list/inspect/enable/disable/doctor")
    c.add_argument("cap_cmd", choices=["list", "inspect", "enable", "disable", "doctor"])
    c.add_argument("id", nargs="?", default=None)
    c.add_argument("--json", action="store_true")
    u = sub.add_parser("uninstall")
    u.add_argument("--yes", action="store_true")
    u.add_argument("--purge-data", action="store_true")
    sub.add_parser("benchmark")
    args = p.parse_args(argv)
    if args.cmd == "capability":
        target = Path(args.target).resolve() if args.target else _default_target()
        # 已安装目标用目标内 registry (随安装版本冻结); 未安装则用仓库内 registry
        reg_root = target if (target / "capabilities" / "registry.json").is_file() else RC_ROOT
        return cmd_capability(args, target, reg_root)
    return {"doctor": cmd_doctor, "install": cmd_install, "launch": cmd_launch,
            "status": cmd_status, "uninstall": cmd_uninstall,
            "benchmark": cmd_benchmark}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
