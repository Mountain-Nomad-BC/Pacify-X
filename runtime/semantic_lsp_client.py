"""Lifecycle-safe LSP client with PX failure isolation and conservative server handlers."""
from __future__ import annotations

from pathlib import Path
import subprocess
from threading import RLock
from typing import Any, Mapping

from .semantic_code_limits import SemanticCodeLimits
from .semantic_lsp_adapters import Adapter
from .semantic_lsp_capabilities import LspCapabilities, parse_capabilities
from .semantic_lsp_diagnostics import LspDiagnosticStore
from .semantic_lsp_documents import LspDocumentManager
from .semantic_lsp_health import RestartPolicy, ServerHealth
from .semantic_lsp_initialize import DEFAULT_CONTENT_MODIFIED_RETRY_METHODS, initialize_params
from .semantic_lsp_transport import LanguageServerTerminatedError, StdioJsonRpcTransport
from .semantic_lsp_types import ServerSpec
from .semantic_lsp_uri import file_uri_to_path


class LspInitializationError(RuntimeError):
    pass


class LspClient:
    def __init__(
        self,
        spec: ServerSpec,
        adapter: Adapter,
        *,
        configuration: Mapping[str, Any] | None = None,
        retry_methods: frozenset[str] | None = None,
        restart_policy: RestartPolicy = RestartPolicy(),
        limits: SemanticCodeLimits = SemanticCodeLimits(),
    ):
        self.spec = spec
        self.adapter = adapter
        self.configuration = dict(configuration or {})
        self.retry_methods = frozenset(spec.content_modified_retry_methods) if retry_methods is None else retry_methods
        self.limits = limits
        self.health = ServerHealth(spec.server_id, restart_policy)
        self.diagnostics = LspDiagnosticStore()
        self.capabilities: LspCapabilities | None = None
        self.documents: LspDocumentManager | None = None
        self._transport: StdioJsonRpcTransport | None = None
        self._lock = RLock()
        self._stopping = False
        self._initialized = False

    @property
    def root(self) -> Path:
        return file_uri_to_path(self.spec.root_uri)

    @property
    def transport(self) -> StdioJsonRpcTransport:
        if self._transport is None:
            raise RuntimeError("LSP client is not started")
        return self._transport

    def is_running(self) -> bool:
        if not self._initialized or self._transport is None:
            return False
        running = self._transport.is_running()
        if not running and not self._stopping:
            snapshot = self.health.snapshot()
            if snapshot.state.value in {"starting", "running"}:
                error = self._transport.termination_error or RuntimeError("language server exited unexpectedly")
                self.health.mark_failure(error)
        return running

    def _build_transport(self) -> StdioJsonRpcTransport:
        transport = StdioJsonRpcTransport(
            self.spec,
            content_modified_retry_methods=self.retry_methods,
            max_content_modified_retries=self.spec.content_modified_max_attempts - 1,
        )
        transport.register_request_handler("workspace/configuration", self._workspace_configuration)
        transport.register_request_handler("workspace/workspaceFolders", self._workspace_folders)
        transport.register_request_handler("workspace/applyEdit", self._reject_apply_edit)
        transport.register_request_handler("window/workDoneProgress/create", lambda _params: None)
        transport.register_request_handler("window/showMessageRequest", lambda _params: None)
        transport.register_request_handler("client/registerCapability", lambda _params: None)
        transport.register_request_handler("client/unregisterCapability", lambda _params: None)
        transport.register_request_handler("workspace/executeClientCommand", lambda _params: [])
        transport.register_notification_handler("textDocument/publishDiagnostics", self._publish_diagnostics)
        transport.register_termination_handler(self._on_terminated)
        return transport

    def start(self) -> None:
        with self._lock:
            if self.is_running():
                return
            self.health.mark_starting()
            self._stopping = False
            self._initialized = False
            transport = self._build_transport()
            self._transport = transport
            try:
                transport.start()
                result = transport.request(
                    "initialize",
                    initialize_params(self.spec, retry_methods=self.retry_methods),
                    timeout=self.spec.startup_timeout_seconds,
                )
                if not isinstance(result, dict) or not isinstance(result.get("capabilities"), dict):
                    raise LspInitializationError("language server returned malformed initialize result")
                capabilities = parse_capabilities(result["capabilities"])
                self.capabilities = capabilities
                self.documents = LspDocumentManager(
                    self.root,
                    transport,
                    capabilities,
                    language_id_for_path=self.adapter.language_id_for_path,
                    limits=self.limits,
                )
                transport.notify("initialized", {})
                self._initialized = True
                self.health.mark_running()
            except BaseException as exc:
                self.health.mark_failure(exc)
                self._stopping = True
                try:
                    transport.close(terminate_process=True)
                finally:
                    self._initialized = False
                raise

    def _workspace_configuration(self, params: Any) -> list[Any]:
        items = params.get("items", []) if isinstance(params, dict) else []
        if not isinstance(items, list):
            return []
        result: list[Any] = []
        for item in items:
            section = item.get("section") if isinstance(item, dict) else None
            if isinstance(section, str) and section:
                current: Any = self.configuration
                for part in section.split("."):
                    if not isinstance(current, Mapping) or part not in current:
                        current = None
                        break
                    current = current[part]
                result.append(current)
            else:
                result.append(dict(self.configuration))
        return result

    def _workspace_folders(self, _params: Any) -> list[dict[str, str]]:
        return [{"uri": self.spec.root_uri, "name": self.root.name or "project"}]

    def _reject_apply_edit(self, _params: Any) -> dict[str, Any]:
        return {
            "applied": False,
            "failureReason": "PACIFY-X rejects unsolicited server workspace edits; request a revision-bound edit plan instead",
        }

    def _publish_diagnostics(self, params: Any) -> None:
        uri = params.get("uri") if isinstance(params, dict) else None
        version = self.documents.version_for_uri(uri) if self.documents is not None and isinstance(uri, str) else None
        self.diagnostics.publish(params, current_version=version)

    def _on_terminated(self, error: BaseException | None) -> None:
        if self._stopping:
            return
        self._initialized = False
        if error is not None:
            self.health.mark_failure(error)

    def request(self, method: str, params: Any = None, *, timeout: float | None = None) -> Any:
        if not self.is_running():
            raise LanguageServerTerminatedError("LSP client is not running")
        effective_timeout = self.spec.request_timeout_overrides.get(method) if timeout is None else timeout
        return self.transport.request(method, params, timeout=effective_timeout)

    def notify(self, method: str, params: Any = None) -> None:
        if not self.is_running():
            raise LanguageServerTerminatedError("LSP client is not running")
        self.transport.notify(method, params)

    def shutdown(self) -> None:
        with self._lock:
            transport = self._transport
            if transport is None:
                self.health.mark_stopped()
                return
            self._stopping = True
            self.health.mark_stopping()
            if self.documents is not None:
                self.documents.close_all()
            try:
                if transport.is_running() and self._initialized:
                    try:
                        transport.request("shutdown", None, timeout=self.spec.shutdown_timeout_seconds)
                        transport.notify("exit", None)
                    except BaseException:
                        pass
                if transport.process.is_running():
                    try:
                        transport.process.wait(timeout=self.spec.shutdown_timeout_seconds)
                    except subprocess.TimeoutExpired:
                        transport.process.terminate_tree(timeout=self.spec.shutdown_timeout_seconds)
            finally:
                transport.close(terminate_process=transport.process.is_running())
                self._initialized = False
                self._transport = None
                self.documents = None
                self.capabilities = None
                self.health.mark_stopped()

    def restart(self) -> None:
        self.shutdown()
        self.start()

    def clear_quarantine(self) -> None:
        self.health.clear_quarantine()
