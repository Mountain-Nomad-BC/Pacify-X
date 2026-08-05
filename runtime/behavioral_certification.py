"""Observable behavioral certification and contained shadow comparison."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence


def _stable(value: object) -> str:
    rendered = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _valid_hash(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


def certify_behavioral_delta(
    cases: Sequence[Mapping[str, object]],
    *,
    baseline_sha256: str,
    candidate_sha256: str,
) -> dict[str, object]:
    """Certify observable decisions, including negative triggers and hard gates."""
    if not cases:
        raise ValueError("at least one behavioral case is required")
    if not _valid_hash(baseline_sha256) or not _valid_hash(candidate_sha256):
        raise ValueError(
            "baseline and candidate hashes must be lowercase SHA-256 values"
        )
    ids: set[str] = set()
    results: list[dict[str, object]] = []
    for case in cases:
        identifier = str(case.get("id", "")).strip()
        if not identifier or identifier in ids:
            raise ValueError("behavioral case IDs must be non-empty and unique")
        ids.add(identifier)
        baseline = case.get("baseline_decision")
        candidate = case.get("candidate_decision")
        expected = case.get("expected_candidate_decision")
        evidence_hash = case.get("evidence_sha256")
        kind = str(case.get("kind", "positive"))
        errors: list[str] = []
        if kind not in {"positive", "negative_trigger", "hard_gate"}:
            errors.append("unsupported case kind")
        if candidate != expected:
            errors.append(
                "candidate decision does not match expected observable decision"
            )
        if not _valid_hash(evidence_hash):
            errors.append("current evidence hash missing or invalid")
        if kind in {"negative_trigger", "hard_gate"} and candidate not in {
            "deny",
            "reject",
            "blocked",
            "quarantine",
            "require_approval",
        }:
            errors.append("negative or gate case did not fail closed")
        results.append(
            {
                "id": identifier,
                "kind": kind,
                "baseline_decision": baseline,
                "candidate_decision": candidate,
                "changed": baseline != candidate,
                "valid": not errors,
                "errors": errors,
                "evidence_sha256": evidence_hash,
            }
        )
    kinds = {str(result["kind"]) for result in results}
    suite_errors = []
    if "negative_trigger" not in kinds:
        suite_errors.append("negative-trigger coverage missing")
    if "hard_gate" not in kinds:
        suite_errors.append("hard-gate coverage missing")
    failures = [result for result in results if not result["valid"]]
    certified = not failures and not suite_errors
    certificate = {
        "schema_version": "1.0",
        "baseline_sha256": baseline_sha256,
        "candidate_sha256": candidate_sha256,
        "case_count": len(results),
        "changed_case_count": sum(bool(result["changed"]) for result in results),
        "results": results,
        "suite_errors": suite_errors,
        "private_reasoning_collected": False,
        "certified": certified,
    }
    certificate["certificate_sha256"] = _stable(certificate)
    return certificate


def compare_shadow_behavior(
    incumbent_result: object,
    candidate_result: object,
    *,
    candidate_effects: Sequence[str] = (),
    cutover_authorized: bool = False,
    kill_switch: bool = False,
) -> dict[str, object]:
    """Compare a candidate while always returning the incumbent result."""
    permitted_effects = {"read_local", "isolated_compute"}
    effects = tuple(sorted(set(map(str, candidate_effects))))
    contained = set(effects) <= permitted_effects
    candidate_observed = not kill_switch and contained
    mismatch = candidate_observed and candidate_result != incumbent_result
    eligible = candidate_observed and not mismatch and cutover_authorized
    comparison = {
        "returned_result": incumbent_result,
        "incumbent_sha256": _stable(incumbent_result),
        "candidate_sha256": _stable(candidate_result) if candidate_observed else None,
        "candidate_observed": candidate_observed,
        "candidate_effects": effects,
        "effects_contained": contained,
        "mismatch": mismatch,
        "kill_switch": kill_switch,
        "cutover_authorized": cutover_authorized,
        "cutover_eligible": eligible,
        "authority_granted": False,
        "errors": []
        if contained
        else ["candidate effects escaped the shadow boundary"],
    }
    comparison["comparison_sha256"] = _stable(comparison)
    return comparison
