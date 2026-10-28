"""Exercise the actual external Studio approval boundary, with disposable trust."""
from dataclasses import asdict
import json
import pytest
from runtime.studio_api import studio_operation
from runtime.workflow_studio import WorkflowStudio
from tests.studio_approval_testkit import approval_proof
from tests.test_workflow_studio import fixture


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-keys"))
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.mark.parametrize("operation", ["approve", "run", "start", "cancel"])
@pytest.mark.parametrize("fields", [{"approved_by": "human:vscode-local-user"}, {"approved": True, "approved_by": "human:vscode-local-user"}])
def test_caller_claims_never_reach_workflow_owner(isolated, monkeypatch, operation, fields):
    def forbidden(*args, **kwargs):
        pytest.fail("unsigned request reached workflow owner")
    monkeypatch.setattr("runtime.studio_api.WorkflowStudio", forbidden)
    with pytest.raises(PermissionError):
        studio_operation(isolated, "workflow", operation, fields)


def test_signed_approval_runs_real_nodes_and_cannot_replay(isolated):
    definition, bindings, grants = fixture()
    studio = WorkflowStudio(isolated)
    studio.save_revision(definition)
    studio.register_authority(bindings, grants, {bindings[0].binding_id: "increment", bindings[1].binding_id: "double"})
    studio.validate_and_admit(definition)
    payload = {**json.loads(json.dumps(asdict(definition))), "node_id": "node:two"}
    proof = approval_proof(isolated, "workflow", "approve", payload)
    request = {**payload, "approval_capability": proof}
    result = studio_operation(isolated, "workflow", "approve", request)
    with pytest.raises(PermissionError):
        studio_operation(isolated, "workflow", "approve", request)
    run = {**json.loads(json.dumps(asdict(definition))), "run_inputs": {"node:one.value": 2}, "approvals": {"node:two": result["approval_id"]}}
    receipt = studio_operation(isolated, "workflow", "run", {**run, "approval_capability": approval_proof(isolated, "workflow", "run", run)})
    assert receipt["run_state"] == "succeeded"
    assert receipt["node_count"] == 2
    assert receipt["node_receipts"][1]["approval_execution"]["host_consumed"] is True
    with pytest.raises(PermissionError):
        studio_operation(isolated, "workflow", "run", {**run, "approval_capability": approval_proof(isolated, "workflow", "run", run)})


@pytest.mark.parametrize("mutation", ["payload", "operation", "signature", "project"])
def test_signed_request_binding_denies_tampering(isolated, monkeypatch, mutation):
    payload = {"node_id": "node:two"}
    proof = approval_proof(isolated, "workflow", "approve", payload)
    root, operation = isolated, "approve"
    if mutation == "payload":
        payload = {"node_id": "node:other"}
    elif mutation == "operation":
        operation = "run"
    elif mutation == "signature":
        proof["signature"] = "invalid"
    else:
        root = isolated.parent / "other-project"
        root.mkdir()
    def forbidden(*args, **kwargs):
        pytest.fail("tampered request reached workflow owner")
    monkeypatch.setattr("runtime.studio_api.WorkflowStudio", forbidden)
    with pytest.raises((PermissionError, ValueError, FileNotFoundError)):
        studio_operation(root, "workflow", operation, {**payload, "approval_capability": proof})
