"""Hermetic tests for tools/security_scan.py — the release security gate.

All tests are offline and deterministic. They never invoke a real scanner:
when a real tool is absent they must NOT skip silently, so the wrapper is
exercised against fixture scanner scripts (fake_trivy.py / fake_gitleaks.py)
that are generated into a tmp dir, put on PATH via $AIWB_TRIVY_PATH /
$AIWB_GITLEAKS_PATH, and driven by a JSON behavior file placed in the scanned
tree root (``.securityscan_fake.json``). This tests parsing, exit-code and
fail-semantics logic deterministically on every platform.

One live-detection test additionally runs the REAL ``trivy`` when it is
installed (pytest.mark.skipif). It uses ``trivy_scanners=("secret",)`` because
secret scanning is pattern-based and works without the vulnerability DB, so
the test has no network dependency.

Fixture secrets below are documented fakes, never real credentials:
- AKIAIOSFODNN7EXAMPLE  (the AWS-documented example access key id)
- AKIAABCDEFGHIJKLMNOP (synthetic AKIA prefix + deterministic suffix; no
                        matching secret part exists, cannot be a live key)
Run from the repo root: python -m pytest tests/test_security_scan.py -q
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RC / "tools"))
import security_scan as ss  # noqa: E402

CLI = RC / "tools" / "security_scan.py"

FAKE_TRIVY = r'''
import json, sys
from pathlib import Path
def main():
    args = [a for a in sys.argv if a and not a.startswith("-")]
    target = args[-1] if args else "."
    behavior = {}
    bf = Path(target) / ".securityscan_fake.json"
    if bf.is_file():
        behavior = json.loads(bf.read_text(encoding="utf-8"))
    cap = behavior.get("argv_capture")
    if cap:
        Path(cap).write_text(json.dumps(sys.argv), encoding="utf-8")
    out = behavior.get("stdout_hex")
    if out:
        sys.stdout.buffer.write(bytes.fromhex(out))
    else:
        sys.stdout.write(behavior.get("stdout_text", '{"Results": []}'))
    sys.stdout.flush()
    if behavior.get("stderr_text"):
        sys.stderr.write(behavior["stderr_text"])
    sys.exit(int(behavior.get("exit_code", 0)))
if __name__ == "__main__":
    main()
'''

FAKE_GITLEAKS = r'''
import json, sys
from pathlib import Path
def _opt(args, name):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return None
def main():
    source = _opt(sys.argv, "--source") or "."
    report = _opt(sys.argv, "--report-path")
    behavior = {}
    bf = Path(source) / ".securityscan_fake.json"
    if bf.is_file():
        behavior = json.loads(bf.read_text(encoding="utf-8"))
    cap = behavior.get("argv_capture")
    if cap:
        Path(cap).write_text(json.dumps(sys.argv), encoding="utf-8")
    if report is not None:
        Path(report).write_text(
            json.dumps(behavior.get("report_findings", []), indent=2),
            encoding="utf-8")
    if behavior.get("stderr_text"):
        sys.stderr.write(behavior["stderr_text"])
    sys.exit(int(behavior.get("exit_code", 0)))
if __name__ == "__main__":
    main()
'''

DOC_EXAMPLE_AWS = "AKIAIOSFODNN7EXAMPLE"  # AWS-documented example, never a live key
SYNTHETIC_AWS = "AKIAABCDEFGHIJKLMNOP"     # synthetic AKIA + deterministic suffix


# ---------------------------------------------------------------- fixtures/helpers


@pytest.fixture
def fake_trivy(tmp_path, monkeypatch):
    """Write fake_trivy.py into tmp/bin and point AIWB_TRIVY_PATH at it."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "fake_trivy.py"
    script.write_text(FAKE_TRIVY, encoding="utf-8")
    monkeypatch.setenv("AIWB_TRIVY_PATH", str(script))
    monkeypatch.delenv("AIWB_GITLEAKS_PATH", raising=False)
    return script


@pytest.fixture
def fake_gitleaks(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "fake_gitleaks.py"
    script.write_text(FAKE_GITLEAKS, encoding="utf-8")
    monkeypatch.setenv("AIWB_GITLEAKS_PATH", str(script))
    monkeypatch.delenv("AIWB_TRIVY_PATH", raising=False)
    return script


def no_scanners_on_path(monkeypatch, empty_path_dir=None):
    """Force deterministic tool-missing regardless of what is installed.

    Patches shutil.which IN-PROCESS (for API-level calls) and returns an env
    dict whose PATH cannot find any scanner (for subprocess CLI calls).
    """
    monkeypatch.delenv("AIWB_TRIVY_PATH", raising=False)
    monkeypatch.delenv("AIWB_GITLEAKS_PATH", raising=False)
    monkeypatch.setattr(ss.shutil, "which", lambda *a, **k: None)
    if empty_path_dir is not None:
        empty_path_dir.mkdir(exist_ok=True)
        return {"PATH": str(empty_path_dir)}
    return {}


def set_behavior(target, **kwargs):
    (Path(target) / ".securityscan_fake.json").write_text(
        json.dumps(kwargs), encoding="utf-8")


def run_cli(target, *extra, env_extra=None, timeout=120):
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, str(CLI), str(target), *extra],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=timeout)


def aws_secret_result(target_name="src/credentials.txt"):
    return {"Results": [{
        "Target": target_name, "Class": "secret", "Type": "secret",
        "Secrets": [{
            "RuleID": "aws-access-key-id", "Category": "AWS", "Severity": "HIGH",
            "Title": "AWS Access Key ID", "Match": DOC_EXAMPLE_AWS, "Line": 3}]}]}


# ---------------------------------------------------------------- scan semantics


def test_fake_secret_detected_status_findings_and_exit_1(tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, stdout_text=json.dumps(aws_secret_result()))
    report = ss.scan(target)
    assert report.status == "findings"
    assert report.exit_code == 1
    assert len(report.findings) == 1
    f = report.findings[0]
    assert f == {
        "scanner": "trivy", "rule": "aws-access-key-id", "severity": "HIGH",
        "target": "src/credentials.txt", "line": 3, "id": "aws-access-key-id"}
    cli = run_cli(target)
    assert cli.returncode == 1, cli.stdout + cli.stderr
    assert "findings" in cli.stdout
    assert "aws-access-key-id" in cli.stdout


def test_clean_tree_status_clean_and_exit_0(tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, stdout_text='{"Results": []}')
    report = ss.scan(target)
    assert report.status == "clean"
    assert report.exit_code == 0
    assert report.findings == []
    assert run_cli(target).returncode == 0


def test_scanner_missing_is_tool_missing_exit_3_not_pass(tmp_path, monkeypatch):
    env = no_scanners_on_path(monkeypatch, tmp_path / "nopath")
    target = tmp_path / "proj"
    target.mkdir()
    report = ss.scan(target)
    assert report.status == "tool-missing"
    assert report.status not in ("clean", "findings")  # NOT pass, NOT a vuln claim
    assert report.exit_code == 3
    assert "trivy" in report.missing
    cli = run_cli(target, env_extra=env)
    assert cli.returncode == 3
    assert "not on PATH" in cli.stdout


def test_scanner_crash_is_infra_failure_exit_3(tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, exit_code=2, stderr_text="fatal: scan engine crashed\n")
    report = ss.scan(target, timeout_s=60)
    assert report.status == "infra-failure"
    assert report.status not in ("clean", "findings")
    assert report.exit_code == 3
    assert "crashed" in report.stderr_tail
    assert run_cli(target).returncode == 3


def test_db_download_failure_like_crash_is_infra_failure(tmp_path, fake_trivy):
    # A scanner that runs but exits nonzero (like a vuln DB download failure)
    # must surface as infra-failure, never as PASS and never as a finding.
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, exit_code=1,
                 stderr_text="FATAL failed to download the vulnerability DB\n")
    report = ss.scan(target)
    assert report.status == "infra-failure"
    assert report.exit_code == 3
    assert "vulnerability DB" in report.stderr_tail
    assert report.findings == []


def test_allow_infra_failure_downgrades_exit_with_loud_warning(
        tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, exit_code=1, stderr_text="db down\n")
    without_flag = run_cli(target)
    assert without_flag.returncode == 3
    with_flag = run_cli(target, "--allow-infra-failure")
    assert with_flag.returncode == 0
    assert "AUDIT mode only" in with_flag.stderr
    assert "WARNING" in with_flag.stderr


def test_tool_missing_is_not_downgraded_by_allow_infra_failure(
        tmp_path, monkeypatch):
    # --allow-infra-failure downgrades ONLY infra-failure, never tool-missing.
    env = no_scanners_on_path(monkeypatch, tmp_path / "nopath")
    target = tmp_path / "proj"
    target.mkdir()
    cli = run_cli(target, "--allow-infra-failure", env_extra=env)
    assert cli.returncode == 3


# ---------------------------------------------------------------- .securityignore


def _two_secret_results():
    return {"Results": [
        {"Target": "a.txt", "Class": "secret", "Type": "secret",
         "Secrets": [{"RuleID": "aaa", "Severity": "HIGH", "Line": 1}]},
        {"Target": "b.txt", "Class": "secret", "Type": "secret",
         "Secrets": [{"RuleID": "bbb", "Severity": "MEDIUM", "Line": 2}]},
    ]}


def test_securityignore_suppresses_by_id(tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, stdout_text=json.dumps(_two_secret_results()))
    (target / ".securityignore").write_text(
        json.dumps([{"id": "aaa", "reason": "false positive",
                     "expires": "2099-01-01"}]), encoding="utf-8")
    report = ss.scan(target)
    assert report.status == "findings"
    assert [f["id"] for f in report.findings] == ["bbb"]
    assert report.suppressed_count == 1
    assert [f["rule"] for f in report.findings] == ["bbb"]


def test_securityignore_entry_without_expires_suppresses(tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, stdout_text=json.dumps(_two_secret_results()))
    (target / ".securityignore").write_text(
        json.dumps([{"id": "bbb", "reason": "fp"}]), encoding="utf-8")
    report = ss.scan(target)
    assert [f["id"] for f in report.findings] == ["aaa"]


def test_securityignore_expired_exception_does_not_suppress_and_is_reported(
        tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, stdout_text=json.dumps(_two_secret_results()))
    expired = {"id": "aaa", "reason": "old exception", "expires": "2020-01-01"}
    (target / ".securityignore").write_text(
        json.dumps([expired]), encoding="utf-8")
    report = ss.scan(target)
    # expired exception is IGNORED: the finding stays ACTIVE
    assert [f["id"] for f in report.findings] == ["aaa", "bbb"]
    assert report.expired_ignore == [expired]
    assert report.suppressed_count == 0
    cli = run_cli(target)
    assert cli.returncode == 1
    assert "expired" in cli.stdout


def test_invalid_securityignore_fails_closed(tmp_path, fake_trivy, monkeypatch):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, stdout_text='{"Results": []}')
    (target / ".securityignore").write_text('{"not": "a list"}', encoding="utf-8")
    with pytest.raises(ValueError):
        ss.scan(target)
    cli = run_cli(target)
    assert cli.returncode == 2  # bad usage / configuration, never green


def test_invalid_securityignore_entry_fails_closed(tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, stdout_text='{"Results": []}')
    (target / ".securityignore").write_text(
        json.dumps([{"reason": "no id here"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        ss.scan(target)


# ---------------------------------------------------------------- license inventory


def make_vendor_tree(target):
    vendor = target / "vendor"
    (vendor / "fakelib").mkdir(parents=True)
    (vendor / "fakelib" / "script.py").write_text("x = 1", encoding="utf-8")
    (vendor / "fakelib2").mkdir()
    (vendor / "fakelib2" / "COPYING.txt").write_text("copy", encoding="utf-8")
    (vendor / "goodlib").mkdir()
    (vendor / "goodlib" / "LICENSE").write_text("MIT", encoding="utf-8")
    (vendor / "goodlib2").mkdir()
    (vendor / "goodlib2" / "NOTICE.txt").write_text("notice", encoding="utf-8")
    (vendor / "ecc").mkdir()
    (vendor / "ecc" / "LICENSE").write_text("Apache-2.0", encoding="utf-8")
    (vendor / "ecc" / "MANIFEST.sha256").write_text("{}", encoding="utf-8")


def test_license_inventory_flags_vendor_without_license(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    make_vendor_tree(target)
    result = ss.licenses(target)
    # COPYING.txt is not a LICENSE*/NOTICE* file by design; findings come back
    # in sorted package order (fakelib before fakelib2)
    assert [f["target"] for f in result["findings"]] == [
        "vendor/fakelib", "vendor/fakelib2"]
    assert result["missing"] == 2
    assert result["checked"] == 5
    f = result["findings"][0]
    assert f["rule"] == "missing-license-file"
    assert f["severity"] == "HIGH"
    assert f["id"] == "license-missing:vendor/fakelib"
    assert f["scanner"] == "license-inventory"


def test_license_inventory_records_licensed_vendor_and_manifest(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    make_vendor_tree(target)
    result = ss.licenses(target)
    inv = result["inventory"]
    assert "vendor/ecc" in inv
    assert inv["vendor/ecc"]["manifest"] is True  # MANIFEST.sha256 provenance
    assert "vendor/goodlib" in inv and "vendor/goodlib2" in inv
    assert "vendor/fakelib" not in inv
    assert any(p.endswith("LICENSE")
               for p in inv["vendor/ecc"]["license_files"])


def test_license_inventory_cli_exit_1_and_json(tmp_path):
    target = tmp_path / "proj"
    target.mkdir()
    make_vendor_tree(target)
    cli = run_cli(target, "--licenses", "--json")
    assert cli.returncode == 1
    payload = json.loads(cli.stdout)
    assert payload["mode"] == "licenses"
    assert payload["status"] == "findings"
    assert payload["exit_code"] == 1
    # clean variant exits 0
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "vendor").mkdir()
    (clean / "vendor" / "ok").mkdir()
    (clean / "vendor" / "ok" / "LICENSE").write_text("MIT", encoding="utf-8")
    assert run_cli(clean, "--licenses").returncode == 0


# ---------------------------------------------------------------- release-asset scope


def test_release_asset_scope_scans_dist_directory(tmp_path, fake_trivy):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "app.pyz").write_bytes(b"mock release-archive bytes")
    capture = tmp_path / "captured_argv.json"
    set_behavior(dist,
                 stdout_text=json.dumps(aws_secret_result("dist/app.pyz")),
                 argv_capture=str(capture))
    report = ss.scan(dist)
    # the scanner really received THIS target path (the release-assets dir)
    captured = json.loads(capture.read_text(encoding="utf-8"))
    assert captured[-1] == str(dist)
    assert "fs" in captured
    # files inside the dist tree are what get reported
    assert report.status == "findings"
    assert report.findings[0]["target"] == "dist/app.pyz"
    cli = run_cli(dist, "--json")
    assert cli.returncode == 1
    payload = json.loads(cli.stdout)
    assert payload["findings"][0]["target"] == "dist/app.pyz"


# ---------------------------------------------------------------- output tolerance


def test_non_utf8_scanner_output_tolerated(tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    # A JSON document whose Match field contains invalid UTF-8 bytes must not
    # crash the wrapper; the bytes become U+FFFD and parsing continues.
    # single-backslash \xff/\xfe are real byte VALUES 0xFF/0xFE in a bytes
    # literal (not the two-character escape), so the fake emits invalid UTF-8
    raw = (
        b'{"Results": [{"Target": "t.txt", "Class": "secret", "Type": "secret",'
        b' "Secrets": [{"RuleID": "r1", "Severity": "HIGH", "Match": "sig\xff\xfe",'
        b' "Line": 5}]}]}'
    )
    set_behavior(target, stdout_hex=raw.hex())
    report = ss.scan(target)
    assert report.status == "findings"
    assert report.findings[0]["rule"] == "r1"
    assert report.findings[0]["line"] == 5


def test_unparseable_stdout_is_infra_failure(tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, stdout_text="not json at all")
    report = ss.scan(target)
    assert report.status == "infra-failure"
    assert report.exit_code == 3


# ---------------------------------------------------------------- gitleaks


def test_gitleaks_findings_parse_and_exit_1(tmp_path, fake_gitleaks):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, report_findings=[{
        "RuleID": "aws-access-token", "Description": "AWS Access Token",
        "File": "cfg/file.txt", "Secret": DOC_EXAMPLE_AWS,
        "StartLine": 4, "Fingerprint": "fp-1"}])
    report = ss.scan(target, scanners=("gitleaks",))
    assert report.status == "findings"
    assert report.exit_code == 1
    f = report.findings[0]
    assert f["scanner"] == "gitleaks"
    assert f["rule"] == "aws-access-token"
    assert f["severity"] == "HIGH"  # gitleaks has no per-finding severity
    assert f["target"] == "cfg/file.txt"
    assert f["line"] == 4
    assert f["id"] == "fp-1"
    cli = run_cli(target, "--scanners", "gitleaks")
    assert cli.returncode == 1
    assert "aws-access-token" in cli.stdout


def test_gitleaks_missing_is_tool_missing_exit_3(tmp_path, monkeypatch):
    no_scanners_on_path(monkeypatch)
    target = tmp_path / "proj"
    target.mkdir()
    report = ss.scan(target, scanners=("gitleaks",))
    assert report.status == "tool-missing"
    assert report.exit_code == 3
    assert "gitleaks" in report.missing
    assert run_cli(target, "--scanners", "gitleaks").returncode == 3


def test_multi_scanner_partial_coverage_never_clean(tmp_path, fake_trivy,
                                                    monkeypatch):
    # trivy present and clean, but the REQUESTED gitleaks is missing: that is
    # partial coverage, never `clean`/exit 0.
    target = tmp_path / "proj"
    target.mkdir()
    monkeypatch.setenv("AIWB_TRIVY_PATH", str(fake_trivy))
    monkeypatch.delenv("AIWB_GITLEAKS_PATH", raising=False)
    monkeypatch.setattr(ss.shutil, "which", lambda *a, **k: None)
    set_behavior(target, stdout_text='{"Results": []}')
    report = ss.scan(target, scanners=("trivy", "gitleaks"))
    assert report.status == "tool-missing"
    assert report.exit_code == 3
    assert report.missing == ["gitleaks"]
    assert report.findings == []


# ---------------------------------------------------------------- CLI usage


def test_cli_missing_target_dir_is_usage_error_exit_2(tmp_path):
    cli = run_cli(tmp_path / "does-not-exist")
    assert cli.returncode == 2
    assert "does not exist" in cli.stderr


def test_cli_json_report_shape(tmp_path, fake_trivy):
    target = tmp_path / "proj"
    target.mkdir()
    set_behavior(target, stdout_text=json.dumps(aws_secret_result()))
    cli = run_cli(target, "--json")
    assert cli.returncode == 1
    payload = json.loads(cli.stdout)
    assert payload["mode"] == "scan"
    assert payload["status"] == "findings"
    assert payload["exit_code"] == 1
    assert payload["findings"][0]["rule"] == "aws-access-key-id"
    assert "stderr_tail" in payload
    assert "duration_s" in payload


# ---------------------------------------------------------------- live (real tool)


@pytest.mark.skipif(shutil.which("trivy") is None,
                    reason="real trivy not installed")
def test_live_detection_with_real_trivy(tmp_path, monkeypatch):
    """Real-tool end-to-end: a real secret must be caught, exit 1.

    Uses trivy_scanners=("secret",) because trivy's secret analyzer is
    pattern-based and needs no vulnerability DB, so this has no network
    dependency. The synthetic AKIA key is not a valid credential.
    """
    monkeypatch.delenv("AIWB_TRIVY_PATH", raising=False)
    target = tmp_path / "live"
    target.mkdir()
    private_key_block = "-----BEGIN %s\n" % "PRIVATE KEY-----"
    (target / "secret.txt").write_text(
        SYNTHETIC_AWS + "\n" + private_key_block + "MIIBcg==\n"
        + "-----END PRIVATE KEY-----\n",
        encoding="utf-8")
    (target / "clean.txt").write_text("nothing to see\n", encoding="utf-8")
    report = ss.scan(target, trivy_scanners=("secret",), timeout_s=180)
    assert report.status == "findings", (
        f"real trivy did not detect the synthetic secret: {report.message} "
        f"{report.stderr_tail}")
    assert report.exit_code == 1
    assert any(f["rule"] == "aws-access-key-id" for f in report.findings)