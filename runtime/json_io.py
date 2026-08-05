"""Small strict JSON-object reader shared by runtime boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value
