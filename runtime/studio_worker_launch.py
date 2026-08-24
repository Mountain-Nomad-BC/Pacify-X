"""Launch Studio work that must survive a one-shot CLI parent."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4
from datetime import datetime, timezone
from typing import Mapping

from .resource_lifecycle import ResourceManager, RunState
from .studio_authority import StudioAuthorityStore
from .studio_models import digest, write_json_atomic
from .studio_run_control import DurableRunControl, TERMINAL_STATES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def finalize_studio_run_if_worker_exited(
    *,
    state_root: Path,
    manager: ResourceManager,
    authority: StudioAuthorityStore,
    run_control: DurableRunControl,
    run_id: str,
) -> dict[str, object]:
    """Publish a terminal Studio state only after its detached worker died."""
    state = run_control.read(run_id)
    current_state = str(state["state"])
    if current_state in TERMINAL_STATES:
        return state
    checkpoint = state.get("checkpoint")
    target = str(
        checkpoint.get("terminal_target") if isinstance(checkpoint, Mapping) else ""
    )
    binding_path = state_root / "sessions" / run_id / "worker-request-cleanup.json"
    records = [
        record
        for record in manager.ledger.load()
        if record.run_id == run_id
        and record.lane_id == f"studio-{state['kind']}"
        and record.creator == "px-studio-durable-launcher"
        and record.resource_type == "process"
    ]
    if len(records) != 1 or not records[0].resource_id or int(records[0].pid or 0) <= 0:
        raise PermissionError("Studio finalization worker identity is ambiguous")
    worker = records[0]
    resource_id = worker.resource_id
    worker_pid = int(worker.pid or 0)
    if binding_path.is_file():
        raw = json.loads(binding_path.read_text(encoding="utf-8"))
        binding = authority.verify_receipt(raw)
        if (
            binding.get("run_id") != run_id
            or binding.get("worker_resource_id") != resource_id
            or int(binding.get("worker_pid") or 0) != worker_pid
        ):
            raise PermissionError("Studio finalization binding is invalid")
    if not manager.persisted_process_has_exited(
        resource_id, expected_pid=worker_pid
    ):
        return state
    if current_state == "paused":
        manager.complete_persisted_process_after_exit(
            resource_id,
            expected_pid=worker_pid,
            run_state=RunState.RECOVERABLE,
        )
        return state
    if current_state != "finalizing":
        target = "cancelled" if current_state == "cancel_requested" else "failed"
        failure = state.get("failure")
        if target == "failed" and not isinstance(failure, Mapping):
            failure = {
                "code": "WORKER_EXITED_WITHOUT_TERMINAL_STATE",
                "message": "Studio worker exited before publishing a terminal target",
            }
        state = run_control.transition(
            run_id,
            "finalizing",
            actor="px-studio-terminal-observer",
            approved=True,
            checkpoint={**dict(state["checkpoint"]), "terminal_target": target},
            failure=failure if isinstance(failure, Mapping) else None,
            operation=f"{state['kind']}.worker-exit-observed",
        )
    if target not in TERMINAL_STATES:
        raise PermissionError("finalizing Studio run lacks a valid terminal target")
    desired = (
        RunState.CANCELLED
        if target == "cancelled"
        else RunState.FAILED
        if target == "failed"
        else RunState.COMPLETED
    )
    try:
        manager.complete_persisted_process_after_exit(
            resource_id,
            expected_pid=worker_pid,
            run_state=desired,
        )
    except ValueError as error:
        if str(error) == "persisted process is still alive":
            return state
        raise
    current = run_control.read(run_id)
    if str(current["state"]) != "finalizing":
        return current
    final = run_control.transition(
        run_id,
        target,
        actor="px-studio-terminal-observer",
        approved=True,
        checkpoint=dict(current["checkpoint"]),
        failure=current.get("failure"),
        operation=f"{state['kind']}.{target}.process-exit-verified",
    )
    run_path = state_root / "runs" / f"{run_id}.json"
    if run_path.is_file():
        receipt = authority.verify_receipt(json.loads(run_path.read_text(encoding="utf-8")))
        if state["kind"] == "agent":
            receipt.update(
                {
                    "runtime_state": target,
                    "status": target,
                    "run_outcome": target,
                    "terminal_target": target,
                    "completed_utc": _now(),
                    "control_sequence": final["sequence"],
                    "control_head_sha256": digest(final),
                }
            )
        else:
            receipt.update(
                {
                    "run_state": target,
                    "status": target,
                    "terminal_target": target,
                    "completed_utc": _now(),
                    "control_sequence": final["sequence"],
                }
            )
        write_json_atomic(run_path, authority.sign_receipt(receipt))
    return final


def wait_for_paused_worker_closure(
    *,
    state_root: Path,
    manager: ResourceManager,
    authority: StudioAuthorityStore,
    run_control: DurableRunControl,
    run_id: str,
    kind: str,
    timeout_seconds: float = 10.0,
) -> dict[str, object]:
    """Fence a paused run from its exact detached worker before resuming it."""

    if kind not in {"agent", "workflow"}:
        raise ValueError("Studio worker kind must be agent or workflow")
    state = run_control.read(run_id)
    if str(state["state"]) != "paused":
        return state
    deadline = time.monotonic() + timeout_seconds
    while True:
        state = finalize_studio_run_if_worker_exited(
            state_root=state_root,
            manager=manager,
            authority=authority,
            run_control=run_control,
            run_id=run_id,
        )
        active_workers = [
            record
            for record in manager.ledger.load()
            if record.run_id == run_id
            and record.lane_id == f"studio-{kind}"
            and record.creator == "px-studio-durable-launcher"
            and record.resource_type == "process"
            and record.active
        ]
        if not active_workers:
            return state
        if str(state["state"]) != "paused":
            raise RuntimeError(
                f"paused {kind} changed state before worker custody closed"
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(f"paused {kind} worker did not close before resume")
        time.sleep(0.02)


def _launch_terminal_observer(
    *,
    project_root: Path,
    manager: ResourceManager,
    kind: str,
    run_id: str,
    environment: Mapping[str, str],
) -> tuple[str, int, str]:
    launch_nonce = uuid4().hex
    observer_run_id = f"studio-finalizer-{run_id}-{launch_nonce}"
    command = (
        sys.executable,
        "-m",
        "runtime.studio_terminal_observer",
        "--root",
        str(project_root),
        "--kind",
        kind,
        "--run-id",
        run_id,
        "--observer-run-id",
        observer_run_id,
        "--launch-nonce",
        launch_nonce,
    )
    record, process = manager.spawn_owned_process(
        command,
        cwd=project_root,
        project_id=project_root.name,
        run_id=observer_run_id,
        lane_id=f"studio-{kind}-terminal-observer",
        creator="px-studio-terminal-observer",
        environment=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=False,
    )
    return record.resource_id, process.pid, observer_run_id


def launch_studio_worker(
    *,
    project_root: Path,
    state_root: Path,
    manager: ResourceManager,
    authority: StudioAuthorityStore,
    run_control: DurableRunControl,
    kind: str,
    run_id: str,
    payload: Mapping[str, object],
    startup_timeout_seconds: float = 8.0,
) -> dict[str, object]:
    """Start one registered worker and acknowledge only observed liveness."""
    request_root = state_root / "worker-requests"
    request_root.mkdir(parents=True, exist_ok=True)
    request_path = request_root / f"{run_id}.json"
    if request_path.exists():
        raise FileExistsError("Studio worker request already exists")
    launch_nonce = uuid4().hex
    command = (
        sys.executable,
        "-m",
        "runtime.studio_session_worker",
        "--root",
        str(project_root),
        "--kind",
        kind,
        "--run-id",
        run_id,
        "--request",
        str(request_path),
        "--launch-nonce",
        launch_nonce,
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    module_root = str(Path(__file__).resolve().parents[1])
    environment["PYTHONPATH"] = os.pathsep.join(
        item
        for item in (module_root, environment.get("PYTHONPATH", ""))
        if item
    )
    record, process = manager.spawn_owned_process(
        command,
        cwd=project_root,
        project_id=project_root.name,
        run_id=run_id,
        lane_id=f"studio-{kind}",
        creator="px-studio-durable-launcher",
        environment=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=False,
    )
    request_record = manager.register_path(
        request_path,
        allowed_cleanup_root=request_root,
        project_id=project_root.name,
        run_id=run_id,
        lane_id=f"studio-{kind}",
        creator="px-studio-durable-launcher",
        parent_resource_id=record.resource_id,
    )
    request = authority.sign_receipt(
        {
            "schema_version": "px.studio-worker-request/1.0",
            "kind": kind,
            "run_id": run_id,
            "resource_id": record.resource_id,
            "request_resource_id": request_record.resource_id,
            "expected_pid": process.pid,
            "launch_nonce": launch_nonce,
            "payload": dict(payload),
            "payload_sha256": digest(payload),
            "authority_state": "codex-host-retained",
        }
    )
    write_json_atomic(request_path, request)
    observer_resource_id, observer_pid, observer_run_id = _launch_terminal_observer(
        project_root=project_root,
        manager=manager,
        kind=kind,
        run_id=run_id,
        environment=environment,
    )
    deadline = time.monotonic() + max(1.0, startup_timeout_seconds)
    while time.monotonic() < deadline:
        state = run_control.read(run_id)
        current_record = manager.ledger.get(record.resource_id)
        worker_pid = int(current_record.pid or process.pid)
        if str(state["state"]) != "queued":
            return {
                "schema_version": f"px.{kind}-session-start/1.1",
                "run_id": run_id,
                "state": state["state"],
                "accepted": True,
                "live_worker_observed": True,
                "worker_pid": worker_pid,
                "worker_resource_id": record.resource_id,
                "terminal_observer_resource_id": observer_resource_id,
                "terminal_observer_pid": observer_pid,
                "terminal_observer_run_id": observer_run_id,
                "authority_state": "codex-host-retained",
            }
        return_code = process.poll()
        if return_code is not None:
            if current_record.active and worker_pid != process.pid:
                time.sleep(0.01)
                continue
        time.sleep(0.02)
    if request_path.exists():
        manager.reclaim_ephemeral_path(
            request_record.resource_id,
            reason="studio-worker-start-timeout",
            state=RunState.FAILED,
        )
    manager.terminate_owned_process(record.resource_id, graceful_timeout_seconds=1.0)
    current = run_control.read(run_id)
    if current["state"] == "queued":
        run_control.transition(
            run_id,
            "failed",
            actor="px-studio-durable-launcher",
            approved=True,
            checkpoint=current["checkpoint"],
            failure={"code": "worker_start_timeout"},
            operation="worker.start.failed",
        )
    raise TimeoutError("Studio worker did not establish a live durable session")
