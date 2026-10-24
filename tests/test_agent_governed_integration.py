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
def test_governed_preview_and_execution_resolve_all_brokers_and_cleanup(tmp_path, with_group):
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
    controller = AgentRuntimeController(tmp_path)
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
        acl=("project", spec.owner),
        observed_at=now,
        effective_at=now,
        certification_status="certified",
        retrieval_enabled=True,
        layer="L1",
        visibility="project",
        priority=80,
    )
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
