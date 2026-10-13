"""selfcheck — per-task acceptance. Usage: python selfcheck.py --task <search|edit|durability|cache>"""
import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "notes.json"


def reset():
    DATA.write_text("", encoding="utf-8")
    sys.path.insert(0, str(ROOT))
    import importlib
    import noter.notes as notes
    importlib.reload(notes)
    return notes


def run(*args):
    return subprocess.run([sys.executable, "-m", "noter", *args],
                          capture_output=True, text=True, timeout=30)


def seed(line):
    """Seed notes.json directly — T1/T2 acceptance must not depend on buggy add (FC1)."""
    DATA.write_text(line, encoding="utf-8")


def check_search():
    seed('{"id": 1, "text": "buy milk"}\n')
    r = run("search", "milk")
    return r.returncode == 0 and "buy milk" in r.stdout


def check_edit():
    seed('{"id": 1, "text": "old text"}\n')
    r = run("edit", "1", "new text")
    l = run("list")
    return r.returncode == 0 and "new text" in l.stdout and "old text" not in l.stdout


def check_durability():
    reset()
    run("add", "must-survive")
    # fresh process reads the file right after add; note must be on disk
    text = DATA.read_text(encoding="utf-8")
    return "must-survive" in text


def check_cache():
    n = reset()
    n.list_notes()          # warm the cache
    n.add("visible-immediately")
    shown = n.list_notes()  # in-process: same cache => FC2 visible
    return any("visible-immediately" in r["text"] for r in shown)


CHECKS = {"search": check_search, "edit": check_edit,
          "durability": check_durability, "cache": check_cache}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    a = ap.parse_args()
    ok = CHECKS[a.task]()
    print(f"{a.task}: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)