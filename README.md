# AI Workbench

*A lightweight, general-purpose enhancement environment for Claude Code —
minimal default interference, necessary safety guarantees, mature plugins on
demand, reliable install and rollback.*

`v0.1.0-preview.5` · **Stable / Maintenance Mode** (see [docs/MAINTENANCE.md](docs/MAINTENANCE.md)) · [中文](README.zh-CN.md)

| Badge | Status |
|---|---|
| CI (contracts + static + CLI smoke) | [![ci](https://github.com/zhongli369/ai-workbench/actions/workflows/ci.yml/badge.svg)](https://github.com/zhongli369/ai-workbench/actions/workflows/ci.yml) |
| Supply-chain security scan | [![security](https://github.com/zhongli369/ai-workbench/actions/workflows/security.yml/badge.svg)](https://github.com/zhongli369/ai-workbench/actions/workflows/security.yml) |
| License | [![license](https://img.shields.io/github/license/zhongli369/ai-workbench)](LICENSE) |

---

## 1. What this is — and is not

AI Workbench is a thin, install-once workspace layer on top of Claude Code:
one session operates many projects, with a safety gate, on-demand
capabilities, and a rollback-able install.

It is **not**:

- an independent LLM
- a second agent framework
- a Java / Python full-stack business system
- a multi-agent autonomous scheduling platform
- a heavy harness that forces planning and verification on every task

Design goals: **minimal default interference, necessary safety guarantees,
mature plugins on demand, reliable install and rollback.**

Evidence behind the philosophy: controlled harness-bench runs showed heavy
default injection *lowering* task performance (SE family -0.486), so the
default stays light (LEAN) and everything heavy is opt-in.

## 2. Current capabilities

### On by default (LEAN mode)

| Capability | Mechanism |
|---|---|
| LEAN session policy | `workbench/CLAUDE.md` (83 lines, installed into the workbench root) |
| Three-tier gate for irreversible commands | single `PreToolUse` hook (Bash + PowerShell); production default **audit** |
| SessionEnd metrics | `hooks/session_metrics.py` → `harness-data/session-metrics.jsonl` (counters only, no conversation content) |
| Multi-project protocol | `PROJECTS.md` cheat-sheet + absolute paths / `git -C`; a target project's `CLAUDE.md` loads via `/add-dir` |
| MCP default zero | launcher enforces `--strict-mcp-config` |
| Curated on-demand subset | **11 skills** / **1 agent** / 14 commands (**(11+1+14)**, loaded per task; pin in `vendor/ecc/`) |
| Global-rule exemption | `claudeMdExcludes` keeps global rule packs from shadowing a project's own rules |

### Explicit, on-demand

| Capability | How to enable |
|---|---|
| POWER mode (Superpowers v7.0.0 @bb92a77, pinned) | `launch\workbench-power.ps1` — loads superpowers only, never sibling plugins |
| frontend-design @a0b04d9 (Apache-2.0) | session-scoped `WORKBENCH_PLUGIN_DIR` (see Quickstart) |
| harness CLI: `plan` / `checkpoint` / `verify` / `snap` / `feedback` / `gate` / `telemetry` | invoked explicitly; never a resident workflow |
| MCP Inspector 2.11.0 (MCP debugging) | external CLI via `npx`; not injected into the workbench, not registered as MCP |
| Capability registry (16 entries) | `workbench capability list/enable/disable`; external capabilities are **never auto-installed** |

### Disabled (kept, restorable via `git mv`)

19 disabled skills and 15 disabled agents live in `workbench/disabled/`
(installed as `.claude/skills.disabled` / `agents.disabled`) — self-built
duplicates of mature upstream capabilities, moved out during the R5
slim-down. They are **not** active capabilities.

## 3. Quickstart (Windows PowerShell, all commands verified)

Requirements: Python ≥ 3.10 + the Claude Code CLI. harness-core is stdlib-only
(stdlib, 253 contracts) — no `pip install` needed.

Commands below install to the default location; add the global flag
`--target <dir>` **before** the subcommand to use a custom install
directory — `<target-dir>` in what follows is that install root.

```powershell
# 1. Install (idempotent, dry-run-able, writes only into the target dir)
git clone https://github.com/zhongli369/ai-workbench.git
cd ai-workbench
python tools/workbench.py doctor
python tools/workbench.py install --yes

# 2. Launch LEAN (default)
<target-dir>\launch\workbench.ps1

#    equivalent, prints then runs the exact launch command:
python tools/workbench.py launch --run

# 3. Launch POWER (LEAN + Superpowers)
<target-dir>\launch\workbench-power.ps1

# 4. Explicitly enable frontend-design (session-scoped; start inside a project dir)
$env:WORKBENCH_PLUGIN_DIR = "<target-dir>\vendor\plugins\frontend-design"
<target-dir>\launch\workbench.ps1

# 5. Clear the session-scoped setting afterwards (zero global state)
Remove-Item Env:WORKBENCH_PLUGIN_DIR

# 6. Show the current gate mode (production default: audit)
python <target-dir>\harness-core\harness\cli.py gate check "git push origin main"
#    real output: {"decision": "audit", "mode": "audit", ...}

# 7. On-demand verify (mechanical acceptance gate)
python <target-dir>\harness-core\harness\cli.py verify status --exec <id>

# 8. Show version / install status
python tools/workbench.py status

# MCP debugging (external on-demand CLI, not installed into the workbench)
npx --yes @modelcontextprotocol/inspector@2.11.0 --cli node <server.js> --method tools/list
```

Uninstall removes only manifest-owned files and keeps your data by default
(append `--purge-data` to wipe it):

```powershell
python tools/workbench.py uninstall --yes
```

## 4. Usage guidance

- **Simple tasks: LEAN** (default) — act directly; no planning, no agents.
- **Complex debugging / TDD / systematic development: POWER** — Superpowers
  adds process discipline. Do not wrap simple tasks in POWER ceremony, and do
  not assume POWER is always better than LEAN.
- **UI/design work**: explicitly enable frontend-design.
- **MCP debugging**: use the external Inspector CLI.
- Other specialized tools (Playwright MCP / Context7 / Promptfoo): adopt only
  when a real need arises — status and the adoption checklist live in
  [docs/open-source-adoption.md](docs/open-source-adoption.md).

## 5. Directory layout (source repo)

```
ai-workbench/
├─ tools/workbench.py      ← installer / CLI (doctor install launch status capability uninstall)
├─ workbench/              ← payload source: CLAUDE.md, .claude/ (11+1+14), disabled/ (19+15)
├─ harness-core/           ← stdlib-only CLI toolkit (253 contracts, usable standalone)
├─ hooks/                  ← harness_gate.py (gate) + session_metrics.py (SessionEnd)
├─ capabilities/           ← capability registry (registry.json + wiring)
├─ vendor/                 ← pinned third-party snapshots (ecc provenance stub, plugins)
├─ tests/                  ← repo contracts (incl. battle / multiproj)
└─ docs/                   ← MAINTENANCE.md, open-source-adoption.md, claims/surface gates
```

An install target additionally gets: `launch/` (LEAN/POWER launchers),
`harness-data/` (gate.json, session-metrics.jsonl and other user data), and
`install-manifest.json` (owned-file list + sha256 drift protection).

## 6. Safety and boundaries

- **Gate, three modes**: `disabled` does nothing; `audit` records and prompts
  (**observability, not protection**); `enforce` blocks configured high-risk
  patterns (push / reset --hard / rm -rf / publish / deploy) unless
  pre-approved with a single-use token (`gate approve --once`). Production
  default is **audit**.
- **The gate is not an absolute safety guarantee**; non-interactive
  `claude --print` skips `PreToolUse` hooks (verified on CC 2.1.x), so
  enforce applies to interactive sessions.
- **User authorization is never bypassed**; the gate mode must not be changed
  by the model on its own.
- **Every business project should be its own Git repository**; the workbench
  carries no business code, dependencies, tests, or project-specific config.
- **Managed files vs user data**: `PROJECTS.md` / `settings.json` /
  `gate.json` are never overwritten; every other managed file is protected by
  per-file sha256 in the manifest — a locally modified managed file is backed
  up to `<file>.user-bak` before a reinstall refreshes it to canonical.
- **The global `~/.claude/CLAUDE.md` is the user's personal config** — the
  installer never reads or modifies it.

## 7. Maintenance status

**Stable / Maintenance Mode.** Only four kinds of changes are allowed: real
security defects, Claude Code upstream compatibility breakage, confirmed
functional bugs, and generic capability gaps that recur across real projects
and can be solved neither natively nor by mature plugins. See
[docs/MAINTENANCE.md](docs/MAINTENANCE.md).

- Current version `0.1.0-preview.5` (no Release cut; the latest published
  release remains `v0.1.0-preview.3`).
- R6 slim candidate `r6-slim @1b91f1c`: **independent experimental candidate,
  net benefit unproven — not merged, not deployed, off by default.**

## 8. Evidence

- **540 offline contracts** = **253 harness-core** (deterministic, 253 contracts) + **287 tests**; the exact number is verified live by
  `tools/check_docs_drift.py` against the pytest collection, and this README
  is not allowed to drift from it.
- CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)): three OSes ×
  Python 3.10–3.12 plus static gates (hygiene / docs-drift / public surface).
- Plugin isolation, empirically probed (2026-10-20, stream-json init events):
  LEAN loads only built-in plugins; POWER loads superpowers; an explicit
  session loads frontend-design.
- Reproducible demos: [docs/demos.md](docs/demos.md).

## 9. Related docs

[中文 README](README.zh-CN.md) · [docs/MAINTENANCE.md](docs/MAINTENANCE.md)
(maintenance mode) · [docs/open-source-adoption.md](docs/open-source-adoption.md)
(open-source adoption & status) · [CHANGELOG.md](CHANGELOG.md) ·
[harness-core/README.md](harness-core/README.md) ·
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [SECURITY.md](SECURITY.md) ·
[NOTICE](NOTICE) (third-party attribution) · [CONTRIBUTING.md](CONTRIBUTING.md)

## License

MIT for this distribution's own code. everything-claude-code is MIT by its
respective authors — see `vendor/ecc/LICENSE` and [NOTICE](NOTICE).
