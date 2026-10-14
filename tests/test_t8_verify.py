"""Offline contracts for the t8-log-pipeline-resume verifier.

Locks the t8.1 verifier semantics established by the batch-5 forensics
(2026-10-14, three real paid arms on frozen workspaces):

- native arm: recorded checkpoint hashes were byte-correct but UPPERCASE
  (Windows `certutil -hashfile` output) — hex case carries no semantics,
  the comparison is case-insensitive (t8.1 fix).
- ecc arm: PIPELINE_STATE.json carried a UTF-8 BOM (Windows PowerShell
  `Out-File` default) — the JSON payload is semantically identical, the
  checkpoint file is read as utf-8-sig (t8.1 fix).
- fusion arm: the recorded render hash was genuinely corrupted (30 hex
  chars, real mismatch) — an honest agent failure that MUST stay FAIL.
"""
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TASK = REPO / "tools" / "bench" / "tasks" / "t8-log-pipeline-resume"


def _load_verify():
    spec = importlib.util.spec_from_file_location("t8_verify", TASK / "verify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def verify():
    return _load_verify()


def _render_report(stats: dict) -> str:
    s = stats
    lines = ["# Endpoint Report",
             f"total: {s['total_lines']} lines, {s['parsed']} parsed, {s['skipped']} skipped",
             "",
             "| path | count | error_rate | p50_ms | max_ms |",
             "|---|---|---|---|---|"]
    order = sorted(s["endpoints"], key=lambda p: (-s["endpoints"][p]["count"], p))
    for p in order:
        e = s["endpoints"][p]
        lines.append(f"| {p} | {e['count']} | {e['error_rate'] * 100:.1f}% | {e['p50_ms']} | {e['max_ms']} |")
    err_eps = [(p, e) for p, e in s["endpoints"].items() if e["errors"] > 0]
    if err_eps:
        top = min(err_eps, key=lambda pe: (-pe[1]["error_rate"], -pe[1]["count"], pe[0]))
        lines += ["", f"top error endpoint: {top[0]} ({top[1]['error_rate'] * 100:.1f}%)"]
    else:
        lines += ["", "top error endpoint: none"]
    return "\n".join(lines) + "\n"


def _build_ws(tmp_path: Path, verify) -> Path:
    """Materialize a fully-correct workspace (golden outputs + truthful checkpoint)."""
    ws = tmp_path / "ws"
    (ws / "logs").mkdir(parents=True)
    (ws / "out").mkdir()
    shutil.copy(TASK / "seed" / "logs" / "raw.log", ws / "logs" / "raw.log")
    lines = (ws / "logs" / "raw.log").read_text(encoding="utf-8").splitlines()
    recs, stats = verify._oracle(lines)

    (ws / "out" / "records.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8", newline="")
    (ws / "out" / "stats.json").write_text(json.dumps(stats), encoding="utf-8", newline="")
    (ws / "report.md").write_text(_render_report(stats), encoding="utf-8", newline="")

    def _sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    state = {"stages": [
        {"name": "parse", "output": "out/records.jsonl",
         "sha256": _sha(ws / "out" / "records.jsonl"), "rows": stats["parsed"]},
        {"name": "aggregate", "output": "out/stats.json",
         "sha256": _sha(ws / "out" / "stats.json"), "rows": len(stats["endpoints"])},
        {"name": "render", "output": "report.md",
         "sha256": _sha(ws / "report.md"), "rows": None},
    ]}
    (ws / "PIPELINE_STATE.json").write_text(json.dumps(state), encoding="utf-8", newline="")
    return ws


def _run(verify, ws, monkeypatch):
    # verify.ROOT is a module-level constant frozen at import time (cwd then);
    # pin it to the workspace instead of relying on chdir.
    monkeypatch.setattr(verify, "ROOT", ws)
    return verify.main()


def test_golden_workspace_passes(verify, tmp_path, monkeypatch, capsys):
    ws = _build_ws(tmp_path, verify)
    assert _run(verify, ws, monkeypatch) == 0
    assert "VERIFY PASS" in capsys.readouterr().out


def test_uppercase_recorded_hash_accepted(verify, tmp_path, monkeypatch):
    """native-arm class: certutil emits uppercase hex — semantically identical."""
    ws = _build_ws(tmp_path, verify)
    st = json.loads((ws / "PIPELINE_STATE.json").read_text(encoding="utf-8"))
    for g in st["stages"]:
        g["sha256"] = g["sha256"].upper()
    (ws / "PIPELINE_STATE.json").write_text(json.dumps(st), encoding="utf-8", newline="")
    assert _run(verify, ws, monkeypatch) == 0


def test_bom_checkpoint_accepted(verify, tmp_path, monkeypatch):
    """ecc-arm class: PowerShell Out-File writes UTF-8 BOM by default."""
    ws = _build_ws(tmp_path, verify)
    p = ws / "PIPELINE_STATE.json"
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    assert _run(verify, ws, monkeypatch) == 0


def test_corrupted_recorded_hash_rejected(verify, tmp_path, monkeypatch, capsys):
    """fusion-arm class: a genuinely corrupted recorded hash (30 chars, real
    mismatch) is an honest agent failure and MUST stay FAIL."""
    ws = _build_ws(tmp_path, verify)
    st = json.loads((ws / "PIPELINE_STATE.json").read_text(encoding="utf-8"))
    st["stages"][2]["sha256"] = st["stages"][2]["sha256"][:24] + "b19129"  # 30 chars, wrong
    (ws / "PIPELINE_STATE.json").write_text(json.dumps(st), encoding="utf-8", newline="")
    assert _run(verify, ws, monkeypatch) == 1
    assert "sha256 stale for stage render" in capsys.readouterr().out


def test_stale_checkpoint_rejected(verify, tmp_path, monkeypatch, capsys):
    """Output rewritten with equal JSON but different bytes → recorded hash stale."""
    ws = _build_ws(tmp_path, verify)
    sp = ws / "out" / "stats.json"
    sp.write_text(sp.read_text(encoding="utf-8") + "\n", encoding="utf-8", newline="")
    assert _run(verify, ws, monkeypatch) == 1
    assert "sha256 stale for stage aggregate" in capsys.readouterr().out


def test_pristine_seed_fails_right_reason(verify, tmp_path, monkeypatch, capsys):
    ws = tmp_path / "ws"
    (ws / "logs").mkdir(parents=True)
    shutil.copy(TASK / "seed" / "logs" / "raw.log", ws / "logs" / "raw.log")
    assert _run(verify, ws, monkeypatch) == 1
    assert "VERIFY FAIL" in capsys.readouterr().out


def test_tampered_raw_log_rejected(verify, tmp_path, monkeypatch, capsys):
    ws = _build_ws(tmp_path, verify)
    rp = ws / "logs" / "raw.log"
    rp.write_bytes(rp.read_bytes() + b"\n")
    assert _run(verify, ws, monkeypatch) == 1
    assert "input is pinned" in capsys.readouterr().out


def test_wrong_rows_rejected(verify, tmp_path, monkeypatch, capsys):
    ws = _build_ws(tmp_path, verify)
    st = json.loads((ws / "PIPELINE_STATE.json").read_text(encoding="utf-8"))
    st["stages"][0]["rows"] += 1
    (ws / "PIPELINE_STATE.json").write_text(json.dumps(st), encoding="utf-8", newline="")
    assert _run(verify, ws, monkeypatch) == 1
    assert "rows wrong for stage parse" in capsys.readouterr().out
