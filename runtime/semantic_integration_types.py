"""Stable value objects for semantic orchestration and knowledge integration."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import math
from typing import Any, Mapping

from .semantic_code_types import stable_sha256


class IntegrationEffect(StrEnum):
    READ = "read"
    PLAN = "plan"
    WRITE = "write"
    PROCESS = "process"
    NETWORK = "network"


def _bounded_text(value: str, field_name: str, *, max_bytes: int = 4096) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be nonempty text")
    if len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field_name} exceeds {max_bytes} UTF-8 bytes")


def _optional_score(value: float | None, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{field_name} must be finite and between 0 and 1")


@dataclass(frozen=True, slots=True)
class IntegrationOperation:
    name: str
    effects: tuple[IntegrationEffect, ...]
    risk: str
    source: str
    requires_project: bool = True
    cross_project_allowed: bool = False
    mutation: bool = False

    def __post_init__(self) -> None:
        _bounded_text(self.name, "operation name", max_bytes=256)
        _bounded_text(self.source, "operation source", max_bytes=128)
        if not self.effects:
            raise ValueError("operation requires at least one effect")
        normalized = tuple(IntegrationEffect(effect) for effect in self.effects)
        if len(set(normalized)) != len(normalized):
            raise ValueError("operation effects must be unique")
        object.__setattr__(self, "effects", normalized)
        if self.risk not in {"R0", "R1", "R2", "R3", "R4"}:
            raise ValueError("operation risk must be R0-R4")
        if type(self.requires_project) is not bool or type(self.cross_project_allowed) is not bool or type(self.mutation) is not bool:
            raise TypeError("operation flags must be booleans")
        if self.mutation and IntegrationEffect.WRITE not in normalized:
            raise ValueError("mutation operation must declare write effect")


@dataclass(frozen=True, slots=True)
class ContextProfile:
    name: str
    client_family: str
    allowed_effects: tuple[IntegrationEffect, ...]
    max_risk: str = "R1"
    single_project: bool = False
    cross_project: bool = False
    structured_output: bool = True

    def __post_init__(self) -> None:
        _bounded_text(self.name, "context name", max_bytes=128)
        _bounded_text(self.client_family, "client family", max_bytes=128)
        effects = tuple(IntegrationEffect(effect) for effect in self.allowed_effects)
        if len(set(effects)) != len(effects):
            raise ValueError("context effects must be unique")
        object.__setattr__(self, "allowed_effects", effects)
        if self.max_risk not in {"R0", "R1", "R2", "R3", "R4"}:
            raise ValueError("context max_risk must be R0-R4")
        if any(type(flag) is not bool for flag in (self.single_project, self.cross_project, self.structured_output)):
            raise TypeError("context flags must be booleans")
        if self.single_project and self.cross_project:
            raise ValueError("context cannot be both single-project and cross-project")


@dataclass(frozen=True, slots=True)
class ModeProfile:
    name: str
    allowed_effects: tuple[IntegrationEffect, ...]
    excluded_operations: tuple[str, ...] = ()
    required_operations: tuple[str, ...] = ()
    cross_project: bool = False
    memory_enabled: bool = True
    mutually_exclusive: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_text(self.name, "mode name", max_bytes=128)
        effects = tuple(IntegrationEffect(effect) for effect in self.allowed_effects)
        if len(set(effects)) != len(effects):
            raise ValueError("mode effects must be unique")
        object.__setattr__(self, "allowed_effects", effects)
        for values, label in (
            (self.excluded_operations, "excluded_operations"),
            (self.required_operations, "required_operations"),
            (self.mutually_exclusive, "mutually_exclusive"),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{label} must be unique")
            for value in values:
                _bounded_text(value, label, max_bytes=256)
        if type(self.cross_project) is not bool or type(self.memory_enabled) is not bool:
            raise TypeError("mode flags must be booleans")


@dataclass(frozen=True, slots=True)
class CapabilityProjection:
    context: str
    modes: tuple[str, ...]
    operations: tuple[str, ...]
    denied: tuple[tuple[str, str], ...]
    projection_sha256: str

    def __post_init__(self) -> None:
        _bounded_text(self.context, "projection context", max_bytes=128)
        if tuple(sorted(set(self.modes))) != self.modes:
            raise ValueError("projection modes must be unique and sorted")
        if tuple(sorted(set(self.operations))) != self.operations:
            raise ValueError("projection operations must be unique and sorted")
        if tuple(sorted(set(self.denied))) != self.denied:
            raise ValueError("projection denials must be unique and sorted")
        if len(self.projection_sha256) != 64:
            raise ValueError("projection_sha256 must be a SHA-256 hex digest")
        try:
            int(self.projection_sha256, 16)
        except ValueError as exc:
            raise ValueError("projection_sha256 must be a SHA-256 hex digest") from exc


@dataclass(frozen=True, slots=True)
class ProjectDescriptor:
    project_id: str
    root: str
    read_only: bool = True
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_text(self.project_id, "project_id", max_bytes=256)
        _bounded_text(self.root, "project root", max_bytes=8192)
        if type(self.read_only) is not bool:
            raise TypeError("read_only must be a boolean")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("project labels must be unique")
        for label in self.labels:
            _bounded_text(label, "project label", max_bytes=256)


@dataclass(frozen=True, slots=True)
class QueryAuthorization:
    token_id: str
    actor_id: str
    project_ids: tuple[str, ...]
    operations: tuple[str, ...]
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.token_id, "authorization token_id", max_bytes=512)
        _bounded_text(self.actor_id, "authorization actor_id", max_bytes=512)
        if not self.project_ids:
            raise ValueError("authorization requires at least one project_id")
        if len(set(self.project_ids)) != len(self.project_ids):
            raise ValueError("authorization project_ids must be unique")
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("authorization operations must be unique")
        for project_id in self.project_ids:
            _bounded_text(project_id, "authorization project_id", max_bytes=256)
        for operation in self.operations:
            _bounded_text(operation, "authorization operation", max_bytes=256)
        if self.expires_at is not None:
            if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
                raise ValueError("authorization expiry must be timezone-aware")

    def expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("authorization time must be timezone-aware")
        return current.astimezone(timezone.utc) >= self.expires_at.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class SemanticEvidence:
    source_id: str
    source_kind: str
    title: str
    text: str
    project_id: str
    lineage: str
    locator: str
    revision: str | None = None
    visibility: tuple[str, ...] = ("project",)
    trust: float | None = None
    dense_score: float | None = None
    graph_score: float | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
    structured: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, label, limit in (
            (self.source_id, "source_id", 512),
            (self.source_kind, "source_kind", 128),
            (self.title, "title", 4096),
            (self.project_id, "project_id", 256),
            (self.lineage, "lineage", 4096),
            (self.locator, "locator", 8192),
        ):
            _bounded_text(value, label, max_bytes=limit)
        if type(self.text) is not str or len(self.text.encode("utf-8")) > 256 * 1024:
            raise ValueError("evidence text must be text bounded to 262144 UTF-8 bytes")
        if self.revision is not None:
            _bounded_text(self.revision, "revision", max_bytes=512)
        if not self.visibility or len(set(self.visibility)) != len(self.visibility):
            raise ValueError("visibility must be a nonempty unique tuple")
        for value in self.visibility:
            _bounded_text(value, "visibility", max_bytes=128)
        _optional_score(self.trust, "trust")
        _optional_score(self.dense_score, "dense_score")
        _optional_score(self.graph_score, "graph_score")
        if not isinstance(self.metadata, Mapping) or not isinstance(self.structured, Mapping):
            raise TypeError("metadata and structured must be mappings")


@dataclass(frozen=True, slots=True)
class FusedQueryResult:
    query: str
    project_id: str
    hits: tuple[Mapping[str, object], ...]
    source_counts: Mapping[str, int]
    context_bytes: int
    canonical_retrieval_owner: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        _bounded_text(self.query, "query", max_bytes=64 * 1024)
        _bounded_text(self.project_id, "project_id", max_bytes=256)
        _bounded_text(self.canonical_retrieval_owner, "canonical_retrieval_owner", max_bytes=512)
        if type(self.context_bytes) is not int or self.context_bytes < 0:
            raise ValueError("context_bytes must be a non-negative integer")
        if len(self.receipt_sha256) != 64:
            raise ValueError("receipt_sha256 must be a SHA-256 digest")
        try:
            int(self.receipt_sha256, 16)
        except ValueError as exc:
            raise ValueError("receipt_sha256 must be a SHA-256 digest") from exc
        if not isinstance(self.source_counts, Mapping):
            raise TypeError("source_counts must be a mapping")
        for key, count in self.source_counts.items():
            _bounded_text(str(key), "source count key", max_bytes=128)
            if type(count) is not int or count < 0:
                raise ValueError("source counts must be non-negative integers")


def projection_digest(
    context: str,
    modes: tuple[str, ...],
    operations: tuple[str, ...],
    denied: tuple[tuple[str, str], ...],
) -> str:
    return stable_sha256(
        {"context": context, "modes": modes, "operations": operations, "denied": denied}
    )


def plain(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {key: plain(item) for key, item in asdict(value).items()}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value
