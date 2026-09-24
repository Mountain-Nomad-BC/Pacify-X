from __future__ import annotations

import json
import pytest

from runtime.tiny_model_operator import OperatorCandidate, TinyModelOperator


def candidate(cid: str, score: float = 0.5) -> OperatorCandidate:
    return OperatorCandidate(cid, "skills", "rev1", f"summary {cid}", score, ("evidence.json",))


def operator(invoke):
    return TinyModelOperator(
        invoke,
        model_id="qwen3.5-0.8b-control",
        profile_id="cpu-control",
        model_generation="mgen-a",
        fabric_generation="fgen-a",
    )


def test_single_candidate_bypasses_model():
    calls = []
    decision = operator(lambda payload: calls.append(payload)).select(
        query="choose", purpose="rerank-skills", candidates=(candidate("skill:a"),),
        contract_revision="rev", retrieval_generation="rgen",
    )
    assert decision.selected_ids == ("skill:a",)
    assert decision.invoked is False
    assert calls == []


def test_candidate_only_selection_and_receipt():
    seen = []
    def invoke(payload):
        seen.append(payload)
        return json.dumps({"selected_ids": ["skill:b", "skill:a"], "unresolved": False, "reason": "better fit"})
    decision = operator(invoke).select(
        query="choose", purpose="rerank-skills", candidates=(candidate("skill:a", .8), candidate("skill:b", .79)),
        contract_revision="rev", retrieval_generation="rgen",
    )
    assert decision.selected_ids == ("skill:b", "skill:a")
    assert decision.invoked is True
    assert seen[0]["candidate_ids_are_closed_world"] is True
    assert seen[0]["authority_granted"] is False
    assert len(decision.receipt_sha256) == 64


def test_invented_id_fails_closed_after_one_repair():
    calls = []
    def invoke(payload):
        calls.append(payload)
        return {"selected_ids": ["made-up"], "unresolved": False, "reason": "nope"}
    with pytest.raises(ValueError, match="failed closed"):
        operator(invoke).select(
            query="choose", purpose="rerank-skills", candidates=(candidate("skill:a"), candidate("skill:b")),
            contract_revision="rev", retrieval_generation="rgen",
        )
    assert len(calls) == 2
    assert calls[1]["repair"]["attempt"] == 1


def test_malformed_first_response_gets_one_bounded_repair():
    calls = []
    def invoke(payload):
        calls.append(payload)
        if len(calls) == 1:
            return "not-json"
        return {"selected_ids": [], "unresolved": True, "reason": "insufficient evidence"}
    decision = operator(invoke).select(
        query="choose", purpose="rerank-skills", candidates=(candidate("skill:a"), candidate("skill:b")),
        contract_revision="rev", retrieval_generation="rgen",
    )
    assert decision.unresolved is True
    assert decision.repaired is True
    assert len(calls) == 2



def test_provider_timeout_or_cancellation_fails_closed_without_repair_retry():
    calls = []
    def invoke(payload):
        calls.append(payload)
        raise TimeoutError("provider deadline")
    with pytest.raises(TimeoutError, match="provider deadline"):
        operator(invoke).select(
            query="choose", purpose="rerank-skills", candidates=(candidate("skill:a"), candidate("skill:b")),
            contract_revision="rev", retrieval_generation="rgen",
        )
    assert len(calls) == 1
    assert calls[0]["execution_policy"]["timeout_ms"] == 5000
    assert calls[0]["execution_policy"]["cancellation_owner"] == "injected-px-provider-runtime"
