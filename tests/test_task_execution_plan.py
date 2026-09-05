from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from runtime.capability_routing import compile_route_plan, route_task
from runtime.skill_navigator import CapabilitySummary
from runtime.task_execution_plan import (
    persist_task_execution_plan,
    validate_task_execution_plan,
)
from runtime.execution_contract import execution_request_from_plan


def _route():
    skill = CapabilitySummary(
        "skill:map",
        "map repository source",
        capability_tags=("repository", "map"),
        triggers=("map repository",),
    )
    return route_task("map repository", {"skills": [skill]})


def _plan():
    return compile_route_plan(
        _route(),
        project_id="pacify-x",
        source_revision="source-revision-1",
        projection_revisions={"semantic": "semantic-revision-1"},
        effect_budget=("read_local",),
        authority_bindings=("primitive:task_normalization",),
        created_utc="2026-09-05T00:00:00Z",
    )


def test_router_adapter_compiles_deterministic_immutable_plan() -> None:
    first = _plan()
    second = _plan()
    assert first == second
    assert first.plan_sha256 == second.plan_sha256
    assert validate_task_execution_plan(first)["valid"]
    with pytest.raises(FrozenInstanceError):
        first.project_id = "changed"  # type: ignore[misc]


def test_hash_tampering_and_missing_bindings_fail_closed() -> None:
    plan = _plan()
    assert not validate_task_execution_plan(replace(plan, project_id="changed"))["valid"]
    assert not validate_task_execution_plan(replace(plan, effect_budget=()))["valid"]
    assert not validate_task_execution_plan(replace(plan, authority_bindings=()))["valid"]


def test_stale_source_or_projection_fails_closed() -> None:
    plan = _plan()
    assert not validate_task_execution_plan(
        plan, current_source_revision="source-revision-2"
    )["valid"]
    assert not validate_task_execution_plan(
        plan, current_projection_revisions={"semantic": "semantic-revision-2"}
    )["valid"]


def test_persistence_is_idempotent_but_immutable(tmp_path: Path) -> None:
    plan = _plan()
    target = persist_task_execution_plan(tmp_path, plan)
    assert persist_task_execution_plan(tmp_path, plan) == target
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["project_id"] = "collision"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FileExistsError, match="immutable task plan collision"):
        persist_task_execution_plan(tmp_path, plan)


def test_plan_module_has_no_execution_primitive() -> None:
    source = (Path(__file__).parents[1] / "runtime/task_execution_plan.py").read_text(
        encoding="utf-8"
    )
    forbidden = ("subprocess", "ProviderInvocationGateway", "invoke_harness(")
    assert not any(token in source for token in forbidden)


def test_execution_adapter_preserves_exact_selected_capability_and_effects() -> None:
    plan = _plan()
    request = execution_request_from_plan(plan)
    assert request.capability_id == plan.selected_capabilities[0]
    assert request.effects == plan.effect_budget
