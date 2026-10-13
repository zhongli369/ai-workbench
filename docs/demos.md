# Core Demos — reproducible, offline-verifiable

Every demo below was executed on the reference machine with real Claude Code
sessions; commands, expected outputs, and acceptance checks are included so
you can re-run them. Model output varies run to run — the **acceptance
criteria** are deterministic, the prose is not.

Costs are from `--output-format json` usage blocks, reference machine
(Windows 11, CC 2.1.x, 2026-10-13).

---

## Demo 1 — One workspace, multiple projects (with conflicting rules)

**The claim.** Launch one workbench; operate on two projects whose rules
contradict each other — each project's own CLAUDE.md wins in its own tree,
and neither global rule packs nor the other project bleed across.

**The setup.** Two probe projects (`bench/iso/` in the dev repo):

```
proj-a/CLAUDE.md → files start with `# PROJ-A`, functions snake_case
proj-b/CLAUDE.md → files start with `# PROJ-B`, functions camelCase,
                   commit messages start with `[PROJ-B]` (NOT `feat:`)
```

**The command** (from the installed workbench, one session):

```
Add both projects (--add-dir proj-a --add-dir proj-b), then ask:
"create f1.py in each with a sum function, following each project's own
rules; and write the commit message you would use for proj-b."
```

**Measured result** (real run, $0.113, 0 permission denials):

```python
# proj-a/f1.py            # proj-b/f1.py
# PROJ-A                  # PROJ-B
def add_two_numbers...    def addTwoNumbers...
```

and the model's chosen commit message: `[PROJ-B] add f1.py with addTwoNumbers sum helper`

- `# PROJ-A` + snake_case in A's tree, `# PROJ-B` + camelCase in B's — **zero cross-talk**.
- `[PROJ-B]` beats the globally-installed conventional-commits rule → the
  workbench's `claudeMdExcludes` exemption works; project rules win.

**Acceptance:** inspect the two files + the commit message. Deterministic.

**Recording script (30 s):** launch → show the two CLAUDE.md files → one
prompt → open both f1.py side by side → show the commit message line.

---

## Demo 2 — A failure recorded in session A is reused in session B

**The claim.** A verified lesson recorded in one session (local JSONL, no
network) surfaces in a *later, separate* session when the same error class
appears — and the second session doesn't pay the debugging cost again.

**Why it's honest.** The oracle is consulted **when a failure is actually
encountered** (before debugging/retrying) or on explicit request — never by
default on fresh tasks (measured: default-oracle doubles
cost on fresh single-defect work with zero quality gain; that negative
result is why the policy exists).

**The setup.** `examples/noter` has two seeded defects whose root causes are
structural (write-back boundary `_MEM` vs disk, stale `_LIST_CACHE`).
Session A's lessons are pre-recorded as `human-verified` records:

```bash
python harness-core/harness/cli.py feedback record --project-id noter-demo \
  --cause stale_cache \
  --summary "add/edit 后 list 看似没生效 — list 走 _LIST_CACHE, 写操作后必须失效缓存" \
  --source human-verified --confidence 1.0
```

**The commands.**

```bash
# session A (already happened — the record above is its artifact)
# session B (new, clean session): same error class appears →
python harness-core/harness/cli.py feedback query --project-id noter-demo \
  --keyword cache --json
# → the stale_cache record + mitigation surfaces BEFORE re-debugging
```

**Measured result** (feature-implementation A/B, real runs):

| arm | failure history available | result |
|---|---|---|
| baseline (native CC) | none (native CC has no such store) | see docs/PERF.md |
| vnext, no seeded history | none for this project | see docs/PERF.md |
| vnext, seeded history | the two records above | see docs/PERF.md |

(Numbers land in `docs/PERF.md` as the runs complete — we do not pre-print
expected wins.)

**Acceptance:** the query output contains the seeded record ids; the session
transcript shows the query preceding the fix. Project isolation: query with
a *different* `--project-id` returns nothing.

**Recording script (45 s):** terminal split — left: session A recording;
right: fresh session hitting the same class, querying, applying, selfcheck
PASS; close-up on the JSONL file proving persistence.

---

## Demo 3 — Multi-file feature, capabilities on demand

**The claim.** A real multi-file feature (two new subcommands with
acceptance tests) completes in the workbench with its cost policy holding:
no agent swarm for a STANDARD task, skills load only if needed.

**The command:**

```
"noter needs search <kw> (substring match) and edit <id> <new text>
(error on unknown id). selfcheck --task search and --task edit must PASS;
durability/cache must not regress."
```

**Measured result:** see `docs/PERF.md` (baseline vs vnext, same prompt,
same model, same permissions).

**Acceptance:** `python selfcheck.py --task search|edit|durability|cache`
on the produced tree. Deterministic.

**Recording script (30 s):** prompt → watch the edit sequence → four
selfcheck lines green → cost footer from the usage JSON.

---

## What we deliberately do NOT demo

- "N agents collaborating" theater — when one agent is the right call, the
  policy says so and the demo shows that instead.
- Deterministic transcripts — model prose varies; acceptance checks don't.
- Any number we haven't measured on the current build.
