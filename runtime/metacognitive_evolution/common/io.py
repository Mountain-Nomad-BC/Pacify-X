from __future__ import annotations
import json
from pathlib import Path
from typing import Any

def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def dump_json(data: Any, path: str | Path | None = None) -> str:
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if path is not None:
        Path(path).write_text(text, encoding="utf-8")
    return text
