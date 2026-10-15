"""Contract tests for D1 session_rank. Run: python -m pytest experiments/ -q

Hermetic: stdlib only, no IO, no telemetry, no feedback-store writes.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import session_rank
from session_rank import rank, render_injection

_LINE_RE = re.compile(r"^\[([A-Za-z0-9_-]+) (\d{1,3})%\] .+$")


def make_entry(pid="p1", arch="bugfix", ts="2026-01-01T00:00:00+00:00",
               success=1, fail=0, rid="r1", task_summary="summary",
               stats=True, **kw):
    entry = {
        "project_id": pid,
        "archetype": arch,
        "ts": ts,
        "record_id": rid,
        "task_summary": task_summary,
        "failure_cause": task_summary,
        "confidence": 0.5,
    }
    if stats:
        entry["stats"] = {"success": success, "fail": fail}
    entry.update(kw)
    return entry


def test_cap_is_upper_bound_and_order_desc():
    # 10 entries, distinct success ratios => distinct confidences, one project.
    ratios = [0.9, 0.8, 0.75, 0.7, 0.66, 0.6, 0.5, 0.4, 0.33, 0.2]
    entries = [
        make_entry(success=int(round(r * 100)), fail=int(round((1 - r) * 100)),
                   rid=f"r{i}", ts=f"2026-01-01T00:{i:02d}:00+00:00")
        for i, r in enumerate(ratios)
    ]
    out = rank(entries, project_id="p1", archetype="bugfix")
    assert len(out) == 6  # cap, not 10 (never "always 6" — exactly the 6 top)
    scores = [r["score"] for r in out]
    assert scores == sorted(scores, reverse=True)
    assert out[0]["entry"]["record_id"] == "r0"  # highest confidence first
    # every returned entry stays under cap regardless of input order
    assert len(rank(list(reversed(entries)), project_id="p1")) <= 6


def test_no_match_returns_empty():
    assert rank([], project_id="p1") == []
    others = [make_entry(pid="p2", rid="x"), make_entry(pid="p3", rid="y")]
    assert rank(others, project_id="p1") == []
    arch_mismatch = [make_entry(arch="feature-generic", rid="z")]
    assert rank(arch_mismatch, project_id="p1", archetype="bugfix") == []


def test_determinism():
    entries = [make_entry(success=s, fail=1, rid=f"r{i}", task_summary=f"t{i}")
               for i, s in enumerate((5, 3, 7, 1, 9))]
    a = rank(entries, project_id="p1")
    b = rank(entries, project_id="p1")
    assert a == b
    assert render_injection(a) == render_injection(b)


def test_min_confidence_filters():
    entries = [make_entry(success=1, fail=0, rid="hi", task_summary="high"),
               make_entry(success=0, fail=4, rid="lo", task_summary="low")]
    out = rank(entries, project_id="p1", min_confidence=0.5)
    assert [r["entry"]["record_id"] for r in out] == ["hi"]


def test_render_budget_drops_lowest_whole_entries():
    entries = [
        make_entry(rid=f"r{i}", success=(9 - i), fail=1, task_summary=f"summary-{i}")
        for i in range(6)
    ]
    text = render_injection(rank(entries, project_id="p1"), char_budget=50)
    assert len(text) <= 50
    for line in text.splitlines():
        assert _LINE_RE.match(line), line  # whole rendered entry, never a slice
    # a top line alone must fit: sanity that budget allows at least one
    top_line = render_injection(rank(entries[:1], project_id="p1"), char_budget=50)
    assert _LINE_RE.match(top_line)


def test_render_empty_when_ranked_empty():
    assert render_injection([]) == ""
    assert render_injection(rank([], project_id="p1")) == ""


def test_sanitization_strips_control_chars():
    dirty = make_entry(task_summary="fix\x1b[31mred\x1b[0m\x00 and go",
                       rid="dirty")
    out = rank([dirty], project_id="p1")
    clean_summary = out[0]["entry"]["task_summary"]
    assert "\x1b" not in clean_summary
    assert "\x00" not in clean_summary
    assert "red" in clean_summary


def test_provenance_present():
    entries = [make_entry(rid="r1", task_summary="backup before drop")]
    a = rank(entries, project_id="p1", store_path="C:/store/feedback.jsonl")
    b = rank(entries, project_id="p1", store_path="C:/store/feedback.jsonl")
    p = a[0]["provenance"]
    assert p["store"] == "C:/store/feedback.jsonl"
    assert p["record_id"] == "r1"
    assert re.fullmatch(r"[0-9a-f]{16}", p["hash"])
    assert a[0]["provenance"] == b[0]["provenance"]  # stable


def test_tie_break_recency_then_id():
    same_conf = [make_entry(rid="newer", ts="2026-02-02T00:00:00+00:00"),
                 make_entry(rid="older", ts="2025-01-01T00:00:00+00:00")]
    out = rank(same_conf, project_id="p1")
    assert [r["entry"]["record_id"] for r in out] == ["newer", "older"]
    # same ts => smaller record_id first
    same_ts = [make_entry(rid="b", ts="2026-01-01T00:00:00+00:00"),
               make_entry(rid="a", ts="2026-01-01T00:00:00+00:00")]
    out2 = rank(same_ts, project_id="p1")
    assert [r["entry"]["record_id"] for r in out2] == ["a", "b"]


def test_invalid_arguments_raise():
    import pytest
    entries = [make_entry()]
    with pytest.raises(ValueError):
        rank(entries, project_id="p1", min_confidence=1.5)
    with pytest.raises(ValueError):
        rank(entries, project_id="p1", cap=-1)
    with pytest.raises(ValueError):
        render_injection([], char_budget=-1)


def test_confidence_falls_back_to_stored_field():
    no_stats = make_entry(stats=False, confidence=0.9)
    out = rank([no_stats], project_id="p1")
    assert out[0]["confidence"] == 0.9