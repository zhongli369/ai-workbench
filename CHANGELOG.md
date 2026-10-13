# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
