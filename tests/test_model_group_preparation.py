from dataclasses import replace
from pathlib import Path

import pytest

from runtime.model_attachment import build_model_attachment
from runtime.model_execution_group import BranchAssignment, RoleWorkContract, IndependenceContract, ModelExecutionGroup
from runtime.model_group_preparation import context_for_branch, context_sha256, prepare_model_group, member_attachment
from runtime.semantic_integration_types import FusedQueryResult


def prepared(count, root):
    branches, attachments, retrievals = [], {}, {}
    for i in range(count):
        model = f"model-{i}"
        result = FusedQueryResult("map source", "px", (), {}, 0, "fixture:retrieval", "b" * 64)
        branch = BranchAssignment(model, "proposal", work_contract=RoleWorkContract("answer", "a" * 64),
            independence_contract=IndependenceContract(), agent_generation_id=f"generation-{i}")
        pack = context_for_branch(result, branch)
        branch = replace(branch, work_contract=RoleWorkContract("answer", context_sha256(pack)))
        branches.append(branch)
        retrievals[model] = result
        attachments[model] = build_model_attachment(root, model_id=model, model_revision="fixture-exact",
            artifact_sha256="c" * 64, runtime="provider-gateway", context_tokens=4096,
            modalities=("text",), supports_tools=False, privacy="local", authority_class="contained",
            benchmark_revision="d" * 64, hardware_requirements={"memory": "1GiB"})
    group = ModelExecutionGroup("mesh", "execution", "owner", tuple(branches), quorum="majority")
    return group, attachments, retrievals, prepare_model_group(group, attachments, retrievals, root=root)


def plan_for(group, preparation):
    from runtime.context_generation import ALL_COMPONENTS, context_vector
    from runtime.capability_routing import route_task, compile_route_plan
    from runtime.skill_navigator import CapabilitySummary
    route = route_task("map source", {"skills": [CapabilitySummary("map", "map source")]})
    vector = context_vector("px", "scope", {**dict.fromkeys(ALL_COMPONENTS, "test-fixture-only"),
        "source_revision": "source", "model_execution_group_revision": group.group_sha256,
        "model_contract_set_revision": group.contract_set_sha256})
    return compile_route_plan(route, project_id="px", source_revision="source",
        projection_revisions={"semantic": "revision"}, effect_budget=("read",), authority_bindings=("owner",),
        model_execution_group=group, context_generation=vector, model_group_preparation=preparation,
        created_utc="2026-10-04T00:00:00Z")


@pytest.mark.parametrize("count", [1, 3, 5, 7, 12])
def test_exact_members_normal_compiler_and_recovery(count, tmp_path):
    from runtime.task_execution_plan import task_execution_plan_from_dict, validate_task_execution_plan
    group, _, _, preparation = prepared(count, tmp_path)
    plan = plan_for(group, preparation)
    recovered = task_execution_plan_from_dict(plan.as_dict())
    from pathlib import Path
    from runtime.contracts import validate_instance
    validate_instance(recovered.as_dict(), Path("contracts/task_execution_plan.schema.json"))
    assert validate_task_execution_plan(recovered)["valid"]
    for model in group.model_ids:
        attachment, row = member_attachment(recovered.as_dict(), model)
        assert attachment["model_id"] == row["model_id"] == model
    if count > 1:
        with pytest.raises(ValueError, match="explicit member"):
            member_attachment(recovered.as_dict())


def test_missing_swapped_and_context_drift_refused(tmp_path):
    from runtime.model_group_preparation import read_group_preparation
    group, attachments, retrievals, preparation = prepared(3, tmp_path)
    with pytest.raises(ValueError, match="membership"):
        prepare_model_group(group, {group.model_ids[0]: attachments[group.model_ids[0]]}, retrievals)
    record = preparation.as_dict()
    record["members"][0]["attachment"] = record["members"][1]["attachment"]
    with pytest.raises(ValueError, match="attachment identity"):
        read_group_preparation(record, group)
    record = preparation.as_dict()
    record["members"][0]["context"]["query"] = "changed"
    with pytest.raises(ValueError, match="context.*differs"):
        read_group_preparation(record, group)
    from runtime.task_execution_plan import task_execution_plan_from_dict
    orphan = plan_for(group, preparation).as_dict()
    orphan.pop("model_execution_group")
    with pytest.raises(ValueError, match="requires canonical group"):
        task_execution_plan_from_dict(orphan)


def test_live_member_execution_selects_exact_attachment_and_releases(tmp_path, monkeypatch):
    from runtime.agent_runtime import execute_agent_plan
    from runtime.execution_placement import PlacementCapacityLedger, _hash
    group, _, _, preparation = prepared(3, tmp_path)
    plan = plan_for(group, preparation)
    attachment, member = member_attachment(plan.as_dict(), "model-2")
    placement = {"task_plan_sha256": plan.plan_sha256, "model_id": "model-2",
        "model_attachment_sha256": attachment["attachment_sha256"], "context_sha256": member["context_sha256"],
        "selected_device": "cpu", "fallback": {"device": "cpu"}, "reason": "fixture"}
    placement["placement_sha256"] = _hash(placement)
    calls = []
    monkeypatch.setattr(PlacementCapacityLedger, "reserve", lambda self, p, run_id: (
        calls.append(p["model_id"]) or {"reservation_sha256": "e" * 64}))
    monkeypatch.setattr(PlacementCapacityLedger, "release", lambda self, r, outcome_sha256: (
        calls.append("release") or {"released": True}))
    kwargs = dict(run_id="run", cpu_fn=lambda: calls.append("execute"), gpu_fn=lambda batch: None,
                  member_executor=lambda invocation, **placement: calls.append("execute"),
                  current_context_generation=plan.context_generation)
    _, outcome = execute_agent_plan(tmp_path, plan.as_dict(), placement, **kwargs)
    assert calls == ["model-2", "execute", "release"]
    assert outcome["capacity_release"]["released"]
    calls.clear()
    tampered = {**placement, "context_sha256": "f" * 64}
    tampered["placement_sha256"] = _hash({k: v for k, v in tampered.items() if k != "placement_sha256"})
    with pytest.raises(ValueError, match="context differs"):
        execute_agent_plan(tmp_path, plan.as_dict(), tampered, **kwargs)
    assert calls == []


def test_native_member_hardware_route_and_durable_cleanup(tmp_path):
    from datetime import datetime, timezone
    from runtime.agent_runtime import execute_agent_plan
    from runtime.execution_placement import route_hardware, PlacementCapacityLedger
    from runtime.hardware_routing import WorkloadProfile, WorkloadKind, HardwareProfile, BenchmarkEvidence
    group, attachments, retrievals, _ = prepared(3, tmp_path)
    workload = WorkloadProfile(WorkloadKind.TEXT_ANALYSIS, 5, 1024, False, operation_id="member-fixture")
    hardware = HardwareProfile(False, None, None, None, 0, 0, 16 * 1024**3, "windows", 8, 4,
        False, (), (), cuda_executor_available=False)
    benchmark = BenchmarkEvidence(workload.operation_id, hardware.fingerprint, 2.0, 1.0, True, 0,
        datetime.now(timezone.utc).isoformat(), workload_fingerprint=workload.fingerprint)
    original = attachments["model-2"]
    attachments["model-2"] = build_model_attachment(tmp_path, model_id=original.model_id,
        model_revision=original.model_revision, artifact_sha256=original.artifact_sha256,
        runtime=original.runtime, context_tokens=original.context_tokens, modalities=original.modalities,
        supports_tools=False, privacy=original.privacy, authority_class=original.authority_class,
        benchmark_revision=benchmark.revision, hardware_requirements=dict(original.hardware_requirements))
    preparation = prepare_model_group(group, attachments, retrievals, root=tmp_path)
    plan = plan_for(group, preparation)
    kwargs = dict(workload=workload, hardware=hardware, benchmark=benchmark, project_root=tmp_path)
    with pytest.raises(ValueError, match="explicit member"):
        route_hardware(plan.as_dict(), **kwargs)
    with pytest.raises(ValueError, match="benchmark revision"):
        route_hardware(plan.as_dict(), model_id="model-1", **kwargs)
    placement = route_hardware(plan.as_dict(), model_id="model-2", **kwargs)
    assert placement["model_attachment_sha256"] == attachments["model-2"].attachment_sha256
    def failing(invocation, **placement):
        assert invocation.model_id == "model-2"
        assert invocation.context["model_id"] == "model-2"
        raise RuntimeError("fixture workload failure")
    with pytest.raises(RuntimeError, match="fixture workload"):
        execute_agent_plan(tmp_path, plan.as_dict(), placement, run_id="member-fixture",
            cpu_fn=None, gpu_fn=None, member_executor=failing, current_context_generation=plan.context_generation)
    assert PlacementCapacityLedger(tmp_path)._read()["active"] == {}


def test_branch_artifact_registers_before_directory_creation_and_settles_exact_resource(tmp_path, monkeypatch):
    from runtime.model_group_preparation import member_execution_input
    from runtime.model_branch_artifacts import commit_branch_artifact, read_branch_artifact
    from runtime.resource_lifecycle import ResourceManager
    group, _, _, preparation = prepared(1, tmp_path)
    plan = plan_for(group, preparation)
    invocation = member_execution_input(plan.as_dict(), preparation.as_dict()["members"][0])
    original = ResourceManager.register_path
    observed = []
    def registration(self, path, **kwargs):
        if kwargs.get("creator") == "runtime.model_branch_artifacts":
            observed.append(path)
            assert not path.exists(), "artifact custody must precede creation"
        return original(self, path, **kwargs)
    monkeypatch.setattr(ResourceManager, "register_path", registration)
    artifact = commit_branch_artifact(tmp_path, plan.as_dict(), invocation, {"answer": "controlled"}, run_id="artifact-run")
    assert len(observed) == 1
    assert read_branch_artifact(tmp_path, artifact, invocation, run_id="artifact-run")
    record = next(row for row in ResourceManager(tmp_path / ".agentic_engineering_os_px/studios/agents/resources.json").ledger.observe() if row.resource_id == artifact["resource_id"])
    assert record.path_identity is not None and not record.active
    assert record.run_state == "completed" and record.retention_required


def test_interrupted_branch_publication_retains_recoverable_custody_and_denies_retry(tmp_path, monkeypatch):
    import runtime.model_branch_artifacts as owner
    from runtime.model_group_preparation import member_execution_input
    from runtime.resource_lifecycle import ResourceManager
    from runtime.effect_intent import EffectIntentLedger
    from runtime.scope_lease import ScopeLeaseStore
    group, _, _, preparation = prepared(1, tmp_path)
    plan = plan_for(group, preparation)
    invocation = member_execution_input(plan.as_dict(), preparation.as_dict()["members"][0])
    original = owner._publish_exact
    def interrupted(path, raw):
        if path.name == "commitment.json":
            raise OSError("controlled manifest interruption")
        return original(path, raw)
    monkeypatch.setattr(owner, "_publish_exact", interrupted)
    with pytest.raises(OSError, match="manifest interruption"):
        owner.commit_branch_artifact(tmp_path, plan.as_dict(), invocation, {"partial": True}, run_id="partial-run")
    record = next(row for row in ResourceManager(tmp_path / ".agentic_engineering_os_px/studios/agents/resources.json").ledger.observe() if row.creator == "runtime.model_branch_artifacts")
    assert not record.active and record.run_state == "recoverable" and record.retention_required
    assert (Path(record.path) / "output.json").is_file()
    fence = EffectIntentLedger(tmp_path).fence(owner._artifact_intent_key(invocation, "partial-run"))
    assert not fence["retry_safe"] and fence["reconciliation_required"]
    assert not ScopeLeaseStore(tmp_path).active(effect="write")
    with pytest.raises(ValueError, match="reconciliation"):
        owner.commit_branch_artifact(tmp_path, plan.as_dict(), invocation, {"partial": True}, run_id="partial-run")
