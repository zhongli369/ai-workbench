"""Verify t2: tests pass AND the test file was not modified (hash-pinned)."""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd().resolve()  # the bench workspace (driver runs verify with cwd=workspace)
TEST_SHA256 = "daa0c13f40df1f8c6be3a2d5f3ef43f26e1469ed92d290b3adf63029a2f5bedd"


def fail(msg):
    print(f"VERIFY FAIL: {msg}")
    sys.exit(1)


actual = hashlib.sha256((ROOT / "test_statswin.py").read_bytes()).hexdigest()
if actual != TEST_SHA256:
    fail("test_statswin.py was modified (protected-tests violation)")

out = subprocess.run([sys.executable, "-m", "pytest", "test_statswin.py", "-q"],
                     capture_output=True, text=True, timeout=120, cwd=ROOT)
if out.returncode != 0:
    tail = "\n".join((out.stdout + out.stderr).splitlines()[-6:])
    fail(f"pytest nonzero:\n{tail}")

print("VERIFY PASS")
