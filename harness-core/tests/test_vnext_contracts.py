"""VNext contract tests: experience chain (source/confidence/promote/search),
pattern report, and the three-tier gate. Run: python -m pytest tests/ -q
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import feedback, gate, report as report_mod  # noqa: E402

CLI = str(Path(__file__).resolve().parent.parent / "harness" / "cli.py")
HOOK = str(Path(__file__).resolve().parent.parent.parent / "hooks" / "harness_gate.py")


def _run_hook(tmp_path, payload: dict, env_extra=None) -> subprocess.CompletedProcess:
    env = {**os.environ, "HARNESS_DATA_DIR": str(tmp_path / "data")}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, HOOK], input=json.dumps(payload),
        capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
    )


# ---------- experience chain ----------

def test_record_carries_source_and_confidence(tmp_path):
    # Arrange / Act
    rec = feedback.record(tmp_path, project_id="p1", cause="c", summary="s",
                          source="user-correction", confidence=1.7)
    # Assert: user correction recorded verbatim, confidence clamped to 1.0
    assert rec["source"] == "user-correction"
    assert rec["confidence"] == 1.0
    assert rec["status"] == "candidate"
    rows = feedback.query(tmp_path, project_id="p1")
    assert rows[0]["source"] == "user-correction"


def test_keyword_search_is_case_insensitive_over_summary_and_cause(tmp_path):
    data_dir = tmp_path / "d"
    feedback.record(data_dir, project_id="p1", cause="silent_exit",
                    summary="phase done without verification")
    feedback.record(data_dir, project_id="p1", cause="wrong_assumption",
                    summary="assumed cache invalidated")
    # Act: keyword hits summary of r1 and cause of r2
    hit1 = feedback.query(data_dir, project_id="p1", keyword="VERIFICATION")
    hit2 = feedback.query(data_dir, project_id="p1", keyword="wrong_assum")
    miss = feedback.query(data_dir, project_id="p1", keyword="nonexistent")
    assert [r["failure_cause"] for r in hit1] == ["silent_exit"]
    assert [r["failure_cause"] for r in hit2] == ["wrong_assumption"]
    assert miss == []


def test_promote_flow_is_append_only_and_last_write_wins(tmp_path):
    data_dir = tmp_path / "d"
    rec = feedback.record(data_dir, project_id="p1", cause="c", summary="s")
    # Act: candidate -> verified -> promoted -> retired
    feedback.promote(data_dir, project_id="p1", record_id=rec["record_id"], status="verified")
    feedback.promote(data_dir, project_id="p1", record_id=rec["record_id"], status="promoted")
    assert [r["record_id"] for r in feedback.promoted(data_dir, project_id="p1")] == [rec["record_id"]]
    feedback.promote(data_dir, project_id="p1", record_id=rec["record_id"], status="retired")
    assert feedback.promoted(data_dir, project_id="p1") == []
    # original record line untouched (append-only store)
    assert feedback.query(data_dir, project_id="p1")[0]["status"] == "candidate"


def test_promote_rejects_unknown_record_and_bad_status(tmp_path):
    data_dir = tmp_path / "d"
    feedback.record(data_dir, project_id="p1", cause="c", summary="s")
    for bad in ({"record_id": "fb-nope", "status": "promoted"},
                {"record_id": None, "status": "banana"}):
        try:
            rid = bad["record_id"] or "fb-whatever"
            feedback.promote(data_dir, project_id="p1", record_id=rid, status=bad["status"])
            raise AssertionError("should have raised")
        except ValueError:
            pass


# ---------- report ----------

def test_report_flags_recurring_cause_with_proposal(tmp_path):
    data_dir = tmp_path / "d"
    for i in range(3):
        feedback.record(data_dir, project_id="p1", cause="silent_exit",
                        summary=f"run {i} done without evidence")
    feedback.record(data_dir, project_id="p1", cause="one_off", summary="x")
    # Act
    rep = report_mod.report(data_dir, project_id="p1", min_count=2)
    # Assert
    assert rep["total_records"] == 4
    assert len(rep["recurring"]) == 1
    r = rep["recurring"][0]
    assert r["cause"] == "silent_exit" and r["count"] == 3
    assert r["proposal"] and "promote" in r["proposal"]
    assert r["already_promoted"] is False
    # once promoted, proposal disappears
    rec = feedback.query(data_dir, project_id="p1", keyword="run 2")[0]
    feedback.promote(data_dir, project_id="p1", record_id=rec["record_id"], status="promoted")
    rep2 = report_mod.report(data_dir, project_id="p1", min_count=2)
    assert rep2["recurring"][0]["already_promoted"] is True
    assert rep2["recurring"][0]["proposal"] is None


# ---------- gate: three-tier semantics ----------

def _cfg(tmp_path, mode):
    data_dir = tmp_path / "data"
    gate.write_config(data_dir, mode=mode)
    return data_dir


def test_gate_disabled_allows_everything_and_logs_nothing(tmp_path):
    data_dir = _cfg(tmp_path, "disabled")
    r = gate.evaluate(data_dir, "git push origin main")
    assert r["decision"] == "allow" and r["mode"] == "disabled"


def test_gate_audit_logs_but_never_blocks(tmp_path):
    data_dir = _cfg(tmp_path, "audit")
    r = gate.evaluate(data_dir, "git push origin main")
    # Assert: decision is explicitly audit — proceed + logged, NOT protection
    assert r["decision"] == "audit" and r["matched"]
    gate.log_decision(data_dir, mode=r["mode"], decision=r["decision"],
                      command="git push origin main", matched=r["matched"])
    log = (data_dir / "gate-audit.jsonl").read_text(encoding="utf-8")
    assert '"decision": "audit"' in log


def test_gate_enforce_blocks_unapproved_and_allows_after_approval(tmp_path):
    data_dir = _cfg(tmp_path, "enforce")
    # Act 1: no approval -> block
    r1 = gate.evaluate(data_dir, "git push origin main")
    assert r1["decision"] == "block"
    # Act 2: human approves pattern -> allow
    gate.approve(data_dir, pattern=r"git push.*", ttl=600)
    r2 = gate.evaluate(data_dir, "git push origin main")
    assert r2["decision"] == "allow" and r2.get("reason") == "valid approval"
    # Act 3: approval expired -> block again
    r3 = gate.evaluate(data_dir, "git push origin main", now=time.time() + 601)
    assert r3["decision"] == "block"
    # unmatched command never blocked
    assert gate.evaluate(data_dir, "pytest tests/")["decision"] == "allow"


def test_gate_enforce_fails_closed_when_config_unreadable(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "gate.json").write_text("{not json", encoding="utf-8")
    r = gate.evaluate(data_dir, "git push origin main", mode_override="enforce")
    assert r["decision"] == "block-error"
    assert "fail closed" in r["reason"]


# ---------- hook end-to-end (simulated, no real dangerous commands run) ----------

def test_hook_blocks_git_push_in_enforce_and_passes_in_audit(tmp_path):
    _cfg(tmp_path, "enforce")
    payload = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
    # enforce: exit 2 with explanation on stderr
    r1 = _run_hook(tmp_path, payload)
    assert r1.returncode == 2 and "ENFORCE" in r1.stderr
    # audit: same command passes (exit 0), decision logged
    _cfg(tmp_path, "audit")
    r2 = _run_hook(tmp_path, payload)
    assert r2.returncode == 0
    assert "git push" in (tmp_path / "data" / "gate-audit.jsonl").read_text(encoding="utf-8")


def test_hook_ignores_non_bash_and_safe_commands(tmp_path):
    _cfg(tmp_path, "enforce")
    r1 = _run_hook(tmp_path, {"tool_name": "Edit", "tool_input": {"file_path": "x"}})
    r2 = _run_hook(tmp_path, {"tool_name": "Bash", "tool_input": {"command": "pytest -q"}})
    r3 = _run_hook(tmp_path, {"tool_name": "Bash", "tool_input": {"command": ""}})
    assert (r1.returncode, r2.returncode, r3.returncode) == (0, 0, 0)


def test_cli_gate_check_and_report_roundtrip(tmp_path):
    env = {**os.environ, "HARNESS_DATA_DIR": str(tmp_path / "data")}
    def run(*args):
        return subprocess.run([sys.executable, CLI, *args],
                              capture_output=True, text=True, env=env,
                              cwd=tmp_path, timeout=60)
    # Arrange: set enforce, record recurring cause
    assert run("gate", "mode", "--set", "enforce").returncode == 0
    out = json.loads(run("gate", "check", "git push").stdout)
    assert out["decision"] == "block"
    for i in range(2):
        run("feedback", "record", "--cause", "cache_stale", "--summary", f"stale {i}",
            "--source", "user-correction", "--project-id", "p1")
    rep = json.loads(run("report", "--project-id", "p1").stdout)
    assert rep["recurring"][0]["cause"] == "cache_stale"
    assert "user-correction" in rep["recurring"][0]["sources"]


def test_experiment_seed_source_roundtrip(tmp_path):
    """experiment-seed records: writable, queryable, clearly marked synthetic."""
    rec = feedback.record(tmp_path, project_id="p1", cause="stale_cache",
                          summary="synthetic fixture", source="experiment-seed",
                          confidence=1.0)
    assert rec["source"] == "experiment-seed"
    hits = feedback.query(tmp_path, project_id="p1", keyword="stale_cache")
    assert [h["record_id"] for h in hits] == [rec["record_id"]]
    assert hits[0]["source"] == "experiment-seed"
