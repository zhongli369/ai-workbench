"""Contract tests for D2 turn_gate. Run: python -m pytest experiments/ -q

Hermetic: stdlib only, no IO.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from turn_gate import is_trivial, recall_metrics, should_auto_retrieve

_TRIVIAL = [
    "", "   ", "\n\t", "hi", "hello!", "Hey", "yo", "sup", "thanks :)",
    "thanks", "thank you", "ok", "OK!", "okay", "sure", "yes", "no", "y",
    "n", "yep", "nope", "yeah", "nah", "continue", "go ahead", "do it",
    "proceed", "got it", "cool", "nice", "great", "done", "next", "lgtm",
    "k", "/status", "/help", "/clear", "done???",
]
_NON_TRIVIAL = [
    "fix the auth middleware token expiry check",
    "explain git rebase vs merge",
    "how does X reach Y?",
    "k8s",          # the bare 'k' must NOT match a prefix of 'k8s'
    "note",         # 'n' in the word list must not match 'note'
    "no way to fix this",
    "could you review PR #12",
    "running npm install",
]

_TRUE_CASES = ["hi", "ok", "thanks", "/status", "", "  ", "continue"]


def test_trivial_prompts_skip_auto_retrieval():
    for prompt in _TRIVIAL:
        assert is_trivial(prompt) is True, prompt
        assert should_auto_retrieve(prompt) is False, prompt


def test_normal_prompts_pass_the_gate():
    for prompt in _NON_TRIVIAL:
        assert is_trivial(prompt) is False, prompt
        assert should_auto_retrieve(prompt) is True, prompt


def test_explicit_query_never_blocked():
    # An explicit memory ask is allowed even when the text alone is trivial.
    for prompt in _TRUE_CASES:
        assert is_trivial(prompt, explicit_query=True) is False, prompt
        assert should_auto_retrieve(prompt, explicit_query=True) is True, prompt


def test_recall_metrics_math():
    m = recall_metrics(["a", "b", "c", "d"], {"b", "d", "e"})
    assert m["recalled"] == 4
    assert m["used"] == 2
    assert m["unused"] == 2
    assert m["precision"] == 0.5


def test_recall_metrics_no_injection():
    m = recall_metrics([], ["x"])
    assert m["recalled"] == 0
    assert m["used"] == 0
    assert m["precision"] == 0.0


def test_recall_metrics_used_requires_injected():
    # id referenced but never injected contributes nothing.
    m = recall_metrics(["a"], ["a", "ghost"])
    assert m["used"] == 1
    m2 = recall_metrics([], ["host"])
    assert m2["used"] == 0


def test_recall_metrics_deduplicates_injected():
    m = recall_metrics(["a", "a", "b"], ["a"])
    assert m["recalled"] == 2  # count distinct injected ids? no: raw ids counted once
    assert m["used"] == 1
    assert m["precision"] == 0.5