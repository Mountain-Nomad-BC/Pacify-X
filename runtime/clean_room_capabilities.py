"""Executable dispatch and orchestration validation for clean-room controls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping

from .agent_fleet_controls import (
    admit_inbox_message,
    evaluate_fleet_readiness,
    plan_terminal_session_action,
)
from .backend_capabilities import (
    select_backend_capabilities,
    validate_backend_capability_model,
)
from .behavioral_certification import (
    certify_behavioral_delta,
    compare_shadow_behavior,
)
from .durable_state import close_specification_lifecycle, transition_durable_goal
from .memory_remediation import plan_memory_graph_remediation
from .reasoning_controls import compact_communication, run_independent_hypothesis_panel


OPERATIONS: dict[str, Callable[..., dict[str, object]]] = {
    "independent-hypothesis-panel": run_independent_hypothesis_panel,
    "behavioral-delta-certification": certify_behavioral_delta,
    "communication-budget": compact_communication,
    "fleet-readiness": evaluate_fleet_readiness,
    "bounded-inbox": admit_inbox_message,
    "memory-graph-remediation": plan_memory_graph_remediation,
    "durable-goal-transition": transition_durable_goal,
    "terminal-session-plan": plan_terminal_session_action,
    "backend-capability-validation": validate_backend_capability_model,
    "backend-capability-selection": select_backend_capabilities,
    "shadow-behavior-comparison": compare_shadow_behavior,
    "specification-lifecycle-closure": close_specification_lifecycle,
}


def run_clean_room_operation(
    operation: str, payload: Mapping[str, object]
) -> dict[str, object]:
    """Execute one side-effect-free operation from an explicit structured payload."""
    handler = OPERATIONS.get(operation)
    if handler is None:
        raise KeyError(f"unknown clean-room operation: {operation}")
    return handler(**dict(payload))


def validate_clean_room_capability_workflow(root: Path) -> dict[str, object]:
    """Validate workflow reachability to every required operation and contract."""
    path = root / "orchestration/workflows/clean-room-capability-controls.yaml"
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "valid": False,
            "errors": [f"workflow unavailable: {type(exc).__name__}: {exc}"],
        }
    workflows = payload.get("workflows", ())
    if (
        len(workflows) != 1
        or workflows[0].get("id") != "clean-room-capability-controls"
    ):
        errors.append("clean-room workflow identity mismatch")
        steps = []
    else:
        steps = workflows[0].get("steps", ())
    operation_ids = {str(step.get("operation")) for step in steps}
    if operation_ids != set(OPERATIONS):
        errors.append(
            f"operation denominator mismatch: declared={len(operation_ids)} runtime={len(OPERATIONS)}"
        )
    step_ids = {str(step.get("id")) for step in steps}
    if len(step_ids) != len(steps):
        errors.append("workflow step IDs are not unique")
    for step in steps:
        contract = root / str(step.get("contract", ""))
        if not contract.is_file():
            errors.append(f"{step.get('id')}: contract missing")
        if str(step.get("runtime_binding")) not in {
            f"runtime.clean_room_capabilities:{operation}" for operation in OPERATIONS
        }:
            errors.append(f"{step.get('id')}: runtime binding is not canonical")
    return {
        "valid": not errors,
        "workflow": "clean-room-capability-controls",
        "operation_count": len(operation_ids),
        "errors": errors,
        "authority_granted": False,
    }
