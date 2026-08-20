"""Independent owned worker for durable Agent and Workflow Studio sessions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Mapping

from .agent_runtime import AgentRuntimeController
from .resource_lifecycle import ResourceManager, RunState
from .studio_api import _workflow
from .studio_authority import StudioAuthorityStore
from .studio_models import digest, write_json_atomic
from .studio_models import AgentSpec
from .studio_run_control import TERMINAL_STATES
from .workflow_studio import WorkflowStudio


def _load_request(path: Path, authority: StudioAuthorityStore) -> dict[str, object]:
    deadline = time.monotonic() + 8.0
    while not path.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not path.is_file():
        raise FileNotFoundError("signed Studio worker request was not published")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise PermissionError("Studio worker request must be an object")
    request = authority.verify_receipt(raw)
    payload = request.get("payload")
    if (
        request.get("schema_version") != "px.studio-worker-request/1.0"
        or not isinstance(payload, Mapping)
        or request.get("payload_sha256") != digest(payload)
    ):
        raise PermissionError("Studio worker request identity is invalid")
    return request


def _execute(
    root: Path,
    kind: str,
    run_id: str,
    request: Mapping[str, object],
    *,
    defer_terminal_publication: bool = False,
) -> None:
    payload = request["payload"]
    assert isinstance(payload, Mapping)
    if kind == "agent":
        controller = AgentRuntimeController(root)
        spec_value = payload.get("spec")
        task = payload.get("task")
        admission = payload.get("admission")
        live_hashes = payload.get("live_hashes")
        if not all(
            isinstance(value, Mapping)
            for value in (spec_value, task, admission, live_hashes)
        ):
            raise ValueError("agent worker payload is incomplete")
        spec = AgentSpec(
            str(spec_value["agent_id"]),
            str(spec_value["version"]),
            str(spec_value["project_id"]),
            str(spec_value["owner"]),
            str(spec_value["harness_id"]),
            str(spec_value["instruction_sha256"]),
            tuple(map(str, spec_value.get("capability_binding_ids", []))),
            tuple(map(str, spec_value.get("effect_grant_ids", []))),
            tuple(map(str, spec_value.get("required_tests", []))),
            str(spec_value.get("lifecycle", "draft")),
            model=dict(spec_value.get("model", {})),
            tool_binding_ids=tuple(
                map(str, spec_value.get("tool_binding_ids", []))
            ),
            memory_binding_ids=tuple(
                map(str, spec_value.get("memory_binding_ids", []))
            ),
            handoff_agent_ids=tuple(
                map(str, spec_value.get("handoff_agent_ids", []))
            ),
            input_schema=dict(spec_value.get("input_schema", {})),
            output_schema=dict(spec_value.get("output_schema", {})),
        )
        record_path = root / str(payload.get("record_path") or "")
        controller._execute_session(
            spec,
            task=task,
            run_id=run_id,
            record_path=record_path,
            admission=admission,
            live_hashes={str(key): str(value) for key, value in live_hashes.items()},
            defer_terminal_publication=defer_terminal_publication,
        )
        return
    if kind == "workflow":
        studio = WorkflowStudio(root)
        definition_value = payload.get("definition")
        inputs = payload.get("inputs")
        approvals = payload.get("approvals")
        if not all(isinstance(value, Mapping) for value in (definition_value, inputs, approvals)):
            raise ValueError("workflow worker payload is incomplete")
        studio.execute(
            _workflow(definition_value),
            inputs,
            {str(key): str(value) for key, value in approvals.items()},
            approval=True,
            run_id=run_id,
            defer_terminal_publication=defer_terminal_publication,
        )
        return
    raise ValueError("unsupported Studio worker kind")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--kind", choices=("agent", "workflow"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    authority = StudioAuthorityStore(root)
    exit_code = 0
    resource_id = ""
    manager: ResourceManager | None = None
    try:
        request = _load_request(args.request, authority)
        if (
            request.get("kind") != args.kind
            or request.get("run_id") != args.run_id
            or int(request.get("expected_pid", 0)) != os.getpid()
        ):
            raise PermissionError("Studio worker launch binding is invalid")
        resource_id = str(request.get("resource_id") or "")
        request_resource_id = str(request.get("request_resource_id") or "")
        state_root = root / ".engineering-bootstrap" / "studios" / ("agents" if args.kind == "agent" else "workflows")
        manager = ResourceManager(state_root / "resources.json")
        record = manager.ledger.get(resource_id)
        if record.pid != os.getpid() or record.run_id != args.run_id or not record.active:
            raise PermissionError("Studio worker resource binding is invalid")
        request_record = manager.ledger.get(request_resource_id)
        if (
            request_record.parent_resource_id != resource_id
            or Path(request_record.path or "").resolve(strict=False) != args.request.resolve(strict=True)
            or request_record.run_id != args.run_id
        ):
            raise PermissionError("Studio worker request resource binding is invalid")
        request_cleanup = manager.reclaim_ephemeral_path(
            request_resource_id,
            reason="studio-worker-request-consumed",
        )
        cleanup = authority.sign_receipt(
            {
                "schema_version": "px.studio-worker-request-cleanup/1.0",
                "run_id": args.run_id,
                "request_sha256": digest(request),
                "request_content_retained": False,
                "cleanup_id": request_cleanup.cleanup_id,
                "worker_resource_id": resource_id,
                "worker_pid": os.getpid(),
                "authority_state": "codex-host-retained",
            }
        )
        write_json_atomic(state_root / "sessions" / args.run_id / "worker-request-cleanup.json", cleanup)
        _execute(
            root,
            args.kind,
            args.run_id,
            request,
            defer_terminal_publication=True,
        )
    except BaseException as error:
        exit_code = 1
        try:
            state_root = root / ".engineering-bootstrap" / "studios" / ("agents" if args.kind == "agent" else "workflows")
            control = (AgentRuntimeController(root).run_control if args.kind == "agent" else WorkflowStudio(root).run_control)
            state = control.read(args.run_id)
            if str(state["state"]) not in TERMINAL_STATES and str(state["state"]) != "finalizing":
                target = "failed"
                control.transition(
                    args.run_id,
                    "finalizing",
                    actor="px-studio-durable-worker",
                    approved=True,
                    checkpoint={
                        **dict(state["checkpoint"]),
                        "terminal_target": target,
                    },
                    failure={"code": type(error).__name__, "message": str(error)[:500]},
                    operation="worker.failed",
                )
        except BaseException:
            pass
    finally:
        if manager is not None and resource_id:
            try:
                defer_worker_closure = False
                state_root = root / ".engineering-bootstrap" / "studios" / (
                    "agents" if args.kind == "agent" else "workflows"
                )
                control = (
                    AgentRuntimeController(root).run_control
                    if args.kind == "agent"
                    else WorkflowStudio(root).run_control
                )
                state = control.read(args.run_id)
                if str(state["state"]) == "finalizing":
                    defer_worker_closure = True
                if not defer_worker_closure:
                    manager.complete_current_process(resource_id, expected_pid=os.getpid(), exit_code=exit_code)
            except BaseException:
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
