#!/usr/bin/env python3
"""ECC provenance check. Two modes, both offline-capable:

1. default (CI mode): verify the bundled snapshot still matches the SHA-256
   manifest recorded at RC build time (tamper / accidental-edit detector).
2. --upstream PATH: additionally hash-compare every paired file against a
   local clone of github.com/affaan-m/everything-claude-code and verify the
   pinned commit exists there. This is the command a reviewer runs to
   re-verify provenance without any network.

Exit 1 on any mismatch.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

RC = Path(__file__).resolve().parent.parent
MANIFEST = RC / "vendor" / "ecc" / "MANIFEST.sha256"
ECC_DIRS = ("skills", "agents", "commands")
SELF_DEVELOPED = {  # not from upstream; everything else must pair
    "skills/experience-capture/SKILL.md",
    "skills/failure-oracle/SKILL.md",
    "skills/workbench/SKILL.md",
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build_manifest() -> dict:
    files = {}
    for kind in ECC_DIRS:
        base = RC / "workbench" / ".claude" / kind
        for f in sorted(base.rglob("*")):
            # incidental bytecode caches are not part of the vendored snapshot
            if f.is_dir() or f.name.startswith(".") or "__pycache__" in f.parts:
                continue
            rel = f"{kind}/{f.relative_to(base)}".replace("\\", "/")
            files[rel] = sha(f)
    return files


def cmd_record() -> int:
    files = build_manifest()
    MANIFEST.write_text(json.dumps(files, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"recorded {len(files)} file hashes -> {MANIFEST.relative_to(RC)}")
    return 0


def cmd_verify(upstream: Path | None) -> int:
    if not MANIFEST.is_file():
        print("FAIL: MANIFEST.sha256 missing — run with --record first")
        return 1
    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    current = build_manifest()
    bad = []
    for rel, h in recorded.items():
        if rel not in current:
            bad.append(f"missing: {rel}")
        elif current[rel] != h:
            bad.append(f"modified: {rel}")
    for rel in current:
        if rel not in recorded:
            bad.append(f"added: {rel}")
    if bad:
        print("FAIL: snapshot drift vs MANIFEST.sha256:")
        for b in bad:
            print(" ", b)
        return 1
    print(f"manifest OK ({len(recorded)} files)")

    if upstream:
        upstream = Path(upstream)
        if not (upstream / ".git").is_dir():
            print(f"FAIL: --upstream {upstream} is not a git clone")
            return 1
        mism, paired = [], 0
        for rel, h in recorded.items():
            if rel in SELF_DEVELOPED:
                continue
            kind, sub = rel.split("/", 1)
            up = upstream / kind / sub
            if not up.is_file():
                mism.append(f"not in upstream: {rel}")
            elif sha(up) != h:
                mism.append(f"differs from upstream: {rel}")
            else:
                paired += 1
        pin = json.loads((RC / "vendor" / "ecc" / "VERSION").read_text(
            encoding="utf-8"))["commit"]
        r = subprocess.run(["git", "cat-file", "-t", pin], cwd=upstream,
                           capture_output=True, text=True)
        if r.returncode != 0 or r.stdout.strip() != "commit":
            mism.append(f"pin {pin[:12]} not found in upstream clone")
        if mism:
            print("FAIL: upstream comparison:")
            for m in mism:
                print(" ", m)
            return 1
        print(f"upstream OK ({paired} files identical, pin {pin[:12]} present)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--record", action="store_true",
                    help="(maintainer) record current snapshot hashes")
    ap.add_argument("--upstream", default=None,
                    help="path to a local everything-claude-code clone")
    a = ap.parse_args()
    if a.record:
        return cmd_record()
    return cmd_verify(Path(a.upstream) if a.upstream else None)


if __name__ == "__main__":
    sys.exit(main())
