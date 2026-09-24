"""Normalize LSP locations and document symbols into Wave-1 semantic records."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .semantic_code_document import DocumentSnapshot, read_document_snapshot
from .semantic_code_limits import SemanticCodeLimits
from .semantic_code_types import Position, SymbolKind, SymbolRecord, TextRange, stable_id
from .semantic_lsp_encoding import position_to_offset
from .semantic_lsp_types import LocationRecord, LspPosition, LspRange, PositionEncoding
from .semantic_lsp_uri import uri_to_relative_path


_LSP_KIND_MAP = {
    1: SymbolKind.MODULE,
    2: SymbolKind.MODULE,
    3: SymbolKind.MODULE,
    4: SymbolKind.MODULE,
    5: SymbolKind.CLASS,
    6: SymbolKind.METHOD,
    7: SymbolKind.PROPERTY,
    8: SymbolKind.PROPERTY,
    9: SymbolKind.METHOD,
    11: SymbolKind.CLASS,
    12: SymbolKind.FUNCTION,
    13: SymbolKind.VARIABLE,
    14: SymbolKind.CONSTANT,
    23: SymbolKind.CLASS,
}


def parse_position(value: Any) -> LspPosition:
    if not isinstance(value, dict):
        raise ValueError("LSP position must be an object")
    return LspPosition(int(value["line"]), int(value["character"]))


def parse_range(value: Any) -> LspRange:
    if not isinstance(value, dict):
        raise ValueError("LSP range must be an object")
    return LspRange(parse_position(value["start"]), parse_position(value["end"]))


def normalize_locations(value: Any) -> tuple[LocationRecord, ...]:
    if value is None:
        return ()
    items = value if isinstance(value, list) else [value]
    result: list[LocationRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            if "uri" in item:
                result.append(LocationRecord(str(item["uri"]), parse_range(item["range"])))
            elif "targetUri" in item:
                target = item.get("targetSelectionRange", item.get("targetRange"))
                origin = item.get("originSelectionRange")
                result.append(
                    LocationRecord(
                        str(item["targetUri"]),
                        parse_range(target),
                        parse_range(origin) if origin is not None else None,
                    )
                )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(result)


def _wave1_position(text: str, lsp: LspPosition, encoding: PositionEncoding) -> Position:
    offset = position_to_offset(text, lsp, encoding)
    line = text.count("\n", 0, offset)
    line_start = text.rfind("\n", 0, offset) + 1
    return Position(line, offset - line_start)


def _wave1_range(snapshot: DocumentSnapshot, value: Any, encoding: PositionEncoding) -> TextRange:
    parsed = parse_range(value)
    return TextRange(
        _wave1_position(snapshot.text, parsed.start, encoding),
        _wave1_position(snapshot.text, parsed.end, encoding),
    )


def normalize_document_symbols(
    root: Path,
    relative_path: str,
    payload: Any,
    *,
    language: str,
    encoding: PositionEncoding,
    limits: SemanticCodeLimits = SemanticCodeLimits(),
    snapshot: DocumentSnapshot | None = None,
) -> tuple[SymbolRecord, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, list):
        raise ValueError("documentSymbol result must be a list or null")
    snapshot = snapshot or read_document_snapshot(root, relative_path, max_bytes=limits.max_file_bytes)
    result: list[SymbolRecord] = []

    def add_document_symbol(item: dict[str, Any], parent_id: str | None, prefix: str) -> None:
        name = str(item.get("name") or "").strip()
        if not name:
            return
        body = _wave1_range(snapshot, item.get("range"), encoding)
        selection = _wave1_range(snapshot, item.get("selectionRange", item.get("range")), encoding)
        qualified = f"{prefix}.{name}" if prefix else name
        kind_raw = item.get("kind")
        kind = _LSP_KIND_MAP.get(kind_raw if isinstance(kind_raw, int) else -1, SymbolKind.UNKNOWN)
        symbol_id = stable_id("sym", relative_path, qualified, body.start.line, body.start.column, kind.value)
        detail = item.get("detail")
        result.append(
            SymbolRecord(
                symbol_id=symbol_id,
                name=name,
                qualified_name=qualified,
                kind=kind,
                relative_path=relative_path,
                declaration=selection,
                body=body,
                parent_symbol_id=parent_id,
                language=language,
                signature=str(detail)[:2048] if detail is not None else None,
                metadata={"source": "lsp", "deprecated": bool(item.get("deprecated", False))},
            )
        )
        children = item.get("children", [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    add_document_symbol(child, symbol_id, qualified)

    for item in payload:
        if not isinstance(item, dict):
            continue
        if "location" not in item:
            try:
                add_document_symbol(item, None, "")
            except (KeyError, TypeError, ValueError):
                continue
            continue
        # SymbolInformation fallback. Keep only records actually belonging to this document.
        location = item.get("location")
        if not isinstance(location, dict) or str(location.get("uri")) != snapshot_uri(root, relative_path):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            location_range = _wave1_range(snapshot, location.get("range"), encoding)
        except (KeyError, TypeError, ValueError):
            continue
        container = str(item.get("containerName") or "").strip()
        qualified = f"{container}.{name}" if container else name
        kind_raw = item.get("kind")
        kind = _LSP_KIND_MAP.get(kind_raw if isinstance(kind_raw, int) else -1, SymbolKind.UNKNOWN)
        result.append(
            SymbolRecord(
                symbol_id=stable_id("sym", relative_path, qualified, location_range.start.line, location_range.start.column, kind.value),
                name=name,
                qualified_name=qualified,
                kind=kind,
                relative_path=relative_path,
                declaration=location_range,
                body=location_range,
                language=language,
                metadata={"source": "lsp-symbol-information"},
            )
        )
    result.sort(key=lambda item: (item.body.start, item.body.end, item.qualified_name, item.symbol_id))
    return tuple(result[: limits.max_symbols])


def snapshot_uri(root: Path, relative_path: str) -> str:
    from .semantic_lsp_uri import relative_path_to_uri
    return relative_path_to_uri(root, relative_path)
