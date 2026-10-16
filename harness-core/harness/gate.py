"""Irreversible-action gate engine with explicit three-tier semantics.

Modes (config gate.json in data dir, or env override in the hook wrapper):
  - "disabled": fully off, zero overhead, nothing logged.
  - "audit":    matched dangerous commands are LOGGED ONLY. Never blocks.
                THIS IS NOT PROTECTION. It is an observation mode.
  - "enforce":  commands matching enforce_patterns require a valid approval
                (approvals.jsonl, pattern regex + expiry). No valid approval
                -> BLOCK. If config/state is unreadable -> FAIL CLOSED (block).
                Audit mode on the other hand fails open (it never blocks anyway).

Approvals are granted out-of-band by the human via:
  python harness/cli.py gate approve --pattern "git push.*" --ttl 600
The hook itself never approves.

One-time approval tokens (adapted from WorkFlow's approval_token_store):
  python harness/cli.py gate approve --once --action "git push origin main"
prints a single-use token (awt-<48hex>) exactly once. Only its SHA-256 is
stored. A token is bound to ONE action (exact normalized command, or a
regex fullmatch with --scope pattern), expires with TTL, and is consumed
atomically (threading lock + O_EXCL lockfile) on first use — replay,
expiry, and scope mismatch are all denied with distinct reasons. AUDIT
mode never consults tokens; ENFORCE fails closed on an unreadable store.
The raw token never appears in audit logs (12-char hash prefix only).
"""
import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ENFORCE_PATTERNS = [
    r"\bgit\s+push\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-zA-Z]*f",
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f",
    r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r",
    r"\bdel\b.*\s/[fs]\b",
    r"\b(npm|pip|yarn|pnpm)\s+publish\b",
    r"\b(kubectl|helm|terraform)\s+(apply|delete|destroy)\b",
]
_lock = threading.Lock()
_TOKENS_LOCK_TIMEOUT = 2.0  # seconds; fail closed on timeout


class TokenStoreError(Exception):
    """Token store cannot be read/written — ENFORCE must fail closed."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_file(data_dir: Path) -> Path:
    return Path(data_dir) / "gate.json"


def _approvals_file(data_dir: Path) -> Path:
    return Path(data_dir) / "gate-approvals.jsonl"


def _audit_file(data_dir: Path) -> Path:
    return Path(data_dir) / "gate-audit.jsonl"


def _tokens_file(data_dir: Path) -> Path:
    return Path(data_dir) / "gate-tokens.jsonl"


def _tokens_lockfile(data_dir: Path) -> Path:
    return Path(data_dir) / "gate-tokens.lock"


def load_config(data_dir: Path) -> dict:
    """Return {"mode", "enforce_patterns", "audit_patterns"}.

    Missing config -> mode "disabled". Unreadable config -> raises (the hook
    wrapper decides fail-open vs fail-closed per requested mode).
    """
    path = _config_file(data_dir)
    if not path.is_file():
        return {"mode": "disabled",
                "enforce_patterns": list(DEFAULT_ENFORCE_PATTERNS),
                "audit_patterns": list(DEFAULT_ENFORCE_PATTERNS)}
    cfg = json.loads(path.read_text(encoding="utf-8"))
    mode = cfg.get("mode", "disabled")
    if mode not in {"disabled", "audit", "enforce"}:
        raise ValueError(f"bad gate mode: {mode}")
    return {
        "mode": mode,
        "enforce_patterns": cfg.get("enforce_patterns", list(DEFAULT_ENFORCE_PATTERNS)),
        "audit_patterns": cfg.get("audit_patterns", list(DEFAULT_ENFORCE_PATTERNS)),
    }


def write_config(data_dir: Path, *, mode: str,
                 enforce_patterns: list[str] | None = None,
                 audit_patterns: list[str] | None = None) -> dict:
    if mode not in {"disabled", "audit", "enforce"}:
        raise ValueError(f"bad gate mode: {mode}")
    cfg = {"mode": mode,
           "enforce_patterns": enforce_patterns or list(DEFAULT_ENFORCE_PATTERNS),
           "audit_patterns": audit_patterns or list(DEFAULT_ENFORCE_PATTERNS)}
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    _config_file(data_dir).write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def approve(data_dir: Path, *, pattern: str, ttl: int = 600, note: str = "") -> dict:
    """Human grants approval for commands matching `pattern` for ttl seconds."""
    re.compile(pattern)  # validate
    entry = {"ts": _now_iso(), "pattern": pattern,
             "expires_epoch": time.time() + ttl, "note": note[:200]}
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(_approvals_file(data_dir), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
    return entry


def _is_approved(data_dir: Path, commands, now: float | None = None) -> bool:
    """commands: normalized variant tuple from _normalize_shell — an approval
    regex matching ANY variant authorizes the command (it is the same action
    at runtime)."""
    now = now if now is not None else time.time()
    path = _approvals_file(data_dir)
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            a = json.loads(line)
        except json.JSONDecodeError:
            continue
        if a.get("expires_epoch", 0) < now:
            continue
        try:
            if any(re.search(a.get("pattern", r"$^"), c) for c in commands):
                return True
        except re.error:
            continue
    return False


# ------------------------------------------------------- one-time tokens


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_command(command: str) -> str:
    return " ".join(command.split())


def _canonical_command(command: str) -> str:
    """Deterministic single canonical form for token-scope comparison.
    Both the runtime command and the granted action pass through the same
    shell normalization, so an approval stays valid when spelled differently
    (e.g. Windows backslash paths) while an expansion form of the bound
    action still matches — and anything unrecognized fails closed (deny)."""
    return _normalize_command(min(_normalize_shell(command),
                                  key=lambda s: (len(s), s)))


_NORMALIZE_MAX_PASSES = 8
_NORMALIZE_MAX_VARIANTS = 32


def _find_substitution(text: str) -> tuple[int, int, str] | None:
    """Locate the first $(...) or `...` command substitution.

    Returns (start, end, inner) where text[start:end] is the full span
    (delimiters included) and inner is the content between them. Parenthesis
    depth is counted for $(...); an unbalanced `$(` is left alone (bash would
    reject the command anyway, so it cannot execute as a bypass).
    """
    i = text.find("$(")
    if i >= 0:
        depth = 0
        for j in range(i + 1, len(text)):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    return i, j + 1, text[i + 2:j]
    k = text.find("`")
    if k >= 0:
        close = text.find("`", k + 1)
        if close >= 0:
            return k, close + 1, text[k + 1:close]
    return None


def _normalize_shell_pass(text: str) -> set[str]:
    """One normalization pass; returns 1-2 variants (see _normalize_shell)."""
    span = _find_substitution(text)
    if span is None:
        bases = [text]
    else:
        start, end, inner = span
        # Two fail-closed readings of a substitution: REMOVED (a space, so
        # git$(printf ' ')push reads as "git push") and INLINED (inner kept,
        # so echo $(rm -rf /) still exposes the nested rm to the patterns).
        bases = [text[:start] + " " + text[end:],
                 text[:start] + " " + inner + " " + text[end:]]
    outs = set()
    for b in bases:
        # Parameter expansions ($IFS, ${IFS%...}, $HOME, $@, $1, ...): the
        # runtime value is unknowable at gate time, so each collapses to a
        # space — word-joining forms like git${IFS}push then read plainly.
        b = re.sub(r"\$\{[A-Za-z_][A-Za-z0-9_]*[^}]*\}", " ", b)
        b = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]*", " ", b)
        b = re.sub(r"\$[@*#?$!0-9-]", " ", b)
        # Brace expansion {git,push} -> "git push" (both words kept; keeping
        # more text can only widen matching, never narrow it).
        b = re.sub(r"\{([^{}]*,[^{}]*)\}",
                   lambda m: " " + m.group(1).replace(",", " ") + " ", b)
        # Backslash escapes and quote characters never survive bash parsing;
        # dropping them reveals the runtime word (g\it / g'i't -> git).
        b = re.sub(r"\\([\s\S])", r"\1", b)
        b = b.replace("'", "").replace('"', "")
        outs.add(" ".join(b.split()))
    return outs


def _normalize_shell(command: str) -> tuple[str, ...]:
    """Collapse shell expansion forms that bash resolves at runtime but a
    raw-string regex never sees (git${IFS}push, {git,push}, git$(...)push,
    backticks, g\\it push, g'i't push).

    Returns a bounded set of normalized variants; a pattern matching ANY
    variant is treated as matched (fail-closed union). The direction only
    ever over-blocks, never under-blocks: normalization removes or unfolds
    syntax, it never hides a plainly-written dangerous command. This is not
    a shell parser — it is a conservative canonicalization for matching.
    """
    variants = {command}
    for _ in range(_NORMALIZE_MAX_PASSES):
        new: set[str] = set()
        for v in variants:
            new.update(_normalize_shell_pass(v))
        if new == variants:
            break
        variants = set(sorted(new)[:_NORMALIZE_MAX_VARIANTS])
    return tuple(sorted(variants))


class _StoreLock:
    """Cross-process mutual exclusion for the token store: in-process
    threading lock + O_EXCL lockfile. Timeout raises TokenStoreError so
    ENFORCE fails closed instead of consuming non-atomically."""

    def __init__(self, data_dir: Path, timeout: float):
        self.data_dir = Path(data_dir)
        self.timeout = timeout
        self._fd: int | None = None

    def __enter__(self):
        _lock.acquire()
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            deadline = time.time() + self.timeout
            while True:
                try:
                    self._fd = os.open(str(_tokens_lockfile(self.data_dir)),
                                       os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    return self
                except FileExistsError:
                    if time.time() >= deadline:
                        raise TokenStoreError("token store lock timeout")
                    time.sleep(0.02)
        except TokenStoreError:
            _lock.release()
            raise
        except OSError as e:
            _lock.release()
            raise TokenStoreError(f"token store lock error: {e}") from e

    def __exit__(self, *exc):
        try:
            if self._fd is not None:
                os.close(self._fd)
            try:
                os.unlink(str(_tokens_lockfile(self.data_dir)))
            except OSError:
                pass
        finally:
            _lock.release()
        return False


def _read_token_entries(data_dir: Path) -> list[dict]:
    path = _tokens_file(data_dir)
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise TokenStoreError(f"token store unreadable: {e}") from e
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as e:
            # corrupt store: replay state unknowable -> fail closed
            raise TokenStoreError(f"token store corrupt: {e}") from e
    return entries


def approve_once(data_dir: Path, *, action: str, scope: str = "command",
                 ttl: int = 600, note: str = "") -> dict:
    """Human grants a single-use token bound to one action.

    scope "command": exact match after whitespace normalization.
    scope "pattern": re.fullmatch(action, command).
    The RAW token is returned here (printed once by the CLI) and never
    stored — only its SHA-256 lands in gate-tokens.jsonl.
    """
    if scope not in {"command", "pattern"}:
        raise ValueError(f"bad scope: {scope}")
    if not action.strip():
        raise ValueError("action must not be empty")
    if scope == "pattern":
        re.compile(action)  # validate
    token = "awt-" + secrets.token_hex(24)
    entry = {"type": "grant", "grant_id": "g-" + secrets.token_hex(8),
             "token_hash": _hash_token(token), "action": action,
             "scope": scope, "created": _now_iso(),
             "expires_epoch": time.time() + ttl, "note": note[:200]}
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(_tokens_file(data_dir), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
    return {"token": token, "grant_id": entry["grant_id"], "scope": scope,
            "action": action, "expires_epoch": entry["expires_epoch"]}


def _consume_token(data_dir: Path, token: str, command: str,
                   now: float | None = None) -> tuple[bool, str]:
    """Validate a token and atomically record its consumption.

    Denial reasons are distinct on purpose: unknown token / token expired /
    token scope mismatch / token already used (replay).
    """
    now = now if now is not None else time.time()
    with _StoreLock(data_dir, _TOKENS_LOCK_TIMEOUT):
        entries = _read_token_entries(data_dir)
        th = _hash_token(token)
        grant = next((e for e in entries
                      if e.get("type") == "grant" and e.get("token_hash") == th),
                     None)
        if grant is None:
            return False, "unknown token"
        if grant.get("expires_epoch", 0) < now:
            return False, "token expired"
        if grant.get("scope") == "pattern":
            try:
                if not re.fullmatch(grant.get("action", r"$^"), command):
                    return False, "token scope mismatch"
            except re.error:
                return False, "token scope mismatch"
        elif _canonical_command(command) != _canonical_command(grant.get("action", "")):
            return False, "token scope mismatch"
        if any(e.get("type") == "consume" and e.get("grant_id") == grant["grant_id"]
               for e in entries):
            return False, "token already used"
        consume = {"type": "consume", "grant_id": grant["grant_id"],
                   "ts": _now_iso(), "command": command[:300]}
        try:
            with open(_tokens_file(data_dir), "a", encoding="utf-8") as f:
                f.write(json.dumps(consume, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            raise TokenStoreError(f"token consume write failed: {e}") from e
        return True, "token consumed"


def log_decision(data_dir: Path, *, mode: str, decision: str,
                 command: str, matched: str | None,
                 token_hash: str | None = None) -> None:
    entry = {"ts": _now_iso(), "mode": mode, "decision": decision,
             "command": command[:300], "matched": matched}
    if token_hash:
        entry["token"] = token_hash[:12]  # hash prefix only, never raw
    try:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        with _lock:
            with open(_audit_file(data_dir), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
    except OSError:
        pass  # audit logging is best-effort; blocking semantics unaffected


def evaluate(data_dir: Path, command: str, *,
             token: str | None = None,
             mode_override: str | None = None,
             now: float | None = None) -> dict:
    """Decide what should happen for one Bash command.

    Returns {"decision", "mode", "matched"} with decision in:
      "allow"        — proceed (unmatched, or disabled, or approved)
      "audit"        — proceed, but this was logged as dangerous (NOT protection)
      "block"        — enforce mode, no valid approval (reason says why when
                       a token was presented and denied)
      "block-error"  — enforce mode requested but config/token store
                       unreadable: fail closed

    AUDIT mode never consults tokens: it logs and proceeds, and a presented
    token is neither validated nor consumed there (an audit log line must
    not masquerade as real authorization).
    """
    try:
        cfg = load_config(data_dir)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        if (mode_override or "enforce") == "enforce":
            return {"decision": "block-error", "mode": "enforce",
                    "matched": None, "reason": f"config unreadable, fail closed: {e}"}
        return {"decision": "allow", "mode": "disabled", "matched": None}

    mode = mode_override or cfg["mode"]
    if mode == "disabled":
        return {"decision": "allow", "mode": mode, "matched": None}

    patterns = cfg["enforce_patterns"] if mode == "enforce" else cfg["audit_patterns"]
    # Match against shell-normalized variants so expansion forms (e.g.
    # git${IFS}push) cannot slip past a raw-string regex (fail-closed union).
    variants = _normalize_shell(command)
    matched = next((p for p in patterns
                    if any(_safe_search(p, v) for v in variants)), None)
    if not matched:
        return {"decision": "allow", "mode": mode, "matched": None}

    if mode == "audit":
        return {"decision": "audit", "mode": mode, "matched": matched}

    # enforce
    if _is_approved(data_dir, variants, now=now):
        return {"decision": "allow", "mode": mode, "matched": matched,
                "reason": "valid approval"}
    if token:
        th_prefix = _hash_token(token)[:12]
        try:
            ok, reason = _consume_token(data_dir, token, command, now=now)
        except TokenStoreError as e:
            return {"decision": "block-error", "mode": mode, "matched": matched,
                    "reason": str(e), "token": th_prefix}
        if ok:
            return {"decision": "allow", "mode": mode, "matched": matched,
                    "reason": reason, "token": th_prefix}
        return {"decision": "block", "mode": mode, "matched": matched,
                "reason": reason, "token": th_prefix}
    return {"decision": "block", "mode": mode, "matched": matched}


def _safe_search(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text) is not None
    except re.error:
        return False
