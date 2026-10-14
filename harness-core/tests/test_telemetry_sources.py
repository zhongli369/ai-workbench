"""Telemetry self-exclusion contracts (P1.5).

A metrics system must never inflate itself:
  - reader commands (telemetry / feedback.stats / report / gate.check)
    are never logged — not by log() and not by the CLI dispatch
  - feedback.query STAYS logged (real adoption signal — the oracle being
    consulted is product usage, not self-observation)
  - every row carries a source label; HARNESS_BENCH=1 marks bench traffic;
    legacy rows without a source count as "cli"
  - summarize() is a pure read (calling it twice appends nothing) and its
    adoption view counts only source == "cli", so bench/synthetic traffic
    can never masquerade as product usage
  - log() never raises, even on a bad source label (telemetry must not
    break the tool) — but an invalid source must not write a row either
  - all three bench runners label their subprocess traffic HARNESS_BENCH=1
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness-core"))

from harness import telemetry  # noqa: E402


def _rows(data_dir: Path) -> list[dict]:
    path = data_dir / "telemetry.jsonl"
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_reader_commands_never_write(tmp_path):
    for cmd in ("telemetry", "feedback.stats", "report", "gate.check"):
        telemetry.log(tmp_path, cmd=cmd, project_id="p", argv=["x"])
    assert _rows(tmp_path) == [], "a stats system counted its own reads"


def test_query_is_logged_as_cli_adoption_signal(tmp_path, monkeypatch):
    monkeypatch.delenv("HARNESS_BENCH", raising=False)
    telemetry.log(tmp_path, cmd="feedback.query", project_id="p", argv=["x"])
    rows = _rows(tmp_path)
    assert len(rows) == 1 and rows[0]["source"] == "cli"


def test_cli_dispatch_has_no_reader_log_calls():
    """Defense in depth: even if log()'s reader set regresses, the dispatch
    layer must not attempt to log readers in the first place."""
    src = (REPO / "harness-core" / "harness" / "cli.py").read_text(encoding="utf-8")
    stats_branch = re.search(r'fcmd == "stats":\n(.*?)\n    if args\.cmd', src, re.S)
    report_branch = re.search(r'args\.cmd == "report":\n(.*?)\n    if args\.cmd', src, re.S)
    assert stats_branch and "telemetry.log" not in stats_branch.group(1)
    assert report_branch and "telemetry.log" not in report_branch.group(1)
    # writers stay logged — the guard must not over-delete
    for writer in ("record", "query", "promote", "supersede"):
        branch = re.search(rf'fcmd == "{writer}":\n(.*?)\n    if args\.cmd', src, re.S)
        assert branch and "telemetry.log" in branch.group(1), \
            f"feedback.{writer} lost its telemetry row"


def test_bench_env_marks_source(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_BENCH", "1")
    telemetry.log(tmp_path, cmd="feedback.record", project_id="p", argv=["x"])
    assert _rows(tmp_path)[0]["source"] == "bench"


def test_explicit_source_wins_over_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_BENCH", "1")
    telemetry.log(tmp_path, cmd="feedback.record", project_id="p",
                  argv=["x"], source="synthetic")
    assert _rows(tmp_path)[0]["source"] == "synthetic"


def test_invalid_source_neither_raises_nor_writes(tmp_path):
    telemetry.log(tmp_path, cmd="feedback.record", project_id="p",
                  argv=["x"], source="bogus")
    assert _rows(tmp_path) == []


def test_adoption_view_counts_cli_only_including_legacy(tmp_path):
    legacy = {"ts": "2026-10-13T00:00:00+00:00", "cmd": "feedback.record",
              "project_id": "p", "argv": []}  # no "source" key = legacy row
    with open(tmp_path / "telemetry.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(legacy) + "\n")
    telemetry.log(tmp_path, cmd="feedback.record", project_id="p",
                  argv=["x"], source="bench")
    telemetry.log(tmp_path, cmd="feedback.query", project_id="p",
                  argv=["x"], source="synthetic")
    s = telemetry.summarize(tmp_path)
    assert s["total"] == 3
    assert s["by_source"] == {"cli": 1, "bench": 1, "synthetic": 1}
    assert s["adoption"] == {"total": 1, "by_cmd": {"feedback.record": 1}}, \
        "bench/synthetic traffic leaked into the adoption view"


def test_summarize_is_a_pure_read(tmp_path):
    telemetry.log(tmp_path, cmd="feedback.query", project_id="p", argv=["x"])
    before = _rows(tmp_path)
    s1 = telemetry.summarize(tmp_path)
    s2 = telemetry.summarize(tmp_path)
    assert s1 == s2 and _rows(tmp_path) == before, \
        "querying the stats changed the stats"


def test_all_bench_runners_label_traffic():
    for rel in ("tools/bench/run_arm.py", "tools/bench/run_sdk_arm.py",
                "tools/bench/run_t3_pair.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert "HARNESS_BENCH" in src, f"{rel}: bench traffic unlabeled"
