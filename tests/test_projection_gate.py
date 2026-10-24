import pytest

from runtime.context_generation import context_vector
from runtime.projection_gate import ProjectionReadPolicy, evaluate_projection


def vector(revision="r1", **extra):
    return context_vector("px", "metadata", {"source_revision": revision, **extra}, required_components=("source_revision",))


def test_the_gate_covers_every_registered_projection_or_reports_it_ungated() -> None:
    """SEM-005's actual gap: opt-in coverage is not coverage.

    Five authority-bearing projections are registered in
    registry/projection_dependencies.json. Before the universal gate existed,
    every one of them sat outside the gate, so a stale catalog could still be
    served as fresh while the one gated projection looked healthy.
    """
    from runtime.projection_gate import (
        RegisteredProjection,
        assert_gate_complete,
        evaluate_registered_projections,
    )

    registered = [
        RegisteredProjection(
            projection_id=f"projection-{index}", output=f"registry/out-{index}.json",
            owner="builders/out.py", output_revision=f"rev{index}",
        )
        for index in range(5)
    ]
    report = evaluate_registered_projections(registered, {})

    assert report.complete is False
    assert len(report.ungated) == 5
    # An unmeasured projection is unknown, never fresh.
    for status in report.statuses.values():
        assert status.state == "ungated"
        assert status.serve_allowed is False
        assert "no_recorded_generation_vector" in status.reasons

    with pytest.raises(ValueError, match="gate is incomplete"):
        assert_gate_complete(report)


def test_a_fully_gated_registry_completes_and_still_detects_drift() -> None:
    from runtime.projection_gate import (
        RegisteredProjection,
        assert_gate_complete,
        evaluate_registered_projections,
    )

    recorded = context_vector("px", "catalog", {"source_revision": "r1"},
                              required_components=("source_revision",))
    registered = [
        RegisteredProjection(
            projection_id="catalog", output="registry/catalog.json",
            owner="builders/catalog.py", output_revision="rev1", recorded_vector=recorded,
        )
    ]
    current = {"catalog": context_vector("px", "catalog", {"source_revision": "r1"},
                                        required_components=("source_revision",))}
    report = evaluate_registered_projections(registered, current)
    assert report.complete is True
    assert report.statuses["catalog"].state == "fresh"
    assert_gate_complete(report)

    drifted = {"catalog": context_vector("px", "catalog", {"source_revision": "r2"},
                                         required_components=("source_revision",))}
    after = evaluate_registered_projections(registered, drifted)
    assert after.complete is True, "coverage is complete; the read is blocked"
    assert after.statuses["catalog"].state == "blocked"
    assert after.statuses["catalog"].serve_allowed is False


def test_stale_projection_is_blocked_and_cannot_claim_fresh():
    result = evaluate_projection("catalog", vector(), vector("r2"))
    assert result.state == "blocked"
    assert result.serve_allowed is False
    assert result.rebuild_required is True
    assert "source_revision" in result.stale_dependencies
    fresh = evaluate_projection("catalog", vector(), vector())
    assert fresh.state == "fresh" and fresh.serve_allowed and not fresh.rebuild_required
    execution = evaluate_projection("catalog", vector(), vector(), purpose="execute")
    assert execution.state == "blocked" and not execution.serve_allowed


def test_degraded_read_requires_explicit_host_policy_and_never_grants_execution():
    policy = ProjectionReadPolicy(authority="admitted-read-owner", allow_degraded=True)
    result = evaluate_projection("catalog", vector(), vector("r2"), policy=policy)
    assert result.state == "degraded" and result.serve_allowed
    assert result.rebuild_required
    assert evaluate_projection("catalog", vector(), vector("r2"), policy=policy, purpose="execute").serve_allowed is False
    with pytest.raises(ValueError):
        ProjectionReadPolicy(authority="", allow_degraded=True)


def test_missing_required_dependency_and_scope_changes_fail_closed():
    missing = context_vector("px", "metadata", {}, required_components=("source_revision",))
    policy = ProjectionReadPolicy(authority="admitted-read-owner", allow_degraded=True)
    assert evaluate_projection("catalog", vector(), missing, policy=policy).state == "blocked"
    with pytest.raises(ValueError, match="scope"):
        evaluate_projection("catalog", vector(), context_vector("px", "other", {"source_revision": "r1"}, required_components=("source_revision",)))


def test_authority_drift_cannot_be_waived_by_read_policy():
    policy = ProjectionReadPolicy(authority="admitted-read-owner", allow_degraded=True)
    before = vector(authority_revision="a1")
    after = vector(authority_revision="a2")
    result = evaluate_projection("catalog", before, after, policy=policy)
    assert result.state == "blocked" and not result.serve_allowed
