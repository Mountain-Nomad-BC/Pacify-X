"""Diagnostic-only failure grouping and discriminating-test planning."""

from __future__ import annotations

import hashlib
import json
from typing import Iterable, Mapping


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def group_candidate_roots(
    failures: Iterable[Mapping[str, object]],
    *,
    expected_failure_ids: Iterable[str],
) -> dict[str, object]:
    """Cluster complete failure evidence; never claim or initiate a repair."""
    rows = tuple(dict(item) for item in failures)
    expected = set(map(str, expected_failure_ids))
    observed = [str(item.get("failure_id", "")) for item in rows]
    if not expected or set(observed) != expected or len(observed) != len(set(observed)):
        raise ValueError("complete unique failure denominator is required")
    groups: dict[tuple[str, ...], list[str]] = {}
    evidence_by_group: dict[tuple[str, ...], dict[str, tuple[str, ...]]] = {}
    for row in rows:
        evidence = tuple(sorted(set(map(str, row.get("evidence_refs", ())))))
        owners = tuple(sorted(set(map(str, row.get("owners", ())))))
        dependencies = tuple(sorted(set(map(str, row.get("dependencies", ())))))
        shared = tuple([*(f"e:{item}" for item in evidence), *(f"o:{item}" for item in owners), *(f"d:{item}" for item in dependencies)])
        # An empty signature stays isolated; similarity is never guessed.
        key = shared or (f"isolated:{row['failure_id']}",)
        groups.setdefault(key, []).append(str(row["failure_id"]))
        evidence_by_group[key] = {
            "evidence_refs": evidence,
            "owners": owners,
            "dependencies": dependencies,
        }
    candidates = []
    for index, key in enumerate(sorted(groups), 1):
        members = tuple(sorted(groups[key]))
        basis = evidence_by_group[key]
        payload = {"members": members, "basis": basis}
        candidates.append(
            {
                "candidate_id": f"candidate-root-{index:03d}-{_digest(payload)[:12]}",
                "failure_ids": members,
                "shared_basis": basis,
                "status": "candidate_unconfirmed",
                "authority_to_repair": False,
            }
        )
    payload = {
        "schema_version": "px.repair-root-groups/1.0",
        "failure_denominator": tuple(sorted(expected)),
        "candidate_groups": tuple(candidates),
        "diagnostic_only": True,
        "mutation_authorized": False,
    }
    return {**payload, "analysis_sha256": _digest(payload)}


def build_discriminating_test_plan(
    analysis: Mapping[str, object],
    *,
    confirmed_candidate_ids: Iterable[str] = (),
) -> dict[str, object]:
    confirmed = set(map(str, confirmed_candidate_ids))
    groups = tuple(analysis.get("candidate_groups", ()))
    known = {str(item.get("candidate_id")) for item in groups if isinstance(item, Mapping)}
    if confirmed - known:
        raise ValueError("confirmation references an unknown candidate root")
    tests = []
    for group in groups:
        candidate_id = str(group["candidate_id"])
        for dimension, values in group["shared_basis"].items():
            if values:
                tests.append(
                    {
                        "candidate_id": candidate_id,
                        "dimension": dimension,
                        "remove_or_substitute": tuple(values),
                        "oracle": "failure membership changes only when the proposed shared basis is causal",
                    }
                )
    payload = {
        "schema_version": "px.discriminating-test-plan/1.0",
        "analysis_sha256": analysis.get("analysis_sha256"),
        "tests": tuple(tests),
        "confirmed_candidate_ids": tuple(sorted(confirmed)),
        "repair_authorized": False,
        "execution_primitive": None,
    }
    return {**payload, "plan_sha256": _digest(payload)}
