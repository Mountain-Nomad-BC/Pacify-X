"""Revision-bound dependency graph and deterministic invalidation cones."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable, Mapping

from .generated_dependency import (
    GRAPH_SCHEMA as GENERATED_GRAPH_SCHEMA,
    MAX_EDGES,
    MAX_NODES,
    dependency_identity,
    generated_dependency_graph,
    strongly_connected_components,
)
from .json_io import bounded_json_text, load_json_object
from .archive_io import portable_member_name, reject_path_links


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
    reject_path_links(root)
    path = root / "registry/dependency_authority.json"
    reject_path_links(path)
    return load_json_object(path, max_bytes=1024 * 1024)


def _validate_policy_shape(payload: object) -> None:
    bounded_json_text(payload, max_bytes=1024 * 1024)
    if type(payload) is not dict or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported dependency authority schema")
    required = {
        "schema_version",
        "node_kind_count",
        "cycle_policy",
        "allowed_cycle_components",
        "node_kinds",
    }
    if set(payload) != required:
        raise ValueError("dependency authority fields are incomplete or unknown")
    records = payload["node_kinds"]
    if type(records) is not list or len(records) != len(REQUIRED_KINDS):
        raise ValueError("dependency authority requires every registered node kind")
    seen = set()
    for record in records:
        if type(record) is not dict:
            raise ValueError("dependency kind record must be an object")
        for field in ("kind", "canonical_owner", "invalidation_owner", "rebuild_gate"):
            if field not in record:
                raise ValueError("missing " + field)
            dependency_identity(record[field])
        if set(record) != {
            "kind",
            "canonical_owner",
            "invalidation_owner",
            "rebuild_gate",
        }:
            raise ValueError("unknown dependency kind record field")
        kind = record["kind"]
        if kind not in REQUIRED_KINDS or kind in seen:
            raise ValueError("dependency kinds must be known and unique")
        seen.add(kind)
        for field in ("canonical_owner", "invalidation_owner"):
            portable_member_name(record[field], allow_directory=False)
    if type(payload["node_kind_count"]) is not int or payload["node_kind_count"] != len(
        records
    ):
        raise ValueError("node_kind_count does not match node_kinds")
    if type(payload["cycle_policy"]) is not str or payload["cycle_policy"] not in {
        "reject",
        "declared_components",
    }:
        raise ValueError("cycle_policy must be reject or declared_components")
    allowed = payload["allowed_cycle_components"]
    if type(allowed) is not list or len(allowed) > 1000:
        raise ValueError("allowed cycle components require a bounded list")
    components = set()
    count = 0
    for component in allowed:
        if type(component) is not list or not 2 <= len(component) <= MAX_NODES:
            raise ValueError("allowed cycle component must contain bounded node IDs")
        values = tuple(sorted(dependency_identity(value) for value in component))
        count += len(values)
        if len(set(values)) != len(values) or values in components or count > MAX_NODES:
            raise ValueError("allowed cycle identities must be bounded and unique")
        components.add(values)


def validate_dependency_authority(
    root: Path, authority: Mapping[str, object] | None = None
) -> dict[str, object]:
    try:
        reject_path_links(root)
        resolved = root.resolve(strict=True)
        payload = (
            authority if authority is not None else load_dependency_authority(root)
        )
        _validate_policy_shape(payload)
        for record in payload["node_kinds"]:
            for field in ("canonical_owner", "invalidation_owner"):
                path = resolved / record[field]
                reject_path_links(path)
                if not path.resolve().is_relative_to(resolved) or not path.is_file():
                    raise ValueError(
                        f"{record['kind']}.{field} does not exist within repository"
                    )
        return {
            "schema_version": SCHEMA_VERSION,
            "valid": True,
            "node_kind_count": len(payload["node_kinds"]),
            "errors": [],
        }
    except (OSError, TypeError, ValueError) as error:
        return {
            "schema_version": SCHEMA_VERSION,
            "valid": False,
            "errors": [str(error)],
        }


def _graph_inputs(nodes, edges):
    if isinstance(nodes, (str, bytes, Mapping)) or isinstance(
        edges, (str, bytes, Mapping)
    ):
        raise ValueError("dependency nodes and edges require record iterables")
    normalized = {}
    normalized_edges = set()
    input_bytes = 0
    try:
        node_iterator, edge_iterator = iter(nodes), iter(edges)
    except TypeError as error:
        raise ValueError("dependency nodes and edges must be iterable") from error

    def identity(value):
        nonlocal input_bytes
        value = dependency_identity(value)
        input_bytes += len(value.encode("utf-8"))
        if input_bytes > 32 * 1024 * 1024:
            raise ValueError("dependency graph identity byte budget exceeded")
        return value

    for count, item in enumerate(node_iterator, 1):
        if count > MAX_NODES:
            raise ValueError("dependency node budget exceeded")
        if type(item) is not dict or set(item) != {"node_id", "kind", "revision"}:
            raise ValueError("dependency node record is malformed")
        node_id, revision = identity(item["node_id"]), identity(item["revision"])
        kind = item["kind"]
        if node_id in normalized:
            raise ValueError("node ID must be non-empty and unique")
        if type(kind) is not str or kind not in REQUIRED_KINDS:
            raise ValueError("unknown dependency kind")
        normalized[node_id] = {"node_id": node_id, "kind": kind, "revision": revision}
    for count, item in enumerate(edge_iterator, 1):
        if count > MAX_EDGES:
            raise ValueError("dependency edge budget exceeded")
        if type(item) is not dict or set(item) != {"dependency", "consumer"}:
            raise ValueError("dependency edge record is malformed")
        dependency, consumer = identity(item["dependency"]), identity(item["consumer"])
        if dependency not in normalized or consumer not in normalized:
            raise ValueError(f"unknown dependency edge: {dependency!r} -> {consumer!r}")
        normalized_edges.add((dependency, consumer))
    return normalized, normalized_edges


def _cycles(nodes: set[str], edges: set[tuple[str, str]]) -> list[list[str]]:
    if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES:
        raise ValueError("dependency graph cycle input budget exceeded")
    components = strongly_connected_components(sorted(nodes), sorted(edges))
    return sorted(
        component
        for component in components
        if len(component) > 1 or (component[0], component[0]) in edges
    )


def _check_cycles(cycles, policy):
    allowed = (
        set()
        if policy["cycle_policy"] == "reject"
        else {
            tuple(sorted(component)) for component in policy["allowed_cycle_components"]
        }
    )
    undeclared = [cycle for cycle in cycles if tuple(cycle) not in allowed]
    if undeclared:
        raise ValueError(f"undeclared dependency cycles: {undeclared}")


def build_dependency_graph(
    root: Path,
    nodes: Iterable[Mapping[str, object]],
    edges: Iterable[Mapping[str, object]],
    *,
    authority: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build bounded typed graph inputs whose edges point dependency -> consumer."""
    policy = authority if authority is not None else load_dependency_authority(root)
    report = validate_dependency_authority(root, policy)
    if not report["valid"]:
        raise ValueError("invalid dependency authority: " + "; ".join(report["errors"]))
    normalized, normalized_edges = _graph_inputs(nodes, edges)
    cycles = _cycles(set(normalized), normalized_edges)
    _check_cycles(cycles, policy)
    result = {
        "schema_version": GRAPH_SCHEMA,
        "nodes": [normalized[key] for key in sorted(normalized)],
        "edges": [
            {"dependency": dependency, "consumer": consumer}
            for dependency, consumer in sorted(normalized_edges)
        ],
        "cycle_components": cycles,
    }
    bounded_json_text(result, max_bytes=32 * 1024 * 1024)
    return result


def compute_invalidation_cone(
    graph: Mapping[str, object],
    current_revisions: Mapping[str, object],
    *,
    authority: Mapping[str, object],
) -> dict[str, object]:
    """Propagate supplied revision drift; expose bindings not evaluated by this call."""
    bounded_json_text(graph, max_bytes=32 * 1024 * 1024)
    _validate_policy_shape(authority)
    if (
        type(graph) is not dict
        or graph.get("schema_version") != GRAPH_SCHEMA
        or set(graph) != {"schema_version", "nodes", "edges", "cycle_components"}
        or type(graph["nodes"]) is not list
        or type(graph["edges"]) is not list
    ):
        raise ValueError("unsupported or malformed dependency graph")
    nodes, edges = _graph_inputs(graph["nodes"], graph["edges"])
    cycles = _cycles(set(nodes), edges)
    _check_cycles(cycles, authority)
    if graph["cycle_components"] != cycles:
        raise ValueError("dependency graph cycle metadata is inconsistent")
    if not isinstance(current_revisions, Mapping) or len(current_revisions) > MAX_NODES:
        raise ValueError("current revisions require a bounded mapping")
    revisions = {}
    revision_bytes = 0
    for count, (node_id, revision) in enumerate(current_revisions.items(), 1):
        if count > MAX_NODES:
            raise ValueError("current revision count budget exceeded")
        node_id, revision = dependency_identity(node_id), dependency_identity(revision)
        revision_bytes += len(node_id.encode("utf-8")) + len(revision.encode("utf-8"))
        if revision_bytes > 32 * 1024 * 1024:
            raise ValueError("current revision byte budget exceeded")
        if node_id not in nodes or node_id in revisions:
            raise ValueError(
                "current revisions contain unknown or duplicate dependency nodes"
            )
        revisions[node_id] = revision
    seeds = sorted(
        node_id
        for node_id, revision in revisions.items()
        if revision != nodes[node_id]["revision"]
    )
    adjacency = defaultdict(list)
    for dependency, consumer in sorted(edges):
        adjacency[dependency].append(consumer)
    depths = {node_id: 0 for node_id in seeds}
    queue = deque(seeds)
    while queue:
        node_id = queue.popleft()
        for consumer in adjacency[node_id]:
            if consumer not in depths:
                depths[consumer] = depths[node_id] + 1
                queue.append(consumer)
    gates = {
        record["kind"]: record["rebuild_gate"] for record in authority["node_kinds"]
    }
    stale = [
        {
            "node_id": node_id,
            "kind": nodes[node_id]["kind"],
            "recorded_revision": nodes[node_id]["revision"],
            "current_revision": revisions.get(node_id),
            "depth": depths[node_id],
            "reason": "revision_drift"
            if depths[node_id] == 0
            else "dependency_invalidated",
            "required_rebuild_gate": gates[nodes[node_id]["kind"]],
        }
        for node_id in sorted(depths, key=lambda value: (depths[value], value))
    ]
    result = {
        "schema_version": "px.invalidation-cone/1.0",
        "valid": True,
        "seed_nodes": seeds,
        "direct_consumers": [item["node_id"] for item in stale if item["depth"] == 1],
        "transitive_consumers": [
            item["node_id"] for item in stale if item["depth"] > 1
        ],
        "stale_nodes": stale,
        "historical_records_retained": True,
        "revision_scope": "provided-bindings-only",
        "complete_revision_coverage": len(revisions) == len(nodes),
        "unevaluated_nodes": sorted(set(nodes) - set(revisions)),
    }
    bounded_json_text(result, max_bytes=32 * 1024 * 1024)
    return result


def adapt_generated_dependency_graph(
    payload: Mapping[str, object],
    *,
    revisions: Mapping[str, object],
    default_kind: str = "source",
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Adapt canonical source/target edges, or explicit legacy from/to input."""
    bounded_json_text(payload, max_bytes=16 * 1024 * 1024)
    if type(payload) is not dict or not isinstance(revisions, Mapping):
        raise ValueError("generated graph and revision bindings must be mappings")
    if type(default_kind) is not str or default_kind not in REQUIRED_KINDS:
        raise ValueError("unknown generated graph dependency kind")
    canonical = payload.get("schema_version") == GENERATED_GRAPH_SCHEMA
    if "schema_version" in payload and not canonical:
        raise ValueError("unsupported generated graph schema")
    if canonical and payload.get("valid") is not True:
        raise ValueError("generated graph is not valid")
    raw_nodes, raw_edges = payload.get("nodes", []), payload.get("edges")
    if (
        type(raw_nodes) is not list
        or len(raw_nodes) > MAX_NODES
        or type(raw_edges) is not list
        or len(raw_edges) > MAX_EDGES
    ):
        raise ValueError("generated graph nodes/edges require bounded lists")
    node_ids = [dependency_identity(node) for node in raw_nodes]
    if len(set(node_ids)) != len(node_ids):
        raise ValueError("duplicate generated graph node identity")
    declarations = {node: [] for node in node_ids}
    expected_fields = {"source", "target", "kind"} if canonical else {"from", "to"}
    for item in raw_edges:
        if type(item) is not dict or set(item) != expected_fields:
            raise ValueError("malformed or ambiguous generated graph edge")
        if canonical and item["kind"] != "input":
            raise ValueError("unsupported generated graph edge kind")
        dependency = dependency_identity(item["source" if canonical else "from"])
        consumer = dependency_identity(item["target" if canonical else "to"])
        if canonical and (
            dependency not in declarations or consumer not in declarations
        ):
            raise ValueError("generated edge references an undeclared node")
        declarations.setdefault(dependency, [])
        declarations.setdefault(consumer, []).append(dependency)
    normalized = generated_dependency_graph(declarations)
    if not normalized["valid"]:
        raise ValueError("generated dependency cycle")
    nodes = []
    revision_bytes = 0
    for node_id in normalized["nodes"]:
        revision = dependency_identity(revisions.get(node_id))
        revision_bytes += len(revision.encode("utf-8"))
        if revision_bytes > 16 * 1024 * 1024:
            raise ValueError("generated graph revision byte budget exceeded")
        nodes.append(
            {
                "node_id": node_id,
                "kind": default_kind,
                "revision": revision,
            }
        )
    edges = [
        {"dependency": item["source"], "consumer": item["target"]}
        for item in normalized["edges"]
    ]
    bounded_json_text({"nodes": nodes, "edges": edges}, max_bytes=32 * 1024 * 1024)
    return nodes, edges
