"""Verify t3a: summary works, reader untouched, state migrated (payload kept)."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd().resolve()  # the bench workspace (driver runs verify with cwd=workspace)
APP_SHA256 = "aac701c9ef1b0c92fbbd380312ca8c382328b903a659a4fcbad07cffc9b9f550"


def fail(msg):
    print(f"VERIFY FAIL: {msg}")
    sys.exit(1)


app = ROOT / "app.py"
state = ROOT / "state.json"
if not app.is_file():
    fail("app.py missing")
if hashlib.sha256(app.read_bytes()).hexdigest() != APP_SHA256:
    fail("app.py was modified (reader is hash-pinned)")

out = subprocess.run([sys.executable, str(app), "summary"],
                     capture_output=True, text=True, timeout=30, cwd=ROOT)
if out.returncode != 0:
    fail(f"summary still crashes: {out.stderr.strip()[:200]!r}")
if "idea: 2" not in out.stdout or "todo: 1" not in out.stdout:
    fail(f"summary output wrong (payload lost?): {out.stdout!r}")

data = json.loads(state.read_text(encoding="utf-8"))
if data.get("version") != 2:
    fail("state.json was not migrated to schema v2")
if len(data.get("notes", [])) != 3:
    fail("state.json lost notes in migration")

print("VERIFY PASS")
