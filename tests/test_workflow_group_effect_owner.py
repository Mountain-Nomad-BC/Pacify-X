"""Actual native group owner fixtures; in-process member work, no model operations."""
import json
import pytest
from runtime.studio_models import CapabilityBinding, EffectGrant, digest
from runtime.scope_lease import ScopeLeaseStore
from runtime.studio_authority import StudioAuthorityStore
from runtime.trusted_evidence import TrustedEvidenceResolver
from tests.test_workflow_group_transport import _prepared_plan

@pytest.mark.parametrize("failed_member", [False, True, "workflow-cancel"])
def test_actual_group_owner_correlates_only_successful_native_runtime_effect(tmp_path, failed_member):
    plan, group, persisted = _prepared_plan(tmp_path, "d" * 64, "fixture", with_group=True)
    from tests.workflow_group_owner_fixture import workflow_group_fixture
    fixture = workflow_group_fixture(tmp_path, plan, group)
    spec, controller, placements, authority, control, run_id, context, ledger, effect, signed = (
        fixture[key] for key in ("spec","controller","placements","authority","control","run_id","context","ledger","effect","signed"))
    calls = []
    def member_executor(invocation, **kwargs):
        assert ledger.fence(effect["idempotency_key"])["disposition"] == "in_flight"
        assert ScopeLeaseStore(tmp_path).active(effect="execute")
        calls.append(invocation.model_id)
        if failed_member == "workflow-cancel":
            control.transition(run_id, "cancel_requested", actor="human:owner", approved=True)
            assert kwargs["cancellation_token"]() is True
            raise RuntimeError("controlled workflow cancellation observed during native member work")
        if failed_member is True and invocation.model_id == group.model_ids[-1]:
            raise RuntimeError("controlled unit member failure")
        return {"answer":"bounded in-process result", "member":invocation.model_id}
    store = tmp_path / "unit-evidence"
    store.mkdir()
    trust = tmp_path / "unit-trust.json"
    trust.write_text("{}")
    result = controller.execute_governed_group(spec, task_plan=plan.as_dict(), placements=placements,
        approval=True, member_executor=member_executor, generation_observer=lambda:plan.context_generation,
        evidence_resolver=TrustedEvidenceResolver(store,trust), accepted_producers={"unit:producer"},
        attestation_provider=None, workflow_effect_receipt=signed)
    assert calls == ([group.model_ids[0]] if failed_member == "workflow-cancel" else list(group.model_ids))
    retained = authority.verify_receipt(json.loads((controller.state_root/"group-runs"/(result["group_run_sha256"]+".json")).read_text()))
    assert digest(retained) == digest(result)
    assert retained["workflow_execution_context"] == context.as_dict()
    observed = ledger.fence(effect["idempotency_key"])
    if failed_member:
        assert result["control_state"] == "failed"
        assert observed["disposition"] == "in_flight"
    else:
        assert result["control_state"] == "succeeded"
        assert observed["disposition"] == "committed"
        assert observed["result_sha256"] == result["group_run_sha256"]
        assert all(row["outcome"]["branch_artifact"] for row in result["member_receipts"].values())
    # No independent attestation was manufactured: convergence remains unproven.
    assert not all(row["admitted"] for row in result["assessment"]["branch_assessments"])


def test_unknown_workflow_adapter_is_rejected_by_native_authority(tmp_path):
    authority = StudioAuthorityStore(tmp_path)
    grant = EffectGrant("grant:unit", "workflow:unit", ("execute",), ("runtime",),
        "human:owner", ("unit:grant",), state="admitted")
    binding = CapabilityBinding("binding:unit", "workflow", "workflow:unit", "capability:unit",
        "1.0.0", (grant.grant_id,), None, "non-billable", "deny", "admitted", ("unit:binding",))
    with pytest.raises(ValueError, match="closed registry"):
        authority.register_authority_transaction((binding,), (grant,), {binding.binding_id:"unknown-adapter"})
    authority.register_authority_transaction((binding,), (grant,), {binding.binding_id:"model-group"})
    executor, executor_sha = authority.resolve_executor(binding.binding_id)
    assert executor["adapter_id"] == "model-group" and len(executor_sha) == 64
