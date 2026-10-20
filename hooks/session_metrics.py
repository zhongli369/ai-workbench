"""SessionEnd hook — one structured metric line per session, written at exit.

Closure of the observability gap: harness telemetry only records CLI calls, but
production sessions never invoke the CLI. This hook aggregates one ASCII JSON
metric line from the session transcript (zero model tokens, no content read)
and appends it to `<data_dir>/session-metrics.jsonl`.

Wire in .claude/settings.json (host integration):
  {"hooks": {"SessionEnd": [{"hooks": [{"type": "command",
      "command": "python <abs>/hooks/session_metrics.py"}]}]}}

stdin payload (defensive .get — missing fields never crash):
  {"session_id", "transcript_path", "cwd", "reason"}

Ledger record:
  {schema, ts(UTC ISO), session_id, cwd, duration_s,
   user_msgs, human_msgs, assistant_msgs, input_tokens, output_tokens,
   cache_read_tokens, cache_create_tokens, tool_calls{tool:count},
   compact_events}

Counting semantics:
  - user_msgs  = every type=="user" transcript event (includes tool_result
    feedback appended back as a user turn).
  - human_msgs = user events whose message.content does NOT contain a
    tool_result block (genuine human input). user_msgs is kept unchanged for
    backward compatibility; human_msgs narrows it.
  - assistant/token/tool_calls are deduped by message.id: Claude Code
    re-serializes the same assistant message once per streamed chunk /
    compaction. The FIRST snapshot of a message is a placeholder (measured:
    all-zero usage, tool name not yet attached); the LAST snapshot per id
    carries the complete usage and content. So usage/tool_calls are taken
    from the LAST occurrence of each distinct message.id (measured over 491
    ids: every repeat sequence is monotone non-decreasing; 0 cases where the
    last snapshot is emptier than an earlier one). Counting every streamed
    event would inflate tokens ~3x. Events without an id (foreign transcript
    shape) are counted as-is.
  - append-only: a SessionEnd normally fires once per session; if the host
    fires it again (e.g. resumed session), another row is appended rather
    than an existing one mutated. Consumers must group by session_id + ts.

Structural privacy:
  - counter-only aggregation: never stores message bodies, tool inputs,
    commands or file paths. cwd is recorded (same convention as gate-audit).
  - pure ASCII on disk: json.dumps(ensure_ascii=True) escapes any CJK.

Never blocks exit: any error (unparseable payload, unreadable transcript,
unwritable ledger) exits 0. A write/layout failure additionally prints one
short diagnostic line to stderr (captured by Claude Code's debug log) so
missing metrics are diagnosable without ever affecting session exit.
stdlib only.
"""
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    import msvcrt  # Windows only
except ImportError:  # pragma: no cover - POSIX/macOS never needs the lock
    msvcrt = None

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness-core"))

from harness import data_dir as dd  # noqa: E402

LEDGER_NAME = "session-metrics.jsonl"
SCHEMA = 1


def _parse_ts(raw):
    """ISO-8601 -> aware datetime, tolerating 'Z' and mis-typed input."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iter_transcript(path):
    """Stream valid JSON objects from a transcript JSONL; skip corrupt lines.

    File missing/unreadable yields nothing (OSError swallowed) — matches the
    'transcript gone -> silent exit 0' contract.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except (OSError, ValueError):
        return


def _has_tool_result(msg):
    """True when the user message carries tool_result feedback (not a human line)."""
    if not isinstance(msg, dict):
        return False
    content = msg.get("content")
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
    return False  # str / missing content counts as human input


def aggregate(iterable):
    """Reduce transcript events to counters + duration. Content never read."""
    acc = {
        "user_msgs": 0,
        "human_msgs": 0,
        "assistant_msgs": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_create_tokens": 0,
        "tool_calls": Counter(),
        "compact_events": 0,
    }
    seen_assistant_ids = set()  # streaming/compaction re-serializations of one message
    last_usage = {}  # id -> final (most complete) usage dict; streaming snapshots grow
    last_tools = {}  # id -> tool_use names from the final snapshot of that message
    timestamps = []
    for ev in iterable:
        if not isinstance(ev, dict):
            continue
        ts = _parse_ts(ev.get("timestamp"))
        if ts is not None:
            timestamps.append(ts)

        kind = ev.get("type")
        if kind == "user":
            acc["user_msgs"] += 1
            if not _has_tool_result(ev.get("message")):
                acc["human_msgs"] += 1
        elif kind == "assistant":
            msg = ev.get("message")
            if isinstance(msg, dict):
                mid = msg.get("id")
                if isinstance(mid, str) and mid:
                    # One logical message re-serialised per streamed chunk / compact.
                    # Streaming snapshots START partial (often all-zero usage, no
                    # tool name yet) and GROW to the final usage, so the LAST
                    # occurrence per id is authoritative — first occurrence is a
                    # placeholder and would undercount tokens and tool_calls.
                    if mid in seen_assistant_ids:
                        # remember this later snapshot; usage/tool_calls rebased at end
                        usage = msg.get("usage")
                        if isinstance(usage, dict):
                            last_usage[mid] = usage
                        content = msg.get("content")
                        if isinstance(content, list):
                            last_tools[mid] = [
                                b.get("name") for b in content
                                if isinstance(b, dict) and b.get("type") == "tool_use"
                            ]
                        continue
                    seen_assistant_ids.add(mid)
                    acc["assistant_msgs"] += 1
                    usage = msg.get("usage")
                    if isinstance(usage, dict):
                        last_usage[mid] = usage
                    content = msg.get("content")
                    if isinstance(content, list):
                        last_tools[mid] = [
                            b.get("name") for b in content
                            if isinstance(b, dict) and b.get("type") == "tool_use"
                        ]
                else:
                    # Foreign transcript shape: no message.id, count every event as-is.
                    acc["assistant_msgs"] += 1
                    usage = msg.get("usage")
                    if isinstance(usage, dict):
                        acc["input_tokens"] += usage.get("input_tokens") or 0
                        acc["output_tokens"] += usage.get("output_tokens") or 0
                        acc["cache_read_tokens"] += usage.get("cache_read_input_tokens") or 0
                        acc["cache_create_tokens"] += usage.get("cache_creation_input_tokens") or 0
                    content = msg.get("content")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                name = block.get("name")
                                if isinstance(name, str):
                                    acc["tool_calls"][name] += 1
            else:
                acc["assistant_msgs"] += 1
        elif kind == "system" and ev.get("subtype") == "compact_boundary":
            acc["compact_events"] += 1

    # Rebate from the FINAL (complete) snapshot of each message.id. Streaming
    # re-serialisations share one id; their last occurrence carries full usage.
    for usage in last_usage.values():
        acc["input_tokens"] += usage.get("input_tokens") or 0
        acc["output_tokens"] += usage.get("output_tokens") or 0
        acc["cache_read_tokens"] += usage.get("cache_read_input_tokens") or 0
        acc["cache_create_tokens"] += usage.get("cache_creation_input_tokens") or 0
    for names in last_tools.values():
        for name in names:
            if isinstance(name, str):
                acc["tool_calls"][name] += 1

    duration_s = 0.0
    if len(timestamps) >= 2:
        duration_s = max(0.0, (max(timestamps) - min(timestamps)).total_seconds())
    return acc, duration_s


def build_record(payload, acc, duration_s):
    return {
        "schema": SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": payload.get("session_id") or "",
        "cwd": payload.get("cwd") or "",
        "duration_s": duration_s,
        "user_msgs": acc["user_msgs"],
        "human_msgs": acc["human_msgs"],
        "assistant_msgs": acc["assistant_msgs"],
        "input_tokens": acc["input_tokens"],
        "output_tokens": acc["output_tokens"],
        "cache_read_tokens": acc["cache_read_tokens"],
        "cache_create_tokens": acc["cache_create_tokens"],
        "tool_calls": dict(acc["tool_calls"]),
        "compact_events": acc["compact_events"],
    }


def append_line(target: Path, line: str) -> None:
    """Append one ASCII JSON line to `<target>/` + LEDGER_NAME, fsynced.

    Windows CRT "a" mode re-seeks to EOF before each write, so two concurrent
    processes can land the same offset and overwrite each other (measured:
    8 procs x 25 appends -> 138/200 rows lost without the lock). A 1-byte
    byte-range lock at offset 0 serialises appends; on POSIX O_APPEND is
    atomic per write (single flush) and no lock is taken. Raises on any
    failure — caller decides.
    """
    target.mkdir(parents=True, exist_ok=True)
    ledger = target / LEDGER_NAME
    if msvcrt is not None:
        # Neutral lock byte: only the exclusivity matters, not the range.
        with open(ledger, "a+b") as fh:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)  # blocks until free
            try:
                fh.write(line.encode("ascii") + b"\n")  # line is ASCII by construction
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:  # pragma: no cover - POSIX/macOS
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def _diagnose(exc: BaseException, target) -> None:
    """One short stderr line so lost metrics are diagnosable, without blocking."""
    location = str(target) if target is not None else "<unresolved>"
    sys.stderr.write(
        "session_metrics: ledger append failed "
        f"[{type(exc).__name__}: {exc}] data_dir={location}; "
        "exiting 0, no metric row written\n"
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return 0
    path = Path(transcript_path)
    if not path.is_file():
        return 0

    target = None
    try:
        acc, duration_s = aggregate(_iter_transcript(path))
        record = build_record(payload, acc, duration_s)
        target = dd.resolve_data_dir(flag=None, env=os.environ.get("HARNESS_DATA_DIR"))
        line = json.dumps(record, ensure_ascii=True, sort_keys=True)
        append_line(target, line)
    except Exception as exc:  # noqa: BLE001 — a hook must never break session exit
        _diagnose(exc, target)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())