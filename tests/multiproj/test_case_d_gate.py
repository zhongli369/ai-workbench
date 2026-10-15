"""CASE D — 权限/高危拦截 (the "permission denied" layer, automated).

Drives the REAL PreToolUse gate hook (hooks/harness_gate.py) with
constructed Bash payloads, exercising the three modes plus one-shot tokens
exactly as the hook reads them (env overrides + gate.json in the data dir):
  DISABLED pass-through (zero log),
  AUDIT logs dangerous commands but never blocks,
  ENFORCE blocks high-risk commands (exit 2) unless approved,
  corrupt config FAILS CLOSED (block-error),
  missing config means DISABLED (documented default),
  non-Bash / unparseable tool input is ignored.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from multiproj_util import (  # noqa: E402
    run_cli, run_cli_json, run_hook, bash_payload,
)


def _audit_lines(data_dir: Path) -> list[dict]:
    f = data_dir / "gate-audit.jsonl"
    if not f.is_file():
        return []
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def test_case_d_disabled_is_pass_through_zero_log(data_dir):
    rc, out, err = run_hook(data_dir, bash_payload("git push origin main"),
                            {"HARNESS_GATE_MODE": "disabled"})
    assert rc == 0, err
    assert not (data_dir / "gate-audit.jsonl").exists()


def test_case_d_audit_logs_but_never_blocks(data_dir):
    # gate.json default from the workbench install is mode "audit".
    rc, out, err = run_hook(data_dir, bash_payload("git push origin main"))
    assert rc == 0, err
    lines = _audit_lines(data_dir)
    assert len(lines) == 1
    assert lines[0]["decision"] == "audit"
    assert "git push" in lines[0]["command"]

    # benign commands are not logged.
    rc, out, err = run_hook(data_dir, bash_payload("ls -la"))
    assert rc == 0, err
    assert len(_audit_lines(data_dir)) == 1


def test_case_d_enforce_blocks_high_risk(data_dir):
    rc, out, err = run_cli(data_dir, "gate", "mode", "--set", "enforce")
    assert rc == 0, err
    for cmd in ("git push origin main",
                "git reset --hard",
                "rm -rf /tmp/x",
                "rm -fr lib",
                "git clean -fdx"):
        rc, out, err = run_hook(data_dir, bash_payload(cmd))
        assert rc == 2, (cmd, rc, err)
        assert "ENFORCE" in err, (cmd, err)
    # benign passes.
    rc, out, err = run_hook(data_dir, bash_payload("ls -la"))
    assert rc == 0, err


def test_case_d_enforce_one_shot_token_grants_then_consumes(data_dir):
    run_cli(data_dir, "gate", "mode", "--set", "enforce")
    action = "git push origin main"
    tok = run_cli_json(data_dir, "gate", "approve", "--once", "--action", action)
    token = tok["token"]
    assert token.startswith("awt-")

    rc, out, err = run_hook(data_dir, bash_payload(action),
                            {"HARNESS_GATE_TOKEN": token})
    assert rc == 0, err
    # replay is denied.
    rc, out, err = run_hook(data_dir, bash_payload(action),
                            {"HARNESS_GATE_TOKEN": token})
    assert rc == 2, (rc, err)
    assert "ENFORCE" in err

    # a different command with the same token is also denied (scope-mismatch).
    rc, out, err = run_hook(data_dir, bash_payload("git push origin other"),
                            {"HARNESS_GATE_TOKEN": tok["token"]})
    assert rc == 2


def test_case_d_non_bash_or_unparseable_input_ignored(data_dir):
    cases = [
        json.dumps({"tool_name": "Edit", "tool_input": {}}),
        "not even json {{{",
        json.dumps({"tool_name": "Bash", "tool_input": {}}),
        "",
    ]
    for payload in cases:
        rc, out, err = run_hook(data_dir, payload)
        assert rc == 0, (payload, rc, err)
    assert not (data_dir / "gate-audit.jsonl").exists()


def test_case_d_corrupt_config_fails_closed(data_dir):
    (data_dir / "gate.json").write_text("{ this is not json", encoding="utf-8")
    rc, out, err = run_hook(data_dir, bash_payload("git push origin main"))
    assert rc == 2
    assert "fail-closed" in err


def test_case_d_missing_config_means_disabled(data_dir):
    # a bare data dir (no gate.json yet): the documented default is DISABLED,
    # so the hook passes everything through without logging.
    (data_dir / "gate.json").unlink()
    for cmd in ("git push origin main", "git reset --hard", "rm -rf x"):
        rc, out, err = run_hook(data_dir, bash_payload(cmd))
        assert rc == 0, (cmd, err)
    assert not (data_dir / "gate-audit.jsonl").exists()