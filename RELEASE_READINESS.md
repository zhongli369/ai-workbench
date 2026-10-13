# RELEASE READINESS — 0.1.0-rc.1

Verdict per gate: **PASS** / **FAIL** / **PENDING** (with the exact evidence or
the exact missing step). Nothing here is aspirational. Negative history is
kept, not deleted.

Reference machine: Windows 11, Python 3.12, Claude Code 2.1.x (2026-10-13).

---

## Public Preview gates

### G1 — Installs on a clean machine: **PASS**
- 11 clean-room contracts (`tests/test_cleanroom_install.py`): fresh-dir install,
  foreign-dir refusal + `--force` backup, idempotent reinstall (user gate config
  preserved), dry-run writes nothing, project-scope install, doctor never mutates.
- Installed tree renders every `{{ROOT}}`; zero builder-machine paths in copied
  payload (contract-enforced); `tools/check_hygiene.py` PASS.
- Install → status → benchmark → uninstall round-trip exercised in CI on
  Windows / Linux / macOS.

### G2 — Uninstalls cleanly, owns-only: **PASS**
- Manifest-driven deletion; refuses without manifest (contract).
- User data (`harness-data/`) preserved unless `--purge-data`; foreign files in
  the target dir untouched (contract).
- Post-uninstall purge removes the tree completely (contract).

### G3 — Contracts green offline: **PASS**
- 41/41 (12 clean-room + 27 harness-core + 2 misc) in ~5 s, stdlib + pytest
  only, no network, no Claude Code, no model login. Harness-core grew one
  contract on 2026-10-13: `experiment-seed` source round-trip (synthetic
  benchmark fixtures are writable/queryable and clearly marked — they must
  never be promoted into production evidence).

### G4 — Honest performance story: **PASS (with disclosed residual gap)**
Measured (same machine, same model, `--output-format json`):

| Benchmark | baseline (native CC) | vnext | ratio |
|---|---|---|---|
| Resident context (structural, `workbench benchmark`) | ≈20.7k chars global rule layer | L0 ≈1.7k; L0+skill index ≈9.0k chars | **−57%** (L0 alone −92%) |
| Fixed trivial prompt (N=1 each) | $0.0228 | $0.0199 | 0.87× |
| Bugfix task T3+T4, first A/B (2026-10-13, kept as negative history) | $0.569 / 16 turns | $1.335 / 44 turns | **2.33×** |
| Bugfix task T3+T4, rerun after permission+policy fix | $0.444 (1 denial) | $0.540 (3 denials) | **1.22×** |
| Multi-file feature (search+edit subcommands, 4 selfchecks) | $0.587 / 25 turns (3 den) | $0.491 / 29 turns (3 den) | **0.84×** — vnext cheaper |
| Repeat-error recovery, oracle seeded vs control | see G10 | see G10 | measuring |

Rerun analysis: both arms PASS selfcheck; **zero oracle queries, zero skill
loads in both arms** (FAST policy held). vnext non-cached input was 62% LOWER
(16.9k vs 44.8k tokens); the residual gap comes from more turns/output in the
task path (cache_read 650k vs 335k, output 5.2k vs 2.1k), not from resident
context. Optimization target "≈ or below baseline on ordinary tasks" is **not
yet met** on bugfix — but the feature-type A/B (4/4 selfchecks PASS both arms,
transcript-verified zero Task/Skill/oracle calls both arms) landed at 0.84×.
N=1 per arm per type; variance unknown. Remaining types (test-diagnosis,
repeat-error recovery, architecture) in G10.

### G5 — Safety semantics honest: **PASS**
- AUDIT documented as observability, never as protection (README, SECURITY,
  CLAUDE.md, hook docstrings).
- ENFORCE fail-closed on corrupt config (contract).
- `--print` does not execute hooks — documented in README/SECURITY/
  harness-core README (verified 2026-10).

### G6 — No fake anything: **PASS**
- No fabricated users/stars/performance. The 2.33× regression is printed in
  README, README.zh-CN, CHANGELOG, and this file. ECC attribution in NOTICE.

### G7 — ECC provenance: **PASS (local) / PENDING (remote re-verify)**
- Pin `928076cc` (v2.0.0-rc.1, 2026-05-25) with MIT license bundled; rationale
  in NOTICE.
- **Locally verified 2026-10-13**: `tools/check_ecc_provenance.py --upstream
  <path-to-local-ecc-clone>` — pin commit exists in the clone
  (`git cat-file -t` = commit), and all 71 paired files are SHA-256-identical
  to the bundled snapshot. 3 self-developed skills confirmed not from ECC.
  Snapshot matches `vendor/ecc/MANIFEST.sha256` (74 files) — 3 contracts.
- **Remote re-verification still pending** (network blocked at maintainer
  site): `git ls-remote https://github.com/affaan-m/everything-claude-code`
  + re-run with a fresh clone. Recorded as a v1.0 blocker, not silently
  skipped. No unilateral ECC upgrade will happen; bumping the pin requires
  re-recording the manifest and re-running all contracts.

---

## Beta gates (beyond Public Preview)

### G8 — Interactive gate verification: **PENDING (human-only steps)**
- Subprocess-level: enforce-blocks (exit 2) and audit-passes are
  contract-proven (26 harness-core contracts).
- Interactive 5-state checklist (DISABLED / AUDIT / ENFORCE-blocks /
  ENFORCE-allows-approved / ENFORCE-fail-closed) prepared in
  `docs/INTERACTIVE_ACCEPTANCE.md` — requires the user's first trusted launch.
  Not claimed until executed.

### G9 — Cross-project rule isolation: **PASS (probe)**
- Real-session probe 2026-10-13 (single session, two `--add-dir` projects with
  **contradicting** CLAUDE.md rules, $0.113, 0 denials): proj-a output carried
  `# PROJ-A` + snake_case; proj-b carried `# PROJ-B` + camelCase, and the
  model's commit message for proj-b started `[PROJ-B]` — the project rule
  **overrode** the globally-installed conventional-commits pack. Zero
  cross-talk; zero global bleed. Reproducible via `bench/iso/` probe dirs in
  the development repo (see `docs/demos.md` Demo 1).
- Mechanism basis: process-env `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1`
  + `--add-dir` auto-loads target CLAUDE.md; `claudeMdExcludes` exempts global
  rule packs; project-settings env block does NOT work — encoded in the
  launcher.

### G10 — Five-task-type cost matrix: **IN PROGRESS**
Runner `bench/run_arm.py` + transcript forensics `bench/analyze_transcript.py`
(both in the development repo) produce per-arm cost / turns / denials /
Task / Skill / harness-CLI counts.

| task type | arms | result (2026-10-13) |
|---|---|---|
| trivial prompt (FAST tier) | baseline vs vnext | $0.0228 vs $0.0199 (0.87×), 2 turns each, 0 agent/skill/oracle calls both |
| bugfix T3+T4 | baseline vs vnext | $0.444 vs $0.540 (1.22×), both PASS, 0 oracle calls both |
| multi-file feature | baseline vs vnext | $0.587 vs $0.491 (0.84×), 4/4 selfchecks PASS both, 0 oracle calls both |
| repeat-error recovery | oracle-seeded vs control | running — see final Phase 5 report |
| test-diagnosis | — | staged (arms arm-g2/arm-g2b prepared) |
| architecture (DEEP tier) | — | PENDING (budget check first) |

Negative finding that reshaped the product on 2026-10-13: the seeded-history
arm (r2) never queried the oracle (hCLI=0) because the task bundle's ISSUES.md
handed the model the root causes — it fixed proactively and never hit a
failure. The "query on 2nd occurrence" policy was unfireable in a single
session (the model cannot know an error is a repeat without querying first).
Policy corrected to **fail-triggered**: query before debugging/retrying an
actual failure, never by default on a fresh task. The r3/r3c pair measures
the corrected policy.

---

## v1.0 gates (require real users)

- External users install, use, and report (none yet — nothing fabricated).
- ECC pin re-verified against upstream.
- Interactive gates G8/G9 executed and recorded.
- Cost matrix G10 filled; residual bugfix gap closed or explained.

---

## Interactive evidence log

| date | step | result | notes |
|---|---|---|---|
| 2026-10-13 | G1–G6 (automated) | PASS | this document written from live runs |
| 2026-10-13 | G7 local re-verify | PASS (local) | 71/71 files hash-identical to pinned clone; remote re-verify pending (network) |
| 2026-10-13 | G9 isolation probe | PASS (probe) | contradictory rules, zero cross-talk, $0.113 |
| 2026-10-13 | oracle policy fix | fail-triggered | r2 showed "2nd occurrence" unfireable; r3/r3c measuring the fix |
| — | G8 interactive | PENDING | awaiting user's first trusted launch |
