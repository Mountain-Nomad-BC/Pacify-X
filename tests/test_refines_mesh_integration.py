import pytest

from runtime.model_execution_group import build_execution_group


@pytest.mark.parametrize("count", [1, 3, 5, 7, 12])
def test_required_mesh_cardinalities(count):
    group = build_execution_group("g", "execution", "owner", proposal_models=tuple(f"m{i}" for i in range(count)))
    assert group.branch_count == count


def test_generation_bound_verdict_invalidates_changed_dependency():
    from runtime.generation_bound_verdict import create_verdict, verdict_is_current
    verdict = create_verdict(candidate_sha256="a" * 64, dependencies={"task_plan": "b" * 64},
                             verifier_revision="v1", evidence_sha256=("c" * 64,), status="PASS")
    assert verdict_is_current(verdict, "a" * 64, {"task_plan": "b" * 64})
    assert not verdict_is_current(verdict, "a" * 64, {"task_plan": "d" * 64})


def test_missing_containment_cannot_be_counted_as_independent_convergence():
    from runtime.model_convergence import EvidenceItem, BranchObservation, converge
    group = build_execution_group("g", "execution", "owner", proposal_models=("a", "b"), quorum="all")
    rows = tuple(BranchObservation(model_id=m, conclusion="yes", artifact_sha256="a" * 64,
                 evidence=(EvidenceItem(m, "independent_observation", m),), isolation_proven=True,
                 containment_proven=False) for m in group.model_ids)
    result = converge(group, rows, minimum_independent=2)
    assert result["status"] == "INDETERMINATE"
    assert result["authority_granted"] is False


def contracted_group(count):
    from runtime.model_execution_group import ModelExecutionGroup, BranchAssignment, RoleWorkContract, IndependenceContract
    return ModelExecutionGroup("contracted", "execution", "owner", tuple(
        BranchAssignment(f"m{i}", "proposal", work_contract=RoleWorkContract("answer", "a" * 64),
                         independence_contract=IndependenceContract(), agent_generation_id=f"generation-{i}")
        for i in range(count)), quorum="majority")


def task_plan(group):
    from runtime.capability_routing import route_task, compile_route_plan
    from runtime.skill_navigator import CapabilitySummary
    route = route_task("map repository", {"skills": [CapabilitySummary("skill:map", "map repository source",
                       capability_tags=("repository", "map"), triggers=("map repository",))]})
    return compile_route_plan(route, project_id="px", source_revision="source", projection_revisions={"semantic": "revision"},
                              effect_budget=("read_local",), authority_bindings=("owner",), model_execution_group=group,
                              created_utc="2026-10-04T00:00:00Z")


@pytest.mark.parametrize("count", [1, 3, 5, 7, 12])
def test_zero_token_scenario_through_normal_route_plan_and_verdict(count):
    from runtime.deterministic_model_stub import run_control_plane_scenario
    from runtime.task_execution_plan import task_execution_plan_from_dict, validate_task_execution_plan
    group = contracted_group(count)
    plan = task_plan(group)
    recovered = task_execution_plan_from_dict(plan.as_dict())
    assert validate_task_execution_plan(recovered)["valid"]
    result = run_control_plane_scenario(recovered, dict.fromkeys(group.model_ids, "same conclusion"),
              containment_by_model=dict.fromkeys(group.model_ids, True), minimum_independent=min(2, count))
    assert result["convergence"]["status"] == "PASS"
    assert result["verdict"]["dependencies"]["model_execution_group"] == group.group_sha256
    assert result["authority_granted"] is False
    assert result["testbed_only"] is True


def test_correlated_origins_and_failed_members_never_disappear():
    from runtime.deterministic_model_stub import run_control_plane_scenario
    group = contracted_group(5)
    result = run_control_plane_scenario(task_plan(group), dict.fromkeys(group.model_ids, "answer"),
        containment_by_model=dict.fromkeys(group.model_ids, True), origin_by_model=dict.fromkeys(group.model_ids, "same-origin"))
    assert result["convergence"]["effective_independent_count"] == 1
    assert result["convergence"]["status"] == "INDETERMINATE"
    loss = run_control_plane_scenario(task_plan(group), dict.fromkeys(group.model_ids, "answer"),
        containment_by_model=dict.fromkeys(group.model_ids, True), states={"m0": "killed", "m1": "starved", "m2": "failed"})
    assert loss["convergence"]["declared_count"] == 5
    assert loss["convergence"]["not_admitted"] == ["m0", "m1", "m2"]
    assert loss["convergence"]["status"] == "INDETERMINATE"
    assert len(loss["boundary"]["dispositions"]) == 5


def test_temporary_exception_expires_and_generation_changes_disable_it():
    from runtime.governed_exception import create_exception, exception_is_active
    e = create_exception(exception_id="e", scope="read", owner="owner", reason="test", generation_sha256="a" * 64,
                         evidence_sha256="b" * 64, expires_utc="2026-10-05T00:00:00Z", supersession_condition="revision change")
    args = dict(scope="read", generation_sha256="a" * 64, now="2026-10-04T00:00:00Z")
    assert exception_is_active(e, **args)
    assert not exception_is_active(e, **{**args, "generation_sha256": "c" * 64})
    assert not exception_is_active(e, **{**args, "now": e["expires_utc"]})
    assert not exception_is_active(e, **args, superseded_ids=("e",))


def test_diverse_portfolio_preserves_canonical_manual_primary_and_denials():
    from runtime.model_route_state import RouteCandidateRecord, build_route_decision
    from runtime.models import select_execution_portfolio
    rows = tuple(RouteCandidateRecord(f"m{i}", 10-i, 10-i, i+1, "deny" if i == 4 else "admit") for i in range(5))
    decision = build_route_decision(request_id="r", task_class="coding", subject_ids=("python",),
        policy_sha256="a" * 64, policy_semantic_sha256="b" * 64, phase="freeze", candidates=rows,
        primary_model_id="m0", dispatch_state="dispatch")
    selected = select_execution_portfolio(decision, {"m0": {"family": "x"}, "m1": {"family": "x"},
        "m2": {"family": "y"}, "m3": {"family": "z"}}, target_members=3, minimum_members=3)
    assert selected.selected_model_ids == ("m0", "m2", "m3")
    assert selected.record()["selected_model_ids"] == ["m0", "m2", "m3"]
    assert selected.primary_model_id == "m0" and selected.challenger_model_id == "m2"
    assert selected.authority_granted is False


def test_group_recovery_cannot_accept_forged_derived_values():
    from runtime.model_execution_group import read_execution_group
    group = contracted_group(5)
    row = group.as_mapping()
    row["quorum_size"] = 1
    with pytest.raises(ValueError):
        read_execution_group(row)


def test_canonical_plan_schema_accepts_mesh_and_rejects_extra_authority():
    from pathlib import Path
    from runtime.contracts import validate_instance
    schema = Path(__file__).resolve().parents[1] / "contracts/task_execution_plan.schema.json"
    plan = task_plan(contracted_group(5)).as_dict()
    validate_instance(plan, schema)
    plan["model_execution_group"]["authority_granted"] = True
    with pytest.raises(ValueError):
        validate_instance(plan, schema)


def test_normal_reasoning_panel_routes_typed_correlation_without_legacy_downgrade():
    from runtime.reasoning_controls import run_independent_hypothesis_panel
    rows = [dict(model_id=f"m{i}", conclusion="answer", context_sha256="a" * 64,
                 artifact_sha256="b" * 64, agent_generation_id=f"gen{i}", isolated=True, containment_proven=True,
                 evidence_items=[dict(evidence_id=f"observation{i}", kind="independent_observation", origin_id="shared")])
            for i in range(3)]
    result = run_independent_hypothesis_panel(rows)
    assert result["converged"] is False
    assert result["convergence_receipt"]["effective_independent_count"] == 1
    rows[0].pop("evidence_items")
    with pytest.raises(ValueError, match="downgrade"):
        run_independent_hypothesis_panel(rows)


def test_role_contracts_are_required_for_independent_count():
    from runtime.model_convergence import converge, BranchObservation, EvidenceItem
    group = build_execution_group("g", "execution", "owner", proposal_models=("a", "b"), quorum="all")
    rows = [BranchObservation(m, "same", "a" * 64, (EvidenceItem(m, "independent_observation", m),), True, True)
            for m in group.model_ids]
    assert converge(group, rows)["eligible_count"] == 0


def test_sparse_critique_balances_fanout_without_self_edges():
    from collections import Counter
    from runtime.model_convergence import critique_edges
    edges = critique_edges(tuple(f"m{i}" for i in range(5)))
    assert len(edges) == 10 and all(a != b for a, b in edges)
    assert set(Counter(a for a, _ in edges).values()) == {2}
    assert set(Counter(b for _, b in edges).values()) == {2}
