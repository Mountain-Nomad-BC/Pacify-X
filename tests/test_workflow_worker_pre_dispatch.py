import json
import sys
import pytest
from runtime.studio_authority import StudioAuthorityStore
from runtime.studio_models import write_json_atomic
from runtime import workflow_worker
from tests.test_workflow_studio import fixture


@pytest.mark.parametrize("invalid", ["config", "kind", "approval"])
def test_signed_invalid_task_never_invokes_adapter(tmp_path, monkeypatch, invalid):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "keys"))
    definition, bindings, grants = fixture()
    authority = StudioAuthorityStore(root)
    authority.register_authority_transaction(bindings, grants, {bindings[0].binding_id: "sleep"})
    binding = bindings[0].binding_id
    hashes = {}
    _, hashes[f"binding:{binding}"] = authority.resolve_binding(binding, subject_kind="workflow", subject_id=definition.workflow_id)
    _, hashes[f"executor:{binding}"] = authority.resolve_executor(binding)
    _, hashes[f"grant:{grants[0].grant_id}"] = authority.resolve_grant(grants[0].grant_id, subject_id=definition.workflow_id)
    task = {"schema_version": "px.workflow-node-task/1.0", "workflow_id": definition.workflow_id,
            "node_id": "node:one", "attempt": 1, "adapter_id": "sleep", "executor_binding_id": binding,
            "authority_record_hashes": hashes, "effect_grant_ids": [grants[0].grant_id],
            "inputs": {"seconds": 0}, "node_kind": "task", "node_config": {},
            "approval_required": False, "approval_execution": {}}
    if invalid == "config":
        task["node_config"] = {"approved_by": "human:vscode-local-user"}
    elif invalid == "kind":
        task["node_kind"] = "unadmitted"
    else:
        task["approval_required"] = True
    path = root / "signed-task.json"
    write_json_atomic(path, authority.sign_receipt(task))
    calls = []
    monkeypatch.setattr(workflow_worker.time, "sleep", lambda seconds: calls.append(seconds))
    monkeypatch.setattr(sys, "argv", ["workflow_worker", "--project-root", str(root), "--task", str(path)])
    with pytest.raises((ValueError, PermissionError)):
        workflow_worker.main()
    assert calls == [], "adapter ran before the signed task's approval/configuration was checked"
