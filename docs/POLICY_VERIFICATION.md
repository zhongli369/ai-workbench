# FAST / STANDARD / DEEP — what is actually verified (2026-10-13)

The three tiers are a **prompt-level policy with transcript-auditable
behavior**, not a runtime enforcement mechanism. This document separates
what is *structurally guaranteed* from what is *measured behavior*, and
lists what remains unproven. Evidence: `bench/analyze_transcript.py` run
over the real session transcripts of every controlled arm.

## Structurally guaranteed (not dependent on model compliance)

1. **Failure history is NOT in resident context.** The oracle is reachable
   only via an explicit harness CLI call — so "FAST never pays for the
   oracle" costs nothing to honor, and any violation leaves a CLI trace in
   the transcript (`harness_calls` counter).
2. **Skill bodies are NOT in resident context** — only the index. Loading a
   skill requires an explicit `Skill` tool call (counted per arm).
3. **Telemetry costs zero model turns** — recorded by the CLI itself.
4. Resident sizes: L0 ≈1.7k chars; L0+skill index ≈9.0k vs ≈20.7k global
   rule layer (−57%, L0 alone −92%). `workbench benchmark` output.

## Measured behavior (transcript forensics, N=1 per cell)

| arm (task, tier) | turns | Task | Skill | oracle CLI | cost |
|---|---|---|---|---|---|
| baseline trivial (FAST) | 2 | 0 | 0 | 0 | $0.0228 |
| vnext trivial (FAST) | 2 | 0 | 0 | 0 | $0.0199 |
| baseline bugfix (STANDARD) | 18 | 0 | 0 | 0 | $0.4436 |
| vnext bugfix (STANDARD) | 39 | 0 | 0 | 0 | $0.5396 |
| baseline feature (STANDARD) | 25 | 0 | 0 | 0 | $0.5874 |
| vnext feature (STANDARD) | 29 | 0 | 0 | 0 | $0.4912 |
| vnext recovery r4b, oracle seeded (STANDARD) | 39 | 0 | 0 | **0 (never queried)** | $0.796 |
| vnext recovery r3c, control empty store (STANDARD) | 66 | 0 | 0 | 0 (nothing to find) | $1.144 |

Recovery-pair caveat: the noter bundle's `notes.py` docstring names both
root causes, so skipping the query was correct policy execution; r4b's lower
cost is N=1 variance with the treatment unused — not oracle benefit. Full
analysis in the development repo `bench/R3R4_RECOVERY_REPORT.md`.

**Negative evidence, kept:** the invalidated first A/B (2026-10-13, before
the policy fix) ran a small task with **5 oracle calls + 1 skill load**
($1.335, 2.33×). That waste is exactly what the "never query by default on
fresh tasks" policy now forbids — and the fix is visible in the rerun
(zero oracle calls).

## What the measurements say, tier by tier

- **FAST** "no agents, no oracle, no bookkeeping": **verified** in the
  trivial-prompt arms (0/0/0) and auditable in principle for any run.
- **STANDARD** "skills on demand": both STANDARD task types completed 4/4
  acceptance checks with **zero** skill loads — the model judged them
  unnecessary. "On demand" means *permitted*, not *forced*; the load-branch
  is therefore **unproven** (no run needed it).
- **STANDARD** "fail-triggered oracle": policy corrected 2026-10-13 after
  the r2 arm showed "query on 2nd occurrence" can never fire in one
  session. The r3c/r4b controlled pair then measured the corrected trigger:
  **zero spurious queries when the root cause is code-visible** (the oracle
  behaved as a free option), and zero missed opportunities observable in the
  control. A scenario where querying is *forced* to pay off (root cause
  outside the readable repo) has not been run — the load-branch of the
  oracle, like the skill load-branch, is **unproven in-vivo**.
- **DEEP** "planner first, reviewer after": **no measured sample**.
  Requires an architecture-class task (G10); claimed nowhere until then.
- **Tier cost separation** is task-driven, not mechanism-driven: FAST-class
  runs land at ~$0.02, STANDARD-class at ~$0.5–0.8 on this reference
  machine. The tiers steer behavior; they do not cap spend.

## Honest bottom line

The tier system is a policy the model follows with auditable side-effects,
backed by structural properties that make the expensive paths opt-in. It is
**not** a runtime governor. Claims are scoped exactly to the cells above;
empty cells are PENDING, not assumed.

## Addendum 2026-10-13 — Claude Code env precedence (measured, cost us one invalid arm)

When a session is launched with `--settings FILE` from a cwd that also has
`.claude/settings.json`, the **project-level `env` block is applied to tool
subprocesses and overrides the launching process's own env** for the same
keys. `--settings` content outranks the project file. Measured with an
in-session probe (`python -c "import os; print(os.environ[...])"`, $0.044):

- `HARNESS_DATA_DIR` injected via `subprocess env=` → **lost** to the project
  settings env block (`workbench-vnext/harness-data`).
- Same key injected via a generated `--settings` file → **won**
  (`_bench-data/r3`, probe-verified).
- `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD` is read by CC at startup —
  settings env is too late for it; it must stay a real process env var.

Rule of thumb: **CC-startup vars → process env; tool-subprocess vars →
settings file.** The r3 arm's oracle queries all missed because of this
(store pinned to the workbench's own empty-for-that-project dir); the arm is
kept as negative evidence and the measurement rerun as r4.
