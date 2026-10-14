"""Fleet client (ops-owned, hash-pinned).

Loads its upstream endpoint from the deploy config, connects, and validates
the service banner. Exit 0 + APP OK on success; non-zero with a reason on
failure.
"""
import json
import socket
import sys
import time
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "deploy.conf"
EXPECTED_BANNER = "FLEET-OK"


def load_upstream() -> tuple[str, int, int, float]:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    host, _, port = cfg["upstream"].partition(":")
    return host, int(port), int(cfg.get("retries", 3)), float(cfg.get("timeout_ms", 1500)) / 1000.0


def probe(host: str, port: int, timeout: float) -> str:
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        data = b""
        while not data.endswith(b"\n") and len(data) < 256:
            chunk = s.recv(256 - len(data))
            if not chunk:
                break
            data += chunk
    return data.decode("utf-8", errors="replace").strip()


def main() -> int:
    host, port, retries, timeout = load_upstream()
    address = f"{host}:{port}"
    for attempt in range(1, retries + 1):
        try:
            banner = probe(host, port, timeout)
        except ConnectionRefusedError:
            print(f"upstream refused: {address} (attempt {attempt}/{retries})")
            time.sleep(0.2)
            continue
        except (socket.timeout, TimeoutError):
            print(f"upstream timeout: {address} (attempt {attempt}/{retries})")
            time.sleep(0.2)
            continue
        except OSError as e:
            print(f"upstream unreachable: {address} ({e})")
            return 1
        if not banner.startswith(EXPECTED_BANNER):
            print(f"unexpected upstream banner from {address}: {banner!r}")
            return 1
        print("APP OK")
        return 0
    print(f"upstream refused: {address}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
