from __future__ import annotations

from dataclasses import replace

import pytest

from runtime.agency_studio_adapter import (
    compile_studio_agent_request,
    submit_studio_agent_request,
)


H = "a" * 64


def registry(**changes):
    agent = {
        "agent_id": "agency.engineer",
        "body_sha256": H,
        "manifest_sha256": "b" * 64,
        "capabilities": ["coding", "review"],
    }
    agent.update(changes)
    return {"agents": [agent]}


def selection(**changes):
    value = {
        "valid": True,
        "primary_agent": "agency.engineer",
        "authority_granted": False,
        "route_receipt_sha256": "c" * 64,
        "score_evidence": [{"agent_id": "agency.engineer", "score": 80}],
    }
    value.update(changes)
    return value


def compile_request(**changes):
    values = {
        "requested_authority": ("read",),
        "available_authority": ("read", "write"),
        "budgets": {"tool_calls": 2},
        "budget_ceilings": {"tool_calls": 3},
    }
    values.update(changes)
    return compile_studio_agent_request(
        selection(),
        registry(),
        {"plan_id": "plan", "plan_sha256": H},
        **values,
    )


def test_selection_compiles_to_exact_nonexecuting_studio_request():
    request = compile_request()
    assert request.specialist_id == "agency.engineer"
    assert request.allowed_capabilities == ("coding", "review")
    assert request.studio_executor.endswith("DurableRunControl.create")
    assert request.agency_executes_directly is False


def test_unknown_unpinned_authority_and_budget_fail_closed():
    with pytest.raises(ValueError, match="unknown_specialist"):
        compile_studio_agent_request(
            selection(primary_agent="missing"), registry(), {"plan_id": "plan", "plan_sha256": H},
            requested_authority=("read",), available_authority=("read",), budgets={"calls": 1}, budget_ceilings={"calls": 1},
        )
    with pytest.raises(ValueError, match="unpinned"):
        compile_studio_agent_request(
            selection(), registry(body_sha256=""), {"plan_id": "plan", "plan_sha256": H},
            requested_authority=("read",), available_authority=("read",), budgets={"calls": 1}, budget_ceilings={"calls": 1},
        )
    with pytest.raises(PermissionError, match="widens authority"):
        compile_request(requested_authority=("delete",))
    with pytest.raises(PermissionError, match="widens or omits budget"):
        compile_request(budgets={"tool_calls": 4})


def test_submission_calls_only_existing_studio_owner():
    class Controller:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return {"run_id": "run-fixture", **kwargs}

    controller = Controller()
    request = compile_request()
    result = submit_studio_agent_request(controller, request)
    assert result["run_id"] == "run-fixture"
    assert len(controller.calls) == 1
    assert controller.calls[0]["checkpoint"]["task_plan_sha256"] == H
    tampered = replace(request, agency_executes_directly=True)
    assert tampered.agency_executes_directly  # No method exists that executes it.
