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
"""
import json
import re
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_file(data_dir: Path) -> Path:
    return Path(data_dir) / "gate.json"


def _approvals_file(data_dir: Path) -> Path:
    return Path(data_dir) / "gate-approvals.jsonl"


def _audit_file(data_dir: Path) -> Path:
    return Path(data_dir) / "gate-audit.jsonl"


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


def _is_approved(data_dir: Path, command: str, now: float | None = None) -> bool:
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
            if re.search(a.get("pattern", r"$^"), command):
                return True
        except re.error:
            continue
    return False


def log_decision(data_dir: Path, *, mode: str, decision: str,
                 command: str, matched: str | None) -> None:
    entry = {"ts": _now_iso(), "mode": mode, "decision": decision,
             "command": command[:300], "matched": matched}
    try:
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        with _lock:
            with open(_audit_file(data_dir), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                f.flush()
    except OSError:
        pass  # audit logging is best-effort; blocking semantics unaffected


def evaluate(data_dir: Path, command: str, *,
             mode_override: str | None = None,
             now: float | None = None) -> dict:
    """Decide what should happen for one Bash command.

    Returns {"decision", "mode", "matched"} with decision in:
      "allow"        — proceed (unmatched, or disabled, or approved)
      "audit"        — proceed, but this was logged as dangerous (NOT protection)
      "block"        — enforce mode, no valid approval
      "block-error"  — enforce mode requested but config unreadable: fail closed
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
    matched = next((p for p in patterns if _safe_search(p, command)), None)
    if not matched:
        return {"decision": "allow", "mode": mode, "matched": None}

    if mode == "audit":
        return {"decision": "audit", "mode": mode, "matched": matched}

    # enforce
    if _is_approved(data_dir, command, now=now):
        return {"decision": "allow", "mode": mode, "matched": matched,
                "reason": "valid approval"}
    return {"decision": "block", "mode": mode, "matched": matched}


def _safe_search(pattern: str, text: str) -> bool:
    try:
        return re.search(pattern, text) is not None
    except re.error:
        return False
