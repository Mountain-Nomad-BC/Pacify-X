from __future__ import annotations

import pytest

from runtime.learning_promotion import (
    aggregate_operations,
    confidence_gate,
    decay_decision,
    freeze_revision,
    hash_tree,
    measure_reuse,
    operation_evidence,
    promote_revision,
    research_validation,
    compare_revisions,
    content_hash,
    validate_learning_pipeline_state,
)


def test_tier_four_and_five_revisions_remain_validated_until_final_promotion():
    for tier in (4, 5):
        revision = freeze_revision(
            unit_id=f"placement.pattern.{tier}",
            kind="runtime",
            artifact={"tier": tier},
            evidence_sha256=[H],
            tier=tier,
        )
        assert revision["tier"] == tier
        assert revision["state"] == "validated"
        assert revision["canonical"] is False


H = "a" * 64


def evidence(index: int, value: float = 1.0):
    return operation_evidence(
        operation_id=f"op-{index}",
        task_class="repair",
        outcome="passed",
        measurements={"quality": value},
        capability_ids=["A", "C"],
        environment_sha256=H,
        source_refs=[f"trace:{index}"],
        observed_at=f"2026-08-12T00:00:{index:02d}+00:00",
    )


def test_operation_hashes_are_stable_and_aggregations_remain_hashless():
    left = evidence(1)
    right = evidence(1)
    assert left == right
    aggregate = aggregate_operations([left, evidence(2, 2.0)], metric="quality")
    assert aggregate["aggregation_identity"] is None
    assert "record_sha256" not in aggregate
    assert len(aggregate["source_merkle_root"]) == 64


def test_confidence_requires_statistical_lower_bound_not_a_bare_majority():
    assert not confidence_gate(wins=4, losses=2, minimum_trials=6)["passed"]
    assert confidence_gate(wins=18, losses=2, minimum_trials=6)["passed"]


def test_full_candidate_ab_research_validation_and_promotion_chain():
    incumbent = freeze_revision(
        unit_id="route.failure-x",
        kind="skill",
        artifact={"skills": ["A", "B", "C"]},
        evidence_sha256=[H],
        dependency_sha256={"policy": H},
    )
    challenger = freeze_revision(
        unit_id="route.failure-x",
        kind="skill",
        artifact={"skills": ["A", "C"]},
        evidence_sha256=[H],
        dependency_sha256={"policy": H},
        parent_revision_sha256=incumbent["revision_sha256"],
        tier=2,
    )
    trials = [{"winner": "challenger", "evidence_sha256": H} for _ in range(18)] + [
        {"winner": "incumbent", "evidence_sha256": H} for _ in range(2)
    ]
    comparison = compare_revisions(
        incumbent=incumbent, challenger=challenger, trials=trials
    )
    confidence = confidence_gate(wins=18, losses=2)
    research = research_validation(
        question="Is A+C the best evidenced procedure?",
        references=[
            {
                "uri": "evidence:independent-review",
                "evidence_sha256": H,
                "independent": True,
            }
        ],
        better_alternative_found=False,
        conclusion="No stronger bounded alternative was found.",
    )
    promotion = promote_revision(
        revision=challenger,
        confidence=confidence,
        comparison=comparison,
        research=research,
        final_validation_sha256=H,
        current_dependencies={"policy": H},
        partial_units=["failure-x-router"],
    )
    assert promotion["passed"]
    assert len(promotion["canonical_corpus_sha256"]) == 64
    assert not promotion["learning_direct_write_allowed"]
    assert promotion["rollback_revision_sha256"] == incumbent["revision_sha256"]

    state = {
        "incumbent_revision": incumbent,
        "challenger_revision": challenger,
        "trials": trials,
        "comparison": comparison,
        "selection_comparison": comparison,
        "selected_revision": challenger,
        "research": research,
        "final_validation": {
            "schema_version": "px.learning-final-validation/1.0",
            "evidence_sha256": H,
        },
        "promotion_decision": promotion,
        "reuse_measurements": [],
    }
    validate_learning_pipeline_state(state)
    assert (
        len(
            {
                challenger["artifact_sha256"],
                challenger["revision_sha256"],
                challenger["record_sha256"],
                promotion["record_sha256"],
                promotion["canonical_corpus_sha256"],
            }
        )
        == 5
    )


def test_typed_parser_rejects_swapped_revision_and_corpus_hash_roles():
    incumbent = freeze_revision(
        unit_id="route.parser",
        kind="skill",
        artifact={"skills": ["A", "B"]},
        evidence_sha256=[H],
    )
    challenger = freeze_revision(
        unit_id="route.parser",
        kind="skill",
        artifact={"skills": ["A"]},
        evidence_sha256=[H],
        parent_revision_sha256=incumbent["revision_sha256"],
        tier=2,
    )
    trials = [{"winner": "challenger", "evidence_sha256": H} for _ in range(20)]
    comparison = compare_revisions(
        incumbent=incumbent, challenger=challenger, trials=trials
    )
    research = research_validation(
        question="Is the parser-bound route better?",
        references=[{"uri": "evidence:review", "evidence_sha256": H}],
        better_alternative_found=False,
        conclusion="The bounded route passed independent review.",
    )
    promotion = promote_revision(
        revision=challenger,
        confidence=comparison["gate"],
        comparison=comparison,
        research=research,
        final_validation_sha256=H,
        current_dependencies={},
    )
    base = {
        "incumbent_revision": incumbent,
        "challenger_revision": challenger,
        "trials": trials,
        "comparison": comparison,
        "selection_comparison": comparison,
        "selected_revision": challenger,
        "research": research,
        "final_validation": {
            "schema_version": "px.learning-final-validation/1.0",
            "evidence_sha256": H,
        },
        "promotion_decision": promotion,
    }

    swapped_revision = dict(challenger)
    swapped_revision["artifact_sha256"] = challenger["revision_sha256"]
    swapped_revision["record_sha256"] = content_hash(
        {
            key: value
            for key, value in swapped_revision.items()
            if key != "record_sha256"
        }
    )
    with pytest.raises(ValueError, match="semantic identity"):
        validate_learning_pipeline_state(
            {
                **base,
                "challenger_revision": swapped_revision,
                "selected_revision": swapped_revision,
            }
        )

    swapped_promotion = dict(promotion)
    swapped_promotion["canonical_corpus_sha256"] = promotion["record_sha256"]
    swapped_promotion["record_sha256"] = content_hash(
        {
            key: value
            for key, value in swapped_promotion.items()
            if key != "record_sha256"
        }
    )
    with pytest.raises(ValueError, match="canonical corpus binding"):
        validate_learning_pipeline_state(
            {**base, "promotion_decision": swapped_promotion}
        )


def test_dependency_drift_and_any_failed_gate_block_canonical_promotion():
    revision = freeze_revision(
        unit_id="memory.repo-fact",
        kind="memory",
        artifact={"fact": "x"},
        evidence_sha256=[H],
        dependency_sha256={"repo": H},
    )
    failed = confidence_gate(wins=3, losses=3)
    research = research_validation(
        question="valid?",
        references=[{"uri": "evidence:r", "evidence_sha256": H}],
        better_alternative_found=False,
        conclusion="bounded",
    )
    result = promote_revision(
        revision=revision,
        confidence=failed,
        comparison={"record_type": "ab_comparison", "passed": False},
        research=research,
        final_validation_sha256=H,
        current_dependencies={"repo": "b" * 64},
    )
    assert not result["passed"]
    assert result["canonical_corpus_sha256"] is None
    assert not result["checks"]["dependencies_current"]


def test_measured_reuse_can_decay_but_never_delete_a_canonical_revision():
    measurement = measure_reuse(promotion_sha256=H, uses=12, successes=7, regressions=3)
    decision = decay_decision(measurement)
    assert decision["decay"]
    assert decision["next_state"] == "decayed"
    assert not decision["automatic_delete_allowed"]


def test_hierarchical_hashes_are_order_stable_and_reject_unknown_dependencies():
    left = hash_tree({"skill": {"x": 1}, "router": {"y": 2}}, {"router": ["skill"]})
    right = hash_tree({"router": {"y": 2}, "skill": {"x": 1}}, {"router": ["skill"]})
    assert left["root_sha256"] == right["root_sha256"]
    try:
        hash_tree({"skill": {}}, {"skill": ["missing"]})
    except ValueError as error:
        assert "unknown" in str(error)
    else:
        raise AssertionError("unknown dependency was accepted")
