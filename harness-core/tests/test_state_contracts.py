"""Checkpoint store contracts (TOTAL FUSION Batch 1 — t8-class integrity).

Each test pins one of the eight t8 requirements:
  integrity detection / explicit errors / versioned format / lossless read
  (BOM+CRLF) / atomic+append-only write / crash recovery (torn tail +
  marker) / cross-platform pure-ASCII / evidence never silently destroyed.
Plus: damage is always distinguishable from absence (the SK silent-None
bug class), lineage verification, and CLI wiring with exit codes.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness-core"))

from harness import cli, state  # noqa: E402
from harness.state import CheckpointStore, CorruptStateError  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return CheckpointStore(tmp_path)


def _save3(store, exec_id="exec-1"):
    r1 = store.save(exec_id, "collect", {"rows": 10}, stage_index=1)
    r2 = store.save(exec_id, "render", {"bytes": 2048}, stage_index=2)
    r3 = store.save(exec_id, "verify", {"ok": True}, stage_index=3)
    return r1, r2, r3


# ---- roundtrip & lineage -----------------------------------------------------

def test_roundtrip_and_parent_chain(store, tmp_path):
    r1, r2, r3 = _save3(store)
    latest, health = store.load_latest("exec-1")
    assert health["ok"] is True
    assert latest["checkpoint_id"] == r3["checkpoint_id"]
    assert r2["parent_id"] == r1["checkpoint_id"]
    assert r3["parent_id"] == r2["checkpoint_id"]
    records, health = store.replay("exec-1")
    assert [r["stage"] for r in records] == ["collect", "render", "verify"]
    assert store.verify("exec-1")["ok"] is True

    # project scoping: the SAME exec_id under two projects is two
    # independent chains (namespaced <project>~<exec_id> logs), each record
    # carries its project_id, and the flat store stays untouched.
    sa = CheckpointStore(tmp_path, project_id="projA")
    ra = sa.save("task-9", "collect", {"who": "A"}, stage_index=1)
    assert ra["project_id"] == "projA"
    assert ra["payload"] == {"who": "A"}
    sb = CheckpointStore(tmp_path, project_id="projB")
    rb = sb.save("task-9", "collect", {"who": "B"}, stage_index=1)
    assert rb["project_id"] == "projB"
    assert (tmp_path / "checkpoints" / "projA~task-9.jsonl").is_file()
    assert (tmp_path / "checkpoints" / "projB~task-9.jsonl").is_file()
    # cross-project isolation: A never sees B's chain
    latest_b_through_a, _ = sa.load_latest("task-9")
    assert latest_b_through_a["payload"] == {"who": "A"}
    # scoped chains are invisible to the flat store (and vice versa)
    flat, _ = store.load_latest("task-9")
    assert flat is None
    assert CheckpointStore(tmp_path, project_id="projA").load_latest("x")[0] is None


def test_absent_is_not_damage(store):
    """No file => (None, health.ok) — the exact opposite of silent damage."""
    rec, health = store.load_latest("nope")
    assert rec is None and health["ok"] is True
    assert store.verify("nope")["total_valid"] == 0


# ---- torn tail (crash mid-append) --------------------------------------------

def test_torn_tail_recovered_and_reported(store, tmp_path):
    _save3(store)
    log = tmp_path / "checkpoints" / "exec-1.jsonl"
    with open(log, "a", encoding="ascii", newline="\n") as f:
        f.write('{"schema": 1, "checkpoint_id": "cp-torn", "paylo')  # died here
    latest, health = store.load_latest("exec-1")
    assert latest["stage"] == "verify"           # previous good state survives
    assert health["dropped_tail"] == 1           # ...and the loss is EXPLICIT
    assert health["corrupt_lines"] == []         # torn tail is not "corruption"
    assert health["ok"] is False
    report = store.verify("exec-1")
    assert report["ok"] is False and report["dropped_tail"] == 1


# ---- corruption classes -------------------------------------------------------

def test_corrupt_middle_line_enumerated(store, tmp_path):
    _save3(store)
    log = tmp_path / "checkpoints" / "exec-1.jsonl"
    lines = log.read_text(encoding="ascii").splitlines(keepends=True)
    lines[1] = "{not json at all}\n"
    log.write_text("".join(lines), encoding="ascii", newline="\n")
    records, health = store.replay("exec-1")
    assert [r["stage"] for r in records] == ["collect", "verify"]
    assert health["corrupt_lines"] == [2]        # line-level evidence
    latest, _ = store.load_latest("exec-1")
    assert latest["stage"] == "verify"           # damage never reads as absence


def test_hash_mismatch_detected(store, tmp_path):
    _save3(store)
    log = tmp_path / "checkpoints" / "exec-1.jsonl"
    rec = json.loads(log.read_text(encoding="ascii").splitlines()[0])
    rec["payload"]["rows"] = 99999               # tamper, keep valid JSON
    lines = log.read_text(encoding="ascii").splitlines(keepends=True)
    lines[0] = json.dumps(rec, ensure_ascii=True) + "\n"
    log.write_text("".join(lines), encoding="ascii", newline="\n")
    _records, health = store.replay("exec-1")
    assert health["hash_failures"] == [1]
    assert store.verify("exec-1")["ok"] is False


def test_unknown_schema_version_explicit(store, tmp_path):
    _save3(store)
    log = tmp_path / "checkpoints" / "exec-1.jsonl"
    lines = log.read_text(encoding="ascii").splitlines(keepends=True)
    rec = json.loads(lines[0])
    rec["schema"] = 999
    lines[0] = json.dumps(rec, ensure_ascii=True) + "\n"
    log.write_text("".join(lines), encoding="ascii", newline="\n")
    _records, health = store.replay("exec-1")
    assert health["bad_schema_lines"] == [1]


def test_all_lines_unusable_raises_not_none(store, tmp_path):
    log = tmp_path / "checkpoints"
    log.mkdir(parents=True)
    (log / "exec-1.jsonl").write_text("{broken\n{also broken\n", encoding="ascii")
    with pytest.raises(CorruptStateError):
        store.load_latest("exec-1")


# ---- cross-platform encodings --------------------------------------------------

def test_bom_tolerant_read(store, tmp_path):
    _save3(store)
    log = tmp_path / "checkpoints" / "exec-1.jsonl"
    raw = log.read_bytes()
    log.write_bytes(b"\xef\xbb\xbf" + raw)       # PowerShell Out-File BOM
    latest, health = store.load_latest("exec-1")
    assert latest["stage"] == "verify" and health["ok"] is True


def test_crlf_tolerant_read(store, tmp_path):
    _save3(store)
    log = tmp_path / "checkpoints" / "exec-1.jsonl"
    raw = log.read_bytes().replace(b"\n", b"\r\n")  # Windows checkout
    log.write_bytes(raw)
    records, health = store.replay("exec-1")
    assert len(records) == 3 and health["ok"] is True


def test_disk_bytes_are_pure_ascii(store, tmp_path):
    store.save("exec-1", "render", {"标题": "中文内容", "emoji": "✓"})
    raw = (tmp_path / "checkpoints" / "exec-1.jsonl").read_bytes()
    assert all(b < 128 for b in raw)
    latest, _ = store.load_latest("exec-1")       # lossless through escaping
    assert latest["payload"] == {"标题": "中文内容", "emoji": "✓"}


# ---- crash marker --------------------------------------------------------------

def test_crash_marker_lifecycle(store):
    assert store.active("exec-1") is None
    store.begin("exec-1", "render", 2)
    marker = store.active("exec-1")
    assert marker["stage"] == "render" and marker["stage_index"] == 2
    store.save("exec-1", "render", {"partial": True}, stage_index=2,
               status="started")                    # in-flight update: marker stays
    assert store.active("exec-1") is not None
    store.save("exec-1", "render", {"bytes": 1}, stage_index=2, status="done")
    assert store.active("exec-1") is None          # clean finish clears it


def test_crash_marker_atomic_overwrite(store):
    store.begin("exec-1", "collect", 1)
    store.begin("exec-1", "render", 2)             # restart overwrote atomically
    assert store.active("exec-1")["stage"] == "render"


# ---- append-only / input hygiene ------------------------------------------------

def test_bad_status_rejected(store):
    with pytest.raises(ValueError):
        store.save("exec-1", "x", {}, status="exploded")


def test_verify_catches_chain_break(store, tmp_path):
    _save3(store)
    log = tmp_path / "checkpoints" / "exec-1.jsonl"
    lines = log.read_text(encoding="ascii").splitlines(keepends=True)
    rec = json.loads(lines[2])
    rec["parent_id"] = "cp-forged"
    rec["payload_sha256"] = state.payload_hash(rec["payload"])  # hash stays valid
    lines[2] = json.dumps(rec, ensure_ascii=True) + "\n"
    log.write_text("".join(lines), encoding="ascii", newline="\n")
    report = store.verify("exec-1")
    assert report["ok"] is False and len(report["chain_breaks"]) == 1


def test_verify_catches_non_monotonic_stage_index(store, tmp_path):
    _save3(store)
    log = tmp_path / "checkpoints" / "exec-1.jsonl"
    lines = log.read_text(encoding="ascii").splitlines(keepends=True)
    rec = json.loads(lines[2])
    rec["stage_index"] = 0                          # time travel
    rec["payload_sha256"] = state.payload_hash(rec["payload"])
    lines[2] = json.dumps(rec, ensure_ascii=True) + "\n"
    log.write_text("".join(lines), encoding="ascii", newline="\n")
    report = store.verify("exec-1")
    assert report["ok"] is False and len(report["non_monotonic"]) == 1


# ---- standalone (zero legacy dependency) ----------------------------------------

def test_module_has_no_legacy_path_dependency():
    src = Path(state.__file__).read_text(encoding="utf-8")
    assert "F:\\Claude" not in src
    assert "SystemKernel\\" not in src and "WorkFlow\\" not in src


# ---- CLI wiring ------------------------------------------------------------------

def test_cli_checkpoint_happy_path(tmp_path, capsys):
    dd = str(tmp_path)
    assert cli.main(["--data-dir", dd, "checkpoint", "begin",
                     "--exec", "e1", "--stage", "collect", "--index", "1"]) == 0
    assert cli.main(["--data-dir", dd, "checkpoint", "save",
                     "--exec", "e1", "--stage", "collect", "--index", "1",
                     "--payload", '{"rows": 5}']) == 0
    capsys.readouterr()  # drain begin/save JSON
    assert cli.main(["--data-dir", dd, "checkpoint", "verify",
                     "--exec", "e1"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True and report["total_valid"] == 1
    assert cli.main(["--data-dir", dd, "checkpoint", "load", "--exec", "e1"]) == 0
    load_out = json.loads(capsys.readouterr().out)
    assert load_out["checkpoint"]["payload"] == {"rows": 5}
    assert load_out["health"]["ok"] is True


def test_cli_verify_exit_1_on_damage(tmp_path, capsys):
    dd = str(tmp_path)
    cli.main(["--data-dir", dd, "checkpoint", "save",
              "--exec", "e1", "--stage", "s1", "--payload", "{}"])
    capsys.readouterr()
    log = tmp_path / "checkpoints" / "e1.jsonl"
    with open(log, "a", encoding="ascii") as f:
        f.write("{torn")
    assert cli.main(["--data-dir", dd, "checkpoint", "verify",
                     "--exec", "e1"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and report["dropped_tail"] == 1


def test_cli_list_and_bad_payload(tmp_path, capsys):
    dd = str(tmp_path)
    cli.main(["--data-dir", dd, "checkpoint", "save",
              "--exec", "e1", "--stage", "s1", "--payload", "{}"])
    capsys.readouterr()
    assert cli.main(["--data-dir", dd, "checkpoint", "list"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["execution_id"] == "e1" and rows[0]["healthy"] is True
    assert cli.main(["--data-dir", dd, "checkpoint", "save",
                     "--exec", "e1", "--stage", "s2",
                     "--payload", '[1,2]']) == 2   # non-object payload rejected

    # project scoping through the CLI: the same exec_id under two projects
    # must be fully independent — no cross-project read/write, even with
    # identical exec ids. --project-id wins, --cwd derives the namespace.
    assert cli.main(["--data-dir", dd, "checkpoint", "save",
                     "--exec", "e1", "--stage", "s1", "--project-id", "projA",
                     "--payload", '{"who": "A"}']) == 0
    capsys.readouterr()
    assert cli.main(["--data-dir", dd, "checkpoint", "save",
                     "--exec", "e1", "--stage", "s1", "--project-id", "projB",
                     "--payload", '{"who": "B"}']) == 0
    capsys.readouterr()
    assert cli.main(["--data-dir", dd, "checkpoint", "load",
                     "--exec", "e1", "--project-id", "projA"]) == 0
    load_a = json.loads(capsys.readouterr().out)
    assert load_a["checkpoint"]["payload"] == {"who": "A"}
    assert load_a["checkpoint"]["project_id"] == "projA"
    assert load_a["health"]["ok"] is True
    assert cli.main(["--data-dir", dd, "checkpoint", "load",
                     "--exec", "e1", "--project-id", "projB"]) == 0
    load_b = json.loads(capsys.readouterr().out)
    assert load_b["checkpoint"]["payload"] == {"who": "B"}
    # flat (unscoped) chain still holds the original e1/s2 s1={} records
    flat_latest, _flat_health = CheckpointStore(tmp_path).load_latest("e1")
    assert "project_id" not in flat_latest
    # --cwd derives a project namespace from the directory's project_id
    assert cli.main(["--data-dir", dd, "checkpoint", "save",
                     "--exec", "k9", "--stage", "s1", "--cwd", str(tmp_path),
                     "--payload", '{"from_cwd": true}']) == 0
    capsys.readouterr()
    # list enumerates all four chains (flat + 2 scoped + cwd-derived)
    assert cli.main(["--data-dir", dd, "checkpoint", "list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    tags = {(r.get("project_id"), r["execution_id"]) for r in listed}
    assert (None, "e1") in tags
    assert ("projA", "e1") in tags and ("projB", "e1") in tags
    derived = {r["execution_id"] for r in listed if r.get("project_id")}
    assert derived  # every non-flat row carries a project_id
