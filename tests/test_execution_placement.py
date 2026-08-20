from pathlib import Path

import pytest

from runtime.execution_placement import (
    decide_observed_placement,
    decide_placement,
    observe_workload,
    observed_promotion_gate,
    production_promotion_gate,
    promotion_gate,
    publish_placement_artifact,
    reusable_pattern_gate,
)
from runtime.work_admission import RuntimeWorkPlane


H = "a" * 64


def candidate(identifier, kind, score, *, current=False, boundary=.02, gates=True):
    return {"id": identifier, "class": kind, "keep_current": current, "scores": {"correctness": score, "latency": score, "throughput": score, "operability": score, "portability": score, "cost": score, "maintainability": score, "reversibility": score}, "boundary_costs": {"serialization": boundary, "network": boundary}, "gates": {"compatible": gates, "correctness": gates, "rollback_ready": gates, "baseline_available": gates}}


def test_keep_current_is_mandatory_and_small_gains_do_not_force_migration():
    decision = decide_placement(mode="language_runtime", baseline_sha256=H, candidates=[candidate("current", "host_language", .75, current=True), candidate("worker", "compiled_worker", .78)])
    assert decision["selected_candidate"] == "current"
    assert decision["recommendation"] == "keep_current"
    assert not decision["migration_authorized"]


def test_boundary_cost_and_hard_gates_are_in_total_system_decision():
    decision = decide_placement(mode="deployment_platform", baseline_sha256=H, candidates=[candidate("current", "local_process", .5, current=True), candidate("fast-but-boundary-heavy", "serverless_container", .95, boundary=.6), candidate("incompatible", "container", 1, boundary=0, gates=False)])
    assert decision["selected_candidate"] == "current"
    assert next(row for row in decision["candidates"] if row["id"] == "incompatible")["eligible"] is False


def test_bounded_candidate_can_advance_but_not_self_authorize_production():
    decision = decide_placement(mode="database_storage", baseline_sha256=H, candidates=[candidate("current", "relational", .5, current=True), candidate("sidecar", "search_index", .9)])
    assert decision["selected_candidate"] == "sidecar"
    assert decision["promotion_tier"] == 1
    gate = promotion_gate(decision, after_benchmark_sha256=H, rollback_test_sha256=H, boundary_validation_sha256=H, correctness_passed=True, improvement_passed=True, rollback_passed=True, partial_units=["search-projection"])
    assert gate["passed"] and gate["promotion_tier"] == 3
    assert not gate["production_authorized"]


def test_missing_rollback_or_invalid_hash_blocks_promotion():
    decision = decide_placement(mode="language_runtime", baseline_sha256=H, candidates=[candidate("current", "host_language", .5, current=True), candidate("ffi", "ffi_extension", .9)])
    gate = promotion_gate(decision, after_benchmark_sha256=H, rollback_test_sha256="bad", boundary_validation_sha256=H, correctness_passed=True, improvement_passed=True, rollback_passed=False)
    assert not gate["passed"]
    assert gate["rollback_candidate"] == "current"


def test_candidate_classes_do_not_bleed_between_modes():
    try:
        decide_placement(mode="database_storage", baseline_sha256=H, candidates=[candidate("current", "relational", .5, current=True), candidate("wrong", "serverless_function", .9)])
    except ValueError as error:
        assert "classes" in str(error)
    else:
        raise AssertionError("cross-mode candidate class was accepted")


def test_observed_workload_reaches_tier_five_without_scorer_authority(tmp_path):
    scheduler = RuntimeWorkPlane(tmp_path).snapshot()
    observation = observe_workload(
        workload_id="index-segment",
        workload_kind="text_analysis",
        current_placement="python-cpu",
        source_sha256=H,
        scheduler_snapshot=scheduler,
        before_benchmark={"sealed": True, "custody_hash": H},
        boundary_contract_sha256=H,
        rollback_artifact_sha256=H,
        hardware_route={
            "selected_device": "cpu",
            "actual_device": "cpu",
            "fallback": False,
            "routing_reason": "no admitted CUDA executor",
            "correctness_passed": True,
        },
    )
    decision = decide_observed_placement(
        observation=observation,
        mode="language_runtime",
        candidates=[
            candidate("current", "host_language", .5, current=True),
            candidate("worker", "compiled_worker", .9),
        ],
    )
    assert decision["observed_workload"] is True
    assert decision["migration_authorized"] is False
    tier3 = observed_promotion_gate(
        decision,
        after_benchmark={"sealed": True, "custody_hash": H},
        matched_benchmark={"sealed": True, "custody_hash": H},
        rollback_test_sha256=H,
        boundary_validation_sha256=H,
        correctness_passed=True,
        improvement_passed=True,
        rollback_passed=True,
        partial_units=["index-segment"],
    )
    tier4 = production_promotion_gate(
        tier3,
        production_approval_sha256=H,
        production_validation_sha256=H,
        monitoring_artifact_sha256=H,
        rollback_artifact_sha256=H,
        production_approved=True,
    )
    tier5 = reusable_pattern_gate(
        tier4,
        reuse_evidence_sha256=[H, "b" * 64, "c" * 64],
        successful_reuses=3,
        regressions=0,
        minimum_reuses=3,
        reusable_pattern_sha256=H,
        rollback_artifact_sha256=H,
    )
    assert tier3["promotion_tier"] == 3
    assert tier4["promotion_tier"] == 4 and tier4["production_authorized"]
    assert tier5["promotion_tier"] == 5 and tier5["reusable_pattern_candidate"]
    assert tier5["canonical"] is False and tier5["learning_promotion_required"]
    published = publish_placement_artifact(tmp_path, tier5)
    assert (tmp_path / published["path"]).is_file()
    assert published["runtime_admission"]["decision"] == "ran"


def test_cpu_authoritative_workload_rejects_gpu_observation():
    with pytest.raises(ValueError, match="CPU-authoritative"):
        observe_workload(
            workload_id="serialize",
            workload_kind="serialization",
            current_placement="python",
            source_sha256=H,
            scheduler_snapshot=RuntimeWorkPlane(Path(".")).snapshot(),
            before_benchmark={"sealed": True, "custody_hash": H},
            boundary_contract_sha256=H,
            rollback_artifact_sha256=H,
            hardware_route={
                "selected_device": "cuda",
                "actual_device": "cuda",
                "fallback": False,
                "correctness_passed": True,
            },
        )


def test_observation_rejects_ambiguous_route_and_unverified_cuda(tmp_path):
    base = {
        "workload_id": "segment",
        "workload_kind": "text_analysis",
        "current_placement": "python",
        "source_sha256": H,
        "scheduler_snapshot": RuntimeWorkPlane(tmp_path).snapshot(),
        "before_benchmark": {"sealed": True, "custody_hash": H},
        "boundary_contract_sha256": H,
        "rollback_artifact_sha256": H,
    }
    with pytest.raises(ValueError, match="selected and actual"):
        observe_workload(**base, hardware_route={"actual_device": "cpu"})
    with pytest.raises(ValueError, match="correctness"):
        observe_workload(
            **base,
            hardware_route={
                "selected_device": "cuda",
                "actual_device": "cuda",
                "fallback": False,
            },
        )
