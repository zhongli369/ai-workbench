"""D1 - Oracle session-ranking (instinct-style SessionStart surfacing).

SOURCE PATTERN (extracted, not copied): ECC (MIT, pinned b92f181b)
`scripts/hooks/session-start.js:summarizeActiveInstincts()` - the RANKING
SHAPE only:
    filter by confidence >= threshold -> dedupe -> sort (confidence desc,
    project-scope first, then id) -> slice(0, MAX_INJECTED_INSTINCTS).
    Render `- [scope conf%] action` lines; zero candidates -> '' (zero
    injection).

Adaptation for the harness failure oracle:
  * confidence is DERIVED from a per-entry success/fail ratio when the entry
    carries `stats: {"success": n, "fail": n}` (a record ranks by how often
    following it actually worked), falling back to the stored `confidence`
    field otherwise. This keeps the ranking endurance-aware rather than a
    fixed editorial quality number.
  * project-match and archetype-match are HARD relevance gates: an entry whose
    project_id differs from the query context, or whose archetype differs
    while the caller passed archetype=, scores 0 and is dropped. That is the
    precision-over-recall posture this prototype exists to evidence: the
    oracle's known pain is injected-but-unused memory, so injection only
    happens for in-context entries.
  * `cap` is an UPPER BOUND, never a target ("always 6" is forbidden): fewer
    relevant entries => fewer injected lines. Empty candidate set => [].
  * every returned ranked entry carries provenance (source store path + a
    per-entry content hash + record_id), so an injected->used attribution
    measurement can trace a used mitigation back to one store line.
  * entries are sanitized on the way in: control chars stripped and text
    length-bounded. The caller's dicts are never mutated.

Pure stdlib, fully deterministic, zero IO, zero LLM.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

# ------------------------------------------------------------------ constants

_PROJECT_MATCH_BOOST = 1.0
_ARCHETYPE_MATCH_BOOST = 1.0
# A relevance miss is a hard zero (precision over recall), NOT a soft penalty.
_MISS_BOOST = 0.0

_DEFAULT_CONFIDENCE = 0.5
_DEFAULT_CAP = 6
_DEFAULT_CHAR_BUDGET = 2200

_SANITIZE_MAX = 200          # per text field, e.g. task_summary
_MITIGATION_LINE_MAX = 160   # what a rendered line actually shows
_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_PROVENANCE_HASH_LEN = 16


# ------------------------------------------------------------------ sanitize

def sanitize_text(text: Any, *, max_len: int = _SANITIZE_MAX,
                  keep_newlines: bool = True) -> str:
    """Strip control chars (incl. \\x1b ANSI escapes) and bound length.

    Newlines are kept by default so a multi-line mitigation renders as one
    record; a single-line variant collapses them first.
    """
    if text is None:
        return ""
    s = str(text)
    if not keep_newlines:
        s = s.replace("\r", " ").replace("\n", " ")
    s = _CTRL_CHARS.sub("", s).strip()
    if max_len and len(s) > max_len:
        s = s[: max(max_len - 3, 0)].rstrip() + "..."
    return s


# ------------------------------------------------------------------ scoring

def entry_confidence(entry: dict) -> float:
    """Base confidence: success/(success+fail) from stats, else stored field.

    Never raises; malformed stats fall back to the stored confidence, and a
    wholly unusable entry resolves to 0.0 (never injected).
    """
    stats = entry.get("stats")
    if isinstance(stats, dict):
        try:
            success = int(stats.get("success") or 0)
            fail = int(stats.get("fail") or 0)
        except (TypeError, ValueError):
            success = fail = 0
        if success + fail > 0:
            return min(1.0, max(0.0, success / (success + fail)))
    try:
        raw = float(entry.get("confidence", _DEFAULT_CONFIDENCE))
    except (TypeError, ValueError):
        raw = 0.0
    return min(1.0, max(0.0, raw))


def _relevance_boosts(entry: dict, project_id: str,
                      archetype: str | None) -> tuple[float, float]:
    """(project_boost, archetype_boost). A miss is a hard 0 => score 0 => drop."""
    if sanitize_text(entry.get("project_id"), max_len=64) != project_id:
        return _MISS_BOOST, _MISS_BOOST
    if archetype is not None and entry.get("archetype") != archetype:
        return _MISS_BOOST, _MISS_BOOST
    return _PROJECT_MATCH_BOOST, _ARCHETYPE_MATCH_BOOST


def _recency_key(value: Any) -> float:
    """Stable recency sort key: ISO timestamp (or numeric epoch) => seconds.

    Unparseable/missing timestamps sort as 0 (oldest) so they never leapfrog
    a real timestamp.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.timestamp()
    except (TypeError, ValueError):
        return 0.0


def _entry_id(entry: dict) -> str:
    return str(entry.get("record_id") or "")


def _entry_hash(entry: dict) -> str:
    """Deterministic per-entry content hash (provenance)."""
    blob = json.dumps(entry, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("ascii")).hexdigest()[:_PROVENANCE_HASH_LEN]


# ------------------------------------------------------------------ core API

def rank(entries: list[dict], *,
         project_id: str,
         archetype: str | None = None,
         cap: int = _DEFAULT_CAP,
         min_confidence: float = 0.0,
         char_budget: int = _DEFAULT_CHAR_BUDGET,
         store_path: str | None = None) -> list[dict]:
    """Rank oracle entries for one project context -> ranked_entry list.

    Deterministic scoring = base confidence x project-match boost x
    archetype-match boost. Ties break by recency (newest first) then id (asc).

    - `cap` is an UPPER bound: no filler entries are synthesized to reach it.
    - `char_budget` additionally trims the LOWEST-scored whole entries that
      would not fit an injection under the budget (same rule render_injection
      applies), so rank() alone never over-delivers.
    - `store_path` (optional) is stamped into every ranked entry's
      provenance so a later attribution measurement can point at the source
      store line.
    - Returns [] (zero injection) for empty / irrelevant / below-threshold
      candidate sets.
    """
    if cap < 0:
        raise ValueError("cap must be >= 0")
    if not (0.0 <= min_confidence <= 1.0):
        raise ValueError("min_confidence must be in [0.0, 1.0]")
    if char_budget < 0:
        raise ValueError("char_budget must be >= 0")
    if not entries:
        return []

    scored: list[tuple[float, float, str, dict]] = []  # (score, recency, id, entry)
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        entry = _sanitize_entry_copy(raw)
        conf = entry_confidence(entry)
        if conf < min_confidence:
            continue
        project_boost, archetype_boost = _relevance_boosts(
            entry, project_id, archetype)
        score = conf * project_boost * archetype_boost
        if score <= 0.0:
            continue
        scored.append((score, -_recency_key(entry.get("ts") or entry.get("timestamp")),
                       _entry_id(entry), entry))

    if not scored:
        return []

    scored.sort(key=lambda t: (-t[0], t[1], t[2]))  # score desc, newest first, id asc
    ranked = [
        {
            "entry": entry,
            "score": round(score, 6),
            "confidence": round(entry_confidence(entry), 4),
            "project_boost": project_boost,
            "archetype_boost": archetype_boost,
            "provenance": {
                "store": sanitize_text(store_path, max_len=256)
                         if store_path else "",
                "record_id": _entry_id(entry),
                "hash": _entry_hash(entry),
            },
        }
        for (score, _, _, entry) in scored
    ]
    ranked = ranked[:cap] if cap else []
    return _fit_budget(ranked, char_budget)


def render_injection(ranked: list[dict], *,
                     char_budget: int = _DEFAULT_CHAR_BUDGET) -> str:
    """Render ranked entries as `[archetype conf%] mitigation` lines.

    Total output length is <= char_budget; when a line would overflow the
    budget the LOWEST-scored whole entry is dropped, never a mid-entry
    truncation. Empty input => "" (zero injection).
    """
    if char_budget < 0:
        raise ValueError("char_budget must be >= 0")
    kept: list[str] = []
    for item in _fit_budget(ranked, char_budget):
        line = _render_line(item)
        if line:
            kept.append(line)
    return "\n".join(kept)


# ------------------------------------------------------------------ internals

def _sanitize_entry_copy(entry: dict) -> dict:
    """Sanitized COPY of one oracle record. Never mutates the caller's dict."""
    clean = dict(entry)
    clean["project_id"] = sanitize_text(clean.get("project_id"), max_len=64)
    clean["archetype"] = sanitize_text(clean.get("archetype"), max_len=64)
    for key in ("task_summary", "summary", "mitigation", "failure_cause"):
        if key in clean:
            clean[key] = sanitize_text(clean.get(key))
    return clean


def _mitigation_text(entry: dict) -> str:
    """Mitigation to render: explicit `mitigation`, else the classic fields."""
    text = (entry.get("mitigation") or entry.get("task_summary")
            or entry.get("summary") or entry.get("failure_cause") or "")
    return sanitize_text(text, max_len=_MITIGATION_LINE_MAX)


def _render_line(item: dict) -> str:
    entry = item.get("entry") or {}
    archetype = entry.get("archetype") or "feature-generic"
    pct = int(round(min(1.0, max(0.0, item.get("confidence", 0.0))) * 100))
    mitigation = _mitigation_text(entry)
    if not mitigation:
        return ""
    return f"[{archetype} {pct}%] {mitigation}"


def _fit_budget(ranked: list[dict], char_budget: int) -> list[dict]:
    """Keep only the top entries whose RENDERED lines fit under char_budget.

    Entries are already score-desc; we walk high->low and stop at the first
    whole line that would push the total over budget. The caller then cannot
    produce a >budget injection, and never renders a half entry.
    """
    kept: list[dict] = []
    total = 0
    for item in ranked:
        line = _render_line(item)
        if not line:
            continue  # no mitigation: whole entry is unrenderable, skip it
        cost = len(line) + (1 if kept else 0)  # + '\n' separator for later lines
        if total + cost > char_budget:
            break  # the next LOWEST entry no longer fits whole: stop
        kept.append(item)
        total += cost
    return kept