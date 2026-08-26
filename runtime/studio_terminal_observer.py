"""Autonomous terminal publisher for detached Agent and Workflow Studio runs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import time
import hashlib
from collections.abc import Callable

from .agent_runtime import AgentRuntimeController
from .file_lock import FileLockTimeout
from .resource_lifecycle import ResourceManager, RunState
from .studio_models import write_json_atomic
from .studio_run_control import TERMINAL_STATES
from .studio_worker_launch import finalize_studio_run_if_worker_exited
from .workflow_studio import WorkflowStudio


def _retryable_finalize_error(error: Exception) -> bool:
    """Classify only bounded I/O contention and durable CAS races for retry."""
    return isinstance(error, FileLockTimeout) or (
        isinstance(error, OSError) and not isinstance(error, PermissionError)
    ) or (
        isinstance(error, ValueError)
        and str(error).startswith("illegal durable run transition:")
    )


def _wait_for_worker_handoff(
    binding_path: Path,
    *,
    timeout_seconds: float = 30.0,
    poll_seconds: float = 0.02,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> bool:
    """Fence terminal inspection until the durable worker publishes its handoff.

    A Windows virtual-environment launcher may exit before the interpreter has
    rebound the registered process record.  The worker writes this run-unique
    binding only after the rebind and request cleanup succeed.  Its signature
    and exact worker identity are verified by the finalization owner; this
    helper only prevents the observer from mistaking the exited launcher for
    the durable worker during that bounded handoff.
    """

    deadline = clock() + max(0.0, timeout_seconds)
    while not binding_path.is_file():
        if clock() >= deadline:
            return False
        sleeper(max(0.001, poll_seconds))
    return True


def _wait_for_observer_binding(
    manager: ResourceManager,
    *,
    observer_run_id: str,
    kind: str,
    launch_nonce: str,
    timeout_seconds: float = 30.0,
):
    """Wait for the launcher to publish this already-started process identity."""
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    while True:
        matches = [
            record
            for record in manager.ledger.load()
            if record.run_id == observer_run_id
            and record.active
            and record.lane_id == f"studio-{kind}-terminal-observer"
            and record.creator == "px-studio-terminal-observer"
        ]
        observer = matches[0] if len(matches) == 1 else None
        if observer is not None:
            binding = hashlib.sha256(
                f"{observer_run_id}\0{kind}\0{launch_nonce}".encode()
            ).hexdigest()
            observer = manager.rebind_current_process(
                observer.resource_id,
                expected_launcher_pid=int(observer.pid or 0),
                expected_run_id=observer_run_id,
                expected_lane_id=f"studio-{kind}-terminal-observer",
                expected_creator="px-studio-terminal-observer",
                launch_binding=binding,
            )
            if observer.pid != os.getpid():
                raise PermissionError("terminal observer process handoff is invalid")
            return observer
        if time.monotonic() >= deadline:
            raise PermissionError("terminal observer resource binding is invalid")
        time.sleep(0.01)


def _reconcile_exited_worker_paths(
    manager: ResourceManager,
    *,
    run_control,
    run_id: str,
    kind: str,
) -> None:
    """Close exact-run ephemeral paths after worker exit, before terminal publication."""
    records = manager.ledger.load()
    workers = [
        record
        for record in records
        if record.run_id == run_id
        and record.lane_id == f"studio-{kind}"
        and record.creator == "px-studio-durable-launcher"
        and record.resource_type == "process"
    ]
    if len(workers) != 1:
        return
    worker = workers[0]
    worker_pid = int(worker.pid or 0)
    if worker_pid <= 0 or not manager.persisted_process_has_exited(
        worker.resource_id, expected_pid=worker_pid
    ):
        return

    state = run_control.read(run_id)
    current = str(state["state"])
    checkpoint = state.get("checkpoint")
    target = (
        str(checkpoint.get("terminal_target") or "")
        if isinstance(checkpoint, dict)
        else ""
    )
    ended_state = (
        # The run remains recoverable, but this exact worker-owned request
        # path has finished its lifecycle and is safe to close permanently.
        RunState.COMPLETED
        if current == "paused"
        else RunState.CANCELLED
        if current in {"cancel_requested", "cancelled"} or target == "cancelled"
        else RunState.COMPLETED
        if target == "succeeded"
        else RunState.FAILED
    )
    for record in records:
        if (
            record.run_id != run_id
            or record.resource_type != "path"
            or not record.active
        ):
            continue
        if record.classification != "ephemeral":
            raise PermissionError(
                "Studio terminal reconciliation encountered a non-ephemeral run path"
            )
        cleanup = manager.reclaim_ephemeral_path(
            record.resource_id,
            reason="studio-worker-exited-run-path-reconciliation",
            state=ended_state,
        )
        if cleanup.resources_reclaimed != 1 or cleanup.errors:
            raise OSError(
                "Studio terminal reconciliation could not close an exact-run path: "
                + "; ".join(cleanup.errors)
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--kind", choices=("agent", "workflow"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--observer-run-id", required=True)
    parser.add_argument("--launch-nonce", required=True)
    args = parser.parse_args(argv)
    if args.observer_run_id != f"studio-finalizer-{args.run_id}-{args.launch_nonce}":
        raise PermissionError("terminal observer launch binding is invalid")
    root = args.root.resolve(strict=True)
    state_root = root / ".engineering-bootstrap" / "studios" / (
        "agents" if args.kind == "agent" else "workflows"
    )
    manager = ResourceManager(state_root / "resources.json")
    observer = _wait_for_observer_binding(
        manager,
        observer_run_id=args.observer_run_id,
        kind=args.kind,
        launch_nonce=args.launch_nonce,
    )
    controller = (
        AgentRuntimeController(root)
        if args.kind == "agent"
        else WorkflowStudio(root)
    )
    exit_code = 0
    first_finalize_error: float | None = None
    diagnostic_path = (
        state_root
        / "sessions"
        / args.run_id
        / "terminal-observer-diagnostic.json"
    )
    worker_binding_path = (
        state_root
        / "sessions"
        / args.run_id
        / "worker-request-cleanup.json"
    )
    try:
        _wait_for_worker_handoff(worker_binding_path)
        while True:
            try:
                _reconcile_exited_worker_paths(
                    manager,
                    run_control=controller.run_control,
                    run_id=args.run_id,
                    kind=args.kind,
                )
                state = finalize_studio_run_if_worker_exited(
                    state_root=state_root,
                    manager=manager,
                    authority=controller.authority,
                    run_control=controller.run_control,
                    run_id=args.run_id,
                )
                first_finalize_error = None
            except Exception as error:
                now = time.monotonic()
                first_finalize_error = first_finalize_error or now
                retrying = _retryable_finalize_error(error) and (
                    now - first_finalize_error < 30.0
                )
                try:
                    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
                    write_json_atomic(
                        diagnostic_path,
                        {
                            "schema_version": "px.studio-terminal-observer-diagnostic/1.0",
                            "authoritative": False,
                            "run_id": args.run_id,
                            "observer_run_id": args.observer_run_id,
                            "error_type": type(error).__name__,
                            "message": str(error)[:500],
                            "retrying": retrying,
                        },
                    )
                except OSError:
                    # Diagnostics are deliberately non-authoritative and must
                    # never suppress the bounded lifecycle retry itself.
                    pass
                if not retrying:
                    raise
                time.sleep(0.1)
                continue
            if str(state["state"]) in TERMINAL_STATES:
                return 0
            if str(state["state"]) == "paused":
                active_workers = [
                    record
                    for record in manager.ledger.load()
                    if record.run_id == args.run_id
                    and record.lane_id == f"studio-{args.kind}"
                    and record.creator == "px-studio-durable-launcher"
                    and record.resource_type == "process"
                    and record.active
                ]
                if not active_workers:
                    return 0
            time.sleep(0.02)
    except BaseException:
        exit_code = 1
        raise
    finally:
        manager.complete_current_process(
            observer.resource_id,
            expected_pid=os.getpid(),
            exit_code=exit_code,
        )


if __name__ == "__main__":
    raise SystemExit(main())
