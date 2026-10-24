"""The N-way model mesh: governed group declaration and branch convergence.

Two properties carry the weight here:

* an N-way fan-out is BOUNDED, attributed and reproducible;
* convergence means substantive agreement, and is never confused with selection.

The adversarial cases matter most: a silent branch must not count as agreement,
formatting noise must not manufacture consensus, and an over-bound fan-out must
be refused rather than quietly clamped.
"""

from __future__ import annotations

import pytest

from runtime.model_branch_contracts import (
    COMPLETED,
    FAILED,
    BranchContractError,
    BranchResult,
    MeshOutcome,
    canonical_digest,
    evaluate_mesh,
)
from runtime.model_execution_group import (
    ANCHOR,
    CALIBRATION,
    CHALLENGER,
    DISCOVERY,
    EXECUTION,
    PROPOSAL,
    BranchAssignment,
    ModelExecutionGroup,
    ModelExecutionGroupError,
    build_execution_group,
)
from runtime.model_execution_group import MAX_MODEL_GROUP_MEMBERS as MAX_CHALLENGER_BRANCHES


def _group(**kwargs) -> ModelExecutionGroup:
    defaults = dict(
        group_id="mesh-1",
        purpose=EXECUTION,
        authority_id="authority-a",
        proposal_models=("m-proposal",),
        challenger_models=("m-b", "m-c"),
    )
    defaults.update(kwargs)
    return build_execution_group(**defaults)


# -- group declaration -------------------------------------------------------


def test_a_multi_branch_mesh_is_admissible() -> None:
    group = _group()
    assert group.branch_count == 3
    assert group.proposals == ("m-proposal",)
    assert group.challengers == ("m-b", "m-c")
    # Declaration order is replay order, so a rebuild is reproducible.
    assert group.model_ids == ("m-proposal", "m-b", "m-c")


def test_fan_out_beyond_the_bound_is_refused_not_clamped() -> None:
    too_many = tuple(f"m-{index}" for index in range(MAX_CHALLENGER_BRANCHES + 1))
    with pytest.raises(ModelExecutionGroupError, match="exceeds the admitted bound"):
        _group(challenger_models=too_many)


def test_exactly_the_bound_is_admissible() -> None:
    exact = tuple(f"m-{index}" for index in range(MAX_CHALLENGER_BRANCHES - 1))
    group = _group(challenger_models=exact)
    assert group.branch_count == MAX_CHALLENGER_BRANCHES


def test_a_group_requires_authority() -> None:
    with pytest.raises(ModelExecutionGroupError, match="authority_id"):
        _group(authority_id="")


def test_a_duplicate_model_may_not_occupy_two_slots() -> None:
    with pytest.raises(ModelExecutionGroupError, match="may not appear twice"):
        _group(proposal_models=("m-a",), challenger_models=("m-a",))


def test_only_execution_groups_claim_outputs() -> None:
    """A discovery run must never be mistaken for a result."""
    assert _group().produces_outputs is True
    assert _group(purpose=DISCOVERY).produces_outputs is False
    assert _group(purpose=CALIBRATION).produces_outputs is False


def test_quorum_sizes_follow_the_declared_rule() -> None:
    assert _group(quorum="any").quorum_size() == 1
    assert _group(quorum="all").quorum_size() == 3
    assert _group(quorum="majority").quorum_size() == 2


def test_group_identity_changes_when_any_replayed_field_changes() -> None:
    base = _group().digest_input()
    assert _group(determinism_seed=7).digest_input() != base
    assert _group(authority_id="other").digest_input() != base
    assert _group(quorum="all").digest_input() != base


def test_unknown_purpose_and_role_are_refused() -> None:
    with pytest.raises(ModelExecutionGroupError, match="purpose"):
        _group(purpose="guess")
    with pytest.raises(ModelExecutionGroupError, match="branch role"):
        BranchAssignment(model_id="m", role="whatever")


def test_boolean_weight_is_refused_rather_than_read_as_one() -> None:
    with pytest.raises(ModelExecutionGroupError, match="non-negative float"):
        BranchAssignment(model_id="m", role=PROPOSAL, weight=True)


# -- branch results and convergence ------------------------------------------


def _results(outputs: dict[str, str]) -> list[BranchResult]:
    return [BranchResult(model_id=mid, state=COMPLETED, output=out)
            for mid, out in outputs.items()]


def test_unanimous_branches_reach_consensus() -> None:
    outcome = evaluate_mesh(
        "mesh-1", 3, "all", _results({"a": "same", "b": "same", "c": "same"})
    )
    assert outcome.consensus_reached is True
    assert outcome.largest_agreement == 3
    assert outcome.agreement_buckets == (("a", "b", "c"),)


def test_divergent_branches_do_not_reach_consensus() -> None:
    outcome = evaluate_mesh(
        "mesh-1", 3, "any", _results({"a": "one", "b": "two", "c": "three"})
    )
    assert outcome.consensus_reached is True  # quorum "any" needs only one
    assert outcome.largest_agreement == 1
    assert outcome.quorum == "any"
    # ...but under majority it must not.
    strict = evaluate_mesh(
        "mesh-1", 3, "majority", _results({"a": "one", "b": "two", "c": "three"})
    )
    assert strict.consensus_reached is False


def test_a_failed_branch_does_not_vote() -> None:
    results = [
        BranchResult(model_id="a", state=COMPLETED, output="same"),
        BranchResult(model_id="b", state=COMPLETED, output="same"),
        BranchResult(model_id="c", state=FAILED, detail="provider timeout"),
    ]
    outcome = evaluate_mesh("mesh-1", 3, "all", results)
    assert outcome.failed == ("c",)
    # "all" cannot be met when a branch failed, even though the survivors agree.
    assert outcome.consensus_reached is False
    assert outcome.largest_agreement == 2


def test_a_silent_completed_branch_is_refused() -> None:
    """An empty output is failed, not completed - otherwise silence votes."""
    with pytest.raises(BranchContractError, match="must carry output"):
        BranchResult(model_id="a", state=COMPLETED, output="")


def test_formatting_differences_do_not_manufacture_consensus() -> None:
    left = canonical_digest("the answer\n")
    right = canonical_digest("the answer")
    assert left == right, "trailing whitespace is transport noise"
    # ...but different wording is a real disagreement.
    assert canonical_digest("the answer") != canonical_digest("a different answer")


def test_result_count_must_match_the_declared_branch_count() -> None:
    with pytest.raises(BranchContractError, match="expected 3 branch results"):
        evaluate_mesh("mesh-1", 3, "any", _results({"a": "x"}))


def test_duplicate_branch_results_are_refused() -> None:
    duplicate = [
        BranchResult(model_id="a", state=COMPLETED, output="x"),
        BranchResult(model_id="a", state=COMPLETED, output="y"),
        BranchResult(model_id="c", state=COMPLETED, output="z"),
    ]
    with pytest.raises(BranchContractError, match="duplicate branch result"):
        evaluate_mesh("mesh-1", 3, "any", duplicate)


def test_convergence_never_names_a_winner() -> None:
    """Selection is a separate authority; convergence must not smuggle one in."""
    outcome = evaluate_mesh(
        "mesh-1", 3, "any", _results({"a": "same", "b": "same", "c": "other"})
    )
    assert outcome.as_mapping()["recommended_model_id"] is None
