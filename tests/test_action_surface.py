from __future__ import annotations

import pytest

from runtime.action_surface import ActionDescriptor, ActionSurface, project_capability_descriptor
from runtime.execution_contract import ExecutionRequest, PolicyDecision, enforce
from runtime.operation_authority import AuthorityRequest, decide_projected_action
from runtime.skill_navigator import CapabilitySummary, navigate


def _surface() -> ActionSurface:
    return ActionSurface((
        ActionDescriptor(
            action_id="cap.open-index",
            capability_id="cap.open-index",
            description="Open the admitted capability index",
            aliases=("open capability index", "show capability index"),
            allowed_roles=("operator",),
            required_context_fields=("project_id",),
            authority_revision="rev-7",
        ),
    ))


def test_action_surface_is_deterministic_and_non_authoritative() -> None:
    surface = _surface()
    first = surface.resolve("please open capability index", roles=(), available_context_fields=())
    second = surface.resolve("please open capability index", roles=(), available_context_fields=())
    assert first == second
    assert first.status == "candidate"
    assert first.capability_id == "cap.open-index"
    assert first.authority_granted is False
    assert first.descriptor_sha256
    assert first.surface_sha256 == surface.surface_sha256
    assert first.preflight["warnings"] == ["role_prerequisite_unsatisfied", "context_prerequisite_unsatisfied"]


def test_action_surface_rejects_alias_collision() -> None:
    with pytest.raises(ValueError, match="ambiguous action alias"):
        ActionSurface((
            ActionDescriptor("a", "a", "A", aliases=("open it",)),
            ActionDescriptor("b", "b", "B", aliases=("open it",)),
        ))


def test_projected_action_can_narrow_navigation_but_not_authorize() -> None:
    surface = _surface()
    rows = (
        CapabilitySummary("cap.open-index", "Inspect capability catalog", aliases=("capability catalog",)),
        CapabilitySummary("cap.other", "Unrelated operation", aliases=("other",)),
    )
    result = navigate("please open capability index", rows, action_surface=surface)
    assert result.candidates[0].capability_id == "cap.open-index"
    assert "projected action candidate" in result.candidates[0].reasons
    assert len(result.navigation_id) == 64
    assert result.action_surface_sha256 == surface.surface_sha256


def test_execution_contract_revalidates_projection_identity() -> None:
    resolution = _surface().resolve("open capability index", roles=("operator",), available_context_fields=("project_id",))
    request = ExecutionRequest("cap.open-index", ("read_local",), 10, 0)
    policy = PolicyDecision(True, ("read_local",))
    manifest = {"id": "cap.open-index", "status": "admitted", "effects": ["read_local"]}
    decision = enforce(request, policy, manifest, action_resolution=resolution)
    assert decision.approved

    wrong = ExecutionRequest("cap.other", ("read_local",), 10, 0)
    wrong_manifest = {"id": "cap.other", "status": "admitted", "effects": ["read_local"]}
    denied = enforce(wrong, policy, wrong_manifest, action_resolution=resolution)
    assert not denied.approved
    assert "action projection capability mismatch" in denied.reasons


def test_projected_action_never_satisfies_operation_authority() -> None:
    resolution = _surface().resolve("open capability index")
    request = AuthorityRequest(executor="codex-host", effects=("workspace-write",))
    decision = decide_projected_action(request, resolution, capability_id="cap.open-index")
    assert not decision.allowed
    assert "non-read effects require current user approval" in decision.reasons


def test_capability_projection_marks_mutation_without_granting_it() -> None:
    descriptor = project_capability_descriptor(
        {"capability_id": "cap.write", "purpose": "Write", "status": "admitted", "risk": "R3"},
        effects=("write_workspace",),
    )
    assert descriptor.mutating is True
    resolution = ActionSurface((descriptor,)).resolve("cap.write")
    assert resolution.preflight["mutating"] is True
    assert resolution.authority_granted is False


def test_capability_projection_rejects_scalar_alias_field() -> None:
    with pytest.raises(ValueError, match="aliases"):
        project_capability_descriptor({"capability_id": "cap.bad", "purpose": "Bad", "status": "admitted", "aliases": "not-a-list"})
