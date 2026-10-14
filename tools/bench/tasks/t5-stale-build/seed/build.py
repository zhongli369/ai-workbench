"""build check — fails while the generated asset is stale.

The verifier hash-pins this file: it must not change.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = ROOT / "src" / "manifest.json"
GENERATED = ROOT / "assets.gen.json"


def manifest_hash() -> str:
    return hashlib.sha256(MANIFEST.read_bytes()).hexdigest()[:12]


def main() -> int:
    if not GENERATED.is_file():
        print("BUILD FAIL: assets.gen.json missing (stale or never generated)")
        return 1
    gen = json.loads(GENERATED.read_text(encoding="utf-8"))
    if gen.get("src_hash") != manifest_hash():
        print("BUILD FAIL: stale generated file (src changed after generation)")
        return 1
    print("BUILD OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
