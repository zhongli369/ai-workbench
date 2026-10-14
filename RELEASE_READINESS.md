# RELEASE READINESS — 0.1.0-preview.1

> **RELEASE CANDIDATE FREEZE — 2026-10-14, OPERATION SHIP IT.**
> The publishable set is frozen at the `fusion` HEAD. From this point only
> release-blocking defects may be fixed; no new features, agents, benchmark
> tasks, or architecture. Frozen surface: CLI (`workbench.py` 7 commands),
> install/uninstall/doctor, PreToolUse gate hook, 30 skills + 16 agents +
> 14 commands (ECC pinned), harness-core (feedback/gate/report/telemetry),
> capability registry, docs-drift / public-surface / hygiene / ECC-provenance
> gates, one-time approval tokens, README EN/ZH, LICENSE, NOTICE, CHANGELOG —
> 216 git-tracked files, 174 contracts green.

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
| Repeat-error recovery, oracle seeded vs control (r4b vs r3c) | $1.144 / 66 turns (0 queries) | $0.796 / 39 turns (**0 queries — seeds never read**) | not attributable — see G10 |

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

## Post-RC hardening gates (legacy power-up, P1)

### P1.1 — Docs drift gate: **PASS**
`tools/check_docs_drift.py` + `docs/claims.json`: release claims are structured
data verified against live sources (pytest collection, ECC payload counts,
VERSION constant); performance figures must carry their qualifier (N=1 /
controlled / model-independent) in the same paragraph block. Caught real drift
before and after its own introduction (count bumps on every P1 commit).
21 contracts; wired into the static CI job.

### P1.2 — Frozen public surface: **PASS**
`tools/check_public_surface.py` + `docs/surface.json`: explicit manifest of the
committed CLI commands/flags, 7 JSONL schemas and settings keys. Additive
changes are free; removal/retype/choice-shrink is BREAKING and requires
`--accept-new --bump major` + rationale. Self-dogfooded on the P1.5 telemetry
schema addition (detected exactly 1 additive field, accepted as minor).
15 contracts; wired into the static CI job.

### P1.3 — One-time approval tokens: **PASS**
`gate approve --once --action <cmd>` issues `awt-<48hex>` (SHA-256 stored,
TTL-bound, scope = exact command or regex fullmatch). Atomic consumption under
a store lock (8-thread race: exactly 1 succeeds); replay / expiry / scope
mismatch are distinct denials and mismatch does not consume; AUDIT mode never
consults tokens; the raw token never reaches the audit log (12-char hash
prefix only). 17 contracts.

### P1.4 — Incident replay contracts: **PASS**
`docs/incidents/registry.json` + `tests/test_incident_replay.py`: four named
historical failures (permission probing, verify-wrong-root, `__pycache__`
provenance pollution, user-path leakage) locked as permanent regression tests;
the bench SDK driver hashes each task's verifier pre/post run and voids
tampered results. Proved live twice: incident C caught test-inflicted cache
pollution during its own development; incident D caught the incident test file
itself entering the publish set post-commit. 13 contracts.

### P1.5 — Telemetry self-exclusion: **PASS**
Reader commands (`telemetry`, `feedback stats`, `report`, `gate check`) are
never logged (enforced in `log()` AND in CLI dispatch); every row carries a
source label (`cli` / `bench` via `HARNESS_BENCH=1` / `synthetic`); all three
bench runners label their traffic; `summarize()` is a pure read whose adoption
view counts only `cli` rows — bench/synthetic traffic can never masquerade as
product usage. 9 contracts.

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

### G10 — Five-task-type cost matrix: **MEASURED — results mixed, all disclosed (architecture cell PENDING budget)**
Runner `bench/run_arm.py` + transcript forensics `bench/analyze_transcript.py`
(both in the development repo) produce per-arm cost / turns / denials /
Task / Skill / harness-CLI counts.

| task type | arms | result (2026-10-13) |
|---|---|---|
| trivial prompt (FAST tier) | baseline vs vnext | $0.0228 vs $0.0199 (0.87×), 2 turns each, 0 agent/skill/oracle calls both |
| bugfix T3+T4 | baseline vs vnext | $0.444 vs $0.540 (1.22×), both PASS, 0 oracle calls both |
| multi-file feature | baseline vs vnext | $0.587 vs $0.491 (0.84×), 4/4 selfchecks PASS both, 0 oracle calls both |
| repeat-error recovery | r4b (2 seeds) vs r3c (empty) | $0.796/39 turns vs $1.144/66 — **oracle arm made 0 queries**; difference is N=1 variance, NOT oracle benefit. Both arms 4/4 PASS. |
| env-class recovery (E4) | e4o (1 seed) vs e4c (empty) | $0.307/25 turns (0 den) vs $0.565/32 turns (1 den) — **oracle arm again 0 queries** (seed `fb-3c39129847bd` never read; control queried the empty store 3×). Both arms PASS/PASS builder re-verified. Full report: dev repo `bench/E4_ENVRECOVERY_REPORT.md`. |
| test-diagnosis | g2 (vnext) vs g2b (baseline) | $0.754/48 turns (1 den, Skill×2, hCLI×4) vs $0.417/23 turns (0/0/0) — **1.81×**: fail-triggered policy on an EMPTY store costs ~$0.34 (2 skill loads + 2 queries + bookkeeping). Both arms cache+durability PASS. Offset observation: g2 organically RECORDED its diagnosis back (`model-inference`, correct cause) — first in-vivo capture-loop write. |
| architecture (DEEP tier) | — | PENDING (budget check first) |

**Benchmark batch 2 (2026-10-14, claude-haiku-4-5, 8/8 runs PASS, $0.355 this
batch — cumulative ledger $0.822 of the $3.00 cap, N=1 per cell,
exploratory).** Three-arm matrix (native / ecc-only / fusion) plus the
experience-reuse pair and the stuck-recovery task:

| task | native | ecc-only | fusion |
|---|---|---|---|
| t1 fast rename (FAST) | $0.0847 / 10t | $0.0561 / 8t | $0.0722 / 8t |
| t2 failing test (STANDARD) | $0.0701 / 9t | $0.0457 / 6t | $0.0488 / 7t |
| t4 multi-file feature | $0.1167 / 16t | $0.0449 / 8t | $0.0747 / 11t |
| t5 stale build (stuck recovery) | $0.0603 / 4t | — | $0.0218 / 4t |
| t3b legacy-state variant | $0.0509 / 7t (control) | — | $0.0230 / 5t (seeded store, **0 oracle queries**) |

Batch-2 verdicts (all N=1, differences within haiku run variance):
- **ECC-only vs fusion vs native**: ordering native > fusion ≥ ecc is
  directionally consistent across t1/t2/t4, but no difference is statistically
  established. The fusion harness layer adds ≈$0.00–0.03/run on small tasks —
  the "no large fusion tax" reading from batch 1 survives a third arm.
- **Zero capability invocations across all 8 runs**: no Skill call, no harness
  CLI call, no oracle query. On green-run small tasks the agent never needs
  the machinery — the harness is a free option that only activates on failure.
- **Experience reuse (t3 pair)**: treatment solved the variant cheaper
  ($0.0230 vs $0.0509) and in fewer turns (5 vs 7) with the seeded store
  present, but made **0 oracle queries** — the benefit is NOT attributable to
  the oracle (the fail-triggered policy correctly never fired: the agent never
  failed). This is the third independent seeded arm with 0 queries
  (r4b, e4o, t3b) — a robust pattern: on tasks agents solve without failing,
  the oracle cannot show benefit by design. Synthetic seeds prove the
  mechanism, not the payoff.
- **Stuck recovery (t5)**: both arms escaped the stale-build trap in 4 turns;
  fusion was cheaper (N=1, not significant). No rework differential measurable
  at this task size.
- Verifier integrity: `verify_sha256` identical pre/post on every run,
  `verify_tampered=false` throughout.

**Recovery-type verdict (r3/r3c/r4/r4b, full report in the development repo
`bench/R3R4_RECOVERY_REPORT.md`):** the scenario cannot measure oracle value,
because the noter task bundle documents both root causes in `notes.py`'s own
docstring — reading the code answers everything, so the fail-triggered policy
correctly produces zero queries. Secondary findings that DO survive:
(a) the policy makes the oracle a free option — no spurious queries when the
root cause is code-visible (the 2.33× waste class stays closed);
(b) the isolated-store infrastructure works end-to-end — r3's query misses
were root-caused to the CC settings-env precedence bug, fixed in the runner,
and probe-verified.

**E4 verdict (env-class scenario purpose-built to force the oracle):** root
cause moved into DATA state (`"text": null` record in a shuffled 60-line
JSONL, crash in the CLI formatter, no code/docstring hints). Result:
**honest-null again** — the seeded arm self-diagnosed for $0.307 without a
single query, independently choosing the seed's recommended fix, while the
control queried its empty store 3× before self-diagnosing for $0.565.
Meta-finding across all three seeded arms (r3/r4b/e4o): **a model-issued
query that hits a reachable seed has never been observed.** The advisory
policy permits queries; the model takes them only when uncertain, and on
small self-contained repos it is confident enough to read code+data. The
oracle's necessary domain narrows to root causes not readable anywhere in
the project (service/env/world-knowledge class). Evidence-based v1.1
proposal recorded: a hook-time nudge on failing verification commands
("query history once before debugging") — structural salience, budgeted
against the 2.33× lesson; NOT built.

Negative finding that reshaped the product on 2026-10-13: the seeded-history
arm (r2) never queried the oracle (hCLI=0) because the task bundle's ISSUES.md
handed the model the root causes — it fixed proactively and never hit a
failure. The "query on 2nd occurrence" policy was unfireable in a single
session (the model cannot know an error is a repeat without querying first).
Policy corrected to **fail-triggered**: query before debugging/retrying an
actual failure, never by default on a fresh task. The r3/r3c pair measures
the corrected policy.

---

## PHASE P — discriminative task battery (2026-10-14)

Directed by the Phase-P mandate (ship, prove, evolve): end the oracle value
dispute with tasks whose root cause is NOT readable from the project, and
prove complex-engineering value on deep/long-horizon tasks. All N=1 results
are exploratory; the $3.00 shared ledger governs every run.

| task | class | layer status |
|---|---|---|
| t6-external-config-drift | real-world failure recovery (root cause in EXTERNAL state: stale deploy config vs endpoint registry) | **MEASURED 2026-10-14** (t6.1, all four arms PASS): native $0.0892/15t · ecc $0.0774/6t · fusion-empty $0.0726/12t · fusion-seeded $0.0452/7t; **0 oracle queries on every arm** — fourth independent seeded arm with no reads. §1.3 verdict: honest-null class (the diagnostic path is fully workspace-readable, so direct read-then-fix is correct; zero queries ≠ harness failure). Seeded arm's −$0.027/−5t is NOT attributable (treatment never read). Two earlier voided runs root-caused to a task/tooling defect (foreground serve-forever blocks the SDK Bash call) — fixed by t6.1's self-terminating verify command; zero double-billing |
| t7-validator-drift-refactor | deep multi-file refactor (two drifted validator copies, spec.md is authoritative, public API + CLI frozen, hash-pinned shipped suite) | **MEASURED 2026-10-14** (batch 4, all three arms PASS, verify hashes untampered): native $0.1558/22t/105s · ecc $0.1235/18t/82s · fusion $0.1514/27t/75s. Every arm completed the dedup (shape-agnostic `__globals__` check), kept the frozen API/CLI, passed the hash-pinned suite and the port-0 CLI smoke. **Zero skill/oracle calls on every arm** — on a green-run refactor the fail-triggered policy correctly never fires; the harness stays a free option. Direction (N=1, EXPLORATORY, not generalizable): cost ecc < fusion < native; turns ecc < native < fusion (+5 turns fusion vs native for −$0.004, i.e. no measurable harness tax or benefit) |
| t8-log-pipeline-resume | long-horizon engineering (three-stage pipeline + PIPELINE_STATE.json checkpoint contract; TWO sequential fresh sessions per arm — session B must resume from workspace state, not memory) | **MEASURED 2026-10-14** (batch 5, $0.7992; t8.1 verifier fix + zero-cost re-verify on the frozen workspaces): **native PASS** $0.2961 (A 18t / B 21t) · **ecc PASS** $0.2713 (A 20t / B 16t) · **fusion FAIL** $0.2318 (A 9t / B 22t). **Two-session resume worked on all three arms** (redone_in_b all False — session B resumed from the checkpoint, never redid stages). Checkpoint honesty: native ✓ (recorded hashes byte-correct, uppercase certutil hex), ecc ✓ (hashes correct; JSON carried a PowerShell BOM), fusion ✗ (render hash corrupted to 30 chars — honest agent failure, still FAIL after the fix). The original all-FAIL verdict was root-caused to two verifier platform-tolerance defects (case-sensitive hex compare, strict utf-8 JSON) — fixed per directive §2.1 as a one-shot mechanism repair, locked by 8 new offline contracts (tests/test_t8_verify.py), original v1 verdicts preserved in batch5_t8.json. Zero oracle queries on every arm (the failure was silent — the agent never observed it, so fail-triggered could not fire). Session B consistently ≤ session A cost (resume saves work) |

**P4 oracle product decision (2026-10-14, final for this cycle): EXPERIMENTAL /
ON-DEMAND.** Evidence: four independent seeded arms (r4b, e4o, t3b, t6.1) with
zero real reads; every zero-query outcome is the honest-null class — the model
queries only when uncertain, and on self-contained workspaces it is confident
enough to read the evidence directly. The mechanism (layer-1 offline: ranking,
expiry, supersede, isolation, fast-negative, read-back honesty) is fully
contract-verified; the payoff (layer-3) has never been observed and cannot be
claimed. Per directive §2: with no real reads and no distinguishable causality,
EXPERIMENTAL / ON-DEMAND is maintained; no REMOVE (no measured cost harm —
fusion-empty ≈ native on t6.1) and no upgrade (no attributable benefit). The
§1.5 closable structural trigger remains an unbuilt proposal — building it is
not justified by the evidence: the model's no-query choice was correct every
time so far.

Anti-cheat properties enforced by contract on every task: verifiers judge
the fix CLASS not the shape; protected suites/inputs are sha256-pinned;
verify scripts are self-contained (incident-B class: no `__file__`
anchoring — t8 recomputes its golden values from the workspace's own
pinned input); agents get identical instruction and budget across arms;
the t6 seeded record names only the failure class and its generic
diagnostic path (ban-list contract in `tests/test_bench_infra.py`), so
the oracle can only ever be a shortcut, never the sole source of truth.

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
| 2026-10-13 | oracle policy fix | fail-triggered | r2 showed "2nd occurrence" unfireable; corrected policy measured below |
| 2026-10-13 | G10 recovery pair (r3c/r4b) | done, honest-null | oracle arm 0 queries (root causes code-visible); −30% cost = N=1 variance, not benefit; infrastructure fix (settings-env precedence) probe-verified |
| 2026-10-13 | G10 E4 pair (e4c/e4o) | done, honest-null | data-state root cause; seeded arm 0 queries again ($0.307 self-fix); control 3 queries on empty store; 3 seeded arms total, 0 retrieval hits ever observed |
| 2026-10-13 | G10 diagnosis pair (g2/g2b) | done, vnext 1.81× | policy overhead on empty store ≈$0.34 (Skill×2+queries); offset: g2 organically recorded correct diagnosis back (first in-vivo capture write) |
| — | G8 interactive | PENDING | awaiting user's first trusted launch |
