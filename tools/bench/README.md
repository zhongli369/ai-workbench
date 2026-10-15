# tools/bench — controlled A/B bench tooling

Developer tooling for measured Native-vs-Workbench comparisons. **Not part of
the installed payload** (`workbench install` does not copy this directory).

## Contents

- `run_arm.py` — single-arm runner with fixed, symmetric configuration for
  both arms (vnext / native). Encodes hard-won CC 2.1.x mechanics:
  - `--allowedTools` must cover the same command prefixes on **both** the
    Bash and PowerShell tools on Windows (the 25-denial / $2.41 lesson).
  - Per-arm generated settings file injects `HARNESS_DATA_DIR` — a project
    `.claude/settings.json` env block applies to tool subprocesses and
    **overrides** the launching process env; `--settings` outranks the
    project file ("CC 启动变量→进程 env; 工具子进程变量→settings 文件").
  - `--harness-data-dir` must never point at the real platform feedback DB
    (guard in help text).
- `analyze_transcript.py` — transcript forensics: given result JSONs, finds
  the session JSONL under `~/.claude/projects/<sanitized-cwd>/` and counts
  turns / cost / denials / Task / Skill / harness-CLI invocations.

Scenario builders (e.g. `build_e4.py`) are deliberately **not** here: they
are scenario-specific and lived with the experiment archive under
`harness-experiments/` (retired 2026-10-15; recovery point
`_snapshots/fusion-omega-m0-20261013/harness-experiments/`).

## Fairness rules (binding for any published number)

Same model, same initial snapshot, same prompt, same acceptance test, same
permissions, per-arm isolated data dirs, recorded run order, N=1 cells
labeled exploratory. Negative results are published, never deleted.

Planned (M5): terminal-bench-derived task subset (Apache-2.0, canary
anti-leak) driven through the official `claude-agent-sdk-python` instead of
parsing CLI output.
