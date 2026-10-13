"""noter CLI: add / list / rm."""
import sys

from noter import notes


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("usage: python -m noter <add|list|rm> [args]", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "add":
        try:
            rec = notes.add(rest[0])
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"added #{rec['id']}")
        return 0
    if cmd == "list":
        for r in notes.list_notes():
            print(f"#{r['id']}: {r['text']}")
        return 0
    if cmd == "rm":
        ok = notes.rm(int(rest[0]))
        print("removed" if ok else "not found")
        return 0 if ok else 1
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())