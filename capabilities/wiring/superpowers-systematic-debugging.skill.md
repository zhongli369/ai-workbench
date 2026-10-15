---
name: aiwb-superpowers-systematic-debugging
description: Root-cause-first debugging for non-obvious failures — reproduce, gather evidence at component boundaries, test one hypothesis at a time, fix the cause rather than the symptom, and stop after three failed fixes to question the design. Use when a failure is unexplained, has survived one or more fix attempts, or spans components. Skip the ceremony for trivial, obvious fixes — just fix those.
---

# Systematic debugging (root-cause-first)

Ported and condensed from **superpowers** — https://github.com/obra/superpowers
Pinned at commit `bb92a77741419a4ab5f06e711a283343f1ada0c3` (2026-10-15).
Original author: Jesse Vincent. MIT License, Copyright (c) 2025 Jesse Vincent.

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

AI Workbench adaptation: the upstream skill was a mandatory, phase-gated
workflow. This port keeps the investigation discipline and drops the
forced-process language, the upstream SessionStart injection, and the
cross-references to other superpowers-only skills.

## When to use / when not to

Use the full four phases when:
- the failure is unexplained, order-dependent, flaky, or spans components;
- a first fix did not work (or a "quick fix" made things worse);
- the error points at one layer but the data may come from another;
- you catch yourself about to say "let me just try changing X".

Do NOT run the ceremony when:
- the fix is trivial and the cause is obvious from the error (typo, missing
  import, off-by-one in code you just wrote) — fix it, run the test, move on;
- you are exploring/prototyping, not repairing a reported failure.

The cheap invariant that always applies: read the actual error text before
changing anything, and know why the change should work.

## Phase 1 — Root cause investigation (before any fix)

1. **Read the error completely.** Stack trace, line numbers, paths, error
   codes. Errors usually name the culprit layer; do not skim past them.
2. **Reproduce consistently.** Record the exact command/steps. Does it fail
   every time? In isolation? Only in a full suite, or only at certain times?
   Order dependence and isolation-vs-suite differences are evidence — note
   them, do not explain them away.
3. **Check recent changes.** Diff, recent commits, new dependencies, config
   or environment drift. "It worked before X" points at X.
4. **Gather evidence at component boundaries** (multi-component systems).
   Instrument each boundary once: log what enters and what exits, verify
   config/env propagation, check state at each layer. Run once to see WHERE
   it breaks, then investigate that component — do not guess from the outside.
5. **Trace the bad value backward.** Find where the wrong value or state
   originates, who called with it, and keep walking up the call chain until
   you reach the source. Fix at the source, not where it exploded.

## Phase 2 — Pattern analysis

1. Find a working example of the same pattern in this codebase.
2. Compare working vs broken and list every difference, however small.
3. Read reference implementations completely if you are following one —
   partial understanding guarantees bugs.
4. Understand the dependencies and assumptions the failing path relies on.

## Phase 3 — Hypothesis and minimal test

1. State one hypothesis in one sentence: "X is the root cause because Y."
2. Test it with the smallest possible experiment — one variable at a time.
3. Confirmed → Phase 4. Not confirmed → form a NEW hypothesis; do not stack
   more fixes on top of the unverified one.
4. If you do not understand something, say so and investigate; do not bluff.

## Phase 4 — Fix

1. **Add a failing regression test first** (cheapest reproduction you have —
   a test, or a one-off script if there is no framework). Watch it fail for
   the right reason. Keep test-first discipline if a TDD skill is in play.
2. **One fix at a time.** No "while I'm here" improvements, no bundled
   refactoring — they destroy your ability to attribute the outcome.
3. **Verify**: the failing reproducer now passes, the suite is still green,
   and the original symptom is gone for the original reason.
4. **If the fix did not work:** stop, count attempts, return to Phase 1 with
   the new information. When three fixes have failed, stop fixing — the
   pattern of "each fix reveals a new problem in a different place" means the
   architecture, not the hypothesis, is wrong. Discuss the design before
   attempt four.

## Red flags — stop and go back to Phase 1

- "Quick fix now, investigate later."
- "Probably X — let me just change it and see."
- Multiple unrelated changes in one attempt.
- Skip the reproducer; "I'll verify manually."
- Proposing solutions without having traced where the bad value entered.
- One more attempt when two already failed.

## Supporting techniques (summaries)

- **Backward tracing:** from the failure site, walk callers upward logging the
  value at each hop until you find the first place it is already wrong. The
  step before that is the origin.
- **Condition-based waiting:** never sleep for an arbitrary duration; poll for
  the condition you actually need, with a bound and a clear timeout error.
- **Defense in depth:** after finding the root cause, decide deliberately where
  validation belongs (source, boundary, consumer). Do not scatter redundant
  checks as a substitute for fixing the cause.

## Honest exit

If investigation shows the cause truly is environmental, timing-dependent, or
external, that is a finding — document what was ruled out and handle it
(retry, timeout, clearer error, monitoring). But treat "no root cause" as
suspect until the investigation was actually complete.
