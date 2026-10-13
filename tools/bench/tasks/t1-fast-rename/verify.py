"""Verify t1: total_price renamed to compute_total everywhere, behavior kept."""
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd().resolve()  # the bench workspace (driver runs verify with cwd=workspace)


def fail(msg):
    print(f"VERIFY FAIL: {msg}")
    sys.exit(1)


for fname in ("calc.py", "main.py"):
    src = (ROOT / fname).read_text(encoding="utf-8")
    if "total_price" in src:
        fail(f"{fname} still references total_price")
    if "compute_total" not in src:
        fail(f"{fname} lacks compute_total")

sys.path.insert(0, str(ROOT))
import calc  # noqa: E402

if hasattr(calc, "total_price"):
    fail("calc.total_price still exists")
if abs(calc.compute_total([("pen", 1.5, 4), ("book", 12.0, 1)]) - 18.0) > 1e-9:
    fail("compute_total returns wrong value")
if abs(calc.discount(100.0, 10) - 90.0) > 1e-9:
    fail("discount behavior changed")

out = subprocess.run([sys.executable, str(ROOT / "main.py")],
                     capture_output=True, text=True, timeout=30)
if out.returncode != 0 or "total: 18.0" not in out.stdout:
    fail(f"main.py run: rc={out.returncode} out={out.stdout!r} err={out.stderr[:200]!r}")

print("VERIFY PASS")
