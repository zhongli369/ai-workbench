"""D2 - Per-turn retrieval gate (hermes-style trivial-prompt skip).

SOURCE PATTERN: hermes-agent (MIT, pinned 450ad505):
  - `agent/memory_provider.py:TRIVIAL_PROMPT_RE` + `is_trivial_prompt()` -
    the anchored word list of no-semantic-signal prompts;
  - `agent/turn_context.py:_memory_turn_start_and_prefetch()` - the gate is
    APPLIED to the per-turn AUTO prefetch, so trivial prompts skip the recall
    round-trip entirely;
  - `agent/memory_manager.py:describe_recall()` - the "recalled N" indicator
    that makes memory-use visible to the user/model.

The gate skips AUTO retrieval only. An explicit query (someone asking for
memory on purpose) is never blocked: `is_trivial(..., explicit_query=True)`.

`recall_metrics()` is the measurement primitive the failure oracle has been
missing: given the ids actually INJECTED into a turn and the ids the model's
transcript actually REFERENCED, it returns the injected->used attribution
(recalled / used / precision). "Recorded as injected" is not "model used it";
precision is the disillusion metric.

Pure stdlib, deterministic, zero IO.
"""
from __future__ import annotations

import re
from typing import Iterable

# Anchored and followed only by whitespace/punctuation, so "k8s"/"yolo"/"note"
# do NOT match (the ASCII 'k'/'n' word alone must be the whole prompt) while
# "hi!"/"thanks :)"/"done???" do. Pattern shape mirrors hermes TRIVIAL_PROMPT_RE.
_TRIVIAL_PROMPT_RE = re.compile(
    r"""^(?:yes|no|ok|okay|sure|thanks|thank you|y|n|yep|nope|yeah|nah|"""
    r"""hi|hey|hello|yo|sup|"""
    r"""continue|go ahead|do it|proceed|got it|cool|nice|great|done|next|lgtm|k)"""
    r"""[\s!?.:;,'"~‘’“”—–…()\[\]{}<>*&^%$#@!+=` ]*$""",
    re.IGNORECASE,
)


def is_trivial(prompt: str | None, *, explicit_query: bool = False) -> bool:
    """Deterministic gate: does this prompt carry no semantic memory signal?

    - empty / whitespace / slash-command ("/status", "/help") => trivial;
    - a bare greeting / acknowledgement (yes/no/ok/thanks/hi/continue/done/...)
      => trivial - a recall prefetch has no signal to match and would only
      derail a one-word reply;
    - `explicit_query=True` ALWAYS returns False: an explicit memory ask is
      never blocked by the AUTO-retrieval gate.
    """
    if explicit_query:
        return False
    stripped = (prompt or "").strip()
    if not stripped or stripped.startswith("/"):
        return True
    return bool(_TRIVIAL_PROMPT_RE.match(stripped))


def should_auto_retrieve(prompt: str | None, *, explicit_query: bool = False) -> bool:
    """Mirror of the gate for call sites that phrase the decision positively."""
    return not is_trivial(prompt, explicit_query=explicit_query)


def recall_metrics(injected_ids: Iterable[str],
                   referenced_ids: Iterable[str]) -> dict:
    """Injected->used attribution for one turn.

    `injected_ids`  - ids the ranker/session-start actually injected this turn.
    `referenced_ids`- ids the model's transcript/output actually referenced.

    Returns {recalled (N), used (M), unused, precision} where
    precision = used / recalled (0.0 when nothing was injected). No id is
    counted as "used" unless it was first counted as "recalled": an id that
    appears referenced but was never injected contributes nothing.
    """
    referenced = {str(r) for r in (referenced_ids or []) if r not in (None, "")}
    # Distinct injected ids, preserving first-seen order. An id injected twice
    # in one turn is ONE memory to attribute, not two.
    injected: list[str] = []
    seen: set[str] = set()
    for i in (injected_ids or []):
        rid = str(i)
        if rid in (None, "") or rid in seen:
            continue
        seen.add(rid)
        injected.append(rid)
    recalled = len(injected)
    used = sum(1 for rid in injected if rid in referenced)
    precision = used / recalled if recalled else 0.0
    return {
        "recalled": recalled,
        "used": used,
        "unused": recalled - used,
        "precision": round(precision, 6),
    }