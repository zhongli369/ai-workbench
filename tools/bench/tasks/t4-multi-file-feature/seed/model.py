"""Inventory model: JSON-file backed."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Item:
    name: str
    qty: int
    price: float


def load(path):
    p = Path(path)
    if not p.is_file():
        return []
    return [Item(**row) for row in json.loads(p.read_text(encoding="utf-8"))]


def save(path, items):
    Path(path).write_text(json.dumps([asdict(i) for i in items], indent=2),
                          encoding="utf-8")
