"""Authority-preserving adapter from Agency selection to Studio run control."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class StudioAgentRequest:
    schema_version: str
    specialist_id: str
    specialist_revision: str
    allowed_capabilities: tuple[str, ...]
    agency_route_receipt_sha256: str
    task_plan_id: str
    task_plan_sha256: str
    authority: tuple[str, ...]
    budgets: Mapping[str, int]
    studio_executor: str
    agency_executes_directly: bool
    request_sha256: str


def validate_agency_selection(
    selection: Mapping[str, object], registry: Mapping[str, object]
) -> dict[str, object]:
    errors: list[str] = []
    agents = {
        str(item.get("agent_id")): item
        for item in registry.get("agents", ())
        if isinstance(item, Mapping)
    }
    primary = str(selection.get("primary_agent", ""))
    if not selection.get("valid"):
        errors.append("agency_selection_invalid")
    if selection.get("authority_granted") is not False:
        errors.append("agency_selection_must_not_grant_authority")
    if primary not in agents:
        errors.append("unknown_specialist")
    if not str(selection.get("route_receipt_sha256", "")):
        errors.append("agency_route_receipt_missing")
    if primary and not any(
        isinstance(item, Mapping) and item.get("agent_id") == primary
        for item in selection.get("score_evidence", ())
    ):
        errors.append("selected_specialist_missing_score_evidence")
    return {"valid": not errors, "errors": tuple(errors), "agent": agents.get(primary)}


def compile_studio_agent_request(
    selection: Mapping[str, object],
    registry: Mapping[str, object],
    task_plan: object,
    *,
    requested_authority: tuple[str, ...],
    available_authority: tuple[str, ...],
    budgets: Mapping[str, int],
    budget_ceilings: Mapping[str, int],
) -> StudioAgentRequest:
    validation = validate_agency_selection(selection, registry)
    if not validation["valid"]:
        raise ValueError("invalid Agency selection: " + ",".join(validation["errors"]))
    agent = validation["agent"]
    assert isinstance(agent, Mapping)
    authority = tuple(sorted(set(map(str, requested_authority))))
    if not authority or not set(authority) <= set(map(str, available_authority)):
        raise PermissionError("Agency-to-Studio translation widens authority")
    normalized_budgets = {str(key): int(value) for key, value in sorted(budgets.items())}
    if not normalized_budgets or any(
        value < 1 or value > int(budget_ceilings.get(key, 0))
        for key, value in normalized_budgets.items()
    ):
        raise PermissionError("Agency-to-Studio translation widens or omits budget")
    plan = task_plan.as_dict() if hasattr(task_plan, "as_dict") else dict(task_plan)
    plan_id = str(plan.get("plan_id", ""))
    plan_sha = str(plan.get("plan_sha256", ""))
    if not plan_id or len(plan_sha) != 64:
        raise ValueError("exact task plan binding is required")
    revision_payload = {
        "agent_id": agent.get("agent_id"),
        "body_sha256": agent.get("body_sha256"),
        "manifest_sha256": agent.get("manifest_sha256"),
    }
    if any(len(str(revision_payload[key] or "")) != 64 for key in ("body_sha256", "manifest_sha256")):
        raise ValueError("specialist revision is unpinned")
    specialist_revision = _digest(revision_payload)
    base = {
        "schema_version": "px.agency-studio-agent-request/1.0",
        "specialist_id": str(agent["agent_id"]),
        "specialist_revision": specialist_revision,
        "allowed_capabilities": tuple(
            sorted(set(map(str, agent.get("capabilities", ()))))
        ),
        "agency_route_receipt_sha256": str(selection["route_receipt_sha256"]),
        "task_plan_id": plan_id,
        "task_plan_sha256": plan_sha,
        "authority": authority,
        "budgets": normalized_budgets,
        "studio_executor": "runtime.studio_run_control.DurableRunControl.create",
        "agency_executes_directly": False,
    }
    return StudioAgentRequest(**base, request_sha256=_digest(base))


def submit_studio_agent_request(controller: object, request: StudioAgentRequest):
    """Submit only through Studio's existing durable run-control owner."""
    create = getattr(controller, "create", None)
    if not callable(create):
        raise TypeError("Studio DurableRunControl owner is required")
    return create(
        kind="agent",
        subject_id=request.specialist_id,
        version=f"agency-{request.specialist_revision[:12]}",
        owner="agency-studio-adapter",
        revision_sha256=request.specialist_revision,
        request_sha256=request.request_sha256,
        checkpoint={
            "phase": "queued_from_agency",
            "task_plan_id": request.task_plan_id,
            "task_plan_sha256": request.task_plan_sha256,
            "authority": list(request.authority),
            "budgets": dict(request.budgets),
        },
    )
