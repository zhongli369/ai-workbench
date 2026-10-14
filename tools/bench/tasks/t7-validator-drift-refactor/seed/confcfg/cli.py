"""confcfg CLI: check | normalize."""
import argparse
import sys

from .loader import load_config, dump_config
from .validators_a import ConfigError
from .report import report_config


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="confcfg")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="report config health")
    c.add_argument("file")
    n = sub.add_parser("normalize", help="load (with defaults) and rewrite")
    n.add_argument("file")
    args = p.parse_args(argv)

    if args.cmd == "check":
        print(report_config(args.file))
        return 0
    try:
        cfg = load_config(args.file)
    except ConfigError as e:
        print(f"normalize failed: {e}", file=sys.stderr)
        return 1
    dump_config(cfg, args.file)
    print("normalized")
    return 0


if __name__ == "__main__":
    sys.exit(main())
