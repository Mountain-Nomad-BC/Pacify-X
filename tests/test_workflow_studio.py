from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
import threading
import time

from runtime.studio_models import (
    CapabilityBinding,
    EffectGrant,
    StudioVersionConflict,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowPort,
    allocate_studio_version,
)
from runtime.workflow_studio import WorkflowStudio
from runtime.file_lock import _process_exists
from runtime.resource_lifecycle import RunState
from runtime.resource_lifecycle import ResourceManager
from runtime.studio_terminal_observer import (
    _reconcile_exited_worker_paths,
    _wait_for_worker_handoff,
)
from tests.studio_approval_testkit import approval_proof, one_shot as _one_shot


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    grant = EffectGrant(
        "grant:workflow",
        "workflow:demo",
        ("read",),
        ("workspace:demo",),
        "human:owner",
        ("receipt:grant",),
        state="admitted",
    )
    first = CapabilityBinding(
        "binding:first",
        "workflow",
        "workflow:demo",
        "capability:first",
        "1.0.0",
        (grant.grant_id,),
        None,
        "non-billable",
        "deny",
        "admitted",
        ("receipt:first",),
    )
    second = CapabilityBinding(
        "binding:second",
        "workflow",
        "workflow:demo",
        "capability:second",
        "1.0.0",
        (grant.grant_id,),
        None,
        "non-billable",
        "deny",
        "admitted",
        ("receipt:second",),
    )
    one = WorkflowNode(
        "node:one",
        first.binding_id,
        (WorkflowPort("value", "integer"),),
        (WorkflowPort("value", "integer"),),
        (grant.grant_id,),
        "fail-closed",
        10,
    )
    two = WorkflowNode(
        "node:two",
        second.binding_id,
        (WorkflowPort("value", "integer"),),
        (WorkflowPort("result", "integer"),),
        (grant.grant_id,),
        "fail-closed",
        10,
        approval_required=True,
    )
    return (
        WorkflowDefinition(
            "workflow:demo",
            "1.0.0",
            "owner",
            (one, two),
            (WorkflowEdge(one.node_id, "value", two.node_id, "value"),),
        ),
        [first, second],
        [grant],
    )


def test_workflow_revision_runnable_dry_run_and_real_run_are_distinct(tmp_path):
    definition, bindings, grants = fixture()
    studio = WorkflowStudio(tmp_path)
    assert studio.save_revision(definition)["runnable_state"] == "unvalidated"
    studio.register_authority(
        bindings,
        grants,
        {bindings[0].binding_id: "increment", bindings[1].binding_id: "double"},
    )
    admitted = studio.validate_and_admit(definition)
    assert admitted["runnable_state"] == "runnable"
    assert studio.dry_run(definition)["effects_executed"] is False
    with pytest.raises(PermissionError, match="approval"):
        studio.execute(definition, {"node:one.value": 2}, approval=True)
    approval = studio.issue_approval(
        definition, "node:two", approved_by="human:vscode-local-user"
    )
    receipt = studio.execute(
        definition, {"node:one.value": 2}, {"node:two": approval}, approval=True
    )
    assert receipt["run_state"] == "succeeded" and receipt["node_count"] == 2
    approval_result = receipt["node_receipts"][1]["approval_execution"]
    assert approval_result["host_consumed"] is True
    assert approval_result["approved_by"] == "human:vscode-local-user"
    assert len(approval_result["approval_id_sha256"]) == 64


def test_legacy_workflow_save_reports_initial_creation_and_exact_replay_truth(tmp_path):
    definition, _, _ = fixture()
    studio = WorkflowStudio(tmp_path)
    created = studio.save_revision(definition)
    replay = studio.save_revision(definition)
    assert created["created"] is True
    assert replay["created"] is False
    assert created["revision_sha256"] == replay["revision_sha256"]


@pytest.mark.parametrize(
    "mutation",
    (
        "year-zero",
        "invalid-calendar",
        "excess-precision",
        "undeclared-key",
        "revision-hash",
        "definition-hash",
        "layout-hash",
        "identity",
        "version",
        "record-path",
        "layout-path",
        "authority-state",
        "authority-path",
        "host-authority",
        "created-state",
    ),
)
def test_workflow_replay_rejects_each_invalid_creation_receipt_field(
    tmp_path, mutation
) -> None:
    definition, _, _ = fixture()
    studio = WorkflowStudio(tmp_path)
    layout = {
        node.node_id: {"x": index * 320, "y": 0}
        for index, node in enumerate(definition.nodes)
    }
    created = studio.save_revision(definition, editor_layout=layout)
    receipt_path = (tmp_path / str(created["path"])).with_name("creation-receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "year-zero":
        receipt["created_utc"] = "0000-01-01T00:00:00Z"
    elif mutation == "invalid-calendar":
        receipt["created_utc"] = "2026-02-31T00:00:00Z"
    elif mutation == "excess-precision":
        receipt["created_utc"] = "2026-08-16T00:00:00.1234Z"
    elif mutation == "undeclared-key":
        receipt["undeclared"] = True
    elif mutation == "revision-hash":
        receipt["revision_sha256"] = "f" * 64
    elif mutation == "definition-hash":
        receipt["definition_sha256"] = "f" * 64
    elif mutation == "layout-hash":
        receipt["editor_layout_sha256"] = "f" * 64
    elif mutation == "identity":
        receipt["workflow_id"] = "workflow:substituted"
    elif mutation == "version":
        receipt["version"] = "9.9.9"
    elif mutation == "record-path":
        receipt["path"] = "substituted"
    elif mutation == "layout-path":
        receipt["editor_layout_path"] = "substituted"
    elif mutation == "authority-state":
        receipt["authority_state"] = "granted"
    elif mutation == "authority-path":
        receipt["authority_definition_path"] = "substituted"
    elif mutation == "host-authority":
        receipt["host_authority_retained"] = False
    else:
        receipt["created"] = False
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(StudioVersionConflict) as refused:
        studio.save_revision(definition, editor_layout=layout)
    assert refused.value.reason == "immutable-workflow-revision-differs"


def test_workflow_create_returns_bounded_cleanup_warnings_after_commit(
    tmp_path, monkeypatch
) -> None:
    definition, _, _ = fixture()
    studio = WorkflowStudio(tmp_path)
    layout = {
        node.node_id: {"x": index * 320, "y": 0}
        for index, node in enumerate(definition.nodes)
    }
    monkeypatch.setattr(
        studio.manager,
        "reclaim",
        lambda *args, **kwargs: SimpleNamespace(errors=tuple("y" * 300 for _ in range(12))),
    )
    created = studio.save_revision(definition, editor_layout=layout)
    assert created["created"] is True
    assert len(created["cleanup_warnings"]) == 8
    assert all(len(warning) == 240 for warning in created["cleanup_warnings"])
    assert (tmp_path / str(created["path"])).is_file()


def test_workflow_publish_failure_remains_authoritative_when_reconciliation_fails(
    tmp_path, monkeypatch
) -> None:
    definition, _, _ = fixture()
    studio = WorkflowStudio(tmp_path)
    layout = {
        node.node_id: {"x": index * 320, "y": 0}
        for index, node in enumerate(definition.nodes)
    }
    calls = []

    def fail_publication(*_args):
        raise ValueError("authoritative-publication-failure")

    def fail_closure(*_args, **_kwargs):
        calls.append("closure")
        raise RuntimeError("closure-failure")

    def fail_reclaim(*_args, **_kwargs):
        calls.append("reclaim")
        raise RuntimeError("reclaim-failure")

    monkeypatch.setattr("runtime.workflow_studio.publish_directory_no_replace", fail_publication)
    monkeypatch.setattr(studio.manager, "mark_run_ended", fail_closure)
    monkeypatch.setattr(studio.manager, "reclaim", fail_reclaim)
    with pytest.raises(ValueError, match="authoritative-publication-failure") as refused:
        studio.save_revision(definition, editor_layout=layout)
    assert calls == ["closure", "reclaim"]
    assert any("closure-failure" in note for note in refused.value.__notes__)
    assert any("reclaim-failure" in note for note in refused.value.__notes__)


def test_workflow_exact_replay_rejects_undeclared_revision_topology(tmp_path) -> None:
    definition, _, _ = fixture()
    studio = WorkflowStudio(tmp_path)
    layout = {
        node.node_id: {"x": index * 320, "y": 0}
        for index, node in enumerate(definition.nodes)
    }
    created = studio.save_revision(definition, editor_layout=layout)
    revision = (tmp_path / created["path"]).parent
    (revision / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(StudioVersionConflict) as refused:
        studio.save_revision(definition, editor_layout=layout)
    assert refused.value.reason == "immutable-workflow-revision-differs"


def test_workflow_publication_revalidates_allocation_and_preserves_collision(tmp_path):
    definition, _, _ = fixture()
    studio = WorkflowStudio(tmp_path)
    layout = {
        node.node_id: {"x": index * 320, "y": 0}
        for index, node in enumerate(definition.nodes)
    }
    studio.save_revision(definition, editor_layout=layout)
    allocation = allocate_studio_version(
        tmp_path, "workflow", definition.workflow_id, definition.version
    )
    candidate = replace(definition, version="1.0.1")
    created = studio.save_revision(
        candidate,
        editor_layout=layout,
        version_allocation=allocation,
    )
    record_path = tmp_path / str(created["path"])
    original = record_path.read_bytes()
    replay = studio.save_revision(
        candidate,
        editor_layout=layout,
        version_allocation=allocation,
    )
    assert replay["created"] is False and replay["idempotent_replay"] is True
    assert record_path.read_bytes() == original


def test_workflow_runtime_publishes_only_the_normalized_canonical_version(tmp_path):
    definition, _, _ = fixture()
    normalized = replace(definition, version=" 1.0.0-RC.1 ")
    assert normalized.version == "1.0.0-rc.1"
    receipt = WorkflowStudio(tmp_path).save_revision(normalized)
    assert receipt["version"] == "1.0.0-rc.1"
    assert "/revisions/1.0.0-rc.1/" in f"/{receipt['path']}"


def test_workflow_node_approval_rejects_non_host_issuer(tmp_path):
    definition, bindings, grants = fixture()
    studio = WorkflowStudio(tmp_path)
    studio.save_revision(definition)
    studio.register_authority(
        bindings,
        grants,
        {bindings[0].binding_id: "increment", bindings[1].binding_id: "double"},
    )
    studio.validate_and_admit(definition)
    with pytest.raises(PermissionError, match="authenticated host"):
        studio.issue_approval(
            definition, "node:two", approved_by="human:untrusted-caller"
        )


def test_workflow_is_not_runnable_when_an_executor_is_only_declared(tmp_path):
    definition, bindings, grants = fixture()
    studio = WorkflowStudio(tmp_path)
    studio.save_revision(definition)
    studio.register_authority(bindings, grants, {bindings[0].binding_id: "increment"})
    result = studio.validate_and_admit(definition)
    assert result["runnable_state"] == "not_runnable" and any(
        "executor" in reason for reason in result["reasons"]
    )


def test_workflow_condition_never_does_not_propagate_and_failed_run_is_durable(
    tmp_path,
):
    definition, bindings, grants = fixture()
    definition = WorkflowDefinition(
        definition.workflow_id,
        definition.version,
        definition.owner,
        definition.nodes,
        (WorkflowEdge("node:one", "value", "node:two", "value", "never"),),
    )
    studio = WorkflowStudio(tmp_path)
    studio.save_revision(definition)
    studio.register_authority(
        bindings,
        grants,
        {bindings[0].binding_id: "increment", bindings[1].binding_id: "double"},
    )
    studio.validate_and_admit(definition)
    approval = studio.issue_approval(
        definition, "node:two", approved_by="human:vscode-local-user"
    )
    receipt = studio.execute(
        definition, {"node:one.value": 2}, {"node:two": approval}, approval=True
    )
    assert receipt["run_state"] == "succeeded"
    assert [row["state"] for row in receipt["node_receipts"]] == [
        "succeeded",
        "skipped",
    ]
    assert receipt["node_receipts"][1]["skip_reason"] == "incoming_condition_disabled"
    receipts = list(
        (tmp_path / ".engineering-bootstrap/studios/workflows/runs").glob("run-*.json")
    )
    assert (
        len(receipts) == 1
        and __import__("json").loads(receipts[0].read_text())["run_state"]
        == "succeeded"
    )


def test_workflow_approval_is_single_use(tmp_path):
    definition, bindings, grants = fixture()
    studio = WorkflowStudio(tmp_path)
    studio.save_revision(definition)
    studio.register_authority(
        bindings,
        grants,
        {bindings[0].binding_id: "increment", bindings[1].binding_id: "double"},
    )
    studio.validate_and_admit(definition)
    approval = studio.issue_approval(
        definition, "node:two", approved_by="human:vscode-local-user"
    )
    studio.execute(
        definition, {"node:one.value": 2}, {"node:two": approval}, approval=True
    )
    with pytest.raises(PermissionError, match="replay"):
        studio.execute(
            definition, {"node:one.value": 2}, {"node:two": approval}, approval=True
        )


def test_workflow_timeout_and_retry_controls_are_enforced(tmp_path):
    grant = EffectGrant(
        "grant:timeout",
        "workflow:timeout",
        ("read",),
        ("workspace:demo",),
        "human:owner",
        ("receipt:grant",),
        state="admitted",
    )
    binding = CapabilityBinding(
        "binding:timeout",
        "workflow",
        "workflow:timeout",
        "capability:timeout",
        "1.0.0",
        (grant.grant_id,),
        None,
        "non-billable",
        "deny",
        "admitted",
        ("receipt:binding",),
    )
    node = WorkflowNode(
        "node:timeout",
        binding.binding_id,
        (WorkflowPort("seconds", "number"),),
        (WorkflowPort("seconds", "number"),),
        (grant.grant_id,),
        "fail-closed",
        0.05,
        retry_limit=1,
    )
    definition = WorkflowDefinition("workflow:timeout", "1.0.0", "owner", (node,), ())
    studio = WorkflowStudio(tmp_path)
    studio.save_revision(definition)
    studio.register_authority([binding], [grant], {binding.binding_id: "sleep"})
    studio.validate_and_admit(definition)
    with pytest.raises(RuntimeError, match="node failed"):
        studio.execute(definition, {"node:timeout.seconds": 0.2}, approval=True)
    receipt_path = next(
        (tmp_path / ".engineering-bootstrap/studios/workflows/runs").glob("run-*.json")
    )
    receipt = __import__("json").loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["run_state"] == "failed"
    assert len(receipt["node_receipts"][0]["attempts"]) == 2
    assert all(
        row["status"] in {"startup_timeout", "idle_timeout", "total_timeout"}
        for row in receipt["node_receipts"][0]["attempts"]
    )


def _wait_for_workflow_state(studio, run_id: str, expected: set[str]) -> dict:
    # Allow bounded scheduler jitter after long serial release groups without
    # making status() a hidden finalization trigger.
    deadline = time.monotonic() + 45
    state = studio.run_control.read(run_id)
    while time.monotonic() < deadline:
        # Finalization is owned by the registered observer, not by status().
        state = studio.run_control.read(run_id)
        if state["state"] in expected:
            return state
        time.sleep(0.02)
    lifecycle = [
        {
            "resource_id": record.resource_id,
            "resource_type": record.resource_type,
            "run_id": record.run_id,
            "pid": record.pid,
            "active": record.active,
            "status": record.status,
            "run_state": record.run_state,
            "cleanup_result": record.cleanup_result,
        }
        for record in studio.manager.ledger.load()
        if record.run_id == run_id
        or record.run_id.startswith(f"studio-finalizer-{run_id}-")
    ]
    diagnostic_path = (
        studio.state_root
        / "sessions"
        / run_id
        / "terminal-observer-diagnostic.json"
    )
    diagnostic = (
        diagnostic_path.read_text(encoding="utf-8")
        if diagnostic_path.is_file()
        else "missing"
    )
    raise AssertionError(
        f"workflow did not reach {expected}; last state="
        f"{state.get('state')} sequence={state.get('sequence')} "
        f"failure={state.get('failure')} lifecycle={lifecycle!r} "
        f"observer_diagnostic={diagnostic}"
    )


@pytest.mark.parametrize("action", ["cancel", "stop"])
def test_workflow_cancel_or_stop_wins_during_nonterminal_finalization(
    tmp_path, monkeypatch, action
) -> None:
    monkeypatch.setenv(
        "PX_STUDIO_KEY_ROOT", str(tmp_path.parent / f"{tmp_path.name}-host-keys")
    )
    studio = WorkflowStudio(tmp_path)
    created = studio.run_control.create(
        kind="workflow",
        subject_id="workflow:finalizing-race",
        version="1.0.0",
        owner="human:owner",
        revision_sha256="a" * 64,
        request_sha256="b" * 64,
    )
    studio.run_control.transition(
        created["run_id"], "running", actor="human:owner", approved=True
    )
    studio.run_control.transition(
        created["run_id"],
        "finalizing",
        actor="human:owner",
        approved=True,
        checkpoint={"terminal_target": "succeeded"},
    )

    cancelled = studio.request_lifecycle(
        created["run_id"],
        action,
        approved=True,
        approved_by="human:owner",
    )

    assert cancelled["state"] == "cancelled"
    assert cancelled["checkpoint"]["terminal_target"] == "cancelled"


def test_terminal_observer_reclaims_exact_run_task_path_before_publication(
    tmp_path,
) -> None:
    state_root = tmp_path / "state"
    manager = ResourceManager(state_root / "resources.json")
    run_id = "run-terminal-path-reconciliation"
    worker, process = manager.spawn_owned_process(
        [sys.executable, "-c", "import time; time.sleep(0.2)"],
        cwd=tmp_path,
        project_id="workflow:lifecycle",
        run_id=run_id,
        lane_id="studio-workflow",
        creator="px-studio-durable-launcher",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert process.wait(timeout=10) == 0
    task_root = state_root / "node-tasks"
    task_root.mkdir(parents=True)
    task_path = task_root / "attempt"
    task_path.mkdir()
    (task_path / "request.json").write_text("{}\n", encoding="utf-8")
    task = manager.register_path(
        task_path,
        allowed_cleanup_root=task_root,
        project_id="workflow:lifecycle",
        run_id=run_id,
        lane_id="node:slow",
        creator="human:owner",
    )

    _reconcile_exited_worker_paths(
        manager,
        run_control=SimpleNamespace(
            read=lambda observed: {
                "run_id": observed,
                "state": "cancel_requested",
                "checkpoint": {},
            }
        ),
        run_id=run_id,
        kind="workflow",
    )

    reclaimed = manager.ledger.get(task.resource_id)
    assert reclaimed.active is False and reclaimed.status == "reclaimed"
    assert task_path.exists() is False
    manager.complete_persisted_process_after_exit(
        worker.resource_id,
        expected_pid=int(worker.pid or 0),
        run_state=RunState.CANCELLED,
    )


def test_terminal_observer_waits_for_worker_handoff_before_inspecting_launcher(
    tmp_path,
) -> None:
    binding_path = tmp_path / "sessions" / "run-handoff" / "worker-request-cleanup.json"
    clock_values = iter((10.0, 10.01))
    sleeps: list[float] = []

    def publish_binding(delay: float) -> None:
        sleeps.append(delay)
        binding_path.parent.mkdir(parents=True)
        binding_path.write_text("{}\n", encoding="utf-8")

    assert _wait_for_worker_handoff(
        binding_path,
        timeout_seconds=30.0,
        clock=lambda: next(clock_values),
        sleeper=publish_binding,
    )
    assert sleeps == [0.02]


def test_workflow_pause_resume_cancel_and_checkpoint_recovery(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "PX_STUDIO_KEY_ROOT", str(tmp_path.parent / f"{tmp_path.name}-host-keys")
    )
    grant = EffectGrant(
        "grant:lifecycle",
        "workflow:lifecycle",
        ("write",),
        ("workspace:demo",),
        "human:owner",
        ("receipt:grant",),
        state="admitted",
    )
    first_binding = CapabilityBinding(
        "binding:lifecycle-first",
        "workflow",
        "workflow:lifecycle",
        "capability:increment",
        "1.0.0",
        (grant.grant_id,),
        None,
        "non-billable",
        "deny",
        "admitted",
        ("receipt:first",),
    )
    slow_binding = CapabilityBinding(
        "binding:lifecycle-slow",
        "workflow",
        "workflow:lifecycle",
        "capability:sleep",
        "1.0.0",
        (grant.grant_id,),
        None,
        "non-billable",
        "deny",
        "admitted",
        ("receipt:slow",),
    )
    first = WorkflowNode(
        "node:first",
        first_binding.binding_id,
        (WorkflowPort("value", "integer"),),
        (WorkflowPort("value", "integer"),),
        (grant.grant_id,),
        "fail-closed",
        5,
    )
    slow = WorkflowNode(
        "node:slow",
        slow_binding.binding_id,
        (WorkflowPort("seconds", "number"),),
        (WorkflowPort("seconds", "number"),),
        (grant.grant_id,),
        "fail-closed",
        10,
    )
    definition = WorkflowDefinition(
        "workflow:lifecycle", "1.0.0", "human:owner", (first, slow), ()
    )
    studio = WorkflowStudio(tmp_path)
    studio.save_revision(definition)
    studio.register_authority(
        [first_binding, slow_binding],
        [grant],
        {
            first_binding.binding_id: "increment",
            slow_binding.binding_id: "sleep",
        },
    )
    studio.validate_and_admit(definition)
    # Keep a real pause/cancel window after a clean-room status subprocess
    # starts on Windows, below the admitted node deadline.
    inputs = {"node:first.value": 1, "node:slow.seconds": 4.0}
    start_payload = {**asdict(definition), "run_inputs": inputs, "approvals": {}}
    approval = approval_proof(tmp_path, "workflow", "start", start_payload)
    started = _one_shot(tmp_path, "workflow", "start", {**start_payload, "approval_capability": approval})
    assert _one_shot(tmp_path, "workflow", "status", {"run_id": started["run_id"]})["state"] != "queued"
    state = _wait_for_workflow_state(studio, started["run_id"], {"running"})
    while "node:first" not in state["checkpoint"]["completed_nodes"]:
        time.sleep(0.02)
        state = studio.status(started["run_id"])
    with pytest.raises(PermissionError, match="explicit host approval"):
        studio.request_lifecycle(
            started["run_id"],
            "pause",
            approved=False,
            approved_by="human:owner",
        )
    studio.request_lifecycle(
        started["run_id"],
        "pause",
        approved=True,
        approved_by="human:owner",
    )
    paused = _wait_for_workflow_state(studio, started["run_id"], {"paused"})
    assert paused["checkpoint"]["completed_nodes"] == ["node:first"]
    paused_observers = [
        record
        for record in studio.manager.ledger.load()
        if record.run_id.startswith(f"studio-finalizer-{started['run_id']}-")
        and record.creator == "px-studio-terminal-observer"
    ]
    assert len(paused_observers) == 1
    paused_observer_id = paused_observers[0].resource_id
    resumed = studio.resume(
        definition,
        inputs,
        {},
        run_id=started["run_id"],
        approval=True,
    )
    assert resumed["run_state"] == "succeeded" and resumed["node_count"] == 2
    paused_observer = studio.manager.ledger.get(paused_observer_id)
    assert paused_observer.active is False
    paused_worker = next(
        record
        for record in studio.manager.ledger.load()
        if record.resource_type == "process" and record.run_id == started["run_id"]
    )
    assert paused_worker.active is False
    assert paused_worker.run_state in {
        RunState.CANCELLED.value,
        RunState.COMPLETED.value,
        RunState.RECOVERABLE.value,
    }
    assert paused_worker.status == "reclaimed"
    assert [row["node_id"] for row in resumed["node_receipts"]] == [
        "node:first",
        "node:slow",
    ]

    for _cycle in range(5):
        approval = approval_proof(tmp_path, "workflow", "start", start_payload)
        cancelled_start = _one_shot(
            tmp_path,
            "workflow",
            "start",
            {**start_payload, "approval_capability": approval},
        )
        _wait_for_workflow_state(studio, cancelled_start["run_id"], {"running"})
        studio.request_lifecycle(
            cancelled_start["run_id"],
            "cancel",
            approved=True,
            approved_by="human:owner",
        )
        cancelled = _wait_for_workflow_state(
            studio, cancelled_start["run_id"], {"cancelled"}
        )
        assert cancelled["state"] == "cancelled"
        worker = next(
            record
            for record in studio.manager.ledger.load()
            if record.resource_type == "process" and record.run_id == cancelled_start["run_id"]
        )
        assert worker.pid is not None and not _process_exists(worker.pid)
        assert worker.active is False and worker.status == "reclaimed"
        assert not any(
            record.active and record.run_id == cancelled_start["run_id"]
            for record in studio.manager.ledger.load()
        )
        immediate = studio.execute(
            definition,
            {"node:first.value": 1, "node:slow.seconds": 0.02},
            approval=True,
        )
        assert immediate["run_state"] == "succeeded"
        assert not any(
            record.active and record.run_id == immediate["run_id"]
            for record in studio.manager.ledger.load()
        )

    success_inputs = {"node:first.value": 1, "node:slow.seconds": 0.02}
    success_payload = {**asdict(definition), "run_inputs": success_inputs, "approvals": {}}
    success_approval = approval_proof(tmp_path, "workflow", "start", success_payload)
    success_start = _one_shot(tmp_path, "workflow", "start", {**success_payload, "approval_capability": success_approval})
    succeeded = _wait_for_workflow_state(studio, success_start["run_id"], {"succeeded"})
    assert succeeded["state"] == "succeeded"
    success_worker = next(
        record
        for record in studio.manager.ledger.load()
        if record.resource_type == "process" and record.run_id == success_start["run_id"]
    )
    assert success_worker.pid is not None and not _process_exists(success_worker.pid)
    assert success_worker.active is False and success_worker.status == "reclaimed"


@pytest.mark.parametrize("duration", [1.9, 2.0, 2.2])
def test_silent_workflow_node_crosses_two_second_boundary(
    tmp_path, monkeypatch, duration
) -> None:
    project = tmp_path / str(duration).replace(".", "-")
    project.mkdir()
    monkeypatch.setenv(
        "PX_STUDIO_KEY_ROOT", str(tmp_path / "host-keys")
    )
    grant = EffectGrant(
        "grant:silent", "workflow:silent", ("read",), ("workspace:demo",),
        "human:owner", ("receipt:grant",), state="admitted"
    )
    binding = CapabilityBinding(
        "binding:silent", "workflow", "workflow:silent", "capability:sleep",
        "1.0.0", (grant.grant_id,), None, "non-billable", "deny", "admitted",
        ("receipt:binding",)
    )
    node = WorkflowNode(
        "node:silent", binding.binding_id,
        (WorkflowPort("seconds", "number"),),
        (WorkflowPort("seconds", "number"),),
        (grant.grant_id,), "fail-closed", 5
    )
    definition = WorkflowDefinition(
        "workflow:silent", "1.0.0", "human:owner", (node,), ()
    )
    studio = WorkflowStudio(project)
    studio.save_revision(definition)
    studio.register_authority([binding], [grant], {binding.binding_id: "sleep"})
    studio.validate_and_admit(definition)
    receipt = studio.execute(
        definition, {"node:silent.seconds": duration}, approval=True
    )
    assert receipt["run_state"] == "succeeded"
    assert receipt["node_receipts"][0]["attempts"][0]["status"] == "exited"


def test_validation_node_executes_fail_closed_declarative_checks(tmp_path) -> None:
    grant = EffectGrant(
        "grant:validation",
        "workflow:validation",
        ("read",),
        ("workspace:demo",),
        "human:owner",
        ("receipt:grant",),
        state="admitted",
    )
    binding = CapabilityBinding(
        "binding:validation",
        "workflow",
        "workflow:validation",
        "capability:identity",
        "1.0.0",
        (grant.grant_id,),
        None,
        "non-billable",
        "deny",
        "admitted",
        ("receipt:binding",),
    )
    node = WorkflowNode(
        "node:validation",
        binding.binding_id,
        (WorkflowPort("value", "integer"),),
        (WorkflowPort("value", "integer"),),
        (grant.grant_id,),
        "fail-closed",
        5,
        kind="validation",
        config={
            "checks": [
                {
                    "id": "check:min-value",
                    "source": "outputs",
                    "port": "value",
                    "operator": "greater-than-or-equal",
                    "expected": 2,
                }
            ]
        },
    )
    definition = WorkflowDefinition(
        "workflow:validation", "1.0.0", "human:owner", (node,), ()
    )
    studio = WorkflowStudio(tmp_path)
    studio.save_revision(definition)
    studio.register_authority([binding], [grant], {binding.binding_id: "identity"})
    studio.validate_and_admit(definition)

    passed = studio.execute(
        definition, {"node:validation.value": 2}, approval=True
    )
    attempt = passed["node_receipts"][0]["attempts"][0]
    assert attempt["adapter_admitted"] is True
    assert attempt["validation"]["passed"] is True
    assert attempt["validation"]["check_count"] == 1

    with pytest.raises(RuntimeError, match="node failed"):
        studio.execute(
            definition, {"node:validation.value": 1}, approval=True
        )


def test_independent_ready_nodes_use_bounded_deterministic_parallel_batch(
    tmp_path, monkeypatch
) -> None:
    grants = [
        EffectGrant(
            f"grant:branch-{suffix}",
            "workflow:parallel",
            (f"effect:{suffix}",),
            (f"workspace:demo/{suffix}",),
            "human:owner",
            (f"receipt:{suffix}",),
            state="admitted",
        )
        for suffix in ("a", "b")
    ]
    bindings = [
        CapabilityBinding(
            f"binding:branch-{suffix}",
            "workflow",
            "workflow:parallel",
            f"capability:branch-{suffix}",
            "1.0.0",
            (grant.grant_id,),
            None,
            "non-billable",
            "deny",
            "admitted",
            (f"receipt:binding-{suffix}",),
        )
        for suffix, grant in zip(("a", "b"), grants)
    ]
    nodes = tuple(
        WorkflowNode(
            f"branch:{suffix}",
            binding.binding_id,
            (WorkflowPort("value", "integer"),),
            (WorkflowPort("value", "integer"),),
            (grant.grant_id,),
            "fail-closed",
            5,
        )
        for suffix, binding, grant in zip(("a", "b"), bindings, grants)
    )
    definition = WorkflowDefinition(
        "workflow:parallel", "1.0.0", "human:owner", nodes, ()
    )
    studio = WorkflowStudio(tmp_path)
    studio.save_revision(definition)
    studio.register_authority(
        bindings,
        grants,
        {binding.binding_id: "identity" for binding in bindings},
    )
    studio.validate_and_admit(definition)
    lock = threading.Lock()
    active = 0
    max_active = 0

    def execute_node(_definition, node, node_inputs, _run_id, approval_execution):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.1)
        with lock:
            active -= 1
        return dict(node_inputs), {
            "node_id": node.node_id,
            "kind": node.kind,
            "state": "succeeded",
            "attempts": [],
            "approval_execution": dict(approval_execution or {}),
        }

    monkeypatch.setattr(studio, "_execute_node", execute_node)
    receipt = studio.execute(
        definition,
        {"branch:a.value": 1, "branch:b.value": 2},
        approval=True,
    )
    assert max_active == 2
    assert [row["node_id"] for row in receipt["node_receipts"]] == [
        "branch:a",
        "branch:b",
    ]
    assert receipt["execution_policy"]["max_parallel_nodes"] == 4
    assert studio._select_ready_batch(
        ["branch:a", "branch:b"],
        {node.node_id: node for node in nodes},
        {
            "branch:a": (("workspace:demo", "exclusive", "effect:a"),),
            "branch:b": (("workspace:demo", "exclusive", "effect:b"),),
        },
    ) == ["branch:a"]
