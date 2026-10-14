"""notes tool — print a per-tag summary of the notes store.

Shipped reader. The verifier hash-pins this file: it must not change.
"""
import json
import sys
from pathlib import Path

STATE = Path(__file__).parent / "state.json"


def load_notes():
    data = json.loads(STATE.read_text(encoding="utf-8"))
    if data["version"] != 2:
        raise SystemExit(f"unsupported schema: {data['version']!r}")
    return data["notes"]


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "summary":
        print("usage: app.py summary")
        return 2
    counts = {}
    for note in load_notes():
        counts[note["tag"]] = counts.get(note["tag"], 0) + 1
    for tag in sorted(counts):
        print(f"{tag}: {counts[tag]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
