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
                   help="user-correction | model-inference | human-verified | experiment-seed")
    r.add_argument("--confidence", type=float, default=0.5)
    r.add_argument("--valid-until", default=None,
                   help="ISO date/datetime; record hidden from default query after this (never deleted)")

    q = rec.add_parser("query", help="recent failures for this project")
    q.add_argument("--project-id", default=None)
    q.add_argument("--last", type=int, default=10)
    q.add_argument("--archetype", default=None)
    q.add_argument("--keyword", default=None,
                   help="substring filter over summary+cause, BM25-ranked (failure oracle)")
    q.add_argument("--include-expired", action="store_true")
    q.add_argument("--include-superseded", action="store_true")
    q.add_argument("--json", action="store_true")

    sup = rec.add_parser("supersede", help="mark a record as replaced by a newer one (append-only)")
    sup.add_argument("--record-id", required=True, help="old record to hide by default")
    sup.add_argument("--superseded-by", required=True, help="newer replacement record")
    sup.add_argument("--project-id", default=None)

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
    ga = g.add_parser("approve", help="approve commands matching regex for ttl seconds; "
                                      "--once issues a single-use token instead")
    ga.add_argument("--pattern", default=None, help="multi-use: commands matching this regex (ttl seconds)")
    ga.add_argument("--once", action="store_true", help="issue a single-use token bound to --action")
    ga.add_argument("--action", default=None, help="with --once: exact command (or regex with --scope pattern)")
    ga.add_argument("--scope", choices=["command", "pattern"], default="command",
                    help="with --once: exact command match or regex fullmatch")
    ga.add_argument("--ttl", type=int, default=600)
    ga.add_argument("--note", default="")
    gc = g.add_parser("check", help="dry-run: what would the gate do with this command?")
    gc.add_argument("command")
    gc.add_argument("--token", default=None, help="one-time approval token (awt-...)")

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
            valid_until=args.valid_until,
        )
        print(json.dumps(rec, ensure_ascii=False))
        print(f"project_id={pid} (source: {source})", file=sys.stderr)
        return 0

    if args.cmd == "feedback" and args.fcmd == "query":
        telemetry.log(data_dir, cmd="feedback.query", project_id=pid, argv=sys.argv)
        rows = feedback.query(data_dir, project_id=pid, last=args.last,
                              archetype=args.archetype, keyword=args.keyword,
                              include_expired=args.include_expired,
                              include_superseded=args.include_superseded)
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
        # pure reader — never logged (self-exclusion, P1.5)
        s = feedback.stats(data_dir, project_id=pid)
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "feedback" and args.fcmd == "promote":
        telemetry.log(data_dir, cmd="feedback.promote", project_id=pid, argv=sys.argv)
        entry = feedback.promote(data_dir, project_id=pid,
                                 record_id=args.record_id, status=args.status)
        print(json.dumps(entry, ensure_ascii=False))
        return 0

    if args.cmd == "feedback" and args.fcmd == "supersede":
        telemetry.log(data_dir, cmd="feedback.supersede", project_id=pid, argv=sys.argv)
        entry = feedback.supersede(data_dir, project_id=pid,
                                   record_id=args.record_id,
                                   superseded_by=args.superseded_by)
        print(json.dumps(entry, ensure_ascii=False))
        return 0

    if args.cmd == "report":
        # pure reader — never logged (self-exclusion, P1.5)
        print(json.dumps(report_mod.report(data_dir, project_id=pid,
                                           min_count=args.min_count),
                         ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "gate" and args.gcmd == "mode":
        cfg = gate.write_config(data_dir, mode=args.set)
        print(json.dumps(cfg, ensure_ascii=False))
        return 0

    if args.cmd == "gate" and args.gcmd == "approve":
        if args.once:
            if not args.action:
                print("gate approve --once requires --action", file=sys.stderr)
                return 2
            entry = gate.approve_once(data_dir, action=args.action,
                                      scope=args.scope, ttl=args.ttl, note=args.note)
            # the raw token is printed exactly here, exactly once
            print(json.dumps(entry, ensure_ascii=False))
            return 0
        if not args.pattern:
            print("gate approve requires --pattern (or --once --action)", file=sys.stderr)
            return 2
        entry = gate.approve(data_dir, pattern=args.pattern, ttl=args.ttl, note=args.note)
        print(json.dumps(entry, ensure_ascii=False))
        return 0

    if args.cmd == "gate" and args.gcmd == "check":
        print(json.dumps(gate.evaluate(data_dir, args.command, token=args.token),
                         ensure_ascii=False))
        return 0

    if args.cmd == "telemetry":
        telemetry.print_summary(data_dir)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())