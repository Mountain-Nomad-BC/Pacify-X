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


def test_group_only_capability_does_not_execute_additional_workflow_nodes(boundary):
    studio, _, reference, selection, calls, owner, definition = boundary
    extra = replace(definition.nodes[0], node_id="node:additional")
    definition = replace(definition, version="1.0.1", nodes=(*definition.nodes, extra))
    studio.save_revision(definition)
    path = next(studio.state_root.glob("*/revisions/1.0.1/record.json"))
    owner.update(version=definition.version, revision_path=path.relative_to(studio.project_root).as_posix(), revision_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    proof = approval_proof(studio.project_root, "remote-model", "chat", selection)
    with pytest.raises(PermissionError, match="single-node"):
        studio.execute_prepared_group_node(reference, approval_capability=proof, selection=selection)
    assert calls == []
