"""Tests for the governed System-1 decision layer (Laya integration).

These prove the PX *contract*, not the Laya weights: the engine is stubbed so the tests run
without torch/transformers while still exercising the real adapter, compiler, policy gate,
and gateway.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.system_one_decision import (
    DecisionGateway,
    DecisionPolicy,
    DecisionResult,
    LayaDecisionAdapter,
    LayaProtocolError,
    compile_decision_state,
    evaluate_decision,
    load_decision_policy,
    validate_questions,
)

ROOT = Path(__file__).parents[1]

QUESTIONS = {
    "tier": {
        "type": "choice",
        "instructions": "Which model tier should handle this task?",
        "criteria": {
            "nano": "trivial extraction",
            "active_librarian": "normal PX work",
            "heavy_local": "hard reasoning",
            "remote": "frontier only",
        },
    },
    "success_likely": {
        "type": "noul",
        "instructions": "Is the current model likely to succeed?",
    },
}


def _stub(probabilities: dict[str, float] | None = None):
    probs = probabilities or {"nano": 0.03, "active_librarian": 0.77, "heavy_local": 0.17, "remote": 0.03}

    class _Engine:
        def predict(self, state, questions):
            answers = {}
            for qid, spec in questions.items():
                if spec["type"] == "choice":
                    answers[qid] = {
                        "type": "choice",
                        "choice": max(probs, key=lambda k: probs[k]),
                        "probabilities": dict(probs),
                    }
                elif spec["type"] == "noul":
                    answers[qid] = {"type": "noul", "probability": 0.91}
                else:
                    answers[qid] = {"type": "score", "score": 1, "probabilities": {"0": 0.2, "1": 0.8}}
            return {"answers": answers, "routing": {"model": "typed-decisions", "reason": "stub"}}

    return _Engine()


# --- policy registry -------------------------------------------------------


def test_policy_registry_is_versioned_and_valid() -> None:
    policies = load_decision_policy(ROOT)
    assert policies, "decision policy registry must exist"
    for policy in policies.values():
        policy.validate()
        assert policy.version >= 1
        assert 0.0 <= policy.min_top_probability <= 1.0
        assert 0.0 <= policy.min_margin <= 1.0
    assert "routing.model_tier" in policies


def test_destructive_risk_policy_is_advisory_only() -> None:
    policies = load_decision_policy(ROOT)
    assert policies["destructive_action_risk"].advisory_only is True


# --- question envelope -----------------------------------------------------


def test_question_envelope_is_validated() -> None:
    normalized = validate_questions(QUESTIONS)
    assert set(normalized) == {"tier", "success_likely"}
    with pytest.raises(ValueError):
        validate_questions({"q": {"type": "nonsense", "instructions": "x"}})
    with pytest.raises(ValueError):
        validate_questions({})
    with pytest.raises(ValueError):
        validate_questions({"q": {"type": "choice", "instructions": "x"}})


# --- decision state compiler ----------------------------------------------


def test_missing_state_is_explicitly_unknown_and_never_invented() -> None:
    compiled = compile_decision_state(
        "routing.model_tier",
        provided={"task_kind": "repository_debug"},
        required=("task_kind",),
        optional=("retrieval_coverage",),
    )
    assert compiled.fields == {"task_kind": "repository_debug"}
    assert "retrieval_coverage" in compiled.unknown_fields
    mapping = compiled.as_mapping()
    assert mapping["retrieval_coverage_known"] is False
    assert "retrieval_coverage" not in mapping["fields"]


def test_state_compiler_drops_optional_fields_to_fit_budget() -> None:
    compiled = compile_decision_state(
        "routing.model_tier",
        provided={"task_kind": "x", "padding": "y" * 4000},
        required=("task_kind",),
        optional=("padding",),
        token_budget=64,
    )
    assert "task_kind" in compiled.fields
    assert "padding" not in compiled.fields
    assert compiled.token_estimate <= 64


# --- adapter ---------------------------------------------------------------


def test_adapter_returns_typed_result_with_checkpoint_identity() -> None:
    adapter = LayaDecisionAdapter(engine_factory=_stub)
    assert adapter.available() is True
    result = adapter.decide(decision_id="routing.model_tier", state={"a": 1}, questions=QUESTIONS)
    assert isinstance(result, DecisionResult)
    assert result.checkpoint == "typed-decisions"
    assert len(result.input_state_sha256) == 64
    assert result.latency_ms >= 0.0


def test_adapter_fails_typed_on_out_of_contract_payload() -> None:
    adapter = LayaDecisionAdapter(engine_factory=lambda: type("B", (), {"predict": lambda s, q: "nope"})())
    with pytest.raises(LayaProtocolError):
        adapter.decide(decision_id="routing.model_tier", state={"a": 1}, questions=QUESTIONS)


# --- policy gate -----------------------------------------------------------


def test_threshold_and_margin_gate_accepts_a_strong_distribution() -> None:
    policy = DecisionPolicy("routing.model_tier", 1, 0.72, 0.18, "escalate")
    adapter = LayaDecisionAdapter(engine_factory=_stub)
    result = adapter.decide(decision_id="routing.model_tier", state={"a": 1}, questions=QUESTIONS)
    evaluation = evaluate_decision(result, policy, question_id="tier")
    assert evaluation.accepted is True
    assert evaluation.top_label == "active_librarian"


def _narrow_stub():
    """A stub whose distribution is below the margin threshold (two near-equal leaders)."""
    narrow = {"nano": 0.51, "active_librarian": 0.49, "heavy_local": 0.0, "remote": 0.0}

    class _Narrow:
        def predict(self, state, questions):
            return {
                "answers": {
                    "tier": {
                        "type": "choice",
                        "choice": "nano",
                        "probabilities": dict(narrow),
                    }
                },
                "routing": {"model": "typed-decisions"},
            }

    return _Narrow()


def test_ambiguous_distribution_routes_to_policy_action_not_acceptance() -> None:
    policy = DecisionPolicy("routing.model_tier", 1, 0.72, 0.18, "escalate")
    adapter = LayaDecisionAdapter(engine_factory=_narrow_stub)
    result = adapter.decide(decision_id="routing.model_tier", state={"a": 1}, questions=QUESTIONS)
    evaluation = evaluate_decision(result, policy, question_id="tier")
    assert evaluation.accepted is False
    assert evaluation.reason in {"top_probability_below_threshold", "margin_below_threshold"}
    assert evaluation.ambiguity_action == "escalate"


def test_non_choice_answers_are_advisory_only() -> None:
    policy = DecisionPolicy("routing.model_tier", 1, 0.72, 0.18, "escalate")
    adapter = LayaDecisionAdapter(engine_factory=_stub)
    result = adapter.decide(decision_id="routing.model_tier", state={"a": 1}, questions=QUESTIONS)
    evaluation = evaluate_decision(result, policy, question_id="success_likely")
    assert evaluation.accepted is False
    assert evaluation.reason == "advisory_only_answer_type"


def test_policy_must_belong_to_the_decision() -> None:
    policy = DecisionPolicy("other.decision", 1, 0.5, 0.1, "escalate")
    adapter = LayaDecisionAdapter(engine_factory=_stub)
    result = adapter.decide(decision_id="routing.model_tier", state={"a": 1}, questions=QUESTIONS)
    with pytest.raises(ValueError):
        evaluate_decision(result, policy, question_id="tier")


# --- gateway ---------------------------------------------------------------


def test_gateway_returns_deterministic_fallback_when_engine_unavailable() -> None:
    def _boom():
        raise ImportError("torch missing")

    gateway = DecisionGateway(adapter=LayaDecisionAdapter(engine_factory=_boom), policies=load_decision_policy(ROOT))
    record = gateway.decide(
        decision_id="routing.model_tier",
        state_facts={"task_kind": "x"},
        required=("task_kind",),
        optional=(),
        questions=QUESTIONS,
    )
    assert record["available"] is False
    assert record["fallback"] == "deterministic"
    assert "questions" not in record


def test_gateway_records_decision_with_policy_and_advisory_authority() -> None:
    gateway = DecisionGateway(
        adapter=LayaDecisionAdapter(engine_factory=_stub),
        policies=load_decision_policy(ROOT),
    )
    record = gateway.decide(
        decision_id="routing.model_tier",
        state_facts={"task_kind": "repository_debug", "retrieval_coverage": 0.94},
        required=("task_kind",),
        optional=("retrieval_coverage", "context_saturation"),
        questions=QUESTIONS,
        question_id="tier",
    )
    assert record["available"] is True
    assert record["accepted"] is True
    assert record["authority"] == "advisory"
    assert record["model"]["checkpoint"] == "typed-decisions"
    assert "context_saturation" in record["unknown_fields"]
    assert len(record["input_state_sha256"]) == 64
    assert gateway.telemetry and gateway.telemetry[-1] is record


# --- registry wiring -------------------------------------------------------


def test_capability_map_includes_the_system_one_capability() -> None:
    payload = json.loads((ROOT / "registry/capability_map.json").read_text(encoding="utf-8"))
    ids = {entry["id"] for entry in payload["active_capabilities"]}
    assert "system-one-decision" in ids
    assert len(ids) > 100