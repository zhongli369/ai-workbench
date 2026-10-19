"""Offline contracts for tools/context_audit.py.

The audit is read-only and must report sizes/counts without echoing message
bodies or prompt snapshots.  These fixtures model the real 2026-10-19 session:
one api-request-shape, repeated instruction attachments, and compact boundaries.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import context_audit as ca  # noqa: E402


def _write_transcript(path: Path) -> None:
    recs = [
        {"type": "attachment", "attachment": {
            "type": "instructions", "files": [
                {"path": "C:/rules/development-workflow.md",
                 "content": "SECRET-INSTRUCTION-BODY"},
            ]}},
        {"type": "system", "subtype": "compact_boundary",
         "timestamp": "2026-10-19T12:21:05.292Z",
         "compactMetadata": {"trigger": "auto", "preTokens": 305617,
                             "postTokens": 6902,
                             "cumulativeDroppedTokens": 298715}},
        {"type": "api-request-shape", "shape": {
            "system": [{"type": "text", "text": "system prompt"}],
            "tools": [
                {"name": "Bash", "description": "native"},
                {"name": "mcp__rea__inspect_binary",
                 "description": "REA-SECRET-SCHEMA-" + "x" * 800},
                {"name": "mcp__scrapling__get",
                 "description": "SCRAPLING-SECRET-" + "y" * 200},
            ]}},
        {"type": "attachment", "attachment": {
            "type": "prompt_snapshot",
            "systemPrompt": ["SNAPSHOT-SECRET"],
            "tools": []}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in recs) + "\n",
                    encoding="utf-8")


def test_audit_groups_tools_by_server_and_reads_compact_metadata(tmp_path):
    p = tmp_path / "s.jsonl"
    _write_transcript(p)
    rep = ca.audit(p)
    assert rep["request_shape"]["tools"] == 3
    by = {r["server"]: r for r in rep["request_shape"]["by_server"]}
    assert by["native"]["tools"] == 1
    assert by["rea"]["tools"] == 1
    assert by["rea"]["chars"] > by["scrapling"]["chars"] > 0
    assert rep["compact_count"] == 1
    assert rep["compact_boundaries"][0]["preTokens"] == 305617
    assert rep["instruction_injections"][0]["injections"] == 1
    assert rep["prompt_snapshots"] == 1


def test_render_text_never_echoes_bodies_or_schemas(tmp_path):
    p = tmp_path / "s.jsonl"
    _write_transcript(p)
    out = ca.render_text(ca.audit(p))
    assert "rea" in out and "305617" in out
    for secret in ("SECRET-INSTRUCTION-BODY", "REA-SECRET-SCHEMA",
                   "SCRAPLING-SECRET", "SNAPSHOT-SECRET"):
        assert secret not in out


def test_cli_json_uses_explicit_transcript(tmp_path, capsys):
    p = tmp_path / "s.jsonl"
    _write_transcript(p)
    assert ca.main(["--transcript", str(p), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["compact_count"] == 1
    assert rep["transcript"] == str(p)


def test_project_key_matches_claude_directory_encoding():
    key = ca.project_key(Path(r"F:\Claude\ClaudeCodeProject\ai-workbench-rc"))
    assert key == "F--Claude-ClaudeCodeProject-ai-workbench-rc"
