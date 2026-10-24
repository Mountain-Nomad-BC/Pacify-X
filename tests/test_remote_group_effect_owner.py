"""Actual prepared group/gateway owners; recording transport only, no real egress."""
from dataclasses import replace
import json
import pytest
from tests.test_remote_model_bridge import configured, RecordingTransport
from tests.test_remote_group_attachment import prepare_remote_fixture
from tests.workflow_group_owner_fixture import workflow_group_fixture
from runtime.remote_provider_profiles import ROOT
from runtime.remote_provider_placement import route_remote_provider
from runtime.provider_gateway import build_provider_execution_policy
from runtime.group_provider_adapters import build_group_adapter_resolver
from runtime.remote_provider_adapters import remote_adapter_for
from runtime.workflow_worker import _group_remote_gateway
from runtime.member_execution import build_provider_member_executor
from runtime.trusted_evidence import TrustedEvidenceResolver


def remote_group_fixture(configured, monkeypatch, *, prepare=prepare_remote_fixture, local_for=None):
    engine, root, authority, profile, _ = configured
    monkeypatch.setenv("PX_ENGINE_ROOT",str(engine))
    attachment,group,prepared,plan = prepare(configured)
    from runtime.model_attachment import model_attachment_from_dict
    attachments={row['model_id']:model_attachment_from_dict(row['attachment']) for row in prepared.as_dict()['members']}
    from runtime.remote_model_attachment import RemoteModelAttachment
    placements={model:route_remote_provider(plan.as_dict(),project_root=root,model_id=model) if type(item) is RemoteModelAttachment else local_for(item,plan,None)['placement'] for model,item in attachments.items()}
    claims=tuple(sorted({('execute','runtime'),('write',ROOT+'/gateway/events'),('write',ROOT+'/gateway/budget')} | {('network',item.origin if type(item) is RemoteModelAttachment else 'loopback') for item in attachments.values()}))
    fixture=workflow_group_fixture(root,plan,group,placements=placements,claims=claims)
    budget_path=engine/"registry/provider_budget_policy.json"
    budget=json.loads(budget_path.read_text());budget["budgets"][0]["actor_id"]=fixture["spec"].owner
    # This explicitly admitted disposable policy budgets every real member reservation.
    for field in ("hard_limit_microunits", "max_input_tokens", "max_output_tokens", "max_requests"):
        budget["budgets"][0][field] *= len(attachments)
    budget_path.write_text(json.dumps(budget))
    config={"schema_version":"px.group-provider-adapters/1.0","adapters":{}}
    locals_by_model={item.model_id:local_for(item,plan,fixture) for item in attachments.values() if type(item) is not RemoteModelAttachment}
    for item in attachments.values():
        if item.model_id in locals_by_model: continue
        policy=build_provider_execution_policy(task_plan_sha256=plan.plan_sha256,
            model={"provider_id":item.provider_id,"adapter_id":item.adapter_id,"model_id":item.provider_model_id,
            "model_revision":item.model_revision,"attachment_sha256":item.attachment_sha256,
            "privacy":item.privacy,"authority_class":item.authority_class},
            authority={"revision":item.grant_revision,"provider_effect":True},
            egress={"mode":"allowlist","allowed_destinations":[item.origin]},
            cost={"budget_id":item.budget_id,"max_charge_microunits":100},fallbacks=[],exact_receipt_required=True)
        (root/item.policy_locator).write_text(json.dumps(authority.sign_receipt(policy)))
        config['adapters'][item.model_id]={"kind":"remote_provider","profile_id":item.profile_id,"adapter_id":item.adapter_id,
            "budget_id":item.budget_id,"requester_id":item.requester_id,"attachment_sha256":item.attachment_sha256}
    native=build_group_adapter_resolver(engine,root,config)
    from runtime.remote_provider_profiles import load_profiles
    profiles=load_profiles(root)[1]
    transport=RecordingTransport()
    bindings={}
    for model,item in attachments.items():
        if model in locals_by_model:
            bindings[model]=locals_by_model[model]['binding']
            continue
        native_binding=native(model)
        actual_profile=next(row for row in profiles if row['profile_id']==item.profile_id)
        adapter=remote_adapter_for(actual_profile,credential_resolver=lambda reference:"fixture-credential-never-log",
            validate_current=native_binding.assert_current,transport=transport)
        bindings[model]=replace(native_binding,adapter=adapter)
    binding=bindings[attachment.model_id]
    gateway=_group_remote_gateway(root)
    executor=build_provider_member_executor(gateway=gateway,policy=lambda model:locals_by_model[model]['policy'] if model in locals_by_model else bindings[model].policy,adapter_for=bindings.get,
        project_id=plan.project_id,actor_id=fixture["spec"].owner,accountable_owner=fixture["spec"].owner,
        project_root=root,workflow_effect_receipt=fixture["signed"],workflow_task_plan=plan.as_dict(),
        workflow_agent_spec=fixture["spec"],workflow_placements=placements)
    store=root/"unit-evidence";store.mkdir();trust=root/"unit-trust.json";trust.write_text("{}")
    return {**fixture,"root":root,"plan":plan,"group":group,"binding":binding,"gateway":gateway,
        "executor":executor,"transport":transport,"bindings":bindings,"resolver":TrustedEvidenceResolver(store,trust)}


def test_actual_remote_group_owner_observes_native_provider_effects(configured,monkeypatch):
    f=remote_group_fixture(configured,monkeypatch)
    result=f["controller"].execute_governed_group(f["spec"],task_plan=f["plan"].as_dict(),placements=f["placements"],
        approval=True,member_executor=f["executor"],generation_observer=lambda:f["plan"].context_generation,
        evidence_resolver=f["resolver"],accepted_producers={"unit:producer"},attestation_provider=None,
        workflow_effect_receipt=f["signed"])
    assert result["control_state"]=="succeeded",result["member_failures"]
    assert len(f["transport"].calls)==1
    receipt=next(iter(result["member_receipts"].values()))
    assert "capacity_release" not in receipt["outcome"]
    assert "value" not in receipt["outcome"]["remote_provider_execution"]
    assert receipt["outcome"]["branch_artifact"]
    for effect in f["effects"]:
        assert f["ledger"].fence(effect["idempotency_key"])["disposition"]=="committed"
    assert not all(row["admitted"] for row in result["assessment"]["branch_assessments"])


@pytest.mark.parametrize("field,value",[("origin","https://different.example"),("provider_id","other"),("selected_device","cpu")])
def test_remote_placement_cannot_mutate_service_or_claim_cpu(configured,field,value):
    from runtime.remote_provider_placement import validate_remote_provider_placement
    from runtime.execution_placement import _hash
    _,root,_,_,_=configured
    attachment,_,_,plan=prepare_remote_fixture(configured)
    placement=route_remote_provider(plan.as_dict(),project_root=root,model_id=attachment.model_id)
    placement[field]=value
    placement["placement_sha256"]=_hash({k:v for k,v in placement.items() if k!="placement_sha256"})
    with pytest.raises(ValueError,match="binding differs"):
        validate_remote_provider_placement(placement,plan.as_dict(),project_root=root)


def test_remote_native_workflow_does_not_accept_unobserved_settlement(configured,monkeypatch):
    from runtime.workflow_worker import _verify_group_workflow_effect_receipt
    f=remote_group_fixture(configured,monkeypatch)
    with pytest.raises(PermissionError,match="denominator"):
        _verify_group_workflow_effect_receipt(f["root"],f["signed"],task_plan=f["plan"],spec=f["spec"],
            placements=f["placements"],remote_outcomes={})
    assert f["transport"].calls==[]
    assert all(f["ledger"].fence(row["idempotency_key"])["disposition"]=="in_flight" for row in f["effects"])


def test_group_verifier_does_not_create_missing_native_authority(tmp_path):
    from runtime.workflow_worker import _verify_group_workflow_effect_receipt
    with pytest.raises(FileNotFoundError,match="not been initialized"):
        _verify_group_workflow_effect_receipt(tmp_path,{},task_plan={},spec=None,placements={})
    assert list(tmp_path.iterdir())==[]


def test_unconfigured_mixed_prepared_group_refuses_before_gateway_and_run_creation(configured):
    from tests.test_model_group_preparation import prepared,plan_for
    from runtime.model_group_preparation import prepare_model_group
    from runtime.model_execution_group import ModelExecutionGroup
    from runtime.semantic_integration_types import FusedQueryResult
    from runtime.task_execution_plan import persist_task_execution_plan
    from runtime.agent_runtime import AgentRuntimeController
    from runtime.workflow_worker import _run_model_group
    _,root,_,_,_=configured
    attachment,remote_group,_,_=prepare_remote_fixture(configured)
    local_group,attachments,retrievals,_=prepared(1,root)
    attachments[attachment.model_id]=attachment
    retrievals[attachment.model_id]=FusedQueryResult("map source","px",(),{},0,"fixture:retrieval","b"*64)
    group=ModelExecutionGroup("mixed","execution","owner",local_group.branches+remote_group.branches)
    plan=plan_for(group,prepare_model_group(group,attachments,retrievals,root=root))
    persisted=persist_task_execution_plan(root,plan)
    controller=AgentRuntimeController(root)
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(PermissionError,match="current configured local provider authority is unavailable"):
        controller.execute_governed_group(None,task_plan=plan.as_dict(),placements={},approval=True,
            member_executor=None,generation_observer=None,evidence_resolver=None,accepted_producers=set(),attestation_provider=None)
    with pytest.raises(PermissionError,match="current configured local provider authority is unavailable"):
        _run_model_group(root,{"task_execution_plan":{"path":persisted.relative_to(root).as_posix(),"plan_sha256":plan.plan_sha256}})
    assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob("*") if p.is_file()}
