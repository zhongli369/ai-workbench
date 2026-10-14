"""PreToolUse hook (Bash matcher) — harness irreversible-action gate.

Wire in .claude/settings.json:
  {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
    {"type": "command", "command": "python <abs>/hooks/harness_gate.py"}]}]}}

Semantics (see harness/gate.py docstring — read it before trusting this):
  DISABLED : pass-through, zero log.
  AUDIT    : dangerous commands are logged. NEVER blocks. NOT protection.
  ENFORCE  : dangerous commands block (exit 2, stderr -> Claude) unless a
             valid approval exists; unreadable config FAILS CLOSED.

Env overrides:
  HARNESS_GATE_MODE  — force mode for this session (audit|enforce|disabled)
  HARNESS_DATA_DIR   — where gate.json / approvals / audit log live
  HARNESS_GATE_TOKEN — one-time approval token (awt-...) for THIS session;
                       consumed atomically on first matching command
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness-core"))

from harness import data_dir as dd  # noqa: E402
from harness import gate  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # unparseable hook input: nothing to gate

    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0

    mode_override = os.environ.get("HARNESS_GATE_MODE") or None
    token = os.environ.get("HARNESS_GATE_TOKEN") or None
    data_dir = dd.resolve_data_dir(flag=None, env=os.environ.get("HARNESS_DATA_DIR"))
    result = gate.evaluate(data_dir, command, token=token, mode_override=mode_override)

    if result["decision"] in ("audit", "block", "block-error") or result["matched"]:
        gate.log_decision(data_dir, mode=result["mode"],
                          decision=result["decision"],
                          command=command, matched=result.get("matched"),
                          token_hash=result.get("token"))

    if result["decision"] == "block":
        print(
            f"[harness-gate ENFORCE] blocked irreversible/high-risk command "
            f"(matched: {result['matched']}). Human approval required: "
            f"python harness/cli.py gate approve --pattern \"<regex>\" --ttl 600 "
            f"or one-shot: gate approve --once --action \"<exact command>\"",
            file=sys.stderr,
        )
        return 2
    if result["decision"] == "block-error":
        print(
            f"[harness-gate ENFORCE] fail-closed: {result.get('reason')}. "
            f"Fix gate.json or switch mode deliberately.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
