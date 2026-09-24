"""Bounded symbol, reference and overview queries over immutable semantic indexes."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase

from .semantic_code_index import SemanticProjectIndex
from .semantic_code_limits import SemanticCodeLimits
from .semantic_code_types import ReferenceRecord, SymbolKind, SymbolRecord


@dataclass(frozen=True, slots=True)
class SymbolQuery:
    pattern: str
    relative_path: str | None = None
    kinds: tuple[SymbolKind, ...] = ()
    substring: bool = False
    case_sensitive: bool = True
    max_results: int = 50

    def __post_init__(self) -> None:
        if not isinstance(self.pattern, str) or not self.pattern.strip():
            raise ValueError("symbol query pattern must be non-empty")
        if type(self.max_results) is not int or not 1 <= self.max_results <= 500:
            raise ValueError("max_results must be between 1 and 500")


def _matches_name(symbol: SymbolRecord, query: SymbolQuery) -> bool:
    pattern = query.pattern if query.case_sensitive else query.pattern.casefold()
    names = (symbol.name, symbol.qualified_name)
    if not query.case_sensitive:
        names = tuple(name.casefold() for name in names)
    if query.substring:
        return any(pattern in name for name in names)
    if any(char in pattern for char in "*?["):
        return any(fnmatchcase(name, pattern) for name in names)
    return pattern in names


def find_symbols(
    index: SemanticProjectIndex,
    query: SymbolQuery,
    *,
    limits: SemanticCodeLimits = SemanticCodeLimits(),
) -> tuple[SymbolRecord, ...]:
    if len(query.pattern) > limits.max_query_chars:
        raise ValueError("semantic query exceeds maximum length")
    result: list[SymbolRecord] = []
    kind_set = set(query.kinds)
    for symbol in index.symbols:
        if query.relative_path is not None and symbol.relative_path != query.relative_path:
            continue
        if kind_set and symbol.kind not in kind_set:
            continue
        if not _matches_name(symbol, query):
            continue
        result.append(symbol)
        if len(result) >= min(query.max_results, limits.max_results):
            break
    return tuple(result)


def find_references(
    index: SemanticProjectIndex,
    symbol_id: str,
    *,
    max_results: int = 100,
) -> tuple[ReferenceRecord, ...]:
    if type(max_results) is not int or not 1 <= max_results <= 1000:
        raise ValueError("max_results must be between 1 and 1000")
    result = [
        reference for reference in index.references
        if symbol_id in reference.target_symbol_ids
    ]
    return tuple(result[:max_results])


def symbol_overview(
    index: SemanticProjectIndex,
    relative_path: str,
    *,
    max_depth: int = 4,
    max_results: int = 200,
) -> tuple[dict[str, object], ...]:
    if type(max_depth) is not int or not 0 <= max_depth <= 16:
        raise ValueError("max_depth must be between 0 and 16")
    if type(max_results) is not int or not 1 <= max_results <= 1000:
        raise ValueError("max_results must be between 1 and 1000")
    symbols = [item for item in index.symbols if item.relative_path == relative_path]
    by_parent: dict[str | None, list[SymbolRecord]] = {}
    for symbol in symbols:
        by_parent.setdefault(symbol.parent_symbol_id, []).append(symbol)
    for children in by_parent.values():
        children.sort(key=lambda item: (item.declaration.start, item.qualified_name))

    emitted = 0

    def render(symbol: SymbolRecord, depth: int) -> dict[str, object]:
        nonlocal emitted
        emitted += 1
        item: dict[str, object] = {
            "symbol_id": symbol.symbol_id,
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "kind": symbol.kind.value,
            "line": symbol.declaration.start.line,
        }
        if depth < max_depth and emitted < max_results:
            children = []
            for child in by_parent.get(symbol.symbol_id, ()):
                if emitted >= max_results:
                    break
                children.append(render(child, depth + 1))
            if children:
                item["children"] = children
        return item

    roots = by_parent.get(None, ())
    if not roots:
        module_ids = {item.symbol_id for item in symbols if item.kind == SymbolKind.MODULE}
        roots = [item for item in symbols if item.parent_symbol_id not in module_ids]
        module_symbols = [item for item in symbols if item.kind == SymbolKind.MODULE]
        if module_symbols:
            roots = module_symbols
    result = []
    for root in roots:
        if emitted >= max_results:
            break
        result.append(render(root, 0))
    return tuple(result)
