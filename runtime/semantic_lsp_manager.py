"""Bounded project/server ownership for Wave-2 language services."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from .semantic_code_limits import SemanticCodeLimits
from .semantic_code_paths import canonical_project_root
from .semantic_lsp_client import LspClient
from .semantic_lsp_health import RestartPolicy
from .semantic_lsp_registry import LspAdapterRegistry
from .semantic_lsp_types import ServerSpec
from .semantic_lsp_uri import path_to_file_uri


class LanguageServerUnavailable(RuntimeError):
    pass


class LspClientManager:
    def __init__(
        self,
        *,
        registry: LspAdapterRegistry | None = None,
        max_clients: int = 8,
        restart_policy: RestartPolicy = RestartPolicy(),
        limits: SemanticCodeLimits = SemanticCodeLimits(),
        allow_launch_overrides: bool = False,
    ):
        if type(max_clients) is not int or not 1 <= max_clients <= 64:
            raise ValueError("max_clients outside supported bounds")
        self.registry = registry or LspAdapterRegistry()
        self.max_clients = max_clients
        self.restart_policy = restart_policy
        self.limits = limits
        self.allow_launch_overrides = bool(allow_launch_overrides)
        self._lock = RLock()
        self._clients: dict[tuple[str, str], LspClient] = {}

    @staticmethod
    def _key(root: Path, adapter_key: str) -> tuple[str, str]:
        return (str(canonical_project_root(root)), adapter_key.casefold())

    def open(
        self,
        root: Path,
        adapter_key: str,
        *,
        argv: tuple[str, ...] | None = None,
        environment: Mapping[str, str] | None = None,
        initialization_options: Mapping[str, Any] | None = None,
        configuration: Mapping[str, Any] | None = None,
    ) -> LspClient:
        root = canonical_project_root(root)
        adapter = self.registry.get(adapter_key)
        if adapter is None:
            raise LanguageServerUnavailable(f"unknown language-server adapter: {adapter_key}")
        if not self.allow_launch_overrides and (argv is not None or environment is not None):
            raise LanguageServerUnavailable(
                "explicit language-server argv/environment overrides require trusted launch authority"
            )

        requested_environment = dict(environment or {})
        requested_initialization = None if initialization_options is None else dict(initialization_options)
        requested_configuration = dict(configuration or {})
        if argv is None:
            discovery_env = os.environ.copy()
            discovery_env.update(requested_environment)
            candidates = adapter.discover_argv(environment=discovery_env)
            if not candidates:
                raise LanguageServerUnavailable(
                    f"no executable discovered for adapter {adapter.key}; Wave 2 never auto-installs servers"
                )
            requested_argv = tuple(candidates[0])
        else:
            requested_argv = tuple(argv)

        root_uri = path_to_file_uri(root)
        root_digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
        spec = ServerSpec(
            server_id=f"{adapter.key}:{root_digest}",
            language=adapter.language,
            argv=requested_argv,
            root_uri=root_uri,
            initialization_options=requested_initialization,
            environment=requested_environment,
        )
        key = self._key(root, adapter.key)
        with self._lock:
            existing = self._clients.get(key)
            if existing is not None:
                same_spec = (
                    existing.spec.argv == spec.argv
                    and dict(existing.spec.environment) == dict(spec.environment)
                    and (
                        None if existing.spec.initialization_options is None else dict(existing.spec.initialization_options)
                    ) == (None if spec.initialization_options is None else dict(spec.initialization_options))
                    and existing.configuration == requested_configuration
                )
                if not same_spec:
                    raise LanguageServerUnavailable(
                        "existing language-server client has different launch/configuration authority; close it before reopening"
                    )
                if not existing.is_running():
                    existing.restart()
                return existing
            if len(self._clients) >= self.max_clients:
                raise LanguageServerUnavailable("language-server client budget exhausted")
            client = LspClient(
                spec,
                adapter,
                configuration=requested_configuration,
                restart_policy=self.restart_policy,
                limits=self.limits,
            )
            client.start()
            self._clients[key] = client
            return client

    def get(self, root: Path, adapter_key: str) -> LspClient | None:
        key = self._key(root, adapter_key)
        with self._lock:
            return self._clients.get(key)

    def close(self, root: Path, adapter_key: str) -> None:
        key = self._key(root, adapter_key)
        with self._lock:
            client = self._clients.pop(key, None)
        if client is not None:
            client.shutdown()

    def close_all(self) -> None:
        with self._lock:
            clients = tuple(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                client.shutdown()
            except BaseException:
                continue

    def health_inventory(self) -> tuple[object, ...]:
        with self._lock:
            clients = tuple(self._clients.values())
        return tuple(client.health.snapshot() for client in clients)
