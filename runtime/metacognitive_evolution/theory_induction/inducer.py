from __future__ import annotations
from collections import defaultdict
from itertools import combinations
from typing import Any


def _signature(record: dict[str, Any]) -> set[str]:
    fields = (
        "mechanisms",
        "formulas",
        "inputs",
        "outputs",
        "failure_modes",
        "invariants",
    )
    return {
        str(item).strip().lower()
        for field in fields
        for item in record.get(field, [])
        if str(item).strip()
    }


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return 0.0 if not union else len(left & right) / len(union)


def induce(records: list[dict[str, Any]], threshold: float = 0.45) -> dict[str, Any]:
    adjacency = defaultdict(set)
    similarities = []
    for left, right in combinations(records, 2):
        score = jaccard(_signature(left), _signature(right))
        similarities.append(
            {"left": left["id"], "right": right["id"], "similarity": round(score, 6)}
        )
        if score >= threshold:
            adjacency[left["id"]].add(right["id"])
            adjacency[right["id"]].add(left["id"])
    by_id = {r["id"]: r for r in records}
    visited = set()
    clusters = []
    for record_id in sorted(by_id):
        if record_id in visited:
            continue
        stack = [record_id]
        members = []
        visited.add(record_id)
        while stack:
            current = stack.pop()
            members.append(current)
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        if len(members) >= 2:
            common = set.intersection(*[_signature(by_id[m]) for m in members])
            cluster_id = "meta-" + "-".join(sorted(members)[:2])
            clusters.append(
                {
                    "cluster_id": cluster_id,
                    "members": sorted(members),
                    "shared_mechanisms": sorted(common),
                    "proposal_status": "candidate",
                    "required_evidence": [
                        "distinctness_from_members",
                        "held_out_generalization",
                        "failure_boundary",
                        "operational_value",
                    ],
                }
            )
    return {
        "threshold": threshold,
        "clusters": clusters,
        "pairwise_similarities": sorted(
            similarities, key=lambda x: (-x["similarity"], x["left"], x["right"])
        ),
        "proposal_count": len(clusters),
        "warning": "Clusters are hypotheses, not automatically admitted theories.",
    }


def validate_proposal(
    proposal: dict[str, Any], held_out_cases: list[dict[str, Any]]
) -> dict[str, Any]:
    passed = sum(1 for case in held_out_cases if bool(case.get("passed")))
    total = len(held_out_cases)
    rate = passed / total if total else 0.0
    minimum = float(proposal.get("minimum_held_out_pass_rate", 0.8))
    return {
        "proposal_id": proposal.get("proposal_id"),
        "held_out_cases": total,
        "held_out_pass_rate": rate,
        "distinctness_evidence_present": bool(proposal.get("distinctness_evidence")),
        "admit": total > 0
        and rate >= minimum
        and bool(proposal.get("distinctness_evidence")),
    }
