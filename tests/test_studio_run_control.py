from __future__ import annotations

import json
import sys

import pytest

import runtime.studio_run_control as run_control_module
from runtime.resource_lifecycle import ResourceManager
from runtime.studio_run_control import DurableRunControl
from runtime.studio_terminal_observer import _retryable_finalize_error
from runtime.studio_worker_launch import finalize_studio_run_if_worker_exited


def test_durable_run_control_is_approval_gated_hash_chained_and_tamper_evident(
    tmp_path,
) -> None:
    control = DurableRunControl(tmp_path, tmp_path / ".engineering-bootstrap/runs")
    state = control.create(
        kind="agent",
        subject_id="agent:demo",
        version="1.0.0",
        owner="human:owner",
        revision_sha256="a" * 64,
        request_sha256="b" * 64,
    )
    with pytest.raises(PermissionError, match="explicit host approval"):
        control.transition(
            state["run_id"], "running", actor="human:owner", approved=False
        )
    running = control.transition(
        state["run_id"], "running", actor="human:owner", approved=True
    )
    assert running["state"] == "running" and running["sequence"] == 2
    head_path = (
        tmp_path
        / ".engineering-bootstrap/runs"
        / str(state["run_id"])
        / "head.json"
    )
    forged = json.loads(head_path.read_text(encoding="utf-8"))
    forged["state"] = "succeeded"
    head_path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(PermissionError, match="authentication"):
        control.read(str(state["run_id"]))


def test_terminal_observer_retries_only_transient_finalize_failures() -> None:
    assert _retryable_finalize_error(OSError("transient filesystem contention"))
    assert _retryable_finalize_error(
        ValueError("illegal durable run transition: finalizing -> finalizing")
    )
    assert not _retryable_finalize_error(ValueError("invalid terminal target"))
    assert not _retryable_finalize_error(PermissionError("identity mismatch"))


def test_stale_owned_run_is_reconciled_to_interrupted_not_claimed_complete(
    tmp_path, monkeypatch
) -> None:
    control = DurableRunControl(tmp_path, tmp_path / ".engineering-bootstrap/runs")
    with monkeypatch.context() as context:
        context.setattr(run_control_module, "_now", lambda: "2020-01-01T00:00:00.000Z")
        state = control.create(
            kind="workflow",
            subject_id="workflow:demo",
            version="1.0.0",
            owner="human:owner",
            revision_sha256="a" * 64,
            request_sha256="b" * 64,
        )
        control.transition(
            state["run_id"], "running", actor="human:owner", approved=True
        )
    with pytest.raises(PermissionError, match="explicit host approval"):
        control.reconcile(actor="human:owner", approved=False)
    receipt = control.reconcile(
        actor="human:owner", approved=True, stale_after_seconds=1
    )
    assert receipt["interrupted"] == 1
    recovered = control.read(str(state["run_id"]))
    assert recovered["state"] == "interrupted"
    assert recovered["failure"]["code"] == "OWNER_HEARTBEAT_STALE"


def test_exact_authenticated_trailing_event_repairs_crash_window_only_with_approval(
    tmp_path, monkeypatch
) -> None:
    control = DurableRunControl(tmp_path, tmp_path / ".engineering-bootstrap/runs")
    state = control.create(
        kind="workflow",
        subject_id="workflow:crash",
        version="1.0.0",
        owner="human:owner",
        revision_sha256="a" * 64,
        request_sha256="b" * 64,
    )
    original_write = run_control_module.write_json_atomic

    def crash_before_head(path, value):
        if path.name == "head.json":
            raise OSError("simulated crash before head replace")
        return original_write(path, value)

    with monkeypatch.context() as context:
        context.setattr(run_control_module, "write_json_atomic", crash_before_head)
        with pytest.raises(OSError, match="simulated crash"):
            control.transition(
                state["run_id"], "running", actor="human:owner", approved=True
            )
    with pytest.raises(PermissionError, match="event sequence is incomplete"):
        control.read(str(state["run_id"]))
    with pytest.raises(PermissionError, match="explicit host approval"):
        control.recover_projection(
            str(state["run_id"]), actor="human:owner", approved=False
        )
    reconciliation = control.reconcile(
        actor="human:owner", approved=True, stale_after_seconds=3600
    )
    assert reconciliation["projection_repairs"] == 1
    recovered = control.read(str(state["run_id"]))
    assert recovered["state"] == "running" and recovered["sequence"] == 2
    receipt = next(
        (
            tmp_path
            / ".engineering-bootstrap/runs"
            / str(state["run_id"])
            / "recovery-receipts"
        ).glob("*.json")
    )
    assert receipt.is_file()
    assert control.authority.verify_receipt(json.loads(receipt.read_text()))[
        "projection_repaired"
    ] is True
    assert control.read(str(state["run_id"]))["state"] == "running"


def test_missing_initial_head_can_recover_from_exactly_one_signed_create_event(
    tmp_path, monkeypatch
) -> None:
    control = DurableRunControl(tmp_path, tmp_path / ".engineering-bootstrap/runs")
    original_write = run_control_module.write_json_atomic

    def crash_before_initial_head(path, value):
        if path.name == "head.json":
            raise OSError("simulated initial head crash")
        return original_write(path, value)

    with monkeypatch.context() as context:
        context.setattr(
            run_control_module, "write_json_atomic", crash_before_initial_head
        )
        with pytest.raises(OSError, match="initial head crash"):
            control.create(
                kind="agent",
                subject_id="agent:create-crash",
                version="1.0.0",
                owner="human:owner",
                revision_sha256="a" * 64,
                request_sha256="b" * 64,
            )
    run_root = next((tmp_path / ".engineering-bootstrap/runs").glob("run-*"))
    recovered = control.recover_projection(
        run_root.name, actor="human:owner", approved=True
    )
    assert recovered["projection_repaired"] is True
    assert control.read(run_root.name)["state"] == "queued"


def test_projection_recovery_rejects_tampered_or_multiple_trailing_events(
    tmp_path, monkeypatch
) -> None:
    def crash_transition(control, state):
        original_write = run_control_module.write_json_atomic

        def crash_before_head(path, value):
            if path.name == "head.json":
                raise OSError("crash")
            return original_write(path, value)

        with monkeypatch.context() as context:
            context.setattr(
                run_control_module, "write_json_atomic", crash_before_head
            )
            with pytest.raises(OSError, match="crash"):
                control.transition(
                    state["run_id"], "running", actor="human:owner", approved=True
                )

    tamper_root = tmp_path / "tamper"
    tamper_root.mkdir()
    tamper = DurableRunControl(
        tamper_root, tamper_root / ".engineering-bootstrap/runs"
    )
    tamper_state = tamper.create(
        kind="agent",
        subject_id="agent:tamper",
        version="1.0.0",
        owner="human:owner",
        revision_sha256="a" * 64,
        request_sha256="b" * 64,
    )
    crash_transition(tamper, tamper_state)
    event = (
        tamper_root
        / ".engineering-bootstrap/runs"
        / str(tamper_state["run_id"])
        / "events/00000002.json"
    )
    forged = json.loads(event.read_text(encoding="utf-8"))
    forged["operation"] = "forged"
    event.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(PermissionError, match="authentication"):
        tamper.recover_projection(
            str(tamper_state["run_id"]), actor="human:owner", approved=True
        )

    multiple_root = tmp_path / "multiple"
    multiple_root.mkdir()
    multiple = DurableRunControl(
        multiple_root, multiple_root / ".engineering-bootstrap/runs"
    )
    multiple_state = multiple.create(
        kind="workflow",
        subject_id="workflow:multiple",
        version="1.0.0",
        owner="human:owner",
        revision_sha256="a" * 64,
        request_sha256="b" * 64,
    )
    crash_transition(multiple, multiple_state)
    events = (
        multiple_root
        / ".engineering-bootstrap/runs"
        / str(multiple_state["run_id"])
        / "events"
    )
    (events / "00000003.json").write_bytes((events / "00000002.json").read_bytes())
    with pytest.raises(PermissionError, match="exceeds one trailing event"):
        multiple.recover_projection(
            str(multiple_state["run_id"]), actor="human:owner", approved=True
        )


@pytest.mark.parametrize(
    ("initial_state", "expected_state"),
    (("queued", "failed"), ("running", "failed"), ("cancel_requested", "cancelled")),
)
def test_dead_worker_is_terminally_reconciled_from_every_live_launch_state(
    tmp_path, monkeypatch, initial_state: str, expected_state: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-keys"))
    state_root = project / ".engineering-bootstrap/studios/agents"
    manager = ResourceManager(state_root / "resources.json")
    control = DurableRunControl(project, state_root / "run-control")
    state = control.create(
        kind="agent",
        subject_id="agent:test",
        version="1.0.0",
        owner="human:test",
        revision_sha256="a" * 64,
        request_sha256="b" * 64,
    )
    if initial_state != "queued":
        control.transition(
            state["run_id"], initial_state, actor="human:test", approved=True
        )
    record, process = manager.spawn_owned_process(
        (sys.executable, "-c", "pass"),
        cwd=project,
        project_id=project.name,
        run_id=str(state["run_id"]),
        lane_id="studio-agent",
        creator="px-studio-durable-launcher",
    )
    process.wait(timeout=10)

    final = finalize_studio_run_if_worker_exited(
        state_root=state_root,
        manager=manager,
        authority=control.authority,
        run_control=control,
        run_id=str(state["run_id"]),
    )

    assert final["state"] == expected_state
    if expected_state == "failed":
        assert final["failure"]["code"] == "WORKER_EXITED_WITHOUT_TERMINAL_STATE"
    persisted = manager.ledger.get(record.resource_id)
    assert persisted.active is False
    assert persisted.cleanup_result == "process_absence_verified"
