"""Single-tier JSONL failure store.

Write schema (v2, superset of v1):
  {ts, project_id, archetype, failure_cause, task_summary, phases[], record_id,
   source, confidence, status}
  - source: "user-correction" | "model-inference" | "human-verified" (user
    correction outranks model inference; free-form non-empty strings tolerated)
    | "experiment-seed" (synthetic benchmark fixture — MUST NOT be promoted
    or treated as production evidence)
  - confidence: 0..1 (clamped)
  - status: "candidate" (default) | "verified" | "promoted" | "retired"
    Status changes are append-only via promotions.jsonl (last write wins);
    the record line itself is never rewritten.
Read tolerance: v1 and legacy CodeLike fields (task_type, timestamp) are
accepted and normalized on read; unknown fields preserved. Nothing is uploaded.
"""
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_REDACT_PATTERNS = [
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),      # email
    re.compile(r"\b(sk|pk|ghp|glpat|xox[baprs])[-_][A-Za-z0-9]{10,}\b"),  # key shapes
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]
_SUMMARY_MAX = 200
_write_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_id(ts: str, project_id: str, cause: str, summary: str) -> str:
    raw = f"{project_id}|{ts}|{cause}|{summary}".encode("utf-8")
    return "fb-" + hashlib.sha256(raw).hexdigest()[:12]


def redact_text(text: str) -> str:
    for pat in _REDACT_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def _store_file(data_dir: Path) -> Path:
    return Path(data_dir) / "feedback.jsonl"


def record(
    data_dir: Path,
    *,
    project_id: str,
    cause: str,
    summary: str,
    archetype: str = "feature-generic",
    phases: list[str] | None = None,
    redact: bool = False,
    ts: str | None = None,
    source: str = "model-inference",
    confidence: float = 0.5,
) -> dict:
    """Append one failure record. Returns the record. Raises ValueError on bad args."""
    if not cause.strip():
        raise ValueError("cause must not be empty")
    if not summary.strip():
        raise ValueError("summary must not be empty")
    if not source.strip():
        raise ValueError("source must not be empty")
    if redact:
        summary, cause = redact_text(summary), redact_text(cause)
    summary = summary[:_SUMMARY_MAX]
    ts = ts or _now_iso()
    rec = {
        "ts": ts,
        "project_id": project_id,
        "archetype": archetype,
        "failure_cause": cause,
        "task_summary": summary,
        "phases": list(phases or []),
        "record_id": _record_id(ts, project_id, cause, summary),
        "source": source.strip(),
        "confidence": max(0.0, min(1.0, float(confidence))),
        "status": "candidate",
    }
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    path = _store_file(data_dir)
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    return rec


def _normalize_legacy(raw: dict) -> dict:
    """Read-tolerance for legacy CodeLike schema (task_type + timestamp)."""
    if "project_id" not in raw:
        raw = {**raw, "project_id": None}
    if "ts" not in raw:
        raw = {**raw, "ts": raw.get("timestamp")}
    if "failure_cause" not in raw:
        raw = {**raw, "failure_cause": raw.get("cause")}
    if "task_summary" not in raw and raw.get("task_type"):
        raw = {**raw, "task_summary": raw["task_type"][:200]}
    raw.setdefault("archetype", "feature-generic")
    raw.setdefault("phases", [])
    raw.setdefault("source", "legacy")
    raw.setdefault("confidence", 0.5)
    raw.setdefault("status", "candidate")
    return raw


def _read_all(data_dir: Path) -> tuple[list[dict], int]:
    """Return (valid_records, corrupted_count). Tolerates missing file and bad lines."""
    path = _store_file(data_dir)
    if not path.is_file():
        return [], 0
    records, corrupted = [], 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(_normalize_legacy(json.loads(line)))
        except (json.JSONDecodeError, TypeError):
            corrupted += 1
    return records, corrupted


def query(
    data_dir: Path,
    *,
    project_id: str,
    last: int = 10,
    archetype: str | None = None,
    keyword: str | None = None,
) -> list[dict]:
    """Recent failures for this project, newest first.

    keyword: case-insensitive substring over task_summary + failure_cause —
    the cheap "failure oracle" lookup before retrying a failed approach.
    """
    records, _ = _read_all(data_dir)
    ours = [r for r in records if r["project_id"] == project_id]
    if archetype:
        ours = [r for r in ours if r["archetype"] == archetype]
    if keyword:
        kw = keyword.casefold()
        ours = [r for r in ours
                if kw in (r["task_summary"] or "").casefold()
                or kw in (r["failure_cause"] or "").casefold()]
    return list(reversed(ours))[:last]


def _promotions_file(data_dir: Path) -> Path:
    return Path(data_dir) / "promotions.jsonl"


def promote(
    data_dir: Path,
    *,
    project_id: str,
    record_id: str,
    status: str,
) -> dict:
    """Append a status override (append-only; last write wins).

    status: "verified" | "promoted" | "retired" | "candidate".
    "promoted" means: candidate for becoming a rule/skill — exported for
    HUMAN review, never auto-injected into global config.
    """
    if status not in {"candidate", "verified", "promoted", "retired"}:
        raise ValueError(f"bad status: {status}")
    records, _ = _read_all(data_dir)
    known = {r.get("record_id") for r in records if r["project_id"] == project_id}
    if record_id not in known:
        raise ValueError(f"unknown record_id for project {project_id}: {record_id}")
    entry = {"ts": _now_iso(), "project_id": project_id,
             "record_id": record_id, "status": status}
    path = _promotions_file(data_dir)
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
    return entry


def effective_status(data_dir: Path, *, project_id: str) -> dict[str, str]:
    """record_id -> latest status, seeded from records then overridden by promotions."""
    records, _ = _read_all(data_dir)
    ours = [r for r in records if r["project_id"] == project_id]
    eff = {r["record_id"]: r.get("status", "candidate") for r in ours if r.get("record_id")}
    path = _promotions_file(data_dir)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            if p.get("project_id") == project_id and p.get("record_id") in eff:
                eff[p["record_id"]] = p.get("status", "candidate")
    return eff


def promoted(data_dir: Path, *, project_id: str) -> list[dict]:
    """Records whose effective status is 'promoted' — human-review candidates."""
    records, _ = _read_all(data_dir)
    eff = effective_status(data_dir, project_id=project_id)
    return [r for r in records
            if r["project_id"] == project_id
            and eff.get(r.get("record_id")) == "promoted"]


def stats(data_dir: Path, *, project_id: str) -> dict:
    """Aggregate for one project: totals, per-cause counts, corrupted lines."""
    records, corrupted = _read_all(data_dir)
    ours = [r for r in records if r["project_id"] == project_id]
    by_cause: dict[str, int] = {}
    for r in ours:
        by_cause[r["failure_cause"]] = by_cause.get(r["failure_cause"], 0) + 1
    return {
        "project_id": project_id,
        "total": len(ours),
        "by_cause": dict(sorted(by_cause.items(), key=lambda kv: -kv[1])),
        "corrupted_lines": corrupted,
        "all_projects_total": len(records),
    }