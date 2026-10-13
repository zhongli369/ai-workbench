"""inventory CLI: add / list."""
import argparse
from pathlib import Path

from model import Item, load, save

DB = Path(__file__).resolve().parent / "inventory.json"


def main(argv=None):
    p = argparse.ArgumentParser(prog="inv")
    sub = p.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add")
    pa.add_argument("name")
    pa.add_argument("qty", type=int)
    pa.add_argument("price", type=float)
    sub.add_parser("list")
    args = p.parse_args(argv)
    items = load(DB)
    if args.cmd == "add":
        items.append(Item(args.name, args.qty, args.price))
        save(DB, items)
        print(f"added {args.name}")
        return 0
    for it in items:
        print(f"{it.name}\tx{it.qty}\t{it.price:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
