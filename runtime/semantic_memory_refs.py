"""Stable, canonical memory-reference syntax independent of physical storage.

``pxmem://`` references identify a project + memory identity and may optionally pin an
exact record revision.  They never encode a storage tier/path, so hot/warm/cold
relocation cannot invalidate logical references.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import quote, unquote

_PROJECT_MAX_BYTES = 256
_MEMORY_MAX_BYTES = 512
_URI_MAX_BYTES = 4096
_SEGMENT = r"(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+"
_REF_RE = re.compile(
    rf"pxmem://(?P<project>{_SEGMENT})/(?P<memory>{_SEGMENT})"
    r"(?:@(?P<revision>[1-9][0-9]*))?"
)
# Prevent extracting a valid-looking prefix from a malformed longer reference.
_EXTRACT_RE = re.compile(
    _REF_RE.pattern + r"(?![A-Za-z0-9._~%+@-])"
)


def _bounded_identity(value: str, field: str, *, max_bytes: int) -> None:
    if type(value) is not str or not value:
        raise ValueError(f"{field} must be nonempty text")
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field} exceeds {max_bytes} UTF-8 bytes")


@dataclass(frozen=True, slots=True)
class MemoryReference:
    project_id: str
    memory_id: str
    revision: int | None = None

    def __post_init__(self) -> None:
        _bounded_identity(self.project_id, "project_id", max_bytes=_PROJECT_MAX_BYTES)
        _bounded_identity(self.memory_id, "memory_id", max_bytes=_MEMORY_MAX_BYTES)
        if self.revision is not None and (
            type(self.revision) is not int or self.revision < 1
        ):
            raise ValueError("memory revision must be a positive integer")

    def uri(self) -> str:
        base = (
            f"pxmem://{quote(self.project_id, safe='._~-')}/"
            f"{quote(self.memory_id, safe='._~-')}"
        )
        return base if self.revision is None else f"{base}@{self.revision}"


def parse_memory_reference(value: str) -> MemoryReference:
    if type(value) is not str or not value or len(value.encode("utf-8")) > _URI_MAX_BYTES:
        raise ValueError("memory reference must be bounded nonempty text")
    match = _REF_RE.fullmatch(value)
    if not match:
        raise ValueError("invalid PX memory reference")
    revision = match.group("revision")
    ref = MemoryReference(
        unquote(match.group("project")),
        unquote(match.group("memory")),
        None if revision is None else int(revision),
    )
    # Stable references have one canonical spelling.  This rejects malformed/ambiguous
    # percent-encoding and equivalent-but-different aliases such as %6d for ``m``.
    if ref.uri() != value:
        raise ValueError("PX memory reference is not canonically encoded")
    return ref


def extract_memory_references(
    content: str,
    *,
    max_references: int = 2048,
) -> tuple[MemoryReference, ...]:
    if type(content) is not str:
        raise TypeError("memory reference source must be text")
    if type(max_references) is not int or max_references < 1:
        raise ValueError("max_references must be a positive integer")
    result: list[MemoryReference] = []
    for match in _EXTRACT_RE.finditer(content):
        if len(result) >= max_references:
            raise ValueError("memory reference budget exceeded")
        result.append(parse_memory_reference(match.group(0)))
    return tuple(result)
