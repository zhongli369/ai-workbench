"""Verify t4: --json flag added to list, text output unchanged, add intact,
README documents the flag."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd().resolve()  # the bench workspace (driver runs verify with cwd=workspace)
CLI = ROOT / "cli.py"
DB = ROOT / "inventory.json"


def fail(msg):
    print(f"VERIFY FAIL: {msg}")
    sys.exit(1)


def run(*argv):
    return subprocess.run([sys.executable, str(CLI), *argv],
                          capture_output=True, text=True, timeout=30, cwd=ROOT)


DB.unlink(missing_ok=True)  # fresh DB for deterministic assertions

if run("add", "pen", "4", "1.5").returncode != 0:
    fail("add pen failed")
if run("add", "book", "1", "12.0").returncode != 0:
    fail("add book failed")

out = run("list", "--json")
if out.returncode != 0:
    fail(f"list --json rc={out.returncode} err={out.stderr[:200]!r}")
try:
    rows = json.loads(out.stdout)
except json.JSONDecodeError:
    fail(f"list --json stdout not pure JSON: {out.stdout[:120]!r}")
if not isinstance(rows, list) or len(rows) != 2:
    fail(f"expected 2 rows, got {rows!r}")
for row in rows:
    if set(row.keys()) != {"name", "qty", "price"}:
        fail(f"bad keys: {row!r}")
if rows[0] != {"name": "pen", "qty": 4, "price": 1.5}:
    fail(f"row0 mismatch: {rows[0]!r}")

text = run("list")
if text.returncode != 0 or text.stdout.lstrip().startswith("["):
    fail("text list output changed or broken")
if "pen" not in text.stdout or "book" not in text.stdout:
    fail(f"text list missing items: {text.stdout!r}")

readme = (ROOT / "README.md").read_text(encoding="utf-8")
if "--json" not in readme:
    fail("README does not document --json")

print("VERIFY PASS")
