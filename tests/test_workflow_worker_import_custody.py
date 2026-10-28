from pathlib import Path
from runtime.workflow_studio import WorkflowStudio
from tests.test_workflow_studio import fixture


def test_project_runtime_package_cannot_shadow_owned_workflow_worker(tmp_path, monkeypatch):
    root = tmp_path / "managed-project"
    root.mkdir()
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-keys"))
    hostile = root / "runtime"
    hostile.mkdir()
    marker = root / "untrusted-package-executed.txt"
    (hostile / "__init__.py").write_text("from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('shadowed', encoding='utf-8')\n", encoding="utf-8")
    (hostile / "workflow_worker.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
    definition, bindings, grants = fixture()
    studio = WorkflowStudio(root)
    studio.save_revision(definition)
    studio.register_authority(bindings, grants, {bindings[0].binding_id: "increment", bindings[1].binding_id: "double"})
    assert studio.validate_and_admit(definition)["runnable_state"] == "runnable"
    approved = studio.issue_approval(definition, "node:two", approved_by="human:vscode-local-user")
    try:
        receipt = studio.execute(definition, {"node:one.value": 2}, {"node:two": approved}, approval=True)
    except RuntimeError:
        assert not marker.exists(), "managed project code shadowed the owned engine before worker checks"
        raise
    assert not marker.exists(), "managed project code shadowed the owned engine before worker checks"
    assert receipt["run_state"] == "succeeded"
