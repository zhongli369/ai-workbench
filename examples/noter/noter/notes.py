"""noter store. Two seeded defects, deterministic and independently fixable:

FC1 (durability, T3): add() only writes to in-memory _MEM when DATA file already
exists ("write-back not implemented"); new process never sees the note.
FC2 (cache, T4): _LIST_CACHE never invalidated; in-process list after add is stale.

Feature gaps: search / edit not implemented (T1/T2).
"""
import json
import pathlib

DATA = pathlib.Path(__file__).parent.parent / "notes.json"
_MEM = []          # FC1: write-back buffer, persists only when file absent
_LIST_CACHE = None  # FC2: stale cache


def _load():
    if not DATA.is_file():
        return []
    with open(DATA, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return []
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def add(text):
    if not text.strip():
        raise ValueError("note text must not be empty")
    base = _load() if not _MEM else _MEM
    rec = {"id": len(base) + 1, "text": text.strip()}
    if not DATA.is_file():  # FC1: only brand-new files get written
        with open(DATA, "w", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    _MEM.append(rec)
    return rec


def list_notes():
    global _LIST_CACHE
    if _LIST_CACHE is None:
        _LIST_CACHE = _load()  # FC2: never invalidated after this
    return list(_LIST_CACHE)


def rm(note_id):
    global _LIST_CACHE
    rows = _load()
    kept = [r for r in rows if r["id"] != note_id]
    DATA.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in kept) + ("\n" if kept else ""),
                    encoding="utf-8")
    _LIST_CACHE = None
    return len(rows) != len(kept)