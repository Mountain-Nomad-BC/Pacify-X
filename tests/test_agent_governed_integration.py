from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from runtime.agent_handoff import acknowledge_handoff, create_handoff_packet
from runtime.agent_runtime import AgentRuntimeController
from runtime.capability_routing import route_task
from runtime.execution_placement import PlacementCapacityLedger, route_hardware
from runtime.hardware_routing import (
    BenchmarkEvidence,
    HardwareProfile,
    WorkloadKind,
    WorkloadProfile,
)
from runtime.memory_broker import build_memory_query_plan
from runtime.memory_fabric import MemoryRecord
from runtime.memory_vault import MemoryVault
from runtime.model_attachment import build_model_attachment
from runtime.skill_navigator import CapabilitySummary
from runtime.studio_models import AgentSpec, CapabilityBinding, EffectGrant
from runtime.task_execution_plan import compile_task_execution_plan


def test_live_agent_refuses_stale_generation_before_reservation_or_callbacks(tmp_path, monkeypatch):
    from runtime.agent_runtime import execute_agent_plan
    from runtime.context_generation import ALL_COMPONENTS, context_vector
    from runtime.execution_placement import _hash
    original = _plan(tmp_path, "b" * 64)
    route = route_task("review bounded evidence", {"skills": (
        CapabilitySummary("review", "review bounded evidence"),)})
    components = {**dict.fromkeys(ALL_COMPONENTS, "test-fixture-only"),
                  "source_revision": "source-1"}
    current = context_vector("project:demo", "scope", components)
    plan = compile_task_execution_plan(route, project_id="project:demo", source_revision="source-1",
        projection_revisions={"semantic": "revision"}, effect_budget=("read",),
        authority_bindings=("binding:agent-search",), model_attachment=original.model_attachment,
        model_ranking_receipt=original.model_ranking_receipt, context_generation=current,
        created_utc="2026-10-04T00:00:00Z")
    placement = {"task_plan_sha256": plan.plan_sha256,
                 "model_attachment_sha256": original.model_attachment["attachment_sha256"],
                 "selected_device": "cpu", "fallback": {"device": "cpu"}, "reason": "fixture"}
    placement["placement_sha256"] = _hash(placement)
    calls = []
    def reserve(self, value, *, run_id):
        calls.append("reserve")
        return {"reservation_sha256": "a" * 64}
    def release(self, value, *, outcome_sha256):
        calls.append("release")
        return {"released": True}
    monkeypatch.setattr(PlacementCapacityLedger, "reserve", reserve)
    monkeypatch.setattr(PlacementCapacityLedger, "release", release)
    stale = context_vector("project:demo", "scope", {**components, "network_policy_revision": "changed"})
    kwargs = dict(run_id="run", gpu_fn=lambda batch: calls.append("gpu"),
                  cpu_fn=lambda: calls.append("cpu"))
    with pytest.raises(ValueError, match="blocked"):
        execute_agent_plan(tmp_path, plan.as_dict(), placement, current_context_generation=stale, **kwargs)
    assert calls == []
    controller = AgentRuntimeController(tmp_path)
    with pytest.raises(ValueError, match="blocked"):
        controller.execute_governed_plan(None, task_plan=plan.as_dict(), placement=placement,
            approval=True, gpu_fn=kwargs["gpu_fn"], cpu_fn=kwargs["cpu_fn"],
            current_context_generation=stale)
    assert calls == []
    value, outcome = execute_agent_plan(tmp_path, plan.as_dict(), placement,
        current_context_generation=current, **kwargs)
    assert calls == ["reserve", "cpu", "release"]
    assert outcome["capacity_release"]["released"]


def _agent(body: str):
    grant = EffectGrant(
        "grant:agent-read",
        "agent:demo",
        ("read",),
        ("workspace:demo",),
        "human:owner",
        ("receipt:grant",),
        state="admitted",
    )
    binding = CapabilityBinding(
        "binding:agent-search",
        "agent",
        "agent:demo",
        "capability:search",
        "1.0.0",
        (grant.grant_id,),
        None,
        "non-billable",
        "deny",
        "admitted",
        ("receipt:binding",),
    )
    import hashlib

    spec = AgentSpec(
        "agent:demo",
        "1.0.0",
        "project:demo",
        "human:owner",
        "harness:px",
        hashlib.sha256(body.encode()).hexdigest(),
        (binding.binding_id,),
        (grant.grant_id,),
        ("identity", "sandbox"),
        memory_binding_ids=("memory:one",),
        handoff_agent_ids=("agent:prior",),
    )
    return spec, binding, grant


def _plan(root: Path, benchmark_revision: str):
    attachment = build_model_attachment(
        root,
        model_id="local-policy/model",
        model_revision="exact-1",
        artifact_sha256="e" * 64,
        runtime="provider-gateway",
        context_tokens=4096,
        modalities=("text",),
        supports_tools=False,
        privacy="local",
        authority_class="contained",
        benchmark_revision=benchmark_revision,
        hardware_requirements={"memory": "1GiB"},
    )
    route = route_task(
        "review bounded evidence",
        {
            "skills": (
                CapabilitySummary("review", "review bounded evidence"),
            )
        },
    )
    return compile_task_execution_plan(
        route,
        project_id="project:demo",
        source_revision="source-1",
        projection_revisions={"model_attachment": attachment.attachment_sha256},
        effect_budget=("read",),
        authority_bindings=("binding:agent-search",),
        model_attachment=attachment.as_dict(),
        model_ranking_receipt={
            "selected_attachment_sha256": attachment.attachment_sha256
        },
        created_utc="2026-09-05T00:00:00Z",
    )


@pytest.mark.parametrize("with_group", [False, True])
@pytest.mark.parametrize("memory_case", ["current", "missing-owner", "stale-source", "stale-dependencies", "forged-records", "actor-mismatch", "subject-mismatch"])
def test_governed_preview_and_execution_resolve_all_brokers_and_cleanup(tmp_path, with_group, memory_case):
    now = datetime.now(timezone.utc)
    workload = WorkloadProfile(
        WorkloadKind.TEXT_ANALYSIS,
        5,
        1024,
        False,
        operation_id="agent-governed",
    )
    hardware = HardwareProfile(
        False,
        None,
        None,
        None,
        0,
        0,
        16 * 1024**3,
        "windows",
        8,
        4,
        False,
        (),
        (),
        cuda_executor_available=False,
    )
    benchmark = BenchmarkEvidence(
        workload.operation_id,
        hardware.fingerprint,
        2.0,
        1.0,
        True,
        0,
        now.isoformat(),
        workload_fingerprint=workload.fingerprint,
    )
    plan = _plan(tmp_path, benchmark.revision)
    current_generation = None
    if with_group:
        from runtime.model_attachment import model_attachment_from_dict
        from runtime.model_execution_group import BranchAssignment, RoleWorkContract, IndependenceContract, ModelExecutionGroup
        from runtime.model_group_preparation import context_for_branch, context_sha256, prepare_model_group
        from runtime.semantic_integration_types import FusedQueryResult
        from runtime.context_generation import ALL_COMPONENTS, context_vector
        from dataclasses import replace
        primary = model_attachment_from_dict(plan.model_attachment)
        members, exact, retrievals = [], {}, {}
        for i, model in enumerate((primary.model_id, "fixture:model-1", "fixture:model-2")):
            branch = BranchAssignment(model, "proposal", work_contract=RoleWorkContract("answer", "a" * 64),
                independence_contract=IndependenceContract(), agent_generation_id=f"fixture-generation-{i}")
            retrieval = FusedQueryResult("review bounded evidence", "project:demo", (), {}, 0,
                "fixture:retrieval", "b" * 64)
            context = context_for_branch(retrieval, branch)
            branch = replace(branch, work_contract=RoleWorkContract("answer", context_sha256(context)))
            members.append(branch)
            retrievals[model] = retrieval
            exact[model] = primary if i == 0 else build_model_attachment(tmp_path,
                model_id=model, model_revision="fixture-exact", artifact_sha256="e" * 64,
                runtime="provider-gateway", context_tokens=4096, modalities=("text",), supports_tools=False,
                privacy="local", authority_class="contained", benchmark_revision=benchmark.revision,
                hardware_requirements={"memory": "1GiB"})
        group = ModelExecutionGroup("fixture-group", "execution", "human:owner", tuple(members), quorum="majority")
        preparation = prepare_model_group(group, exact, retrievals, root=tmp_path)
        current_generation = context_vector("project:demo", "scope", {**dict.fromkeys(ALL_COMPONENTS, "test-fixture-only"),
            "source_revision": "source-1", "model_execution_group_revision": group.group_sha256,
            "model_contract_set_revision": group.contract_set_sha256})
        route = route_task("review bounded evidence", {"skills": (CapabilitySummary("review", "review bounded evidence"),)})
        plan = compile_task_execution_plan(route, project_id="project:demo", source_revision="source-1",
            projection_revisions={"semantic": "revision"}, effect_budget=("read",), authority_bindings=("binding:agent-search",),
            model_attachment=primary.as_dict(), model_ranking_receipt=plan.model_ranking_receipt,
            model_execution_group=group, model_group_preparation=preparation, context_generation=current_generation,
            created_utc="2026-10-04T00:00:00Z")
    plan_dict = plan.as_dict()
    placement = route_hardware(
        plan_dict,
        workload=workload,
        hardware=hardware,
        benchmark=benchmark,
        project_root=tmp_path,
        model_id="fixture:model-2" if with_group else None,
    )

    body = "Use only brokered context and Studio-admitted effects.\n"
    spec, binding, grant = _agent(body)
    vault = MemoryVault(tmp_path / 'canonical-memory', workspace_id='workspace', project_id=spec.project_id)
    controller = AgentRuntimeController(tmp_path, **({} if memory_case == 'missing-owner' else {'memory_vault': vault}))
    controller.create_candidate(spec, body)
    assert controller.test_candidate(spec)["passed"] is True
    controller.register_authority([binding], [grant])
    admission = controller.admit(spec)
    receiver_revision = str(admission["agent_revision_sha256"])

    memory_plan = build_memory_query_plan(
        project_id=spec.project_id,
        subject_id=plan.plan_id,
        actor_id=spec.owner,
        agent_id=spec.agent_id,
        binding_ids=spec.memory_binding_ids,
        memory_classes=("decision",),
        tiers=("L1",),
        max_items=2,
        max_bytes=4096,
        max_tokens=1024,
        trust_floor=0.8,
        max_age_seconds=3600,
        conflict_policy="quarantine",
        provenance_required=True,
        writeback_policy="deny",
        source_revision="source-1",
        dependency_revisions={"memory": "revision-1"},
    )
    record = MemoryRecord(
        memory_id="memory:one",
        workspace_id="workspace",
        project_id=spec.project_id,
        owner_id=spec.owner,
        session_id="session",
        lease_id="lease",
        title="Decision",
        memory_type="decision",
        summary="Use bounded proof",
        source_artifact="evidence.json",
        source_sha256="a" * 64,
        evidence_locator="evidence:one",
        epistemic_status="observation",
        confidence=0.9,
        confidence_method="direct",
        classification="internal",
        acl=("project", spec.owner, "foreign-actor"),
        observed_at=now,
        effective_at=now,
        certification_status="certified",
        retrieval_enabled=True,
        layer="L1",
        visibility="project",
        priority=80,
    )
    if memory_case != 'missing-owner':
        vault.append(record)
        revisions = vault.query_revisions()
        parameters = memory_plan.as_dict()
        for key in ('schema_version', 'plan_id', 'plan_sha256'):
            parameters.pop(key)
        parameters['source_revision'] = 'stale-source' if memory_case == 'stale-source' else revisions['source_revision']
        parameters['dependency_revisions'] = {'memory': 'stale'} if memory_case == 'stale-dependencies' else revisions['dependency_revisions']
        if memory_case == 'actor-mismatch':
            parameters['actor_id'] = 'foreign-actor'
        if memory_case == 'subject-mismatch':
            parameters['subject_id'] = 'foreign-task'
        memory_plan = build_memory_query_plan(**parameters)
    if memory_case == 'forged-records':
        from dataclasses import replace
        record = replace(record, summary='unverified substituted content')
    packet = create_handoff_packet(
        project_id=spec.project_id,
        task_plan_id=plan.plan_id,
        task_plan_revision=plan.plan_sha256,
        run_id="prior-run",
        sender_agent_id="agent:prior",
        sender_revision="c" * 64,
        receiver_agent_id=spec.agent_id,
        receiver_revision=receiver_revision,
        evidence=({"ref": "evidence:one", "sha256": "a" * 64, "revision": "r1"},),
        hypotheses=("bounded",),
        open_questions=(),
        authority=("read",),
        sender_authority=("read",),
        budgets={"tool_calls": 1},
        memory_query_plan_sha256=memory_plan.plan_sha256,
        created_utc=now.isoformat(),
        expires_utc=(now + timedelta(hours=1)).isoformat(),
    )
    ack = acknowledge_handoff(
        packet,
        decision="accept",
        reason="verified",
        receiver_agent_id=spec.agent_id,
        receiver_revision=receiver_revision,
        acknowledged_utc=now.isoformat(),
    )
    validation = {
        "expected_project_id": spec.project_id,
        "receiver_agent_id": spec.agent_id,
        "receiver_revision": receiver_revision,
        "current_evidence_revisions": {"evidence:one": "r1"},
        "now_utc": now.isoformat(),
    }
    handoff = {
        "packet": packet,
        "acknowledgment": ack,
        "validation_context": validation,
    }

    assert controller.preview(spec)["eligible"] is False
    preview = controller.preview_governed(
        spec,
        task_plan=plan_dict,
        placement=placement,
        memory_query_plan=memory_plan,
        memory_records=(record,),
        handoff_inputs=(handoff,),
        memory_now_utc=now,
        current_context_generation=current_generation,
    )
    if memory_case != 'current':
        assert preview['eligible'] is False
        assert 'memory_bindings_not_runtime_resolved' in preview['blockers']
        callbacks = []
        with pytest.raises(PermissionError):
            controller.execute_governed_plan(
                spec, task_plan=plan_dict, placement=placement, approval=True,
                gpu_fn=lambda _: callbacks.append('gpu'), cpu_fn=lambda: callbacks.append('cpu'),
                member_executor=lambda *args, **kwargs: callbacks.append('member'),
                memory_query_plan=memory_plan, memory_records=(record,),
                handoff_inputs=(handoff,), memory_now_utc=now,
                current_context_generation=current_generation,
            )
        assert callbacks == []
        return
    assert preview["eligible"] is True
    assert preview["memory_context_receipt_sha256"]
    assert preview["handoff_packet_sha256"] == [packet.packet_sha256]

    receipt = controller.execute_governed_plan(
        spec,
        task_plan=plan_dict,
        placement=placement,
        approval=True,
        gpu_fn=lambda _batch: "gpu",
        cpu_fn=lambda: {"answer": "bounded"},
        member_executor=(lambda invocation, **placement: {"answer": "bounded", "member": invocation.model_id}) if plan_dict.get("model_execution_group") else None,
        memory_query_plan=memory_plan,
        memory_records=(record,),
        handoff_inputs=(handoff,),
        memory_now_utc=now,
        current_context_generation=current_generation,
    )
    assert receipt["effects_studio_admitted"] is True
    assert receipt["outcome"]["capacity_release"]["released"] is True
    assert controller.session_status(receipt["run_id"])["state"] == "succeeded"
    assert PlacementCapacityLedger(tmp_path)._read()["active"] == {}

    blocked = controller.preview_governed(
        spec,
        task_plan=plan_dict,
        placement=placement,
        memory_query_plan=memory_plan,
        memory_records=(record,),
        handoff_inputs=({**handoff, "acknowledgment": None},),
        memory_now_utc=now,
        current_context_generation=current_generation,
    )
    assert blocked["eligible"] is False
    assert "handoff_agents_not_runtime_resolved" in blocked["blockers"]


from runtime.cancellation_scope import build_scope, resolve_control, CancellationScopeError

@pytest.mark.parametrize('state,target',[('cancelled','cancelled'),('paused','paused')])
def test_stable_child_control_reaches_running_root_and_sibling(state,target):
    scope=build_scope('scope','project','root',('child','sibling'))
    result=resolve_control(scope,{'root':'running','child':state,'sibling':'running'})
    assert result['requested_control']==target
    assert result['adopt']=={'root':target,'sibling':target}
    assert 'child' not in result['adopt']
    assert result['authority_granted'] is False

def test_cancelled_child_outranks_other_child_pause_request():
    scope=build_scope('scope','project','root',('cancelled-child','pausing-child'))
    result=resolve_control(scope,{'root':'running','cancelled-child':'cancelled','pausing-child':'pause_requested'})
    assert result['requested_control']=='cancelled'
    assert result['adopt']=={'root':'cancelled','pausing-child':'cancelled'}

@pytest.mark.parametrize('state,target',[('cancel_requested','cancelled'),('interrupted','cancelled'),('pause_requested','paused')])
def test_requested_controls_keep_existing_positive_path(state,target):
    scope=build_scope('scope','project','root',('child',))
    result=resolve_control(scope,{'root':'running','child':state})
    assert result['requested_control']==target
    assert result['adopt']['root']==target

def test_cancelled_root_is_never_resurrected_by_child_pause():
    scope=build_scope('scope','project','root',('child',))
    result=resolve_control(scope,{'root':'cancelled','child':'pause_requested'})
    assert 'root' not in result['adopt']
    assert 'root' in result['terminal_members']

def test_no_requested_control_keeps_running_members_unchanged():
    scope=build_scope('scope','project','root',('child',))
    result=resolve_control(scope,{'root':'running','child':'running'})
    assert result['requested_control'] is None and result['adopt']=={}

def test_expired_deadline_cancels_running_members():
    scope=build_scope('scope','project','root',('child',))
    result=resolve_control(scope,{'root':'running','child':'running'},now_utc='2026-11-16T12:00:00Z',deadline_utc='2026-11-16T11:59:59Z')
    assert result['adopt']=={'root':'cancelled','child':'cancelled'}
    assert result['deadline_expired'] is True

def test_foreign_scope_member_cannot_inject_control():
    scope=build_scope('scope','project','root',('child',))
    with pytest.raises(CancellationScopeError,match='exact scope membership'):
        resolve_control(scope,{'root':'running','child':'running','foreign':'cancelled'})


@pytest.mark.parametrize('terminal_child',['cancelled','paused','failed','corrupt',None])
def test_live_group_owner_adopts_already_terminal_child(tmp_path,monkeypatch,terminal_child):
    from dataclasses import replace
    from datetime import datetime,timezone
    import pytest
    from runtime.agent_runtime import AgentRuntimeController
    from runtime.model_attachment import build_model_attachment
    from runtime.model_group_preparation import prepare_model_group
    from runtime.execution_placement import route_hardware,PlacementCapacityLedger
    from runtime.hardware_routing import WorkloadProfile,WorkloadKind,HardwareProfile,BenchmarkEvidence
    from runtime.trusted_evidence import TrustedEvidenceResolver
    from tests.test_model_group_preparation import prepared,plan_for
    from tests.test_agent_runtime import fixtures

    root=tmp_path/'project';root.mkdir()
    monkeypatch.setenv('PX_STUDIO_KEY_ROOT',str(tmp_path/'fixture-authority-keys'))
    group,attachments,retrievals,_=prepared(2,root)
    workload=WorkloadProfile(WorkloadKind.TEXT_ANALYSIS,5,1024,False,operation_id='studio-prepared-member')
    hardware=HardwareProfile(False,None,None,None,0,0,16*1024**3,'windows',8,4,False,(),(),cuda_executor_available=False)
    benchmark=BenchmarkEvidence(workload.operation_id,hardware.fingerprint,2.0,1.0,True,0,datetime.now(timezone.utc).isoformat(),workload_fingerprint=workload.fingerprint)
    for model,old in tuple(attachments.items()):
        attachments[model]=build_model_attachment(root,model_id=old.model_id,model_revision=old.model_revision,artifact_sha256=old.artifact_sha256,runtime=old.runtime,context_tokens=old.context_tokens,modalities=old.modalities,supports_tools=False,privacy=old.privacy,authority_class=old.authority_class,benchmark_revision=benchmark.revision,hardware_requirements=dict(old.hardware_requirements))
    preparation=prepare_model_group(group,attachments,retrievals,root=root);plan=plan_for(group,preparation)
    placements={model:route_hardware(plan.as_dict(),model_id=model,workload=workload,hardware=hardware,benchmark=benchmark,project_root=root) for model in group.model_ids}
    body='Use only the prepared member context.';spec,binding,grant=fixtures(body);spec=replace(spec,project_id=plan.project_id)
    controller=AgentRuntimeController(root);controller.create_candidate(spec,body)
    assert controller.test_candidate(spec)['passed'] is True
    controller.register_authority([binding],[grant]);assert controller.admit(spec)['decision']=='admitted'
    store=root/'evidence-store';store.mkdir();policy=root/'trust-policy.json';policy.write_text('{}',encoding='utf-8')
    seen=[];member_ids=[];injected=[];root_ids=[]
    def execute(invocation,**kwargs):
        seen.append(invocation.model_id);member_ids.append(kwargs['execution_context'].execution_id);root_ids.append(kwargs['execution_context'].root_execution_id)
        return {'answer':'bounded real prepared member'}
    original_release=PlacementCapacityLedger.release
    def release_then_request(self,reservation,*,outcome_sha256):
        result=original_release(self,reservation,outcome_sha256=outcome_sha256)
        if terminal_child in {'cancelled','paused','failed'} and not injected:
            request='failed' if terminal_child=='failed' else 'cancel_requested' if terminal_child=='cancelled' else 'pause_requested'
            state=controller.run_control.transition(member_ids[-1],request,actor=spec.owner,approved=True,operation='fixture.external-control-after-native-capacity-release')
            injected.append(state['run_id'])
        return result
    monkeypatch.setattr(PlacementCapacityLedger,'release',release_then_request)
    def corrupt_member_custody(model, artifact):
        if not injected:
            assert PlacementCapacityLedger(root)._read()['active']=={}
            (controller.run_control.root/member_ids[-1]/'head.json').write_text('{}',encoding='utf-8')
            injected.append(member_ids[-1])
        return None # No independent evidence or approval manufactured.
    def execute_group():
        return controller.execute_governed_group(spec,task_plan=plan.as_dict(),placements=placements,approval=True,member_executor=execute,generation_observer=lambda:plan.context_generation,evidence_resolver=TrustedEvidenceResolver(store,policy),accepted_producers=set(),attestation_provider=corrupt_member_custody if terminal_child=='corrupt' else None)
    if terminal_child=='corrupt':
        with pytest.raises(PermissionError):
            execute_group()
        assert seen==[group.model_ids[0]], 'Unreadable member custody must halt sibling dispatch'
        assert PlacementCapacityLedger(root)._read()['active']=={}
        reopened=AgentRuntimeController(root)
        assert reopened.run_control.read(root_ids[0])['state']=='failed'
        return
    result=execute_group()
    assert PlacementCapacityLedger(root)._read()['active']=={}
    if terminal_child:
        assert injected and controller.run_control.read(injected[0])['state']==terminal_child
    print({'terminal_child':terminal_child,'root_state':result['control_state'],'seen':seen,'member_states':[controller.run_control.read(x)['state'] for x in member_ids],'released_capacity':True})
    if terminal_child:
        assert result['control_state']==terminal_child,'Group root ignored already-terminal native child'
        assert seen==[group.model_ids[0]],'Sibling dispatched after child scope halt'
        assert result['member_failures'][group.model_ids[1]]['state']=='not_admitted'
        reopened=AgentRuntimeController(root)
        assert reopened.run_control.read(result['group_run_id'])['state']==terminal_child
    else:
        assert seen==list(group.model_ids)
        assert result['control_state']=='failed' # No independent attestation manufactured.
        assert all(controller.run_control.read(x)['state']=='succeeded' for x in member_ids)


@pytest.mark.parametrize("state", ["queued", "running", "pause_requested", "paused", "cancel_requested", "finalizing", "cancelled", "succeeded", "failed", "interrupted"])
def test_scope_classifies_every_canonical_durable_state(state):
    from runtime.studio_run_control import RUN_STATES
    assert state in RUN_STATES
    result = resolve_control(build_scope("scope", "project", "root", ("child",)), {"root": "running", "child": state})
    expected = {"pause_requested": "paused", "paused": "paused", "cancel_requested": "cancelled", "cancelled": "cancelled", "failed": "failed", "interrupted": "cancelled"}.get(state)
    assert result["requested_control"] == expected
    assert result["adopt"].get("root") == expected
    if state in {"succeeded", "failed", "cancelled"}:
        assert "child" in result["terminal_members"]
        assert "child" not in result["adopt"]

@pytest.mark.parametrize("other,expected", [("paused", "failed"), ("pause_requested", "failed"), ("cancelled", "cancelled"), ("interrupted", "cancelled")])
def test_scope_failure_has_one_canonical_precedence(other, expected):
    result = resolve_control(build_scope("scope", "project", "root", ("failed", "other")), {"root": "running", "failed": "failed", "other": other})
    assert result["requested_control"] == expected
    assert result["adopt"]["root"] == expected
    assert "failed" not in result["adopt"]

@pytest.mark.parametrize("terminal", ["failed", "succeeded", "cancelled"])
def test_scope_never_resurrects_any_terminal_root(terminal):
    result = resolve_control(build_scope("scope", "project", "root", ("child",)), {"root": terminal, "child": "pause_requested"})
    assert "root" not in result["adopt"]
    assert "root" in result["terminal_members"]

def test_scope_reports_paused_failure_adoption_as_blocked_without_resuming():
    result = resolve_control(build_scope("scope", "project", "root", ("failed", "paused")), {"root": "running", "failed": "failed", "paused": "paused"})
    assert result["requested_control"] == "failed"
    assert result["adopt"] == {"root": "failed"}
    assert result["blocked_adoptions"] == {"paused": "failed"}

@pytest.mark.parametrize("malformed", [None, True, [], {}, "fictional"])
def test_scope_rejects_malformed_durable_state(malformed):
    with pytest.raises(CancellationScopeError):
        resolve_control(build_scope("scope", "project", "root", ("child",)), {"root": "running", "child": malformed})
