"""v3 oracle contracts: BM25 ranking, valid_until expiry, supersession,
write-honesty read-back, empty-store fast negative. stdlib + pytest only.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import feedback  # noqa: E402

CLI = str(Path(__file__).resolve().parent.parent / "harness" / "cli.py")


def _run_cli(tmp_path, cmd: list[str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "HARNESS_DATA_DIR": str(tmp_path / "data")}
    return subprocess.run(
        [sys.executable, CLI, *cmd], capture_output=True, text=True, encoding="utf-8", env=env,
        cwd=tmp_path, timeout=60,
    )


# ---------- BM25 ranking ----------

def test_bm25_ranks_most_relevant_first(tmp_path):
    data_dir = tmp_path / "d"
    # weak hit first (newest-first would return it second anyway — so make the
    # STRONG hit the OLDEST to prove ranking beats recency)
    feedback.record(data_dir, project_id="p1", cause="cache_invalidation",
                    summary="cache invalidation race: cache stampede under cache load",
                    ts="2026-10-01T00:00:00+00:00")
    feedback.record(data_dir, project_id="p1", cause="other_bug",
                    summary="mentions cache once in passing",
                    ts="2026-10-02T00:00:00+00:00")
    rows = feedback.query(data_dir, project_id="p1", keyword="cache")
    assert [r["failure_cause"] for r in rows] == ["cache_invalidation", "other_bug"]


def test_bm25_tie_breaks_newest_first(tmp_path):
    data_dir = tmp_path / "d"
    feedback.record(data_dir, project_id="p1", cause="c1", summary="identical cache text",
                    ts="2026-10-01T00:00:00+00:00")
    feedback.record(data_dir, project_id="p1", cause="c2", summary="identical cache text",
                    ts="2026-10-02T00:00:00+00:00")
    rows = feedback.query(data_dir, project_id="p1", keyword="cache")
    assert [r["failure_cause"] for r in rows] == ["c2", "c1"]


def test_cjk_keyword_roundtrip(tmp_path):
    data_dir = tmp_path / "d"
    feedback.record(data_dir, project_id="p1", cause="silent_exit",
                    summary="阶段被标记完成但没有执行验证")
    rows = feedback.query(data_dir, project_id="p1", keyword="验证")
    assert len(rows) == 1 and rows[0]["failure_cause"] == "silent_exit"


# ---------- valid_until expiry (失效不删) ----------

def test_valid_until_excludes_expired_by_default(tmp_path):
    data_dir = tmp_path / "d"
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    feedback.record(data_dir, project_id="p1", cause="old", summary="expired hint",
                    valid_until=yesterday)
    feedback.record(data_dir, project_id="p1", cause="fresh", summary="still valid",
                    valid_until=tomorrow)
    feedback.record(data_dir, project_id="p1", cause="timeless", summary="no expiry")
    default = feedback.query(data_dir, project_id="p1")
    assert [r["failure_cause"] for r in default] == ["timeless", "fresh"]
    everything = feedback.query(data_dir, project_id="p1", include_expired=True)
    assert len(everything) == 3
    # 失效不删: record line still on disk and counted by stats
    assert feedback.stats(data_dir, project_id="p1")["total"] == 3


def test_record_rejects_malformed_valid_until(tmp_path):
    with pytest.raises(ValueError, match="valid_until"):
        feedback.record(tmp_path / "d", project_id="p1", cause="c", summary="s",
                        valid_until="not-a-date")


# ---------- supersession (append-only, 失效不删) ----------

def test_supersede_hides_old_by_default_and_chains(tmp_path):
    data_dir = tmp_path / "d"
    a = feedback.record(data_dir, project_id="p1", cause="c", summary="old answer")
    b = feedback.record(data_dir, project_id="p1", cause="c", summary="better answer")
    c = feedback.record(data_dir, project_id="p1", cause="c", summary="final answer")
    feedback.supersede(data_dir, project_id="p1", record_id=a["record_id"],
                       superseded_by=b["record_id"])
    feedback.supersede(data_dir, project_id="p1", record_id=b["record_id"],
                       superseded_by=c["record_id"])
    default = feedback.query(data_dir, project_id="p1")
    assert [r["record_id"] for r in default] == [c["record_id"]]
    everything = feedback.query(data_dir, project_id="p1", include_superseded=True)
    assert len(everything) == 3
    assert feedback.superseded_ids(data_dir, project_id="p1") == {
        a["record_id"], b["record_id"]}


def test_supersede_rejects_unknown_and_self(tmp_path):
    data_dir = tmp_path / "d"
    a = feedback.record(data_dir, project_id="p1", cause="c", summary="s")
    with pytest.raises(ValueError, match="itself"):
        feedback.supersede(data_dir, project_id="p1", record_id=a["record_id"],
                           superseded_by=a["record_id"])
    with pytest.raises(ValueError, match="unknown record_id"):
        feedback.supersede(data_dir, project_id="p1", record_id=a["record_id"],
                           superseded_by="fb-nope")


# ---------- write honesty (未落库不算成功) ----------

def test_record_raises_when_readback_fails(tmp_path, monkeypatch):
    def boom(path, record_id):
        raise IOError("simulated readback failure")
    monkeypatch.setattr(feedback, "_verify_tail", boom)
    with pytest.raises(IOError, match="readback"):
        feedback.record(tmp_path / "d", project_id="p1", cause="c", summary="s")


def test_verify_tail_rejects_corrupted_tail(tmp_path):
    path = tmp_path / "feedback.jsonl"
    path.write_text('{"record_id": "fb-ok"}\n{corrupted\n', encoding="utf-8")
    with pytest.raises(IOError, match="write verification failed"):
        feedback._verify_tail(path, "fb-ok")
    # and the healthy case passes silently
    path.write_text('{"record_id": "fb-ok"}\n', encoding="utf-8")
    feedback._verify_tail(path, "fb-ok")


# ---------- empty-store fast negative ----------

def test_query_empty_store_fast_negative_no_side_effects(tmp_path):
    missing = tmp_path / "nope"
    assert feedback.query(missing, project_id="p1", keyword="cache") == []
    assert not missing.exists()  # query must not create dir/files
    assert feedback.superseded_ids(missing, project_id="p1") == set()


# ---------- CLI roundtrip ----------

def test_cli_valid_until_and_supersede_roundtrip(tmp_path):
    r1 = _run_cli(tmp_path, ["feedback", "record", "--cause", "c", "--summary", "old",
                             "--valid-until", "2020-01-01"])
    assert r1.returncode == 0, r1.stderr
    rec1 = json.loads(r1.stdout)
    assert rec1["valid_until"] == "2020-01-01"
    r2 = _run_cli(tmp_path, ["feedback", "record", "--cause", "c", "--summary", "new"])
    rec2 = json.loads(r2.stdout)
    q = _run_cli(tmp_path, ["feedback", "query", "--json"])
    assert [r["record_id"] for r in json.loads(q.stdout)] == [rec2["record_id"]]
    q_all = _run_cli(tmp_path, ["feedback", "query", "--json", "--include-expired"])
    assert len(json.loads(q_all.stdout)) == 2
    s = _run_cli(tmp_path, ["feedback", "supersede", "--record-id", rec2["record_id"],
                            "--superseded-by", rec1["record_id"]])
    assert s.returncode == 0, s.stderr
    q2 = _run_cli(tmp_path, ["feedback", "query", "--json",
                             "--include-expired"])
    assert json.loads(q2.stdout)[0]["record_id"] == rec1["record_id"]
