"""Normalized capability and position-encoding negotiation for language servers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .semantic_lsp_types import PositionEncoding


@dataclass(frozen=True, slots=True)
class LspCapabilities:
    document_symbols: bool = False
    definitions: bool = False
    declarations: bool = False
    implementations: bool = False
    references: bool = False
    rename: bool = False
    prepare_rename: bool = False
    workspace_folders: bool = False
    text_sync_kind: int = 1
    open_close: bool = True
    position_encoding: PositionEncoding = PositionEncoding.UTF16


def _enabled(value: Any) -> bool:
    return value is True or isinstance(value, Mapping)


def _sync(caps: Mapping[str, Any]) -> tuple[int, bool]:
    sync = caps.get("textDocumentSync", 1)
    if isinstance(sync, Mapping):
        raw_kind = sync.get("change", 1)
        kind = int(raw_kind) if isinstance(raw_kind, int) and not isinstance(raw_kind, bool) else 1
        open_close = bool(sync.get("openClose", True))
    elif isinstance(sync, int) and not isinstance(sync, bool):
        kind = sync
        open_close = True
    else:
        kind, open_close = 1, True
    return max(0, min(kind, 2)), open_close


def _position_encoding(caps: Mapping[str, Any]) -> PositionEncoding:
    value = caps.get("positionEncoding", PositionEncoding.UTF16.value)
    try:
        return PositionEncoding(str(value).casefold())
    except ValueError:
        return PositionEncoding.UTF16


def parse_capabilities(value: Mapping[str, Any] | None) -> LspCapabilities:
    caps = dict(value or {})
    rename = caps.get("renameProvider")
    prepare = isinstance(rename, Mapping) and bool(rename.get("prepareProvider"))
    sync_kind, open_close = _sync(caps)
    workspace = caps.get("workspace")
    folders = bool(
        isinstance(workspace, Mapping)
        and isinstance(workspace.get("workspaceFolders"), Mapping)
        and workspace["workspaceFolders"].get("supported")
    )
    return LspCapabilities(
        document_symbols=_enabled(caps.get("documentSymbolProvider")),
        definitions=_enabled(caps.get("definitionProvider")),
        declarations=_enabled(caps.get("declarationProvider")),
        implementations=_enabled(caps.get("implementationProvider")),
        references=_enabled(caps.get("referencesProvider")),
        rename=_enabled(rename),
        prepare_rename=prepare,
        workspace_folders=folders,
        text_sync_kind=sync_kind,
        open_close=open_close,
        position_encoding=_position_encoding(caps),
    )
