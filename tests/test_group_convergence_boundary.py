from dataclasses import replace
import pytest
from runtime.model_convergence import BranchObservation, EvidenceItem, converge, critique_edges
from runtime.work_disposition import WorkDisposition, settle_boundary
from tests.test_model_group_preparation import prepared


def observations(group, shared=False):
    return [BranchObservation(model, "supported", "a" * 64,
        (EvidenceItem("evidence:" + model, "independent_observation", "shared" if shared else model),), True, True)
        for model in group.model_ids]


def test_actual_group_independent_quorum_and_shared_origin_collapse(tmp_path):
    group, _, _, _ = prepared(3, tmp_path)
    result = converge(group, observations(group))
    assert result["status"] == "PASS"
    assert result["authority_granted"] is False
    shared = converge(group, observations(group, shared=True))
    assert shared["status"] == "INDETERMINATE"
    assert shared["effective_independent_count"] == 1


@pytest.mark.parametrize("mutation", ["uncontained", "failed", "missing", "duplicate", "derived", "dissent"])
def test_unproven_or_incomplete_group_never_converges(tmp_path, mutation):
    group, _, _, _ = prepared(3, tmp_path)
    rows = observations(group)
    if mutation == "uncontained":
        rows = [replace(row, containment_proven=False) for row in rows]
    elif mutation == "failed":
        rows = [replace(row, state="failed") for row in rows]
    elif mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[1] = rows[0]
    elif mutation == "derived":
        rows = [replace(row, evidence=(EvidenceItem("derived", "derived", row.model_id),)) for row in rows]
    else:
        rows[1] = replace(rows[1], conclusion="opposed")
    if mutation in {"missing", "duplicate"}:
        with pytest.raises(ValueError):
            converge(group, rows)
    else:
        assert converge(group, rows)["status"] == "INDETERMINATE"


def test_terminal_work_denominator_is_explicit_and_contract_valid():
    result = settle_boundary(["a", "b"], [WorkDisposition("a", "completed", "verified"), WorkDisposition("b", "blocked", "missing native evidence", "evidence:b")])
    assert len(result["dispositions"]) == 2
    with pytest.raises(ValueError):
        settle_boundary(["a", "b"], [WorkDisposition("a", "completed", "verified")])
    with pytest.raises(ValueError):
        WorkDisposition("b", "blocked", "unowned blocker")


def test_critique_graph_is_sparse_and_bounded():
    ids = tuple(str(i) for i in range(12))
    assert len(critique_edges(ids)) == 24
    assert all(source != target for source, target in critique_edges(ids))


def test_committed_native_artifact_without_attestation_stays_not_admitted(tmp_path):
    from runtime.model_convergence import converge_committed_group
    from runtime.model_branch_artifacts import commit_branch_artifact
    from runtime.model_group_preparation import member_attachment, member_execution_input
    from runtime.trusted_evidence import TrustedEvidenceResolver
    from tests.test_model_group_preparation import plan_for
    group, _, _, preparation = prepared(1, tmp_path)
    plan = plan_for(group, preparation)
    model = group.model_ids[0]
    _, member = member_attachment(plan.as_dict(), model)
    invocation = member_execution_input(plan.as_dict(), member)
    artifact = commit_branch_artifact(tmp_path, plan.as_dict(), invocation, {"answer": "retained output"}, run_id="native-branch")
    store = tmp_path / "evidence-store"
    store.mkdir()
    policy = tmp_path / "trust-policy.json"
    policy.write_text("{}", encoding="utf-8")
    resolver = TrustedEvidenceResolver(store, policy)
    result = converge_committed_group(tmp_path, plan, {model: artifact}, {model: None}, resolver=resolver, accepted_producers=set(), actor_id="fixture-owner", containment_proofs={model: {"proven": True}})
    assert result["convergence"]["status"] == "INDETERMINATE"
    assert result["boundary"]["dispositions"][0]["state"] == "blocked"
    assert result["authority_granted"] is False
