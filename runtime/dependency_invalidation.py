"""Revision-bound dependency graph and deterministic invalidation cones."""

from __future__ import annotations

from collections import defaultdict, deque
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "px.dependency-authority/1.0"
GRAPH_SCHEMA = "px.dependency-graph/1.0"
REQUIRED_KINDS = frozenset(
    {
        "agent",
        "formula",
        "knowledge",
        "model_profile",
        "projection",
        "release_evidence",
        "section",
        "skill",
        "source",
        "test",
        "workflow",
    }
)


def load_dependency_authority(root: Path) -> dict[str, Any]:
    payload = json.loads(
        (root.resolve() / "registry/dependency_authority.json").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(payload, dict):
        raise ValueError("dependency authority must be an object")
    return payload


def validate_dependency_authority(
    root: Path, authority: Mapping[str, object] | None = None
) -> dict[str, object]:
    root = root.resolve()
    try:
        payload = dict(authority) if authority is not None else load_dependency_authority(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return {"schema_version": SCHEMA_VERSION, "valid": False, "errors": [str(error)]}
    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    records = payload.get("node_kinds")
    if not isinstance(records, list):
        records = []
        errors.append("node_kinds must be a list")
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            errors.append(f"node_kinds[{index}] must be an object")
            continue
        kind = str(record.get("kind") or "")
        if not kind or kind in seen:
            errors.append(f"node_kinds[{index}] kind must be non-empty and unique")
        seen.add(kind)
        for field in ("canonical_owner", "invalidation_owner", "rebuild_gate"):
            value = str(record.get(field) or "")
            if not value:
                errors.append(f"{kind or index} missing {field}")
        for field in ("canonical_owner", "invalidation_owner"):
            value = str(record.get(field) or "")
            if value:
                path = (root / value).resolve()
                try:
                    path.relative_to(root)
                except ValueError:
                    errors.append(f"{kind}.{field} escapes the repository")
                else:
                    if not path.is_file():
                        errors.append(f"{kind}.{field} does not exist: {value}")
    missing = sorted(REQUIRED_KINDS - seen)
    unknown = sorted(seen - REQUIRED_KINDS)
    if missing:
        errors.append(f"missing dependency kinds: {missing}")
    if unknown:
        errors.append(f"unknown dependency kinds: {unknown}")
    if payload.get("node_kind_count") != len(records):
        errors.append("node_kind_count does not match node_kinds")
    if payload.get("cycle_policy") not in {"reject", "declared_components"}:
        errors.append("cycle_policy must be reject or declared_components")
    allowed = payload.get("allowed_cycle_components", [])
    if not isinstance(allowed, list) or any(
        not isinstance(item, list) or len(item) < 2 for item in allowed
    ):
        errors.append("allowed_cycle_components must contain node-ID lists")
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not errors,
        "node_kind_count": len(records),
        "errors": errors,
    }


def _cycles(nodes: set[str], edges: set[tuple[str, str]]) -> list[list[str]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for dependency, consumer in edges:
        adjacency[dependency].append(consumer)
    active: list[str] = []
    active_set: set[str] = set()
    visited: set[str] = set()
    found: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        visited.add(node)
        active.append(node)
        active_set.add(node)
        for consumer in sorted(adjacency.get(node, ())):
            if consumer not in visited:
                visit(consumer)
            elif consumer in active_set:
                start = active.index(consumer)
                found.add(tuple(sorted(set(active[start:]))))
        active.pop()
        active_set.remove(node)

    for node in sorted(nodes):
        if node not in visited:
            visit(node)
    return [list(item) for item in sorted(found)]


def build_dependency_graph(
    root: Path,
    nodes: Iterable[Mapping[str, object]],
    edges: Iterable[Mapping[str, object]],
    *,
    authority: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a validated graph whose edges point dependency -> consumer."""
    root = root.resolve()
    policy = dict(authority) if authority is not None else load_dependency_authority(root)
    authority_report = validate_dependency_authority(root, policy)
    if not authority_report["valid"]:
        raise ValueError("invalid dependency authority: " + "; ".join(authority_report["errors"]))
    errors: list[str] = []
    normalized_nodes: dict[str, dict[str, str]] = {}
    for item in nodes:
        node_id = str(item.get("node_id") or "")
        kind = str(item.get("kind") or "")
        revision = str(item.get("revision") or "")
        if not node_id or node_id in normalized_nodes:
            errors.append(f"node ID must be non-empty and unique: {node_id!r}")
            continue
        if kind not in REQUIRED_KINDS:
            errors.append(f"{node_id}: unknown dependency kind {kind!r}")
        if not revision:
            errors.append(f"{node_id}: revision is required")
        normalized_nodes[node_id] = {"node_id": node_id, "kind": kind, "revision": revision}
    normalized_edges: set[tuple[str, str]] = set()
    for item in edges:
        dependency = str(item.get("dependency") or "")
        consumer = str(item.get("consumer") or "")
        if dependency not in normalized_nodes or consumer not in normalized_nodes:
            errors.append(f"unknown dependency edge: {dependency!r} -> {consumer!r}")
            continue
        normalized_edges.add((dependency, consumer))
    cycles = _cycles(set(normalized_nodes), normalized_edges)
    allowed = {
        tuple(sorted(map(str, component)))
        for component in policy.get("allowed_cycle_components", [])
    }
    undeclared = [cycle for cycle in cycles if tuple(cycle) not in allowed]
    if undeclared:
        errors.append(f"undeclared dependency cycles: {undeclared}")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "schema_version": GRAPH_SCHEMA,
        "nodes": [normalized_nodes[key] for key in sorted(normalized_nodes)],
        "edges": [
            {"dependency": dependency, "consumer": consumer}
            for dependency, consumer in sorted(normalized_edges)
        ],
        "cycle_components": cycles,
    }


def compute_invalidation_cone(
    graph: Mapping[str, object],
    current_revisions: Mapping[str, object],
    *,
    authority: Mapping[str, object],
) -> dict[str, object]:
    """Propagate revision drift while retaining all historical node records."""
    nodes = {
        str(item["node_id"]): item
        for item in graph.get("nodes", [])
        if isinstance(item, Mapping) and item.get("node_id")
    }
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in graph.get("edges", []):
        if isinstance(edge, Mapping):
            adjacency[str(edge.get("dependency"))].add(str(edge.get("consumer")))
    unknown = sorted(set(map(str, current_revisions)) - set(nodes))
    if unknown:
        raise ValueError(f"current revisions contain unknown dependency nodes: {unknown}")
    seeds = sorted(
        node_id
        for node_id, revision in current_revisions.items()
        if str(revision) != str(nodes[str(node_id)].get("revision"))
    )
    depths = {node_id: 0 for node_id in seeds}
    queue = deque(seeds)
    while queue:
        node_id = queue.popleft()
        for consumer in sorted(adjacency.get(node_id, ())):
            if consumer not in depths:
                depths[consumer] = depths[node_id] + 1
                queue.append(consumer)
    gates = {
        str(record["kind"]): str(record["rebuild_gate"])
        for record in authority.get("node_kinds", [])
        if isinstance(record, Mapping)
    }
    stale = [
        {
            "node_id": node_id,
            "kind": str(nodes[node_id].get("kind")),
            "recorded_revision": str(nodes[node_id].get("revision")),
            "current_revision": (
                str(current_revisions[node_id]) if node_id in current_revisions else None
            ),
            "depth": depths[node_id],
            "reason": "revision_drift" if depths[node_id] == 0 else "dependency_invalidated",
            "required_rebuild_gate": gates.get(str(nodes[node_id].get("kind"))),
        }
        for node_id in sorted(depths, key=lambda value: (depths[value], value))
    ]
    return {
        "schema_version": "px.invalidation-cone/1.0",
        "valid": True,
        "seed_nodes": seeds,
        "direct_consumers": [item["node_id"] for item in stale if item["depth"] == 1],
        "transitive_consumers": [item["node_id"] for item in stale if item["depth"] > 1],
        "stale_nodes": stale,
        "historical_records_retained": True,
    }


def adapt_generated_dependency_graph(
    payload: Mapping[str, object],
    *,
    revisions: Mapping[str, object],
    default_kind: str = "source",
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Adapt generated ``from``/``to`` edges into universal graph inputs."""
    edges: list[dict[str, str]] = []
    node_ids: set[str] = set()
    for item in payload.get("edges", []):
        if not isinstance(item, Mapping):
            continue
        dependency = str(item.get("from") or "")
        consumer = str(item.get("to") or "")
        if dependency and consumer:
            node_ids.update((dependency, consumer))
            edges.append({"dependency": dependency, "consumer": consumer})
    nodes = [
        {
            "node_id": node_id,
            "kind": default_kind,
            "revision": str(revisions.get(node_id) or ""),
        }
        for node_id in sorted(node_ids)
    ]
    return nodes, edges
