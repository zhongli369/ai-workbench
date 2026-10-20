"""Streaming-snapshot dedup contract for the SessionEnd hook (R3 Agent B).

Measured over 12 real transcripts (491 distinct message.ids, 438 repeated):
the FIRST snapshot of a streamed assistant message is a placeholder with
all-zero usage and no tool name yet; the LAST snapshot per message.id carries
the complete usage AND the authoritative tool_use name. Every repeat sequence
is monotone non-decreasing; there was never a case where the last snapshot was
emptier than an earlier one. So "last occurrence wins" is the correct policy —
counting the first occurrence undercounts tokens to zero for ~190 of the 438
repeated ids and drops their tool_calls entirely.

This file locks that behaviour through the real hook script (subprocess):
  - one message.id re-serialised 3x (placeholder -> partial -> complete) must
    contribute the FINAL usage + FINAL tool name, not the placeholder.
  - the R1/R2 dedup contract (identical duplicates) is unaffected.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "hooks" / "session_metrics.py"
LEDGER = "session-metrics.jsonl"


def run_hook(payload, data_dir):
    env = dict(os.environ)
    env["HARNESS_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
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


def test_streaming_snapshot_uses_last_complete_usage(tmp_path):
    """Real growth pattern: one message.id re-serialised 3x while streaming.

    First snapshot is a placeholder (all-zero usage, empty tool name), middle
    partly populated, final snapshot carries the complete usage AND the
    authoritative tool name. First-occurrence counting would undercount tokens
    to 0 and lose the tool name entirely.
    """
    data_dir = tmp_path / "data"
    snap1 = {
        "type": "assistant",
        "timestamp": "2026-10-19T12:00:00.000Z",
        "message": {
            "id": "msg-stream-1",
            "usage": {
                "input_tokens": 0, "output_tokens": 0,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            },
            "content": [{"type": "tool_use", "name": ""}],
        },
    }
    snap2 = {
        "type": "assistant",
        "timestamp": "2026-10-19T12:00:01.000Z",
        "message": {
            "id": "msg-stream-1",
            "usage": {
                "input_tokens": 0, "output_tokens": 0,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            },
            "content": [{"type": "tool_use", "name": "WebFetch"}],
        },
    }
    snap3 = {
        "type": "assistant",
        "timestamp": "2026-10-19T12:00:02.000Z",
        "message": {
            "id": "msg-stream-1",
            "usage": {
                "input_tokens": 252, "output_tokens": 179,
                "cache_read_input_tokens": 19200, "cache_creation_input_tokens": 0,
            },
            "content": [{"type": "tool_use", "name": "WebSearch"}],
        },
    }
    single = {
        "type": "assistant",
        "timestamp": "2026-10-19T12:00:03.000Z",
        "message": {
            "id": "msg-stream-2",
            "usage": {
                "input_tokens": 7, "output_tokens": 3,
                "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            },
            "content": [{"type": "tool_use", "name": "Read"}],
        },
    }
    body = "".join(json.dumps(o) + "\n" for o in [snap1, snap2, snap3, single])
    transcript = tmp_path / "stream.jsonl"
    transcript.write_text(body, encoding="utf-8")
    payload = {
        "session_id": "sess-stream",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
    }

    proc = run_hook(payload, data_dir)
    assert proc.returncode == 0

    row = read_ledger(data_dir)[0]
    assert row["assistant_msgs"] == 2                 # 4 events, 2 distinct ids
    assert row["input_tokens"] == 259                 # 252 + 7, NOT 0 + 7
    assert row["output_tokens"] == 182                # 179 + 3
    assert row["cache_read_tokens"] == 19200          # 19200 + 0
    assert row["tool_calls"] == {"WebSearch": 1, "Read": 1}  # last snapshot wins


def test_identical_duplicates_still_dedup_once(tmp_path):
    """The R1/R2 dedup contract still holds: identical re-serialisations count
    one message, one usage set — no token inflation from ~3x re-emission."""
    data_dir = tmp_path / "data"
    dup = {
        "type": "assistant",
        "timestamp": "2026-10-19T12:00:00.000Z",
        "message": {
            "id": "msg-dedup-1",
            "usage": {
                "input_tokens": 5, "output_tokens": 2,
                "cache_read_input_tokens": 1, "cache_creation_input_tokens": 0,
            },
            "content": [{"type": "tool_use", "name": "Bash"}],
        },
    }
    body = (json.dumps(dup) + "\n") * 3 + json.dumps({
        "type": "assistant",
        "timestamp": "2026-10-19T12:00:01.000Z",
        "message": {"id": "msg-single", "usage": {
            "input_tokens": 7, "output_tokens": 3,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
        }, "content": [{"type": "tool_use", "name": "Read"}]},
    }) + "\n"
    transcript = tmp_path / "dedup2.jsonl"
    transcript.write_text(body, encoding="utf-8")
    payload = {
        "session_id": "sess-dedup2",
        "transcript_path": str(transcript),
        "cwd": str(tmp_path),
    }

    proc = run_hook(payload, data_dir)
    assert proc.returncode == 0
    row = read_ledger(data_dir)[0]
    assert row["assistant_msgs"] == 2
    assert row["input_tokens"] == 12        # 5 + 7, NOT 5+5+5+7
    assert row["output_tokens"] == 5        # 2 + 3
    assert row["cache_read_tokens"] == 1
    assert row["tool_calls"] == {"Bash": 1, "Read": 1}