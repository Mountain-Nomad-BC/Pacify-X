"""Validated declarative workflow proposals (PC-501)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

try:  # installed package
    from engineering_bootstrap.graphs import validate_orchestration
except ImportError:  # source checkout
    from runtime.graphs import validate_orchestration

from .common import BuilderError, MUTATING_EFFECTS, bounded_unique, proposal_envelope, require_identifier


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    step_id: str
    capability_id: str
    depends_on: tuple[str, ...] = ()
    effects: tuple[str, ...] = ()
    approval_gate: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    max_tool_calls: int
    max_seconds: int
    max_agents: int = 1
    max_test_runners: int = 1


@dataclass(frozen=True, slots=True)
class OrchestrationRequest:
    workflow_id: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    steps: tuple[WorkflowStep, ...]
    stop_conditions: tuple[str, ...]
    resource_budget: ResourceBudget
    version: str = "0.1.0"


def _validated_contracts(
    records: Iterable[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for record in records:
        capability_id = record.get("id")
        if not isinstance(capability_id, str) or not capability_id:
            raise BuilderError("capability contract is missing id")
        if capability_id in result:
            raise BuilderError(f"duplicate capability contract: {capability_id}")
        result[capability_id] = record
    return result


def _is_validated(contract: Mapping[str, object]) -> bool:
    validation = contract.get("validation")
    evidence = contract.get("evidence")
    return (
        contract.get("status") in {"admitted", "active"}
        and isinstance(validation, Mapping)
        and validation.get("failed", 0) == 0
        and isinstance(evidence, Mapping)
        and evidence.get("status") == "current"
    )


def _topological_order(dependencies: Mapping[str, set[str]]) -> tuple[str, ...]:
    pending = {step_id: set(values) for step_id, values in dependencies.items()}
    ordered: list[str] = []
    while pending:
        ready = sorted(step_id for step_id, values in pending.items() if not values)
        if not ready:
            raise BuilderError("workflow contains a dependency cycle")
        for step_id in ready:
            ordered.append(step_id)
            pending.pop(step_id)
        for values in pending.values():
            values.difference_update(ready)
    return tuple(ordered)


def propose_orchestration(
    request: OrchestrationRequest,
    capability_contracts: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    workflow_id = require_identifier(request.workflow_id, "workflow_id")
    workflow_inputs = set(bounded_unique(request.inputs, "inputs", maximum=24))
    outputs = bounded_unique(request.outputs, "outputs", maximum=24)
    steps = bounded_unique(request.steps, "steps", maximum=24)
    stop_conditions = bounded_unique(request.stop_conditions, "stop_conditions", maximum=16)
    budget = request.resource_budget
    if budget.max_tool_calls < 0 or budget.max_seconds < 1:
        raise BuilderError("resource budget requires non-negative tool calls and positive seconds")
    if budget.max_agents < 1 or budget.max_test_runners < 1:
        raise BuilderError("parallelism budgets must be positive")

    contracts = _validated_contracts(capability_contracts)
    by_step: dict[str, WorkflowStep] = {}
    capability_steps: dict[str, list[str]] = {}
    for step in steps:
        require_identifier(step.step_id, "step_id")
        require_identifier(step.capability_id, "capability_id")
        if step.step_id in by_step:
            raise BuilderError(f"duplicate workflow step: {step.step_id}")
        contract = contracts.get(step.capability_id)
        if contract is None:
            raise BuilderError(f"unknown workflow capability: {step.capability_id}")
        if not _is_validated(contract):
            raise BuilderError(f"capability is not admitted with current evidence: {step.capability_id}")
        by_step[step.step_id] = step
        capability_steps.setdefault(step.capability_id, []).append(step.step_id)

    dependencies: dict[str, set[str]] = {
        step_id: set(step.depends_on) for step_id, step in by_step.items()
    }
    for step_id, step in by_step.items():
        unknown = dependencies[step_id] - set(by_step)
        if unknown:
            raise BuilderError(f"{step_id} has unknown dependencies: {', '.join(sorted(unknown))}")
        contract = contracts[step.capability_id]
        for capability_dependency in contract.get("dependencies", ()):
            candidates = capability_steps.get(str(capability_dependency), [])
            if len(candidates) != 1:
                raise BuilderError(
                    f"{step_id} cannot resolve capability dependency {capability_dependency}"
                )
            dependencies[step_id].add(candidates[0])

    # Resolve I/O edges only when one selected producer unambiguously supplies a type.
    for step_id, step in by_step.items():
        contract = contracts[step.capability_id]
        for consumed in contract.get("consumes", ()):
            if consumed in workflow_inputs:
                continue
            producers = sorted(
                other_id
                for other_id, other_step in by_step.items()
                if other_id != step_id
                and consumed in contracts[other_step.capability_id].get("provides", ())
            )
            if len(producers) != 1:
                raise BuilderError(
                    f"{step_id} input {consumed} has {len(producers)} eligible producers"
                )
            dependencies[step_id].add(producers[0])

    order = _topological_order(dependencies)
    available = set(workflow_inputs)
    for step_id in order:
        step = by_step[step_id]
        contract = contracts[step.capability_id]
        missing = sorted(set(contract.get("consumes", ())) - available)
        if missing:
            raise BuilderError(f"{step_id} inputs are unavailable: {', '.join(missing)}")
        available.update(str(value) for value in contract.get("provides", ()))
    missing_outputs = sorted(set(outputs) - available)
    if missing_outputs:
        raise BuilderError("workflow outputs are unavailable: " + ", ".join(missing_outputs))

    estimated_calls = sum(
        int(contracts[step.capability_id].get("cost", {}).get("max_tool_calls", 0))
        for step in steps
    )
    estimated_seconds = sum(
        int(contracts[step.capability_id].get("latency", {}).get("max_seconds", 0))
        for step in steps
    )
    if estimated_calls > budget.max_tool_calls:
        raise BuilderError("workflow exceeds max_tool_calls budget")
    if estimated_seconds > budget.max_seconds:
        raise BuilderError("workflow exceeds max_seconds budget")

    spec_steps: list[dict[str, object]] = []
    approval_gates: list[dict[str, object]] = []
    evidence_steps: list[dict[str, object]] = []
    for step_id in order:
        step = by_step[step_id]
        contract = contracts[step.capability_id]
        declared_effects = tuple(str(value) for value in contract.get("effects", ()))
        effects = step.effects or declared_effects
        if not set(effects) <= set(declared_effects):
            raise BuilderError(f"{step_id} effects exceed capability declaration")
        spec_steps.append(
            {
                "id": step_id,
                "capability": step.capability_id,
                "depends_on": sorted(dependencies[step_id]),
                "effects": sorted(effects),
            }
        )
        if set(effects) & MUTATING_EFFECTS:
            approval_gates.append(
                {
                    "before_step": step_id,
                    "required": True,
                    "gate": step.approval_gate or f"explicit-approval-{step_id}",
                }
            )
        evidence_steps.append(
            {
                "id": f"evidence-{step_id}",
                "after_step": step_id,
                "required": True,
                "status": "current",
            }
        )

    spec = {
        "id": workflow_id,
        "version": request.version,
        "status": "candidate",
        "inputs": sorted(workflow_inputs),
        "outputs": sorted(outputs),
        "steps": spec_steps,
        "parallelism": {
            "max_agents": budget.max_agents,
            "max_test_runners": budget.max_test_runners,
        },
        "stop_conditions": sorted(stop_conditions),
        "resource_budget": {
            "max_tool_calls": budget.max_tool_calls,
            "max_seconds": budget.max_seconds,
        },
    }
    graph_errors = validate_orchestration(spec, contracts.values())
    if graph_errors:
        raise BuilderError("invalid orchestration: " + "; ".join(graph_errors))
    body = {
        "workflow": spec,
        "resolved_order": list(order),
        "io_graph_validated": True,
        "dag_validation": {"valid": True, "errors": []},
        "approval_gates": approval_gates,
        "evidence_steps": evidence_steps,
        "budget_analysis": {
            "known_before_execution": True,
            "estimated_tool_calls": estimated_calls,
            "estimated_seconds": estimated_seconds,
        },
    }
    return proposal_envelope("orchestration", workflow_id, body)
