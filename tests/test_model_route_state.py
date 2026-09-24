from __future__ import annotations

import pytest

from runtime.model_route_state import (
    AdaptiveRouteSignal,
    RouteCandidateRecord,
    build_route_decision,
    route_transition_record,
    stable_sample,
)


def test_stable_signal_requires_hashed_evidence_and_strict_units() -> None:
    with pytest.raises(ValueError, match="require hashed evidence"):
        AdaptiveRouteSignal("m", affinity=0.9, maturity="stable", model_generation_sha256="b" * 64)
    with pytest.raises(ValueError, match=r"\[0,1\]"):
        AdaptiveRouteSignal("m", pressure=float("nan"))
    signal = AdaptiveRouteSignal("m", affinity=0.9, quality=0.8, maturity="stable", model_generation_sha256="b" * 64, evidence_sha256=("a" * 64,))
    assert signal.evidence_only is True


def test_route_decision_identity_is_deterministic_and_authority_free() -> None:
    rows = (
        RouteCandidateRecord("m1", 10.0, 11.0, 1, "admit", ("a" * 64,), ("reason",)),
        RouteCandidateRecord("m2", 9.0, 9.0, 2, "admit", (), ("reason",)),
    )
    kwargs = dict(
        request_id="r1", task_class="coding", subject_ids=("python",), policy_sha256="b" * 64, policy_semantic_sha256="c" * 64,
        phase="freeze", candidates=rows, primary_model_id="m1", challenger_model_id=None,
        dispatch_state="dispatch", fallback_used=False,
    )
    one = build_route_decision(**kwargs)
    two = build_route_decision(**kwargs)
    assert one.decision_sha256 == two.decision_sha256
    assert one.authority_granted is False
    assert one.record()["authority_granted"] is False


def test_route_decision_rejects_challenger_or_wait_inconsistency() -> None:
    rows = (RouteCandidateRecord("m1", 1.0, 1.0, 1, "wait", (), ("capacity",)),)
    with pytest.raises(ValueError, match="wait decisions"):
        build_route_decision(
            request_id="r", task_class="coding", subject_ids=("coding",), policy_sha256="a" * 64, policy_semantic_sha256="b" * 64,
            phase="freeze", candidates=rows, primary_model_id="m1", dispatch_state="wait",
        )
    with pytest.raises(ValueError, match="distinct candidate"):
        build_route_decision(
            request_id="r", task_class="coding", subject_ids=("coding",), policy_sha256="a" * 64, policy_semantic_sha256="b" * 64,
            phase="freeze", candidates=rows, primary_model_id="m1", challenger_model_id="m1",
            dispatch_state="dispatch",
        )


def test_stable_sample_is_repeatable_and_bounded() -> None:
    assert stable_sample("same", rate=1.0) is True
    assert stable_sample("same", rate=0.0) is False
    assert stable_sample("same", rate=0.37) == stable_sample("same", rate=0.37)
    with pytest.raises(ValueError, match="sample rate"):
        stable_sample("x", rate=1.1)


def test_route_transition_is_evidence_only_and_content_addressed() -> None:
    record = route_transition_record(
        before_decision_sha256="a" * 64,
        after_decision_sha256="b" * 64,
        trigger="candidate policy benchmark",
        evidence_sha256=("c" * 64,),
    )
    assert len(record["transition_sha256"]) == 64
    assert record["authority_granted"] is False
    assert record["promotion_required"] is True
    with pytest.raises(ValueError, match="distinct"):
        route_transition_record(
            before_decision_sha256="a" * 64,
            after_decision_sha256="a" * 64,
            trigger="same",
            evidence_sha256=("c" * 64,),
        )
