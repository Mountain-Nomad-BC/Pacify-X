"""Stable value objects for PACIFY-X semantic code intelligence.

This module is intentionally backend-neutral.  External language servers belong behind
these contracts; callers should not need to know which parser or language service
produced the evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum, StrEnum
import hashlib
import json
from typing import Any, Iterable


class SymbolKind(StrEnum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    PROPERTY = "property"
    VARIABLE = "variable"
    CONSTANT = "constant"
    PARAMETER = "parameter"
    IMPORT = "import"
    UNKNOWN = "unknown"


class DiagnosticSeverity(IntEnum):
    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


class ReferenceResolution(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True, order=True)
class Position:
    """Zero-based line/column position in decoded source text."""

    line: int
    column: int

    def __post_init__(self) -> None:
        if type(self.line) is not int or self.line < 0:
            raise ValueError("line must be a non-negative integer")
        if type(self.column) is not int or self.column < 0:
            raise ValueError("column must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class TextRange:
    start: Position
    end: Position

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("range end precedes range start")


@dataclass(frozen=True, slots=True)
class SymbolRecord:
    symbol_id: str
    name: str
    qualified_name: str
    kind: SymbolKind
    relative_path: str
    declaration: TextRange
    body: TextRange
    parent_symbol_id: str | None = None
    language: str = "unknown"
    signature: str | None = None
    decorators: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True, slots=True)
class ReferenceRecord:
    reference_id: str
    name: str
    relative_path: str
    location: TextRange
    source_symbol_id: str | None = None
    target_symbol_ids: tuple[str, ...] = ()
    resolution: ReferenceResolution = ReferenceResolution.UNRESOLVED
    language: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True, slots=True)
class DiagnosticRecord:
    diagnostic_id: str
    relative_path: str
    severity: DiagnosticSeverity
    message: str
    location: TextRange
    source: str
    code: str | None = None
    symbol_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True, slots=True)
class ImportRecord:
    relative_path: str
    module: str
    imported_name: str | None
    alias: str | None
    location: TextRange
    level: int = 0

    def as_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass(frozen=True, slots=True)
class SemanticDocument:
    relative_path: str
    language: str
    sha256: str
    size_bytes: int
    symbols: tuple[SymbolRecord, ...] = ()
    references: tuple[ReferenceRecord, ...] = ()
    imports: tuple[ImportRecord, ...] = ()
    diagnostics: tuple[DiagnosticRecord, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return _plain(self)


def _plain(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        result = {}
        for key, item in asdict(value).items():
            result[key] = _plain(item)
        return result
    if isinstance(value, (StrEnum, IntEnum)):
        return value.value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def stable_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def stable_id(prefix: str, *parts: object) -> str:
    if not prefix or ":" in prefix:
        raise ValueError("prefix must be non-empty and must not contain ':'")
    digest = stable_sha256([str(part) for part in parts])
    return f"{prefix}:{digest[:24]}"


def sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value}))
