"""Verify t3b: total works, reader untouched, store migrated (payload kept)."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd().resolve()  # the bench workspace (driver runs verify with cwd=workspace)
INV_SHA256 = "9e5d82845f3b4834b4c519dabfb3928d9c2bc0ccec90d90eaf691c76f737cb42"


def fail(msg):
    print(f"VERIFY FAIL: {msg}")
    sys.exit(1)


inv = ROOT / "inv.py"
state = ROOT / "inv_state.json"
if not inv.is_file():
    fail("inv.py missing")
if hashlib.sha256(inv.read_bytes()).hexdigest() != INV_SHA256:
    fail("inv.py was modified (reader is hash-pinned)")

out = subprocess.run([sys.executable, str(inv), "total"],
                     capture_output=True, text=True, timeout=30, cwd=ROOT)
if out.returncode != 0:
    fail(f"total still crashes: {out.stderr.strip()[:200]!r}")
if "total: 12" not in out.stdout:
    fail(f"total output wrong (payload lost?): {out.stdout!r}")

data = json.loads(state.read_text(encoding="utf-8"))
if data.get("revision") != 3:
    fail("inv_state.json was not migrated to revision 3")
if len(data.get("items", [])) != 3:
    fail("inv_state.json lost items in migration")

print("VERIFY PASS")
