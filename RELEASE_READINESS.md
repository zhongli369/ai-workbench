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
- 37/37 (11 clean-room + 26 harness-core) in 5 s, stdlib + pytest only, no
  network, no Claude Code, no model login.

### G4 — Honest performance story: **PASS (with disclosed residual gap)**
Measured (same machine, same model, `--output-format json`):

| Benchmark | baseline (native CC) | vnext | ratio |
|---|---|---|---|
| Resident context (structural, `workbench benchmark`) | ≈20.7k chars global rule layer | L0 ≈1.7k; L0+skill index ≈9.0k chars | **−57%** (L0 alone −92%) |
| Fixed trivial prompt (N=1 each) | $0.0228 | $0.0199 | 0.87× |
| Bugfix task T3+T4, first A/B (2026-10-13, kept as negative history) | $0.569 / 16 turns | $1.335 / 44 turns | **2.33×** |
| Bugfix task T3+T4, rerun after permission+policy fix | $0.444 (1 denial) | $0.540 (3 denials) | **1.22×** |

Rerun analysis: both arms PASS selfcheck; **zero oracle queries, zero skill
loads in both arms** (FAST policy held). vnext non-cached input was 62% LOWER
(16.9k vs 44.8k tokens); the residual gap comes from more turns/output in the
task path (cache_read 650k vs 335k, output 5.2k vs 2.1k), not from resident
context. Optimization target "≈ or below baseline on ordinary tasks" is **not
yet met** — tracked as the first post-RC item. N=1 per arm; variance unknown.
Five-task-type matrix (multi-file, test-diagnosis, repeat-error, architecture)
**PENDING** — only the bugfix type has controlled data.

### G5 — Safety semantics honest: **PASS**
- AUDIT documented as observability, never as protection (README, SECURITY,
  CLAUDE.md, hook docstrings).
- ENFORCE fail-closed on corrupt config (contract).
- `--print` does not execute hooks — documented in README/SECURITY/
  harness-core README (verified 2026-10).

### G6 — No fake anything: **PASS**
- No fabricated users/stars/performance. The 2.33× regression is printed in
  README, README.zh-CN, CHANGELOG, and this file. ECC attribution in NOTICE.

### G7 — ECC provenance: **PENDING (documented risk)**
- Pin `928076cc` (v2.0.0-rc.1, 2026-05-25) with MIT license bundled; rationale
  in NOTICE. **Could not re-verify against upstream at RC time** (network
  blocked at maintainer site). Must be re-checked before v1.0.

---

## Beta gates (beyond Public Preview)

### G8 — Interactive gate verification: **PENDING (human-only steps)**
- Subprocess-level: enforce-blocks (exit 2) and audit-passes are
  contract-proven (26 harness-core contracts).
- Interactive 5-state checklist (DISABLED / AUDIT / ENFORCE-blocks /
  ENFORCE-allows-approved / ENFORCE-fail-closed) prepared in
  `docs/INTERACTIVE_ACCEPTANCE.md` — requires the user's first trusted launch.
  Not claimed until executed.

### G9 — Cross-project rule isolation, interactive: **PENDING**
- Mechanism verified via probe sessions (process-env
  `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1` + `--add-dir` auto-loads
  target CLAUDE.md; project-settings env block does NOT work — encoded in the
  launcher). Interactive confirmation pending (same checklist).

### G10 — Five-task-type cost matrix: **PENDING**
- Only bugfix has controlled A/B data (G4). The runner
  (`bench/run_arm.py` in the development repo) is reusable; matrix execution
  is post-RC.

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
| — | G8/G9 interactive | PENDING | awaiting user's first trusted launch |
