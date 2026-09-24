"""Diagnostic ownership and ad-hoc candidate validation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .semantic_code_document import snapshot_bytes
from .semantic_code_index import SemanticProjectIndex
from .semantic_code_limits import SemanticCodeLimits
from .semantic_code_registry import SemanticBackendRegistry
from .semantic_code_types import DiagnosticRecord, Position, SymbolRecord


def _contains(symbol: SymbolRecord, position: Position) -> bool:
    return symbol.body.start <= position <= symbol.body.end


def attach_diagnostic_owners(
    index: SemanticProjectIndex,
) -> tuple[DiagnosticRecord, ...]:
    by_path: dict[str, list[SymbolRecord]] = {}
    for symbol in index.symbols:
        by_path.setdefault(symbol.relative_path, []).append(symbol)
    result: list[DiagnosticRecord] = []
    for diagnostic in index.diagnostics:
        candidates = [
            symbol for symbol in by_path.get(diagnostic.relative_path, ())
            if _contains(symbol, diagnostic.location.start)
        ]
        if candidates:
            candidates.sort(
                key=lambda item: (
                    item.body.end.line - item.body.start.line,
                    item.body.end.column - item.body.start.column,
                    item.qualified_name,
                )
            )
            result.append(replace(diagnostic, symbol_id=candidates[0].symbol_id))
        else:
            result.append(diagnostic)
    return tuple(result)


def validate_candidate_text(
    relative_path: str,
    text: str,
    *,
    registry: SemanticBackendRegistry | None = None,
    limits: SemanticCodeLimits = SemanticCodeLimits(),
) -> tuple[DiagnosticRecord, ...]:
    if not isinstance(text, str):
        raise ValueError("candidate text must be a string")
    raw = text.encode("utf-8")
    snapshot = snapshot_bytes(relative_path, raw, max_bytes=limits.max_file_bytes)
    registry = registry or SemanticBackendRegistry()
    backend = registry.for_path(relative_path)
    if backend is None:
        raise ValueError(f"no semantic backend for {relative_path}")
    return backend.analyze(snapshot).diagnostics
