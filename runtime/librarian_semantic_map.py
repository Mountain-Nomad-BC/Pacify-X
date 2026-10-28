"""Librarian semantic map: the unified ontology the resident 4B model navigates.

The librarian is a small model whose expertise comes from ONE thing: it can answer
"what is this, where is it, what owns it, what is it related to, and what may I do
with it" over a fully-mapped system, without scanning the repository.

Three canonical roots form that map (directive sections 2, 4, 13, 28):

    registry/            ontology + relational hub
                         capability_map, models, tools, skills, knowledge_sources,
                         agency agents, graph_manifest -> derived graphs
    contracts/           the typed schemas / authority every asset must satisfy
    knowledge/nsai/      validated semantic objects with cross-domain relationship
                         edges (74 objects, every one carrying relationship_targets)

This module joins them into a single navigable index:

    entity  (registry asset or nsai object)
      - kind / namespace / object_type
      - canonical id + source path
      - contract(s) that govern it
      - relationship edges (typed, cross-namespace)
      - search terms

and exposes deterministic lookups an LLM cannot fake:

    load_semantic_map(root)                  -> SemanticMap
    resolve_entity(map, query)               -> ranked EntityMatch
    traverse(map, entity_id, relation)       -> neighbours
    describe_entity(map, entity_id)          -> grounded, cited description

Design rule: this layer is evidence, not inference. An entity is only described from
fields that actually exist in the three roots. Unknown ids return an explicit miss.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Callable
from types import MappingProxyType

from .semantic_entity import EntityRegistry, EntityRecord, SemanticEntityError, identity_basis_for
from .semantic_locator import LocatorRegistry, LocatorRecord, RelationRegistry, RelationRecord, LocatorReferencePolicy, LOCATOR_KINDS
from .compact_address import (
    CompactAddressAllocator,
    CompactAddress,
    concepts_for_entity_kind,
    parse_alias,
    ALIAS_PREFIX,
)
from .context_generation import ContextGenerationVector
from .dependency_invalidation import context_vector_for_dependencies
from .projection_gate import evaluate_projection, ProjectionReadPolicy
from .bounded_walk import bounded_walk, WalkLimits
from .archive_io import reject_path_links
from .json_io import read_bounded_bytes, bounded_canonical_json_bytes, decode_json_value, validate_json_value
from .semantic_revision import compute_semantic_revision

SEMANTIC_MAP_SCHEMA = "px.librarian-semantic-map/1.0"
MAX_QUERY = 512
MAX_MATCHES = 12
MAX_DESCRIPTION_RELATIONS = 12

# Words that appear across many entities' free-text fields and therefore carry no
# discriminating power. Matching only these must not produce a confident hit.
STOP_TERMS = frozenset(
    {
        "thing", "things", "stuff", "item", "items", "entry", "entries", "system",
        "value", "values", "data", "record", "records", "state", "status", "name",
        "type", "kind", "level", "mode", "list", "info", "information", "detail",
        "details", "general", "default", "other", "done", "run", "use", "get", "set",
    }
)
# A match scores confidently only when at least one matched term is not a stop term.
MIN_MATCH_SCORE = 2.0

# The three canonical roots. Absence of any one is a hard error: a partial map would
# silently mislead the librarian.
ROOTS = ("registry", "contracts", "knowledge/nsai")

# Registry files that define canonical entities (the ontology hub).
REGISTRY_ENTITY_SOURCES = {
    "registry/capability_map.json": "capability",
    "registry/models.json": "model",
    "registry/tools.json": "tool",
    "registry/integrations.json": "integration",
    "registry/knowledge_sources.json": "knowledge_source",
    "registry/agency_agent_registry.json": "agent",
    "registry/builders.json": "builder",
    "registry/project_stream_orchestrations.json": "orchestration",
    "registry/skill_catalog.toml": "skill",
}

#: Agency/registry domain prefixes that partition a flat source kind (e.g. 270
#: agency agents) into distinct compact-address namespaces. The prefix is real
#: source taxonomy taken from the entity id, not an invented bucket.
_DOMAIN_PREFIXES = (
    "academic", "design", "engineering", "finance", "marketing", "product",
    "operations", "research", "security", "sales", "support", "data", "legal",
    "media", "people", "quality", "education", "spatial", "specialized",
    "testing", "game-development", "project-management",
)


def _agency_domain(legacy_id: str) -> str | None:
    """Extract the real agency/registry domain prefix from an entity id."""
    text = str(legacy_id).casefold()
    for prefix in _DOMAIN_PREFIXES:
        if prefix in text:
            return prefix
    return None


#: Skill action family: the leading verb of a skill id is real source taxonomy.
#: Each family maps to a frozen-vocabulary ``object`` member so a flat catalog of
#: hundreds of skills partitions into namespaces that stay under the kind
#: dimension's capacity. An unmapped verb keeps the base family rather than being
#: forced into an invented bucket.
_SKILL_VERB_FAMILIES: dict[str, str] = {
    "acquire": "service", "install": "service", "connect": "service",
    "configure": "service", "automate": "service", "deploy": "service",
    "maintain": "service", "scale": "service", "handle": "service",
    "audit": "record", "analyze": "document", "inspect": "record",
    "diagnose": "record", "triage": "record", "verify": "record",
    "validate": "record", "benchmark": "record", "measure": "record",
    "trace": "record", "map": "document", "query": "document",
    "read": "document", "corpus": "document", "provenance": "record",
    "build": "construction", "implement": "construction", "forge": "construction",
    "repair": "construction", "harden": "construction", "optimize": "construction",
    "refactor": "construction", "generate": "construction", "author": "construction",
    "plan": "orchestration", "orchestrate": "orchestration", "schedule": "orchestration",
    "coordinate": "orchestration", "supervise": "orchestration", "gate": "policy",
    "admit": "policy", "permission": "policy", "quarantine": "policy",
    "isolate": "policy", "evolve": "agent", "adapt": "agent", "learn": "agent",
    "reason": "agent", "reasoning": "agent", "propose": "agent", "decide": "agent",
    "design": "document", "research": "document", "document": "document",
}


def _skill_action_family(legacy_id: str) -> str | None:
    """Map a skill id's leading action verb to a frozen object family."""
    tail = str(legacy_id).split(":")[-1]
    verb = tail.split("-")[0].casefold()
    return _SKILL_VERB_FAMILIES.get(verb)

# Derived graphs the ontology produces (read-only navigation aids).
REGISTRY_GRAPH_SOURCES = {
    "registry/graphs/capability_graph.json": "capability_graph",
    "registry/graphs/system_asset_graph.json": "system_asset_graph",
    "registry/graphs/dependency_effect_graph.json": "dependency_effect_graph",
    "registry/graphs/io_graph.json": "io_graph",
    "registry/graphs/project_stream_dependency_graph.json": "project_stream_graph",
}

#: Explicit mapping from a source-object kind onto the canonical entity kind
#: (``runtime.semantic_entity.ENTITY_KINDS``). Collapsing every entity onto a
#: single ``record`` kind both lost the real taxonomy and exhausted one compact
#: address namespace (``evidence.record.recording``). A source kind with no
#: entry here has no admitted canonical kind and stays an explicit ambiguity.
CANONICAL_ENTITY_KIND_BY_SOURCE_KIND = {
    "capability": "surface",
    "model": "surface",
    "tool": "surface",
    "integration": "surface",
    "knowledge_source": "artifact",
    "agent": "surface",
    "builder": "operation",
    "orchestration": "operation",
    "skill": "operation",
    "nsai_object": "artifact",
    "contract": "contract",
    "declaration": "declaration",
    "policy": "policy",
    "module": "module",
    "operation": "operation",
    "symbol": "symbol",
    "artifact": "artifact",
    "relation_kind": "relation_kind",
    "record": "record",
}


@dataclass(frozen=True, slots=True)
class Relation:
    relation: str
    target: str
    namespace: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {"relation": self.relation, "target": self.target, "namespace": self.namespace}


@dataclass(frozen=True, slots=True)
class Entity:
    entity_id: str
    kind: str
    namespace: str
    source_path: str
    object_type: str | None
    status: str
    terms: tuple[str, ...]
    contract: str | None
    relations: tuple[Relation, ...]
    canonical_entity_id: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "entity_id": self.entity_id,
            "canonical_entity_id": self.canonical_entity_id,
            "kind": self.kind,
            "namespace": self.namespace,
            "source_path": self.source_path,
            "object_type": self.object_type,
            "status": self.status,
            "terms": list(self.terms),
            "contract": self.contract,
            "relations": [r.as_mapping() for r in self.relations],
        }


@dataclass(frozen=True, slots=True)
class EntityMatch:
    entity: Entity
    score: float
    matched_terms: tuple[str, ...]

    def as_mapping(self) -> dict[str, object]:
        return {
            "entity": self.entity.as_mapping(),
            "score": round(self.score, 6),
            "matched_terms": list(self.matched_terms),
        }


@dataclass(frozen=True, slots=True)
class SemanticMap:
    schema_version: str
    entities: Mapping[str, Entity]
    by_namespace: Mapping[str, tuple[str, ...]]
    by_kind: Mapping[str, tuple[str, ...]]
    contracts: tuple[str, ...]
    graphs: Mapping[str, tuple[str, ...]]
    counts: Mapping[str, int]
    map_sha256: str
    _canonical_entity_records: tuple[EntityRecord, ...]
    _canonical_locator_records: tuple[LocatorRecord, ...]
    _canonical_locator_history_records: tuple[LocatorRecord, ...]
    _locator_snapshot: bytes
    _entity_snapshot: bytes
    _canonical_relation_records: tuple[RelationRecord, ...]
    _compact_by_entity: Mapping[str, CompactAddress]
    _compact_by_alias: Mapping[str, str]
    compact_table_sha256: str
    identity_ambiguities: Mapping[str, str]
    canonical_lookup: Mapping[str, str]
    _recorded_context: ContextGenerationVector
    _current_context: Callable[[], ContextGenerationVector]

    @property
    def canonical_entities(self):
        return {record.entity_id: record.as_mapping() for record in self._canonical_entity_records}

    @property
    def canonical_locators(self):
        return {record.entity_id: record.as_mapping() for record in self._canonical_locator_records}

    @property
    def canonical_relations(self):
        return {record.relation_id: record.as_mapping() for record in self._canonical_relation_records}

    @property
    def compact_addresses(self):
        return {entity_id: address.as_mapping(entity_id=entity_id)
                for entity_id, address in self._compact_by_entity.items()}

    def resolve_compact_reference(self, alias: str, *, table_sha256: str) -> Entity | None:
        self.assert_current()
        if not isinstance(table_sha256, str) or table_sha256 != self.compact_table_sha256:
            raise ValueError("compact table binding does not match the current generation")
        parsed = parse_alias(alias)
        entity_id = self._compact_by_alias.get(parsed.alias)
        return self._lookup(entity_id) if entity_id is not None else None

    def locator_snapshot_bytes(self) -> bytes:
        """Recoverable metadata for caller-owned persistence; no store activation."""
        self.assert_current()
        return self._locator_snapshot

    @property
    def entity_snapshot_bytes(self) -> bytes:
        """Canonical entity snapshot for caller-owned persistence.

        This is what makes accepted canonical identity durable. A caller
        persists this image and passes it back as ``entity_snapshot`` on the
        next ``load_semantic_map`` run. Without it the map re-derives every
        identity from current sources, which is correct but discards the
        accepted lifecycle recorded previously.
        """
        self.assert_current()
        return self._entity_snapshot

    def entity_snapshot_sha256(self) -> str:
        self.assert_current()
        return hashlib.sha256(self._entity_snapshot).hexdigest()

    def resolve_reference(self, reference: str, *, locator_kind: str = "file",
                          include_history: bool = False, table_sha256: str | None = None) -> tuple[Entity, ...]:
        """Resolve exact canonical/declared IDs, bound aliases or locator metadata.

        Preserve every canonical candidate. History is opt-in, metadata only;
        neither path similarity nor a raw projection ID creates an owner.
        """
        self.assert_current()
        if type(reference) is not str or not reference.strip() or len(reference) > 1024 or type(include_history) is not bool:
            raise ValueError("semantic reference must be bounded text with an explicit history flag")
        if type(locator_kind) is not str or locator_kind not in LOCATOR_KINDS:
            raise ValueError("semantic reference requires a known locator kind")
        if reference.startswith(ALIAS_PREFIX + ":"):
            entity = self.resolve_compact_reference(reference, table_sha256=table_sha256)
            return (entity,) if entity is not None else ()
        entity = self._lookup(reference)
        if entity is not None:
            canonical = self._lookup(entity.canonical_entity_id) if entity.canonical_entity_id else None
            return (canonical,) if canonical is not None else ()
        if reference.startswith(("pxe1:", "registry:", "nsai:", "graph:")):
            return ()
        LocatorReferencePolicy().validate(locator_kind, reference)
        records = self._canonical_locator_history_records if include_history else self._canonical_locator_records
        identifiers = sorted({record.entity_id for record in records
                              if record.locator_kind == locator_kind and record.reference == reference})
        return tuple(self._lookup(identifier) for identifier in identifiers if identifier in self.canonical_lookup)

    @property
    def generation_vector(self) -> dict:
        return self._recorded_context.as_mapping()

    def projection_status(self, *, policy: ProjectionReadPolicy | None = None):
        return evaluate_projection("px-archivist-map", self._recorded_context,
                                   self._current_context(), policy=policy)

    def assert_current(self):
        status = self.projection_status()
        if not status.serve_allowed:
            raise ValueError("Archivist map projection is blocked: " + ", ".join(status.reasons))

    def _lookup(self, entity_id: str) -> Entity | None:
        return self.entities.get(self.canonical_lookup.get(entity_id, entity_id))

    def get(self, entity_id: str) -> Entity | None:
        self.assert_current()
        if isinstance(entity_id, str) and entity_id.startswith(ALIAS_PREFIX + ":"):
            raise ValueError("compact aliases require an explicit table binding")
        return self._lookup(entity_id)


def _load(path: Path) -> object:
    reject_path_links(path)
    raw = read_bounded_bytes(path, max_bytes=8*1024**2)
    if path.suffix == ".toml":
        value = tomllib.loads(raw.decode("utf-8-sig"))
        validate_json_value(value, max_depth=64, max_nodes=200000)
        return value
    return decode_json_value(raw.removeprefix(b"\xef\xbb\xbf"), max_bytes=8*1024**2,
                             max_depth=64, max_nodes=200000)


def _contract_ids(contracts_dir: Path) -> tuple[str, ...]:
    """All contract schema ids, from flat schemas and namespace directories."""

    found: set[str] = set()
    walk = bounded_walk(contracts_dir, limits=WalkLimits(max_files=4096,
        max_depth=16, max_bytes=32*1024**2, max_entries=10000,
        max_directories=2048, max_duration_seconds=30))
    for entry in walk.files:
        if entry.relative.endswith(".schema.json"):
            found.add(entry.path.relative_to(contracts_dir.parent).as_posix())
    return tuple(sorted(found))


def _input_snapshot(root: Path) -> dict[str, str | None]:
    """Bounded current metadata images; never model/tool/skill bodies."""
    paths = set(_contract_ids(root / "contracts")) | set(REGISTRY_ENTITY_SOURCES) | set(REGISTRY_GRAPH_SOURCES)
    paths.update({"knowledge/nsai/index.json", "registry/dependency_authority.json",
                  "policies/rev1xx-validation.json"})
    locations = {"project:" + relative: root / relative for relative in paths}
    for name in ("librarian_semantic_map.py", "semantic_entity.py", "semantic_locator.py",
                 "context_generation.py", "projection_gate.py", "dependency_invalidation.py",
                 "semantic_revision.py", "generated_dependency.py", "json_io.py", "archive_io.py", "bounded_walk.py", "compact_address.py"):
        locations["engine:runtime/" + name] = Path(__file__).parent / name
    remaining = 64*1024**2
    result = {}
    for name, path in sorted(locations.items()):
        reject_path_links(path)
        if not path.exists():
            result[name] = None
            continue
        if not path.is_file() or remaining <= 0:
            raise ValueError("Archivist metadata input is not a bounded file")
        raw = read_bounded_bytes(path, max_bytes=min(8*1024**2, remaining))
        remaining -= len(raw)
        result[name] = hashlib.sha256(raw).hexdigest()
    return result


def _map_context(snapshot, semantic_revision, projection_revision):
    source_revision = hashlib.sha256(bounded_canonical_json_bytes(snapshot, max_bytes=2*1024**2)).hexdigest()
    revisions = {"snapshot:source": source_revision, "snapshot:semantics": semantic_revision,
                 "snapshot:projection": projection_revision,
                 "authority:dependency-owner": snapshot.get("project:registry/dependency_authority.json"),
                 "policy:current-owner": snapshot.get("project:policies/rev1xx-validation.json")}
    bindings = {"source_revision": ["snapshot:source"], "semantic_generation": ["snapshot:semantics"],
                "projection_generation": ["snapshot:projection"],
                "authority_revision": ["authority:dependency-owner"], "policy_revision": ["policy:current-owner"]}
    return context_vector_for_dependencies("pacify-x", "archivist-map-metadata", revisions, bindings,
        required_components=("source_revision", "semantic_generation", "projection_generation"))


def _contract_for(kind: str, namespace: str, contracts: tuple[str, ...]) -> str | None:
    """Best-match governing contract for a kind/namespace, deterministically."""

    candidates = {
        "capability": "contracts/capability-contract.schema.json",
        "model": "contracts/model-contract.schema.json",
        "tool": "contracts/tool-contract.schema.json",
        "integration": "contracts/integration-contract.schema.json",
        "agent": "contracts/agent_handoff_packet.schema.json",
        "knowledge_source": "contracts/knowledge-source.schema.json",
        "orchestration": "contracts/orchestration-contract.schema.json",
    }
    preferred = candidates.get(kind)
    if preferred and preferred in contracts:
        return preferred
    ns_contract = f"contracts/{namespace}"
    for contract in contracts:
        if contract.startswith(ns_contract + "/") or contract.startswith(ns_contract + "."):
            return contract
    return None


def _terms_from(value: object) -> tuple[str, ...]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, (list, tuple)):
        out.extend(str(item) for item in value if isinstance(item, (str, int, float)))
    elif isinstance(value, dict):
        out.extend(str(k) for k in value)
    return tuple(t.strip() for t in out if str(t).strip())[:64]


def _registry_entities(root: Path, contracts: tuple[str, ...]) -> dict[str, Entity]:
    entities: dict[str, Entity] = {}
    for relative, kind in REGISTRY_ENTITY_SOURCES.items():
        path = root / relative
        if not path.is_file():
            continue
        payload = _load(path)
        rows = payload if isinstance(payload, list) else None
        if rows is None and isinstance(payload, dict):
            for key in ("active_capabilities", "capabilities", "models", "tools", "integrations", "skills",
                        "knowledge_sources", "agents", "builders", "orchestrations", "entries"):
                if isinstance(payload.get(key), list):
                    rows = payload[key]
                    break
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            raw_id = (
                row.get("capability_id") or row.get("model_id") or row.get("tool_id")
                or row.get("integration_id") or row.get("source_id") or row.get("agent_id")
                or row.get("builder_id") or row.get("orchestration_id") or row.get("id")
            )
            if not raw_id:
                continue
            entity_id = f"registry:{kind}:{raw_id}"
            if entity_id in entities:
                raise ValueError(f"duplicate semantic entity: {entity_id}")
            terms: list[str] = [str(raw_id)]
            for key in ("name", "display_name", "title", "summary", "description",
                        "traits", "tags", "domains", "capabilities", "keywords", "aliases"):
                terms.extend(_terms_from(row.get(key)))
            entities[entity_id] = Entity(
                entity_id=entity_id,
                kind=kind,
                namespace="registry",
                source_path=relative,
                object_type=kind,
                status=str(row.get("status") or row.get("state") or "declared"),
                terms=tuple(dict.fromkeys(terms))[:64],
                contract=_contract_for(kind, "registry", contracts),
                relations=(),
            )
    return entities


def _nsai_entities(root: Path, contracts: tuple[str, ...]) -> dict[str, Entity]:
    index_path = root / "knowledge/nsai/index.json"
    if not index_path.is_file():
        return {}
    payload = _load(index_path)
    entities: dict[str, Entity] = {}
    for record in payload.get("records", []):
        if not isinstance(record, dict) or "object_id" not in record:
            continue
        object_id = str(record["object_id"])
        if object_id in entities:
            raise ValueError(f"duplicate semantic entity: {object_id}")
        namespace = str(record.get("namespace", "unknown"))
        relations = tuple(
            Relation(
                relation="related_to",
                target=str(target),
                namespace=str(target).split(":")[1] if ":" in str(target) else None,
            )
            for target in record.get("relationship_targets", []) or []
        )
        terms: list[str] = [object_id, str(record.get("object_type", ""))]
        for key in ("terms", "tags", "classes"):
            terms.extend(_terms_from(record.get(key)))
        entities[object_id] = Entity(
            entity_id=object_id,
            kind="nsai_object",
            namespace=namespace,
            source_path=f"knowledge/nsai/{record.get('path', '')}",
            object_type=str(record.get("object_type")) if record.get("object_type") else None,
            status=str(record.get("status", "unknown")),
            terms=tuple(dict.fromkeys(t for t in terms if t))[:64],
            contract=_contract_for("nsai_object", namespace, contracts),
            relations=relations,
        )
    return entities


def _graph_entities(root: Path) -> tuple[dict[str, Entity], dict[str, tuple[str, ...]]]:
    entities: dict[str, Entity] = {}
    edges: dict[str, list[str]] = {}
    for relative, kind in REGISTRY_GRAPH_SOURCES.items():
        path = root / relative
        if not path.is_file():
            continue
        payload = _load(path)
        nodes = payload.get("nodes", []) if isinstance(payload, dict) else []
        graph_edges = payload.get("edges", []) if isinstance(payload, dict) else []
        for node in nodes:
            if isinstance(node, str):
                node = {"id": node}
            if not isinstance(node, dict):
                raise ValueError(f"invalid semantic graph node in {relative}")
            node_id = node.get("node_id") or node.get("id")
            if not node_id:
                continue
            entity_id = f"graph:{kind}:{node_id}"
            if entity_id in entities:
                raise ValueError(f"duplicate semantic entity: {entity_id}")
            entities[entity_id] = Entity(
                entity_id=entity_id,
                kind="graph_node",
                namespace="registry",
                source_path=relative,
                object_type=str(node.get("asset_type") or node.get("kind") or "node"),
                status=str(node.get("status", "declared")),
                terms=tuple(dict.fromkeys(str(v) for v in node.values() if isinstance(v, (str, int)))),
                contract=None,
                relations=(),
            )
        for edge in graph_edges:
            if not isinstance(edge, dict):
                continue
            source = edge.get("source") or edge.get("from")
            target = edge.get("target") or edge.get("to")
            if not source or not target:
                continue
            edges.setdefault(f"graph:{kind}:{source}", []).append(
                f"{edge.get('relation', 'related_to')}|graph:{kind}:{target}"
            )
    return entities, {k: tuple(sorted(set(v))) for k, v in edges.items()}


def load_semantic_map(root: Path, *, locator_snapshot: bytes | None = None,
                      entity_snapshot: bytes | None = None) -> SemanticMap:
    """Build the unified librarian semantic map from the three canonical roots.

    ``entity_snapshot`` restores previously accepted canonical lifecycle. The
    recovered registry is an independent owner: identities still re-derive
    from the current sources, and only a recovered record whose derived
    identity and kind match what this run produced is carried forward. A
    recovered identity that no longer exists in current source, or whose kind
    changed, is discarded rather than resurrected, so a stale snapshot can
    never inject a phantom or silently retype an entity.
    """

    reject_path_links(root)
    root = root.resolve(strict=True)
    missing = [r for r in ROOTS if not (root / r).exists()]
    if missing:
        raise FileNotFoundError(f"semantic roots are missing: {missing}")

    input_snapshot = _input_snapshot(root)

    contracts = _contract_ids(root / "contracts")
    entities: dict[str, Entity] = {}
    for collection in (_registry_entities(root, contracts), _nsai_entities(root, contracts)):
        overlap = set(entities).intersection(collection)
        if overlap:
            raise ValueError(f"duplicate semantic entity: {sorted(overlap)}")
        entities.update(collection)
    graph_entities, graph_edges = _graph_entities(root)
    if set(entities).intersection(graph_entities):
        raise ValueError("duplicate semantic entity across graph and registry owners")

    # Fold graph adjacency into entity relations where the node is known.
    merged: dict[str, Entity] = {}
    for entity_id, entity in {**entities, **graph_entities}.items():
        adjacency = graph_edges.get(entity_id, ())
        relations = list(entity.relations)
        for entry in adjacency:
            relation, _, target = entry.partition("|")
            relations.append(Relation(relation=relation, target=target))
        merged[entity_id] = Entity(
            entity_id=entity.entity_id,
            kind=entity.kind,
            namespace=entity.namespace,
            source_path=entity.source_path,
            object_type=entity.object_type,
            status=entity.status,
            terms=entity.terms,
            contract=entity.contract,
            relations=tuple(relations),
        )

    # Admit logical identifiers through the shared identity owner. Legacy keys
    # remain compatibility aliases; path-shaped keys remain explicitly unresolved.
    # Existing asset status cannot promote these proposed semantic records.
    canonical = EntityRegistry()
    pending_locations: list[tuple[str, str]] = []
    ambiguities: dict[str, str] = {}
    lookup: dict[str, str] = {}
    for legacy_id, entity in tuple(merged.items()):
        if entity.kind == "graph_node":
            ambiguities[legacy_id] = (
                "Derived graph identity must be bound to an admitted source entity; "
                "a projection node ID alone is not an intrinsic identity"
            )
            continue
        try:
            canonical_kind = CANONICAL_ENTITY_KIND_BY_SOURCE_KIND.get(entity.kind)
            if canonical_kind is None:
                ambiguities[legacy_id] = (
                    "Source kind has no admitted canonical entity kind: " + str(entity.kind)
                )
                continue
            record = canonical.register(
                entity_kind=canonical_kind,
                identity_basis=identity_basis_for("declared_identifier", legacy_id),
                declared_by=entity.source_path,
                governing_contract=entity.contract,
                terms=tuple(dict.fromkeys(
                    token for term in entity.terms
                    for token in ((term,) if len(term) <= 300 else _tokens(term))
                    if token.strip() and len(token) <= 300
                ))[:256],
            )
        except SemanticEntityError as error:
            ambiguities[legacy_id] = str(error)
            continue
        if record.entity_id in lookup:
            raise ValueError(f"duplicate canonical semantic entity: {legacy_id}")
        lookup[record.entity_id] = legacy_id
        pending_locations.append((record.entity_id, entity.source_path))
        merged[legacy_id] = replace(entity, canonical_entity_id=record.entity_id)

    # Location is bound first, from current sources only. A locator owner
    # correctly refuses a retired entity, so recovered lifecycle must not be
    # applied before this loop or a restored retirement would orphan the
    # entity's own location.
    locators = (LocatorRegistry.from_snapshot_bytes(canonical, locator_snapshot)
                if locator_snapshot is not None else LocatorRegistry(canonical))
    for identifier, reference in pending_locations:
        locators.set_locator(entity_id=identifier, locator_kind="file", reference=reference)

    # Restore previously accepted lifecycle from an independently recovered
    # registry. The recovered registry is a separate owner: it can confirm an
    # acceptance, never introduce an identity this run did not derive. When no
    # explicit snapshot is supplied, fall back to the durable published registry
    # so accepted identity survives a restart through the normal path.
    if entity_snapshot is None:
        try:
            from .semantic_entity import load_published_registry
            published = load_published_registry(root)
        except (OSError, ValueError):
            published = None
        if published is not None:
            entity_snapshot = published.snapshot_bytes()
    if entity_snapshot is not None:
        # A recovered record without its own acceptance time would otherwise
        # invent one; stamp the recovery instant instead of guessing history.
        now_utc = datetime.now(timezone.utc).isoformat()
        recovered = EntityRegistry.from_snapshot_bytes(entity_snapshot)
        for prior in recovered.all_entities():
            current = canonical.get(prior.entity_id)
            if current is None or current.entity_kind != prior.entity_kind:
                continue
            if prior.lifecycle_state == "accepted" and current.lifecycle_state == "proposed":
                canonical.transition(prior.entity_id, "accepted", at_utc=prior.accepted_utc or now_utc)
            elif prior.lifecycle_state == "retired" and current.lifecycle_state != "retired":
                # Retirement is only reachable from accepted, so restore that
                # step first. Skipping it would leave an accepted_utc-less
                # retired record, which the snapshot contract rightly refuses.
                if current.lifecycle_state == "proposed":
                    canonical.transition(
                        prior.entity_id, "accepted",
                        at_utc=prior.accepted_utc or prior.retired_utc or now_utc,
                    )
                canonical.transition(
                    prior.entity_id, "retired",
                    at_utc=prior.retired_utc or now_utc,
                    reason=prior.retirement_reason or "recovered retired state",
                )
    # The W1 exit condition of zero duplicate accepted canonical IDs is now
    # checkable rather than assumed. This raises rather than merging.
    canonical.assert_unique_accepted()

    locator_snapshot_image = locators.snapshot_bytes()

    # These graph kinds have an explicit source-kind contract in graph_registry:
    # the first three contain capability IDs; system assets declare asset_type.
    # Bind only exact declared IDs, never titles, paths or similarity scores.
    capability_graphs = {"capability_graph", "dependency_effect_graph", "io_graph"}
    project_stream_kinds: dict[str, set[str]] = {}
    orchestration_path = root / "registry/project_stream_orchestrations.json"
    if orchestration_path.is_file():
        for row in _load(orchestration_path).get("orchestrations", []):
            if not isinstance(row, dict):
                raise ValueError("invalid project stream orchestration declaration")
            if row.get("orchestration_id"):
                project_stream_kinds.setdefault(str(row["orchestration_id"]), set()).add("orchestration")
            for field, source_kind in (("skills", "skill"), ("deferred_capabilities", "capability")):
                for reference in row.get(field, []):
                    project_stream_kinds.setdefault(str(reference), set()).add(source_kind)
    for legacy_id, entity in tuple(merged.items()):
        if entity.kind != "graph_node":
            continue
        _, graph_kind, raw_id = legacy_id.split(":", 2)
        source_kind = "capability" if graph_kind in capability_graphs else (
            {"knowledge": "knowledge_source"}.get(entity.object_type, entity.object_type)
            if graph_kind == "system_asset_graph" else None)
        if graph_kind == "project_stream_graph":
            declared_kinds = project_stream_kinds.get(raw_id, set())
            if len(declared_kinds) == 1:
                source_kind = next(iter(declared_kinds))
            elif len(declared_kinds) > 1:
                ambiguities[legacy_id] = "Projection node conflates declared source kinds: " + ", ".join(sorted(declared_kinds))
        source = merged.get(f"registry:{source_kind}:{raw_id}") if source_kind else None
        if source is not None and source.canonical_entity_id is not None:
            merged[legacy_id] = replace(entity, canonical_entity_id=source.canonical_entity_id)
            ambiguities.pop(legacy_id, None)

    canonical_records = {record.entity_id: record.as_mapping() for record in canonical.all_entities()}

    def _location_for(entity_id: str) -> dict:
        """Current locator, or the last known one for a retired entity.

        A retired entity has no current location by definition, but its
        tombstone must still carry the provenance of where it used to live.
        Resolving to None would drop that provenance and crash the map, so the
        latest historical observation is surfaced explicitly instead.
        """
        current_locator = locators.get(entity_id, "file")
        if current_locator is not None:
            return current_locator.as_mapping()
        history = locators.all_history()
        for record in reversed(history):
            if record.entity_id == entity_id:
                return record.as_mapping()
        raise ValueError(f"canonical entity has no locatable observation: {entity_id}")

    canonical_locations = {entity_id: _location_for(entity_id) for entity_id in lookup}
    relation_owner = RelationRegistry(canonical)
    location_relations = relation_owner.bind_locators(locators)
    allocator = CompactAddressAllocator()
    source_kind_by_entity = {
        entity_id: merged[lookup[entity_id]].kind for entity_id in lookup
    }
    domain_by_entity = {
        entity_id: (
            _agency_domain(lookup[entity_id])
            if source_kind_by_entity.get(entity_id) != "skill"
            else _skill_action_family(lookup[entity_id])
        )
        for entity_id in lookup
    }
    compact_by_entity = {
        entity_id: allocator.allocate(
            entity_id,
            concepts_for_entity_kind(
                canonical_records[entity_id].get("entity_kind", ""),
                lifecycle_state=canonical_records[entity_id].get(
                    "lifecycle_state", "accepted"
                ),
                source_kind=source_kind_by_entity.get(entity_id),
                domain=domain_by_entity.get(entity_id),
            ),
        )
        for entity_id in sorted(canonical_records)
    }
    compact_by_alias = {address.alias: entity_id for entity_id, address in compact_by_entity.items()}
    if len(compact_by_alias) != len(compact_by_entity):
        raise ValueError("compact semantic address collision")
    compact_rows = {entity_id: address.as_mapping(entity_id=entity_id)
                    for entity_id, address in compact_by_entity.items()}
    compact_table_sha = hashlib.sha256(bounded_canonical_json_bytes({
        "project_id": "pacify-x", "scope": "archivist-map-metadata", "entries": compact_rows,
    }, max_bytes=32*1024**2)).hexdigest()

    by_namespace: dict[str, list[str]] = {}
    by_kind: dict[str, list[str]] = {}
    for entity_id, entity in merged.items():
        by_namespace.setdefault(entity.namespace, []).append(entity_id)
        by_kind.setdefault(entity.kind, []).append(entity_id)

    body = {
        "schema_version": SEMANTIC_MAP_SCHEMA,
        "entities": [merged[key].as_mapping() for key in sorted(merged)],
        "contracts": list(contracts),
        "canonical_entities": canonical_records,
        "canonical_locators": canonical_locations,
        "locator_snapshot_sha256": hashlib.sha256(locator_snapshot_image).hexdigest(),
        "canonical_relations": [record.as_mapping() for record in location_relations],
        "compact_addresses": compact_rows,
        "compact_table_sha256": compact_table_sha,
        "identity_ambiguities": ambiguities,
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    semantic_generation = compute_semantic_revision(
        bounded_canonical_json_bytes(canonical_records, max_bytes=32*1024**2),
        artifact_type=".json").effective_revision
    if _input_snapshot(root) != input_snapshot:
        raise ValueError("Archivist metadata inputs changed during map capture")
    context = _map_context(input_snapshot, semantic_generation, digest)
    return SemanticMap(
        schema_version=SEMANTIC_MAP_SCHEMA,
        entities=MappingProxyType(merged),
        by_namespace=MappingProxyType({k: tuple(sorted(v)) for k, v in by_namespace.items()}),
        by_kind=MappingProxyType({k: tuple(sorted(v)) for k, v in by_kind.items()}),
        contracts=contracts,
        graphs=MappingProxyType({k: () for k in REGISTRY_GRAPH_SOURCES.values()}),
        counts=MappingProxyType({
            "entities": len(merged),
            "nsai_objects": sum(1 for e in merged.values() if e.kind == "nsai_object"),
            "registry_entities": sum(1 for e in merged.values() if e.namespace == "registry" and e.kind != "graph_node"),
            "graph_nodes": sum(1 for e in merged.values() if e.kind == "graph_node"),
            "relations": sum(len(e.relations) for e in merged.values()),
            "contracts": len(contracts),
            "canonical_entities": len(canonical_records),
            "identity_ambiguities": len(ambiguities),
            "compact_aliases": len(compact_by_entity),
            "canonical_relations": len(location_relations),
        }),
        map_sha256=digest,
        _canonical_entity_records=canonical.all_entities(),
        _canonical_locator_records=locators.all_locators(),
        _canonical_locator_history_records=locators.all_history(),
        _locator_snapshot=locator_snapshot_image,
        _entity_snapshot=canonical.snapshot_bytes(),
        _canonical_relation_records=location_relations,
        _compact_by_entity=MappingProxyType(compact_by_entity),
        _compact_by_alias=MappingProxyType(compact_by_alias),
        compact_table_sha256=compact_table_sha,
        identity_ambiguities=MappingProxyType(ambiguities),
        canonical_lookup=MappingProxyType(lookup),
        _recorded_context=context,
        _current_context=lambda: _map_context(_input_snapshot(root), semantic_generation, digest),
    )


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token.strip(".,?!:;'\"/\\()[]").casefold()
        for token in value.replace("-", " ").replace("_", " ").split()
        if len(token) >= 3
    )


def resolve_entity(map: SemanticMap, query: str) -> tuple[EntityMatch, ...]:
    """Rank entities against a natural-language or id query. Deterministic, no model."""
    map.assert_current()

    if type(query) is not str or not query.strip() or len(query.encode("utf-8")) > MAX_QUERY:
        raise ValueError("librarian query must be bounded nonempty text")
    tokens = set(_tokens(query))
    if not tokens:
        return ()

    scored: list[EntityMatch] = []
    for entity in map.entities.values():
        haystack = " ".join(entity.terms).casefold()
        matched = tuple(sorted(t for t in tokens if t in haystack))
        if not matched:
            continue
        specific = tuple(t for t in matched if t not in STOP_TERMS)
        # Exact id token is a much stronger signal than a generic term hit.
        id_tokens = set(_tokens(entity.entity_id))
        exact = len(tokens & id_tokens)
        score = len(matched) * 1.0 + exact * 3.0
        if entity.status in {"validated", "certified", "ready"}:
            score += 0.5
        if not specific and exact == 0:
            # Only stop-words matched: structurally real but not an answer.
            continue
        if score < MIN_MATCH_SCORE and exact == 0:
            continue
        scored.append(EntityMatch(entity=entity, score=score, matched_terms=specific or matched))

    scored.sort(key=lambda m: (-m.score, m.entity.entity_id))
    return tuple(scored[:MAX_MATCHES])


def traverse(map: SemanticMap, entity_id: str, relation: str | None = None) -> tuple[Relation, ...]:
    """Return typed neighbours of an entity, optionally filtered by relation."""

    entity = map.get(entity_id)
    if entity is None:
        return ()
    if relation is None:
        return entity.relations[:MAX_DESCRIPTION_RELATIONS]
    return tuple(r for r in entity.relations if r.relation == relation)[:MAX_DESCRIPTION_RELATIONS]


def describe_entity(map: SemanticMap, entity_id: str, *, locator_kind: str = "file",
                    include_history: bool = False, table_sha256: str | None = None) -> dict[str, object]:
    """A grounded, cited description built only from fields that exist in the map."""

    map.assert_current()
    if type(include_history) is not bool or type(locator_kind) is not str or locator_kind not in LOCATOR_KINDS:
        raise ValueError("semantic description requires an explicit history flag and known locator kind")
    entity = map._lookup(entity_id)
    if entity is None:
        candidates = map.resolve_reference(entity_id, locator_kind=locator_kind,
                                           include_history=include_history, table_sha256=table_sha256)
        if len(candidates) > 1:
            return {"found": False, "entity_id": entity_id, "resolution_status": "ambiguous",
                    "candidate_entity_ids": [candidate.canonical_entity_id for candidate in candidates],
                    "message": "Multiple canonical entities match this exact reference; owner selection is required."}
        entity = candidates[0] if candidates else None
    if entity is None:
        return {
            "found": False,
            "entity_id": entity_id,
            "message": "PX has no mapped entity with that id. It is unsupported, not inferred.",
        }
    neighbours = []
    for relation in entity.relations[:MAX_DESCRIPTION_RELATIONS]:
        target = map._lookup(relation.target)
        neighbours.append(
            {
                "relation": relation.relation,
                "target": relation.target,
                "target_known": target is not None,
                "target_source": target.source_path if target else None,
            }
        )
    map.assert_current()

    canonical_lifecycle = next((record.lifecycle_state for record in map._canonical_entity_records
                               if record.entity_id == entity.canonical_entity_id), None)
    # A retired entity has no CURRENT locator by definition, so _canonical_locator_records
    # (all_locators) excludes it. Reporting None here would drop the tombstone's
    # provenance at the exact point a consumer looks for it, so fall back to the
    # last known observation and mark it retired rather than presenting a stale
    # location as if the entity were still live.
    current_locator = next((record.as_mapping() for record in map._canonical_locator_records
                            if record.entity_id == entity.canonical_entity_id
                            and record.locator_kind == locator_kind), None)
    retired_locator = None
    if current_locator is None:
        for record in reversed(map._canonical_locator_history_records):
            if record.entity_id == entity.canonical_entity_id and record.locator_kind == locator_kind:
                retired_locator = {**record.as_mapping(), "current": False}
                break
    return {
        "found": True,
        "entity_id": entity.entity_id,
        "canonical_entity_id": entity.canonical_entity_id,
        "canonical_lifecycle": canonical_lifecycle,
        "canonical_locator": current_locator or retired_locator,
        "compact_reference": ({
            "alias": map._compact_by_entity[entity.canonical_entity_id].alias,
            "entity_id": entity.canonical_entity_id,
            "table_sha256": map.compact_table_sha256,
        } if entity.canonical_entity_id in map._compact_by_entity else None),
        "canonical_relations": [record.as_mapping() for record in map._canonical_relation_records
                                if record.source_entity_id == entity.canonical_entity_id][:MAX_DESCRIPTION_RELATIONS],
        "kind": entity.kind,
        "namespace": entity.namespace,
        "object_type": entity.object_type,
        "status": entity.status,
        "source_path": entity.source_path,
        "governing_contract": entity.contract,
        "terms": list(entity.terms[:24]),
        "neighbours": neighbours,
        "map_sha256": map.map_sha256,
        "context_generation_vector": map.generation_vector,
        "projection_status": map.projection_status().as_mapping(),
    }
