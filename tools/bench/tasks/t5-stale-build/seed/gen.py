"""generator — (re)create assets.gen.json from src/manifest.json.

The verifier hash-pins this file: it must not change.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = ROOT / "src" / "manifest.json"
GENERATED = ROOT / "assets.gen.json"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = {
        "src_hash": hashlib.sha256(MANIFEST.read_bytes()).hexdigest()[:12],
        "assets": [f"{name}.min.js" for name in manifest["entries"]],
    }
    GENERATED.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"generated {GENERATED.name} ({len(out['assets'])} assets)")


if __name__ == "__main__":
    main()
