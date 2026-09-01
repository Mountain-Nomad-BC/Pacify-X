"""Bounded structured semantics for canonical project memory records.

Canonical truth remains the individually revisioned ``MemoryRecord``.  This
module supplies a uniform semantic envelope and deterministic routing/graph
signals; embeddings and other indexes are rebuildable projections.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Mapping


SCHEMA_VERSION = "px.semantic-memory-envelope/1.0"
VALIDATION_STATES = frozenset({"candidate", "validated", "certified"})
TOKEN = re.compile(r"[a-z0-9_.:/-]+")
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_PAYLOAD_DEPTH = 8
MAX_PAYLOAD_NODES = 512
MAX_ROUTING_VALUES = 64
MAX_ENTITIES = 128
MAX_RELATIONS = 256


def _normalize(value: object) -> str:
    return "-".join(TOKEN.findall(str(value).strip().casefold()))[:160].strip("-")


def _dedupe(values: object, *, limit: int = MAX_ROUTING_VALUES) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    normalized = tuple(
        dict.fromkeys(item for item in (_normalize(value) for value in values) if item)
    )
    return normalized[:limit]


def _canonical_values(values: object, *, limit: int = MAX_ROUTING_VALUES) -> list[str]:
    return sorted(_dedupe(values, limit=limit))


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(map(str, value))


def _json_errors(value: object) -> tuple[str, ...]:
    errors: list[str] = []
    nodes = 0

    def walk(item: object, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_PAYLOAD_NODES:
            errors.append("semantic_payload_node_limit")
            return
        if depth > MAX_PAYLOAD_DEPTH:
            errors.append("semantic_payload_depth_limit")
            return
        if item is None or isinstance(item, (str, int, float, bool)):
            return
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str) or not key.strip():
                    errors.append("semantic_payload_key_invalid")
                    continue
                walk(child, depth + 1)
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                walk(child, depth + 1)
            return
        errors.append("semantic_payload_not_json")

    walk(value, 0)
    try:
        rendered = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    except (TypeError, ValueError):
        errors.append("semantic_payload_not_json")
    else:
        if len(rendered) > MAX_PAYLOAD_BYTES:
            errors.append("semantic_payload_byte_limit")
    return tuple(sorted(set(errors)))


@dataclass(frozen=True, slots=True)
class SemanticEntity:
    entity_id: str
    entity_type: str
    aliases: tuple[str, ...] = ()

    def normalized(self) -> "SemanticEntity":
        return SemanticEntity(
            _normalize(self.entity_id),
            _normalize(self.entity_type),
            _dedupe(self.aliases),
        )


@dataclass(frozen=True, slots=True)
class SemanticRelation:
    source_id: str
    predicate: str
    target_id: str
    confidence: float = 1.0
    evidence_locator: str = ""

    def normalized(self) -> "SemanticRelation":
        return SemanticRelation(
            _normalize(self.source_id),
            _normalize(self.predicate).upper().replace("-", "_"),
            _normalize(self.target_id),
            float(self.confidence),
            str(self.evidence_locator).strip(),
        )


@dataclass(frozen=True, slots=True)
class SemanticEnvelope:
    namespace: str
    record_type: str
    payload: Mapping[str, object]
    exact_keys: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    entities: tuple[SemanticEntity, ...] = ()
    relations: tuple[SemanticRelation, ...] = ()
    required_context: Mapping[str, object] | None = None
    excluded_context: Mapping[str, object] | None = None
    validation_status: str = "candidate"
    validation_checks: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def validation_errors(self, *, project_id: str | None = None) -> tuple[str, ...]:
        errors: list[str] = []
        if self.schema_version != SCHEMA_VERSION:
            errors.append("semantic_schema_version_invalid")
        namespace = _normalize(self.namespace)
        if not namespace:
            errors.append("semantic_namespace_missing")
        if project_id and namespace not in {
            _normalize(project_id),
            _normalize(f"project:{project_id}"),
        }:
            errors.append("semantic_namespace_crosses_project")
        if not _normalize(self.record_type):
            errors.append("semantic_record_type_missing")
        exact_keys = _dedupe(self.exact_keys)
        if not exact_keys:
            errors.append("semantic_exact_keys_missing")
        if len(self.exact_keys) > MAX_ROUTING_VALUES:
            errors.append("semantic_exact_keys_limit")
        if len(self.aliases) > MAX_ROUTING_VALUES or len(self.tags) > MAX_ROUTING_VALUES:
            errors.append("semantic_routing_limit")
        if self.validation_status not in VALIDATION_STATES:
            errors.append("semantic_validation_status_invalid")
        if not isinstance(self.payload, Mapping) or not self.payload:
            errors.append("semantic_payload_missing")
        else:
            errors.extend(_json_errors(self.payload))
        for context in (self.required_context or {}, self.excluded_context or {}):
            if not isinstance(context, Mapping):
                errors.append("semantic_context_not_object")
            else:
                errors.extend(_json_errors(context))

        normalized_entities = tuple(entity.normalized() for entity in self.entities)
        if len(normalized_entities) > MAX_ENTITIES:
            errors.append("semantic_entity_limit")
        entity_ids = [entity.entity_id for entity in normalized_entities]
        if any(not entity.entity_id or not entity.entity_type for entity in normalized_entities):
            errors.append("semantic_entity_invalid")
        if len(entity_ids) != len(set(entity_ids)):
            errors.append("semantic_entity_duplicate")

        normalized_relations = tuple(
            relation.normalized() for relation in self.relations
        )
        if len(normalized_relations) > MAX_RELATIONS:
            errors.append("semantic_relation_limit")
        for relation in normalized_relations:
            if (
                not relation.source_id
                or not relation.predicate
                or not relation.target_id
                or relation.source_id not in entity_ids
                or relation.target_id not in entity_ids
            ):
                errors.append("semantic_relation_dangling")
            if not 0.0 <= relation.confidence <= 1.0:
                errors.append("semantic_relation_confidence_invalid")
            if not relation.evidence_locator:
                errors.append("semantic_relation_evidence_missing")
        return tuple(sorted(set(errors)))

    def canonical_mapping(self) -> dict[str, object]:
        value = asdict(self)
        value["namespace"] = _normalize(self.namespace)
        value["record_type"] = _normalize(self.record_type)
        value["exact_keys"] = _canonical_values(self.exact_keys)
        value["aliases"] = _canonical_values(self.aliases)
        value["tags"] = _canonical_values(self.tags)
        value["entities"] = [
            {
                **asdict(entity.normalized()),
                "aliases": _canonical_values(entity.aliases),
            }
            for entity in sorted(
                self.entities, key=lambda item: item.normalized().entity_id
            )
        ]
        value["relations"] = [
            asdict(relation.normalized())
            for relation in sorted(
                self.relations,
                key=lambda item: (
                    item.normalized().source_id,
                    item.normalized().predicate,
                    item.normalized().target_id,
                    item.normalized().evidence_locator,
                ),
            )
        ]
        value["validation_checks"] = _canonical_values(self.validation_checks)
        value["required_context"] = dict(self.required_context or {})
        value["excluded_context"] = dict(self.excluded_context or {})
        return value

    def canonical_sha256(self) -> str:
        rendered = json.dumps(
            self.canonical_mapping(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def semantic_envelope_from_mapping(value: Mapping[str, object]) -> SemanticEnvelope:
    raw_entities = _mapping_sequence(value.get("entities", ()))
    raw_relations = _mapping_sequence(value.get("relations", ()))
    entities = tuple(
        SemanticEntity(
            str(item.get("entity_id", "")),
            str(item.get("entity_type", "")),
            _string_sequence(item.get("aliases", ())),
        )
        for item in raw_entities
    )
    relations = tuple(
        SemanticRelation(
            str(item.get("source_id", "")),
            str(item.get("predicate", "")),
            str(item.get("target_id", "")),
            float(item.get("confidence", 1.0)),
            str(item.get("evidence_locator", "")),
        )
        for item in raw_relations
    )
    payload = value.get("payload", {})
    required = value.get("required_context", {})
    excluded = value.get("excluded_context", {})
    return SemanticEnvelope(
        namespace=str(value.get("namespace", "")),
        record_type=str(value.get("record_type", "")),
        payload=dict(payload) if isinstance(payload, Mapping) else {},
        exact_keys=_string_sequence(value.get("exact_keys", ())),
        aliases=_string_sequence(value.get("aliases", ())),
        tags=_string_sequence(value.get("tags", ())),
        entities=entities,
        relations=relations,
        required_context=dict(required) if isinstance(required, Mapping) else {},
        excluded_context=dict(excluded) if isinstance(excluded, Mapping) else {},
        validation_status=str(value.get("validation_status", "candidate")),
        validation_checks=_string_sequence(value.get("validation_checks", ())),
        schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
    )


def semantic_query_signals(
    query: str, envelope: SemanticEnvelope | None
) -> tuple[int, float]:
    """Return deterministic exact priority and bounded structured overlap."""
    if envelope is None:
        return 1, 0.0
    normalized = _normalize(query)
    query_terms = set(TOKEN.findall(normalized))
    exact = set(_dedupe(envelope.exact_keys))
    aliases = set(_dedupe(envelope.aliases))
    tags = set(_dedupe(envelope.tags))
    entities = {entity.normalized().entity_id for entity in envelope.entities}
    predicates = {
        relation.normalized().predicate.casefold().replace("_", "-")
        for relation in envelope.relations
    }
    exact_hit = normalized in exact or any(
        f"-{item}-" in f"-{normalized}-" for item in exact if item
    )
    alias_hit = normalized in aliases or any(
        f"-{item}-" in f"-{normalized}-" for item in aliases if item
    )
    signal_terms = exact | aliases | tags | entities | predicates
    flattened = {term for value in signal_terms for term in TOKEN.findall(value)}
    union = query_terms | flattened
    overlap = len(query_terms & flattened) / len(union) if union else 0.0
    score = min(1.0, overlap + (0.35 if exact_hit else 0.15 if alias_hit else 0.0))
    return (0 if exact_hit else 1), score


def semantic_index_projection(envelope: SemanticEnvelope | None) -> dict[str, object]:
    if envelope is None:
        return {}
    value = envelope.canonical_mapping()
    return {
        "semantic_sha256": envelope.canonical_sha256(),
        "namespace": value["namespace"],
        "record_type": value["record_type"],
        "exact_keys": value["exact_keys"],
        "aliases": value["aliases"],
        "tags": value["tags"],
        "entity_ids": [item["entity_id"] for item in value["entities"]],
        "relations": value["relations"],
        "validation_status": value["validation_status"],
    }
