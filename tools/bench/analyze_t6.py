"""Analyze batch3_t6_quad.json against the PHASE P verdict frame.

Reads the four-arm result and prints:
  - the arm matrix (success / cost / turns / oracle queries);
  - layer-2 verdict: did the fail-triggered policy fire on a real failure?
    (fusion empty-store arm is the mechanism control — its agent MUST hit
    the 'upstream refused' failure, so queries>0 proves trigger-on-failure);
  - layer-3 verdict: oracle isolation (fusion-seeded vs fusion) and
    overall deltas vs native/ecc;
  - the P4 fate recommendation implied by the verdict matrix (advisory —
    the human makes the call).

Usage: python tools/bench/analyze_t6.py [path-to-batch3_t6_quad.json]
"""
import json
import sys
from pathlib import Path

DEFAULT = Path(__file__).parent / "results" / "batch3_t6_quad.json"


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    data = json.loads(path.read_text(encoding="utf-8"))
    arms = data["arms"]

    print(f"task: {data['task']}  model: {data['model']}  ts: {data['ts']}")
    print(f"{'arm':<15} {'ok':<4} {'cost':>8} {'turns':>6} {'queries':>8} {'tampered':>9}")
    for name, r in arms.items():
        print(f"{name:<15} {str(r['success']):<4} ${r['cost'] or 0:>7.4f} "
              f"{r['turns'] or 0:>6} {r['oracle_queries']:>8} "
              f"{str(r['verify_tampered']):>9}")

    for name, r in arms.items():
        if r["verify_tampered"]:
            print(f"\n!! {name}: verify script tampered — result void")
    if not all(r["success"] for r in arms.values()):
        print("\n!! not all arms passed verify — read verify_tail before verdicts")
        for name, r in arms.items():
            if not r["success"]:
                print(f"  {name}: {r['verify_tail'][:300]}")

    q_empty = arms["fusion"]["oracle_queries"]
    q_seed = arms["fusion-seeded"]["oracle_queries"]
    c_empty = arms["fusion"]["cost"] or 0
    c_seed = arms["fusion-seeded"]["cost"] or 0
    t_empty = arms["fusion"]["turns"] or 0
    t_seed = arms["fusion-seeded"]["turns"] or 0

    print("\n--- layer 2 (trigger on real failure) ---")
    if q_empty > 0:
        print(f"TRIGGERED: fusion empty-store arm queried {q_empty}x — the "
              f"fail-triggered policy fires on a real failure (fast-negative)")
    else:
        print("NOT TRIGGERED: fusion empty-store arm never queried despite an "
              "unavoidable failure — policy-layer defect (not 'not needed')")

    print("\n--- layer 3 (oracle isolation: fusion-seeded vs fusion) ---")
    print(f"queries: seeded={q_seed} empty={q_empty}")
    print(f"cost:    seeded=${c_seed:.4f} empty=${c_empty:.4f} "
          f"delta=${c_seed - c_empty:+.4f}")
    print(f"turns:   seeded={t_seed} empty={t_empty} delta={t_seed - t_empty:+d}")
    print(f"native=${arms['native']['cost'] or 0:.4f}/{arms['native']['turns']}t  "
          f"ecc=${arms['ecc']['cost'] or 0:.4f}/{arms['ecc']['turns']}t")

    print("\n--- P4 fate (advisory) ---")
    if q_empty == 0:
        print("queries=0 on the mechanism control → REMOVE_OR_REPLACE or build "
              "the §1.5 closable structural trigger, then re-judge")
    elif q_seed > 0 and (c_seed < c_empty * 0.9 or t_seed < t_empty - 1):
        print("triggered AND attributable benefit (seeded cheaper/faster) → "
              "KEEP_OPTIONAL eligible (N=1, exploratory)")
    elif q_seed > 0:
        print("triggered, hit the seed, no measurable delta → stay EXPERIMENTAL")
    else:
        print("control triggered but treatment never queried → investigate "
              "seed reachability before any fate change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
