"""Single-tier JSONL failure store.

Write schema (v3, superset of v1/v2):
  {ts, project_id, archetype, failure_cause, task_summary, phases[], record_id,
   source, confidence, status, valid_until?}
  - source: "user-correction" | "model-inference" | "human-verified" (user
    correction outranks model inference; free-form non-empty strings tolerated)
    | "experiment-seed" (synthetic benchmark fixture — MUST NOT be promoted
    or treated as production evidence)
  - confidence: 0..1 (clamped)
  - status: "candidate" (default) | "verified" | "promoted" | "retired"
    Status changes are append-only via promotions.jsonl (last write wins);
    the record line itself is never rewritten.
  - valid_until (v3, optional): ISO date/datetime; expired records stay in the
    store but are hidden from query() by default (失效不删).
  - supersession (v3): supersede() appends to supersedes.jsonl; a superseded
    record stays in the store but is hidden from query() by default.
  - write honesty (v3): every append is fsync'd and read back; a record that
    cannot be read back raises IOError — "written" is never claimed otherwise.
  - ranking (v3): query(keyword=...) keeps the case-insensitive substring
    FILTER (unchanged) and re-ranks the hits by BM25 (most relevant first;
    ties newest first), instead of plain newest-first.
Read tolerance: v1 and legacy CodeLike fields (task_type, timestamp) are
accepted and normalized on read; unknown fields preserved. Nothing is uploaded.
"""
import hashlib
import json
import math
import os
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


def _verify_tail(path: Path, record_id: str) -> None:
    """Read-back check: the last non-empty line must be the record just written.

    Raises IOError otherwise — write honesty: never claim "written" when the
    store does not actually end with the record (未落库不算成功).
    """
    tail = ""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                tail = line
    try:
        got = json.loads(tail).get("record_id")
    except json.JSONDecodeError:
        got = None
    if got != record_id:
        raise IOError(
            f"write verification failed for {path}: "
            f"expected tail record_id {record_id!r}, got {got!r}"
        )


def _append_locked(path: Path, line: str, *, verify_record_id: str) -> None:
    """Append one line with fsync + read-back verification (thread-serialized)."""
    Path(path.parent).mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        _verify_tail(path, verify_record_id)


def _parse_valid_until(value: str) -> datetime:
    """ISO date or datetime; naive values are treated as UTC."""
    dt = datetime.fromisoformat(value.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


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
    valid_until: str | None = None,
) -> dict:
    """Append one failure record. Returns the record. Raises ValueError on bad args.

    valid_until: optional ISO date/datetime after which the record is treated
    as expired (hidden from default query, never deleted).
    Raises IOError if the record cannot be read back after the write.
    """
    if not cause.strip():
        raise ValueError("cause must not be empty")
    if not summary.strip():
        raise ValueError("summary must not be empty")
    if not source.strip():
        raise ValueError("source must not be empty")
    if valid_until is not None:
        try:
            _parse_valid_until(valid_until)
        except ValueError:
            raise ValueError(f"valid_until must be ISO date/datetime: {valid_until!r}")
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
    if valid_until is not None:
        rec["valid_until"] = valid_until.strip()
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    _append_locked(_store_file(data_dir), line, verify_record_id=rec["record_id"])
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


# ---------- BM25 ranking (v3; pure stdlib) ----------

_TOKEN_RE = re.compile(r"[a-z0-9]+|[一-鿿]+")  # latin runs | CJK (U+4E00-U+9FFF) runs


def _tokenize(text: str) -> list[str]:
    """Latin/digit runs (lowercased) + CJK bigrams (unigram for a lone char)."""
    tokens: list[str] = []
    for m in _TOKEN_RE.finditer((text or "").casefold()):
        chunk = m.group(0)
        if chunk.isascii():
            tokens.append(chunk)
        elif len(chunk) == 1:
            tokens.append(chunk)
        else:
            tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
    return tokens


def _bm25_rank(records: list[dict], keyword: str, k1: float = 1.5, b: float = 0.75) -> list[dict]:
    """Re-rank records by BM25 over task_summary + failure_cause.

    Score ties keep newest-first order (records arrive in file order).
    """
    query_terms = _tokenize(keyword)
    if not query_terms or not records:
        return list(reversed(records))
    docs = [_tokenize(f"{r.get('task_summary') or ''} {r.get('failure_cause') or ''}")
            for r in records]
    n_docs = len(docs)
    avgdl = sum(len(d) for d in docs) / n_docs or 1.0
    df: dict[str, int] = {}
    for d in docs:
        for t in set(d):
            df[t] = df.get(t, 0) + 1

    def _score(doc: list[str]) -> float:
        tf: dict[str, int] = {}
        for t in doc:
            tf[t] = tf.get(t, 0) + 1
        total = 0.0
        for t in query_terms:
            n = df.get(t, 0)
            if n == 0:
                continue
            idf = math.log(1 + (n_docs - n + 0.5) / (n + 0.5))
            f = tf.get(t, 0)
            total += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * len(doc) / avgdl))
        return total

    scored = [(_score(d), i, r) for i, (d, r) in enumerate(zip(docs, records))]
    scored.sort(key=lambda x: (-x[0], -x[1]))  # score desc, then newest first
    return [r for _, _, r in scored]


# ---------- supersession (v3; append-only, 失效不删) ----------

def _supersedes_file(data_dir: Path) -> Path:
    return Path(data_dir) / "supersedes.jsonl"


def supersede(data_dir: Path, *, project_id: str, record_id: str, superseded_by: str) -> dict:
    """Mark record_id as replaced by superseded_by (append-only; both must exist).

    The old record is never rewritten or deleted — it is hidden from default
    query() results and remains visible via include_superseded=True.
    """
    if record_id == superseded_by:
        raise ValueError("record cannot supersede itself")
    records, _ = _read_all(data_dir)
    known = {r.get("record_id") for r in records if r["project_id"] == project_id}
    for rid in (record_id, superseded_by):
        if rid not in known:
            raise ValueError(f"unknown record_id for project {project_id}: {rid}")
    entry = {"ts": _now_iso(), "project_id": project_id,
             "record_id": record_id, "superseded_by": superseded_by}
    _append_locked(_supersedes_file(data_dir),
                   json.dumps(entry, ensure_ascii=False) + "\n",
                   verify_record_id=record_id)
    return entry


def superseded_ids(data_dir: Path, *, project_id: str) -> set[str]:
    """record_ids replaced by something newer (left side of every supersede entry)."""
    path = _supersedes_file(data_dir)
    if not path.is_file():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("project_id") == project_id and e.get("record_id"):
            out.add(e["record_id"])
    return out


def _is_expired(rec: dict, now: datetime) -> bool:
    value = rec.get("valid_until")
    if not value:
        return False
    try:
        return _parse_valid_until(value) < now
    except (ValueError, TypeError):
        return False  # read tolerance: malformed legacy data never hides a record


def query(
    data_dir: Path,
    *,
    project_id: str,
    last: int = 10,
    archetype: str | None = None,
    keyword: str | None = None,
    include_expired: bool = False,
    include_superseded: bool = False,
) -> list[dict]:
    """Recent failures for this project.

    Default view hides expired (valid_until passed) and superseded records —
    nothing is ever deleted. Without keyword: newest first. With keyword:
    case-insensitive substring FILTER over task_summary + failure_cause
    (unchanged), hits re-ranked by BM25 (most relevant first, ties newest
    first) — the cheap "failure oracle" lookup before retrying a failed
    approach. Empty/missing store returns [] immediately (fast negative) and
    never creates files as a side effect.
    """
    records, _ = _read_all(data_dir)
    if not records:
        return []
    ours = [r for r in records if r["project_id"] == project_id]
    if not include_superseded:
        hidden = superseded_ids(data_dir, project_id=project_id)
        if hidden:
            ours = [r for r in ours if r.get("record_id") not in hidden]
    if not include_expired:
        now = datetime.now(timezone.utc)
        ours = [r for r in ours if not _is_expired(r, now)]
    if archetype:
        ours = [r for r in ours if r["archetype"] == archetype]
    if keyword:
        kw = keyword.casefold()
        ours = [r for r in ours
                if kw in (r["task_summary"] or "").casefold()
                or kw in (r["failure_cause"] or "").casefold()]
        return _bm25_rank(ours, keyword)[:last]
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
    _append_locked(_promotions_file(data_dir),
                   json.dumps(entry, ensure_ascii=False) + "\n",
                   verify_record_id=record_id)
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