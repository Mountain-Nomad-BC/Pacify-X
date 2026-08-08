from __future__ import annotations

import copy
from pathlib import Path

import pytest

from runtime.benchmark_operations import (
    BenchmarkFailureClass,
    build_custody_record,
    classify_failure,
    decide_benchmark_retry,
    admit_test_only_capability,
    evaluate_contamination,
    evaluate_preflight,
    freeze_execution_profile,
    matched_control_comparison,
    result_claim_labels,
    summarize_matched_results,
    verify_frozen_profile,
)
from runtime.contracts import validate_instance


ROOT = Path(__file__).resolve().parents[1]


def profile(*, enabled: bool = True, lane: str = "cold") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "run_id": "run-001-on" if enabled else "run-001-off",
        "lane": lane,
        "benchmark": {"name": "private-suite", "version": "1", "dataset_hash": "a" * 64},
        "agent": {"name": "codex", "version": "1"},
        "model": {"id": "model", "provider": "provider", "reasoning": "fixed"},
        "pacify_x": {"enabled": enabled, "version": "0.6.3", "sha": "b" * 40, "capabilities": ["assurance"] if enabled else []},
        "limits": {"seconds": 60, "credits": 10, "concurrency": 1},
        "permissions": {"network": False, "writes": False, "tools": []},
        "retry_policy": {"max_retries": 1, "retryable_classes": ["timeout", "tool_failure"]},
        "environment": {"container": "sha256:" + "c" * 64, "memory": "disabled", "cache": "empty"},
        "hardware_route": {"device": "cpu"},
        "adapter_hashes": {"harness": "d" * 64},
    }


def test_freeze_is_deterministic_and_contract_valid() -> None:
    frozen = freeze_execution_profile(profile())
    assert frozen == freeze_execution_profile(profile())
    assert verify_frozen_profile(frozen) == (True, ())
    validate_instance(frozen, ROOT / "contracts/benchmark-execution-profile.schema.json")


def test_treatment_mutation_invalidates_profile() -> None:
    frozen = freeze_execution_profile(profile())
    mutated = copy.deepcopy(frozen)
    mutated["limits"]["seconds"] = 600
    valid, reasons = verify_frozen_profile(mutated)
    assert not valid
    assert "frozen_hash_mismatch" in reasons


def test_preflight_fails_closed_and_never_scores_infrastructure() -> None:
    frozen = freeze_execution_profile(profile())
    decision = evaluate_preflight(
        frozen,
        {
            "harness_ready": True,
            "oracle_ready": False,
            "dependencies_ready": True,
            "permissions_ready": True,
            "evidence_sink_ready": True,
        },
    )
    assert not decision.scoreable
    assert decision.failed_checks == ("preflight_failed:oracle_ready",)


def test_retry_budget_and_treatment_are_frozen() -> None:
    frozen = freeze_execution_profile(profile())
    admitted = decide_benchmark_retry(
        frozen,
        completed_attempts=1,
        failure_class="timeout",
        observed_profile_hash=frozen["frozen_hash"],
    )
    exhausted = decide_benchmark_retry(
        frozen,
        completed_attempts=2,
        failure_class="timeout",
        observed_profile_hash=frozen["frozen_hash"],
    )
    changed = decide_benchmark_retry(
        frozen,
        completed_attempts=1,
        failure_class="timeout",
        observed_profile_hash="0" * 64,
    )
    assert admitted.allowed
    assert not exhausted.allowed and exhausted.reason == "retry_budget_exhausted"
    assert not changed.allowed and changed.reason == "treatment_changed"


def test_cold_lane_contamination_is_blocked() -> None:
    decision = evaluate_contamination(
        lane="cold",
        oracle_visibility="visible",
        treatment_visibility="visible",
        benchmark_informed_changes=["prompt tuned from case 4"],
    )
    assert not decision.allowed
    assert set(decision.reasons) == {
        "cold_oracle_visible",
        "cold_case_visible_to_treatment",
        "cold_treatment_benchmark_informed",
    }


def test_matched_on_off_control_ignores_only_activation_surface() -> None:
    on = freeze_execution_profile(profile(enabled=True))
    off = freeze_execution_profile(profile(enabled=False))
    assert matched_control_comparison(on, off)["matched"]
    changed = profile(enabled=False)
    changed["model"]["reasoning"] = "different"
    assert not matched_control_comparison(on, freeze_execution_profile(changed))["matched"]


def test_custody_is_content_addressed_without_mutating_sources(tmp_path: Path) -> None:
    source = tmp_path / "result.json"
    source.write_bytes(b'{"score": 1}')
    before = source.read_bytes()
    record = build_custody_record("run-1", {"result.json": source}, {"score": 1}, cold=True)
    assert source.read_bytes() == before
    assert record["sealed"] and len(record["custody_hash"]) == 64
    validate_instance(record, ROOT / "contracts/benchmark-custody.schema.json")


def test_failure_classification_preserves_contributors_and_grading_boundary() -> None:
    failure = classify_failure(
        "run-1",
        "task-1",
        {BenchmarkFailureClass.HARNESS_FAILURE: 0.9, BenchmarkFailureClass.UNKNOWN: 0.2},
        ["evidence:log"],
    )
    assert failure["classification"] == "harness_failure"
    assert failure["graded_failure"] is False
    validate_instance(failure, ROOT / "contracts/benchmark-failure.schema.json")


def test_invalid_profile_and_confidence_are_rejected() -> None:
    with pytest.raises(ValueError):
        freeze_execution_profile({"lane": "cold"})
    with pytest.raises(ValueError):
        classify_failure("run", "task", {"unknown": 1.1}, [])
    malformed = profile()
    malformed["pacify_x"] = "enabled"
    with pytest.raises(ValueError, match="must be objects"):
        freeze_execution_profile(malformed)


def test_cold_memory_and_cache_must_be_isolated() -> None:
    candidate = profile()
    candidate["environment"] = {"memory": "shared", "cache": "warm"}
    valid, reasons = verify_frozen_profile(freeze_execution_profile(candidate))
    assert not valid
    assert set(reasons) >= {"cold_memory_not_isolated", "cold_cache_not_isolated"}


def test_test_only_capability_requires_explicit_benchmark_context() -> None:
    assert admit_test_only_capability(
        execution_mode="normal", capability_scope="test_only"
    ) == (False, "test_only_capability_requires_benchmark_execution_mode")
    assert admit_test_only_capability(
        execution_mode="benchmark", capability_scope="test_only"
    )[0]


def test_matched_statistics_report_variance_cost_and_no_invented_significance() -> None:
    treatment = [
        {"task_id": "a", "passed": True, "quality": 1, "latency": 2, "cost": 3},
        {"task_id": "b", "passed": True, "quality": 0.8, "latency": 3, "cost": 4},
    ]
    control = [
        {"task_id": "a", "passed": True, "quality": 1, "latency": 2, "cost": 2},
        {"task_id": "b", "passed": False, "quality": 0, "latency": 4, "cost": 2},
    ]
    report = summarize_matched_results(treatment, control)
    assert report["absolute_pass_delta"] == 0.5
    assert report["treatment_only_passes"] == ["b"]
    assert report["metrics"]["cost"]["treatment"]["mean"] == 3.5
    assert report["infrastructure_errors"] == {"treatment": 0, "control": 0}
    assert report["significance_claimed"] is False


def test_matched_statistics_reject_unbalanced_trial_counts() -> None:
    with pytest.raises(ValueError, match="trial counts differ"):
        summarize_matched_results(
            [{"task_id": "a", "passed": True}, {"task_id": "a", "passed": True}],
            [{"task_id": "a", "passed": True}],
        )


def test_result_labels_fail_closed_and_never_overclaim_comparability() -> None:
    invalid = result_claim_labels(
        matched_control=True,
        custody_sealed=False,
        contamination_clear=True,
        external_environment_matched=True,
    )
    assert not invalid["valid"]
    unrelated = result_claim_labels(
        matched_control=True,
        custody_sealed=True,
        contamination_clear=True,
        external_environment_matched=False,
    )
    assert unrelated["external_comparability"] == "NOT_CAUSALLY_COMPARABLE"
