"""Versioned LSP document synchronization bound to immutable PX snapshots."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
from threading import RLock
from typing import Iterator

from .semantic_code_document import DocumentSnapshot, read_document_snapshot
from .semantic_code_limits import SemanticCodeLimits
from .semantic_lsp_capabilities import LspCapabilities
from .semantic_lsp_encoding import LspPositionError, offsets_to_range
from .semantic_lsp_transport import StdioJsonRpcTransport
from .semantic_lsp_uri import relative_path_to_uri


@dataclass(frozen=True, slots=True)
class OpenDocument:
    relative_path: str
    uri: str
    language_id: str
    version: int
    text: str
    sha256: str


class DocumentSyncError(RuntimeError):
    pass


def _single_replacement(old: str, new: str) -> tuple[int, int, str]:
    if old == new:
        return len(old), len(old), ""
    prefix = 0
    common = min(len(old), len(new))
    while prefix < common and old[prefix] == new[prefix]:
        prefix += 1
    old_tail = len(old)
    new_tail = len(new)
    while old_tail > prefix and new_tail > prefix and old[old_tail - 1] == new[new_tail - 1]:
        old_tail -= 1
        new_tail -= 1
    return prefix, old_tail, new[prefix:new_tail]


class LspDocumentManager:
    def __init__(
        self,
        root: Path,
        transport: StdioJsonRpcTransport,
        capabilities: LspCapabilities,
        *,
        language_id_for_path,
        limits: SemanticCodeLimits = SemanticCodeLimits(),
    ):
        self.root = root
        self.transport = transport
        self.capabilities = capabilities
        self.language_id_for_path = language_id_for_path
        self.limits = limits
        self._lock = RLock()
        self._documents: dict[str, OpenDocument] = {}

    def current(self, relative_path: str) -> OpenDocument | None:
        with self._lock:
            return self._documents.get(relative_path)

    def open_path(self, relative_path: str) -> OpenDocument:
        snapshot = read_document_snapshot(self.root, relative_path, max_bytes=self.limits.max_file_bytes)
        return self.open_snapshot(snapshot)

    def open_snapshot(self, snapshot: DocumentSnapshot) -> OpenDocument:
        with self._lock:
            existing = self._documents.get(snapshot.relative_path)
            if existing is not None:
                if existing.sha256 == snapshot.raw_sha256:
                    return existing
                return self._sync_locked(existing, snapshot)
            uri = relative_path_to_uri(self.root, snapshot.relative_path)
            item = OpenDocument(
                snapshot.relative_path,
                uri,
                self.language_id_for_path(snapshot.relative_path),
                1,
                snapshot.text,
                snapshot.raw_sha256,
            )
            if self.capabilities.open_close:
                self.transport.notify(
                    "textDocument/didOpen",
                    {
                        "textDocument": {
                            "uri": uri,
                            "languageId": item.language_id,
                            "version": item.version,
                            "text": item.text,
                        }
                    },
                )
            self._documents[item.relative_path] = item
            return item

    def sync_path(self, relative_path: str) -> OpenDocument:
        snapshot = read_document_snapshot(self.root, relative_path, max_bytes=self.limits.max_file_bytes)
        return self.sync_snapshot(snapshot)

    def sync_snapshot(self, snapshot: DocumentSnapshot) -> OpenDocument:
        with self._lock:
            existing = self._documents.get(snapshot.relative_path)
            if existing is None:
                return self.open_snapshot(snapshot)
            if existing.sha256 == snapshot.raw_sha256:
                return existing
            return self._sync_locked(existing, snapshot)

    def _sync_locked(self, existing: OpenDocument, snapshot: DocumentSnapshot) -> OpenDocument:
        version = existing.version + 1
        if self.capabilities.text_sync_kind == 1:
            changes = [{"text": snapshot.text}]
        elif self.capabilities.text_sync_kind == 2:
            start, end, replacement = _single_replacement(existing.text, snapshot.text)
            try:
                change_range = offsets_to_range(existing.text, start, end, self.capabilities.position_encoding)
            except LspPositionError:
                # A minimal code-point diff can land between the CR and LF of a CRLF
                # sequence. LSP positions cannot represent that boundary, so preserve
                # incremental-sync semantics with one whole-document ranged change.
                change_range = offsets_to_range(
                    existing.text, 0, len(existing.text), self.capabilities.position_encoding
                )
                replacement = snapshot.text
            changes = [{"range": change_range.as_dict(), "text": replacement}]
        else:
            changes = []
        if changes:
            self.transport.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": existing.uri, "version": version},
                    "contentChanges": changes,
                },
            )
        item = OpenDocument(
            snapshot.relative_path,
            existing.uri,
            existing.language_id,
            version,
            snapshot.text,
            snapshot.raw_sha256,
        )
        self._documents[item.relative_path] = item
        return item

    def close(self, relative_path: str) -> None:
        with self._lock:
            item = self._documents.pop(relative_path, None)
        if item is not None and self.capabilities.open_close:
            self.transport.notify("textDocument/didClose", {"textDocument": {"uri": item.uri}})

    def close_all(self) -> None:
        with self._lock:
            paths = tuple(sorted(self._documents))
        for relative_path in paths:
            try:
                self.close(relative_path)
            except BaseException:
                continue

    @contextmanager
    def opened_path(self, relative_path: str) -> Iterator[OpenDocument]:
        was_open = self.current(relative_path) is not None
        item = self.sync_path(relative_path)
        try:
            yield item
        finally:
            if not was_open:
                self.close(relative_path)

    def version_for_uri(self, uri: str) -> int | None:
        with self._lock:
            for item in self._documents.values():
                if item.uri == uri:
                    return item.version
        return None

    def sha_for_uri(self, uri: str) -> str | None:
        with self._lock:
            for item in self._documents.values():
                if item.uri == uri:
                    return item.sha256
        return None
