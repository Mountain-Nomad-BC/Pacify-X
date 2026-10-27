"""One bounded, project/scope-bound generation vector for current consumers."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
from types import MappingProxyType

from .json_io import bounded_json_text, bounded_canonical_json_bytes

SCHEMA_VERSION = "px.context-generation-vector/1.0"
COMPONENTS = (
    "source_revision", "semantic_generation", "projection_generation", "runtime_epoch",
    "model_fabric_generation", "retrieval_generation", "authority_revision",
    "policy_revision", "execution_graph_revision",
)
EXECUTION_LINEAGE_COMPONENTS = (
    "model_execution_group_revision", "model_contract_set_revision", "gremlin_revision",
    "network_policy_revision", "workflow_adapter_revision",
)
ALL_COMPONENTS = COMPONENTS + EXECUTION_LINEAGE_COMPONENTS


def _text(value: object, label: str) -> str:
    if (type(value) is not str or not value.strip() or len(value) > 512
            or any(ord(character) < 32 for character in value)):
        raise ValueError(label + " must be bounded nonempty text")
    return value


@dataclass(frozen=True, slots=True)
class ContextGenerationVector:
    project_id: str
    scope: str
    component_items: tuple[tuple[str, str | None], ...]
    required_components: tuple[str, ...]

    def __post_init__(self):
        _text(self.project_id, "project_id")
        _text(self.scope, "scope")
        expected = ALL_COMPONENTS if type(self.component_items) is tuple and len(self.component_items) == len(ALL_COMPONENTS) else COMPONENTS
        if (type(self.component_items) is not tuple
                or len(self.component_items) != len(expected)
                or any(type(item) is not tuple or len(item) != 2 for item in self.component_items)
                or tuple(item[0] for item in self.component_items) != tuple(sorted(expected))):
            raise ValueError("vector components must be complete, unique and canonical")
        for _, revision in self.component_items:
            if revision is not None:
                _text(revision, "component revision")
        if (type(self.required_components) is not tuple or not self.required_components
                or any(type(name) is not str or name not in expected for name in self.required_components)
                or self.required_components != tuple(sorted(set(self.required_components)))):
            raise ValueError("required components must be nonempty, known and unique")

    @property
    def components(self) -> Mapping[str, str | None]:
        return MappingProxyType(dict(self.component_items))

    def _body(self) -> dict:
        return {"schema_version": SCHEMA_VERSION if len(self.component_items) == len(COMPONENTS) else "px.context-generation-vector/2.0", "project_id": self.project_id,
                "scope": self.scope, "vector": dict(self.component_items),
                "required_components": list(self.required_components)}

    @property
    def vector_sha256(self) -> str:
        return hashlib.sha256(bounded_canonical_json_bytes(self._body(), max_bytes=32*1024)).hexdigest()

    def as_mapping(self) -> dict:
        return {**self._body(), "vector_sha256": self.vector_sha256}


def context_vector(project_id: str, scope: str, components: Mapping[str, str | None],
                   *, required_components: Iterable[str] = COMPONENTS) -> ContextGenerationVector:
    if not isinstance(components, Mapping) or len(components) > len(ALL_COMPONENTS):
        raise ValueError("components require a bounded mapping")
    if any(name not in ALL_COMPONENTS for name in components):
        raise ValueError("unknown generation component")
    if isinstance(required_components, (str, bytes, Mapping)):
        raise ValueError("required components require a bounded sequence")
    required = []
    for index, name in enumerate(required_components):
        if index >= len(ALL_COMPONENTS) or name not in ALL_COMPONENTS or name in required:
            raise ValueError("required components must be bounded, known and unique")
        required.append(name)
    names = ALL_COMPONENTS if (set(components) | set(required)).intersection(EXECUTION_LINEAGE_COMPONENTS) else COMPONENTS
    return ContextGenerationVector(project_id, scope,
        tuple((name, components.get(name)) for name in sorted(names)), tuple(sorted(required)))


def read_context_vector(record: Mapping[str, object]) -> ContextGenerationVector:
    if type(record) is not dict:
        raise ValueError("generation vector record must be an object")
    bounded_json_text(record, max_bytes=32*1024)
    names = ALL_COMPONENTS if record.get("schema_version") == "px.context-generation-vector/2.0" else COMPONENTS
    if (set(record) != {"schema_version", "project_id", "scope", "vector", "required_components", "vector_sha256"}
            or record["schema_version"] not in {SCHEMA_VERSION, "px.context-generation-vector/2.0"}
            or type(record["vector"]) is not dict or set(record["vector"]) != set(names)
            or type(record["required_components"]) is not list):
        raise ValueError("generation vector record schema is invalid")
    vector = context_vector(record["project_id"], record["scope"], record["vector"],
                            required_components=record["required_components"])
    if record["vector_sha256"] != vector.vector_sha256:
        raise ValueError("generation vector digest differs from its bound inputs")
    return vector
