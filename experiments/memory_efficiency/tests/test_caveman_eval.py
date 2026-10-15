"""Contract tests for D3 caveman eval. Run: python -m pytest experiments/ -q

Hermetic: stdlib only. Tests both the deterministic transform (retention /
shrink) and the token-delta measurement shape.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caveman_eval import evaluate_caveman, run_eval
from caveman_fixtures import FIXTURES
from caveman_rules import (TOKENIZER_PROXY, caveman_transform, estimate_tokens,
                           retention_report)
from session_rank import sanitize_text


def _fx(name):
    return next(fx["original"] for fx in FIXTURES if fx["name"] == name)


def test_proxy_tokenizer():
    assert TOKENIZER_PROXY == "chars4"
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcdefgh") == 2
    assert estimate_tokens("a" * 300) == 75


def test_chatty_help_shrinks():
    original, transformed = _fx("chatty_help"), caveman_transform(_fx("chatty_help"))
    assert len(transformed) < len(original)
    assert transformed != original


def test_already_terse_stays_terse():
    original, transformed = _fx("already_terse"), caveman_transform(_fx("already_terse"))
    # Caveman on already-plain text must not add tokens and barely shrinks.
    assert len(transformed) <= len(original)


def test_payload_survives_byte_identical():
    for fx in FIXTURES:
        original = fx["original"]
        transformed = caveman_transform(original)
        report = retention_report(original, transformed)
        assert report["pass"], fx["name"]
        assert report["payload_spans"] > 0, fx["name"]  # fixture has payload


def test_commands_paths_errors_numbers_retained_on_representative():
    original = (
        "Sure! Just run `npm run test` at C:\\Users\\dev\\auth-service and "
        "check that the count is 128 with 0 failures. If you see HTTP 503 or "
        "the error `Error 1045`, inspect /var/log/service/errors.log. "
        "Hope this helps!"
    )
    transformed = caveman_transform(original)
    for payload in ("`npm run test`", "C:\\Users\\dev\\auth-service", "128",
                    "HTTP 503", "`Error 1045`", "/var/log/service/errors.log"):
        assert payload in transformed, payload
    assert "128" in transformed and "0 failures" in transformed


def test_evaluate_caveman_shape():
    result = evaluate_caveman(_fx("technical_brief"))
    assert result["original_tokens"] > result["transformed_tokens"]
    assert result["token_delta"] == result["original_tokens"] - result["transformed_tokens"]
    assert result["retention_pass"] is True
    assert result["token_delta_pct"] > 0


def test_determinism():
    original = _fx("chatty_help")
    a, b = caveman_transform(original), caveman_transform(original)
    assert a == b
    r1, r2 = run_eval(), run_eval()
    assert r1 == r2


def test_payload_heavy_delta_is_small_but_retention_ok():
    result = evaluate_caveman(_fx("payload_heavy"))
    assert result["retention_pass"] is True
    # Mostly payload: prose ceremony is a small part of the fixture => the
    # measured delta should be a modest positive or zero, never a "win" that
    # breaks payload.
    assert result["token_delta_pct"] < 50.0


def test_mixed_zh_prose_keeps_style_and_payload():
    result = evaluate_caveman(_fx("mixed_zh_prose_retained"))
    assert result["retention_pass"] is True
    # English ceremony ("Hope this helps!") is compressible; the Chinese prose
    # is left intact (caveman rule 8: style, not language).
    transformed = caveman_transform(_fx("mixed_zh_prose_retained"))
    assert "希望你先运行" in transformed
    assert "Hope this helps" not in transformed.casefold()