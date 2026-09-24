"""Deterministic LSP initialize parameters for PACIFY-X."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from .semantic_lsp_types import ServerSpec
from .semantic_lsp_uri import file_uri_to_path


DEFAULT_CONTENT_MODIFIED_RETRY_METHODS = frozenset({
    "textDocument/documentSymbol",
    "textDocument/definition",
    "textDocument/declaration",
    "textDocument/implementation",
    "textDocument/references",
    "textDocument/prepareRename",
    "textDocument/rename",
})


def client_capabilities(*, retry_methods: Iterable[str] = DEFAULT_CONTENT_MODIFIED_RETRY_METHODS) -> dict[str, Any]:
    retry = sorted({str(item) for item in retry_methods if item})
    return {
        "workspace": {
            "applyEdit": False,
            "workspaceFolders": True,
            "configuration": True,
            "workspaceEdit": {
                "documentChanges": True,
                "resourceOperations": [],
                "failureHandling": "abort",
                "normalizesLineEndings": False,
                "changeAnnotationSupport": {"groupsOnLabel": False},
            },
        },
        "textDocument": {
            "synchronization": {"dynamicRegistration": False, "willSave": False, "didSave": False},
            "documentSymbol": {"dynamicRegistration": False, "hierarchicalDocumentSymbolSupport": True},
            "definition": {"dynamicRegistration": False, "linkSupport": True},
            "declaration": {"dynamicRegistration": False, "linkSupport": True},
            "implementation": {"dynamicRegistration": False, "linkSupport": True},
            "references": {"dynamicRegistration": False},
            "rename": {"dynamicRegistration": False, "prepareSupport": True, "honorsChangeAnnotations": True},
            "publishDiagnostics": {"relatedInformation": True, "versionSupport": True, "codeDescriptionSupport": True},
        },
        "general": {
            "positionEncodings": ["utf-16", "utf-8", "utf-32"],
            "staleRequestSupport": {"cancel": True, "retryOnContentModified": retry},
        },
        "window": {"workDoneProgress": True, "showMessage": {"messageActionItem": {"additionalPropertiesSupport": False}}},
    }


def initialize_params(spec: ServerSpec, *, retry_methods: Iterable[str] = DEFAULT_CONTENT_MODIFIED_RETRY_METHODS) -> dict[str, Any]:
    root = file_uri_to_path(spec.root_uri)
    payload: dict[str, Any] = {
        "processId": os.getpid(),
        "clientInfo": {"name": "PACIFY-X", "version": "semantic-code-wave2"},
        "locale": "en-US",
        "rootUri": spec.root_uri,
        "rootPath": str(root),
        "capabilities": client_capabilities(retry_methods=retry_methods),
        "workspaceFolders": [{"uri": spec.root_uri, "name": Path(root).name or "project"}],
        "trace": "off",
    }
    if spec.initialization_options is not None:
        payload["initializationOptions"] = dict(spec.initialization_options)
    return payload
