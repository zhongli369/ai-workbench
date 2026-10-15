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
from harness import feedback, gate, plan as plan_mod, project_id  # noqa: E402
from harness import report as report_mod, telemetry  # noqa: E402
from harness import state as state_mod  # noqa: E402


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

    pl = sub.add_parser("plan", help="DEEP-mode: deterministic phase scaffold + AC (on-demand)")
    pl.add_argument("task", nargs="+", help="task description")
    pl.add_argument("--archetype", default=None,
                    help="override classification (one of: " + ", ".join(plan_mod.ARCHETYPES) + ")")
    pl.add_argument("--save", action="store_true",
                    help="persist the plan as stage-0 checkpoint (requires --exec)")
    pl.add_argument("--exec", dest="exec_id", default=None,
                    help="execution id for --save (default: slugified task)")

    t = sub.add_parser("telemetry", help="invocation ledger summary (reader, not counted)")

    cp = sub.add_parser("checkpoint", help="task-state checkpoints (t8-class integrity)").add_subparsers(
        dest="ccmd", required=True)
    cb = cp.add_parser("begin", help="mark a stage in-flight (crash marker)")
    cb.add_argument("--exec", dest="exec_id", required=True)
    cb.add_argument("--stage", required=True)
    cb.add_argument("--index", type=int, default=0)
    cs = cp.add_parser("save", help="append one checkpoint (never truncates)")
    cs.add_argument("--exec", dest="exec_id", required=True)
    cs.add_argument("--stage", required=True)
    cs.add_argument("--index", type=int, default=0)
    cs.add_argument("--status", default="done",
                    choices=["started", "done", "failed", "blocked"])
    cs.add_argument("--payload", default=None, help="JSON object string")
    cs.add_argument("--payload-file", default=None, help="path to JSON file ('-' = stdin)")
    cl = cp.add_parser("load", help="latest valid checkpoint + health (never silent)")
    cl.add_argument("--exec", dest="exec_id", required=True)
    cr = cp.add_parser("replay", help="all valid checkpoints + health")
    cr.add_argument("--exec", dest="exec_id", required=True)
    cv = cp.add_parser("verify", help="full-chain integrity report (exit 1 if damaged)")
    cv.add_argument("--exec", dest="exec_id", required=True)
    cp.add_parser("list", help="list executions present in the checkpoint store")
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


def _force_utf8_stdio() -> None:
    """Human-facing prints may carry CJK text; a cp1252 console (en-US
    Windows) would crash print() with UnicodeEncodeError. Reconfigure to
    UTF-8 so output never raises. (Machine-facing JSON uses ensure_ascii=True
    and stays pure ASCII on any locale.)"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
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
        print(json.dumps(rec, ensure_ascii=True))
        print(f"project_id={pid} (source: {source})", file=sys.stderr)
        return 0

    if args.cmd == "feedback" and args.fcmd == "query":
        telemetry.log(data_dir, cmd="feedback.query", project_id=pid, argv=sys.argv)
        rows = feedback.query(data_dir, project_id=pid, last=args.last,
                              archetype=args.archetype, keyword=args.keyword,
                              include_expired=args.include_expired,
                              include_superseded=args.include_superseded)
        if args.json:
            print(json.dumps(rows, ensure_ascii=True, indent=2))
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
        print(json.dumps(s, ensure_ascii=True, indent=2))
        return 0

    if args.cmd == "feedback" and args.fcmd == "promote":
        telemetry.log(data_dir, cmd="feedback.promote", project_id=pid, argv=sys.argv)
        entry = feedback.promote(data_dir, project_id=pid,
                                 record_id=args.record_id, status=args.status)
        print(json.dumps(entry, ensure_ascii=True))
        return 0

    if args.cmd == "feedback" and args.fcmd == "supersede":
        telemetry.log(data_dir, cmd="feedback.supersede", project_id=pid, argv=sys.argv)
        entry = feedback.supersede(data_dir, project_id=pid,
                                   record_id=args.record_id,
                                   superseded_by=args.superseded_by)
        print(json.dumps(entry, ensure_ascii=True))
        return 0

    if args.cmd == "report":
        # pure reader — never logged (self-exclusion, P1.5)
        print(json.dumps(report_mod.report(data_dir, project_id=pid,
                                           min_count=args.min_count),
                         ensure_ascii=True, indent=2))
        return 0

    if args.cmd == "gate" and args.gcmd == "mode":
        cfg = gate.write_config(data_dir, mode=args.set)
        print(json.dumps(cfg, ensure_ascii=True))
        return 0

    if args.cmd == "gate" and args.gcmd == "approve":
        if args.once:
            if not args.action:
                print("gate approve --once requires --action", file=sys.stderr)
                return 2
            entry = gate.approve_once(data_dir, action=args.action,
                                      scope=args.scope, ttl=args.ttl, note=args.note)
            # the raw token is printed exactly here, exactly once
            print(json.dumps(entry, ensure_ascii=True))
            return 0
        if not args.pattern:
            print("gate approve requires --pattern (or --once --action)", file=sys.stderr)
            return 2
        entry = gate.approve(data_dir, pattern=args.pattern, ttl=args.ttl, note=args.note)
        print(json.dumps(entry, ensure_ascii=True))
        return 0

    if args.cmd == "gate" and args.gcmd == "check":
        print(json.dumps(gate.evaluate(data_dir, args.command, token=args.token),
                         ensure_ascii=True))
        return 0

    if args.cmd == "plan":
        telemetry.log(data_dir, cmd="plan", project_id=pid, argv=sys.argv)
        try:
            result = plan_mod.plan(" ".join(args.task), archetype=args.archetype)
        except ValueError as e:
            print(json.dumps({"error": "bad_input", "detail": str(e)},
                             ensure_ascii=True), file=sys.stderr)
            return 2
        if args.save:
            store = state_mod.CheckpointStore(data_dir)
            exec_id = args.exec_id or result["checkpoint_hint"]["execution_id"]
            rec = store.save(exec_id, "Plan", result, stage_index=0, status="done")
            result["saved_checkpoint"] = {"execution_id": exec_id,
                                          "checkpoint_id": rec["checkpoint_id"]}
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0

    if args.cmd == "telemetry":
        telemetry.print_summary(data_dir)
        return 0

    if args.cmd == "checkpoint":
        return _checkpoint_main(args, data_dir, pid)

    return 2


def _read_payload(args: argparse.Namespace) -> dict:
    """Payload from --payload JSON string, --payload-file path, or {} default."""
    raw = None
    if args.payload_file == "-":
        raw = sys.stdin.read()
    elif args.payload_file:
        raw = Path(args.payload_file).read_text(encoding="utf-8-sig")
    elif args.payload is not None:
        raw = args.payload
    if raw is None:
        return {}
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("checkpoint payload must be a JSON object")
    return obj


def _checkpoint_main(args: argparse.Namespace, data_dir: Path, pid: str) -> int:
    store = state_mod.CheckpointStore(data_dir)
    try:
        if args.ccmd == "begin":
            telemetry.log(data_dir, cmd="checkpoint.begin", project_id=pid, argv=sys.argv)
            marker = store.begin(args.exec_id, args.stage, args.index)
            print(json.dumps(marker, ensure_ascii=True))
            return 0
        if args.ccmd == "save":
            telemetry.log(data_dir, cmd="checkpoint.save", project_id=pid, argv=sys.argv)
            rec = store.save(args.exec_id, args.stage, _read_payload(args),
                             stage_index=args.index, status=args.status)
            print(json.dumps(rec, ensure_ascii=True))
            return 0
        if args.ccmd == "load":
            # pure reader — never logged (self-exclusion)
            rec, health = store.load_latest(args.exec_id)
            print(json.dumps({"checkpoint": rec, "health": health,
                              "active_marker": store.active(args.exec_id)},
                             ensure_ascii=True, indent=2))
            return 0
        if args.ccmd == "replay":
            # pure reader — never logged
            records, health = store.replay(args.exec_id)
            print(json.dumps({"checkpoints": records, "health": health},
                             ensure_ascii=True, indent=2))
            return 0
        if args.ccmd == "verify":
            # pure reader — never logged
            report = store.verify(args.exec_id)
            print(json.dumps(report, ensure_ascii=True, indent=2))
            return 0 if report["ok"] else 1
        if args.ccmd == "list":
            # pure reader — never logged
            print(json.dumps(_list_executions(store), ensure_ascii=True, indent=2))
            return 0
    except state_mod.CorruptStateError as e:
        print(json.dumps({"error": "corrupt_state", "detail": str(e)},
                         ensure_ascii=True), file=sys.stderr)
        return 1
    except (ValueError, json.JSONDecodeError) as e:
        print(json.dumps({"error": "bad_input", "detail": str(e)},
                         ensure_ascii=True), file=sys.stderr)
        return 2
    return 2


def _list_executions(store: state_mod.CheckpointStore) -> list[dict]:
    """One summary row per execution log in the store (reader, tolerant)."""
    rows = []
    log_dir = store._dir  # same-module introspection, read-only
    if not log_dir.is_dir():
        return rows
    for path in sorted(log_dir.glob("*.jsonl")):
        stem = path.stem
        try:
            records, health = store.replay(stem)
            exec_id = records[0]["execution_id"] if records else stem
            rows.append({"execution_id": exec_id, "checkpoints": len(records),
                         "healthy": health["ok"],
                         "active": store.active(stem) is not None})
        except state_mod.CorruptStateError as e:
            rows.append({"execution_id": stem, "checkpoints": 0,
                         "healthy": False, "error": str(e)})
    return rows


if __name__ == "__main__":
    sys.exit(main())