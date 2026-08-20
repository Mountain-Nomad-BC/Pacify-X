"""Versioned Studio operation contract shared with the shipped extension."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


_SOURCE_PATH = Path(__file__).resolve().parents[1] / "registry" / "studio_operations.json"
_PACKAGED_PATH = Path(__file__).resolve().with_name("studio_operations.json")
_PATH = _SOURCE_PATH if _SOURCE_PATH.is_file() else _PACKAGED_PATH
_RAW = json.loads(_PATH.read_text(encoding="utf-8"))
if (
    not isinstance(_RAW, Mapping)
    or _RAW.get("schema_version") != "px.studio-operation-contract/1.0"
    or not isinstance(_RAW.get("kinds"), Mapping)
):
    raise RuntimeError("Studio operation contract is invalid")

STUDIO_OPERATIONS = {
    str(kind): frozenset(map(str, operations))
    for kind, operations in _RAW["kinds"].items()
    if isinstance(operations, list)
}
STUDIO_KINDS = frozenset(STUDIO_OPERATIONS)
ALL_STUDIO_OPERATIONS = frozenset().union(*STUDIO_OPERATIONS.values())


def require_studio_operation(kind: str, operation: str) -> None:
    if kind not in STUDIO_OPERATIONS:
        raise ValueError(f"unsupported Studio kind: {kind}")
    if operation not in STUDIO_OPERATIONS[kind]:
        raise ValueError(f"unsupported {kind} Studio operation: {operation}")
