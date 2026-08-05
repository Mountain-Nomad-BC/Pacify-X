"""Health analysis and dependency-ordered planning for project memory graphs."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence


TEMPORAL_TYPES = frozenset({"observed_at", "valid_from", "valid_until", "supersedes"})


def _stable(value: object) -> str:
    rendered = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def plan_memory_graph_remediation(
    project_id: str,
    nodes: Sequence[Mapping[str, object]],
    dependencies: Sequence[Sequence[str]],
    *,
    mutation_approved: bool = False,
    spend_cap: float = 0.0,
) -> dict[str, object]:
    """Detect graph defects and order bounded repairs without applying them."""
    if not project_id.strip() or spend_cap < 0:
        raise ValueError("a project identity and non-negative spend cap are required")
    by_id: dict[str, Mapping[str, object]] = {}
    findings: list[dict[str, object]] = []
    for node in nodes:
        node_id = str(node.get("id", "")).strip()
        if not node_id or node_id in by_id:
            raise ValueError("memory node IDs must be non-empty and unique")
        by_id[node_id] = node
        if node.get("project_id") != project_id:
            findings.append(
                {"code": "cross_project_node", "node_id": node_id, "cost": 1.0}
            )
        citations = tuple(map(str, node.get("citations", ())))
        if not citations:
            findings.append(
                {"code": "citation_missing", "node_id": node_id, "cost": 0.5}
            )
        temporal = node.get("temporal_claims", ())
        for claim in temporal if isinstance(temporal, Sequence) else ():
            if (
                not isinstance(claim, Mapping)
                or claim.get("type") not in TEMPORAL_TYPES
                or not claim.get("value")
            ):
                findings.append(
                    {"code": "invalid_temporal_claim", "node_id": node_id, "cost": 0.5}
                )

    adjacency = {node_id: set() for node_id in by_id}
    indegree = {node_id: 0 for node_id in by_id}
    for edge in dependencies:
        if len(edge) != 2:
            raise ValueError("dependencies must contain pairs")
        dependency, consumer = map(str, edge)
        if dependency not in by_id or consumer not in by_id:
            findings.append(
                {"code": "dangling_dependency", "node_id": consumer, "cost": 0.25}
            )
            continue
        if consumer not in adjacency[dependency]:
            adjacency[dependency].add(consumer)
            indegree[consumer] += 1
    queue = sorted(node_id for node_id, count in indegree.items() if count == 0)
    ordered: list[str] = []
    while queue:
        node_id = queue.pop(0)
        ordered.append(node_id)
        for consumer in sorted(adjacency[node_id]):
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                queue.append(consumer)
                queue.sort()
    cyclic = sorted(set(by_id) - set(ordered))
    for node_id in cyclic:
        findings.append({"code": "dependency_cycle", "node_id": node_id, "cost": 1.0})

    finding_rank = {
        "dependency_cycle": 0,
        "dangling_dependency": 1,
        "cross_project_node": 2,
        "invalid_temporal_claim": 3,
        "citation_missing": 4,
    }
    findings.sort(
        key=lambda item: (finding_rank[str(item["code"])], str(item["node_id"]))
    )
    steps = []
    spent = 0.0
    for index, finding in enumerate(findings, 1):
        cost = float(finding["cost"])
        within_budget = spent + cost <= spend_cap
        if within_budget:
            spent += cost
        steps.append(
            {
                "order": index,
                "finding": finding,
                "within_spend_cap": within_budget,
                "mutation_approved": mutation_approved,
                "apply": within_budget and mutation_approved,
                "post_step_verification": "recompute graph health and evidence hashes",
            }
        )
    result = {
        "valid": not findings,
        "project_id": project_id,
        "node_count": len(by_id),
        "findings": findings,
        "dependency_order": ordered,
        "steps": steps,
        "spend_cap": spend_cap,
        "planned_spend": spent,
        "mutation_approved": mutation_approved,
        "mutated": False,
        "authority_granted": False,
    }
    result["plan_sha256"] = _stable(result)
    return result
