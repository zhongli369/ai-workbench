"""One-time approval token contracts (P1.3, adapted from WorkFlow's
approval_token_store semantics — single-use, TTL, scope-bound, replay-safe).

Semantics under test:
  - token printed once at grant; only SHA-256 stored
  - exact-command scope (whitespace-normalized) and regex-fullmatch scope
  - replay / expiry / scope mismatch / unknown token: distinct denials
  - atomic concurrent consumption: N racers, exactly one consumes
  - lock timeout and corrupt store fail CLOSED (block-error in enforce)
  - AUDIT mode never consults tokens (no validation, no consumption)
  - raw token never lands in the audit log (12-char hash prefix only)
  - legacy multi-use pattern approvals keep working unchanged
"""
import json
import sys
import threading
import time
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


def _grant(ddir, action="git push origin main", **kw):
    return gate.approve_once(ddir, action=action, **kw)


# ---- grant / storage --------------------------------------------------------

def test_token_format_and_only_hash_stored(ddir):
    g = _grant(ddir)
    assert g["token"].startswith("awt-") and len(g["token"]) == 4 + 48
    stored = (ddir / "gate-tokens.jsonl").read_text(encoding="utf-8")
    assert g["token"] not in stored
    entry = json.loads(stored.strip())
    assert entry["type"] == "grant" and len(entry["token_hash"]) == 64


def test_grant_validates_pattern_scope(ddir):
    with pytest.raises(Exception):
        gate.approve_once(ddir, action="git push (", scope="pattern")


# ---- happy path --------------------------------------------------------------

def test_token_allows_bound_command(ddir):
    g = _grant(ddir)
    r = gate.evaluate(ddir, "git push origin main", token=g["token"])
    assert r["decision"] == "allow" and r["reason"] == "token consumed"


def test_command_scope_normalizes_whitespace(ddir):
    g = _grant(ddir, action="git  push   origin main")
    r = gate.evaluate(ddir, "git push origin main", token=g["token"])
    assert r["decision"] == "allow"


def test_pattern_scope_fullmatch(ddir):
    g = _grant(ddir, action=r"git push origin \w+", scope="pattern")
    ok = gate.evaluate(ddir, "git push origin main", token=g["token"])
    assert ok["decision"] == "allow"
    g2 = _grant(ddir, action=r"git push origin \w+", scope="pattern")
    # fullmatch, not search: extra suffix must NOT match
    no = gate.evaluate(ddir, "git push origin main --force", token=g2["token"])
    assert no["decision"] == "block" and no["reason"] == "token scope mismatch"


# ---- denials ------------------------------------------------------------------

def test_replay_rejected(ddir):
    g = _grant(ddir)
    first = gate.evaluate(ddir, "git push origin main", token=g["token"])
    second = gate.evaluate(ddir, "git push origin main", token=g["token"])
    assert first["decision"] == "allow"
    assert second["decision"] == "block" and second["reason"] == "token already used"


def test_expired_token_rejected(ddir):
    g = gate.approve_once(ddir, action="git push origin main", ttl=5)
    future = time.time() + 10
    r = gate.evaluate(ddir, "git push origin main", token=g["token"], now=future)
    assert r["decision"] == "block" and r["reason"] == "token expired"


def test_wrong_action_rejected_and_not_consumed(ddir):
    g = _grant(ddir, action="git push origin main")
    wrong = gate.evaluate(ddir, "git push origin other", token=g["token"])
    assert wrong["decision"] == "block" and wrong["reason"] == "token scope mismatch"
    # mismatch must NOT consume: the bound command still works
    right = gate.evaluate(ddir, "git push origin main", token=g["token"])
    assert right["decision"] == "allow"


def test_unknown_token_rejected(ddir):
    r = gate.evaluate(ddir, "git push origin main", token="awt-" + "0" * 48)
    assert r["decision"] == "block" and r["reason"] == "unknown token"


# ---- atomicity -----------------------------------------------------------------

def test_concurrent_consumption_exactly_one_wins(ddir):
    g = _grant(ddir)
    results = []
    barrier = threading.Barrier(8)

    def race():
        barrier.wait()
        results.append(gate.evaluate(ddir, "git push origin main",
                                     token=g["token"])["decision"])

    threads = [threading.Thread(target=race) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("allow") == 1
    assert results.count("block") == 7


def test_lock_timeout_fails_closed(ddir, monkeypatch):
    monkeypatch.setattr(gate, "_TOKENS_LOCK_TIMEOUT", 0.15)
    (ddir / "gate-tokens.lock").write_text("held", encoding="utf-8")  # stale lock
    g = _grant(ddir)
    r = gate.evaluate(ddir, "git push origin main", token=g["token"])
    assert r["decision"] == "block-error"
    assert "lock timeout" in r["reason"]


def test_corrupt_store_fails_closed(ddir):
    g = _grant(ddir)
    with open(ddir / "gate-tokens.jsonl", "a", encoding="utf-8") as f:
        f.write("{not json\n")
    r = gate.evaluate(ddir, "git push origin main", token=g["token"])
    assert r["decision"] == "block-error"
    assert "corrupt" in r["reason"]


# ---- mode semantics -------------------------------------------------------------

def test_audit_mode_never_consults_tokens(ddir):
    gate.write_config(ddir, mode="audit")
    g = _grant(ddir)
    r = gate.evaluate(ddir, "git push origin main", token=g["token"])
    assert r["decision"] == "audit"
    # token NOT consumed in audit: still valid for a later enforce use
    gate.write_config(ddir, mode="enforce")
    r2 = gate.evaluate(ddir, "git push origin main", token=g["token"])
    assert r2["decision"] == "allow"


def test_disabled_mode_ignores_tokens(ddir):
    gate.write_config(ddir, mode="disabled")
    g = _grant(ddir)
    assert gate.evaluate(ddir, "git push origin main", token=g["token"])["decision"] == "allow"


def test_no_token_still_blocks(ddir):
    r = gate.evaluate(ddir, "git push origin main")
    assert r["decision"] == "block" and "reason" not in r


def test_legacy_pattern_approval_still_works(ddir):
    gate.approve(ddir, pattern=r"git push.*", ttl=600)
    r = gate.evaluate(ddir, "git push origin main")
    assert r["decision"] == "allow" and r["reason"] == "valid approval"


# ---- audit hygiene ----------------------------------------------------------------

def test_audit_log_never_contains_raw_token(ddir):
    g = _grant(ddir)
    gate.evaluate(ddir, "git push origin main", token=g["token"])
    gate.log_decision(ddir, mode="enforce", decision="allow",
                      command="git push origin main", matched="x",
                      token_hash=gate._hash_token(g["token"]))
    log_text = (ddir / "gate-audit.jsonl").read_text(encoding="utf-8")
    assert g["token"] not in log_text
    entry = json.loads(log_text.strip())
    assert len(entry["token"]) == 12
