"""Autonomous terminal publisher for detached Agent and Workflow Studio runs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import time
import hashlib

from .agent_runtime import AgentRuntimeController
from .resource_lifecycle import ResourceManager
from .studio_run_control import TERMINAL_STATES
from .studio_worker_launch import finalize_studio_run_if_worker_exited
from .workflow_studio import WorkflowStudio


def _wait_for_observer_binding(
    manager: ResourceManager,
    *,
    observer_run_id: str,
    kind: str,
    launch_nonce: str,
    timeout_seconds: float = 8.0,
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
    try:
        while True:
            state = finalize_studio_run_if_worker_exited(
                state_root=state_root,
                manager=manager,
                authority=controller.authority,
                run_control=controller.run_control,
                run_id=args.run_id,
            )
            if str(state["state"]) in TERMINAL_STATES or str(state["state"]) == "paused":
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
