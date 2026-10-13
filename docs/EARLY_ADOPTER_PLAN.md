# Early Adopter Plan — first 10 users

Star count is **not** the success metric. The metric: can a stranger install,
understand, use, and feel the added value — and would they come back?

## Who

Recruit 10 developers, aiming for overlap with at least two of:

- heavy Claude Code users (daily, multi-week)
- maintainers of 2+ active repositories
- developers who repeatedly debug similar issues across sessions
- engineers interested in AI-agent reliability (not just novelty)

Recruitment channels: direct outreach, Claude Code community spaces, ECC
issue/PR participants. No astroturfing, no fabricated testimonials — every
quote in future marketing must trace to a named, consenting tester.

## What they do (≈45 min, self-guided)

| step | task | measures |
|---|---|---|
| 1 | Install from a fresh clone | install success, time, doctor output |
| 2 | Launch + accept trust themselves | trust step clarity |
| 3 | Point the workbench at THEIR repo, run a real small task | time-to-first-success |
| 4 | Run the noter demo (session A: record a failure) | comprehension of the memory concept |
| 5 | New session, same error class (session B: reuse) | did the oracle surface it, was it useful |
| 6 | Optional: switch gate to ENFORCE, attempt `git push` | gate comprehension |
| 7 | Uninstall (or keep) | uninstall cleanliness, data preserved |

## What we collect

Per tester, one filled `FEEDBACK_FORM.md` (this directory):

- install: success? time? errors? (paste doctor output)
- time from clone to first successful task on their own repo
- did they understand the core value without explanation? (yes / needed the docs / no)
- did session B reuse session A's lesson? (yes, found it / found it but useless / no)
- any hook/rule conflicts with their existing setup (ECC, RTK, other hooks)?
- would they use it next week? (yes / maybe / no)
- would they recommend it? (yes / maybe / no)
- one thing to delete, one thing to add

## Success thresholds (pre-registered, not moved after data arrives)

| metric | Public Preview stays | → Beta | → v1.0 |
|---|---|---|---|
| install success | ≥7/10 | ≥9/10 | ≥9/10 + CI clean on their platforms |
| first task success < 15 min | ≥5/10 | ≥7/10 | ≥8/10 |
| understood value unaided | ≥5/10 | ≥7/10 | ≥8/10 |
| session-B reuse rated useful | ≥4/10 | ≥6/10 | ≥7/10 |
| "would use next week" | ≥5/10 | ≥7/10 | ≥8/10 |
| blocking hook/rule conflicts | 0 unresolved | 0 | 0 |

Missing a threshold is a **fix-and-retest** signal, not a marketing problem.

## Feedback handling

- Forms go into the repo tracker as labeled issues (`early-adopter`).
- Recurring (≥2 testers) complaints become the top of the backlog — ahead of
  any new feature work.
- A public `docs/EARLY_ADOPTER_RESULTS.md` summarizes outcomes, including the
  unfavorable ones, before any version-number promotion.
