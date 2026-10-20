"""Deterministic, offline, zero-LLM correctness bench for the RC tree.

Promoted from the R2 round-2 Agent D benchmark (arms 1-3, 20 assertion cases):
  ARM 1  Gate correctness   — black-box pytest reuse of the gate contract
                              assets + REAL PreToolUse hook E2E (Bash/PowerShell
                              benign/danger/expansion-bypass/one-shot token).
  ARM 2  Verify correctness — real `verify run` CLI: pass/fail/timeout,
                              max_reflections clamping, budget exhaustion.
  ARM 3  Checkpoint recovery– real `checkpoint` CLI: healthy chain, torn tail,
                              payload tamper, schema mismatch, all-unusable.

Stdlib only. Runs against THIS checkout (REPO derived from __file__), never the
installed payload. All fixtures/data are written under RESULTS (default
tools/bench/results/deterministic — gitignored); project fixture dirs are
read-only inputs.

Exit code 0 when every assertion-bearing arm passes; 1 otherwise.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
assert (REPO / "tools" / "bench").is_dir(), f"unexpected repo layout: {REPO}"
CLI = REPO / "harness-core" / "harness" / "cli.py"
HOOK_GATE = REPO / "hooks" / "harness_gate.py"
TESTS = REPO / "harness-core" / "tests"

PY = sys.executable
# Output stays OUTSIDE the repo tree on purpose: `python -m zipapp tools`
# packs the whole tools/ directory regardless of .gitignore, so any residue
# under tools/bench/results would leak machine paths into the packaged
# zipapp (tests/test_incident_replay.py::test_d_release_archive_scanned).
# Default = system temp; override with WB_DETERMINISTIC_DIR.
RESULTS = Path(os.environ.get(
    "WB_DETERMINISTIC_DIR",
    Path(tempfile.gettempdir()) / "wb-deterministic-bench"))
DATA = RESULTS / "data"
FIX = RESULTS / "fixtures"

arms = []
_passed = 0
_failed = 0


def rec(arm, case, ok, detail=None, extra=None, duration_ms=None):
    global _passed, _failed
    _passed += bool(ok)
    _failed += not ok
    row = {"arm": arm, "case": case, "pass": bool(ok),
           "duration_ms": round(duration_ms, 1) if duration_ms is not None else None}
    if detail is not None:
        row["detail"] = detail
    if extra is not None:
        row["extra"] = extra
    arms.append(row)
    print(f"  [{'PASS' if ok else 'FAIL'}] {arm} / {case}"
          + (f"  ({row['duration_ms']} ms)" if duration_ms is not None else ""))
    return ok


def env_for(data_dir, **overrides):
    e = dict(os.environ)
    e["HARNESS_DATA_DIR"] = str(data_dir)
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    e.pop("PYTHONPATH", None)
    for k, v in overrides.items():
        if v is None:
            e.pop(k, None)
        else:
            e[k] = v
    return e


def run(cmd, *, data_dir, cwd=None, stdin=None, extra_env=None, timeout=120):
    env = env_for(data_dir, **(extra_env or {}))
    if isinstance(stdin, (bytes, bytearray)):
        stdin = bytes(stdin).decode("utf-8")
    return subprocess.run(cmd, cwd=cwd, input=stdin, env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def cli(args, *, data_dir, cwd=None, timeout=120):
    return run([PY, str(CLI), *args], data_dir=data_dir, cwd=cwd, timeout=timeout)


def timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t0) * 1000


def reset():
    for p in (DATA, FIX):
        if p.exists():
            shutil.rmtree(p)
    for p in (DATA, FIX):
        p.mkdir(parents=True)


# =============================================================================
# ARM 1 — Gate correctness (unit asset reuse + real-hook E2E)
# =============================================================================
def arm1_gate():
    print("\n=== ARM 1: Gate correctness ===")
    t0 = time.perf_counter()
    p = run([PY, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--tb=short",
             str(TESTS / "test_gate_tokens.py"),
             str(TESTS / "test_gate_shell_expansion.py"),
             str(TESTS / "test_gate_powershell.py")],
            data_dir=DATA / "arm1a", cwd=REPO, timeout=600)
    ms = (time.perf_counter() - t0) * 1000
    out = p.stdout + p.stderr
    m = re.search(r"(\d+) passed(?:, (\d+) (?:failed|error))?.*?in ([\d.]+)s", out, re.S)
    failed_n = int(m.group(2)) if m and m.group(2) else 0
    tail = [ln for ln in out.strip().splitlines() if ln.strip()]
    rec("gate", "pytest-assets(test_gate_*).py",
        p.returncode == 0 and failed_n == 0, duration_ms=ms,
        extra={"returncode": p.returncode,
               "summary": (tail[-1] if tail else out[:200])[:160]})

    def hook_case(name, command, tool, data_sub, exp_rc, mode="enforce", token=None):
        d = DATA / f"arm1b-{name}"
        payload = json.dumps({"tool_name": tool,
                              "tool_input": {"command": command}})
        extra_env = {"HARNESS_GATE_MODE": mode}
        if token:
            extra_env["HARNESS_GATE_TOKEN"] = token
        r, ms = timed(lambda: run([PY, str(HOOK_GATE)], data_dir=d,
                                  stdin=payload.encode("utf-8"),
                                  extra_env=extra_env, timeout=60))
        rec("gate-hook", data_sub, r.returncode == exp_rc,
            detail={"command": command[:60], "rc": r.returncode, "exp_rc": exp_rc},
            duration_ms=ms)
        return r

    hook_case("bin", "git status", "Bash", "benign-bash", exp_rc=0)
    hook_case("danger", "rm -rf /tmp/wb_r2_gone", "Bash", "danger-bash", exp_rc=2)
    hook_case("ps-danger", "Remove-Item -Recurse C:\\x -Force", "PowerShell",
              "danger-powershell", exp_rc=2)
    hook_case("ps-benign", "Get-ChildItem C:\\tmp", "PowerShell", "benign-ps",
              exp_rc=0)
    hook_case("exp", "git${IFS}push origin main", "Bash", "expansion-bypass",
              exp_rc=2)

    d = DATA / "arm1b-token"
    r = cli(["gate", "approve", "--once", "--action", "git push origin main"],
            data_dir=d)
    try:
        tok = json.loads(r.stdout.strip())["token"]
    except Exception:
        rec("gate-hook", "token-grant", False, detail={"out": r.stdout[:120]})
        return
    r1, ms1 = timed(lambda: run([PY, str(HOOK_GATE)], data_dir=d,
                                stdin=json.dumps({"tool_name": "Bash",
                                                  "tool_input": {
                                                      "command": "git push origin main"}}).encode("utf-8"),
                                extra_env={"HARNESS_GATE_MODE": "enforce",
                                           "HARNESS_GATE_TOKEN": tok}, timeout=60))
    rec("gate-hook", "one-shot-token-first-use", r1.returncode == 0,
        detail={"rc": r1.returncode}, duration_ms=ms1)
    r2, ms2 = timed(lambda: run([PY, str(HOOK_GATE)], data_dir=d,
                                stdin=json.dumps({"tool_name": "Bash",
                                                  "tool_input": {
                                                      "command": "git push origin main"}}).encode("utf-8"),
                                extra_env={"HARNESS_GATE_MODE": "enforce",
                                           "HARNESS_GATE_TOKEN": tok}, timeout=60))
    rec("gate-hook", "one-shot-token-replay-denied", r2.returncode == 2,
        detail={"rc": r2.returncode}, duration_ms=ms2)


# =============================================================================
# ARM 2 — Verify correctness (real CLI)
# =============================================================================
def make_verify_fixture(name, config=None, scripts=None):
    d = FIX / f"v2-{name}"
    d.mkdir(parents=True, exist_ok=True)
    if config:
        (d / ".harness-verify.json").write_text(json.dumps(config), encoding="utf-8")
    for fn, code in (scripts or {}).items():
        (d / fn).write_text(code, encoding="utf-8")
    return d


def arm2_verify():
    print("\n=== ARM 2: Verify correctness ===")
    dgate = DATA / "arm2"
    cli(["gate", "mode", "--set", "audit"], data_dir=dgate)

    def vrun(exec_id, fixture, extra=(), cwd=None):
        return cli(["verify", "run", "--exec", exec_id, "--stage", "iv",
                    "--cwd", str(cwd or fixture), *extra], data_dir=dgate)

    fixt = make_verify_fixture("pass", scripts={"pass_script.py": 'print("ok")\n'})
    r, ms = timed(lambda: vrun("v-pass", fixt,
                               extra=["--cmd", "python pass_script.py"]))
    j = json.loads(r.stdout)
    rec("verify", "pass-cmd-exit0",
        r.returncode == 0 and j["status"] == "pass" and j["can_claim_done"] is True,
        detail={"rc": r.returncode, "status": j.get("status"),
                "can_claim_done": j.get("can_claim_done")}, duration_ms=ms)

    fixt = make_verify_fixture("fail", scripts={"fail_script.py":
                                                'import sys; sys.exit(1)\n'})
    r, ms = timed(lambda: vrun("v-fail", fixt,
                               extra=["--cmd", "python fail_script.py"]))
    j = json.loads(r.stdout)
    rec("verify", "fail-cmd-exit1",
        r.returncode == 1 and j["status"] == "fail" and j["can_claim_done"] is False,
        detail={"rc": r.returncode, "status": j.get("status"),
                "can_claim_done": j.get("can_claim_done")}, duration_ms=ms)

    fixt = make_verify_fixture("timeout", {
        "commands": [[PY, "-c", "import time; time.sleep(5)"]],
        "timeout_s": 1, "max_reflections": 0})
    r, ms = timed(lambda: vrun("v-timeout", fixt))
    j = json.loads(r.stdout)
    v = (j.get("verdicts") or [{}])[0]
    rec("verify", "timeout-fails",
        r.returncode == 1 and j["status"] == "fail" and j["can_claim_done"] is False
        and v.get("timed_out") is True and v.get("exit_code") is None,
        detail={"rc": r.returncode, "status": j.get("status"), "verdict": v},
        duration_ms=ms)

    def clamp_case(name, config, exp_max_ref):
        dd = DATA / f"arm2-{name}"
        fixt = make_verify_fixture(name, config)
        r = cli(["verify", "run", "--exec", f"v-{name}", "--stage", "iv",
                 "--cwd", str(fixt)], data_dir=dd)
        ev = dd / "verify" / f"v-{name}.jsonl"
        rows = [json.loads(x) for x in ev.read_text(encoding="utf-8").splitlines()
                if x.strip()]
        got = rows[-1]["max_reflections"]
        rec("verify", f"clamp-{name}", got == exp_max_ref,
            detail={"got": got, "exp": exp_max_ref}, duration_ms=None)

    clamp_case("hi", {"commands": [[PY, "-c", "print(1)"]], "max_reflections": 99}, 10)
    clamp_case("garbage", {"commands": [[PY, "-c", "print(1)"]],
                           "max_reflections": "garbage"}, 3)
    clamp_case("neg", {"commands": [[PY, "-c", "print(1)"]], "max_reflections": -5}, 0)

    dd = DATA / "arm2-exhaust"
    fixt = make_verify_fixture("exhaust", {
        "commands": [[PY, "-c", "print('in-budget')"]], "max_reflections": 0})
    j1 = json.loads(cli(["verify", "run", "--exec", "v-exh", "--stage", "iv",
                         "--cwd", str(fixt)], data_dir=dd).stdout)
    j2 = json.loads(cli(["verify", "run", "--exec", "v-exh", "--stage", "iv",
                         "--cwd", str(fixt)], data_dir=dd).stdout)
    rec("verify", "max_reflections=0-budget-exhaust",
        j1["status"] == "pass" and j1["can_claim_done"] is True
        and j2["status"] == "reflections-exhausted"
        and j2["can_claim_done"] is False,
        detail={"first": {"status": j1.get("status"),
                          "can_claim_done": j1.get("can_claim_done")},
                "second": {"status": j2.get("status"),
                           "can_claim_done": j2.get("can_claim_done")}})


# =============================================================================
# ARM 3 — Checkpoint integrity / crash recovery (real CLI)
# =============================================================================
def cp_store_path(data_dir, exec_id):
    return data_dir / "checkpoints" / f"{exec_id}.jsonl"


def arm3_checkpoint():
    print("\n=== ARM 3: Checkpoint integrity / crash recovery ===")
    okdir = DATA / "arm3-ok"
    cli(["checkpoint", "begin", "--exec", "chain-ok", "--stage", "s0"], data_dir=okdir)
    cli(["checkpoint", "save", "--exec", "chain-ok", "--stage", "s0",
         "--payload", '{"k": 1}'], data_dir=okdir)
    cli(["checkpoint", "save", "--exec", "chain-ok", "--stage", "s1",
         "--payload", '{"k": 2}'], data_dir=okdir)
    rep = json.loads(cli(["checkpoint", "verify", "--exec", "chain-ok"],
                         data_dir=okdir).stdout)
    rec("checkpoint", "healthy-chain-verify-ok",
        rep["ok"] is True and rep["total_valid"] == 2,
        detail={"ok": rep.get("ok"), "total_valid": rep.get("total_valid")})

    td = DATA / "arm3-torn"
    cli(["checkpoint", "begin", "--exec", "chain-torn", "--stage", "s0"], data_dir=td)
    cli(["checkpoint", "save", "--exec", "chain-torn", "--stage", "s0",
         "--payload", '{"k": 1}'], data_dir=td)
    cli(["checkpoint", "save", "--exec", "chain-torn", "--stage", "s1",
         "--payload", '{"k": 2}'], data_dir=td)
    with open(cp_store_path(td, "chain-torn"), "a", encoding="ascii") as f:
        f.write('{"checkpoint_id": "cp-deadbeef", "schema": 1, "stage": "s2"')
    rep = json.loads(cli(["checkpoint", "verify", "--exec", "chain-torn"],
                         data_dir=td).stdout)
    jl = json.loads(cli(["checkpoint", "load", "--exec", "chain-torn"],
                        data_dir=td).stdout)
    lb = jl.get("checkpoint") or {}
    rec("checkpoint", "torn-tail-detected+last-valid-readable",
        rep["ok"] is False and rep["dropped_tail"] == 1 and lb.get("stage") == "s1",
        detail={"ok": rep.get("ok"), "dropped_tail": rep.get("dropped_tail"),
                "load_stage": lb.get("stage")})

    td = DATA / "arm3-tamper"
    cli(["checkpoint", "begin", "--exec", "chain-tamper", "--stage", "s0"], data_dir=td)
    cli(["checkpoint", "save", "--exec", "chain-tamper", "--stage", "s0",
         "--payload", '{"k": 1}'], data_dir=td)
    cli(["checkpoint", "save", "--exec", "chain-tamper", "--stage", "s1",
         "--payload", '{"k": 2}'], data_dir=td)
    p = cp_store_path(td, "chain-tamper")
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows[1]["payload"] = {"k": 999}  # hash now mismatches payload_sha256
    p.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
    rep = json.loads(cli(["checkpoint", "verify", "--exec", "chain-tamper"],
                         data_dir=td).stdout)
    rec("checkpoint", "tampered-payload-hash-detected",
        rep["ok"] is False and len(rep["hash_failures"]) == 1,
        detail={"ok": rep.get("ok"), "hash_failures": rep.get("hash_failures")})

    td = DATA / "arm3-schema"
    cli(["checkpoint", "begin", "--exec", "chain-schema", "--stage", "s0"], data_dir=td)
    cli(["checkpoint", "save", "--exec", "chain-schema", "--stage", "s0",
         "--payload", '{"k": 1}'], data_dir=td)
    cli(["checkpoint", "save", "--exec", "chain-schema", "--stage", "s1",
         "--payload", '{"k": 2}'], data_dir=td)
    p = cp_store_path(td, "chain-schema")
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows[1]["schema"] = 999  # keep a valid head line so verify() reports, not CorruptStateError
    p.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
    rep = json.loads(cli(["checkpoint", "verify", "--exec", "chain-schema"],
                         data_dir=td).stdout)
    rec("checkpoint", "schema-version-mismatch-detected",
        rep["ok"] is False and len(rep["bad_schema_lines"]) == 1,
        detail={"ok": rep.get("ok"), "bad_schema_lines": rep.get("bad_schema_lines"),
                "total_valid": rep.get("total_valid")})

    td = DATA / "arm3-allbad"
    cli(["checkpoint", "save", "--exec", "chain-allbad", "--stage", "s0",
         "--payload", '{"k": 1}'], data_dir=td)
    cli(["checkpoint", "save", "--exec", "chain-allbad", "--stage", "s1",
         "--payload", '{"k": 2}'], data_dir=td)
    p = cp_store_path(td, "chain-allbad")
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    for row in rows:
        row.pop("payload_sha256", None)  # must fail validation per-line
    p.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
    r = cli(["checkpoint", "verify", "--exec", "chain-allbad"], data_dir=td)
    rec("checkpoint", "all-unusable-explicit-error-not-silent",
        r.returncode == 1 and "corrupt_state" in (r.stderr or "").strip(),
        detail={"rc": r.returncode, "stderr_tail": (r.stderr or "").strip()[:120]})


# =============================================================================
# main
# =============================================================================
def main():
    print(f"repo    : {REPO}")
    print(f"results : {RESULTS}")
    print(f"py      : {PY}")
    reset()
    t_start = time.perf_counter()
    arm1_gate()
    arm2_verify()
    arm3_checkpoint()
    total_ms = (time.perf_counter() - t_start) * 1000

    result = {
        "bench": "ai-workbench deterministic correctness bench (promoted R2)",
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": str(REPO),
        "python": PY,
        "notes": "offline, zero-LLM, deterministic",
        "total_wall_ms": round(total_ms, 1),
        "arms": arms,
        "summary": {"passed": _passed, "failed": _failed},
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== TOTALS: passed={_passed} failed={_failed} "
          f"({total_ms / 1000:.1f}s wall) ===")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())