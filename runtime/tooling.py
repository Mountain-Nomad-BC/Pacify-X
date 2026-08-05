"""Metadata-first, bounded discovery for tool families."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from typing import Callable


@dataclass(frozen=True, slots=True)
class ToolProbe:
    tool_id: str
    candidate: str
    location: str | None


def load_tool_aliases(root: Path) -> tuple[dict[str, object], ...]:
    path = root.resolve() / "registry" / "source_tool_aliases.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    aliases = document.get("aliases", [])
    if not isinstance(aliases, list):
        raise ValueError("tool alias registry must contain an aliases list")
    return tuple(item for item in aliases if isinstance(item, dict))


def startup_candidates(root: Path, *, maximum: int = 8) -> tuple[str, ...]:
    if maximum < 1 or maximum > 8:
        raise ValueError("maximum must be between 1 and 8")
    candidates = {
        str(candidate)
        for item in load_tool_aliases(root)
        if item.get("startup_default") is True
        for candidate in item.get("candidates", [])
    }
    if len(candidates) > maximum:
        raise ValueError("startup tool candidates exceed the bounded probe budget")
    return tuple(sorted(candidates))


def probe_tool_family(
    root: Path,
    tool_id: str,
    *,
    resolver: Callable[[str], str | None] = shutil.which,
    maximum: int = 8,
) -> tuple[ToolProbe, ...]:
    candidates = {
        str(candidate)
        for item in load_tool_aliases(root)
        if item.get("tool_id") == tool_id
        for candidate in item.get("candidates", [])
    }
    if not candidates:
        raise KeyError(f"unknown tool family: {tool_id}")
    if len(candidates) > maximum:
        raise ValueError("tool family exceeds the bounded probe budget")
    probes: list[ToolProbe] = []
    for candidate in sorted(candidates):
        try:
            location = resolver(candidate)
        except OSError:
            location = None
        probes.append(ToolProbe(tool_id, candidate, location))
    return tuple(probes)
