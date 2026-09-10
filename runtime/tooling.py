"""Metadata-first, bounded discovery for tool families."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
from typing import Callable, Iterable

from .skill_inputs import (
    _text,
    _relative,
    _deadline,
    bounded_deadline,
    load_metadata_object,
)

MAX_TOOL_PROBES = 8
MAX_RAW_TOOL_NAMES = 64
MAX_ALIAS_ROWS = 128


def _maximum(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_TOOL_PROBES:
        raise ValueError("maximum must be an integer between 1 and 8")


def _candidate(value: object) -> str:
    name = _relative(_text(value, "tool candidate"))
    if "/" in name:
        raise ValueError("tool candidate must be a portable executable basename")
    return name


def bounded_tool_names(
    names: Iterable[str],
    *,
    maximum: int = MAX_TOOL_PROBES,
    deadline: float | None = None,
) -> tuple[str, ...]:
    _maximum(maximum)
    deadline = bounded_deadline(deadline)
    if isinstance(names, (str, bytes, dict)):
        raise ValueError("tool names require an iterable of names")
    try:
        iterator = iter(names)
    except TypeError as error:
        raise ValueError("tool names require an iterable of names") from error
    selected = set()
    for index, name in enumerate(iterator):
        _deadline(deadline)
        if index >= MAX_RAW_TOOL_NAMES:
            raise ValueError("raw tool name intake exceeds its budget")
        selected.add(_candidate(name))
        if len(selected) > maximum:
            raise ValueError("tool candidates exceed the bounded probe budget")
    _deadline(deadline)
    return tuple(sorted(selected))


def resolve_tool(name: str, resolver: Callable[[str], str | None]) -> str | None:
    """Validate discovery metadata; a found path does not confer execution trust."""
    if not callable(resolver):
        raise ValueError("tool resolver must be callable")
    name = _candidate(name)
    try:
        location = resolver(name)
    except OSError:
        return None
    return None if location is None else _text(location, "tool location", 4096)


@dataclass(frozen=True, slots=True)
class ToolProbe:
    tool_id: str
    candidate: str
    location: str | None


def load_tool_aliases(
    root: Path, *, deadline: float | None = None
) -> tuple[dict[str, object], ...]:
    deadline = bounded_deadline(deadline)
    document = load_metadata_object(
        root, "registry/source_tool_aliases.json", deadline=deadline
    )
    if (
        set(document) != {"schema_version", "loading_rule", "aliases"}
        or document["schema_version"] != "1.0"
    ):
        raise ValueError("unsupported tool alias metadata contract")
    _text(document["loading_rule"], "tool loading rule", 4096)
    aliases = document["aliases"]
    if type(aliases) is not list or len(aliases) > MAX_ALIAS_ROWS:
        raise ValueError("tool alias registry must contain an aliases list")
    for item in aliases:
        _deadline(deadline)
        if type(item) is not dict or set(item) != {
            "tool_id",
            "candidates",
            "startup_default",
        }:
            raise ValueError("tool alias requires exactly its declared fields")
        _text(item["tool_id"], "tool identity")
        if type(item["startup_default"]) is not bool:
            raise ValueError("startup_default must be boolean")
        candidates = item["candidates"]
        if type(candidates) is not list or not 1 <= len(candidates) <= MAX_TOOL_PROBES:
            raise ValueError("tool alias requires bounded candidate names")
        for name in candidates:
            _candidate(name)
        if len(set(candidates)) != len(candidates):
            raise ValueError("duplicate candidate within tool alias")
    _deadline(deadline)
    return tuple(aliases)


def startup_candidates(
    root: Path, *, maximum: int = 8, deadline: float | None = None
) -> tuple[str, ...]:
    _maximum(maximum)
    candidates = {
        candidate
        for item in load_tool_aliases(root, deadline=deadline)
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
    _maximum(maximum)
    _text(tool_id, "tool identity")
    if not callable(resolver):
        raise ValueError("tool resolver must be callable")
    deadline = bounded_deadline()
    candidates = {
        candidate
        for item in load_tool_aliases(root, deadline=deadline)
        if item.get("tool_id") == tool_id
        for candidate in item.get("candidates", [])
    }
    if not candidates:
        raise KeyError(f"unknown tool family: {tool_id}")
    if len(candidates) > maximum:
        raise ValueError("tool family exceeds the bounded probe budget")
    probes: list[ToolProbe] = []
    for candidate in sorted(candidates):
        _deadline(deadline)
        location = resolve_tool(candidate, resolver)
        _deadline(deadline)
        probes.append(ToolProbe(tool_id, candidate, location))
    return tuple(probes)
