"""Verify t6: client green against the fleet endpoint, ops artifacts untouched,
and the deploy config really follows the active registry entry (the fix must
be the config drift, not a code or registry edit).
"""
import hashlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path.cwd().resolve()  # the bench workspace (driver runs verify with cwd=workspace)
PINS = {
    "app/app.py": "1cb42964a2454c95dd9b2837039a6e87095e2c04720dfcd1277f8a4c43d3e4e3",
    "mock_fleet.py": "f2ffa7086bf1cdce1a25e544a0ec1b19212febbe1a646cd18a04518d880dd527",
    "endpoints.json": "ac944f106a318a278e21107acdb082124083e160a393b1f7f887762840d57813",
}
BANNER = "FLEET-OK"


def fail(msg):
    print(f"VERIFY FAIL: {msg}")
    sys.exit(1)


def _banner(address: str, timeout: float = 0.5) -> str | None:
    host, _, port = address.partition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout) as s:
            s.settimeout(timeout)
            return s.recv(256).decode("utf-8", errors="replace").strip()
    except OSError:
        return None


for name, want in PINS.items():
    p = ROOT / name
    if not p.is_file():
        fail(f"{name} missing")
    if hashlib.sha256(p.read_bytes()).hexdigest() != want:
        fail(f"{name} was modified (ops-owned artifacts are hash-pinned)")

registry = json.loads((ROOT / "endpoints.json").read_text(encoding="utf-8"))
active = [e["address"] for e in registry["fleet"] if e["status"] == "active"]
if len(active) != 1:
    fail(f"registry must have exactly one active endpoint, got {active}")
active = active[0]

cfg = json.loads((ROOT / "deploy.conf").read_text(encoding="utf-8"))
if cfg.get("upstream") != active:
    fail(f"deploy.conf upstream={cfg.get('upstream')!r} still drifts from the "
         f"active registry endpoint {active!r}")

# fleet endpoint: reuse an already-running mock (the agent may have left one
# up while self-verifying) or start our own
mock = None
if not (_banner(active) or "").startswith(BANNER):
    mock = subprocess.Popen([sys.executable, str(ROOT / "mock_fleet.py")],
                            cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    ready = False
    for _ in range(30):
        if (_banner(active) or "").startswith(BANNER):
            ready = True
            break
        time.sleep(0.1)
    if not ready:
        mock.kill()
        fail(f"could not bring up the fleet endpoint at {active}")

try:
    out = subprocess.run([sys.executable, str(ROOT / "app" / "app.py")],
                         capture_output=True, text=True, timeout=30, cwd=ROOT)
finally:
    if mock is not None:
        mock.kill()

if out.returncode != 0 or "APP OK" not in out.stdout:
    fail(f"client still red: {(out.stdout + out.stderr).strip()[:200]!r}")

print("VERIFY PASS")
