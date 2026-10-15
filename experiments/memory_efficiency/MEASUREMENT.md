# MEASUREMENT — Injected→Used Attribution for the Memory & Efficiency Lab

Three prototypes (D1 session-ranking, D2 per-turn gate, D3 caveman-voice A/B) were
built deterministically, stdlib-only, in `experiments/memory_efficiency/`. This file
specifies how their measured claims would be verified in-vivo, what evidence exists
today, and what remains `MODEL_VALIDATION_PENDING`.

Hermetic rule: no network, no package installs, no paid model calls this round. Every
`MODEL_VALIDATION_PENDING` marker below means "needs a real value, measured outside this
worktree, before the claim enters the product runtime."

---

## Context: why the oracle is UNPROVEN today

`harness-core/harness/feedback.py` writes feedback rows and ranks them, but across six
seeded experiments the registry marks in-vivo retrieval UNPROVEN: "recorded as injected"
(via `record_injected_ids`-style bookkeeping) is not "the model actually used it".
Attribution is the missing measurement. The three prototypes are falsification devices
against that gap — they do NOT add memory, they measure / probe the boundary.

---

## 1. D1 — Session-ranking precision (would the injected memory get used?)

### What the prototype proves deterministically
`session_rank.py`:
- `rank(entries, *, project_id, archetype=None, cap=6, min_confidence=0.0,
  char_budget=2200, store_path=None)` — deterministic multiplicative score
  `confidence × project-match(0|1.0) × archetype-match(0|1.0)`. Mismatch on project or
  archetype forces score 0 → entry excluded (hard relevance gates; precision-over-recall).
- `render_injection(ranked, *, char_budget=2200)` — `[archetype conf%] mitigation` lines,
  whole-entry drop from the bottom when over budget, never mid-entry truncation.
- Sanitization (strip control chars, cap length) + provenance (`record_id`, store path,
  sha256(16 hex) of the entry) per returned entry.

Test evidence: `python -m pytest experiments/ -q` → 27 passed (D1 tests include
cap-as-upper-bound, no-match→empty, determinism, budget boundary, tie-break, provenance
stability).

### In-vivo measurement (what would make it SHIPPED)
Design:
- **Event:** extend the existing SessionStart hook flow. On session start, before the
  context build, call `rank(...)` over the feedback store for `(project_id, archetype)`.
- **Telemetry field:** a new `oracle_inject` event (see wiring note at bottom) records
  `{"session_id", "n_injected", "ids": [record_id...], "scores": [...], "budget_used_chars"}`.
- **Success criterion:** over ≥30 real work sessions, measure how often an injected id is
  actually referenced by the model transcript in the same session (see §4 attribution
  method). Precision = referenced-and-injected / injected ≥ 0.5, and ≥1 session shows a
  non-empty injection reaching a real task. If no session ever triggers a non-trivial
  injection, D1 has ZERO demonstrated value → REJECTED regardless of code quality.

### What is NOT yet measured (MODEL_VALIDATION_PENDING)
- Whether rank order beats simple recency on real failure records (needs real store data;
  the worktree seeded only synthetic fixtures).
- The confidence calibration of `entry_confidence()` (success/(success+fail)) against the
  real failure distribution.

---

## 2. D2 — Per-turn retrieval gate (how many round-trips does it actually skip?)

### What the prototype proves deterministically
`turn_gate.py`:
- `is_trivial(prompt, *, explicit_query=False)` — anchored word list (yes/no/ok/thanks/
  hi/continue/done/lgtm/k...) + slash-command/empty → trivial; word-boundary anchored so
  "k8s"/"note"/"yolo" do NOT match; `explicit_query=True` always bypasses.
- `should_auto_retrieve(prompt, *, explicit_query=False)` — positive phrasing of the gate.
- `recall_metrics(injected_ids, referenced_ids) -> {recalled, used, unused, precision}`
  — the attribution primitive: "recorded as injected" vs "model actually referenced".

Test evidence: 27 passed overall; D2 tests confirm trivial/non-trivial classification,
explicit-query never blocked ("hi" with explicit_query=True → auto-retrieval), and
recall_metrics math incl. the discipline rule that a referenced-but-never-injected id
contributes nothing.

### In-vivo measurement (what would make it SHIPPED)
- **Event:** on each user turn, if `is_trivial(prompt)` → DO NOT fire the auto-prefetch
  round-trip; log `{"turn": n, "skipped": true, "prompt_len": N}`.
- **Success criterion:** measure (a) the fraction of turns skipped ≥ 15% in real usage
  (trivial prompts are frequent: greetings/acknowledgements/slash-commands), and (b) zero
  regression on non-trivial turns (gate precision: no real query classified trivial).
  Without (b), an aggressive gate that skips real queries is worse than no gate.
- The hard gate (no model) is the cheap half; the value is in `recall_metrics` feeding §4.

### What is NOT yet measured (MODEL_VALIDATION_PENDING)
- Real per-turn prompt distribution (needs instrumented sessions; the fixture list is a
  hand-picked sample, not a histogram).

---

## 3. D3 — Caveman-voice compression A/B (deterministic token-delta proxy)

### What the prototype proves deterministically
`caveman_rules.py` + `caveman_eval.py` + `caveman_fixtures.py`:
- Docs-approved transform: ceremony/filler removed; **payload (code blocks, inline code,
  windows/unix paths, filenames, errno symbols, error-code shapes, numbers) masked first
  and reinserted byte-identical**.
- Tokenizer: `estimate_tokens()` = chars/4 proxy `(len+3)//4`, floor 1. Real tiktoken
  cl100k_base is NOT invoked (fresh vocabulary cache would attempt a network download → no
  #network rule). Documented in `TOKENIZER_NOTE`.
- `retention_report()` asserts every payload span + digit run survives byte-identical.

Measured (this run):
```
totals: 442 -> 386 tokens (chars/4)  delta 56, 12.67%   retention_all_pass: True
  chatty_help            158 -> 115 (27.22%)   retention=PASS
  technical_brief        128 -> 119 ( 7.03%)   retention=PASS
  already_terse           26 ->  26 ( 0.00%)   retention=PASS   (control: no bloat)
  payload_heavy           79 ->  79 ( 0.00%)   retention=PASS   (control: payload-dominant)
  mixed_zh_prose_retained 51 ->  47 ( 7.84%)   retention=PASS   (style, not language)
```
Test evidence: 27 passed overall; D3 retention/determinism/payload-survival assertions
green.

### Verdict evidence + the KNOWN product conflict
- The user prefers detailed Chinese reports. Caveman voice is the opposite. D3 is therefore
  **default-OFF** in any product wiring; at most an opt-in per-command toggle, never a
  global default.
- Compression here is a proxy for "what would a BPE tokenizer actually save"; chars/4
  systematically under- / over-estimates on some vocabularies.

### What is NOT yet measured (MODEL_VALIDATION_PENDING)
- **Real tiktoken cl100k_base deltas** on the same fixtures (needs the vocab cache
  available offline; today it would download → forbidden). The 12.67% chars/4 figure is a
  lower-bound-of-record only.
- **Real model-output "before" samples** — fixtures are representative but invented; real
  assistant output could have more/less ceremony.
- **Perceptual quality** of transformed output on real docs (IS the voice acceptable? —
  needs human/model judgment, ambiguous → bins into REJECTED without it).

---

## 4. The missing measurement: injected→used attribution (ties D1/D2 together)

The failure oracle records rows; nobody has measured whether injected rows get USED.
Proposed attribution method, all within existing deterministic telemetry (`telemetry.py`):

1. **Event:** a new `oracle_inject` telemetry row written when the harness injects memory
   into a turn (the D1 render result, or the D2 auto-prefetch result). Fields:
   `{session_id, turn_ts, source: "oracle_inject", ids: [feedback record_ids],
   counts: {injected, budget_used_chars}}` with `source=="oracle_inject"` so telemetry.py's
   existing reader-self-exclusion applies and adoption accounting stays clean.
2. **Observed use:** a second lightweight signal is needed to answer "did the model mention
   that id?" — e.g. on turn end, scan the model transcript for each injected `record_id`
   (or its short hash) and record `{used: [ids]}`. This is deterministic substring scan,
   no LLM. `recall_metrics(injected, used)` then yields recalled/used/precision per turn.
3. **Sessions required:** ≥30 real work sessions (multi-session adoption evidence, same
   order as the harness P1 pull-count standard). Success criterion: mean precision ≥ 0.5
   across sessions that had ≥1 injection, AND at least one session where injected memory
   was used (proves the path end-to-end). Zero-use across 30 sessions → oracle injection
   is REJECTED as unproven value (measurement is the deliverable, not a fake win).
4. **Semantic attribution** (model used the *concept*, not the literal id) cannot be done
   deterministically. That part is `MODEL_VALIDATION_PENDING`: an LLM judge comparing
   (injected content, transcript) → used? This is explicitly deferred; no paid model runs
   this round.

### Wiring points (only if a later integrator ships D1/D2)
- **D1:** SessionStart hook flow — before the context build, call
  `session_rank.rank(feedback_store_entries, project_id=..., archetype=...)`; keep
  `cap=6`, `char_budget=2200`. Inject `render_injection(...)` output near the top of the
  built context. Emit `oracle_inject` telemetry with the returned record_ids. **Default
  OFF** behind a feature flag until §1 in-vivo criterion passes.
- **D2:** per-turn AUTO-prefetch site (`turn_context`-analog) — wrap with
  `if should_auto_retrieve(prompt): do_prefetch()`. Explicit queries bypass via
  `explicit_query=True`. Log skip/turn to telemetry. Default OFF until §2 criterion passes.
- **D3:** compress output only under an explicit per-request opt-in (never global). Guard
  any wiring with `retention_report` on the specific payload to keep byte-identical safety.

Both gates/compression are controlled variance; the feedback store remains the only state
introducing variance today.

---

## Summary table

| Prototype | File(s) | Deterministic evidence this round | In-vivo criterion (≥30 sessions) | Status now |
|---|---|---|---|---|
| D1 session-rank | `session_rank.py`, `tests/test_session_rank.py` | rank/render/budget/provenance tests green | precision≥0.5 + ≥1 used | EXPERIMENTAL |
| D2 turn-gate | `turn_gate.py`, `tests/test_turn_gate.py` | trivial/explicit/metrics tests green | skip≥15%, gate-precision 0 regression | EXPERIMENTAL |
| D3 caveman A/B | `caveman_rules.py`/`caveman_eval.py`/`caveman_fixtures.py`/`tests/test_caveman_eval.py` | 442→386 (12.67%) retention PASS all fixtures | real BPE delta + quality (default-OFF) | EXPERIMENTAL, default-OFF |

Verbatim discipline: nothing above enters product runtime until its §-listed in-vivo
criterion is measured. All three are EXperimental; none is SHIPPED yet. The one
`MODEL_VALIDATION_PENDING` risk that can flip a verdict upward is §4 semantic usage
attribution (LLM judge) — deferred by the no-model round.