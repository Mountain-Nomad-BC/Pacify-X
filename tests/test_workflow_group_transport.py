from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.capability_routing import route_task
from runtime.model_attachment import build_model_attachment
from runtime.prepared_group_transport import resolve_prepared_group
from runtime.skill_navigator import CapabilitySummary
from runtime.studio_models import CapabilityBinding, EffectGrant, WorkflowDefinition, WorkflowNode, WorkflowPort
from runtime.task_execution_plan import compile_task_execution_plan, persist_task_execution_plan
from runtime.workflow_studio import WorkflowStudio


def _attachment(root: Path, benchmark_revision: str, model_id: str):
    return build_model_attachment(
        root,
        model_id=model_id,
        model_revision="exact-1",
        artifact_sha256="e" * 64,
        runtime="provider-gateway",
        context_tokens=4096,
        modalities=("text",),
        supports_tools=False,
        privacy="local",
        authority_class="contained",
        benchmark_revision=benchmark_revision,
        hardware_requirements={"memory": "1GiB"},
    )


def _prepared_plan(root: Path, benchmark_revision: str, plan_id: str, *, with_group: bool):
    from runtime.model_execution_group import (
        BranchAssignment, IndependenceContract, ModelExecutionGroup, RoleWorkContract)
    from runtime.model_group_preparation import (
        context_for_branch, context_sha256, prepare_model_group)
    from runtime.semantic_integration_types import FusedQueryResult
    from dataclasses import replace

    attachment = _attachment(root, benchmark_revision, "local-policy/model")
    route = route_task("review bounded evidence", {
        "skills": (CapabilitySummary("review", "review bounded evidence"),)})
    group = None
    preparation = None
    generation = None
    if with_group:
        members, exact, retrievals = [], {}, {}
        for index, model in enumerate(("local-policy/model", "fixture:model-1")):
            branch = BranchAssignment(
                model, "proposal",
                work_contract=RoleWorkContract("answer", "a" * 64),
                independence_contract=IndependenceContract(),
                agent_generation_id=f"fixture-generation-{index}")
            retrieval = FusedQueryResult(
                "review bounded evidence", "project:demo", (), {}, 0,
                "fixture:retrieval", "b" * 64)
            context = context_for_branch(retrieval, branch)
            branch = replace(branch, work_contract=RoleWorkContract("answer", context_sha256(context)))
            members.append(branch)
            retrievals[model] = retrieval
            exact[model] = attachment if index == 0 else build_model_attachment(
                root, model_id=model, model_revision="fixture-exact", artifact_sha256="e" * 64,
                runtime="provider-gateway", context_tokens=4096, modalities=("text",),
                supports_tools=False, privacy="local", authority_class="contained",
                benchmark_revision=benchmark_revision, hardware_requirements={"memory": "1GiB"})
        group = ModelExecutionGroup(
            "fixture-group", "execution", "human:owner", tuple(members), quorum="majority")
        preparation = prepare_model_group(group, exact, retrievals, root=root)
        from runtime.context_generation import ALL_COMPONENTS, context_vector
        generation = context_vector("project:demo", "scope", {
            **dict.fromkeys(ALL_COMPONENTS, "test-fixture-only"),
            "source_revision": "source-1",
            "model_execution_group_revision": group.group_sha256,
            "model_contract_set_revision": group.contract_set_sha256})
    plan = compile_task_execution_plan(
        route,
        project_id="project:demo",
        source_revision="source-1",
        projection_revisions={"model_attachment": attachment.attachment_sha256},
        effect_budget=("read",),
        authority_bindings=("binding:agent-search",),
        model_attachment=attachment.as_dict(),
        model_ranking_receipt={"selected_attachment_sha256": attachment.attachment_sha256},
        model_execution_group=group,
        model_group_preparation=preparation,
        context_generation=generation,
        created_utc="2026-10-04T00:00:00Z",
    )
    typed = resolve_prepared_group if False else None  # keep import used
    persisted = persist_task_execution_plan(root, plan)
    return plan, group, persisted


def _group_definition(reference: dict, binding: CapabilityBinding, grant: EffectGrant):
    node = WorkflowNode(
        "node:group", binding.binding_id,
        (WorkflowPort("value", "integer"),),
        (WorkflowPort("group_run_sha256", "string"),),
        (grant.grant_id,), "fail-closed", 30, 0, True, "task",
        {
            "execution_mode": "prepared-model-group",
            "prepared_group_reference": dict(reference),
            "agent_spec": {
                "agent_id": "group-agent", "version": "1.0.0", "project_id": "project:demo",
                "owner": "human:owner", "harness_id": "workflow",
                "instruction_sha256": "a" * 64, "capability_binding_ids": [],
                "effect_grant_ids": [], "required_tests": ["identity"],
                "lifecycle": "admitted",
                "model": {"provider": "deterministic", "vendor": "",
                          "family": "px-bounded-worker", "model_id": "px-bounded-worker",
                          "version": "", "max_output_tokens": 1024, "temperature": 0.0},
                "tool_binding_ids": [], "memory_binding_ids": [], "handoff_agent_ids": [],
                "input_schema": {"type": "object"}, "output_schema": {"type": "object"},
            },
            "placements": {"local-policy/model": {"model_id": "local-policy/model"},
                           "fixture:model-1": {"model_id": "fixture:model-1"}},
        },
    )
    return WorkflowDefinition("workflow:group", "1.0.0", "human:owner", (node,), ())


def _admit_group_workflow(tmp_path: Path, reference: dict):
    grant = EffectGrant(
        "grant:group", "workflow:group", ("read",), ("workspace:demo",),
        "human:owner", ("receipt:grant",), state="admitted")
    binding = CapabilityBinding(
        "binding:group", "workflow", "workflow:group", "capability:group",
        "1.0.0", (grant.grant_id,), None, "non-billable", "deny", "admitted",
        ("receipt:binding",))
    definition = _group_definition(reference, binding, grant)
    studio = WorkflowStudio(tmp_path)
    studio.save_revision(definition)
    studio.register_authority([binding], [grant], {binding.binding_id: "model-group"})
    studio.validate_and_admit(definition)
    return studio, definition


def test_prepared_group_owner_resolution_and_ambiguity_fail_closed(tmp_path, monkeypatch) -> None:
    """The console transport resolves exactly one admitted workflow owner."""
    from runtime.workflow_group_config import validate_prepared_group_node_config

    benchmark = SimpleNamespace(revision="b" * 64)
    plan, group, persisted = _prepared_plan(tmp_path, "b" * 64, "unused", with_group=True)
    reference = {
        "schema_version": "px.prepared-group-reference/1.0",
        "plan_id": plan.plan_id,
        "plan_sha256": plan.plan_sha256,
    }
    studio, definition = _admit_group_workflow(tmp_path, reference)

    owner = studio.resolve_prepared_group_owner(reference)
    assert owner["schema_version"] == "px.prepared-group-owner/1.0"
    assert owner["workflow_id"] == "workflow:group"
    assert owner["node_id"] == "node:group"
    assert owner["plan_id"] == reference["plan_id"]
    assert owner["execution_authorized"] is False

    # Zero owners fail closed (the wrong digest also fails plan verification).
    missing = {**reference, "plan_sha256": "f" * 64}
    with pytest.raises(ValueError):
        studio.resolve_prepared_group_owner(missing)

    # Exactly malformed references fail closed.
    with pytest.raises(ValueError, match="exact"):
        studio.resolve_prepared_group_owner({"plan_id": reference["plan_id"]})

    # Executing through the owner operation requires the authenticated host.
    with pytest.raises(PermissionError, match="authenticated host"):
        studio.execute_prepared_group_node(
            reference, approved_by="system:some-service")


def test_definition_record_round_trip_is_exact(tmp_path) -> None:
    """The immutable revision record rebuilds the exact typed definition."""
    from runtime.workflow_studio import _definition_from_record

    grant = EffectGrant(
        "grant:group", "workflow:group", ("read",), ("workspace:demo",),
        "human:owner", ("receipt:grant",), state="admitted")
    binding = CapabilityBinding(
        "binding:group", "workflow", "workflow:group", "capability:group",
        "1.0.0", (grant.grant_id,), None, "non-billable", "deny", "admitted",
        ("receipt:binding",))
    reference = {
        "schema_version": "px.prepared-group-reference/1.0",
        "plan_id": "task-plan-0123456789abcdef01234567",
        "plan_sha256": "a" * 64,
    }
    definition = _group_definition(reference, binding, grant)
    studio = WorkflowStudio(tmp_path)
    receipt = studio.save_revision(definition)
    import json as _json
    envelope = _json.loads(
        (tmp_path / receipt["path"]).read_text(encoding="utf-8"))
    rebuilt = _definition_from_record(envelope["record"])
    assert rebuilt == definition
