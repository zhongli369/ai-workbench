"""Recurring failure-pattern report (P3-style, self-contained).

Groups a project's feedback by failure_cause, surfaces recurrence, and emits
rule/skill PROPOSALS for human review. Read-only; never auto-applies anything.
"""
from pathlib import Path

from . import feedback


def report(data_dir: Path, *, project_id: str, min_count: int = 2) -> dict:
    """Recurring-cause report with promotion suggestions.

    min_count: a cause must recur at least this many times to be flagged.
    """
    records, corrupted = feedback._read_all(data_dir)
    ours = [r for r in records if r["project_id"] == project_id]
    eff = feedback.effective_status(data_dir, project_id=project_id)

    by_cause: dict[str, list[dict]] = {}
    for r in ours:
        by_cause.setdefault(r["failure_cause"] or "(unknown)", []).append(r)

    recurring = []
    for cause, rows in sorted(by_cause.items(), key=lambda kv: -len(kv[1])):
        if len(rows) < min_count:
            continue
        statuses = [eff.get(r.get("record_id"), "candidate") for r in rows]
        already = any(s == "promoted" for s in statuses)
        recurring.append({
            "cause": cause,
            "count": len(rows),
            "sources": sorted({r.get("source", "legacy") for r in rows}),
            "max_confidence": max(r.get("confidence", 0.5) for r in rows),
            "samples": [r["task_summary"][:80] for r in rows[-3:]],
            "already_promoted": already,
            "proposal": (
                None if already else
                f"failure_cause '{cause}' 复发 {len(rows)} 次 — 建议人工审查后 "
                f"提炼为规则/Skill (promote 一条最典型记录作为候选)"
            ),
        })

    return {
        "project_id": project_id,
        "total_records": len(ours),
        "distinct_causes": len(by_cause),
        "recurring": recurring,
        "promoted_count": sum(1 for s in eff.values() if s == "promoted"),
        "corrupted_lines": corrupted,
        "note": "proposals 仅供人工审查; harness 不自动修改任何规则/配置",
    }
