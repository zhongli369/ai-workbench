#!/usr/bin/env python3
"""Read-only context audit for Claude Code transcripts.

Claude Code writes ``api-request-shape`` records that contain the real tool
schemas attached to a request.  Those schemas are resident context even when
the model never calls a tool, so counting MCP servers is not enough: one
server can expose hundreds of tools.

This tool reports:

  - peak tool count and schema bytes grouped by server (``rea``,
    ``scrapling`` ...)
  - compact boundaries (pre/post tokens reported by Claude Code itself)
  - instruction files that were re-injected after a compact
  - diagnostic-only prompt snapshots (counted separately, never treated as
    request context)

It never prints message bodies, tool schemas, or environment values.  Token
figures are explicitly marked as ESTIMATES derived from characters / 4; only
``preTokens`` / ``postTokens`` come from Claude Code's own accounting.

Usage:
  python tools/context_audit.py
  python tools/context_audit.py --session <session-id>
  python tools/context_audit.py --transcript <path.jsonl> --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

CHARS_PER_TOKEN_EST = 4
PROJECTS_DIR = Path.home() / ".claude" / "projects"
# Encoding fallback may need to inspect other project directories; cap the
# number of transcript *bodies* read so the audit stays bounded and does not
# become an implicit crawl of unrelated projects.
FALLBACK_SCAN_LIMIT = 50


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def display_path(value: str | Path) -> str:
    """Redact the home prefix in human-readable output."""
    text = str(value).replace("\\", "/")
    home = str(Path.home()).replace("\\", "/").rstrip("/")
    if text.lower() == home.lower():
        return "~"
    if text.lower().startswith(home.lower() + "/"):
        return "~" + text[len(home):]
    return text


def project_key(cwd: Path) -> str:
    """Claude Code's project-directory key: non [A-Za-z0-9._-] -> '-'."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", str(cwd))


def find_transcript(cwd: Path, session: str | None = None) -> Path | None:
    if session:
        p = PROJECTS_DIR / project_key(cwd) / f"{session}.jsonl"
        if p.is_file():
            return p

    d = PROJECTS_DIR / project_key(cwd)
    if d.is_dir():
        files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                       reverse=True)
        if files:
            return files[0]

    # Encoding fallback: match the first-line ``cwd`` field.  This reads one
    # short line per transcript, never the transcript body, and is capped to
    # the most recent FALLBACK_SCAN_LIMIT transcripts.
    target = str(cwd.resolve()).lower()
    newest: tuple[float, Path] | None = None
    candidates = sorted(
        PROJECTS_DIR.glob("*/*.jsonl"), key=_mtime, reverse=True
    )[:FALLBACK_SCAN_LIMIT]
    for p in candidates:
        try:
            with p.open(encoding="utf-8", errors="replace") as f:
                first = f.readline()
            rec = json.loads(first)
        except (OSError, ValueError):
            continue
        if str(rec.get("cwd", "")).lower() != target:
            continue
        mtime = _mtime(p)
        if newest is None or mtime > newest[0]:
            newest = (mtime, p)
    return newest[1] if newest else None


def tool_server(name: str) -> str:
    if not name.startswith("mcp__"):
        return "native"
    parts = name.split("__")
    return parts[1] if len(parts) > 1 and parts[1] else "mcp"


def schema_chars(tool: object) -> int:
    return len(json.dumps(tool, ensure_ascii=False, separators=(",", ":")))


def estimate_tokens(chars: int) -> int:
    return chars // CHARS_PER_TOKEN_EST


def audit(transcript: Path) -> dict:
    best: dict | None = None
    peak_tools = 0
    compacts: list[dict] = []
    instructions: dict[str, dict[str, int]] = {}
    snapshots = 0
    lines = 0

    with transcript.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            lines += 1
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            typ = rec.get("type")

            if typ == "api-request-shape":
                shape = rec.get("shape")
                tools = shape.get("tools") if isinstance(shape, dict) else None
                if not isinstance(tools, list):
                    continue
                peak_tools = max(peak_tools, len(tools))
                agg: dict[str, dict[str, int]] = defaultdict(
                    lambda: {"tools": 0, "chars": 0})
                for tool in tools:
                    name = tool.get("name", "") if isinstance(tool, dict) else ""
                    server = tool_server(name)
                    agg[server]["tools"] += 1
                    agg[server]["chars"] += schema_chars(tool)
                total_chars = sum(v["chars"] for v in agg.values())
                if best is None or total_chars > best["schema_chars"]:
                    system = shape.get("system") or []
                    system_chars = sum(
                        len(b.get("text", "")) for b in system
                        if isinstance(b, dict))
                    best = {
                        "tools": len(tools),
                        "schema_chars": total_chars,
                        "schema_tokens_est": estimate_tokens(total_chars),
                        "system_chars": system_chars,
                        "system_tokens_est": estimate_tokens(system_chars),
                        "by_server": dict(agg),
                    }

            elif typ == "system" and rec.get("subtype") == "compact_boundary":
                meta = rec.get("compactMetadata") or {}
                compacts.append({
                    "timestamp": rec.get("timestamp"),
                    "trigger": meta.get("trigger"),
                    "preTokens": meta.get("preTokens"),
                    "postTokens": meta.get("postTokens"),
                    "cumulativeDroppedTokens": meta.get("cumulativeDroppedTokens"),
                })

            elif typ == "attachment":
                a = rec.get("attachment")
                if not isinstance(a, dict):
                    continue
                if a.get("type") == "instructions":
                    for item in a.get("files") or []:
                        if not isinstance(item, dict):
                            continue
                        path = str(item.get("path") or "?")
                        chars = len(item.get("content") or "")
                        row = instructions.setdefault(
                            path, {"chars": chars, "injections": 0})
                        row["chars"] = max(row["chars"], chars)
                        row["injections"] += 1
                elif a.get("type") == "prompt_snapshot":
                    snapshots += 1

    if best:
        best["by_server"] = sorted(
            (
                {
                    "server": name,
                    "tools": v["tools"],
                    "chars": v["chars"],
                    "tokens_est": estimate_tokens(v["chars"]),
                }
                for name, v in best["by_server"].items()
            ),
            key=lambda row: row["chars"],
            reverse=True,
        )

    return {
        "transcript": str(transcript),
        "lines": lines,
        "peak_tools": peak_tools,
        "request_shape": best,
        "compact_boundaries": compacts,
        "compact_count": len(compacts),
        "instruction_injections": [
            {"path": path, **row}
            for path, row in sorted(
                instructions.items(), key=lambda kv: kv[1]["chars"],
                reverse=True)
        ],
        "prompt_snapshots": snapshots,
        "note": (
            "tool/system token figures are ESTIMATES (chars/4); "
            "preTokens/postTokens are Claude Code's own accounting. "
            "prompt_snapshots are diagnostic records, not request context."
        ),
    }


def render_text(rep: dict) -> str:
    out: list[str] = []
    out.append(f"transcript: {display_path(rep['transcript'])}")
    out.append(f"lines: {rep['lines']}")
    shape = rep.get("request_shape")
    if shape:
        out.append(
            f"largest-schema request: {shape['tools']} tools "
            f"({shape['schema_chars']} schema chars, "
            f"~{shape['schema_tokens_est']} tokens EST)")
        out.append(f"peak tool count across requests: {rep.get('peak_tools', shape['tools'])}")
        out.append(
            f"system prompt: {shape['system_chars']} chars, "
            f"~{shape['system_tokens_est']} tokens EST")
        out.append("tool schema by server:")
        for row in shape["by_server"]:
            out.append(
                f"  {row['server']:<14} {row['tools']:>4} tools  "
                f"{row['chars']:>9} chars  ~{row['tokens_est']:>7} tok EST")
    else:
        out.append("request tools: no api-request-shape record found")

    out.append(f"compact boundaries: {rep['compact_count']}")
    for c in rep["compact_boundaries"]:
        out.append(
            f"  {c.get('timestamp')} trigger={c.get('trigger')} "
            f"pre={c.get('preTokens')} post={c.get('postTokens')} "
            f"dropped={c.get('cumulativeDroppedTokens')}")

    if rep["instruction_injections"]:
        out.append("instruction files in attachments:")
        for row in rep["instruction_injections"]:
            out.append(
                f"  {row['injections']}x {row['chars']:>7} chars  "
                f"{display_path(row['path'])}")
    out.append(
        f"prompt snapshots (diagnostic, not request context): "
        f"{rep['prompt_snapshots']}")
    out.append("note: " + rep["note"])
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only Claude Code context audit (no message bodies)")
    ap.add_argument("--cwd", default=".", help="project cwd (default: .)")
    ap.add_argument("--session", help="session id")
    ap.add_argument("--transcript", help="explicit JSONL transcript path")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    if args.transcript:
        transcript = Path(args.transcript)
    else:
        transcript = find_transcript(Path(args.cwd).resolve(), args.session)
    if transcript is None or not transcript.is_file():
        print("[FAIL] transcript not found; pass --transcript <path.jsonl>",
              file=sys.stderr)
        return 1

    rep = audit(transcript)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(render_text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
