"""D3c - Caveman voice compression: A/B evidence, then verdict.

Runs the deterministic caveman-transform approximation from `caveman_rules`
over the sample model-output fixtures in `caveman_fixtures`, measures the
token delta with the char/4 proxy, and checks byte-identical retention of
payload (commands / file paths / error codes / numbers).

Use:
    python -m memory_efficiency.caveman_eval            # print table
    python -m pytest experiments/ -q                    # test evidence

This is EVIDENCE for the D3 verdict (SHIPPED / EXPERIMENTAL / REJECTED), not a
routing change. The KNOWN product conflict - ECC/user preference for detailed
Chinese reports - already prescribes default-off in MEASUREMENT.md; the eval
only measures the magnitude of the tradeoff. No model, no network, stdlib only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Make this importable both as a script and under pytest (tests/ inserts the
# same dir): discover the package dir from the file, not the cwd.
_PKG_DIR = Path(__file__).resolve().parent
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from caveman_fixtures import FIXTURES  # noqa: E402
from caveman_rules import TOKENIZER_NOTE, caveman_transform, estimate_tokens, retention_report  # noqa: E402
from session_rank import sanitize_text  # noqa: E402  (reuse the sanitizer for name fields)


def evaluate_caveman(original: str, *, transform=caveman_transform,
                     tokenize=estimate_tokens) -> dict:
    """One fixture -> {tokens, delta_pct, retention_pass, retention}."""
    transformed = transform(original)
    orig_t = tokenize(original)
    new_t = tokenize(transformed)
    delta = orig_t - new_t
    delta_pct = (delta / orig_t * 100.0) if orig_t else 0.0
    retention = retention_report(original, transformed)
    return {
        "original_tokens": orig_t,
        "transformed_tokens": new_t,
        "token_delta": delta,
        "token_delta_pct": round(delta_pct, 2),
        "retention_pass": retention["pass"],
        "retention": retention,
    }


def run_eval(fixtures: list[dict[str, str]] | None = None) -> dict:
    """Evaluate all fixtures and aggregate. Deterministic; returns a dict."""
    rows: list[dict[str, Any]] = []
    for fx in (fixtures or FIXTURES):
        row = evaluate_caveman(fx.get("original", ""))
        row = {"name": sanitize_text(fx.get("name"), max_len=32), **row}
        rows.append(row)
    orig_total = sum(r["original_tokens"] for r in rows)
    new_total = sum(r["transformed_tokens"] for r in rows)
    delta_total = orig_total - new_total
    return {
        "fixtures": rows,
        "totals": {
            "original_tokens": orig_total,
            "transformed_tokens": new_total,
            "token_delta": delta_total,
            "token_delta_pct": round((delta_total / orig_total * 100.0) if orig_total else 0.0, 2),
            "retention_all_pass": all(r["retention_pass"] for r in rows),
        },
    }


def pp_print(result: dict) -> None:
    print(f"totals: {result['totals']['original_tokens']} -> "
          f"{result['totals']['transformed_tokens']} tokens "
          f"(delta {result['totals']['token_delta']}, "
          f"{result['totals']['token_delta_pct']}%)")
    print(f"retention_all_pass: {result['totals']['retention_all_pass']}")
    for r in result["fixtures"]:
        print(f"  {r['name']:24} {r['original_tokens']:5} -> {r['transformed_tokens']:5} "
              f"({r['token_delta_pct']:7.2f}%)  retention={'PASS' if r['retention_pass'] else 'FAIL'}")
    print(TOKENIZER_NOTE)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--json" in argv:
        print(json.dumps(run_eval(), ensure_ascii=False, indent=2))
    else:
        pp_print(run_eval())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())