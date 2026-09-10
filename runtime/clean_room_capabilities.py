"""Executable dispatch and orchestration validation for clean-room controls."""

from __future__ import annotations

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
    """Validate exact operation/contract relationships without executing handlers."""
    from .contracts import SUPPORTED_DIALECT, _admit_schema, _schema_children
    from .input_files import cooperative_deadline, directory_root
    from .numeric_inputs import bounded_text
    from .workflow_inputs import active_skill_declarations, ordered_steps, read_declaration, unique_declarations

    expected = (('panel', 'decision-wayfinding', 'independent-hypothesis-panel', 'contracts/reasoning/independent-hypothesis-panel.schema.json', ()), ('delta', 'skill-admission-controller', 'behavioral-delta-certification', 'contracts/cognitive/behavioral-delta-certificate.schema.json', ()), ('communication', 'context-compactor', 'communication-budget', 'contracts/reasoning/communication-budget.schema.json', ()), ('fleet', 'orchestrate-agent-fleets', 'fleet-readiness', 'contracts/agents/fleet-readiness.schema.json', ()), ('inbox', 'orchestrate-agent-fleets', 'bounded-inbox', 'contracts/agents/fleet-readiness.schema.json', ('fleet',)), ('memory', 'govern-memory-fabric', 'memory-graph-remediation', 'contracts/memory/memory-remediation-plan.schema.json', ()), ('goal', 'long-horizon-progress-ledger', 'durable-goal-transition', 'contracts/project_stream/durable-goal-state.schema.json', ()), ('terminal', 'manage-agent-session-fabric', 'terminal-session-plan', 'contracts/agents/terminal-session-adapter.schema.json', ('goal',)), ('backend-validate', 'dynamic-service-discovery', 'backend-capability-validation', 'contracts/external_capabilities/backend-service-capability.schema.json', ()), ('backend-select', 'dynamic-service-discovery', 'backend-capability-selection', 'contracts/external_capabilities/backend-service-capability.schema.json', ('backend-validate',)), ('shadow', 'engineer-verification-lab', 'shadow-behavior-comparison', 'contracts/cognitive/shadow-behavior-comparison.schema.json', ('delta',)), ('specification', 'tracer-bullet-planning', 'specification-lifecycle-closure', 'contracts/reasoning/specification-lifecycle.schema.json', ('panel', 'shadow')))
    try:
        root = directory_root(root)
        deadline = cooperative_deadline()
        payload = read_declaration(root, "orchestration/workflows/clean-room-capability-controls.yaml", deadline=deadline)
        workflows = unique_declarations(payload.get("workflows"), "id", maximum=256)
        if payload.get("schema_version") != "1.0" or payload.get("registry") != "registry/workflow_execution_bindings.json" or tuple(workflows) != ("clean-room-capability-controls",):
            raise ValueError("clean-room workflow envelope mismatch")
        workflow = workflows["clean-room-capability-controls"]
        steps = ordered_steps(workflow.get("steps"))
        actual = tuple((step["id"], step["skill"], step.get("operation"), step.get("contract"), tuple(step["depends_on"])) for step in steps)
        if actual != expected or {step["operation"] for step in steps} != set(OPERATIONS):
            raise ValueError("clean-room operation contract or order mismatch")
        if any(step.get("runtime_binding") != "runtime.clean_room_capabilities:" + step["operation"] for step in steps):
            raise ValueError("clean-room runtime binding does not match its operation")
        if workflow.get("effects") != ["read_local"]:
            raise ValueError("clean-room declared effects mismatch")
        bounded_text(workflow.get("failure_policy"), "failure policy", maximum=4096)
        active = active_skill_declarations(root, deadline=deadline)
        if any(step["skill"] not in active for step in steps):
            raise ValueError("clean-room skill is not declared active or admitted")
        for relative in sorted({step["contract"] for step in steps}):
            schema = read_declaration(root, relative, deadline=deadline)
            identity = "urn:engineering-loop-bootstrap:contract:" + relative.removeprefix("contracts/").removesuffix(".schema.json").replace("/", ":")
            if schema.get("$schema") != SUPPORTED_DIALECT or schema.get("$id") != identity:
                raise ValueError("clean-room schema identity mismatch")
            pending = [schema]
            while pending:
                rule = pending.pop()
                if "$ref" in rule:
                    raise ValueError("clean-room contract profile requires self-contained schemas")
                if "pattern" in rule:
                    bounded_text(rule["pattern"], "clean-room schema pattern", maximum=128, strip=False)
                pending.extend(_schema_children(rule))
            _admit_schema(schema, root / relative, root / "contracts")
    except (OSError, ValueError, TypeError, OverflowError):
        return {"valid": False, "workflow": "clean-room-capability-controls", "operation_count": None, "errors": ["invalid bounded clean-room workflow declarations"], "authority_granted": False}
    return {"valid": True, "workflow": "clean-room-capability-controls", "operation_count": len(steps), "errors": [], "authority_granted": False, "evidence_level": "structural-declarations; handler behavior and current admission require separate proof"}
