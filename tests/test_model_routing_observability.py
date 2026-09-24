from __future__ import annotations

import pytest

from runtime.model_routing_observability import (
    RouteOutcome,
    benchmark_route_outcomes,
    collapse_evidence,
    effective_route_count,
    feature_affinity,
    jensen_shannon_bits,
    normalized_entropy,
    route_transition_counts,
)


def outcome(fid: str, policy: str, primary: str, *, success: bool, domain: str = "coding", ranking=None, latency=10.0, cost=0.0, local=True, features=()):
    ranking = tuple(ranking or (primary, "backup" if primary != "backup" else "other"))
    return RouteOutcome(fid, domain, policy, ranking, primary, None, success, latency, cost, local, tuple(features))


def test_distribution_metrics_are_bounded_and_deterministic() -> None:
    assert normalized_entropy({"a": 1.0}) == 0.0
    assert normalized_entropy({"a": 1.0, "b": 1.0}) == 1.0
    assert effective_route_count({"a": 1.0, "b": 1.0}) == 2.0
    assert jensen_shannon_bits({"a": 1.0}, {"b": 1.0}) == 1.0
    with pytest.raises(ValueError, match="range"):
        normalized_entropy({"a": float("nan")})


def test_benchmark_receipt_binds_quality_drift_domain_floors_and_no_authority() -> None:
    old_policy, new_policy = "a" * 64, "b" * 64
    incumbent = (
        outcome("f1", old_policy, "m1", success=True, ranking=("m1", "m2")),
        outcome("f2", old_policy, "m1", success=False, ranking=("m1", "m2")),
    )
    candidate = (
        outcome("f1", new_policy, "m2", success=True, ranking=("m2", "m1"), latency=9),
        outcome("f2", new_policy, "m2", success=True, ranking=("m2", "m1"), latency=9),
    )
    receipt = benchmark_route_outcomes(
        incumbent, candidate, fixture_sha256="c" * 64, domain_floors={"coding": 0.9},
        materiality={"min_quality_delta": 0.1, "min_latency_improvement_ratio": 0.05, "min_remote_cost_reduction_ratio": 0.05, "min_local_completion_delta": 0.05},
    )
    assert receipt["quality_delta"] == 0.5
    assert receipt["candidate_domain_scores"]["coding"] == 1.0
    assert receipt["review_required"] is True  # route drift is review evidence, not silent mutation
    assert receipt["complexity_tax_passed"] is True
    assert receipt["authority_granted"] is False
    assert receipt["auto_promotion_allowed"] is False
    assert len(receipt["evidence_sha256"]) == 64


def test_domain_floor_regression_blocks_complexity_gate_even_if_aggregate_improves() -> None:
    a, b = "a" * 64, "b" * 64
    incumbent = (
        outcome("c", a, "m1", success=False, domain="coding"),
        outcome("h", a, "m1", success=False, domain="hvac"),
    )
    candidate = (
        outcome("c", b, "m2", success=True, domain="coding"),
        outcome("h", b, "m2", success=False, domain="hvac"),
    )
    receipt = benchmark_route_outcomes(
        incumbent, candidate, fixture_sha256="c" * 64,
        domain_floors={"coding": 0.8, "hvac": 0.8},
        materiality={"min_quality_delta": 0.1, "min_latency_improvement_ratio": 0.05, "min_remote_cost_reduction_ratio": 0.05, "min_local_completion_delta": 0.05},
    )
    assert "hvac" in receipt["failed_domain_floors"]
    assert receipt["complexity_tax_passed"] is False
    assert receipt["promotion_candidate"] is False


def test_matched_fixture_and_policy_identity_are_fail_closed() -> None:
    a, b = "a" * 64, "b" * 64
    with pytest.raises(ValueError, match="matched fixture"):
        benchmark_route_outcomes(
            (outcome("f1", a, "m1", success=True),),
            (outcome("f2", b, "m2", success=True),),
            fixture_sha256="c" * 64, domain_floors={},
            materiality={"min_quality_delta": 0.1, "min_latency_improvement_ratio": 0.05, "min_remote_cost_reduction_ratio": 0.05, "min_local_completion_delta": 0.05},
        )
    with pytest.raises(ValueError, match="distinct"):
        benchmark_route_outcomes(
            (outcome("f1", a, "m1", success=True),),
            (outcome("f1", a, "m2", success=True),),
            fixture_sha256="c" * 64, domain_floors={},
            materiality={"min_quality_delta": 0.1, "min_latency_improvement_ratio": 0.05, "min_remote_cost_reduction_ratio": 0.05, "min_local_completion_delta": 0.05},
        )


def test_feature_affinity_is_outcome_evidence_not_semantic_identity() -> None:
    policy = "a" * 64
    rows = (
        outcome("1", policy, "m1", success=True, features=("python",)),
        outcome("2", policy, "m1", success=False, features=("python",)),
    )
    affinity = feature_affinity(rows)
    assert affinity["python"]["m1"]["observations"] == 2
    assert affinity["python"]["m1"]["smoothed_success"] == 0.5


def test_collapse_and_transition_observability_are_evidence_only() -> None:
    policy = "a" * 64
    rows = tuple(outcome(str(i), policy, "m1", success=True) for i in range(9)) + (outcome("x", policy, "m2", success=True),)
    evidence = collapse_evidence(rows, max_top1_share=0.8, min_normalized_entropy=0.5)
    assert evidence["review_required"] is True
    assert "top1_concentration" in evidence["review_reasons"]
    assert evidence["authority_granted"] is False
    transitions = route_transition_counts((("librarian", "m1", "verifier"), ("librarian", "m1", "verifier")))
    assert transitions["librarian->m1"] == 2
    assert transitions["m1->verifier"] == 2


def test_missing_domain_floor_and_submaterial_gain_fail_closed() -> None:
    a, b = "a" * 64, "b" * 64
    incumbent = (
        outcome("c", a, "m1", success=True, domain="coding", latency=100.0, cost=1.0, local=False),
        outcome("h", a, "m1", success=True, domain="hvac", latency=100.0, cost=1.0, local=False),
    )
    candidate = (
        outcome("c", b, "m1", success=True, domain="coding", latency=99.9, cost=0.999, local=False),
        outcome("h", b, "m1", success=True, domain="hvac", latency=99.9, cost=0.999, local=False),
    )
    receipt = benchmark_route_outcomes(
        incumbent, candidate, fixture_sha256="f" * 64,
        domain_floors={"coding": 0.5},
        materiality={
            "min_quality_delta": 0.05,
            "min_latency_improvement_ratio": 0.05,
            "min_remote_cost_reduction_ratio": 0.05,
            "min_local_completion_delta": 0.05,
        },
    )
    assert "missing_floor:hvac" in receipt["failed_domain_floors"]
    assert receipt["complexity_tax_passed"] is False
    assert "no_material_gain" in receipt["review_reasons"]


def test_matched_fixture_domain_cannot_be_relabelled() -> None:
    with pytest.raises(ValueError, match="cannot change benchmark domain"):
        benchmark_route_outcomes(
            (outcome("f", "a" * 64, "m1", success=True, domain="coding"),),
            (outcome("f", "b" * 64, "m1", success=True, domain="hvac"),),
            fixture_sha256="c" * 64,
            domain_floors={"coding": 0.5, "hvac": 0.5},
            materiality={
                "min_quality_delta": 0.05,
                "min_latency_improvement_ratio": 0.05,
                "min_remote_cost_reduction_ratio": 0.05,
                "min_local_completion_delta": 0.05,
            },
        )
