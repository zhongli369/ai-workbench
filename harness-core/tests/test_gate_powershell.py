"""PowerShell PreToolUse gate coverage (P0 safety-gap fix).

Claude Code's PreToolUse hook fires for BOTH Bash and PowerShell tools.
Previously the hook only handled tool_name == "Bash", so PowerShell executed
dangerous commands with no gating (enforce mode returned exit 0). This file
locks in the fix:

Tool-level E2E (subprocess -> hooks/harness_gate.py):
  - PowerShell + git push / Remove-Item -Recurse / case-variant / inject -> exit 2
  - PowerShell + benign (git status, Get-ChildItem, Remove-Item file.txt) -> exit 0
  - audit mode: PowerShell dangerous command logs, never blocks

Unit level (harness.gate.evaluate directly, with tool=PowerShell):
  - Remove-Item -r (prefix abbreviation) / rm -Recurse -Force (alias) -> block
  - Bash path is byte-for-byte unchanged: default tool still matches only the
    original 8 pattern classes (Remove-Item -Recurse -Force is NOT blocked via
    Bash, kept for backward compatibility)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness-core"))

from harness import gate  # noqa: E402

HOOK = REPO / "hooks" / "harness_gate.py"


@pytest.fixture()
def ddir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    gate.write_config(d, mode="enforce")
    return d


# ---- subprocess hook E2E ------------------------------------------------------


def _run_hook(payload, tmp_path, mode="enforce"):
    env = {**os.environ,
           "HARNESS_DATA_DIR": str(tmp_path),
           "HARNESS_GATE_MODE": mode}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        timeout=60,
        env=env,
    )


PS_DANGEROUS = [
    "git push origin main",
    r"Remove-Item -Recurse -Force C:\x",
    r"REMOVE-ITEM -RECURSE -FORCE C:\x",       # PS cmdlets are case-insensitive
    "git push origin main $(echo x)",           # injected form must not slip past
]


@pytest.mark.parametrize("cmd", PS_DANGEROUS)
def test_hook_blocks_powershell_dangerous(cmd, tmp_path):
    payload = {"tool_name": "PowerShell", "tool_input": {"command": cmd}}
    r = _run_hook(payload, tmp_path)
    assert r.returncode == 2, (
        f"PowerShell command not blocked (rc={r.returncode}): {cmd!r}\n"
        f"stderr: {r.stderr.decode('utf-8', 'replace')}"
    )


PS_BENIGN = [
    "git status",
    "Get-ChildItem",
    "Remove-Item file.txt",   # no -Recurse / -Force: safe single-file delete
]


@pytest.mark.parametrize("cmd", PS_BENIGN)
def test_hook_allows_powershell_benign(cmd, tmp_path):
    payload = {"tool_name": "PowerShell", "tool_input": {"command": cmd}}
    r = _run_hook(payload, tmp_path)
    assert r.returncode == 0, (
        f"PowerShell benign command blocked (rc={r.returncode}): {cmd!r}\n"
        f"stderr: {r.stderr.decode('utf-8', 'replace')}"
    )


def test_hook_audit_logs_powershell_dangerous(tmp_path):
    payload = {"tool_name": "PowerShell",
               "tool_input": {"command": "git push origin main"}}
    r = _run_hook(payload, tmp_path, mode="audit")
    assert r.returncode == 0
    audit = Path(tmp_path) / "gate-audit.jsonl"
    assert audit.is_file()
    lines = [json.loads(l) for l in audit.read_text(encoding="utf-8").splitlines()]
    assert any(e.get("decision") == "audit" for e in lines)


# ---- audit log records the originating tool (R7 observability gap) ------------
#
# gate-audit.jsonl previously had no `tool` field, so Bash and PowerShell
# decisions were indistinguishable in the log (found in production: 11 audit
# rows, tool unattributable). The hook must record it for both tools.


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
def test_hook_audit_entry_records_tool(tmp_path, tool):
    payload = {"tool_name": tool,
               "tool_input": {"command": "git push origin main"}}
    r = _run_hook(payload, tmp_path, mode="audit")
    assert r.returncode == 0
    audit = Path(tmp_path) / "gate-audit.jsonl"
    lines = [json.loads(l) for l in audit.read_text(encoding="utf-8").splitlines()]
    entries = [e for e in lines if e.get("decision") == "audit"]
    assert entries, "no audit entry written"
    assert all(e.get("tool") == tool for e in entries), (
        f"audit entries missing tool={tool!r}: {entries}"
    )


# ---- unit: harness.gate.evaluate with tool=PowerShell -------------------------

PS_UNIT_DANGEROUS = [
    r"Remove-Item -r C:\x",            # prefix abbreviation of -Recurse
    r"rm -Recurse -Force .\build",      # alias, both flags
    "del -Recurse -Force x",            # alias, both flags
]


@pytest.mark.parametrize("cmd", PS_UNIT_DANGEROUS)
def test_unit_blocks_powershell_recursive_delete(ddir, cmd):
    r = gate.evaluate(ddir, cmd, tool="PowerShell")
    assert r["decision"] == "block", f"not blocked: {cmd!r}"


# ---- unit: Bash path unchanged (backward compatibility) -----------------------


def test_unit_bash_path_unchanged(ddir):
    assert gate.evaluate(ddir, "git push origin main")["decision"] == "block"
    # Bash must NOT newly intercept a PS-only form: `Remove-Item -Recurse` is
    # not valid bash syntax and the original 8 patterns do not match it.
    assert gate.evaluate(ddir, "Remove-Item -Recurse -Force x")["decision"] == "allow"