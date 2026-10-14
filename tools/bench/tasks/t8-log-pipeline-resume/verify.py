"""t8-log-pipeline-resume verifier (runs with cwd = agent workspace).

Fully self-contained (incident-B class: no __file__ anchoring, no task-dir
resources): the expected results are recomputed here from the workspace's
own logs/raw.log by an independent oracle implementation, and raw.log
itself is sha256-pinned so an agent cannot weaken the input.

Judges long-horizon correctness:
  1. stage outputs are exactly correct (records.jsonl object-by-object,
     stats.json dict equality against the recomputed oracle);
  2. report.md matches the README rendering contract (summary line,
     table order, percentage format, top-error line);
  3. the checkpoint file is truthful: stages in order, outputs exist,
     recorded sha256 matches the file on disk, rows correct.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path.cwd()
# pinned over LF-normalized bytes: git may convert line endings on checkout
RAW_LOG_SHA256 = "d7db60866d797d9184422df60b2053d6814e830923b89310bf278a95f869b258"


def _fail(msg: str) -> int:
    print(f"VERIFY FAIL: {msg}")
    return 1


# ---- independent oracle (recomputes the golden values from raw.log) ----

def _parse(line: str):
    p = line.split("|")
    if len(p) != 5:
        return None
    ts, method, path, status, ms = p
    try:
        if len(ts) != 20 or ts[4] != "-" or ts[7] != "-" or ts[10] != "T" \
                or ts[13] != ":" or ts[16] != ":" or ts[19] != "Z":
            return None
        if not (1 <= int(ts[5:7]) <= 12 and 1 <= int(ts[8:10]) <= 31
                and 0 <= int(ts[11:13]) <= 23 and 0 <= int(ts[14:16]) <= 59
                and 0 <= int(ts[17:19]) <= 59):
            return None
        if not path or not method or not method.isalpha() or not method.isupper():
            return None
        if len(status) != 3 or status.startswith("0"):
            return None
        st = int(status)
        ms_i = int(ms)
        if not (100 <= st <= 599) or ms_i < 0:
            return None
    except ValueError:
        return None
    return {"ts": ts, "method": method, "path": path, "status": st, "ms": ms_i}


def _oracle(lines: list[str]):
    recs = [r for r in (_parse(l) for l in lines) if r]
    eps: dict[str, list] = {}
    for r in recs:
        eps.setdefault(r["path"], []).append(r)
    stats = {"total_lines": len(lines), "parsed": len(recs),
             "skipped": len(lines) - len(recs), "endpoints": {}}
    for path, rs in eps.items():
        errs = sum(1 for r in rs if r["status"] >= 500)
        xs = sorted(r["ms"] for r in rs)
        stats["endpoints"][path] = {"count": len(rs), "errors": errs,
                                    "error_rate": round(errs / len(rs), 4),
                                    "p50_ms": xs[(len(xs) - 1) // 2],
                                    "max_ms": max(xs)}
    return recs, stats


def main() -> int:
    # 0) input pin — the agent may not weaken the input data
    raw_path = ROOT / "logs" / "raw.log"
    if not raw_path.is_file():
        return _fail("logs/raw.log missing")
    raw_bytes = raw_path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(raw_bytes).hexdigest() != RAW_LOG_SHA256:
        return _fail("logs/raw.log modified — input is pinned")
    lines_raw = raw_path.read_text(encoding="utf-8").splitlines()
    golden_recs, golden_stats = _oracle(lines_raw)

    # 1a) records.jsonl == oracle records (object equality, order preserved)
    recs_path = ROOT / "out" / "records.jsonl"
    if not recs_path.is_file():
        return _fail("out/records.jsonl missing")
    try:
        recs = [json.loads(l) for l in recs_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    except json.JSONDecodeError as e:
        return _fail(f"records.jsonl has invalid JSON: {e}")
    if recs != golden_recs:
        for i, (a, b) in enumerate(zip(recs, golden_recs)):
            if a != b:
                return _fail(f"records.jsonl row {i} differs: got {a} want {b}")
        return _fail(f"records.jsonl row count {len(recs)} != {len(golden_recs)}")

    # 1b) stats.json == oracle stats
    stats_path = ROOT / "out" / "stats.json"
    if not stats_path.is_file():
        return _fail("out/stats.json missing")
    try:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return _fail(f"stats.json invalid: {e}")
    if stats != golden_stats:
        return _fail("stats.json does not match the oracle aggregation")

    # 2) report.md rendering contract
    rep_path = ROOT / "report.md"
    if not rep_path.is_file():
        return _fail("report.md missing")
    lines = rep_path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "# Endpoint Report":
        return _fail("report.md must start with '# Endpoint Report'")
    s = golden_stats
    summary = f"total: {s['total_lines']} lines, {s['parsed']} parsed, {s['skipped']} skipped"
    if summary not in lines:
        return _fail(f"summary line missing or wrong: {summary!r}")
    order = sorted(s["endpoints"], key=lambda p: (-s["endpoints"][p]["count"], p))
    rows = [l for l in lines if l.startswith("| /")]
    got_paths = [r.split("|")[1].strip() for r in rows]
    if got_paths != order:
        return _fail(f"table order {got_paths} != expected {order}")
    for r in rows:
        cells = [c.strip() for c in r.split("|")[1:-1]]
        e = s["endpoints"][cells[0]]
        want = [cells[0], str(e["count"]), f"{e['error_rate'] * 100:.1f}%",
                str(e["p50_ms"]), str(e["max_ms"])]
        if cells != want:
            return _fail(f"table row for {cells[0]}: got {cells} want {want}")
    err_eps = [(p, e) for p, e in s["endpoints"].items() if e["errors"] > 0]
    if err_eps:
        top = min(err_eps, key=lambda pe: (-pe[1]["error_rate"], -pe[1]["count"], pe[0]))
        top_line = f"top error endpoint: {top[0]} ({top[1]['error_rate'] * 100:.1f}%)"
    else:
        top_line = "top error endpoint: none"
    if top_line not in lines:
        return _fail(f"top-error line missing or wrong: {top_line!r}")

    # 3) checkpoint truthfulness
    st_path = ROOT / "PIPELINE_STATE.json"
    if not st_path.is_file():
        return _fail("PIPELINE_STATE.json missing")
    try:
        # utf-8-sig: tolerate a BOM — Windows PowerShell's Out-File/Set-Content
        # emits UTF-8-with-BOM by default; the JSON payload is semantically
        # identical (t8.1 verifier fix, batch-5 forensic evidence).
        state = json.loads(st_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        return _fail(f"PIPELINE_STATE.json invalid: {e}")
    stages = state.get("stages")
    if not isinstance(stages, list) or [g.get("name") for g in stages] != ["parse", "aggregate", "render"]:
        return _fail("checkpoint stages must be [parse, aggregate, render] in order")
    want_rows = {"parse": s["parsed"], "aggregate": len(s["endpoints"]), "render": None}
    for g in stages:
        out = ROOT / g.get("output", "")
        if not out.is_file():
            return _fail(f"checkpoint output missing: {g.get('output')}")
        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        # case-insensitive: Windows certutil -hashfile prints uppercase hex;
        # hex case carries no semantics and the README spec says only "<hex>"
        # (t8.1 verifier fix — batch-5 native arm recorded the correct hash
        # in uppercase and was misjudged as stale).
        if str(g.get("sha256") or "").lower() != digest:
            return _fail(f"checkpoint sha256 stale for stage {g['name']} "
                         f"(recorded hash does not match {g.get('output')})")
        if g.get("rows") != want_rows[g["name"]]:
            return _fail(f"checkpoint rows wrong for stage {g['name']}: "
                         f"got {g.get('rows')} want {want_rows[g['name']]}")

    print("VERIFY PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
