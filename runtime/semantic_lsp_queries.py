"""High-level semantic LSP requests with didOpen synchronization and containment."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .semantic_code_document import read_document_snapshot
from .semantic_code_types import Position, SymbolRecord
from .semantic_lsp_client import LspClient
from .semantic_lsp_encoding import offset_to_position
from .semantic_lsp_normalize import normalize_document_symbols, normalize_locations
from .semantic_lsp_types import LocationRecord, WorkspaceEditPlan
from .semantic_lsp_uri import uri_to_relative_path
from .semantic_lsp_workspace import workspace_edit_plan


class UnsupportedLspCapability(RuntimeError):
    pass


class LspQueryService:
    def __init__(self, client: LspClient):
        self.client = client

    @property
    def _caps(self):
        if self.client.capabilities is None or self.client.documents is None:
            raise RuntimeError("LSP client is not initialized")
        return self.client.capabilities

    def _position_params(self, relative_path: str, position: Position) -> tuple[dict[str, Any], object]:
        snapshot = read_document_snapshot(self.client.root, relative_path, max_bytes=self.client.limits.max_file_bytes)
        offset = snapshot.offset(position)
        lsp = offset_to_position(snapshot.text, offset, self._caps.position_encoding)
        return {"textDocument": {"uri": self.client.documents.sync_path(relative_path).uri}, "position": lsp.as_dict()}, snapshot

    def _contained_locations(self, value: Any, *, allow_external: bool) -> tuple[LocationRecord, ...]:
        result: list[LocationRecord] = []
        for item in normalize_locations(value):
            try:
                uri_to_relative_path(self.client.root, item.uri, allow_external=allow_external)
            except ValueError:
                continue
            result.append(item)
        return tuple(result)

    def document_symbols(self, relative_path: str) -> tuple[SymbolRecord, ...]:
        if not self._caps.document_symbols:
            raise UnsupportedLspCapability("language server does not advertise document symbols")
        assert self.client.documents is not None
        with self.client.documents.opened_path(relative_path) as document:
            payload = self.client.request("textDocument/documentSymbol", {"textDocument": {"uri": document.uri}})
            return normalize_document_symbols(
                self.client.root,
                relative_path,
                payload,
                language=self.client.adapter.language,
                encoding=self._caps.position_encoding,
                limits=self.client.limits,
            )

    def _location_query(self, capability: str, method: str, relative_path: str, position: Position, *, allow_external: bool) -> tuple[LocationRecord, ...]:
        if not getattr(self._caps, capability):
            raise UnsupportedLspCapability(f"language server does not advertise {capability}")
        assert self.client.documents is not None
        was_open = self.client.documents.current(relative_path) is not None
        document = self.client.documents.sync_path(relative_path)
        try:
            params, _snapshot = self._position_params(relative_path, position)
            params["textDocument"] = {"uri": document.uri}
            return self._contained_locations(self.client.request(method, params), allow_external=allow_external)
        finally:
            if not was_open:
                self.client.documents.close(relative_path)

    def definitions(self, relative_path: str, position: Position, *, allow_external: bool = False) -> tuple[LocationRecord, ...]:
        return self._location_query("definitions", "textDocument/definition", relative_path, position, allow_external=allow_external)

    def declarations(self, relative_path: str, position: Position, *, allow_external: bool = False) -> tuple[LocationRecord, ...]:
        return self._location_query("declarations", "textDocument/declaration", relative_path, position, allow_external=allow_external)

    def implementations(self, relative_path: str, position: Position, *, allow_external: bool = False) -> tuple[LocationRecord, ...]:
        return self._location_query("implementations", "textDocument/implementation", relative_path, position, allow_external=allow_external)

    def references(
        self,
        relative_path: str,
        position: Position,
        *,
        include_declaration: bool = True,
        allow_external: bool = False,
    ) -> tuple[LocationRecord, ...]:
        if not self._caps.references:
            raise UnsupportedLspCapability("language server does not advertise references")
        assert self.client.documents is not None
        was_open = self.client.documents.current(relative_path) is not None
        document = self.client.documents.sync_path(relative_path)
        try:
            params, _snapshot = self._position_params(relative_path, position)
            params["textDocument"] = {"uri": document.uri}
            params["context"] = {"includeDeclaration": bool(include_declaration)}
            return self._contained_locations(self.client.request("textDocument/references", params), allow_external=allow_external)
        finally:
            if not was_open:
                self.client.documents.close(relative_path)

    def rename(self, relative_path: str, position: Position, new_name: str) -> WorkspaceEditPlan:
        if not self._caps.rename:
            raise UnsupportedLspCapability("language server does not advertise rename")
        if not isinstance(new_name, str) or not new_name or "\x00" in new_name or len(new_name) > 1024:
            raise ValueError("new_name must be non-empty bounded text")
        assert self.client.documents is not None
        was_open = self.client.documents.current(relative_path) is not None
        document = self.client.documents.sync_path(relative_path)
        try:
            params, _snapshot = self._position_params(relative_path, position)
            params["textDocument"] = {"uri": document.uri}
            if self._caps.prepare_rename:
                prepared = self.client.request("textDocument/prepareRename", params)
                if prepared is None:
                    raise ValueError("language server rejected rename at this position")
            rename_params = dict(params)
            rename_params["newName"] = new_name
            payload = self.client.request("textDocument/rename", rename_params)
            plan = workspace_edit_plan(
                self.client.root,
                payload,
                operation="rename",
                source=self.client.spec.server_id,
                encoding=self._caps.position_encoding,
                limits=self.client.limits,
            )
            for edit in plan.edits:
                if edit.version is not None:
                    current = self.client.documents.version_for_uri(edit.uri)
                    if current is not None and edit.version != current:
                        raise ValueError("language server returned an edit for a stale document version")
            return plan
        finally:
            if not was_open:
                self.client.documents.close(relative_path)
