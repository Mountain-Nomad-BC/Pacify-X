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
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

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
}

# Derived graphs the ontology produces (read-only navigation aids).
REGISTRY_GRAPH_SOURCES = {
    "registry/graphs/capability_graph.json": "capability_graph",
    "registry/graphs/system_asset_graph.json": "system_asset_graph",
    "registry/graphs/dependency_effect_graph.json": "dependency_effect_graph",
    "registry/graphs/io_graph.json": "io_graph",
    "registry/graphs/project_stream_dependency_graph.json": "project_stream_graph",
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

    def as_mapping(self) -> dict[str, object]:
        return {
            "entity_id": self.entity_id,
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

    def get(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _contract_ids(contracts_dir: Path) -> tuple[str, ...]:
    """All contract schema ids, from flat schemas and namespace directories."""

    found: set[str] = set()
    for path in contracts_dir.rglob("*.schema.json"):
        found.add(path.relative_to(contracts_dir.parent).as_posix())
    return tuple(sorted(found))


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
            for key in ("capabilities", "models", "tools", "integrations",
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
            if not isinstance(node, dict):
                continue
            node_id = node.get("node_id") or node.get("id")
            if not node_id:
                continue
            entity_id = f"graph:{kind}:{node_id}"
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
                f"{edge.get('relation', 'related_to')}|{target}"
            )
    return entities, {k: tuple(sorted(set(v))) for k, v in edges.items()}


def load_semantic_map(root: Path) -> SemanticMap:
    """Build the unified librarian semantic map from the three canonical roots."""

    root = root.resolve(strict=True)
    missing = [r for r in ROOTS if not (root / r).exists()]
    if missing:
        raise FileNotFoundError(f"semantic roots are missing: {missing}")

    contracts = _contract_ids(root / "contracts")
    entities: dict[str, Entity] = {}
    entities.update(_registry_entities(root, contracts))
    entities.update(_nsai_entities(root, contracts))
    graph_entities, graph_edges = _graph_entities(root)

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

    by_namespace: dict[str, list[str]] = {}
    by_kind: dict[str, list[str]] = {}
    for entity_id, entity in merged.items():
        by_namespace.setdefault(entity.namespace, []).append(entity_id)
        by_kind.setdefault(entity.kind, []).append(entity_id)

    body = {
        "schema_version": SEMANTIC_MAP_SCHEMA,
        "entity_ids": sorted(merged),
        "contracts": list(contracts),
    }
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SemanticMap(
        schema_version=SEMANTIC_MAP_SCHEMA,
        entities=merged,
        by_namespace={k: tuple(sorted(v)) for k, v in by_namespace.items()},
        by_kind={k: tuple(sorted(v)) for k, v in by_kind.items()},
        contracts=contracts,
        graphs={k: () for k in REGISTRY_GRAPH_SOURCES.values()},
        counts={
            "entities": len(merged),
            "nsai_objects": sum(1 for e in merged.values() if e.kind == "nsai_object"),
            "registry_entities": sum(1 for e in merged.values() if e.namespace == "registry" and e.kind != "graph_node"),
            "graph_nodes": sum(1 for e in merged.values() if e.kind == "graph_node"),
            "relations": sum(len(e.relations) for e in merged.values()),
            "contracts": len(contracts),
        },
        map_sha256=digest,
    )


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token.strip(".,?!:;'\"/\\()[]").casefold()
        for token in value.replace("-", " ").replace("_", " ").split()
        if len(token) >= 3
    )


def resolve_entity(map: SemanticMap, query: str) -> tuple[EntityMatch, ...]:
    """Rank entities against a natural-language or id query. Deterministic, no model."""

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


def describe_entity(map: SemanticMap, entity_id: str) -> dict[str, object]:
    """A grounded, cited description built only from fields that exist in the map."""

    entity = map.get(entity_id)
    if entity is None:
        return {
            "found": False,
            "entity_id": entity_id,
            "message": "PX has no mapped entity with that id. It is unsupported, not inferred.",
        }
    neighbours = []
    for relation in entity.relations[:MAX_DESCRIPTION_RELATIONS]:
        target = map.get(relation.target)
        neighbours.append(
            {
                "relation": relation.relation,
                "target": relation.target,
                "target_known": target is not None,
                "target_source": target.source_path if target else None,
            }
        )
    return {
        "found": True,
        "entity_id": entity.entity_id,
        "kind": entity.kind,
        "namespace": entity.namespace,
        "object_type": entity.object_type,
        "status": entity.status,
        "source_path": entity.source_path,
        "governing_contract": entity.contract,
        "terms": list(entity.terms[:24]),
        "neighbours": neighbours,
        "map_sha256": map.map_sha256,
    }