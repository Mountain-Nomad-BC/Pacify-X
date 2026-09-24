"""Client-neutral facade for Wave-2 semantic language-service operations."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .semantic_code_receipts import semantic_receipt
from .semantic_code_types import Position
from .semantic_lsp_manager import LspClientManager
from .semantic_lsp_queries import LspQueryService
from .semantic_lsp_transaction import apply_workspace_edit_plan
from .semantic_lsp_uri import uri_to_relative_path


class SemanticLanguageService:
    def __init__(self, *, manager: LspClientManager | None = None, allow_writes: bool = False):
        self.manager = manager or LspClientManager()
        self.allow_writes = bool(allow_writes)

    def discovery(self, *, environment: Mapping[str, str] | None = None) -> dict[str, object]:
        found = self.manager.registry.discovery(environment=environment)
        return {
            "adapters": {
                key: [list(argv) for argv in candidates]
                for key, candidates in sorted(found.items())
            }
        }

    def _client(self, root: Path, adapter_key: str, **open_options):
        return self.manager.open(root, adapter_key, **open_options)

    def capabilities(self, root: Path, adapter_key: str, **open_options) -> dict[str, object]:
        client = self._client(root, adapter_key, **open_options)
        assert client.capabilities is not None
        payload = asdict(client.capabilities)
        payload["position_encoding"] = client.capabilities.position_encoding.value
        return {
            "server_id": client.spec.server_id,
            "capabilities": payload,
            "health": asdict(client.health.snapshot()),
        }

    @staticmethod
    def _locations(client, locations) -> list[dict[str, object]]:
        result = []
        for item in locations:
            try:
                relative = uri_to_relative_path(client.root, item.uri)
            except ValueError:
                relative = None
            result.append({
                "uri": item.uri,
                "relative_path": relative,
                "range": item.range.as_dict(),
                "origin_selection_range": None if item.origin_selection_range is None else item.origin_selection_range.as_dict(),
            })
        return result

    def document_symbols(self, root: Path, adapter_key: str, relative_path: str, **open_options) -> dict[str, object]:
        client = self._client(root, adapter_key, **open_options)
        records = LspQueryService(client).document_symbols(relative_path)
        payload = [item.as_dict() for item in records]
        return {
            "symbols": payload,
            "receipt": semantic_receipt(
                operation="lsp.document_symbols",
                project_revision=None,
                source_revision=None,
                result=payload,
            ),
        }

    def locations(
        self,
        root: Path,
        adapter_key: str,
        operation: str,
        relative_path: str,
        line: int,
        column: int,
        *,
        allow_external: bool = False,
        **open_options,
    ) -> dict[str, object]:
        client = self._client(root, adapter_key, **open_options)
        query = LspQueryService(client)
        position = Position(line, column)
        methods = {
            "definition": query.definitions,
            "declaration": query.declarations,
            "implementation": query.implementations,
            "references": query.references,
        }
        if operation not in methods:
            raise ValueError("unsupported location operation")
        records = methods[operation](relative_path, position, allow_external=allow_external)
        payload = self._locations(client, records)
        return {
            "locations": payload,
            "receipt": semantic_receipt(
                operation=f"lsp.{operation}",
                project_revision=None,
                source_revision=None,
                result=payload,
            ),
        }

    def rename(
        self,
        root: Path,
        adapter_key: str,
        relative_path: str,
        line: int,
        column: int,
        new_name: str,
        *,
        write: bool = False,
        **open_options,
    ) -> dict[str, object]:
        if write and not self.allow_writes:
            raise PermissionError("semantic language-service writes are disabled")
        client = self._client(root, adapter_key, **open_options)
        query = LspQueryService(client)
        plan = query.rename(relative_path, Position(line, column), new_name)
        assert client.capabilities is not None
        result = apply_workspace_edit_plan(
            client.root,
            plan,
            encoding=client.capabilities.position_encoding,
            write=write,
            limits=client.limits,
        )
        if result.written and client.documents is not None:
            for changed in plan.expected_sha256:
                if client.documents.current(changed) is not None:
                    client.documents.sync_path(changed)
        return {
            "written": result.written,
            "files": sorted(plan.expected_sha256),
            "before_sha256": dict(result.before_sha256),
            "after_sha256": dict(result.after_sha256),
            "diagnostics": {key: list(value) for key, value in result.diagnostics.items()},
            "preview_text": None if result.text is None else dict(result.text),
            "receipt": dict(result.receipt),
        }

    def health(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.manager.health_inventory()]

    def close_all(self) -> None:
        self.manager.close_all()
