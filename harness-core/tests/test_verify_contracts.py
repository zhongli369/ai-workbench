"""Verification-loop contract tests (OPERATION ARSENAL - Agent B).

Pins the mechanism-only, fail-closed post-edit verification loop:
  - run_verification: real exit code, merged stderr, tail-capped output,
    utf-8-with-replacement decode, hard timeouts, no shell anywhere.
  - authorization: .harness-verify.json (any gate mode) vs operator --cmd
    (refused under DISABLED, logged+allowed under AUDIT) vs skipped default.
  - bounded retry: mechanical reflection counter, reflections-exhausted cap.
  - can_claim_done: the completion gate - a FAILED verification blocks done,
    a fixed fixture unblocks it; corrupt evidence reads as damage, not ok.
  - checkpoint integration:  verify failure flips the stage checkpoint to
    status=failed; all-pass writes {"verify": "ok"} status=done.

Hermetic: tmp_path only, no network, short child timeouts, Windows+Linux safe.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness-core"))

from harness import gate, state  # noqa: E402
from harness.state import CheckpointStore  # noqa: E402
from harness.verify import (  # noqa: E402
    CONFIG_FILENAME, DEFAULT_MAX_OUTPUT, EXHAUSTED, REFUSED,
    VerifyCommand, VerificationLoop, run_verification,
)

PY = sys.executable


# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #

def _task(tmp_path, name="task"):
    task = tmp_path / name
    task.mkdir()
    return task


def _write_config(task, commands, **kw):
    (task / CONFIG_FILENAME).write_text(
        json.dumps({"commands": commands, **kw}), encoding="utf-8")


def _loop(ddir):
    return VerificationLoop(ddir)


# --------------------------------------------------------------------------- #
# VerifyCommand parsing (no shell, ever)
# --------------------------------------------------------------------------- #

def test_verifycommand_rejects_empty_and_non_list():
    with pytest.raises(ValueError):
        VerifyCommand([])
    with pytest.raises(ValueError):
        VerifyCommand("   ")
    with pytest.raises(TypeError):
        VerifyCommand(42)


def test_verifycommand_string_shlex_to_argv():
    c = VerifyCommand("python -m pytest tests -x")
    assert c.argv == ["python", "-m", "pytest", "tests", "-x"]


def test_metacharacters_are_literal_argv_not_shell(tmp_path):
    """`;` and `|` in a token must arrive verbatim - list-form spawn only."""
    out = run_verification(
        [PY, "-c", "import sys; sys.stdout.write(sys.argv[1])", "a;b|c"],
        cwd=tmp_path)
    assert out["ok"] is True
    assert "a;b|c" in out["output_tail"]


# --------------------------------------------------------------------------- #
# run_verification: lint-style - pass
# --------------------------------------------------------------------------- #

def test_lint_pass_good_file(tmp_path):
    good = tmp_path / "good.py"
    good.write_text("X = 1\n", encoding="utf-8")
    v = run_verification(
        [PY, "-c",
         "import py_compile, sys; py_compile.compile(sys.argv[1])",
         str(good)],
        cwd=tmp_path, timeout_s=30)
    assert v["ok"] is True
    assert v["exit_code"] == 0
    assert v["timed_out"] is False
    assert "cmd_display" in v and v["ts"]


# --------------------------------------------------------------------------- #
# run_verification: lint-style - fail (structured stderr tail)
# --------------------------------------------------------------------------- #

def test_lint_fail_bad_file_structured_stderr(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def f(:\n", encoding="utf-8")   # SyntaxError
    v = run_verification(
        [PY, "-c",
         "import py_compile, sys; py_compile.compile(sys.argv[1], "
         "doraise=True)",
         str(bad)],
        cwd=tmp_path, timeout_s=30)
    assert v["ok"] is False
    assert v["exit_code"] != 0
    assert v["timed_out"] is False
    assert "SyntaxError" in v["output_tail"]        # stderr merged, kept


# --------------------------------------------------------------------------- #
# run_verification: pytest-style pass / fail (tiny fixture files)
# --------------------------------------------------------------------------- #

def test_pytest_pass_two_line_fixture(tmp_path):
    t = _task(tmp_path)
    (t / "test_ok.py").write_text("def test_one():\n    assert 1 == 1\n",
                                  encoding="utf-8")
    _write_config(t, [[PY, "-m", "pytest", "-q", "test_ok.py", "-x"]],
                  timeout_s=120)
    res = _loop(tmp_path / "data").attempt("exe-ok", "Verify", task_cwd=t)
    assert res["status"] == "pass"
    assert res["verdicts"][0]["ok"] is True
    assert res["verdicts"][0]["exit_code"] == 0


def test_pytest_fail_two_line_fixture(tmp_path):
    t = _task(tmp_path)
    (t / "test_bad.py").write_text("def test_one():\n    assert 1 == 2\n",
                                   encoding="utf-8")
    _write_config(t, [[PY, "-m", "pytest", "-q", "test_bad.py", "-x"]],
                  timeout_s=120)
    ddir = tmp_path / "data"
    res = _loop(ddir).attempt("exe-bad", "Verify", task_cwd=t)
    assert res["status"] == "fail"
    assert res["failed_cmd"] is not None
    assert res["verdicts"][0]["ok"] is False
    assert "assert" in res["verdicts"][0]["tail"].lower() or "assert" in (
        res["reason"] or "")


# --------------------------------------------------------------------------- #
# run_verification: timeout / huge output / non-UTF-8
# --------------------------------------------------------------------------- #

def test_timeout_kills_and_marks(tmp_path):
    start = __import__("time").perf_counter()
    v = run_verification([PY, "-c", "import time; time.sleep(30)"],
                         cwd=tmp_path, timeout_s=1)
    assert __import__("time").perf_counter() - start < 20
    assert v["timed_out"] is True
    assert v["ok"] is False
    assert v["exit_code"] is None


def test_huge_output_tail_capped(tmp_path):
    v = run_verification(
        [PY, "-c", "import sys; sys.stdout.write('x' * 1_000_000)"],
        cwd=tmp_path, timeout_s=30)
    assert v["ok"] is True
    tail_bytes = v["output_tail"].encode("utf-8", errors="replace")
    assert len(tail_bytes) <= DEFAULT_MAX_OUTPUT
    assert "x" * 50 in v["output_tail"]
    assert v["output_tail"].count("\n") < 5          # tail, not head


def test_non_utf8_output_no_crash_replacement_chars(tmp_path):
    v = run_verification(
        [PY, "-c",
         "import sys; sys.stdout.buffer.write(bytes(range(128, 256)))"],
        cwd=tmp_path, timeout_s=30)
    assert "ok" in v                                    # did not raise
    assert "\ufffd" in v["output_tail"]                 # replacement chars


# --------------------------------------------------------------------------- #
# authorization model (fail closed)
# --------------------------------------------------------------------------- #

def test_arbitrary_cmd_refused_when_gate_disabled(tmp_path):
    """--cmd with gate DISABLED: refusal verdict, NOTHING executed."""
    t = _task(tmp_path)                 # no .harness-verify.json on purpose
    marker = t / "pwned.txt"
    ddir = tmp_path / "data"
    loop = _loop(ddir)
    res = loop.attempt("exe", "Verify", task_cwd=t,
                       explicit_cmd=[PY, "-c",
                                     f"open({str(marker)!r},'w').write('hi')"])
    assert res["status"] == REFUSED
    assert "DISABLED" in res["reason"]
    assert marker.exists() is False                     # no side effect


def test_config_command_allowed_when_gate_disabled(tmp_path):
    """.harness-verify.json is the operator's pre-auth: works gate-free."""
    t = _task(tmp_path)
    marker = t / "marker.txt"
    _write_config(t, [[PY, "-c",
                       f"open({str(marker)!r},'w').write('ok')"]],
                  timeout_s=30)
    ddir = tmp_path / "data"
    loop = _loop(ddir)
    res = loop.attempt("exe", "Verify", task_cwd=t)
    assert res["status"] == "pass"
    assert marker.read_text(encoding="utf-8") == "ok"   # ran because authorized


def test_operator_cmd_requires_token_under_enforce(tmp_path):
    """ENFORCE mode: --cmd matching an enforce pattern needs a one-shot token.

    The trailing "pip publish" tokens make the command's DISPLAY match the
    default enforce pattern (pip publish) while the argv still runs benign
    python. Without a token it is REFUSED before anything executes; with a
    token bound to the exact command it runs.
    """
    t = _task(tmp_path)
    ddir = tmp_path / "data"
    gate.write_config(ddir, mode="enforce")
    marker = t / "mk.txt"
    argv = [PY, "-c", f"open({str(marker)!r},'a').write('x')",
            "pip", "publish"]
    display = VerifyCommand(argv).display

    no_token = _loop(ddir).attempt("exe", "Verify", task_cwd=t,
                                   explicit_cmd=argv)
    assert no_token["status"] == REFUSED
    assert marker.exists() is False                     # nothing executed

    grant = gate.approve_once(ddir, action=display, scope="command", ttl=60)
    with_token = _loop(ddir).attempt("exe", "Verify", task_cwd=t,
                                     explicit_cmd=argv, token=grant["token"])
    assert with_token["status"] == "pass"
    assert marker.read_text(encoding="utf-8") == "x"    # token authorized it


def test_config_command_allowed_under_enforce_without_token(tmp_path):
    """.harness-verify.json is pre-authorization: no token needed even in
    enforce mode - the gate is for operator-typed --cmd, not configs."""
    t = _task(tmp_path)
    ddir = tmp_path / "data"
    gate.write_config(ddir, mode="enforce")
    _write_config(t, [[PY, "-c", "pass"]], timeout_s=30)
    res = _loop(ddir).attempt("exe", "Verify", task_cwd=t)
    assert res["status"] == "pass"


def test_missing_config_and_no_cmd_is_skipped(tmp_path):
    t = _task(tmp_path)
    res = _loop(tmp_path / "data").attempt("exe", "Verify", task_cwd=t)
    assert res["status"] == "skipped"
    assert res["reason"] == "no-verify-config"
    assert _loop(tmp_path / "data").can_claim_done("exe") is False


def test_operator_cmd_allowed_under_audit(tmp_path, capsys):
    """AUDIT mode: --cmd logs and ALLOWS (observation, not protection)."""
    t = _task(tmp_path)
    ddir = tmp_path / "data"
    gate.write_config(ddir, mode="audit")
    marker = t / "mk.txt"
    res = _loop(ddir).attempt(
        "exe", "Verify", task_cwd=t,
        explicit_cmd=[PY, "-c", f"open({str(marker)!r},'w').write('x')"])
    assert res["status"] == "pass"
    assert marker.exists()
    audit = ddir / "gate-audit.jsonl"
    text = audit.read_text(encoding="utf-8")
    assert '"mode": "audit"' in text and "decision" in text


def test_malformed_config_raises_not_skips(tmp_path):
    t = _task(tmp_path)
    (t / CONFIG_FILENAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        _loop(tmp_path / "data").attempt("exe", "Verify", task_cwd=t)
    (t / CONFIG_FILENAME).write_text('{"commands": []}', encoding="utf-8")
    with pytest.raises(ValueError):
        _loop(tmp_path / "data").attempt("exe", "Verify", task_cwd=t)


# --------------------------------------------------------------------------- #
# bounded retry / reflections
# --------------------------------------------------------------------------- #

def test_reflections_exhausted_after_n_attempts(tmp_path):
    t = _task(tmp_path)
    # fails every run, and increments a counter so we can prove NO over-run
    _write_config(t, [[PY, "-c",
                       "import pathlib; pathlib.Path('runs.txt').open('a')."
                       "write('x\\n'); raise SystemExit(1)"]],
                  timeout_s=30, max_reflections=1)
    ddir = tmp_path / "data"
    loop = _loop(ddir)
    first = loop.attempt("exe", "Verify", task_cwd=t)
    assert first["status"] == "fail"
    second = loop.attempt("exe", "Verify", task_cwd=t)
    assert second["status"] == "fail"
    third = loop.attempt("exe", "Verify", task_cwd=t)
    assert third["status"] == EXHAUSTED
    assert third["reflections_exhausted"] is True
    runs = (t / "runs.txt").read_text(encoding="utf-8") if (t / "runs.txt").exists() else ""
    assert runs == "x\nx\n"                             # only 2 real runs
    assert loop.can_claim_done("exe") is False


def test_can_claim_done_false_when_absent():
    assert _loop(Path(__import__("tempfile").gettempdir())
                 / "nh-absent-x").can_claim_done("nope") is False


# --------------------------------------------------------------------------- #
# headline: verification failure blocks done
# --------------------------------------------------------------------------- #

def test_failure_blocks_done_then_fix_passes(tmp_path, monkeypatch):
    # Determinism guard: the two writes below are same-size, and on a fast
    # machine both attempts can land in the SAME second. CPython validates
    # cached bytecode by (mtime-seconds, size), so a stale __pycache__ pyc
    # could otherwise be served for the fixed file and the second attempt
    # would re-run the OLD failing test (seen failing on CI, masked locally
    # by slower process startup straddling a second boundary). Disable
    # bytecode caching for the verify subprocess (env is inherited).
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    t = _task(tmp_path)
    testfile = t / "test_wip.py"
    testfile.write_text("def test_one():\n    assert 2 + 2 == 5\n",
                        encoding="utf-8")
    _write_config(t, [[PY, "-m", "pytest", "-q", "test_wip.py", "-x"]],
                  timeout_s=120)
    ddir = tmp_path / "data"
    loop = _loop(ddir)
    fail = loop.attempt("exe", "Verify", task_cwd=t)
    assert fail["status"] == "fail"
    assert loop.can_claim_done("exe") is False          # BLOCKED

    testfile.write_text("def test_one():\n    assert 2 + 2 == 4\n",
                        encoding="utf-8")               # operator fixes it
    ok = loop.attempt("exe", "Verify", task_cwd=t)
    assert ok["status"] == "pass"
    assert loop.can_claim_done("exe") is True           # UNBLOCKED


# --------------------------------------------------------------------------- #
# checkpoint integration
# --------------------------------------------------------------------------- #

def test_verify_fail_flips_checkpoint_to_failed(tmp_path):
    t = _task(tmp_path)
    (t / "test_f.py").write_text("def test_x():\n    assert False\n",
                                 encoding="utf-8")
    _write_config(t, [[PY, "-m", "pytest", "-q", "test_f.py", "-x"]],
                  timeout_s=120)
    ddir = tmp_path / "data"
    store = CheckpointStore(ddir)
    store.save("exe", "Verify", {"progress": True}, stage_index=5,
               status="started")
    res = _loop(ddir).attempt("exe", "Verify", task_cwd=t)
    assert res["status"] == "fail"
    latest, health = store.load_latest("exe")
    assert health["ok"] is True
    assert latest["status"] == "failed"
    assert latest["payload"]["verify"]["result"] == "fail"


def test_allpass_writes_done_checkpoint(tmp_path):
    t = _task(tmp_path)
    _write_config(t, [[PY, "-c", "pass"]], timeout_s=30)
    ddir = tmp_path / "data"
    loop = _loop(ddir)
    res = loop.attempt("exe", stage="Lint", task_cwd=t)
    assert res["status"] == "pass"
    latest, _health = CheckpointStore(ddir).load_latest("exe")
    assert latest["status"] == "done"
    assert latest["payload"] == {"verify": "ok"}
    assert loop.can_claim_done("exe") is True


# --------------------------------------------------------------------------- #
# evidence integrity (tamper / corruption is never silent ok)
# --------------------------------------------------------------------------- #

def test_corrupt_verdict_line_explicit_health(tmp_path):
    t = _task(tmp_path)
    _write_config(t, [[PY, "-c", "pass"]], timeout_s=30)
    ddir = tmp_path / "data"
    loop = _loop(ddir)
    assert loop.attempt("exe", "Verify", task_cwd=t)["status"] == "pass"
    assert loop.can_claim_done("exe") is True
    log = ddir / "verify" / "exe.jsonl"
    valid = log.read_text(encoding="ascii")
    log.write_text("{not json at all}\n" + valid, encoding="ascii")
    health = loop.health("exe")
    assert health["ok"] is False
    assert health["corrupt_lines"] == [1]               # garbage VERDICT line
    assert loop.can_claim_done("exe") is False          # damage != silent ok


def test_hash_mismatch_detected(tmp_path):
    t = _task(tmp_path)
    _write_config(t, [[PY, "-c", "pass"]], timeout_s=30)
    ddir = tmp_path / "data"
    loop = _loop(ddir)
    loop.attempt("exe", "Verify", task_cwd=t)
    log = ddir / "verify" / "exe.jsonl"
    rec = json.loads(log.read_text(encoding="ascii").splitlines()[0])
    rec["payload"]["result"] = "fail"                   # tampered-but-valid JSON
    log.write_text(json.dumps(rec, ensure_ascii=True) + "\n", encoding="ascii")
    health = loop.health("exe")
    assert health["ok"] is False
    assert health["hash_failures"] == [1]
    assert loop.can_claim_done("exe") is False


# --------------------------------------------------------------------------- #
# record-level guarantees
# --------------------------------------------------------------------------- #

def test_records_are_pure_ascii_and_fsynced(tmp_path):
    t = _task(tmp_path)
    _write_config(t, [[PY, "-c", "pass"]], timeout_s=30)
    ddir = tmp_path / "data"
    loop = _loop(ddir)
    loop.attempt("exe", "Verify", task_cwd=t)
    log = ddir / "verify" / "exe.jsonl"
    raw = log.read_bytes()
    assert all(b < 128 for b in raw)                    # pure ASCII on disk
    rec = json.loads(raw.decode("ascii"))
    assert rec["schema"] == 1
    assert rec["status"] in ("pass", "fail", REFUSED, EXHAUSTED, "skipped")


def test_verify_evidence_never_executes_shell(tmp_path):
    """Module source-level guard: no shell=True anywhere in verify.py."""
    from harness import verify
    src = Path(verify.__file__).read_text(encoding="utf-8")
    assert "shell=True" not in src
    assert "F:\\Claude" not in src                       # no legacy hardcode