# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0-preview.1] — 2026-10-14

First **Public Preview**. Everything from 0.1.0-rc.1 plus the FUSION OMEGA
milestones M3–M5 below. 151 offline contracts, hygiene / ECC-provenance /
compile gates all green on the release commit.

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
