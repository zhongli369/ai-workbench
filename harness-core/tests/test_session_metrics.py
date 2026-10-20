"""SessionEnd hook -> session-metrics ledger contracts.

Runs the real hook script (`hooks/session_metrics.py`) as a subprocess so the
tests cover exactly the wire behaviour Claude Code observes: JSON on stdin,
HARNESS_DATA_DIR in the environment, exit code, and append-only ledger output.

Under test:
  - one transcript -> exactly one metric line with precise counters
    (duration_s, token sums, tool_calls histogram, compact_events=1)
  - corrupt transcript line tolerated, does not abort aggregation
  - missing transcript -> exit 0, no ledger file created
  - non-JSON payload -> exit 0
  - ledger stays pure ASCII even when cwd contains CJK (ensure_ascii)
  - repeated runs append (idempotent), never overwrite
"""
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "session_metrics.py"
LEDGER = "session-metrics.jsonl"

T0 = "2026-10-19T10:00:00.000Z"
T1 = "2026-10-19T10:00:05.000Z"
T2 = "2026-10-19T10:00:15.000Z"
T3 = "2026-10-19T10:00:30.500Z"

_FIXTURE = [
    {"type": "user", "timestamp": T0},
    {"type": "system", "subtype": "compact_boundary"},
    {
        "type": "assistant",
        "timestamp": T1,
        "message": {
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_creation_input_tokens": 3,
                "cache_read_input_tokens": 0,
            },
            "content": [
                {"type": "tool_use", "name": "Bash"},
                {"type": "tool_use", "name": "Read"},
            ],
        },
    },
    {"type": "user", "timestamp": T2},
    {
        "type": "assistant",
        "timestamp": T3,
        "message": {
            "usage": {
                "input_tokens": 20,
                "output_tokens": 7,
                "cache_read_input_tokens": 4,
            },
            "content": [{"type": "tool_use", "name": "Bash"}],
        },
    },
]


# Concurrency driver: loaded by 8 parallel worker processes; each appends the
# same metric line `count` times via the hook's own append_line() so the test
# exercises the exact production write path under real OS-level contention.
DRIVER_SRC = r'''
import importlib.util
import json
import os
import sys

hook_path, transcript, count, data_dir, wid = (
    sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
)
_spec = importlib.util.spec_from_file_location("sm", hook_path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["sm"] = _mod
_spec.loader.exec_module(_mod)

os.environ["HARNESS_DATA_DIR"] = data_dir
target = _mod.dd.resolve_data_dir(flag=None, env=os.environ.get("HARNESS_DATA_DIR"))
acc, duration_s = _mod.aggregate(_mod._iter_transcript(transcript))
record = _mod.build_record(
    {
        "session_id": "w" + wid,
        "cwd": os.path.dirname(os.path.abspath(transcript)),
        "transcript_path": transcript,
    },
    acc,
    duration_s,
)
line = json.dumps(record, ensure_ascii=True, sort_keys=True)
for _ in range(count):
    _mod.append_line(target, line)
'''


def write_transcript(tmp_path, name="transcript.jsonl"):
    body = "".join(json.dumps(o) + "\n" for o in _FIXTURE)
    path = tmp_path / name
    path.write_text(body + "{not json\n", encoding="utf-8")  # trailing corrupt line
    return path


def run_hook(payload, data_dir, stdin_override=None):
    env = dict(os.environ)
    env["HARNESS_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload) if stdin_override is None else stdin_override,
        text=True,
        capture_output=True,
        env=env,
    )


def read_ledger(data_dir):
    ledger_path = data_dir / LEDGER
    if not ledger_path.exists():
        return []
    raw = ledger_path.read_text(encoding="utf-8")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def test_aggregates_exactly_one_line_with_precise_values(tmp_path):
    data_dir = tmp_path / "data"
    transcript = write_transcript(tmp_path)
    payload = {
        "session_id": "sess-0001",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
        "reason": "exit_plan_mode",
    }

    proc = run_hook(payload, data_dir)
    assert proc.returncode == 0

    rows = read_ledger(data_dir)
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == 1
    assert row["session_id"] == "sess-0001"
    assert row["cwd"] == str(tmp_path)
    assert row["duration_s"] == 30.5
    assert row["user_msgs"] == 2
    assert row["human_msgs"] == 2  # fixture user events carry no tool_result
    assert row["assistant_msgs"] == 2
    assert row["input_tokens"] == 30
    assert row["output_tokens"] == 12
    assert row["cache_read_tokens"] == 4
    assert row["cache_create_tokens"] == 3
    assert row["tool_calls"] == {"Bash": 2, "Read": 1}
    assert row["compact_events"] == 1
    assert "ts" in row and "reason" not in row  # reason/body never persisted


def test_missing_transcript_exits_zero_no_ledger(tmp_path):
    data_dir = tmp_path / "data"
    payload = {
        "session_id": "s",
        "transcript_path": str(tmp_path / "nope.jsonl"),
        "cwd": str(tmp_path),
    }

    proc = run_hook(payload, data_dir)
    assert proc.returncode == 0
    assert not (data_dir / LEDGER).exists()


def test_non_json_payload_exits_zero(tmp_path):
    data_dir = tmp_path / "data"
    proc = run_hook({}, data_dir, stdin_override="not { json")
    assert proc.returncode == 0
    assert not (data_dir / LEDGER).exists()


def test_ledger_is_ascii_with_cjk_cwd(tmp_path):
    data_dir = tmp_path / "data"
    cjk_dir = tmp_path / "中文项目目录"
    cjk_dir.mkdir()
    transcript = write_transcript(tmp_path)
    payload = {
        "session_id": "sess-中文",
        "transcript_path": str(transcript),
        "cwd": str(cjk_dir),
    }

    proc = run_hook(payload, data_dir)
    assert proc.returncode == 0

    raw = (data_dir / LEDGER).read_text(encoding="utf-8")
    assert raw.isascii()
    row = json.loads(raw)
    assert row["cwd"] == str(cjk_dir)
    assert row["session_id"] == "sess-中文"


def test_human_msgs_excludes_tool_results(tmp_path):
    """A user event whose content is a tool_result is NOT a human message."""
    data_dir = tmp_path / "data"
    tool_result_user = {
        "type": "user",
        "timestamp": "2026-10-19T10:00:02.000Z",
        "message": {"role": "user", "content": [{"type": "tool_result"}]},
    }
    body = "".join(json.dumps(o) + "\n" for o in _FIXTURE + [tool_result_user])
    transcript = tmp_path / "human.jsonl"
    transcript.write_text(body, encoding="utf-8")
    payload = {
        "session_id": "sess-human",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
    }

    proc = run_hook(payload, data_dir)
    assert proc.returncode == 0

    row = read_ledger(data_dir)[0]
    assert row["user_msgs"] == 3      # total user events (unchanged semantic)
    assert row["human_msgs"] == 2     # tool_result user event excluded


def test_assistant_duplicate_message_ids_deduped(tmp_path):
    """Same message.id (streaming/retry re-serialization) counts once, tokens too."""
    data_dir = tmp_path / "data"
    dup = {
        "type": "assistant",
        "timestamp": "2026-10-19T12:00:00.000Z",
        "message": {
            "id": "msg-dup-1",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 2,
                "cache_read_input_tokens": 1,
                "cache_creation_input_tokens": 0,
            },
            "content": [{"type": "tool_use", "name": "Bash"}],
        },
    }
    distinct = {
        "type": "assistant",
        "timestamp": "2026-10-19T12:00:01.000Z",
        "message": {
            "id": "msg-distinct-2",
            "usage": {
                "input_tokens": 7,
                "output_tokens": 3,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
            "content": [{"type": "tool_use", "name": "Read"}],
        },
    }
    body = json.dumps(dup) + "\n" + json.dumps(dup) + "\n" + json.dumps(distinct) + "\n"
    transcript = tmp_path / "dedup.jsonl"
    transcript.write_text(body, encoding="utf-8")
    payload = {
        "session_id": "sess-dedup",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
    }

    proc = run_hook(payload, data_dir)
    assert proc.returncode == 0

    row = read_ledger(data_dir)[0]
    assert row["assistant_msgs"] == 2          # 3 events, 2 distinct message.id
    assert row["input_tokens"] == 12           # 5+7, not 5+5+7
    assert row["output_tokens"] == 5           # 2+3, not 2+2+3
    assert row["cache_read_tokens"] == 1
    assert row["tool_calls"] == {"Bash": 1, "Read": 1}


def test_ledger_write_failure_reports_to_stderr_and_exits_zero(tmp_path):
    """Failure must never break exit: diagnostic to stderr, still exit 0, no bad row.

    HARNESS_DATA_DIR resolves to a *file* -> mkdir(parents=True) raises
    FileExistsError deterministically on every platform.
    """
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file", encoding="utf-8")
    transcript = write_transcript(tmp_path)
    payload = {
        "session_id": "sess-fail",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
    }

    proc = run_hook(payload, blocker)
    assert proc.returncode == 0
    assert "session_metrics" in proc.stderr and proc.stderr.strip()
    # ledger row never produced anywhere
    assert not (tmp_path / "session-metrics.jsonl").exists()
    assert not (tmp_path / "data" / "session-metrics.jsonl").exists()


def test_concurrent_append_200_lines_no_interleaving(tmp_path):
    """8 parallel processes x 25 appends -> 200 whole, parseable, exact rows."""
    data_dir = tmp_path / "conc"
    transcript = write_transcript(tmp_path, name="conc.jsonl")
    driver = tmp_path / "conc_driver.py"
    driver.write_text(DRIVER_SRC, encoding="utf-8")

    procs = []
    for wid in range(8):
        env = dict(os.environ)
        env["HARNESS_DATA_DIR"] = str(data_dir)
        procs.append(
            subprocess.Popen(
                [sys.executable, str(driver), str(HOOK), str(transcript), "25",
                 str(data_dir), str(wid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        )

    for p in procs:
        _out, err = p.communicate(timeout=180)
        assert p.returncode == 0, f"worker failed: {err}"

    rows = read_ledger(data_dir)
    assert len(rows) == 200
    per_worker = Counter(r["session_id"] for r in rows)
    assert len(per_worker) == 8
    assert all(c == 25 for c in per_worker.values())
    for r in rows:
        assert r["schema"] == 1
        assert r["user_msgs"] == 2
        assert r["human_msgs"] == 2
        assert r["assistant_msgs"] == 2


def test_repeated_runs_append_two_lines(tmp_path):
    data_dir = tmp_path / "data"
    transcript = write_transcript(tmp_path)
    payload = {
        "session_id": "sess-r2",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
    }

    p1 = run_hook(payload, data_dir)
    p2 = run_hook(payload, data_dir)
    assert p1.returncode == 0 and p2.returncode == 0

    rows = read_ledger(data_dir)
    assert len(rows) == 2
    assert rows[0]["session_id"] == rows[1]["session_id"] == "sess-r2"