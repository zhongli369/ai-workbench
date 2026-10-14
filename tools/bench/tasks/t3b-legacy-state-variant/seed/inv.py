"""inventory tool — print the total quantity across all items.

Shipped reader. The verifier hash-pins this file: it must not change.
"""
import json
import sys
from pathlib import Path

STATE = Path(__file__).parent / "inv_state.json"


def load_items():
    data = json.loads(STATE.read_text(encoding="utf-8"))
    if data["revision"] != 3:
        raise SystemExit(f"unsupported store revision: {data['revision']!r}")
    return data["items"]


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "total":
        print("usage: inv.py total")
        return 2
    total = sum(item["qty"] for item in load_items())
    print(f"total: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
