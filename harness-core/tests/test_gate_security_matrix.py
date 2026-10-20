"""Gate security contract matrix (R3 Agent B).

Locks the in-process evaluate() matrix results over ENFORCE mode, Bash and
PowerShell tool paths — the classes already covered by test_gate_shell_expansion
/ test_gate_powershell are not duplicated here. Adds the cross-shell wrap
vectors and the Windows upper-case del form.

Contract intent (fail-closed / documented trade-offs):
  - dangerous commands always BLOCK, including quote-split words, cross-shell
    wrappers (powershell -Command / cmd /c / bash -lc), Windows upper-case
    `del /F /S` under PowerShell (case-insensitive flags).
  - `del /F /S /Q` under the BASH tool is ALLOWED (documented backward compat:
    Windows recursive-delete vocabulary is the PowerShell path; the Bash path
    matches only the original 8 pattern classes, byte-for-byte).
  - `echo "git push"` BLOCKS (documented over-block: quote stripping makes the
    dangerous text visible to the patterns — safety-first direction).
  - `"git"push` is the single runtime word `gitpush` (command-not-found, not
    `git push`), and is not a bypass.
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


QUOTED_SPLIT_DANGEROUS = [
    '"git" "push"',          # two quoted words -> git push at runtime
    '"git "push',            # quote joining with space boundary
    "g'i't 'p'ush",          # interleaved single quotes
    "git p'u'sh",            # quotes inside second word
]


@pytest.mark.parametrize("cmd", QUOTED_SPLIT_DANGEROUS)
def test_quote_split_dangerous_blocks(ddir, cmd):
    assert gate.evaluate(ddir, cmd)["decision"] == "block"


CROSS_SHELL_WRAPS = [
    'powershell -Command "git push"',
    'cmd /c "git push"',
    "bash -lc 'git push origin main'",
    "FOO=bar git push",
    "env git push",
]


@pytest.mark.parametrize("cmd", CROSS_SHELL_WRAPS)
def test_cross_shell_wraps_block(ddir, cmd):
    assert gate.evaluate(ddir, cmd)["decision"] == "block"


def test_windows_ucase_del_blocks_under_powershell(ddir):
    # PS cmdlets and flags are case-insensitive; /F /S upper-case must block.
    r = gate.evaluate(ddir, r"del /F /S /Q C:\temp\*", tool="PowerShell")
    assert r["decision"] == "block"
    assert r["matched"] == r"\bdel\b.*\s/[fs]\b"


def test_windows_del_bash_path_unchanged_backward_compat(ddir):
    # Bash path keeps byte-for-byte historical matching: `del /F /S` (upper-case
    # flags) is not in the original 8 classes AND is not valid bash syntax, so
    # it stays ALLOWED (documented limitation; Windows vocabulary is the
    # PowerShell path).
    assert gate.evaluate(ddir, r"del /F /S /Q C:\temp\*")["decision"] == "allow"
    # lowercase flags in bash WOULD match the original pattern (case-sensitive)
    assert gate.evaluate(ddir, "del /s /f x")["decision"] == "block"


def test_quote_joined_single_word_is_not_a_bypass(ddir):
    # `"git"push` is runtime word `gitpush` (no separator), command-not-found,
    # equivalent to writing `gitpush` — not git push.
    r = gate.evaluate(ddir, '"git"push')
    assert r["decision"] == "allow"


def test_echo_of_dangerous_text_blocks_documented_overblock(ddir):
    # Documented fail-closed trade-off (also in test_gate_shell_expansion).
    assert gate.evaluate(ddir, 'echo "git push origin main"')["decision"] == "block"
    assert gate.evaluate(ddir, "echo 'git push origin main'")["decision"] == "block"


def test_git_syntax_error_is_not_a_bypass(ddir):
    # `git ((push` is a bash syntax error (unbalanced arithmetic), never executes.
    assert gate.evaluate(ddir, "git ((push")["decision"] == "allow"