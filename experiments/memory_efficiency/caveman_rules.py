"""D3a - Deterministic approximation of the caveman voice compression rules.

SOURCE PATTERN: caveman (Apache-2.0, pinned d262ab38)
`skills/caveman/SKILL.md` voice rules. THIS IS NOT a copy of any caveman
engine code - rtk `engine/` is BUSL-1.1 and is intentionally NOT read or
reproduced here. We implement a conservative, deterministic, stdlib-only
approximation of the PROSE rules that a token-cost measurement can exercise:

  Rule 2  Kill ceremony   - greeting/hedging/pleasantries/recap/closer removed
  Rule 3  Short word      - a small set of multi-word fillers shortened
  Rule 6  Payload verbatim- everything payload-like (code blocks, inline code,
                            paths, filenames, error codes, numbers) is masked
                            out before prose rules run and reinserted
                            byte-identical, so commands/paths/errors/numbers
                            survive the transform unchanged.

Rules marked "never perform caveman" (9), "answer first" (1), "one idea per
sentence" (5), "articles optional" (4) and the break-the-rules list (security/
irreversible etc.) are intentional decisions requiring a model and are NOT
approximated here (see MEASUREMENT.md -> MODEL_VALIDATION_PENDING).

Tokenizer: THIS ROUND uses a chars/4 proxy ONLY (documented in TOKENIZER_NOTE).
tiktoken cl100k_base counts are the model-validation step and are deliberately
NOT attempted (no network this round; a fresh tiktoken cache would try to
download its BPE vocabulary).

Pure stdlib, deterministic, zero IO, zero LLM.
"""
from __future__ import annotations

import re
from collections.abc import Callable

# ------------------------------------------------------------------ tokenizer

TOKENIZER_PROXY = "chars4"
TOKENIZER_NOTE = (
    "Token deltas use a chars/4 proxy (len(text)//4 upward), NOT a real BPE. "
    "Real tiktoken cl100k_base deltas are marked MODEL_VALIDATION_PENDING: "
    "tiktoken was not invoked this round because a fresh vocabulary cache "
    "would attempt a network download, which the hard no-network rule forbids."
)


def estimate_tokens(text: str | None, *, method: str = TOKENIZER_PROXY) -> int:
    """Deterministic token proxy. Default chars/4, round up, floor 1."""
    if method != "chars4":
        raise ValueError(f"unknown tokenizer proxy {method!r}")
    return max(1, (len(text or "") + 3) // 4)


# ------------------------------------------------------------ payload masking

# NUL delimiter: Py_UNICODE_ISSPACE treats 0x1c-0x1e as whitespace, so a
# control-char placeholder in that range gets chewed up by `\s`-anchored prose
# rules. 0x00 is not whitespace and never appears in normal prose.
_PLACEHOLDER = "\x00"

_PAYLOAD_RE = re.compile(
    r"```[\s\S]*?```"                                   # fenced code block
    r"|`[^`\n]+`"                                       # inline code span
    r"|[A-Za-z]:\\[^\s\r\n,;`'\"()\[\]{}]+"             # C:\... windows path
    r"|(?:~/|\./|\.\./|/)[A-Za-z0-9_./@+=-]+"           # unix/relative path
    r"|\b[\w.-]+\.(?:py|js|jsx|ts|tsx|json|toml|yaml|yml|sh|ps1|psm1|exe|"
    r"txt|csv|md|go|rs|sql|dll|log)\b"                  # filename w/ extension
    r"|\b(?:ETIMEDOUT|EACCES|ECONNREFUSED|ENOENT|ENOTFOUND)\b"  # errno symbols
    r"|\b[A-Z]{2,}[-_][A-Z0-9]{1,}\b"                   # error-code shapes HHTP_500
    r"|\b\d[\d,._%+-]*(?:[eE][+-]?\d+)?\b"              # numbers (incl 1,000 / 3.14 / 95%)
)

_NUM_RE = re.compile(r"[0-9][0-9.,%+_-]*")


def _mask_spans(text: str) -> tuple[str, list[str]]:
    spans: list[str] = []
    out: list[str] = []
    last = 0
    for m in _PAYLOAD_RE.finditer(text):
        out.append(text[last:m.start()])
        spans.append(m.group(0))
        out.append(f"{_PLACEHOLDER}{len(spans) - 1}{_PLACEHOLDER}")
        last = m.end()
    out.append(text[last:])
    return "".join(out), spans


def _restore_spans(text: str, spans: list[str]) -> str:
    for i, span in enumerate(spans):
        text = text.replace(f"{_PLACEHOLDER}{i}{_PLACEHOLDER}", span)
    return text


# ------------------------------------------------------------ prose ceremony

# (compiled pattern, replacement): removal-first, then shortening. Applied in
# order. Word-boundary-anchored so numbers / paths / error codes are untouched
# (they are additionally pre-masked by _PAYLOAD_RE).
_PROSE_RULES: list[tuple[re.Pattern[str], str]] = [
    # --- opener ceremony ----------------------------------------------------
    (re.compile(r"(?i)\b(?:sure|absolutely|of course|no problem|perfect|"
                r"great|okay|ok|alright|alrighty)[,!\s]+"), " "),
    (re.compile(r"(?i)^\s*i'd be happy to help(?: you)? (?:with|on)\s+"
                r"[^.!?\n]*[.!?]?\s*"), ""),  # "I'd be happy to help with X." intro
    (re.compile(r"(?i)\bplease(?: note(?: that)?| know that| bear in mind)"
                r"[,!\s]+"), " "),
    (re.compile(r"(?i)\bit (?:is|'s) (?:worth noting|worth mentioning|"
                r"important(?: to note)?) that\s+"), "Note: "),
    (re.compile(r"(?i)\bplease note that\s+"), "Note: "),
    (re.compile(r"(?i)\bas (?:you|we) can see[,!]?\s+"), " "),
    (re.compile(r"(?i)\bfirst of all[,!\s]+"), "First, "),
    (re.compile(r"(?i)\bin essence[,!\s]+"), " "),
    # --- hedge / filler words ----------------------------------------------
    (re.compile(r"(?i)\b(?:just|really|basically|actually|simply|literally|"
                r"kind of|sort of)[,]?\s+"), " "),
    # --- short-word substitutions ------------------------------------------
    (re.compile(r"(?i)\bin order to\b"), "to"),
    (re.compile(r"(?i)\bas well as\b"), "and"),
    (re.compile(r"(?i)\bin addition[,]?\s+"), "Also "),
    (re.compile(r"(?i)\bi would like to\b"), "I will"),
    (re.compile(r"(?i)\bgoing to\b"), "will"),
    (re.compile(r"(?i)\bwill be able to\b"), "can"),
    (re.compile(r"(?i)\bnote that\s+"), ""),
    # --- closer ceremony -----------------------------------------------------
    (re.compile(r"(?i)\s+hope (?:this|that) helps[.!]?\s*$"), ""),
    (re.compile(r"(?i)\s+let me know if you have (?:any )?questions[.!]?\s*$"), ""),
    (re.compile(r"(?i)\s+let's get started[.!]?\s*$"), "."),
    (re.compile(r"(?i)\s+(?:i'd|i am) happy to help[.!]?\s*$"), ""),
    (re.compile(r"(?i)\s+feel free to ask[.!]?\s*$"), ""),
]


def caveman_transform(text: str | None) -> str:
    """Apply the deterministic caveman voice approximation.

    Payload (code/paths/numbers/error codes) is masked first and reinserted
    byte-identical afterwards; only prose ceremony/filler is removed.
    """
    if not text:
        return text or ""
    masked, spans = _mask_spans(text)
    prose = masked
    # Chained closers ("Hope this helps! Let me know if you have questions.")
    # need more than one forward pass; loop to near-fixpoint (bounded, so the
    # result stays deterministic).
    for _ in range(3):
        before = prose
        for pattern, repl in _PROSE_RULES:
            prose = pattern.sub(repl, prose)
        if prose == before:
            break
    prose = re.sub(r"[ \t]{2,}", " ", prose)  # never touch ".env" style dots
    prose = prose.strip()
    return _restore_spans(prose, spans)


# ------------------------------------------------------------------ retention

def retention_report(original: str, transformed: str) -> dict:
    """Byte-identical survival check for payload (commands/paths/errors/numbers).

    Every payload span the mask captured from the original must appear in the
    transformed output, and every digit-run must survive. `pass` is False the
    moment anything payload-like was altered.
    """
    spans = [m.group(0) for m in _PAYLOAD_RE.finditer(original or "")]
    missing_spans = [s for s in spans if s not in (transformed or "")]
    digit_runs = _NUM_RE.findall(original or "")
    missing_digits = [d for d in digit_runs if d not in (transformed or "")]
    return {
        "pass": not missing_spans and not missing_digits,
        "payload_spans": len(spans),
        "digit_runs": len(digit_runs),
        "missing_payload_spans": missing_spans[:5],
        "missing_digit_runs": missing_digits[:5],
    }