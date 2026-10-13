"""Contract tests for harness-core proto. Run: python -m pytest tests/ -q
Requires nothing but pytest + stdlib.
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import feedback, project_id, telemetry  # noqa: E402
from harness.data_dir import resolve_data_dir  # noqa: E402

CLI = str(Path(__file__).resolve().parent.parent / "harness" / "cli.py")


def _run_cli(tmp_path, cmd: list[str], env_extra=None) -> subprocess.CompletedProcess:
    env = {**os.environ, "HARNESS_DATA_DIR": str(tmp_path / "data")}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, CLI, *cmd], capture_output=True, text=True, env=env,
        cwd=tmp_path, timeout=60,
    )


def test_record_query_roundtrip(tmp_path):
    # Arrange
    data_dir = tmp_path / "data"
    # Act
    rec = feedback.record(data_dir, project_id="p1", cause="silent_exit",
                          summary="phase marked done without verification")
    rows = feedback.query(data_dir, project_id="p1")
    # Assert
    assert len(rows) == 1
    assert rows[0]["record_id"] == rec["record_id"]
    assert rows[0]["failure_cause"] == "silent_exit"
    assert rows[0]["project_id"] == "p1"
    assert rows[0]["phases"] == []


def test_projects_are_isolated(tmp_path):
    data_dir = tmp_path / "data"
    feedback.record(data_dir, project_id="p1", cause="a", summary="one")
    feedback.record(data_dir, project_id="p2", cause="b", summary="two")
    assert len(feedback.query(data_dir, project_id="p1")) == 1
    assert len(feedback.query(data_dir, project_id="p2")) == 1
    s = feedback.stats(data_dir, project_id="p1")
    assert s["total"] == 1 and s["all_projects_total"] == 2


def test_legacy_codelike_schema_is_readable(tmp_path):
    # Legacy CodeLike record: both task_type and task_summary present, no project_id.
    # task_summary is authoritative when present.
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    legacy = {
        "task_type": "bugfix: cache invalidation",
        "failure_cause": "execution_failed",
        "task_summary": "sync fetched stale draws",
        "phases": ["diagnose", "fix"],
        "timestamp": "2026-09-10T10:00:00+00:00",
        "record_id": "fb-abc123",
    }
    (data_dir / "feedback.jsonl").write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    rows = feedback.query(data_dir, project_id=None)
    assert len(rows) == 1
    assert rows[0]["task_summary"] == "sync fetched stale draws"
    assert rows[0]["ts"] == legacy["timestamp"]
    # Legacy record without task_summary: task_type fills the gap.
    legacy2 = {"task_type": "typo fix", "failure_cause": "c2", "timestamp": "2026-09-11T10:00:00+00:00"}
    with open(data_dir / "feedback.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(legacy2) + "\n")
    rows = feedback.query(data_dir, project_id=None)
    assert rows[0]["task_summary"] == "typo fix"


def test_corrupted_line_skipped_and_counted(tmp_path):
    data_dir = tmp_path / "data"
    feedback.record(data_dir, project_id="p1", cause="a", summary="good")
    with open(data_dir / "feedback.jsonl", "a", encoding="utf-8") as f:
        f.write("{broken json\n")
    rows = feedback.query(data_dir, project_id="p1")
    s = feedback.stats(data_dir, project_id="p1")
    assert len(rows) == 1
    assert s["corrupted_lines"] == 1


def test_concurrent_writes_are_all_kept(tmp_path):
    data_dir = tmp_path / "data"
    n_threads, per_thread = 8, 25

    def writer(i):
        for j in range(per_thread):
            feedback.record(data_dir, project_id="p1", cause=f"c{i}", summary=f"s{i}-{j}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    s = feedback.stats(data_dir, project_id="p1")
    assert s["total"] == n_threads * per_thread
    assert s["corrupted_lines"] == 0


def test_redact_strips_secrets_before_write(tmp_path):
    data_dir = tmp_path / "data"
    feedback.record(data_dir, project_id="p1", cause="auth_failure",
                    summary="key sk-1234567890abcdef used, mail bob@example.com",
                    redact=True)
    rows = feedback.query(data_dir, project_id="p1")
    line = json.dumps(rows[0], ensure_ascii=False)
    assert "sk-1234567890abcdef" not in line and "bob@example.com" not in line
    assert "[REDACTED]" in line


def test_summary_truncated(tmp_path):
    data_dir = tmp_path / "data"
    feedback.record(data_dir, project_id="p1", cause="x", summary="长" * 300)
    rows = feedback.query(data_dir, project_id="p1")
    assert len(rows[0]["task_summary"]) <= 200


def test_telemetry_reader_is_not_counted(tmp_path):
    data_dir = tmp_path / "data"
    telemetry.log(data_dir, cmd="feedback.record", project_id="p1", argv=["harness", "feedback", "record"])
    telemetry.log(data_dir, cmd="feedback.query", project_id="p1", argv=["harness", "feedback", "query"])
    telemetry.log(data_dir, cmd="telemetry", project_id="p1", argv=["harness", "telemetry"])
    s = telemetry.summarize(data_dir)
    assert s["total"] == 2
    assert "telemetry" not in s["by_cmd"]


def test_project_id_precedence_flag_env_file(tmp_path):
    (tmp_path / ".harness-project").write_text("declared-id\n", encoding="utf-8")
    pid, src = project_id.resolve_project_id(cwd=tmp_path, flag="flag-id", env="env-id")
    assert (pid, src) == ("flag-id", "flag")
    pid, src = project_id.resolve_project_id(cwd=tmp_path, env="env-id")
    assert (pid, src) == ("env-id", "env")
    pid, src = project_id.resolve_project_id(cwd=tmp_path)
    assert (pid, src) == ("declared-id", "file")


def test_project_id_path_hash_is_stable_and_private(tmp_path):
    pid1, _ = project_id.resolve_project_id(cwd=tmp_path)
    pid2, _ = project_id.resolve_project_id(cwd=tmp_path)
    assert pid1 == pid2
    assert pid1.startswith("path:")
    assert str(tmp_path) not in pid1  # no raw path leak


def test_cli_record_stat_query_roundtrip(tmp_path):
    r = _run_cli(tmp_path, ["feedback", "record", "--cause", "silent_exit",
                            "--summary", "no verification after phase", "--project-id", "demo"])
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["failure_cause"] == "silent_exit"
    q = _run_cli(tmp_path, ["feedback", "query", "--project-id", "demo", "--json"])
    assert len(json.loads(q.stdout)) == 1
    t = _run_cli(tmp_path, ["telemetry"])
    assert "feedback.record:" in t.stdout


def test_cli_rejects_empty_fields(tmp_path):
    r = _run_cli(tmp_path, ["feedback", "record", "--cause", " ", "--summary", "x",
                            "--project-id", "demo"])
    assert r.returncode != 0


def test_data_dir_env_and_flag(tmp_path):
    flag_dir = tmp_path / "flagdir"
    r = _run_cli(tmp_path, ["--data-dir", str(flag_dir), "feedback", "record",
                            "--cause", "c1", "--summary", "s1", "--project-id", "demo"])
    assert r.returncode == 0
    assert (flag_dir / "feedback.jsonl").is_file()
    assert not (tmp_path / "data" / "feedback.jsonl").exists()


def test_fresh_install_works_no_data_dir(tmp_path):
    r = _run_cli(tmp_path, ["feedback", "query", "--project-id", "demo"])
    assert r.returncode == 0
    assert "(no records)" in r.stdout