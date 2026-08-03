from __future__ import annotations
from collections import defaultdict, deque
from typing import Any
from ..common.mathx import weighted_jaccard

RELATION_TYPES = {
    "depends_on", "requires", "produces", "improves", "conflicts_with",
    "extends", "replaces", "supersedes", "duplicates", "composes_with"
}

def _token_weights(capability: dict[str, Any]) -> dict[str, float]:
    tokens: dict[str, float] = {}
    for field, weight in (("tags", 1.0), ("inputs", 0.8), ("outputs", 0.9), ("mechanisms", 1.2)):
        for value in capability.get(field, []):
            tokens[str(value).lower()] = max(tokens.get(str(value).lower(), 0.0), weight)
    return tokens

def build(capabilities: list[dict[str, Any]], relations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    relations = list(relations or [])
    ids = {str(c["id"]) for c in capabilities}
    errors: list[str] = []
    for relation in relations:
        if relation.get("type") not in RELATION_TYPES:
            errors.append(f"unknown relation type: {relation.get('type')}")
        if relation.get("source") not in ids or relation.get("target") not in ids:
            errors.append(f"relation references unknown node: {relation}")
    duplicates = []
    for i, left in enumerate(capabilities):
        for right in capabilities[i + 1:]:
            similarity = weighted_jaccard(_token_weights(left), _token_weights(right))
            if similarity >= 0.72:
                duplicates.append({
                    "left": left["id"],
                    "right": right["id"],
                    "similarity": round(similarity, 6),
                    "disposition": "review_for_merge_or_alias",
                })
    indegree = defaultdict(int)
    outdegree = defaultdict(int)
    for relation in relations:
        indegree[relation["target"]] += 1
        outdegree[relation["source"]] += 1
    nodes = []
    for capability in capabilities:
        cid = str(capability["id"])
        nodes.append({
            **capability,
            "incoming_relations": indegree[cid],
            "outgoing_relations": outdegree[cid],
            "orphan": indegree[cid] == 0 and outdegree[cid] == 0,
        })
    return {
        "valid": not errors,
        "errors": errors,
        "nodes": nodes,
        "relations": relations,
        "duplicate_candidates": duplicates,
        "metrics": {
            "node_count": len(nodes),
            "relation_count": len(relations),
            "orphan_count": sum(1 for n in nodes if n["orphan"]),
            "duplicate_candidate_count": len(duplicates),
        },
    }

def dependency_health(genome: dict[str, Any]) -> dict[str, Any]:
    nodes = {n["id"]: n for n in genome.get("nodes", [])}
    graph = defaultdict(list)
    indegree = {node_id: 0 for node_id in nodes}
    missing = []
    for rel in genome.get("relations", []):
        if rel.get("type") not in {"depends_on", "requires"}:
            continue
        source, target = rel.get("source"), rel.get("target")
        if source not in nodes or target not in nodes:
            missing.append(rel)
            continue
        graph[target].append(source)
        indegree[source] += 1
    queue = deque(sorted([n for n, degree in indegree.items() if degree == 0]))
    visited = []
    while queue:
        node = queue.popleft()
        visited.append(node)
        for dependent in graph[node]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    cycles = sorted([n for n, degree in indegree.items() if degree > 0])
    critical = sorted(
        (
            {
                "id": node_id,
                "dependent_count": len(graph[node_id]),
                "certification": nodes[node_id].get("certification", "unknown"),
            }
            for node_id in nodes
            if graph[node_id]
        ),
        key=lambda x: (-x["dependent_count"], x["id"]),
    )
    return {
        "healthy": not missing and not cycles,
        "missing_dependency_relations": missing,
        "cycle_nodes": cycles,
        "topological_order": visited if not cycles else [],
        "critical_dependencies": critical,
    }

def mutation_plan(genome: dict[str, Any], desired_outputs: list[str]) -> dict[str, Any]:
    available = {str(x) for n in genome.get("nodes", []) for x in n.get("outputs", [])}
    missing = sorted(set(map(str, desired_outputs)) - available)
    proposals = [
        {
            "gap": gap,
            "proposal_id": f"capability-for-{gap.replace(' ', '-').lower()}",
            "status": "proposal_only",
            "required_validation": ["unit", "integration", "held_out_outcome", "rollback"],
        }
        for gap in missing
    ]
    return {"desired_outputs": desired_outputs, "missing_outputs": missing, "proposals": proposals}
