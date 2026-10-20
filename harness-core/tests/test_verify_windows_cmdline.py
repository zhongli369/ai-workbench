"""Windows verify --cmd quoting contract (R3 Agent B).

Regression: shlex.split(posix=False) on Windows keeps grouping quotes as
literal argv characters. Measured on this host:
  - `--cmd 'python -c "print(1)"'` ran python with the LITERAL code
    `"print(1)"` -> a string expression that prints nothing, yet exited 0, so
    verify reported PASS on a command that did not do what the operator
    intended (silent distortion).
  - `--cmd 'python "dir with space/probe.py"'` split into three argv tokens
    (`"dir`, `with`, `space/probe.py"`), the child exited 2 without running.

The fix: an explicit Windows tokenizer that groups-and-strips quotes (keeping
backslashes literal) while POSIX keeps shlex. These tests run on Windows and
pin the corrected argv + real subprocess execution.
"""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness-core"))

from harness import verify as v  # noqa: E402

PY = sys.executable
B = r"\bgit\s+push\b"  # unused here; kept for import-edge parity with sibling tests


def _split(s):
    return v.VerifyCommand(s).argv


def test_windows_quote_grouping_strips_quotes():
    if os.name != "nt":
        pytest.skip("Windows tokenizer semantics")
    assert _split('python -c "print(1)"') == ["python", "-c", "print(1)"]
    assert _split("python -c 'print(1)'") == ["python", "-c", "print(1)"]


def test_windows_quoted_space_path_is_one_token():
    if os.name != "nt":
        pytest.skip("Windows tokenizer semantics")
    assert _split('python "C:/dir with space/x.py" hi') == [
        "python", "C:/dir with space/x.py", "hi"]


def test_windows_backslash_paths_stay_literal():
    if os.name != "nt":
        pytest.skip("Windows tokenizer semantics")
    assert _split(r"C:\Python312\python.exe -m pytest") == [
        r"C:\Python312\python.exe", "-m", "pytest"]


def test_windows_plain_words_unchanged():
    if os.name != "nt":
        pytest.skip("Windows tokenizer semantics")
    assert _split("python -m pytest tests -x") == ["python", "-m", "pytest", "tests", "-x"]


def test_windows_metachars_stay_literal_argv():
    if os.name != "nt":
        pytest.skip("Windows tokenizer semantics")
    assert _split('echo "a;b|c" > out.txt') == ["echo", "a;b|c", ">", "out.txt"]


def test_windows_nested_different_quote_types():
    if os.name != "nt":
        pytest.skip("Windows tokenizer semantics")
    # single quotes inside a double-quoted payload are literal code chars
    assert _split("""python -c "print('hi')"
""".strip()) == ["python", "-c", "print('hi')"]
    assert _split('''python -c 'print("hi")'
'''.strip()) == ["python", "-c", 'print("hi")']


def test_quoted_dash_c_runs_for_real(tmp_path):
    """The whole point: python -c "print(1)" must actually print 1."""
    r = v.run_verification(
        _split('python -c "print(1729)"'), cwd=str(tmp_path), timeout_s=30)
    assert r["ok"] is True
    assert "1729" in r["output_tail"], r["output_tail"]


def test_quoted_space_path_executes_for_real(tmp_path):
    """A quoted path with a space must run the intended script (was exit 2)."""
    probe = tmp_path / "probe dir"
    probe.mkdir()
    script = probe / "probe.py"
    script.write_text(
        "import sys, pathlib\n"
        "pathlib.Path(sys.argv[1]).write_text('ran')\n",
        encoding="utf-8",
    )
    marker = tmp_path / "marker.txt"
    r = v.run_verification(
        _split(f'{PY} "{script}" "{marker}"'), cwd=str(tmp_path), timeout_s=30)
    assert r["ok"] is True, r["output_tail"]
    assert marker.read_text(encoding="utf-8") == "ran"


def test_verifycommand_empty_and_nonlist_validation(tmp_path):
    with pytest.raises(ValueError):
        v.VerifyCommand([])
    with pytest.raises(ValueError):
        v.VerifyCommand("   ")
    with pytest.raises(TypeError):
        v.VerifyCommand(42)


def test_verify_command_display_roundtrip(tmp_path):
    c = v.VerifyCommand(['python', '-c', 'print(1)'])
    assert c.display == "python -c print(1)"