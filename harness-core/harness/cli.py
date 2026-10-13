"""harness CLI — feedback record/query/stats + telemetry. stdlib only.

Run from anywhere:  python <proto-root>/harness/cli.py feedback record ...
Or:                python -m harness.cli ...   (from proto root)
No F:\\Claude dependency. Data dir via --data-dir / HARNESS_DATA_DIR / platform default.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import data_dir as dd  # noqa: E402
from harness import feedback, gate, project_id, report as report_mod, telemetry  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="harness", description="harness-core proto v0")
    p.add_argument("--data-dir", default=None, help="override data dir (else HARNESS_DATA_DIR / default)")
    sub = p.add_subparsers(dest="cmd", required=True)

    rec = sub.add_parser("feedback", help="feedback record/query/stats").add_subparsers(dest="fcmd", required=True)
    r = rec.add_parser("record", help="record one failure")
    r.add_argument("--cause", required=True)
    r.add_argument("--summary", required=True)
    r.add_argument("--archetype", default="feature-generic")
    r.add_argument("--phases", nargs="*", default=None)
    r.add_argument("--project-id", default=None)
    r.add_argument("--redact", action="store_true")
    r.add_argument("--source", default="model-inference",
                   help="user-correction | model-inference | human-verified")
    r.add_argument("--confidence", type=float, default=0.5)

    q = rec.add_parser("query", help="recent failures for this project")
    q.add_argument("--project-id", default=None)
    q.add_argument("--last", type=int, default=10)
    q.add_argument("--archetype", default=None)
    q.add_argument("--keyword", default=None, help="substring over summary+cause (failure oracle)")
    q.add_argument("--json", action="store_true")

    s = rec.add_parser("stats", help="aggregate per cause")
    s.add_argument("--project-id", default=None)

    pr = rec.add_parser("promote", help="set record status (verified|promoted|retired|candidate)")
    pr.add_argument("--record-id", required=True)
    pr.add_argument("--status", required=True)
    pr.add_argument("--project-id", default=None)

    rp = sub.add_parser("report", help="recurring failure patterns -> rule/skill proposals")
    rp.add_argument("--project-id", default=None)
    rp.add_argument("--min-count", type=int, default=2)

    g = sub.add_parser("gate", help="irreversible-action gate admin").add_subparsers(dest="gcmd", required=True)
    gm = g.add_parser("mode", help="set gate mode (disabled|audit|enforce)")
    gm.add_argument("--set", required=True, choices=["disabled", "audit", "enforce"])
    ga = g.add_parser("approve", help="approve commands matching regex for ttl seconds")
    ga.add_argument("--pattern", required=True)
    ga.add_argument("--ttl", type=int, default=600)
    ga.add_argument("--note", default="")
    gc = g.add_parser("check", help="dry-run: what would the gate do with this command?")
    gc.add_argument("command")

    t = sub.add_parser("telemetry", help="invocation ledger summary (reader, not counted)")
    return p


def _get_data_dir(args: argparse.Namespace) -> Path:
    import os
    return dd.resolve_data_dir(flag=args.data_dir, env=os.environ.get("HARNESS_DATA_DIR"))


def _get_project_id(args: argparse.Namespace) -> tuple[str, str]:
    import os
    return project_id.resolve_project_id(
        flag=getattr(args, "project_id", None),
        env=os.environ.get("HARNESS_PROJECT_ID"),
    )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    data_dir = _get_data_dir(args)
    pid, source = _get_project_id(args)

    if args.cmd == "feedback" and args.fcmd == "record":
        telemetry.log(data_dir, cmd="feedback.record", project_id=pid, argv=sys.argv)
        rec = feedback.record(
            data_dir,
            project_id=pid,
            cause=args.cause,
            summary=args.summary,
            archetype=args.archetype,
            phases=args.phases,
            redact=args.redact,
            source=args.source,
            confidence=args.confidence,
        )
        print(json.dumps(rec, ensure_ascii=False))
        print(f"project_id={pid} (source: {source})", file=sys.stderr)
        return 0

    if args.cmd == "feedback" and args.fcmd == "query":
        telemetry.log(data_dir, cmd="feedback.query", project_id=pid, argv=sys.argv)
        rows = feedback.query(data_dir, project_id=pid, last=args.last,
                              archetype=args.archetype, keyword=args.keyword)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                print(f"{row['ts'][:19]}  [{row['failure_cause']}]  {row['task_summary'][:80]}")
            if not rows:
                print("(no records)")
        print(f"project_id={pid} (source: {source})", file=sys.stderr)
        return 0

    if args.cmd == "feedback" and args.fcmd == "stats":
        telemetry.log(data_dir, cmd="feedback.stats", project_id=pid, argv=sys.argv)
        s = feedback.stats(data_dir, project_id=pid)
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "feedback" and args.fcmd == "promote":
        telemetry.log(data_dir, cmd="feedback.promote", project_id=pid, argv=sys.argv)
        entry = feedback.promote(data_dir, project_id=pid,
                                 record_id=args.record_id, status=args.status)
        print(json.dumps(entry, ensure_ascii=False))
        return 0

    if args.cmd == "report":
        telemetry.log(data_dir, cmd="report", project_id=pid, argv=sys.argv)
        print(json.dumps(report_mod.report(data_dir, project_id=pid,
                                           min_count=args.min_count),
                         ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "gate" and args.gcmd == "mode":
        cfg = gate.write_config(data_dir, mode=args.set)
        print(json.dumps(cfg, ensure_ascii=False))
        return 0

    if args.cmd == "gate" and args.gcmd == "approve":
        entry = gate.approve(data_dir, pattern=args.pattern, ttl=args.ttl, note=args.note)
        print(json.dumps(entry, ensure_ascii=False))
        return 0

    if args.cmd == "gate" and args.gcmd == "check":
        print(json.dumps(gate.evaluate(data_dir, args.command), ensure_ascii=False))
        return 0

    if args.cmd == "telemetry":
        telemetry.print_summary(data_dir)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())