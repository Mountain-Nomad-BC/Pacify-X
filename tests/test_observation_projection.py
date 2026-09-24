from __future__ import annotations
import hashlib
import pytest
from runtime.observation_projection import build_observation_pack, validate_observation_pack
from runtime.evidence_reducer import verify_candidate_receipt
from runtime.memory_intelligence import build_bounded_observation_pack
from runtime.reasoning_controls import decide_context_compaction


def test_full_then_handle_projection_preserves_source_identity_and_handle():
    text="0123456789"*2000
    full=build_observation_pack(text, source_locator="artifact:1", stable_handle="obs:1", provider_requests_since_observed=0, threshold_chars=100)
    handle=build_observation_pack(text, source_locator="artifact:1", stable_handle="obs:1", provider_requests_since_observed=3, threshold_chars=100, excerpt_chars=100)
    assert full["mode"] == "full" and handle["mode"] == "handle"
    assert full["content_sha256"] == handle["content_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert "handle=obs:1" in handle["projected_text"]
    validate_observation_pack(handle)


def test_verified_reducer_receipt_projects_instead_of_unverified_summary():
    text=("important evidence line\n"*500); digest=hashlib.sha256(text.encode()).hexdigest()
    receipt=verify_candidate_receipt(source_text=text, exit_status=0, source_locator="artifact:2", candidate={"schema_version":"px.evidence-reduction/1.0","source_sha256":digest,"source_locator":"artifact:2","exit_status":0,"summary":"evidence repeats","exact_quotes":["important evidence line"],"finding_labels":["evidence"]})
    pack=build_bounded_observation_pack(text=text, source_locator="artifact:2", stable_handle="obs:2", provider_requests_since_observed=5, reducer_receipt=receipt)
    assert pack["mode"] == "verified_receipt" and pack["reducer_receipt_sha256"] == receipt["receipt_sha256"]


def test_receipt_for_different_source_is_rejected():
    text="a"*10000; other="b"*10000; digest=hashlib.sha256(other.encode()).hexdigest()
    receipt=verify_candidate_receipt(source_text=other, exit_status=0, source_locator="artifact:other", candidate={"schema_version":"px.evidence-reduction/1.0","source_sha256":digest,"source_locator":"artifact:other","exit_status":0,"summary":"b summary","exact_quotes":["bbbb"],"finding_labels":[]})
    with pytest.raises(ValueError, match="does not bind"):
        build_observation_pack(text, source_locator="artifact:1", stable_handle="obs", provider_requests_since_observed=3, reducer_receipt=receipt)


def test_context_compaction_is_economic_and_step_boundary_gated_except_emergency():
    delayed=decide_context_compaction(current_context_tokens=6000, context_window_tokens=20000, observed_growth_tokens_per_request=500, observed_requests_per_completed_step=6, unfinished_steps=5, cache_rewrite_ratio=.2, retained_fraction_after_compaction=.5, at_plan_step_boundary=False)
    assert delayed["compact"] is False and delayed["reason"] == "not_plan_boundary"
    boundary=decide_context_compaction(current_context_tokens=6000, context_window_tokens=20000, observed_growth_tokens_per_request=500, observed_requests_per_completed_step=6, unfinished_steps=5, cache_rewrite_ratio=.2, retained_fraction_after_compaction=.5, at_plan_step_boundary=True)
    assert boundary["compact"] is True
    emergency=decide_context_compaction(current_context_tokens=19000, context_window_tokens=20000, observed_growth_tokens_per_request=0, observed_requests_per_completed_step=0, unfinished_steps=0, at_plan_step_boundary=False)
    assert emergency["compact"] is True and emergency["emergency"] is True

def test_context_compaction_rejects_truthy_non_boolean_boundary():
    with pytest.raises(ValueError, match="boundary flag"):
        decide_context_compaction(current_context_tokens=1000, context_window_tokens=2000, observed_growth_tokens_per_request=10, observed_requests_per_completed_step=1, unfinished_steps=1, at_plan_step_boundary="false")
