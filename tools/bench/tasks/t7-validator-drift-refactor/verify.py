"""t7-validator-drift-refactor verifier (runs with cwd = agent workspace).

Judges the REAL fix class:
  1. tests/ is untouched (sha256 pins) — the shipped suite cannot be edited
     into passing;
  2. the shipped suite passes (drift eliminated on every code path);
  3. public API signatures are unchanged (load_config / validate_config /
     dump_config);
  4. validation is deduplicated: the report path and the public
     validate_config resolve to rules defined in the SAME module
     (shape-agnostic heuristic — any structure passes as long as both
     paths share one canonical implementation);
  5. CLI smoke: `python -m confcfg check` agrees with the spec.
"""
import hashlib
import importlib
import inspect
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
PINS = {
    "tests/test_behavior.py": "74ff835d22cdd9837f66a3bd3485594e4ecdffa974cfa5d9ac140dedf1fe8476",
}


def _fail(msg: str) -> int:
    print(f"VERIFY FAIL: {msg}")
    return 1


def main() -> int:
    # 1) hash pins on the protected suite
    for rel, want in PINS.items():
        p = ROOT / rel
        if not p.is_file():
            return _fail(f"protected file missing: {rel}")
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got != want:
            return _fail(f"protected file modified: {rel}")

    # 2) shipped suite must pass
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                       capture_output=True, text=True, timeout=240, cwd=ROOT)
    if r.returncode != 0:
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-12:])
        return _fail(f"shipped test suite not green:\n{tail}")

    # 3) public API signatures unchanged
    sys.path.insert(0, str(ROOT))
    for mod in list(sys.modules):
        if mod == "confcfg" or mod.startswith("confcfg."):
            del sys.modules[mod]
    try:
        pkg = importlib.import_module("confcfg")
    except Exception as e:  # noqa: BLE001
        return _fail(f"cannot import confcfg: {e}")
    expected = {
        "load_config": ["path"],
        "validate_config": ["cfg"],
        "dump_config": ["cfg", "path"],
    }
    for name, params in expected.items():
        fn = getattr(pkg, name, None)
        if not callable(fn):
            return _fail(f"public API missing: confcfg.{name}")
        got = [p.name for p in inspect.signature(fn).parameters.values()]
        if got != params:
            return _fail(
                f"public API signature changed: confcfg.{name}({', '.join(got)}) "
                f"!= ({', '.join(params)})")

    # 4) dedup: report path and public API resolve to the same rules module
    try:
        rep = importlib.import_module("confcfg.report")
    except Exception as e:  # noqa: BLE001
        return _fail(f"cannot import confcfg.report: {e}")
    canonical_mod = pkg.validate_config.__module__
    report_fns = [
        v for v in rep.report_config.__globals__.values()
        if callable(v) and getattr(v, "__module__", "").startswith("confcfg")
    ]
    if not any(getattr(f, "__module__", None) == canonical_mod
               for f in report_fns):
        mods = sorted({getattr(f, "__module__", "?") for f in report_fns})
        return _fail(
            f"validation still duplicated: public API uses {canonical_mod} "
            f"but the report path references {mods}")

    # 5) CLI smoke on a port-0 config (the original drift symptom)
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "c.json"
        f.write_text(json.dumps({"server": {"port": 0}}), encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "confcfg", "check", str(f)],
                           capture_output=True, text=True, timeout=60, cwd=ROOT)
        if r.returncode != 0 or r.stdout.strip() != "INVALID: server.port":
            return _fail(
                f"CLI check on port-0 config: rc={r.returncode} "
                f"stdout={r.stdout.strip()!r}")

    print("VERIFY PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
