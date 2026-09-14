from __future__ import annotations

import copy
import itertools

import pytest

from runtime import operational_controls as controls
from tests import test_operational_controls as legacy_controls

FAMILIES = {
    "bundle": (controls.resolve_bundle, "skill-bundle-resolver"),
    "loop": (controls.assess_loop, "tool-loop-circuit-breaker"),
    "progress": (controls.track_progress, "long-horizon-progress-ledger"),
    "compile": (controls.compile_candidate, "trace-to-skill-compiler"),
    "topology": (controls.select_topology, "read-only-speculation-controller"),
}


def sample():
    return legacy_controls.OperationalControlTests().payload()


@pytest.mark.parametrize("family", list(FAMILIES))
def test_direct_and_routed_policy_agree_without_mutating_input(family):
    function, skill = FAMILIES[family]
    payload = sample()
    before = copy.deepcopy(payload)
    assert function(skill, payload) == controls.run_control(skill, payload)
    assert payload == before


@pytest.mark.parametrize("side", ["first", "second"])
@pytest.mark.parametrize("reverse", [False, True])
def test_bundle_conflicts_are_symmetric_and_input_order_independent(side, reverse):
    records = [
        {"id": "a", "provides": ["a"], "cost": 0, "risk": 0},
        {"id": "b", "provides": ["b"], "cost": 1, "risk": 0},
    ]
    records[0 if side == "first" else 1]["conflicts"] = [
        "b" if side == "first" else "a"
    ]
    if reverse:
        records.reverse()
    result = controls.run_control(
        "skill-bundle-resolver", {"requirements": ["a", "b"], "candidates": records}
    )
    assert result.decision == "incomplete"
    assert result.outputs["selected"] == ("a",)
    assert result.outputs["unresolved"] == ("b",)
    assert result.outputs["excluded_conflicts"] == ("b",)


def test_every_small_conflict_orientation_excludes_conflicting_selected_pairs():
    pairs = [("a", "b"), ("a", "c"), ("b", "c")]
    for directions in itertools.product([0, 1, 2, 3], repeat=3):
        records = {
            name: {
                "id": name,
                "provides": [name],
                "cost": 0,
                "risk": 0,
                "conflicts": [],
            }
            for name in "abc"
        }
        for (left, right), direction in zip(pairs, directions):
            if direction & 1:
                records[left]["conflicts"].append(right)
            if direction & 2:
                records[right]["conflicts"].append(left)
        result = controls.run_control(
            "skill-bundle-resolver",
            {"requirements": list("abc"), "candidates": list(records.values())},
        )
        selected = set(result.outputs["selected"])
        assert all(
            not (set(records[name]["conflicts"]) & selected) for name in selected
        )


@pytest.mark.parametrize(
    "family,field",
    [
        ("bundle", "candidates"),
        ("progress", "milestones"),
        ("compile", "records"),
        ("topology", "approved_templates"),
    ],
)
def test_duplicate_identity_cannot_collapse_a_rejected_or_conflicting_record(
    family, field
):
    payload = sample()
    value = copy.deepcopy(payload[field][0])
    if family == "compile":
        value["verified"] = False
    if family == "progress":
        value["postcondition"] = False
    payload[field].append(value)
    function, skill = FAMILIES[family]
    with pytest.raises(ValueError):
        function(skill, payload)


@pytest.mark.parametrize(
    "field", ["goal", "constraints", "decisions", "evidence", "next_actions"]
)
def test_complete_milestone_cannot_mask_missing_handoff(field):
    payload = sample()
    payload.pop(field)
    result = controls.run_control("long-horizon-progress-ledger", payload)
    assert result.decision == "resumable"
    assert result.outputs["unresolved"] == ()
    assert field in result.outputs["missing_handoff_fields"]
    assert "handoff_fields_missing" in result.reasons


@pytest.mark.parametrize(
    "value",
    ["false", "true", 0, 1, None, []],
    ids=["false-text", "true-text", "zero", "one", "null", "array"],
)
def test_speculation_requires_an_actual_boolean(value):
    payload = sample()
    payload["read_only"] = value
    with pytest.raises(ValueError):
        controls.run_control("read-only-speculation-controller", payload)


@pytest.mark.parametrize("value", [False, True])
def test_actual_speculation_boolean_preserves_nonexecution(value):
    payload = sample()
    payload["read_only"] = value
    result = controls.run_control("read-only-speculation-controller", payload)
    assert result.decision == ("proposal_only" if value else "denied")
    assert result.outputs["executed"] is False


@pytest.mark.parametrize(
    "field",
    ["next_step_cost", "expected_information_gain", "trajectory_risk", "risk_limit"],
)
@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), True, "1", -1, 1e13],
    ids=[
        "nan",
        "positive-infinity",
        "negative-infinity",
        "bool",
        "text",
        "negative",
        "too-large",
    ],
)
def test_loop_numbers_are_finite_actual_values_before_comparison(field, value):
    payload = sample()
    payload[field] = value
    with pytest.raises(ValueError):
        controls.run_control("tool-loop-circuit-breaker", payload)


@pytest.mark.parametrize("field", ["failure_count", "failure_limit"])
@pytest.mark.parametrize(
    "value",
    [True, 1.5, "1", -1, 1000000001],
    ids=["bool", "fraction", "text", "negative", "too-large"],
)
def test_loop_counters_do_not_coerce_or_clamp(field, value):
    payload = sample()
    payload[field] = value
    with pytest.raises(ValueError):
        controls.run_control("tool-loop-circuit-breaker", payload)


@pytest.mark.parametrize(
    "family,field", [("bundle", "candidates"), ("topology", "approved_templates")]
)
@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), True, "1"],
    ids=["nan", "infinity", "bool", "text"],
)
def test_ranking_cannot_consume_invalid_costs(family, field, value):
    payload = sample()
    payload[field][0]["cost"] = value
    function, skill = FAMILIES[family]
    with pytest.raises(ValueError):
        function(skill, payload)


@pytest.mark.parametrize("family", list(FAMILIES))
@pytest.mark.parametrize(
    "bad", [None, [], [("field", "value")]], ids=["null", "array", "pairs"]
)
def test_policy_payload_is_an_actual_bounded_object(family, bad):
    function, skill = FAMILIES[family]
    with pytest.raises(ValueError):
        function(skill, bad)


@pytest.mark.parametrize(
    "case",
    [
        "records",
        "state-history",
        "requirements",
        "evidence",
        "payload-fields",
        "identity",
        "self-conflict",
        "string-state",
        "bool-evidence-count",
        "bool-verified",
        "string-blocked",
        "string-goal",
    ],
)
def test_family_collection_and_identity_boundaries(case):
    payload = sample()
    family = "bundle"
    if case == "records":
        payload["candidates"] = [{"id": str(i)} for i in range(1025)]
    elif case == "state-history":
        family = "loop"
        payload["state_fingerprints"] = ["a"] * 4097
    elif case == "requirements":
        payload["requirements"] = [str(i) for i in range(257)]
    elif case == "evidence":
        family = "compile"
        payload["records"][0]["evidence"] = [str(i) for i in range(257)]
    elif case == "payload-fields":
        payload.update({str(i): None for i in range(65)})
    elif case == "identity":
        payload["candidates"][0]["id"] = "x" * 129
    elif case == "self-conflict":
        payload["candidates"][0]["conflicts"] = [payload["candidates"][0]["id"]]
    elif case == "string-state":
        family = "loop"
        payload["state_fingerprints"] = "abc"
    elif case == "bool-evidence-count":
        family = "loop"
        payload["evidence_counts"] = [True]
    elif case == "bool-verified":
        family = "compile"
        payload["records"][0]["verified"] = "true"
    elif case == "string-blocked":
        family = "progress"
        payload["milestones"][0]["blocked"] = "false"
    elif case == "string-goal":
        family = "progress"
        payload["goal"] = 123
    function, skill = FAMILIES[family]
    with pytest.raises(ValueError):
        function(skill, payload)


def test_compile_keeps_every_unique_negative_record_visible():
    payload = {
        "records": [
            {"id": "good", "verified": True, "evidence": ["test"]},
            {"id": "bad", "verified": False, "evidence": ["test"]},
            {"id": "missing", "verified": True, "evidence": []},
        ]
    }
    result = controls.run_control("trace-to-skill-compiler", payload)
    assert result.outputs["accepted_records"] == ("good",)
    assert result.outputs["rejected_records"] == ("bad", "missing")
    assert result.outputs["activation"] == "candidate"


@pytest.mark.parametrize(
    "value",
    [0, 9, True, "2", 1.5, None],
    ids=["zero", "too-large", "bool", "text", "fraction", "null"],
)
def test_bundle_asset_limit_is_exact(value):
    payload = sample()
    payload["max_assets"] = value
    with pytest.raises(ValueError):
        controls.run_control("skill-bundle-resolver", payload)


def test_opaque_goal_does_not_execute_conversion_hooks():
    class Opaque:
        def __eq__(self, other):
            pytest.fail("opaque goal equality ran before type validation")

        def __str__(self):
            pytest.fail("opaque goal conversion ran before type validation")

        def __bool__(self):
            pytest.fail("opaque goal truthiness ran before type validation")

    payload = sample()
    payload["goal"] = Opaque()
    with pytest.raises(ValueError):
        controls.run_control("long-horizon-progress-ledger", payload)
