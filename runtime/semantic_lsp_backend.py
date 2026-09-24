"""Wave-1 SemanticBackend implementation backed by a live LSP client."""
from __future__ import annotations

from .semantic_code_backend import SemanticBackend
from .semantic_code_document import DocumentSnapshot, read_document_snapshot
from .semantic_code_types import SemanticDocument
from .semantic_lsp_client import LspClient
from .semantic_lsp_diagnostics import normalized_diagnostics
from .semantic_lsp_normalize import normalize_document_symbols


class LspSemanticBackend(SemanticBackend):
    def __init__(self, client: LspClient):
        self.client = client
        self.key = f"lsp-{client.adapter.key}"
        self.language = client.adapter.language
        self.suffixes = tuple(client.adapter.suffixes)

    def analyze(self, snapshot: DocumentSnapshot) -> SemanticDocument:
        if not self.client.is_running() or self.client.capabilities is None or self.client.documents is None:
            raise RuntimeError("LSP semantic backend requires a running client")
        caps = self.client.capabilities
        documents = self.client.documents
        if caps.text_sync_kind == 0:
            disk = read_document_snapshot(
                self.client.root, snapshot.relative_path, max_bytes=self.client.limits.max_file_bytes
            )
            if disk.raw_sha256 != snapshot.raw_sha256:
                raise RuntimeError(
                    "language server declares textDocumentSync=None; PX cannot truthfully analyze an unsaved candidate"
                )
        was_open = documents.current(snapshot.relative_path) is not None
        document = documents.sync_snapshot(snapshot)
        try:
            symbols = ()
            if caps.document_symbols:
                payload = self.client.request("textDocument/documentSymbol", {"textDocument": {"uri": document.uri}})
                symbols = normalize_document_symbols(
                    self.client.root,
                    snapshot.relative_path,
                    payload,
                    language=self.language,
                    encoding=caps.position_encoding,
                    limits=self.client.limits,
                    snapshot=snapshot,
                )
            publication = self.client.diagnostics.get(document.uri, minimum_version=document.version)
            diagnostics = () if publication is None else normalized_diagnostics(
                self.client.root,
                publication,
                encoding=caps.position_encoding,
                limits=self.client.limits,
                snapshot=snapshot,
            )
            return SemanticDocument(
                relative_path=snapshot.relative_path,
                language=self.language,
                sha256=snapshot.raw_sha256,
                size_bytes=snapshot.size_bytes,
                symbols=symbols,
                diagnostics=diagnostics,
            )
        finally:
            if not was_open:
                documents.close(snapshot.relative_path)
