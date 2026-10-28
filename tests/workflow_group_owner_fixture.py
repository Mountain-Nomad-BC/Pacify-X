"""Actual native group owner fixtures; in-process member work, no model operations."""
import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from runtime.agent_runtime import AgentRuntimeController
from runtime.studio_models import CapabilityBinding, EffectGrant, digest
from runtime.effect_intent import EffectIntentLedger
from runtime.scope_lease import ScopeLeaseStore
from runtime.execution_context import ExecutionContext
from runtime.studio_run_control import DurableRunControl
from runtime.studio_authority import StudioAuthorityStore
from runtime.execution_placement import _hash
from runtime.model_group_preparation import member_attachment
from tests.test_agent_governed_integration import _agent

def workflow_group_fixture(tmp_path, plan, group, *, placements=None, claims=(("execute","runtime"),)):
    body = "Use native bounded context only.\n"
    spec, agent_binding, agent_grant = _agent(body)
    spec = replace(spec, project_id=plan.project_id, memory_binding_ids=(), handoff_agent_ids=())
    controller = AgentRuntimeController(tmp_path)
    controller.create_candidate(spec, body)
    assert controller.test_candidate(spec)["passed"]
    controller.register_authority([agent_binding], [agent_grant])
    controller.admit(spec)
    if placements is None:
        placements = {}
    for model in (() if placements else group.model_ids):
        attachment, member = member_attachment(plan.as_dict(), model)
        placement = {"task_plan_sha256": plan.plan_sha256, "model_id": model,
            "model_attachment_sha256": attachment["attachment_sha256"],
            "context_sha256": member["context_sha256"], "selected_device": "cpu",
            "fallback": {"device": "cpu"}, "reason": "in-process native-owner unit fixture",
            "reservation_required": True, "required_capacity_bytes": 1024**3,
            "available_capacity_bytes": 16*1024**3, "hardware_fingerprint": "unit:in-process-cpu"}
        placement["placement_sha256"] = _hash(placement)
        placements[model] = placement
    authority = StudioAuthorityStore(tmp_path)
    grants = tuple(EffectGrant("grant:workflow-effect:"+str(i), "workflow:effect", (effect,), (scope,),
        "human:owner", ("unit:workflow-exact-effect",), state="admitted") for i,(effect,scope) in enumerate(claims))
    binding = CapabilityBinding("binding:workflow-group", "workflow", "workflow:effect", "capability:group", "1.0.0",
        tuple(grant.grant_id for grant in grants), None, "non-billable", "deny", "admitted", ("unit:workflow-group",))
    authority.register_authority_transaction((binding,), grants, {binding.binding_id: "model-group"})
    hashes = {"executor:"+binding.binding_id: authority.resolve_executor(binding.binding_id)[1],
        "binding:"+binding.binding_id: authority.resolve_binding(binding.binding_id, subject_kind="workflow", subject_id="workflow:effect")[1],
        **{"grant:"+grant.grant_id: authority.resolve_grant(grant.grant_id, subject_id="workflow:effect")[1] for grant in grants}}
    control = DurableRunControl(tmp_path, tmp_path / ".agentic_engineering_os_px/studios/workflows/sessions")
    run = control.create(kind="workflow", subject_id="workflow:effect", version="1.0.0",
        owner="human:owner", revision_sha256="a"*64, request_sha256="b"*64)
    run = control.transition(run["run_id"], "running", actor="human:owner", approved=True)
    run_id = run["run_id"]
    expiry = (datetime.now(timezone.utc)+timedelta(seconds=180)).isoformat()
    context = ExecutionContext(execution_id="workflow-node-"+hashlib.sha256(f"{run_id}\0node:group\0{1}\0{1}".encode()).hexdigest()[:40],
        parent_execution_id=run_id, root_execution_id=run_id, project_id="workflow:effect",
        session_id=run_id, revision=run["sequence"], epoch=1, generation_vector_sha256=None,
        authority_reference_sha256=digest(hashes), effect_budget_sha256="c"*64,
        cancellation_scope_id=run_id, deadline_utc=expiry, actor_id="human:owner", provider_id=None,
        trace_root_id=run_id, workflow_adapter_revision="d"*64)
    ledger = EffectIntentLedger(tmp_path)
    effects = []
    for effect_name,scope in claims:
        effect = {"idempotency_key": "workflow-node-effect:"+digest({"run_id":run_id,"node_id":"node:group","effect":effect_name,"scope":scope}),
            "execution_id": "workflow-effect-"+digest({"run_id":run_id,"node_id":"node:group","workflow_version":"1.0.0","authority":hashes})[:40],
            "effect":effect_name, "scopes":[scope]}
        ledger.intend(**effect)
        effect["lease_id"] = "lease:workflow-group:"+str(len(effects))
        ScopeLeaseStore(tmp_path).acquire(lease_id=effect["lease_id"], execution_id=effect["execution_id"],
            effect=effect_name, scopes=[scope], reason="actual owner unit fixture", expires_utc=expiry)
        effects.append(effect)
    effect = effects[0]
    task = {"schema_version":"px.workflow-node-task/1.0", "adapter_id":"model-group",
        "run_id":run_id, "node_id":"node:group", "attempt":1, "workflow_id":"workflow:effect",
        "executor_binding_id":binding.binding_id, "effect_grant_ids":[grant.grant_id for grant in grants],
        "authority_record_hashes":hashes, "execution_context":context.as_dict(),
        "prepared_effect_intents":effects, "task_execution_plan":{"plan_sha256":plan.plan_sha256},
        "node_config":{"execution_mode":"prepared-model-group", "prepared_group_reference":{
            "schema_version":"px.prepared-group-reference/1.0", "plan_id":plan.plan_id,"plan_sha256":plan.plan_sha256},
            "agent_spec":json.loads(json.dumps(asdict(spec))), "placements":placements}}
    signed = authority.sign_receipt(task)
    return {key:value for key,value in locals().items() if key in ("spec","controller","placements","authority","control","run_id","context","ledger","effects","effect","signed","task")}
