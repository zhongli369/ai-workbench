# AI Workbench

*A lightweight, governed, on-demand engineering workbench for Claude Code.*

**What it is.** A thin, install-once workspace layer on top of
[Claude Code](https://claude.com/claude-code) — not another skills mega-pack.
You launch one workspace and point it at any project; irreversible commands
pass through a three-tier gate; expert capabilities load per-task instead of
taxing every prompt; small tasks stay cheap.

**The pain it fixes.** ① juggling several repos means re-establishing context
in every session; ② capability packs charge every prompt for rules you don't
need today; ③ one mistaken irreversible command can ruin your day — the gate
makes it a deliberate act. (A cross-session failure-memory oracle is included
as an **experimental** capability — mechanism verified, in-vivo retrieval
benefit unproven; see [Honest performance notes](#honest-performance-notes).)

**How it's different** — honestly split by origin:

| | native Claude Code | everything-claude-code (ECC) | AI Workbench |
|---|---|---|---|
| Edit, test, ship in one project | ✔ (this is CC itself) | | |
| 60+ agents / 240+ skills catalog | | ✔ (upstream project) | |
| Curated ECC subset, on-demand not resident | | | ✔ (30 skills / 16 agents, pinned) |
| One workspace operating many projects | | | ✔ (self-developed) |
| Cross-session failure memory + repeat-error oracle *(experimental)* | | | ✔ (self-developed, harness-core — benefit unproven in vivo) |
| FAST/STANDARD/DEEP cost policy | | | ✔ (self-developed) |
| Three-tier gate for irreversible commands | | | ✔ (self-developed) |

**Install** (Python ≥ 3.10 + Claude Code CLI; Windows primary, Linux/macOS via CI):

```bash
git clone https://github.com/zhongli369/ai-workbench.git && cd ai-workbench
python tools/workbench.py doctor
python tools/workbench.py install && python tools/workbench.py launch
```

**See it work** — three reproducible demos (offline verifiable):
[1 · one workspace, two projects with conflicting rules](docs/demos.md#demo-1) ·
[2 · a failure recorded in session A is reused in session B](docs/demos.md#demo-2) ·
[3 · multi-file feature with on-demand capabilities](docs/demos.md#demo-3).
Measured results, including the ones we're not proud of: [Performance](#honest-performance-notes).

```
workbench/            ← launch Claude Code here; it loads this workspace's CLAUDE.md
harness-core/         ← self-developed: failure store, gate, telemetry, checkpoints, planning (stdlib, 120 contracts)
hooks/                ← PreToolUse gate hook (fail-closed in ENFORCE mode)
vendor/ecc/           ← third-party: everything-claude-code snapshot (MIT, pin recorded)
tools/workbench.py    ← installer / doctor / launcher / uninstaller
```

## What you get

| # | Differentiator | How |
|---|---|---|
| 1 | One entry, many projects | Launch once, then `cd`-free cross-project work (absolute paths, `git -C`) |
| 2 | Correct rules per target | Project-level `claudeMdExcludes` keeps global rule packs from shadowing a target project's own CLAUDE.md |
| 3 | ECC capabilities on demand | 30 skills / 16 agents from everything-claude-code, loaded per-task, not resident |
| 4 | Cross-session failure memory **(experimental)** | `harness-core` records why approaches failed; the oracle is queried when a failure is hit (fail-triggered). Mechanism contract-verified; in-vivo retrieval benefit **unproven** across six controlled experiments — see honest notes |
| 5 | Complexity-matched tokens | FAST / STANDARD / DEEP policy: small fixes skip planning, agents, and bookkeeping; RECOVERY mode handles stuck states with explicit signals (a single test failure never triggers a recovery cascade, and safety rails are never disabled to get unstuck) |
| 6 | Deterministic quality & safety | 230 offline contracts; three-tier gate (DISABLED / AUDIT / ENFORCE) for irreversible commands; versioned checkpoints with torn-tail recovery for long-horizon work |
| 6b | DEEP-mode planning scaffold | `harness plan`: deterministic 13-archetype phase + acceptance-criteria scaffold, on-demand CLI, never auto-injected; phases double as checkpoint stages |
| 7 | No per-project harness install | Install the workbench once; target projects stay untouched |

## Install

Requirements: **Python ≥ 3.10**, Claude Code CLI. Windows is the primary tested
platform; Linux/macOS use the POSIX code paths exercised in CI.

```bash
git clone https://github.com/zhongli369/ai-workbench.git
cd ai-workbench
python tools/workbench.py doctor                      # preflight, never mutates
python tools/workbench.py install --scope standalone  # default: platform data dir
python tools/workbench.py launch                      # prints the exact launch command
```

Scopes: `standalone` (default, single dir) · `project` (`.ai-workbench/` inside a
repo) · `user` (prints manual global-config steps — **never** edits your global
config silently).

Uninstall removes only files this distribution owns (tracked in
`install-manifest.json`) and preserves your feedback data unless `--purge-data`:

```bash
python tools/workbench.py uninstall --yes
```

## 5-minute quickstart

1. `python tools/workbench.py install --yes`
2. Run the command printed by `python tools/workbench.py launch`
3. Inside the session, point at any project: *"fix the failing test in D:\some\other\repo"*
4. Deliberately trigger a guardrail: *"git push"* — watch the gate log an AUDIT entry
   (switch to ENFORCE with `python harness-core/harness/cli.py gate mode --set enforce`)
5. Next session, the failure store is still there: `status` shows your accumulated records.

## The failure-memory demo (experimental — mechanism, not proven payoff)

```bash
# session 1 — a failure happens and is recorded
python harness-core/harness/cli.py feedback record \
  --project-id demo --cause permission_tool_mismatch \
  --summary "allowedTools listed Bash(python:*) but the model used the PowerShell tool" \
  --source human-verified --confidence 1.0

# session 2 — the same error class appears; query before retrying
python harness-core/harness/cli.py feedback query --project-id demo --keyword allowedTools --json
# → the past fix surfaces; you don't pay for the same debugging twice
```

The oracle is consulted when a failure is actually **encountered** (fail-triggered) or on explicit request — not on every
task. (Measured: consulting it on a fresh single-defect bugfix roughly doubled
cost with zero quality gain. The policy now encodes that.)

## Honest performance notes

Measured on the reference machine (Claude Code 2.1.x, `--output-format json` usage):

- **Resident context** (structural, model-independent, `workbench benchmark`):
  workbench L0 ≈ 1.7 k chars; L0 + full skill index ≈ 9.0 k chars vs the
  equivalent global rule layer at ≈ 20.7 k chars → **−57%** (L0 alone −92%).
- **Fixed trivial prompt**: vnext $0.0199 vs baseline $0.0228 (same model, same
  prompt, N=1 each).
- **Task-level cost is the hard part**: our first controlled bugfix A/B
  measured vnext at **2.33×** baseline cost ($1.335 vs $0.569). Root-caused to
  (a) permission-pattern trial-and-error and (b) oracle consultation on fresh
  defects. After shipping both fixes, the controlled rerun measured **1.22×**
  ($0.540 vs $0.444, both arms PASS, zero oracle calls in either arm). The
  residual gap is turn-count behavior, not resident context (vnext non-cached
  input was 62% *lower*). Not yet "≈ baseline" — tracked in
  `RELEASE_READINESS.md` (G4). We publish negative results, we don't delete them.
- **Full task-type matrix** (all N=1 per arm, transcripts audited; details in
  `RELEASE_READINESS.md` G10 and `docs/POLICY_VERIFICATION.md`):
  trivial **0.87×** · bugfix **1.22×** · multi-file feature **0.84×** ·
  test-diagnosis **1.81×** (the fail-triggered policy costs ≈$0.34 when the
  store is empty — that tax is also what populates the store; the same arm
  organically recorded its correct diagnosis back).
- **Fusion-arm exploratory benchmark (2026-10, `claude-haiku-4-5`, N=1 per cell):**
  early exploratory benchmarks showed lower task cost in three small tasks
  (fusion/native cost ratios 0.85× / 0.70× / 0.64×), with all six runs passing.
  Larger controlled studies are pending. These cells establish "no large tax on
  easy tasks" — they do **not** establish superiority, turn-count effects, or
  cross-model behavior.
- **Repeat-error oracle: honest-null, disclosed.** Across three controlled
  pairs with seeded failure history (including one purpose-built scenario
  whose root cause lived in data state, not code), the seeded arm **never
  queried the oracle** — the model self-diagnosed, once independently
  choosing the seed's own recommended fix. The mechanism (record → store →
  query → project isolation) is contract-verified and the policy never
  produced wasteful queries, but an in-vivo retrieval benefit is **unproven**
  and we say so. The oracle's plausible domain is failures whose root cause
  is not readable anywhere in the project (environment/config/history).

## What is inherited vs self-developed

| Component | Origin |
|---|---|
| Skills / agents / commands (30+16+14) | **Inherited** — [everything-claude-code](https://github.com/affaan-m/everything-claude-code), MIT, pinned snapshot in `vendor/ecc/` (see `NOTICE`) |
| harness-core (feedback, gate, report, telemetry, checkpoint, plan) | **Self-developed**, stdlib-only, deterministic, 120 contracts |
| Installer / launcher / uninstaller | **Self-developed** |
| FAST/STANDARD/DEEP cost policy | **Self-developed**, driven by measurements above |

## Safety semantics (read before relying on the gate)

- `DISABLED`: gate does nothing.
- `AUDIT`: records and prompts — **this is observability, not protection**.
- `ENFORCE`: configured high-risk patterns are blocked unless pre-approved
  (TTL approvals); unreadable config fails **closed**.
- One-time approvals: `gate approve --once --action "git push origin main"`
  issues a single-use token (`awt-…`, SHA-256 stored, TTL-bound, replay-safe)
  consumed by exactly one matching command; the raw token is printed once
  and never written to the audit log.
- `claude --print` (non-interactive) does not execute PreToolUse hooks — gate
  enforcement applies to interactive sessions. Verified 2026-10 on CC 2.1.x.

## Known limitations (Public Preview)

- **Windows is the primary tested platform.** Linux/macOS exercise the POSIX
  code paths in CI; fresh-install acceptance on those platforms is not yet
  human-verified.
- The gate's ENFORCE mode applies to **interactive** sessions only
  (`claude --print` skips PreToolUse hooks — verified on CC 2.1.x).
- The repeat-error oracle's in-vivo retrieval benefit is **unproven** (see
  honest performance notes); the mechanism is contract-verified.
- The bundled ECC snapshot is pinned at a 2026-05 revision; upstream fixes
  published after that date are not included (see `NOTICE`).
- First interactive launch in a fresh directory may require Claude Code's own
  trust confirmation — that prompt is yours to answer; the installer never
  bypasses it.

## Contributing & roadmap

Issues and PRs are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
The near-term roadmap (benchmark batch 2, platform acceptance, ECC pin
refresh) is tracked as gates in [RELEASE_READINESS.md](RELEASE_READINESS.md).

## Docs

- [README.zh-CN.md](README.zh-CN.md) — 中文说明
- [NOTICE](NOTICE) — third-party attribution & ECC pin rationale
- [SECURITY.md](SECURITY.md) — threat model & reporting
- [CHANGELOG.md](CHANGELOG.md) — release history
- [RELEASE_READINESS.md](RELEASE_READINESS.md) — gate-by-gate PASS/FAIL/PENDING status
- [harness-core/README.md](harness-core/README.md) — the memory/safety toolkit, usable standalone
- Maintainer gates: [docs/claims.json](docs/claims.json) (release claims verified
  against live sources), [docs/surface.json](docs/surface.json) (frozen public
  CLI/schema surface — additive changes are free, breaking changes require a
  major bump), [docs/incidents/registry.json](docs/incidents/registry.json)
  (named historical failures locked as permanent regression tests)

## License

MIT (this distribution's own code). everything-claude-code is MIT by its
respective authors — see `vendor/ecc/LICENSE` and `NOTICE`.
