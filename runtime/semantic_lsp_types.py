"""Stable value objects for PACIFY-X external language-service integration.

Wave 2 keeps transport/process details behind these immutable contracts.  No object
in this module launches a process or mutates a project.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from types import MappingProxyType
from typing import Any, Mapping


class ServerState(StrEnum):
    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    QUARANTINED = "quarantined"


class PositionEncoding(StrEnum):
    UTF8 = "utf-8"
    UTF16 = "utf-16"
    UTF32 = "utf-32"


@dataclass(frozen=True, slots=True)
class ServerSpec:
    server_id: str
    language: str
    argv: tuple[str, ...]
    root_uri: str
    initialization_options: Mapping[str, Any] | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    request_timeout_seconds: float = 20.0
    startup_timeout_seconds: float = 30.0
    shutdown_timeout_seconds: float = 5.0
    max_message_bytes: int = 16 * 1024 * 1024
    max_pending_requests: int = 128
    request_timeout_overrides: Mapping[str, float] = field(default_factory=dict)
    content_modified_retry_methods: tuple[str, ...] = (
        "textDocument/documentSymbol", "textDocument/definition", "textDocument/declaration",
        "textDocument/implementation", "textDocument/references", "textDocument/prepareRename",
        "textDocument/rename",
    )
    content_modified_max_attempts: int = 3
    stderr_tail_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if not isinstance(self.server_id, str) or not self.server_id.strip():
            raise ValueError("server_id is required")
        if not isinstance(self.language, str) or not self.language.strip():
            raise ValueError("language is required")
        if not self.root_uri.startswith("file:"):
            raise ValueError("root_uri must be a file URI")
        if not isinstance(self.argv, tuple) or not self.argv or any(
            type(x) is not str or not x or "\x00" in x for x in self.argv
        ):
            raise ValueError("argv must be a non-empty tuple of safe strings")
        if not isinstance(self.environment, Mapping):
            raise ValueError("environment must be a mapping")
        if self.initialization_options is not None and not isinstance(self.initialization_options, Mapping):
            raise ValueError("initialization_options must be a mapping when provided")
        if not isinstance(self.request_timeout_overrides, Mapping):
            raise ValueError("request_timeout_overrides must be a mapping")
        if not isinstance(self.content_modified_retry_methods, tuple):
            raise ValueError("content_modified_retry_methods must be a tuple")
        for key, value in self.environment.items():
            if type(key) is not str or not key or "=" in key or "\x00" in key:
                raise ValueError("environment keys must be safe strings")
            if type(value) is not str or "\x00" in value:
                raise ValueError("environment values must be safe strings")
        for value in (
            self.request_timeout_seconds,
            self.startup_timeout_seconds,
            self.shutdown_timeout_seconds,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value <= 0
                or value > 3600
            ):
                raise ValueError("language-server timeouts must be finite, > 0 and <= 3600 seconds")
        if type(self.max_message_bytes) is not int or not 1024 <= self.max_message_bytes <= 128 * 1024 * 1024:
            raise ValueError("max_message_bytes outside supported bounds")
        if type(self.max_pending_requests) is not int or not 1 <= self.max_pending_requests <= 4096:
            raise ValueError("max_pending_requests outside supported bounds")
        if type(self.stderr_tail_bytes) is not int or not 1024 <= self.stderr_tail_bytes <= 4 * 1024 * 1024:
            raise ValueError("stderr_tail_bytes outside supported bounds")
        if type(self.content_modified_max_attempts) is not int or not 1 <= self.content_modified_max_attempts <= 11:
            raise ValueError("content_modified_max_attempts outside supported bounds")
        retry_methods: list[str] = []
        seen_methods: set[str] = set()
        for method in self.content_modified_retry_methods:
            if type(method) is not str or not method.strip() or "\x00" in method:
                raise ValueError("content_modified_retry_methods must contain safe method names")
            if method not in seen_methods:
                retry_methods.append(method)
                seen_methods.add(method)
        overrides: dict[str, float] = {}
        for method, value in self.request_timeout_overrides.items():
            if type(method) is not str or not method.strip() or "\x00" in method:
                raise ValueError("request_timeout_overrides keys must be safe method names")
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or value <= 0
                or value > 3600
            ):
                raise ValueError("request timeout overrides must be finite, > 0 and <= 3600 seconds")
            overrides[method] = float(value)
        object.__setattr__(self, "environment", MappingProxyType(dict(self.environment)))
        if self.initialization_options is not None:
            object.__setattr__(self, "initialization_options", MappingProxyType(dict(self.initialization_options)))
        object.__setattr__(self, "request_timeout_overrides", MappingProxyType(overrides))
        object.__setattr__(self, "content_modified_retry_methods", tuple(retry_methods))


@dataclass(frozen=True, slots=True, order=True)
class LspPosition:
    line: int
    character: int

    def __post_init__(self) -> None:
        if type(self.line) is not int or type(self.character) is not int or self.line < 0 or self.character < 0:
            raise ValueError("LSP positions must be non-negative integers")

    def as_dict(self) -> dict[str, int]:
        return {"line": self.line, "character": self.character}


@dataclass(frozen=True, slots=True)
class LspRange:
    start: LspPosition
    end: LspPosition

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("LSP range end precedes start")

    def as_dict(self) -> dict[str, dict[str, int]]:
        return {"start": self.start.as_dict(), "end": self.end.as_dict()}


@dataclass(frozen=True, slots=True)
class LocationRecord:
    uri: str
    range: LspRange
    origin_selection_range: LspRange | None = None


@dataclass(frozen=True, slots=True)
class LspTextEdit:
    uri: str
    range: LspRange
    new_text: str
    version: int | None = None
    annotation_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceEditPlan:
    operation: str
    edits: tuple[LspTextEdit, ...]
    expected_sha256: Mapping[str, str]
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.operation.strip() or not self.source.strip():
            raise ValueError("workspace edit operation and source are required")
        if not self.edits:
            raise ValueError("workspace edit plan requires at least one edit")


@dataclass(frozen=True, slots=True)
class ServerHealthSnapshot:
    server_id: str
    state: ServerState
    starts: int
    failures: int
    consecutive_failures: int
    last_error: str | None
    quarantined_reason: str | None
