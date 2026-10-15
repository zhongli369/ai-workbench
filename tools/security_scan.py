#!/usr/bin/env python3
"""Release security gate scanner. stdlib only, Python 3.10+, ASCII.

Wraps real secret/vuln scanner tools (trivy by default, gitleaks optionally)
behind one deterministic interface with HONEST fail semantics, so CI can tell
the difference between:

  clean          scan completed, no findings at/above threshold  -> exit 0
  findings       scan completed, findings remain after
                 ``.securityignore`` filtering                   -> exit 1
  tool-missing   a requested scanner could not be found          -> exit 3
  infra-failure  the scanner crashed, timed out, or could not
                 download its DB (network)                       -> exit 3

The two failure statuses are deliberately NOT "pass" and are NOT a
vulnerability claim. A missing tool or a broken scanner is an environment
problem that must fail closed: it must never read as "the tree is clean" and
must never be reported as a finding ('infra failure masquerading as PASS' is
exactly the bug this module exists to prevent).

Exit codes (process level):
  0 = clean
  1 = findings
  2 = bad usage / invalid configuration (malformed .securityignore, ...)
  3 = tool-missing / infra-failure (downgradable to 0 ONLY with
      --allow-infra-failure, an AUDIT-mode convenience for daily non-blocking
      runs; release/blocking mode must never set that flag)

Scanner discovery order per scanner:
  trivy    -> $AIWB_TRIVY_PATH then `trivy` on PATH
  gitleaks -> $AIWB_GITLEAKS_PATH then `gitleaks` on PATH

A resolved path whose name ends in ``.py`` is executed via ``python <script>``
-- this is how hermetic tests plug in a deterministic fixture scanner without
requiring the real binary. Any other path is executed directly.

False positives: a JSON array file ``.securityignore`` at the scanned tree
root holds entries ``{"id": "...", "reason": "...", "expires": "YYYY-MM-DD"}``
that suppress findings BY ID. An ``expires`` date strictly before today is
EXPIRED: the exception is ignored (the finding stays active) and reported.
There is deliberately no global "skip everything" flag.

License inventory: ``--licenses`` walks ``vendor/`` and flags every vendored
package directory that has no LICENSE*/NOTICE* file. Fully local, no scanner
binary and no network required.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_INFRA = 3

DEFAULT_SCANNERS = ("trivy",)
SUPPORTED_SCANNERS = ("trivy", "gitleaks")
DEFAULT_SEVERITY = ("MEDIUM", "HIGH", "CRITICAL")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
DEFAULT_TIMEOUT_S = 600
TRIVY_SCANNERS = ("secret", "misconfig", "license", "vuln")
IGNORE_FILE = ".securityignore"
FAKE_BEHAVIOR_FILE = ".securityscan_fake.json"  # hermetic test fixture hook
VENDOR_DIR = "vendor"

STATUS_EXIT = {
    "clean": EXIT_OK,
    "findings": EXIT_FINDINGS,
    "tool-missing": EXIT_INFRA,
    "infra-failure": EXIT_INFRA,
}

STDERR_TAIL_CHARS = 2000


class ScanReport:
    """Normalized outcome of one aggregate scan (one or more scanner tools)."""

    def __init__(
        self,
        status: str,
        *,
        target: str = "",
        scanner: str = "",
        findings: list[dict] | None = None,
        message: str = "",
        stderr_tail: str = "",
        missing: list[str] | None = None,
        expired_ignore: list[dict] | None = None,
        suppressed_count: int = 0,
        severity: tuple[str, ...] = DEFAULT_SEVERITY,
        duration_s: float = 0.0,
        downgraded: bool = False,
    ) -> None:
        if status not in STATUS_EXIT:
            raise ValueError(f"invalid status: {status}")
        self.status = status
        self.target = target
        self.scanner = scanner
        self.findings = findings or []
        self.message = message
        self.stderr_tail = stderr_tail
        self.missing = missing or []
        self.expired_ignore = expired_ignore or []
        self.suppressed_count = suppressed_count
        self.severity = tuple(severity)
        self.duration_s = duration_s
        self.downgraded = downgraded  # True only when --allow-infra-failure applied
        # The CLI may override the natural exit code (infra-failure -> 0 in
        # AUDIT mode). None here means "use STATUS_EXIT[self.status]".
        self._exit_code: int | None = None

    @property
    def exit_code(self) -> int:
        return self._exit_code if self._exit_code is not None else STATUS_EXIT[self.status]

    def with_downgrade(self) -> "ScanReport":
        """AUDIT-only: mark this infra-failure report as downgraded to exit 0."""
        if self.status != "infra-failure":
            return self
        self.downgraded = True
        self._exit_code = EXIT_OK
        return self

    def to_dict(self) -> dict:
        return {
            "mode": "scan",
            "status": self.status,
            "exit_code": self.exit_code,
            "downgraded": self.downgraded,
            "scanner": self.scanner,
            "target": self.target,
            "severity": list(self.severity),
            "findings": self.findings,
            "suppressed_count": self.suppressed_count,
            "missing_scanners": self.missing,
            "expired_ignore": self.expired_ignore,
            "message": self.message,
            "stderr_tail": self.stderr_tail,
            "duration_s": round(self.duration_s, 3),
        }


# ---------------------------------------------------------------- helpers


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def _tail(text: str, n: int = STDERR_TAIL_CHARS) -> str:
    return text if len(text) <= n else text[-n:]


def _decode(data: bytes, tail: bool = False) -> str:
    """Decode scanner bytes; invalid sequences become U+FFFD (never crash)."""
    text = data.decode("utf-8", errors="replace")
    return _tail(text) if tail else text


def _resolve_tool(name: str, envvar: str) -> tuple[Path | None, str]:
    """Return (binary path or None, provenance) for one scanner name.

    Order: the dedicated env var ($AIWB_TRIVY_PATH / $AIWB_GITLEAKS_PATH)
    first, then PATH discovery. An env var that names a missing file counts
    as 'not found' but keeps the attempted path visible in the reason string.
    """
    env = os.environ.get(envvar)
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p, f"{envvar}={env}"
        return None, f"{envvar}={env} (file not found)"
    found = shutil.which(name)
    if found:
        return Path(found), f"PATH:{found}"
    return None, f"{name} not on PATH"


def _command_for(bin_path: Path, argv: list[str]) -> list[str]:
    """Build the argv array. No shell is ever involved."""
    if bin_path.suffix.lower() == ".py":
        return [sys.executable, str(bin_path), *argv]
    return [str(bin_path), *argv]


def _proc(cmd: list[str], timeout_s: int):
    """Run argv-array subprocess; normalized to a CompletedProcess-like dict."""
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": -1,
            "stdout": b"",
            "stderr": (exc.stderr or b""),
            "_message": f"scanner timed out after {timeout_s}s",
        }
    except OSError as exc:
        return {
            "returncode": -1,
            "stdout": b"",
            "stderr": str(exc).encode("utf-8", "replace"),
            "_message": f"scanner could not be executed: {exc}",
        }


def _stderr_tail(res) -> str:
    if isinstance(res, dict):
        return _decode(res.get("stderr", b""), tail=True)
    return _decode(res.stderr, tail=True)


def _proc_message(res) -> str | None:
    return res.get("_message") if isinstance(res, dict) else None


# ---------------------------------------------------------------- parsing


def _normalize_severity(value: str | None, default: str) -> str:
    sev = (value or default).upper()
    return sev if sev in SEVERITIES else default


def _trivy_findings(doc: dict) -> list[dict]:
    out: list[dict] = []
    for r in doc.get("Results") or []:
        target = r.get("Target", "") or ""
        for s in r.get("Secrets") or []:
            out.append({
                "scanner": "trivy",
                "rule": s.get("RuleID") or "secret",
                "severity": _normalize_severity(s.get("Severity"), "HIGH"),
                "target": target,
                "line": s.get("Line"),
                "id": s.get("RuleID") or ("secret@" + target),
            })
        for m in r.get("Misconfigurations") or []:
            out.append({
                "scanner": "trivy",
                "rule": m.get("AVDID") or "misconfig",
                "severity": _normalize_severity(m.get("Severity"), "MEDIUM"),
                "target": target,
                "line": m.get("StartLine"),
                "id": m.get("AVDID") or ("misconfig@" + target),
            })
        for lic in r.get("Licenses") or []:
            out.append({
                "scanner": "trivy",
                "rule": lic.get("ID") or lic.get("Name") or "license",
                "severity": _normalize_severity(lic.get("Severity"), "LOW"),
                "target": target,
                "line": lic.get("Line"),
                "id": lic.get("ID") or (lic.get("Name") or ("license@" + target)),
            })
        for v in r.get("Vulnerabilities") or []:
            out.append({
                "scanner": "trivy",
                "rule": v.get("VulnerabilityID") or "vuln",
                "severity": _normalize_severity(v.get("Severity"), "MEDIUM"),
                "target": v.get("Target") or target,
                "line": v.get("StartLine"),
                "id": v.get("VulnerabilityID") or ("vuln@" + target),
            })
    return out


def _parse_trivy(res, timeout_s: int) -> tuple[str, list[dict], str, str]:
    """Return (status, findings, message, stderr_tail) for one trivy run."""
    if res.returncode != 0:
        msg = _proc_message(res) or (
            f"trivy exited {res.returncode} (crash or DB download failure; "
            "stderr tail below)")
        return "infra-failure", [], msg, _stderr_tail(res)
    text = _decode(res.stdout)
    try:
        doc = json.loads(text)
    except ValueError:
        return ("infra-failure", [],
                "trivy exited 0 but stdout was not valid JSON "
                "(unexpected tool output)", _tail(text))
    if not isinstance(doc, dict):
        return ("infra-failure", [],
                "trivy JSON root is not an object", _tail(text))
    return "clean", _trivy_findings(doc), "", ""


def _gitleaks_findings(report: list[dict]) -> list[dict]:
    out: list[dict] = []
    for f in report:
        out.append({
            "scanner": "gitleaks",
            "rule": f.get("RuleID") or "leak",
            "severity": "HIGH",  # gitleaks reports no per-finding severity
            "target": f.get("File") or "",
            "line": f.get("StartLine"),
            "id": f.get("Fingerprint") or (f.get("RuleID") or "leak"),
        })
    return out


def _parse_gitleaks(res, report_path: Path) -> tuple[str, list[dict], str, str]:
    if res.returncode != 0:
        msg = _proc_message(res) or (
            f"gitleaks exited {res.returncode} (crash; stderr tail below)")
        return "infra-failure", [], msg, _stderr_tail(res)
    if not report_path.is_file():
        return ("infra-failure", [],
                "gitleaks exited 0 but wrote no report file", "")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return ("infra-failure", [], f"gitleaks report unreadable: {exc}", "")
    if not isinstance(report, list):
        return ("infra-failure", [], "gitleaks report JSON root is not a list", "")
    return "clean", _gitleaks_findings(report), "", ""


# ---------------------------------------------------------------- .securityignore


def _load_ignore(target: Path) -> tuple[list[dict], list[dict]]:
    """Read .securityignore at the scan root.

    Returns (active_exceptions, expired_exceptions). An entry whose
    ``expires`` (YYYY-MM-DD) is strictly before today is expired: it does NOT
    suppress its id and is surfaced in the report. A malformed file raises
    ValueError so the caller fails closed.
    """
    path = target / IGNORE_FILE
    if not path.is_file():
        return [], []
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"{IGNORE_FILE} in {target} is unreadable: {exc}")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError(f"{IGNORE_FILE} in {target} is not valid JSON: {exc}")
    if not isinstance(data, list):
        raise ValueError(f"{IGNORE_FILE} in {target} must be a JSON array")
    today = date.today().isoformat()
    active: list[dict] = []
    expired: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError(
                f"{IGNORE_FILE} in {target} has an invalid entry: {entry!r} "
                "(each entry must be {{\"id\": str, \"reason\": str, "
                "\"expires\": \"YYYY-MM-DD\"}})")
        expires = entry.get("expires")
        if isinstance(expires, str) and expires < today:
            expired.append(entry)
            continue
        active.append(entry)
    return active, expired


def _apply_ignore(findings: list[dict], active: list[dict]) -> tuple[list[dict], int]:
    suppressed_ids = {e["id"] for e in active}
    kept = [f for f in findings if f.get("id") not in suppressed_ids]
    return kept, len(findings) - len(kept)


# ---------------------------------------------------------------- scan / licenses


def scan(
    target_dir,
    *,
    scanners: tuple[str, ...] = DEFAULT_SCANNERS,
    severity: tuple[str, ...] = DEFAULT_SEVERITY,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    trivy_scanners: tuple[str, ...] = TRIVY_SCANNERS,
) -> ScanReport:
    """Scan one directory tree with the requested scanner tools.

    Honest aggregation rule (documented in the module docstring):
      1. any infra-failure wins  -> infra-failure (exit 3)
      2. findings (after .securityignore) -> findings (exit 1)
      3. any requested scanner missing -> tool-missing (exit 3), even if a
         present scanner came back clean: partial coverage is NOT "green"
      4. otherwise -> clean
    """
    target = Path(target_dir)
    if not target.is_dir():
        raise FileNotFoundError(f"target does not exist: {target}")
    sev = tuple(s.upper() for s in severity if s)
    bad = [s for s in sev if s not in SEVERITIES]
    if bad:
        raise ValueError(f"unknown severity level(s): {bad}")
    if not scanners:
        raise ValueError("at least one scanner is required")
    unknown = [s for s in scanners if s not in SUPPORTED_SCANNERS]
    if unknown:
        raise ValueError(f"unsupported scanner(s): {unknown}")
    if timeout_s <= 0:
        raise ValueError("timeout must be a positive number of seconds")
    if not trivy_scanners:
        raise ValueError("trivy scanner categories must not be empty")

    started = time.monotonic()
    # Validate/fail closed on a malformed .securityignore BEFORE any scanner
    # runs, so a broken exceptions file can never silently disable filtering.
    active, expired = _load_ignore(target)
    env_var = {"trivy": "AIWB_TRIVY_PATH", "gitleaks": "AIWB_GITLEAKS_PATH"}
    per: list[dict] = []
    for name in scanners:
        bin_path, why = _resolve_tool(name, env_var[name])
        if bin_path is None:
            per.append({
                "name": name, "status": "tool-missing", "findings": [],
                "message": why, "stderr_tail": ""})
            continue
        status, findings, message, stderr_tail = _run_one(
            name, bin_path, target, sev, timeout_s, trivy_scanners)
        per.append({
            "name": name, "status": status, "findings": findings,
            "message": message, "stderr_tail": stderr_tail})

    merged = [f for p in per for f in p.get("findings", [])]
    findings, suppressed = _apply_ignore(merged, active)

    statuses = {p["status"] for p in per}
    has_findings = bool(findings)
    has_infra = "infra-failure" in statuses
    has_missing = "tool-missing" in statuses
    any_ran = bool(("clean" in statuses) or ("findings" in statuses))

    if has_infra:
        status = "infra-failure"
    elif has_findings:
        status = "findings"
    elif has_missing:
        status = "tool-missing"
    elif any_ran:
        status = "clean"
    else:
        status = "tool-missing"

    messages = "; ".join(p["message"] for p in per if p["message"])
    stderr_tails = " | ".join(
        _tail(p["stderr_tail"]) for p in per if p["stderr_tail"])
    missing = [p["name"] for p in per if p["status"] == "tool-missing"]
    ran = [p["name"] for p in per if p["status"] in ("clean", "findings")]
    scanner_label = ",".join(ran or missing)
    duration = time.monotonic() - started
    return ScanReport(
        status,
        target=str(target),
        scanner=scanner_label,
        findings=findings,
        message=messages,
        stderr_tail=stderr_tails,
        missing=missing,
        expired_ignore=expired,
        suppressed_count=suppressed,
        severity=sev,
        duration_s=duration,
    )


def _run_one(
    name: str,
    bin_path: Path,
    target: Path,
    severity: tuple[str, ...],
    timeout_s: int,
    trivy_scanners: tuple[str, ...] = TRIVY_SCANNERS,
) -> tuple[str, list[dict], str, str]:
    if name == "trivy":
        argv = [
            "fs", "--quiet", "--format", "json",
            "--scanners", ",".join(trivy_scanners),
            "--severity", ",".join(severity),
            str(target),
        ]
        res = _proc(_command_for(bin_path, argv), timeout_s)
        return _parse_trivy(res, timeout_s)
    if name == "gitleaks":
        with tempfile.TemporaryDirectory() as td:
            report_path = Path(td) / "gitleaks-report.json"
            argv = [
                "detect", "--source", str(target),
                "--report-format", "json", "--report-path", str(report_path),
                "--no-banner", "--exit-code", "0",
            ]
            res = _proc(_command_for(bin_path, argv), timeout_s)
            return _parse_gitleaks(res, report_path)
    raise ValueError(f"unsupported scanner: {name}")


def licenses(target_dir) -> dict:
    """Deterministic local license inventory of ``vendor/``.

    Every package directory directly under vendor/ must carry at least one
    LICENSE*/NOTICE* file. Also records whether vendor/ecc/MANIFEST.sha256
    is present (provenance pin). No scanner, no network. Returns
    {"inventory", "findings", "checked", "missing"} where each finding has the
    normalized finding shape (scanner=license-inventory) so .securityignore
    filtering by id still applies.
    """
    target = Path(target_dir)
    if not target.is_dir():
        raise FileNotFoundError(f"target does not exist: {target}")
    vendor = target / VENDOR_DIR
    inventory: dict[str, dict] = {}
    findings: list[dict] = []
    if vendor.is_dir():
        for pkg in sorted(vendor.iterdir()):
            if not pkg.is_dir():
                continue
            rel = pkg.relative_to(target).as_posix()
            lic = sorted(
                f.relative_to(target).as_posix()
                for f in pkg.iterdir() if f.is_file() and f.name.upper().startswith("LICENSE"))
            notice = sorted(
                f.relative_to(target).as_posix()
                for f in pkg.iterdir() if f.is_file() and f.name.upper().startswith("NOTICE"))
            if not lic and not notice:
                findings.append({
                    "scanner": "license-inventory",
                    "rule": "missing-license-file",
                    "severity": "HIGH",
                    "target": rel,
                    "line": None,
                    "id": f"license-missing:{rel}",
                })
            else:
                inventory[rel] = {
                    "license_files": lic + notice,
                    "manifest": (pkg / "MANIFEST.sha256").is_file(),
                }
    return {
        "inventory": inventory,
        "findings": findings,
        "checked": len(inventory) + len(findings),
        "missing": len(findings),
    }


# ---------------------------------------------------------------- CLI


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="security_scan", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="directory tree to scan (repo root or a "
                                   "release-assets/dist subtree)")
    ap.add_argument("--json", action="store_true",
                    help="emit a single machine-readable JSON report to stdout")
    ap.add_argument("--scanners", default=",".join(DEFAULT_SCANNERS),
                    help="comma-separated scanner tools to run "
                         "(trivy, gitleaks)")
    ap.add_argument("--severity", default=",".join(DEFAULT_SEVERITY),
                    help="comma-separated severity threshold list passed to trivy")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S,
                    help=f"seconds before a scan is aborted (default {DEFAULT_TIMEOUT_S})")
    ap.add_argument("--trivy-scanners", default=",".join(TRIVY_SCANNERS),
                    help="trivy analyzer categories (default "
                         "secret,misconfig,license,vuln)")
    ap.add_argument("--licenses", action="store_true",
                    help="run the deterministic vendor/ license inventory "
                         "(no scanner binary or network required)")
    ap.add_argument("--allow-infra-failure", action="store_true",
                    help="AUDIT-ONLY: downgrade infra-failure exit 3 to 0 with "
                         "a loud warning. Never set in release/blocking mode.")
    return ap.parse_args(argv)


def _emit(report: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(report["exit_code"])
    status = report["status"]
    if "findings" in report:
        for f in report["findings"]:
            loc = f" (line {f['line']})" if f.get("line") is not None else ""
            print(f"  [{f['severity']}] {f['scanner']} {f['rule']} "
                  f"{f['target']}{loc}")
    if report.get("missing_scanners"):
        print("missing scanners: " + ", ".join(report["missing_scanners"]))
    for e in report.get("expired_ignore", []):
        print(f"  expired .securityignore entry ignored (id={e.get('id')}, "
              f"reason={e.get('reason')!r}, expires={e.get('expires')}) "
              "-- the finding it would suppress remains ACTIVE")
    if report.get("stderr_tail"):
        print(f"scanner stderr tail: {report['stderr_tail']!r}")
    if report.get("message"):
        print(f"note: {report['message']}")
    print(f"status={status} exit={report['exit_code']}")
    return int(report["exit_code"])


def _cmd_scan(args: argparse.Namespace, target: Path) -> int:
    try:
        report = scan(
            target,
            scanners=tuple(s.strip() for s in args.scanners.split(",") if s.strip()),
            severity=tuple(s.strip() for s in args.severity.split(",") if s.strip()),
            timeout_s=args.timeout,
            trivy_scanners=tuple(
                s.strip() for s in args.trivy_scanners.split(",") if s.strip()),
        )
    except ValueError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if report.status == "infra-failure" and args.allow_infra_failure:
        report.with_downgrade()
        print(
            "WARNING: infra-failure downgraded to exit 0 by "
            "--allow-infra-failure -- AUDIT mode only; release/blocking "
            "mode must never set this flag",
            file=sys.stderr)
    data = report.to_dict()
    if args.json:
        return _emit(data, as_json=True)
    print(f"security scan: {data['target']}")
    if data["findings"]:
        print(f"findings ({len(data['findings'])}):")
    return _emit(data, as_json=False)


def _cmd_licenses(args: argparse.Namespace, target: Path) -> int:
    try:
        result = licenses(target)
        active, expired = _load_ignore(target)
        findings, suppressed = _apply_ignore(result["findings"], active)
    except ValueError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    status = "findings" if findings else "clean"
    payload = {
        "mode": "licenses",
        "status": status,
        "exit_code": EXIT_FINDINGS if findings else EXIT_OK,
        "inventory": result["inventory"],
        "findings": findings,
        "suppressed_count": suppressed,
        "expired_ignore": expired,
        "checked_dirs": result["checked"],
    }
    if args.json:
        return _emit(payload, as_json=True)
    print(f"license inventory: {target}")
    for rel, meta in sorted(result["inventory"].items()):
        manifest = " manifest" if meta["manifest"] else " (no MANIFEST.sha256)"
        print(f"  {rel}: {len(meta['license_files'])} license file(s){manifest}")
    for f in payload["findings"]:
        print(f"  [HIGH] {f['rule']} {f['target']}")
    for e in payload["expired_ignore"]:
        print(f"  expired .securityignore entry ignored (id={e.get('id')})")
    print(f"status={status} exit={payload['exit_code']}")
    return payload["exit_code"]


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    try:
        args = _parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or EXIT_OK)
    target = Path(args.target).expanduser()
    if not target.is_dir():
        print(f"usage error: target directory does not exist: {args.target}",
              file=sys.stderr)
        return EXIT_USAGE
    if args.timeout <= 0:
        print("usage error: --timeout must be a positive number of seconds",
              file=sys.stderr)
        return EXIT_USAGE
    try:
        if args.licenses:
            return _cmd_licenses(args, target)
        return _cmd_scan(args, target)
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except OSError:
            pass
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())