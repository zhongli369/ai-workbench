# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0-preview.5] — OPERATION NEXT LEAP — Unreleased

Verified external capabilities, integrated only where evidence shows real
value: skill static quality gate SHIP, Codex second opinion SHIP (wiring
only, default OFF), Playwright CLI duel REJECT (MCP kept).
540 offline contracts (253 harness-core + 287 tests).
Development version — no GitHub Release is cut for this entry yet; the
latest published release remains `v0.1.0-preview.3`.

### Changed
- **R5 slim (LEAN by default, POWER on demand)**: payload reduced to 11
  kept skills + 1 kept agent (security-reviewer); the 19 duplicate skills
  and 15 duplicate agents moved to `workbench/disabled/` (not deleted —
  `git mv` back to restore). `workbench/CLAUDE.md` slimmed (task-grading,
  agent-dispatch and auto-plan/checkpoint workflow removed; safety floor
  and multi-project protocol kept). New `launch/workbench-power.ps1|sh`
  load the pinned Superpowers clone from `vendor/plugins/` via the
  `WORKBENCH_PLUGIN_DIR` adapter; LEAN launchers never load it.
  SessionEnd metrics hook KEPT (per-session ledger with session_id /
  human_msgs is not covered by `/cost`; zero measured maintenance cost).

### Added
- **Opt-in session-scoped plugin adapter** (`WORKBENCH_PLUGIN_DIR`, launcher
  templates + 1 contract): loads a pinned local plugin clone (e.g.
  obra/superpowers) via `--plugin-dir` — zero install, zero global state,
  unset to roll back. Adoption decision and evidence:
  `docs/open-source-adoption.md`.
- **SessionEnd metrics hook** (`hooks/session_metrics.py` + 9 contracts):
  one structured metric line per session from the transcript (counter-only,
  content-free), appended to `harness-data/session-metrics.jsonl` with
  cross-process append locking on Windows, message.id dedup, CJK-safe ASCII
  output, and never-blocks-exit semantics. Wired into the installed
  settings template (`timeout: 30`).
- **Deterministic correctness bench** (`tools/bench/deterministic/run_bench.py`):
  zero-LLM, offline bench of the real gate hook E2E (Bash/PowerShell),
  `verify run`, and `checkpoint` crash recovery against this checkout — 20
  assertion cases, exit 0 only when all pass.
- **Context audit + strict MCP launch default** (`tools/context_audit.py`):
  reports real tool-schema bytes by MCP server from Claude Code
  `api-request-shape` records, plus compact boundaries and re-injected
  instruction files. The generated launcher now passes
  `--strict-mcp-config`; global/user MCP servers are ignored, and only the
  workbench's on-demand `.mcp.json` is loaded when present.
- **Skill static quality gate** (`tools/check_skills.py` + 29 contracts in
  `tests/test_skills_quality.py`): offline, stdlib-only checks over the
  mounted skill corpus — frontmatter metadata/schema, static trigger routing
  (latin words + CJK bigram, minimum description pool), wiring integrity
  (registry ↔ disk ↔ template, hook-injection guard), and duplication WARN
  with registry-mutex suppression. Found a real defect on introduction:
  registry claimed "Curated ECC skills (27)" while 30 slots are mounted
  (fixed). Wired into CI static checks. Absorbed from
  anthropics/claude-plugins-official skill-creator's zero-cost static ideas
  only — no runtime, no eval loop. Static metadata routing only; proves
  nothing about live triggering.
- **Codex independent second opinion** (`capabilities/wiring/codex-review.skill.md`
  + registry entry `codex-review`, default OFF): on-demand, bounded,
  non-interactive review of one commit / branch diff / single file via the
  user-installed codex-cli, with read-only enforced by the CLI's own
  `sandbox_mode=read-only` (not by prompt). Health check is a new
  `cli-version` type (path + `--version` prefix) because the PATH `codex`
  on the dev machine is a decoy npm tool. Real E2E evidence: exit 0, 4
  substantive findings, two of them real gate regressions (below). See
  `docs/decisions/2026-10-16-codex.md`.
- **`cli-version` health type** (`tools/capability.py` + 4 contracts):
  full executable path (env-var expanded) must exist and answer `--version`
  with the declared prefix — fail-closed against same-named decoy tools.

### Fixed
- **PowerShell bypassed the ENFORCE gate** (P0): the PreToolUse hook only
  handled `Bash`, so `git push` / `Remove-Item -Recurse` ran in ENFORCE
  with no approval. The hook matcher is now `Bash|PowerShell`, the tool name
  is forwarded to `gate.evaluate()` (which appends PS recursive-delete
  patterns and matches case-insensitively on that path), and the audit log
  carries the `tool` field. Locked by 14 contracts in
  `harness-core/tests/test_gate_powershell.py`.
- **Gate authorization bound to the most-exposed shell variant** (found by
  the codex second opinion above, 3 regression contracts): a one-time token
  or approval bound to `git push origin main` previously also authorized
  `git push origin main $(curl …|sh)` — the payload hid in the shortest
  normalized reading. `_canonical_command` / `_is_approved` now use the
  longest (most-exposed) variant only, and the 32-variant cap always keeps
  both aggregate readings (all-substitutions-removed / all-inlined) instead
  of trimming lexicographically.
- **Registry count drift**: `ecc-skills` name "Curated ECC skills (27)" →
  (30), caught by the new skill quality gate.
- **Session-metrics token counting took the first streaming snapshot**:
  duplicate assistant events share one `message.id`, and for ~43% of
  duplicate groups (190/438 measured across 12 production transcripts) the
  first event is a `(0,0,0,0)` placeholder — first-seen dedup undercounted
  tokens (worst subagent transcript ~27×). Aggregation now takes the LAST
  snapshot per `message.id` (sequences verified monotonically
  non-decreasing, so last == per-id max). 2 streaming-semantics contracts.
- **`verify run --cmd` distorted quoted arguments on Windows**:
  `shlex.split(posix=False)` keeps quotes, so `--cmd 'python -c "…"'`
  silently ran the wrong code yet exited 0 (false PASS) and quoted paths
  with spaces were split apart (command never ran). Windows now splits via
  `_split_windows_cmdline`; POSIX unchanged. 10 contracts.
- **Reinstall clobbered user edits to `.claude/settings.json`**: the
  installer regenerated its rendered template wholesale. It now merges —
  installer-owned keys refresh exactly, user keys (env vars, permissions,
  extra hook entries, extra `claudeMdExcludes`) are preserved, hook entries
  never accumulate, and an unparseable existing file is backed up as
  `settings.json.user-bak` before the fresh render. Same user-data rule as
  `PROJECTS.md` / `gate.json`. 2 contracts.
- **Gate security matrix locked**: 14 contracts pin the block/allow
  contract for quoting/escaping, command chains, cross-shell wrappers
  (`powershell -Command`, `cmd /c`, `bash -lc`), prefix-abbreviated PS
  flags and alias vocabularies — 61-case review found no real bypass; the
  matrix keeps it that way.

### Decisions (no code change)
- **Playwright CLI vs MCP duel — REJECT (keep MCP)**:
  `@playwright/cli@0.1.22` reached only parity (4/4 PASS both sides) against
  the wired `@playwright/mcp@0.0.83` on B1–B4 real-browser tasks; MCP was
  faster wall-clock (persistent process vs per-command node spawn), CLI
  output more compact but no token-savings claim made (no model logs
  collected); CLI's `eval` subcommand name collides with the local gate
  hook on Bash commands (standing integration tax). Verdict C: zero wiring
  change, MCP remains the only browser path. See
  `docs/decisions/2026-10-16-playwright-cli.md`.

## [0.1.0-preview.4] — OPERATION ONE WORKSPACE — Unreleased

One workspace, many projects: natural-language multi-project experience plus
a full README rebuild. 439 offline contracts (201 harness-core + 238 tests).
Development version — no GitHub Release is cut for this entry yet; the
latest published release remains `v0.1.0-preview.3`.

### Added
- **`mcp-config` wiring type** (`tools/wiring_mcp.py` + 47 contracts in
  `tests/test_wiring_mcp.py`): wires a browser capability to the target
  project's native `.mcp.json` on demand — default OFF, readiness-gated
  (node/npm/pinned package/browser, never auto-installed), owns-only mutation
  of one reserved server key (`aiwb-playwright`), idempotent re-enable, and a
  four-state status (`not-installed` / `installed-not-enabled` /
  `enabled-not-connected` / `connected-tested`) backed by a real stdio MCP
  handshake. Pinned to `@playwright/mcp@0.0.83`; optional SKILL.md half wired
  from `capabilities/wiring/playwright-mcp.skill.md`. See
  `docs/decisions/2026-10-15-playwright.md`.
- **`capability` CLI gains mcp-config dispatch + four-state `status`**
  (`tools/capability.py`, `tools/workbench.py`): `capability enable/disable/
  status playwright-mcp` drives the wiring end to end — mutex still enforced,
  readiness failure fail-closed, handshake failure WARN-only,
  `--allow-missing-browser` escape hatch exposed at CLI level (explicitly
  accepts no browser, WARN not FAIL). `status` probes the actual `.mcp.json`
  entry content (a user-edited command is probed as written and the detail
  says so), not a registry-derived argv. Uninstall sweeps every managed
  `.mcp.json` entry and managed SKILL.md (owns-only, marker checked).
  Registry entry upgraded from recorded-intent to mcp-config.
- **`superpowers-systematic-debugging` capability** (skill-file wiring,
  pure-content): adapted port of superpowers' systematic-debugging skill
  (pin `bb92a77`, MIT text reproduced in-file), stripped of the SessionStart
  hook and forced phase-gated workflow language; OFF by default. Rejections
  and dedup evidence in `docs/decisions/2026-10-15-superpowers.md`; port
  recorded in NOTICE.
- **Per-project checkpoint namespacing** (`harness-core`): `checkpoint
  begin/save/load/replay/verify` and `plan` accept `--cwd` / `--project-id`;
  scoped records land in `<project>~<exec>.jsonl` (flat layout byte-identical
  when omitted), so the same exec name in two projects no longer collides.
  `verify run` gains `--project-id` passthrough. Isolation assertions folded
  into existing contract files (no new pytest items).
- **PROJECTS.md scaffold**: install writes a project quick-reference template
  (never overwritten on reinstall, removed by owns-only uninstall, tracked in
  the install manifest). Project identification stays user-driven — no disk
  scanning, no project database.
- **Multi-project operation protocol** (`workbench/CLAUDE.md` +
  `docs/multi-project.md`): identification rules, `--add-dir` /
  `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD` behavior verified against
  the installed CC build (2.1.x), per-project harness scoping, `git -C`
  discipline, and an honest capability classification (native / wired-trigger
  / on-demand / explicitly-authorized).
- **Multi-project isolation suite** (`tests/multiproj/`, 15 contracts, cases
  A–E): dual-project data isolation with per-stage byte fingerprints,
  cross-project read-only probes (zero writes), snap/verify scoping,
  gate-hook enforcement matrix driven through real stdin JSON (disabled /
  audit / enforce / one-time-token replay / corrupt-config fail-closed), and
  zero-overhead plain-project checks — all against real temporary git repos.
- **README.md / README.zh-CN.md fully rebuilt**: 12-section structure,
  delivered-capability inventory with trigger classification (native /
  wired-trigger / on-demand / explicitly-authorized), live-verified counts,
  mermaid architecture diagram, honest limitations list, and real links only
  (CI / security / release / license).

### Changed
- `tests/multiproj/` is collected by the default `pytest tests/` run; repo
  totals reconciled everywhere (README ×2, this file, ci.yml, claims.json):
  **439 offline contracts = 201 harness-core + 238 tests**.
- **Security scan bounded retry** (`tools/security_scan.py`): a transient
  tool-side infra failure (scanner ran and exited non-zero, e.g. a trivy DB
  download 404 from a registry mirror) is retried up to 2 times with a fixed
  20 s delay. Timeouts, spawn failures and real results (clean/findings) are
  never retried; the returned status is always the last attempt's real
  status, so fail-closed semantics are unchanged. Motivated by a real CI
  infra-failure on an otherwise-green PR.
- `test_gate_is_not_vacuous` now asserts the figure gate stays *armed*
  (`figure_docs` configured) instead of requiring a non-empty figure
  whitelist — an empty whitelist is the honest state when the docs carry no
  perf figures; the synthetic negative contracts keep the figure path proven.

### Fixed
- **Launch hint argument order** (`tools/workbench.py`): install's completion
  message printed `launch --target X`, but `--target` is a global option and
  copying the hint failed with `unrecognized arguments: --target` (confirmed
  against the published preview.3 bundle). Now prints `--target X launch`
  plus the `--run` variant; regression-asserted in the clean-room suite.
- **Checkpoint cross-project collision**: two projects using the same
  checkpoint exec name overwrote each other's flat store records; fixed by
  the scoped namespacing above.
- **CRITICAL — ENFORCE gate shell-expansion bypass** (`harness-core/harness/gate.py`):
  bash resolves `${IFS}`, `$IFS`, brace expansion (`{git,push}`), command
  substitution (`$(...)`, backticks), empty quotes and backslash escapes at
  runtime, but the gate matched enforce/audit patterns against the RAW
  command string — so `git${IFS}push origin main` executed as a real
  `git push` yet matched nothing and was ALLOWED under ENFORCE (found by
  real fault injection). Patterns now match against a bounded set of
  shell-normalized variants (fail-closed union: over-block, never
  under-block); approvals and one-time tokens canonicalize both sides so an
  approval still authorizes the same action spelled differently (incl.
  Windows backslash paths). 30 regression contracts in
  `harness-core/tests/test_gate_shell_expansion.py`.
- **`launch` extra-arg passthrough** (`tools/workbench.py`): extra args after
  `--` are forwarded to the launcher script (e.g.
  `launch --run -- --add-dir "<path>"`); previously the documented
  `--add-dir` form exited 2 (`unrecognized arguments`) and
  `docs/multi-project.md` told users to type it. Doc corrected; regression
  in the clean-room suite.
- **Idempotent reinstall truncated the install manifest**: files the
  reinstall did not rewrite (user-edited `PROJECTS.md`) lost their ownership
  entry, so a later owns-only uninstall left them behind. The reinstall now
  merges the previous manifest's file list (dropping paths that no longer
  exist); regression proves reinstall → uninstall removes `PROJECTS.md`.
- **`RELEASE_READINESS.md` superseded header**: the preview.1 freeze block
  (216 files / 174 contracts) read as the current state; a superseded banner
  now points to CHANGELOG + `docs/claims.json` for live numbers. Body kept
  as historical record.

## [0.1.0-preview.3] — OPERATION ARSENAL — 2026-10-15

Absorption of three externally-proven mechanisms into harness-core (origins
recorded per capability in `capabilities/registry.json`; every mechanism
reimplemented stdlib-only — no vendored code, no new runtime dependencies).
335 offline contracts (171 harness-core + 164 tests). The increment over
preview.2 is 24 battle tests under `tests/battle/` (real-behavior checks for
snap/verify/gate/checkpoint) plus 6 clean-room installer regressions;
drift-gate claims in README / README.zh-CN / CI are reconciled to the live
counts.

### Added
- **`harness snap`** (`harness-core/harness/worktree_snap.py`, algorithm
  adapted from cline@789f79e4 Apache-2.0): git-backed workspace file
  snapshots. Captures tracked AND untracked files into
  `refs/harness/snaps/<exec>/<seq>`; restore is dry-run by default (status
  `planned`, never claimed as `restored`), writes only the snapshot's
  managed file set, never deletes unknown untracked files, fails closed on
  three-way concurrent edits, creates a rescue ref before any write, and
  detects interrupted restores via a journal. NEVER issues
  `git reset --hard` / `git clean -fd`. `--apply` is explicit operator
  approval and consults the gate (AUDIT logs; ENFORCE patterns block).
- **`harness verify`** (`harness-core/harness/verify.py`, mechanism adapted
  from aider@5dc9490b Apache-2.0): bounded post-edit lint/test verification
  per stage. Commands come from `.harness-verify.json` (operator
  pre-authorization) or an explicit `--cmd` that is gate-consulted
  (DISABLED refuses fail-closed, AUDIT logs+allows, ENFORCE consumes a
  one-shot token). argv-only execution, output truncated, verdicts appended
  to a sha256 evidence log. `verify status` is the mechanical completion
  gate: a stage whose latest verdict is not `pass` cannot be claimed done
  (`can_claim_done`); failures write `status="failed"` checkpoints.
  Reflections bounded (default 3, hard cap 10).
- **Release supply-chain gate** (`.github/workflows/security.yml` +
  `tools/security_scan.py`, trivy-class, CI-only — zero daily token/FAST
  overhead): trivy binary pinned by version + sha256 (GitHub server-side
  digest), all actions pinned by commit SHA. Honest exit semantics:
  `3 = tool-missing/infra-failure` never reads as PASS; blocking on
  main/tags/release/PR-to-main, AUDIT elsewhere; reports to artifacts only
  (matched secret text never logged); `.securityignore` exceptions are
  expire-aware and reviewable.

## [0.1.0-preview.2] — TOTAL FUSION (refactor/total-fusion)

Engineering annexation of the three retired legacy projects
(SystemKernel / WorkFlow / CodeLike): useful mechanisms absorbed as native
stdlib components, duplicates deleted, external pointers removed.

### Added
- **`harness checkpoint`** (`harness-core/harness/state.py`): versioned,
  append-only task-state checkpoints with t8-class integrity — per-record
  payload sha256, torn-tail detection reported explicitly (damage is never
  indistinguishable from absence — the SystemKernel `load_latest` silent-None
  bug class), BOM/CRLF-tolerant reads, pure-ASCII writes, atomic crash marker
  for in-flight stages, parent-chain + stage-order `verify` (exit 1 on any
  damage). Raw evidence is never truncated, overwritten, or repaired.
- **`harness plan`** (`harness-core/harness/plan.py`): deterministic DEEP-mode
  scaffold — bilingual 13-archetype classifier → ordered phases with
  per-phase static risk + per-archetype acceptance criteria. Minimal
  extraction of the retired CodeLike planning kernel (classifier / templates /
  risk / AC only; feedback adaptation, prompt factory, regex enrichment and
  project-scan coupling deliberately NOT migrated — the native failure oracle
  already covers failure memory). `--save` persists the plan as a stage-0
  checkpoint; phase names double as checkpoint stages.

### Changed
- **Capability Registry**: the external `planning-kernel` entry (pointed at a
  CodeLike checkout via `AIWB_CODELIKE_CLI`, 0 external pulls upstream) is
  replaced by two native capabilities: `harness-plan` and
  `harness-checkpoints`, both file-health-checked, zero-dependency, on by
  default at zero resident cost.
- Workbench DEEP policy: long-horizon/multi-phase work uses `harness plan
  --save` + per-phase `harness checkpoint` for cross-session resume and
  integrity verification.
- Contract totals: 230 offline contracts (up from 174; harness-core 120,
  up from 64: +19 state, +37 plan). Public surface: additive only
  (checkpoint/plan commands), 0 breaking.

## [0.1.0-preview.1] — 2026-10-14

First **Public Preview**. Everything from 0.1.0-rc.1 plus the FUSION OMEGA
milestones M3–M5 below. 230 offline contracts, hygiene / ECC-provenance /
compile gates all green on the release commit.

### Added (post-RC hardening — legacy power-up P1)
- **Docs Drift Gate** (`tools/check_docs_drift.py` + `docs/claims.json`):
  release claims are structured data checked against live sources (pytest
  collection, ECC payload counts, VERSION constant); performance figures must
  carry their qualifier (N=1 / controlled / model-independent) in the same
  paragraph block. Release statements are constrained by evidence, not memory.
- **Frozen Public Surface Verifier** (`tools/check_public_surface.py` +
  `docs/surface.json`): explicit manifest of the committed CLI commands/flags,
  JSONL schemas and settings keys; removal/retype/choice-shrink = BREAKING
  (requires `--accept-new --bump major` + rationale), additions are free.
  Internal refactoring stays aggressive; the public API cannot break by accident.
- **One-time approval tokens** (`gate approve --once --action …`): single-use,
  TTL-bound, scope-limited (`awt-…`, SHA-256 stored only), atomic consumption
  under a store lock, distinct replay/expiry/scope denials, raw token never in
  the audit log. AUDIT mode never consults tokens.
- **Incident replay contracts** (`docs/incidents/registry.json` +
  `tests/test_incident_replay.py`): four named historical failures (permission
  probing, verify-wrong-root, `__pycache__` provenance pollution, user-path
  leakage) locked as permanent regression tests; the bench driver hashes each
  task's verifier pre/post agent run and voids tampered results.
- **Telemetry self-exclusion** (harness-core telemetry): reader commands
  (`telemetry`, `feedback stats`, `report`, `gate check`) are never logged;
  every row carries a source label (`cli` / `bench` / `synthetic`;
  `HARNESS_BENCH=1` marks paid experiment traffic); `summarize()` is a pure
  read and its adoption view counts only real `cli` invocations, so bench or
  synthetic traffic can never masquerade as product usage.

### Added
- **Capability Registry v1** (`capabilities/registry.json` + `tools/capability.py`):
  10 capabilities (5 built-in active, 5 external optional recorded-intent) with
  list/inspect/enable/disable/doctor, mutual-exclusion enforcement, fail-closed
  corrupt-state handling. The registry is contractually barred from model context.
- **Capability wiring v1.1**: enabling an external capability now writes a
  managed, marker-stamped `.claude/skills/aiwb-<id>/SKILL.md` (registered in
  `install-manifest.json` so owns-only uninstall sweeps it). Enable requires a
  passing health check; the workbench **never auto-installs external software**.
- **Oracle v3** (harness-core feedback): BM25 re-ranking over substring-filtered
  candidates (filter semantics unchanged), `valid_until` expiry (hidden by
  default, never deleted), append-only `supersede` chains, fsync + read-back
  write honesty (a record that cannot be verified on disk is an error, not a
  success), empty-store fast-negative. +11 contracts.
- **Benchmark infrastructure** (`tools/bench/`): official claude-agent-sdk
  driver, three original canary tasks (FAST rename / STANDARD failing-test with
  hash-pinned protected test / DEEP-lite multi-file feature), hard per-run
  budget gate ($0.75) and batch cap ($3.00), isolated per-arm workspaces,
  native-vs-fusion arm comparison, right-reason verify contracts (verify must
  fail on the pristine seed *and* emit `VERIFY FAIL`).

### Changed
- Hygiene gate now scans the publishable set (git-tracked files) and also
  rejects user-profile paths (`C:\Users\<name>\…`) — closes the M5 blind spot
  where local benchmark evidence JSONs matched no pattern.
- ECC provenance checker ignores incidental `__pycache__` bytecode so local
  tooling can no longer fake snapshot drift.
- Benchmark result JSONs stay local (`tools/bench/results/` gitignored): they
  contain one-shot temp workspace paths.

### Measured (exploratory, N=1 per cell — not generalizable)
- Benchmark batch 1 (claude-haiku-4-5, 6/6 runs passing, $0.467 of $3.00 cap):
  fusion/native cost ratios 0.85× / 0.70× / 0.64× on three small tasks.
  Reading: "no large fusion tax on easy tasks". Larger controlled studies pending.
- Benchmark batch 2 (claude-haiku-4-5, 8/8 runs passing, $0.355; cumulative
  ledger $0.822 of the $3.00 cap): three-arm matrix native > fusion ≥ ecc-only
  directionally consistent on t1/t2/t4 (no statistically established
  difference); zero Skill/harness/oracle invocations across all 8 runs — the
  harness is a free option on green-run tasks; the seeded-experience arm
  solved its variant cheaper but made 0 oracle queries (third independent
  seeded arm with 0 queries: the in-vivo reuse benefit remains unproven by
  design on tasks agents solve without failing); verifier hashes identical
  pre/post on every run.
- PHASE P discriminative task battery (offline layer, behaviorally
  validated; paid runs pending/in flight — see RELEASE_READINESS):
  t6-external-config-drift (root cause in external state, four arms incl.
  oracle-seeded), t7-validator-drift-refactor (deep multi-file refactor,
  hash-pinned shipped suite, shape-agnostic dedup check),
  t8-log-pipeline-resume (long-horizon: two sequential fresh sessions per
  arm resuming from a workspace checkpoint; self-contained verifier with
  inlined oracle + LF-normalized input pin).
- Benchmark batch 3 / t6.1 (claude-haiku-4-5, 4/4 arms passing, $0.2845;
  cumulative ledger $1.107 of the $3.00 cap): external-config-drift
  recovery — native $0.0892/15t, ecc $0.0774/6t, fusion-empty $0.0726/12t,
  fusion-seeded $0.0452/7t, verify hashes untampered. **Zero oracle queries
  on every arm** — fourth independent seeded arm with no reads. PHASE P2
  §1.3 verdict: honest-null class (workspace-readable diagnosis makes
  direct read-then-fix the correct strategy; zero queries ≠ harness
  failure). The seeded arm's lower cost is disclosed as NOT attributable
  (treatment never read). Two earlier runs voided by a task/tooling defect
  (foreground serve-forever blocked the SDK Bash call; agent's fix was
  correct both times) — repaired by t6.1's self-terminating verify command
  with zero double-billing.
- **P4 oracle product decision: EXPERIMENTAL / ON-DEMAND (final for this
  cycle).** Mechanism contract-verified; payoff never observed across four
  seeded arms; no measured cost harm → no removal; no attributable benefit
  → no upgrade. The unbuilt §1.5 structural-trigger proposal stays unbuilt:
  the model's no-query choice was correct in every case so far.
- Benchmark batch 4 / t7 (claude-haiku-4-5, 3/3 arms passing, $0.4307;
  cumulative ledger $1.537 of the $3.00 cap): deep multi-file validator
  refactor — native $0.1558/22t, ecc $0.1235/18t, fusion $0.1514/27t, verify
  hashes untampered, all arms completed the dedup under the frozen API/CLI.
  Zero skill/oracle calls on every arm (fail-triggered policy correctly
  silent on a green-run task). Direction only (N=1, exploratory):
  cost ecc < fusion < native; no measurable harness tax or benefit.
- Benchmark batch 5 / t8 (claude-haiku-4-5, two-session resume protocol,
  $0.7992; cumulative ledger $2.337 of the $3.00 cap): native PASS $0.2961
  (A 18t / B 21t), ecc PASS $0.2713 (A 20t / B 16t), fusion FAIL $0.2318
  (A 9t / B 22t). Two-session resume worked on all three arms (session B
  never redid a stage). Checkpoint honesty: native/ecc truthful (certutil
  uppercase hex / PowerShell BOM — platform-tool artifacts), fusion
  corrupted (render hash truncated to 30 chars — honest agent failure).
  The initial all-FAIL verdict was root-caused to two verifier
  platform-tolerance defects (case-sensitive hex, strict utf-8 JSON) —
  repaired once per directive §2.1 (t8.1), re-verified on the frozen
  workspaces with zero re-billing, v1 verdicts preserved, and locked by
  8 new offline contracts (tests/test_t8_verify.py). Zero oracle queries
  everywhere: the failure was silent, so fail-triggered could not fire.

### Changed (policy, evidence-driven)
- Failure-oracle trigger corrected from "query on 2nd occurrence of the same
  error" to **fail-triggered** (query before debugging/retrying an actual
  failure; never by default on a fresh task). The old condition was
  unfireable in a single session — the model cannot know an error is a
  repeat without querying first (r2 arm, transcript hCLI=0). The 2.33×
  lesson (never query by default) is preserved.

### Added
- `experiment-seed` feedback source: synthetic benchmark fixtures, writable
  and queryable, explicitly barred from promotion into production evidence
  (+1 harness-core contract → 27).
- docs: `demos.md` (three reproducible demos), `POLICY_VERIFICATION.md`
  (tier policy: structural guarantees vs measured behavior vs pending;
  includes the CC env-precedence addendum).
- RELEASE_READINESS: G7 PASS(local)/PENDING(remote), G9 PASS(probe),
  G10 task-type matrix (trivial 0.87× / bugfix 1.22× / feature 0.84× /
  recovery honest-null).
- Recovery controlled pair (r3c vs r4b): oracle arm made **zero queries**
  because the noter bundle's `notes.py` docstring names both root causes —
  the fail-triggered policy correctly skips the oracle when the answer is
  code-visible (free-option behavior confirmed). The arm's −30% cost vs
  control is disclosed as N=1 variance with the treatment unused, NOT as an
  oracle benefit. Code-visible-bug scenarios are documented as unsuitable
  for measuring oracle retrieval value.
- E4 env-class pair (e4c vs e4o, purpose-built data-state root cause):
  honest-null again — seeded arm self-diagnosed for $0.307 with zero
  queries; control burned 3 queries on an empty store. Across all three
  seeded arms, a model-issued query hitting a reachable seed has never been
  observed. The oracle's necessary domain narrows to root causes not
  readable anywhere in the project; hook-time query nudge recorded as a
  v1.1 proposal (not built).
- G10 diagnosis pair (g2 vs g2b): vnext 1.81× ($0.754 vs $0.417) — the
  fail-triggered policy is NOT free when the store is empty (2 skill loads
  + 2 queries + bookkeeping ≈ $0.34). Offset observed in-vivo: the vnext
  arm organically recorded its correct diagnosis back to the store — the
  first unscripted capture-loop write.

### Fixed
- failure-oracle skill claimed source-weighted query ranking; the
  implementation is time-ordered. Documentation corrected to match reality.

## [0.1.0-rc.1] — 2026-10-13

First release candidate. Feature set:

### Added
- Installer CLI (`tools/workbench.py`): `doctor`, `install` (standalone /
  project / user scopes, idempotent, `--dry-run`, `--force` backup),
  `status`, `launch`, `benchmark`, `uninstall` (manifest-driven, owns-only,
  data-preserving unless `--purge-data`).
- `harness-core`: failure feedback store (v2 schema: source/confidence/status,
  redaction option), keyword query, recurring-cause report, promotion ledger
  (append-only, human-gated), three-tier gate (DISABLED/AUDIT/ENFORCE,
  fail-closed), telemetry ledger. 26 offline contracts.
- Workbench layer: CLAUDE.md with FAST/STANDARD/DEEP cost policy; 27 skills,
  16 agents, 14 commands (27/16/14 from pinned everything-claude-code
  snapshot; 3 skills self-developed: failure-oracle, experience-capture,
  workbench).
- PreToolUse gate hook (`hooks/harness_gate.py`).
- Launch scripts (PowerShell + POSIX) with the process-env workaround for
  `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD`.
- Clean-room installer contracts (11) and a publishable-tree hygiene gate.
- CI: contract matrix (3 OS × 3 Python), static checks, CLI smoke, package build.

### Measured and disclosed (not deleted when unfavorable)
- Resident context: L0 ≈1.7k chars; L0+skill index ≈9.0k vs ≈20.7k chars
  equivalent global rule layer (−57%; L0 alone −92%).
- Fixed trivial prompt: $0.0199 vnext vs $0.0228 baseline (N=1 each).
- First controlled bugfix A/B: vnext 2.33× baseline cost — root-caused to
  permission-pattern trial-and-error plus oracle consultation on fresh
  defects. Controlled rerun after fixes: **1.22×** ($0.540 vs $0.444, both
  arms PASS, zero oracle calls). Residual gap = turn-count behavior, not
  resident context. Details in RELEASE_READINESS.md (G4).

### Known limitations
- Claude Code `--print` does not execute PreToolUse hooks; gate enforcement
  applies to interactive sessions.
- ECC pin (928076cc, v2.0.0-rc.1) could not be re-verified against upstream
  at RC time (network); must be re-checked before v1.0.
- Windows primary; Linux/macOS covered by CI paths, not by interactive use.
