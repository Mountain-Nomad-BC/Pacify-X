"""Real signed durable checkpoints; no fabricated run-owner implementation."""
import json

import pytest

from runtime.contracts import validate_instance
from runtime.studio_models import WorkflowDefinition, WorkflowNode, WorkflowPort
from runtime.studio_run_control import DurableRunControl
from runtime.workflow_resume import WorkflowResumeRejected, validate_workflow_resume
from pathlib import Path


@pytest.fixture
def checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-keys"))
    node = WorkflowNode("first", "binding:first", (WorkflowPort("input", "string"),),
        (WorkflowPort("output", "string"),), ("grant:read",), "fail-closed", 30)
    definition = WorkflowDefinition("workflow:resume", "1.0.0", "human:owner", (node,), ())
    project = tmp_path / "project"
    project.mkdir()
    control = DurableRunControl(project, project / ".engineering-bootstrap/runs")
    state = control.create(kind="workflow", subject_id=definition.workflow_id,
        version=definition.version, owner=definition.owner, revision_sha256="a"*64,
        request_sha256="b"*64, checkpoint={"ready_nodes":["first"],"next_node":"first"})
    return project, definition, control, state


def inspect(checkpoint, **changes):
    _, definition, control, state = checkpoint
    arguments = dict(expected_revision_sha256="a"*64, expected_request_sha256="b"*64,
        expected_control_sequence=state["sequence"])
    arguments.update(changes)
    return validate_workflow_resume(definition, control, state["run_id"], **arguments)


def test_authenticated_unstarted_checkpoint_projects_ready_node_without_execution(checkpoint):
    root, _, _, _ = checkpoint
    before = {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob("*.json")}
    decision = inspect(checkpoint)
    assert decision.ready_nodes == ("first",)
    assert decision.completed_nodes == ()
    assert decision.as_dict()["authority_granted"] is False
    validate_instance(decision.as_dict(), Path(__file__).parents[1]/"contracts/workflow-resume-decision.schema.json")
    assert before == {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob("*.json")}


@pytest.mark.parametrize("changed", [dict(expected_revision_sha256="c"*64),
    dict(expected_request_sha256="c"*64), dict(expected_control_sequence=2)])
def test_checkpoint_reuse_rejects_changed_identity_or_sequence(checkpoint, changed):
    with pytest.raises(WorkflowResumeRejected):
        inspect(checkpoint, **changed)


def test_forged_checkpoint_cannot_skip_work(checkpoint):
    root, _, _, state = checkpoint
    head = root / ".engineering-bootstrap/runs" / state["run_id"] / "head.json"
    forged = json.loads(head.read_text(encoding="utf-8"))
    forged["checkpoint"]["completed_nodes"] = ["first"]
    head.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(PermissionError, match="authentication"):
        inspect(checkpoint)
