import json
from pathlib import Path


def load_hotwords(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"hotwords file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, str) for item in data):
        raise ValueError("hotwords must be a JSON array of strings")
    return data
