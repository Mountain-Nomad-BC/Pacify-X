from dataclasses import asdict, replace
import hashlib
import json
import pytest
from tests.test_remote_profile_catalog import profile_config
from tests.test_remote_provider_placement import remote_plan
from tests.test_agent_runtime import fixtures
from tests.studio_approval_testkit import approval_proof
from runtime.task_execution_plan import persist_task_execution_plan
from runtime.workflow_studio import WorkflowStudio
from runtime.studio_models import WorkflowNode, WorkflowPort, WorkflowDefinition


@pytest.fixture
def boundary(profile_config, monkeypatch):
    root, *_ = profile_config
    plan, attached = remote_plan(profile_config)
    persist_task_execution_plan(root, plan)
    reference = {"schema_version": "px.prepared-group-reference/1.0", "plan_id": plan.plan_id, "plan_sha256": plan.plan_sha256}
    spec = replace(fixtures("bounded instructions")[0], project_id=plan.project_id)
    config = {"execution_mode": "prepared-model-group", "prepared_group_reference": reference, "agent_spec": json.loads(json.dumps(asdict(spec))), "placements": {attached.model_id: {"model_id": attached.model_id}}}
    node = WorkflowNode("node:group", "binding:group", (), (WorkflowPort("group_run_sha256", "string"), WorkflowPort("control_state", "string")), ("grant:group",), "fail-closed", 30, approval_required=True, config=config)
    definition = WorkflowDefinition("workflow:group", "1.0.0", "fixture-owner", (node,), ())
    studio = WorkflowStudio(root)
    studio.save_revision(definition)
    path = next(studio.state_root.glob("*/revisions/*/record.json"))
    owner = {"workflow_id": definition.workflow_id, "version": definition.version, "node_id": node.node_id, "revision_path": path.relative_to(root).as_posix(), "revision_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    # Isolate capability consumption from currently disabled group registration.
    # This fixture does not claim full owner admission or model operation.
    monkeypatch.setattr(studio, "resolve_prepared_group_owner", lambda value: dict(owner))
    calls = []
    monkeypatch.setattr(studio, "issue_approval", lambda *a, **kwargs: (calls.append(("node-approval", kwargs["approved_by"])) or "controlled-node-approval"))
    monkeypatch.setattr(studio, "execute", lambda *a, **kwargs: (calls.append(("execute", kwargs["approval"])) or {"controlled_boundary": True}))
    selection = {"prepared_group_reference": reference, "profile_id": attached.profile_id, "profile_sha256": attached.profile_sha256, "provider_id": attached.provider_id}
    return studio, plan, reference, selection, calls, owner, definition


def test_signed_operation_is_consumed_once_in_execution_owner(boundary):
    studio, _, reference, selection, calls, *_ = boundary
    proof = approval_proof(studio.project_root, "remote-model", "chat", selection)
    result = studio.execute_prepared_group_node(reference, approval_capability=proof, selection=selection)
    assert result == {"controlled_boundary": True}
    assert calls == [("node-approval", "human:vscode-local-user"), ("execute", True)]
    with pytest.raises(PermissionError):
        studio.execute_prepared_group_node(reference, approval_capability=proof, selection=selection)
    assert len(calls) == 2


def test_caller_identity_string_cannot_authorize_prepared_execution(boundary):
    studio, _, reference, selection, calls, *_ = boundary
    with pytest.raises(TypeError):
        studio.execute_prepared_group_node(reference, approved_by="human:vscode-local-user")
    with pytest.raises(PermissionError):
        studio.execute_prepared_group_node(reference, approval_capability=None, selection=selection)
    assert calls == []


@pytest.mark.parametrize("workflow_scope", [False, True])
def test_group_only_capability_does_not_execute_additional_workflow_nodes(boundary, workflow_scope):
    studio, _, reference, selection, calls, owner, definition = boundary
    extra = replace(definition.nodes[0], node_id="node:additional")
    definition = replace(definition, version="1.0.1", nodes=(*definition.nodes, extra))
    studio.save_revision(definition)
    path = next(studio.state_root.glob("*/revisions/1.0.1/record.json"))
    owner.update(version=definition.version, revision_path=path.relative_to(studio.project_root).as_posix(), revision_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    payload = {"prepared_group_reference": reference} if workflow_scope else selection
    proof = approval_proof(studio.project_root,
        "workflow" if workflow_scope else "remote-model",
        "execute-plan-owner" if workflow_scope else "chat", payload)
    with pytest.raises(PermissionError, match="single-node"):
        studio.execute_prepared_group_node(reference, approval_capability=proof,
            selection=None if workflow_scope else selection)
    assert calls == []


def test_workflow_studio_api_delegates_one_use_capability_to_real_execution_owner(boundary, monkeypatch):
    from runtime import studio_api
    studio, _, reference, _, calls, *_ = boundary
    # Keep real capability verification and the real prepared execution method;
    # only the already-disabled commissioned execution host is controlled.
    monkeypatch.setattr(studio_api, "WorkflowStudio", lambda *a, **kw: studio)
    payload = {"prepared_group_reference": reference}
    proof = approval_proof(studio.project_root, "workflow", "execute-plan-owner", payload)
    request = {**payload, "approval_capability": proof, "approved_by": "forged-client"}
    result = studio_api.studio_operation(studio.project_root, "workflow", "execute-plan-owner", request)
    assert result == {"controlled_boundary": True}
    assert calls == [("node-approval", "human:vscode-local-user"), ("execute", True)]
    with pytest.raises(PermissionError):
        studio_api.studio_operation(studio.project_root, "workflow", "execute-plan-owner", request)
    assert len(calls) == 2


@pytest.mark.parametrize("invalid", ["missing", "remote-scope", "different-plan", "extra-fields"])
def test_workflow_prepared_api_rejects_foreign_or_expanded_authority(boundary, monkeypatch, invalid):
    from runtime import studio_api
    studio, _, reference, selection, calls, *_ = boundary
    monkeypatch.setattr(studio_api, "WorkflowStudio", lambda *a, **kw: studio)
    payload = {"prepared_group_reference": reference}
    approved = payload if invalid != "different-plan" else {
        "prepared_group_reference": {**reference, "plan_sha256": "f" * 64}}
    proof = (approval_proof(studio.project_root, "remote-model", "chat", selection)
             if invalid == "remote-scope" else
             approval_proof(studio.project_root, "workflow", "execute-plan-owner", approved))
    request = {**payload, "approved_by": "human:vscode-local-user", "approved": True}
    if invalid != "missing":
        request["approval_capability"] = proof
    if invalid == "extra-fields":
        request["placements"] = {"unexpected": {}}
    with pytest.raises((PermissionError, ValueError)):
        studio_api.studio_operation(studio.project_root, "workflow", "execute-plan-owner", request)
    assert calls == []


def test_workflow_capability_cannot_be_reused_as_selected_remote_approval(boundary):
    studio, _, reference, selection, calls, *_ = boundary
    proof = approval_proof(studio.project_root, "workflow", "execute-plan-owner",
        {"prepared_group_reference": reference})
    with pytest.raises(PermissionError):
        studio.execute_prepared_group_node(reference, approval_capability=proof, selection=selection)
    assert calls == []


def test_changed_owner_after_signed_workflow_consumption_denies_before_node_approval(boundary, monkeypatch):
    studio, _, reference, _, calls, owner, _ = boundary
    original = studio.authority.consume_host_operation_approval
    def changed_owner(*args, **kwargs):
        result = original(*args, **kwargs)
        owner["revision_sha256"] = "f" * 64
        return result
    monkeypatch.setattr(studio.authority, "consume_host_operation_approval", changed_owner)
    proof = approval_proof(studio.project_root, "workflow", "execute-plan-owner",
        {"prepared_group_reference": reference})
    with pytest.raises(PermissionError, match="owner changed"):
        studio.execute_prepared_group_node(reference, approval_capability=proof)
    assert calls == []


@pytest.mark.parametrize("tamper", ["signature", "operation", "replay"])
def test_prepared_api_rejects_bad_proof_before_workflow_initialization(boundary, monkeypatch, tamper):
    from runtime import studio_api
    studio, _, reference, _, _, *_ = boundary
    payload = {"prepared_group_reference": reference}
    proof = approval_proof(studio.project_root, "workflow", "execute-plan-owner", payload)
    if tamper == "signature":
        proof["signature"] = "invalid"
    elif tamper == "operation":
        proof["claim"]["operation"] = "run"
    else:
        studio.authority.consume_host_operation_approval(proof, kind="workflow",
            operation="execute-plan-owner", supplied_payload=payload)
    def forbidden(*args, **kwargs):
        pytest.fail("unverified or replayed capability initialized a workflow owner")
    monkeypatch.setattr(studio_api, "WorkflowStudio", forbidden)
    with pytest.raises(PermissionError):
        studio_api.studio_operation(studio.project_root, "workflow", "execute-plan-owner",
            {**payload, "approval_capability": proof})



def test_capability_preflight_is_read_only_and_does_not_consume_the_effect(boundary):
    from runtime.studio_authority import StudioAuthorityStore
    studio, _, reference, _, calls, *_ = boundary
    payload = {"prepared_group_reference": reference}
    proof = approval_proof(studio.project_root, "workflow", "execute-plan-owner", payload)
    existing = StudioAuthorityStore.open_existing(studio.project_root)
    def snapshot():
        return {p.relative_to(studio.project_root).as_posix(): p.read_bytes()
                for p in studio.project_root.rglob("*") if p.is_file()}
    before = snapshot()
    for _ in range(2):
        verified = existing.verify_host_operation_approval(proof, kind="workflow",
            operation="execute-plan-owner", supplied_payload=payload)
        assert verified["approved_by"] == "human:vscode-local-user"
    assert snapshot() == before
    consumed = studio.authority.consume_host_operation_approval(proof, kind="workflow",
        operation="execute-plan-owner", supplied_payload=payload)
    assert consumed["payload"] == payload
    with pytest.raises(PermissionError, match="replay"):
        existing.verify_host_operation_approval(proof, kind="workflow",
            operation="execute-plan-owner", supplied_payload=payload)
    assert calls == []
