from __future__ import annotations

from runtime.behavioral_assurance import (
    Control,
    FailureSignals,
    assurance_score,
    attribute_failure,
    cluster_coverage_frontier,
    conservative_near_duplicate,
    prioritize_improvement,
    query_hash,
    run_behavioral_probe,
    validate_evaluation_lineage,
)


def test_discriminating_positive_and_negative_controls_pass() -> None:
    controls = (
        Control("known", "positive", "known", True),
        Control("unknown", "negative", "unknown", False),
    )
    result = run_behavioral_probe(controls, lambda value: value == "known", lambda a, b: a == b)
    assert result.passed and result.discriminating


def test_http_200_or_constant_output_cannot_claim_component_health() -> None:
    controls = (
        Control("known", "positive", "known", "ok"),
        Control("unknown", "negative", "unknown", "refuse"),
    )
    result = run_behavioral_probe(controls, lambda _: "ok", lambda a, b: a == b)
    assert not result.passed
    assert "constant_output_not_discriminating" in result.reasons
    assert "control_failed:unknown" in result.reasons


def test_probe_requires_both_control_classes_and_sanitizes_errors() -> None:
    result = run_behavioral_probe(
        [Control("one", "positive", "x", "y")],
        lambda _: (_ for _ in ()).throw(RuntimeError("secret detail")),
        lambda a, b: a == b,
    )
    assert not result.passed and result.degraded
    assert result.controls[0].error_type == "RuntimeError"
    assert "secret detail" not in repr(result)


def test_probe_rejects_duplicate_controls_and_invalid_latency() -> None:
    controls = [
        Control("same", "positive", "a", "a"),
        Control("same", "negative", "b", "b"),
    ]
    result = run_behavioral_probe(controls, lambda value: value, lambda a, b: a == b)
    assert not result.passed and "duplicate_control_id" in result.reasons
    try:
        run_behavioral_probe(controls, lambda value: value, lambda a, b: a == b, max_latency_ms=-1)
    except ValueError as error:
        assert "non-negative" in str(error)
    else:  # pragma: no cover
        raise AssertionError("negative latency was accepted")


def test_failure_attribution_is_multi_cause_and_non_mutating() -> None:
    result = attribute_failure(
        FailureSignals(
            dependency_healthy=False,
            tool_failed=True,
            retrieved_count=0,
            deep_search_has_support=True,
        )
    )
    assert result["primary"] == "tool_failure"
    assert len(result["contributors"]) == 3
    assert result["mutation_allowed"] is False


def test_generated_judge_cannot_self_certify() -> None:
    valid, reasons = validate_evaluation_lineage(
        {
            "case_class": "generated_candidate",
            "origin": "model_generated",
            "oracle_authority": "model_provisional",
            "treatment_visibility": "visible",
            "oracle_visibility": "visible",
            "source_refs": ["evidence:prompt"],
        }
    )
    assert not valid
    assert reasons == ("generated_case_cannot_self_certify",)


def test_holdout_visibility_is_protected() -> None:
    valid, reasons = validate_evaluation_lineage(
        {
            "case_class": "holdout",
            "origin": "human",
            "oracle_authority": "human_verified",
            "treatment_visibility": "visible",
            "oracle_visibility": "visible",
            "source_refs": ["evidence:review"],
        }
    )
    assert not valid
    assert set(reasons) == {"protected_case_visible_to_treatment", "protected_oracle_visible_before_run"}


def test_coverage_frontier_is_sanitized_candidate_signal_not_oracle() -> None:
    rows = cluster_coverage_frontier(
        ["How do I recover a failed build?", "HOW do I recover a failed build!", "short"]
    )
    assert len(rows) == 1 and rows[0]["demand_count"] == 2
    assert rows[0]["candidate_only"] and not rows[0]["oracle_known"]
    assert rows[0]["query_sha256"] == query_hash(rows[0]["normalized"])


def test_near_duplicate_is_conservative() -> None:
    assert conservative_near_duplicate("recover failed build", "recover failed builds")
    assert not conservative_near_duplicate("recover build", "delete production database")


def test_improvement_priority_never_authorizes_mutation() -> None:
    result = prioritize_improvement(
        failure_severity=0.9,
        demand=8,
        confidence=0.8,
        regression=True,
        safety_critical=True,
        risk_of_change=0.2,
    )
    assert result["priority"] > 70
    assert result["admission_required"] is True
    assert result["mutation_allowed"] is False


def test_assurance_average_cannot_mask_a_failed_axis() -> None:
    result = assurance_score(
        {
            "behavior": 1.0,
            "evaluator_calibration": 1.0,
            "evidence_integrity": 1.0,
            "coverage": 0.4,
            "regression": 1.0,
            "operations": 1.0,
        }
    )
    assert result["score"] > 0.8
    assert not result["admissible"]
    assert result["below_threshold"] == ("coverage",)
