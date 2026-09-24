from __future__ import annotations
import pytest
from runtime.action_fusion import build_fused_action_plan, validate_fusion_plan, record_fusion_outcome
from runtime.completion_controls import verify_recursive_terminal_evidence

H="a"*64

def plan(**changes):
    values=dict(mutation_binding_id="binding:edit", mutation_payload_sha256=H, mutation_effect_grant_ids=["grant:write"], followup_binding_id="binding:test", followup_kind="focused_test", followup_arguments={"path":"tests/test_x.py"}, followup_effect_grant_ids=["grant:process"], requires_inspection_before_followup=False, approval_required_between_actions=False, rollback_binding_id="binding:rollback")
    values.update(changes); return build_fused_action_plan(**values)


def test_fusion_plan_is_plan_only_and_requires_distinct_receipts():
    p=plan(); validate_fusion_plan(p); assert p["authority_granted"] is False
    out=record_fusion_outcome(p, mutation_receipt_sha256="b"*64, mutation_succeeded=True, followup_receipt_sha256="c"*64, followup_succeeded=True)
    assert out["completed"] is True and out["authority_granted"] is False
    with pytest.raises(ValueError, match="distinct receipts"):
        record_fusion_outcome(p, mutation_receipt_sha256="b"*64, mutation_succeeded=True, followup_receipt_sha256="b"*64, followup_succeeded=True)


def test_inspection_and_approval_boundaries_refuse_fusion():
    with pytest.raises(PermissionError, match="inspection"):
        plan(requires_inspection_before_followup=True)
    with pytest.raises(PermissionError, match="approval"):
        plan(approval_required_between_actions=True)


def test_failed_mutation_cannot_have_followup_receipt_and_can_bind_rollback():
    p=plan()
    with pytest.raises(ValueError, match="cannot execute"):
        record_fusion_outcome(p, mutation_receipt_sha256="b"*64, mutation_succeeded=False, followup_receipt_sha256="c"*64)
    out=record_fusion_outcome(p, mutation_receipt_sha256="b"*64, mutation_succeeded=False, rollback_receipt_sha256="d"*64)
    assert out["completed"] is False


def test_recursive_terminal_evidence_requires_independent_hashes():
    good=verify_recursive_terminal_evidence(final_evidence_sha256="1"*64,evaluator_sha256="2"*64,acceptance_policy_sha256="3"*64,holdout_case_set_sha256="4"*64,verification_record_sha256=["5"*64])
    assert good["independently_checkable"] is True
    bad=verify_recursive_terminal_evidence(final_evidence_sha256="bad",evaluator_sha256="2"*64,acceptance_policy_sha256="3"*64,holdout_case_set_sha256="4"*64,verification_record_sha256=[])
    assert bad["independently_checkable"] is False
