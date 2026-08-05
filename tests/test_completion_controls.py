from __future__ import annotations

from pathlib import Path

import pytest

from runtime.completion_controls import (
    PIPELINE_STAGES,
    atomic_work_checkout,
    choose_runtime,
    evaluate_offline_skill_candidate,
    fingerprint_repository,
    invalidate_dependents,
    optimize_candidate_package,
    query_bitemporal_facts,
    reconcile_budget,
    reserve_budget,
    synthesize_mechanism_delta,
    transition_job,
    validate_candidate_stage_trace,
    validate_completion_control_workflow,
    validate_delivery,
    verify_batch_independent_scores,
)


ROOT = Path(__file__).parents[1]


def stage_trace():
    current = ("a", "b", "c")
    rows = []
    for stage in PIPELINE_STAGES:
        output = current
        reasons = {}
        if stage == "hard_filtering":
            output = ("a", "b")
            reasons = {"c": "authority_denied"}
        elif stage == "package_selection":
            output = ("a",)
        rows.append(
            {
                "stage": stage,
                "component": stage,
                "required": True,
                "status": "ok",
                "input_ids": current,
                "output_ids": output,
                "removal_reasons": reasons,
            }
        )
        current = output
    return rows


def test_candidate_trace_enforces_membership_and_failure_semantics():
    trace = stage_trace()
    assert validate_candidate_stage_trace(trace)["valid"]
    trace[4]["output_ids"] = ("b", "a", "c")
    report = validate_candidate_stage_trace(trace)
    assert not report["valid"]
    assert any("membership" in error for error in report["errors"])


def test_batch_scores_are_candidate_intrinsic():
    baseline = {"a": {"task": 0.8}, "b": {"task": 0.3}}
    expanded = {**baseline, "unrelated": {"task": 0.1}}
    assert verify_batch_independent_scores(baseline, expanded)["valid"]
    expanded["a"] = {"task": 0.7}
    assert verify_batch_independent_scores(baseline, expanded)[
        "changed_candidate_ids"
    ] == ("a",)


def test_package_is_dependency_complete_diverse_and_accounts_for_every_candidate():
    candidates = (
        {
            "id": "implementation",
            "kind": "skill",
            "family": "one",
            "intrinsic_score": 90,
            "cost": 2,
            "admitted": True,
            "capabilities": ["build"],
            "dependencies": ["validator"],
        },
        {
            "id": "duplicate-family",
            "kind": "skill",
            "family": "one",
            "intrinsic_score": 80,
            "cost": 2,
            "admitted": True,
            "capabilities": ["build"],
        },
        {
            "id": "validator",
            "kind": "validator",
            "family": "two",
            "intrinsic_score": 30,
            "cost": 1,
            "admitted": True,
            "capabilities": ["verify"],
        },
        {
            "id": "untrusted",
            "kind": "tool",
            "intrinsic_score": 100,
            "cost": 1,
            "admitted": False,
            "capabilities": ["build"],
        },
    )
    result = optimize_candidate_package(
        candidates,
        required_capabilities=("build", "verify"),
        required_kinds=("skill", "validator"),
        max_cost=5,
    )
    assert result["complete"]
    assert {"implementation", "validator"} <= set(result["selected"])
    accounted = set(result["selected"]) | {item[0] for item in result["rejected"]}
    assert accounted == {item["id"] for item in candidates}


def test_budget_reservation_is_atomic_and_reconciled():
    denied = reserve_budget(
        project_id="p",
        work_id="w",
        requested={"cost": 6, "turns": 2},
        limits={"cost": 5, "turns": 3},
    )
    assert denied["state"] == "denied"
    granted = reserve_budget(
        project_id="p",
        work_id="w",
        requested={"cost": 4, "turns": 2},
        limits={"cost": 5, "turns": 3},
    )
    assert granted["state"] == "active"
    receipt = reconcile_budget(granted, {"cost": 3, "turns": 2})
    assert receipt["state"] == "reconciled"
    assert receipt["released"]["cost"] == 1


def test_checkout_prevents_duplicate_work_and_version_drift():
    lease = atomic_work_checkout(
        project_id="p", work_id="w", expected_version=0, current=None, actor_id="a"
    )
    assert lease["state"] == "active"
    duplicate = atomic_work_checkout(
        project_id="p", work_id="w", expected_version=1, current=lease, actor_id="b"
    )
    assert duplicate["reason"] == "already_leased"


def test_runtime_placement_filters_before_cost_sorting():
    result = choose_runtime(
        (
            {
                "id": "cheap-untrusted",
                "healthy": True,
                "trust": 1,
                "capabilities": ["gpu"],
                "available_quota": 1,
                "cost": 0,
            },
            {
                "id": "scoped",
                "healthy": True,
                "trust": 3,
                "capabilities": ["gpu"],
                "available_quota": 1,
                "cost": 2,
                "project_scopes": ["p"],
            },
        ),
        project_id="p",
        required_capabilities=("gpu",),
        minimum_trust=2,
    )
    assert result["selected_runtime"] == "scoped"


def test_job_success_requires_evidence_and_terminal_state_is_sticky():
    job = {"job_id": "j", "project_id": "p", "state": "running"}
    with pytest.raises(ValueError, match="evidence"):
        transition_job(job, "succeeded")
    completed = transition_job(job, "succeeded", evidence_ids=("E-1",))
    with pytest.raises(ValueError, match="sticky"):
        transition_job(completed, "running")


def test_bitemporal_query_and_transitive_invalidation_are_distinct():
    facts = (
        {
            "fact_id": "old",
            "project_id": "p",
            "valid_from": "2024-01-01T00:00:00Z",
            "valid_to": "2025-01-01T00:00:00Z",
            "known_from": "2024-02-01T00:00:00Z",
        },
        {
            "fact_id": "foreign",
            "project_id": "q",
            "valid_from": "2024-01-01T00:00:00Z",
            "known_from": "2024-01-01T00:00:00Z",
        },
    )
    selected = query_bitemporal_facts(
        facts,
        valid_at="2024-06-01T00:00:00Z",
        known_at="2024-06-01T00:00:00Z",
        project_id="p",
    )
    assert [item["fact_id"] for item in selected] == ["old"]
    invalidation = invalidate_dependents(
        ("source",), {"observation": ("source",), "report": ("observation",)}
    )
    assert invalidation["invalidated"] == ("observation", "report")


def test_offline_skill_evaluation_cannot_self_approve():
    baseline = ({"case_id": "held", "score": 0.5},)
    candidate = ({"case_id": "held", "score": 0.8},)
    result = evaluate_offline_skill_candidate(
        baseline=baseline,
        candidate=candidate,
        heldout_case_ids=("held",),
        actor_id="actor",
        optimizer_id="optimizer",
        judge_id="judge",
    )
    assert result["decision"] == "proposal_ready"
    assert result["activation"] == "quarantined_candidate"
    with pytest.raises(ValueError, match="distinct"):
        evaluate_offline_skill_candidate(
            baseline=baseline,
            candidate=candidate,
            heldout_case_ids=("held",),
            actor_id="same",
            optimizer_id="same",
            judge_id="judge",
        )


def test_physical_and_media_validation_fail_closed():
    result = validate_delivery(
        expected={"format": "STEP"},
        observed={"format": "STEP", "independent_checks": ["dimensions", "topology"]},
        domain="manufacturing",
    )
    assert not result["valid"]
    assert "missing_independent_check:manufacturability" in result["blockers"]
    assert validate_delivery(
        expected={"codec": "av1"},
        observed={"codec": "av1", "provider_downgrade": False},
        domain="media",
    )["valid"]


def test_research_fingerprints_mechanisms_without_promoting_repositories():
    fingerprint = fingerprint_repository(
        ({"path": "src/a.py", "bytes": 3, "sha256": "a" * 64},)
    )
    assert fingerprint["file_count"] == 1
    delta = synthesize_mechanism_delta(
        (
            {
                "mechanism_id": "known",
                "canonical_owner": "owner",
                "evidence_ids": ["E-1"],
            },
            {"mechanism_id": "new", "canonical_owner": "", "evidence_ids": ["E-2"]},
        ),
        ("owner",),
    )
    assert not delta["promotion_allowed"]
    assert dict((item[0], item[1]) for item in delta["records"]) == {
        "known": "enrich",
        "new": "novel_candidate",
    }


def test_completion_workflow_is_executable_and_complete():
    assert validate_completion_control_workflow(ROOT) == {
        "valid": True,
        "workflow_count": 5,
        "errors": [],
    }
