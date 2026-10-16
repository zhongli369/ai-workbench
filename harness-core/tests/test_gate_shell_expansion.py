"""Shell-expansion bypass contracts for the ENFORCE gate (FINAL SEAL, Agent B).

Real fault-injection finding: bash resolves ${IFS}, brace expansion, command
substitution, backticks, empty quotes and backslash escapes at RUNTIME, while
the gate matched patterns against the RAW command string — so e.g.
`git${IFS}push origin main` executed as `git push origin main` yet matched no
enforce pattern (exit 0, allowed).

Under test:
  - every bypass form below normalizes to a matching variant -> BLOCK
  - nested substitution keeps the inner command visible -> BLOCK
  - benign commands (incl. harmless $VAR / $(...) usage) stay ALLOWED
  - approvals / one-time tokens still authorize the expansion form of the
    approved action (it IS that action at runtime)
  - normalization is bounded (passes / variant count) and never under-blocks
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness-core"))

from harness import gate  # noqa: E402


@pytest.fixture()
def ddir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    gate.write_config(d, mode="enforce")
    return d


# ---- bypass forms must BLOCK -------------------------------------------------

BYPASS_FORMS = [
    "git${IFS}push origin main",                 # ${IFS} word join
    "git$IFS'push' origin main",                # $IFS word join (quoted next)
    "{git,push} origin main",                    # brace expansion
    "git$(printf ' ')push origin main",          # command substitution
    "git`printf ' '`push origin main",           # backtick substitution
    "g\\it push origin main",                    # backslash escape
    "g'i't push origin main",                    # quote-interleaved word
    "git p'u'sh origin main",                    # quotes inside second word
    "rm -r''f /tmp/x",                           # empty quotes joining flags
    "{rm,-rf} /tmp/x",                           # brace joining flags
    "git ${IFS} push origin main",               # spaced ${IFS}
    "git${IFS%???}push origin main",             # ${IFS...} with operator
]


@pytest.mark.parametrize("cmd", BYPASS_FORMS)
def test_shell_expansion_bypass_is_blocked(ddir, cmd):
    r = gate.evaluate(ddir, cmd)
    assert r["decision"] == "block", f"bypass form was allowed: {cmd!r}"
    assert r["matched"] is not None


def test_nested_substitution_exposes_inner_command(ddir):
    r = gate.evaluate(ddir, "echo $(echo $(rm -rf /))")
    assert r["decision"] == "block"


def test_substitution_wrapping_dangerous_inner_is_blocked(ddir):
    r = gate.evaluate(ddir, "echo `rm -rf /tmp/x`")
    assert r["decision"] == "block"


def test_plain_dangerous_command_still_blocked(ddir):
    r = gate.evaluate(ddir, "git push origin main")
    assert r["decision"] == "block"
    assert r["matched"] == r"\bgit\s+push\b"


# ---- benign commands stay allowed ---------------------------------------------

BENIGN_FORMS = [
    "git status",
    "git log --oneline -5",
    "ls -la",
    "echo hello $HOME",
    "echo $(date)",
    "git commit -m \"feat: add thing\"",
    "printf '%s' '{a,b}'",
    "git diff --stat",
]


@pytest.mark.parametrize("cmd", BENIGN_FORMS)
def test_benign_commands_are_allowed(ddir, cmd):
    r = gate.evaluate(ddir, cmd)
    assert r["decision"] == "allow", f"benign command was blocked: {cmd!r}"


# ---- approvals / tokens cover the expansion form of the SAME action ----------

def test_pattern_approval_authorizes_expansion_form(ddir):
    gate.approve(ddir, pattern=r"git push.*", ttl=600)
    r = gate.evaluate(ddir, "git${IFS}push origin main")
    assert r["decision"] == "allow"
    assert r["reason"] == "valid approval"


def test_token_authorizes_expansion_form_of_bound_action(ddir):
    g = gate.approve_once(ddir, action="git push origin main")
    r = gate.evaluate(ddir, "git${IFS}push origin main", token=g["token"])
    assert r["decision"] == "allow", r.get("reason")


def test_token_with_windows_backslash_path_still_matches(ddir):
    # Regression: backslash-escape normalization must apply equally to the
    # granted action and the runtime command, or any Windows-path command
    # under ENFORCE loses its token (over-block breaking a legitimate flow).
    # NOTE: must not use a C:\Users\<name> shape — the hygiene gate flags
    # user-profile paths in the tree (CI static checks).
    cmd = r"C:\tools\python312\python.exe -m pip publish"
    g = gate.approve_once(ddir, action=cmd)
    r = gate.evaluate(ddir, cmd, token=g["token"])
    assert r["decision"] == "allow", r.get("reason")


def test_unapproved_expansion_form_has_no_token_leak(ddir):
    r = gate.evaluate(ddir, "git${IFS}push origin main", token="awt-" + "0" * 48)
    assert r["decision"] == "block"
    assert r["reason"] == "unknown token"


# ---- normalization properties --------------------------------------------------

def test_normalization_is_bounded_and_idempotent(ddir):
    nasty = "git$(printf ' '${IFS}$(echo `date`))push {origin,up} main"
    variants = gate._normalize_shell(nasty)
    assert 1 <= len(variants) <= gate._NORMALIZE_MAX_VARIANTS
    for v in variants:
        assert gate._normalize_shell(v) == tuple(sorted({v}))


def test_overblock_direction_echo_of_dangerous_text(ddir):
    # Documented fail-closed trade-off: stripping quotes makes the dangerous
    # text inside an echo visible to the patterns. Over-blocking is the safe
    # direction for an irreversible-action gate.
    r = gate.evaluate(ddir, 'echo "git push origin main"')
    assert r["decision"] == "block"


def test_audit_mode_also_matches_expansion_forms(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    gate.write_config(d, mode="audit")
    r = gate.evaluate(d, "git${IFS}push origin main")
    assert r["decision"] == "audit"
    assert r["matched"] == r"\bgit\s+push\b"
