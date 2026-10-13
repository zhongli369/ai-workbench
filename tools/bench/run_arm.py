#!/usr/bin/env python3
"""Bench arm runner — fixed-config A/B for VNext vs native Claude Code.

Fixes the 2026-10-13 arm-e invalidation (fb-c11184940f41): --allowedTools
covered only Bash(python:*) but CC 2.1.x on Windows defaults to the
PowerShell tool -> 25-denial loop, $2.41 of garbage. This runner allows the
same command prefixes on BOTH tools, for BOTH arms.

Usage:
  python bench/run_arm.py --mode vnext --project <dir> --prompt-file <md> --output bench/out.json
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

WB = Path(__file__).resolve().parent.parent  # workbench-vnext root

# identical permission surface for both arms; prefixes cover what a bugfix
# session legitimately needs inside an isolated experiment copy
ALLOWED = [
    "Bash(python:*)", "Bash(rtk:*)", "Bash(git:*)", "Bash(echo:*)",
    "Bash(cat:*)", "Bash(ls:*)", "Bash(cd:*)", "Bash(find:*)",
    "PowerShell(python:*)", "PowerShell(rtk:*)", "PowerShell(git:*)",
    "PowerShell(echo:*)", "PowerShell(Get-Content:*)", "PowerShell(Get-ChildItem:*)",
    "PowerShell(Set-Location:*)", "PowerShell(Test-Path:*)",
    "PowerShell(cmd:*)", "PowerShell(cd:*)",  # r3: 9 denials from cmd/cd retries
    "Read", "Edit", "Write", "Glob", "Grep",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["baseline", "vnext"], required=True)
    ap.add_argument("--project", required=True, action="append",
                    help="experiment dir (repeatable for multi-project probes)")
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--harness-data-dir",
                    help="isolated experiment store; NEVER point at the real "
                         "platform-default feedback DB (2026-10-13 user rule)")
    ap.add_argument("--harness-project-id",
                    help="pin HARNESS_PROJECT_ID so project resolution does not "
                         "depend on the model's cwd — keeps the arm variable clean")
    a = ap.parse_args()

    projects = [Path(p).resolve() for p in a.project]
    project = projects[0]
    prompt = Path(a.prompt_file).read_text(encoding="utf-8")
    # 2026-10-13 finding: without explicit paths in the prompt, the vnext arm
    # (cwd = workbench root) wasted ~5 tool calls hunting for the project.
    # Baseline cwd IS the project, so it never paid this. Give both arms the
    # absolute path(s) — anything else measures prompt deficiency, not product.
    prompt = ("项目目录 (已通过 --add-dir 挂载, 直接用绝对路径操作):\n"
              + "\n".join(f"- {p}" for p in projects) + "\n\n" + prompt)
    out = Path(a.output).resolve()
    err = out.with_suffix(".err")

    claude = shutil.which("claude")  # on Windows `claude` is a .cmd shim —
    if not claude:                   # CreateProcess needs the resolved path
        print("[run_arm] claude CLI not on PATH", file=sys.stderr)
        return 1
    cmd = [claude, "--print", "--output-format", "json"]
    if a.mode == "vnext":
        # vnext arm: project-level CLAUDE.md + settings (claudeMdExcludes, gate hook)
        settings = WB / "launch" / "vnext.settings.json"
        if a.harness_data_dir:
            # 2026-10-13 root cause (r3 arm): the PROJECT-LEVEL
            # .claude/settings.json env block pins HARNESS_DATA_DIR to the
            # workbench's own store and wins over the process env for tool
            # subprocesses — so per-arm store isolation must be injected into
            # the settings file CC reads, not just the process env.
            import json as _json
            base = _json.loads(settings.read_text(encoding="utf-8"))
            base.setdefault("env", {})["HARNESS_DATA_DIR"] = str(
                Path(a.harness_data_dir).resolve())
            tmp = WB / "bench" / f".arm-settings-{os.getpid()}.json"
            tmp.write_text(_json.dumps(base, indent=2), encoding="utf-8")
            settings = tmp
        cmd += ["--settings", str(settings)]
        cwd = str(WB)
    else:
        # baseline arm: native CC = global config untouched, neutral cwd
        cwd = str(project)
    # variadic flags would swallow a positional prompt arg — prompt goes via stdin
    for proj in projects:
        cmd += ["--add-dir", str(proj)]
    cmd += ["--allowedTools", *ALLOWED]
    if claude.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c", *cmd]  # CreateProcess cannot exec batch shims

    env = {**os.environ, "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD": "1"}
    if a.harness_data_dir:
        env["HARNESS_DATA_DIR"] = str(Path(a.harness_data_dir).resolve())
    if a.harness_project_id:
        env["HARNESS_PROJECT_ID"] = a.harness_project_id
    print(f"[run_arm] mode={a.mode} cwd={cwd} project={project}")
    with open(out, "w", encoding="utf-8") as fo, open(err, "w", encoding="utf-8") as fe:
        r = subprocess.run(cmd, cwd=cwd, env=env, stdout=fo, stderr=fe,
                           input=prompt, text=True, timeout=1800)
    if r.returncode != 0:
        print(f"[run_arm] claude exit {r.returncode}; see {err}", file=sys.stderr)
    try:
        d = json.loads(out.read_text(encoding="utf-8"))
        print(f"[run_arm] cost=${d.get('total_cost_usd')} denials={len(d.get('permission_denials', []))} "
              f"reason={d.get('terminal_reason')}")
    except (json.JSONDecodeError, OSError) as e:
        print(f"[run_arm] output unparseable: {e}", file=sys.stderr)
        return 1
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
