"""Causal contract cases for typed selection and resource decision inputs."""

import math
import pytest

from runtime.metacognitive_evolution.agent_profiles.router import route, compose_team
from runtime.metacognitive_evolution import facade
from runtime.completion_controls import reserve_budget, reconcile_budget, choose_runtime


def agent(**fields):
    return {"id": "a", "domains": ["python"], "precision": 0.8, **fields}


def profile(**fields):
    return {
        "id": "r",
        "healthy": True,
        "trust": 3,
        "capabilities": ["python"],
        "available_quota": 1,
        "cost": 2,
        "project_scopes": ["p"],
        **fields,
    }


def choose(profiles):
    return choose_runtime(
        profiles, project_id="p", required_capabilities=["python"], minimum_trust=2
    )


def reserve(**fields):
    return reserve_budget(
        **{
            "project_id": "p",
            "work_id": "w",
            "requested": {"cost": 1},
            "limits": {"cost": 3},
            **fields,
        }
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("risk", math.nan),
        ("estimated_cost", math.inf),
        ("calibration_error", -0.1),
        ("precision", True),
        ("precision", "0.8"),
        ("latency", -1),
    ],
)
def test_profile_rejects_malformed_numeric_before_selection(field, value):
    with pytest.raises(ValueError):
        route({}, [agent(**{field: value})])


@pytest.mark.parametrize(
    "query",
    [
        {"weights": {"precision": math.nan}},
        {"weights": {"precision": -1}},
        {"requirements": {"unknown_dimension": 0.9}},
        {"max_risk": math.nan},
        {"max_cost": math.inf},
        {"weights": {"unmeasured_score": 0.9}},
    ],
)
def test_request_rejects_unknown_or_malformed_constraints(query):
    with pytest.raises(ValueError):
        route(query, [agent()])


def test_required_domain_is_a_hard_filter():
    result = route({"domains": ["rust"]}, [agent()])
    assert result["abstained"] and result["selected_agent"] is None
    assert "required_domains" in result["ranked_candidates"][0]["exclusions"]


def test_required_measurement_cannot_be_satisfied_by_default():
    result = route({"requirements": {"depth": 0.4}}, [agent()])
    assert result["abstained"]


@pytest.mark.parametrize("query", [{"max_risk": 0.7}, {"max_cost": 3}])
def test_explicit_risk_or_cost_budget_requires_its_measurement(query):
    assert route(query, [agent()])["abstained"]


@pytest.mark.parametrize(
    "agents",
    [
        [{"precision": 1}],
        [agent(), agent()],
        [agent(id=" ")],
        [agent(id="a"), agent(id=" a ")],
    ],
)
def test_agent_identities_are_nonempty_unique_canonical(agents):
    with pytest.raises(ValueError):
        route({}, agents)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2", 257])
def test_team_limit_is_admitted_before_route(limit, monkeypatch):
    import runtime.metacognitive_evolution.agent_profiles.router as router

    monkeypatch.setattr(
        router, "route", lambda *a: pytest.fail("selection ran before limit admission")
    )
    with pytest.raises(ValueError):
        compose_team({}, [agent()], max_agents=limit)


def test_facade_does_not_coerce_team_limit():
    result = facade.run_operation(
        "compose-team", {"request": {}, "agents": [agent()], "max_agents": 1.5}
    )
    assert result["valid"] is False


def test_facade_does_not_hash_unadmitted_payload(monkeypatch):
    monkeypatch.setattr(
        facade, "_hash", lambda value: pytest.fail("unadmitted input hashed")
    )
    result = facade.run_operation(
        "route-agent", {"request": {}, "agents": [agent(precision=math.nan)]}
    )
    assert result["valid"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("requested", {"cost": math.nan}),
        ("requested", {"cost": True}),
        ("requested", {"cost": "1"}),
        ("limits", {"cost": math.inf}),
        ("requested", {}),
        ("project_id", " "),
        ("work_id", 2),
    ],
)
def test_budget_requires_explicit_finite_dimensions_and_identity(field, value):
    with pytest.raises(ValueError):
        reserve(**{field: value})


def test_missing_limit_does_not_grant_zero_request():
    result = reserve(requested={"gpu": 0})
    assert result["state"] == "denied" and "missing_limit:gpu" in result["blockers"]


def test_negative_active_reservation_cannot_create_capacity():
    active = {
        "project_id": "p",
        "work_id": "other",
        "state": "active",
        "reservation_id": "res_old",
        "reserved": {"cost": -100},
    }
    with pytest.raises(ValueError):
        reserve(requested={"cost": 10}, active_reservations=[active])


def test_unknown_reservation_state_cannot_hide_usage():
    prior = reserve(work_id="prior")
    prior["state"] = "unrecognized"
    with pytest.raises(ValueError):
        reserve(active_reservations=[prior])


def test_reserved_arithmetic_overflow_is_rejected():
    active = {
        "project_id": "p",
        "work_id": "other",
        "state": "active",
        "reservation_id": "res_old",
        "reserved": {"cost": 1e308},
    }
    with pytest.raises(ValueError):
        reserve(
            requested={"cost": 1e308},
            limits={"cost": 1e308},
            active_reservations=[active],
        )


@pytest.mark.parametrize(
    "actual", [{"cost": math.nan}, {"cost": -1}, {"cost": True}, {}]
)
def test_reconciliation_requires_complete_actual_finite_nonnegative_measurements(
    actual,
):
    reservation = reserve()
    with pytest.raises(ValueError):
        reconcile_budget(reservation, actual)


def test_reconciliation_requires_original_reservation_identity():
    reservation = reserve()
    reservation.pop("reservation_id")
    with pytest.raises(ValueError):
        reconcile_budget(reservation, {"cost": 1})


@pytest.mark.parametrize(
    "field,value",
    [
        ("available_quota", math.nan),
        ("cost", math.nan),
        ("cost", -1),
        ("trust", 2.5),
        ("trust", True),
        ("available_quota", "1"),
    ],
)
def test_runtime_profiles_reject_coercions_and_nonfinite_data(field, value):
    with pytest.raises(ValueError):
        choose([profile(**{field: value})])


def test_empty_project_scopes_do_not_mean_global_permission():
    result = choose([profile(project_scopes=[])])
    assert result["valid"] is False
    assert "project_scope" in dict(result["rejected"])["r"]


@pytest.mark.parametrize("profiles", [[profile(), profile()], [profile(id=" ")]])
def test_runtime_identities_are_nonempty_and_unique(profiles):
    with pytest.raises(ValueError):
        choose(profiles)


def test_selection_and_budget_collections_reject_unbounded_iterators():
    def forbidden():
        pytest.fail("unbounded iterator consumed")
        yield profile()

    with pytest.raises(ValueError):
        choose(forbidden())


def test_cost_budget_and_normalized_cost_are_distinct_and_input_is_unchanged():
    import copy

    request = {"max_cost": 3, "requirements": {"cost": 0.7}}
    agents = [
        agent(id="cheap-normalized", cost=0.1, estimated_cost=4),
        agent(id="within-budget", cost=0.2, estimated_cost=2),
    ]
    before = copy.deepcopy((request, agents))
    result = route(request, agents)
    assert result["selected_agent"] == "within-budget"
    assert (
        "cost_budget"
        in next(
            r
            for r in result["ranked_candidates"]
            if r["agent_id"] == "cheap-normalized"
        )["exclusions"]
    )
    assert (request, agents) == before


def test_default_weighted_score_and_declared_penalties_are_preserved():
    result = route({}, [agent(calibration_error=0.1, known_failure_modes=["timeout"])])
    # 0.24*0.8 + 0.18*1 + (0.20+0.12+0.08+0.08+0.05+0.05)*0.5 - 0.1 - 0.05
    assert result["ranked_candidates"][0]["score"] == pytest.approx(0.512)


def test_valid_budget_is_all_or_none_across_dimensions_and_preserves_usage():
    prior = reserve(
        work_id="prior",
        requested={"cost": 2, "turns": 1},
        limits={"cost": 5, "turns": 3},
    )
    result = reserve(
        requested={"cost": 2, "turns": 3},
        limits={"cost": 5, "turns": 3},
        active_reservations=[prior],
    )
    assert result["state"] == "denied" and result["blockers"] == (
        "limit_exceeded:turns",
    )
    assert prior["reserved"] == {"cost": 2.0, "turns": 1.0}


def test_reconcile_reports_extra_dimensions_and_retains_scope():
    reservation = reserve()
    result = reconcile_budget(reservation, {"cost": 0.5, "gpu": 1})
    assert result["state"] == "reconciled_with_overage"
    assert result["overages"] == ("gpu",) and result["released"] == {"cost": 0.5}
    assert result["reservation_id"] == reservation["reservation_id"]
    assert result["project_id"] == "p" and result["work_id"] == "w"


def test_valid_runtime_tie_is_stable_after_all_hard_filters():
    profiles = [
        profile(id="z"),
        profile(id="a"),
        profile(id="cheapest", cost=0, project_scopes=["foreign"]),
    ]
    result = choose(profiles)
    assert result["selected_runtime"] == "a"
    assert dict(result["rejected"])["cheapest"] == ("project_scope",)


@pytest.mark.parametrize("count", [257, 10000])
def test_oversized_valid_candidate_frontier_is_rejected(count):
    with pytest.raises(ValueError):
        route({}, [agent(id=f"a{i}") for i in range(count)])
    with pytest.raises(ValueError):
        choose([profile(id=f"r{i}") for i in range(count)])


def test_late_malformed_profile_is_not_hidden_by_earlier_valid_winner():
    with pytest.raises(ValueError):
        route({}, [agent(), agent(id="late", calibration_error=math.nan)])
    with pytest.raises(ValueError):
        choose([profile(), profile(id="late", available_quota=math.inf)])


def test_finite_weights_cannot_produce_an_infinite_routing_score():
    from runtime.metacognitive_evolution.agent_profiles.router import DEFAULT_WEIGHTS

    with pytest.raises(ValueError, match="finite"):
        route({"weights": {key: 1e308 for key in DEFAULT_WEIGHTS}}, [agent()])


def test_duplicate_reservation_identity_cannot_be_counted_twice():
    prior = reserve(work_id="prior")
    with pytest.raises(ValueError, match="unique"):
        reserve(active_reservations=[prior, prior])


def test_foreign_reservation_is_typed_before_scope_filtering():
    prior = reserve(project_id="foreign", work_id="prior")
    prior["reserved"]["cost"] = math.nan
    with pytest.raises(ValueError):
        reserve(active_reservations=[prior])


def test_colliding_resource_dimensions_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        reserve(requested={"cost": 1, " cost ": 1})


def test_zero_measurement_of_unreserved_dimension_remains_explicit():
    result = reconcile_budget(reserve(), {"cost": 0, "gpu": 0})
    assert result["state"] == "reconciled_with_overage"
    assert result["overages"] == ("gpu",)


def test_required_capabilities_do_not_consume_unbounded_iterators():
    def forbidden():
        pytest.fail("unbounded requirements consumed")
        yield "python"

    with pytest.raises(ValueError):
        choose_runtime(
            [], project_id="p", required_capabilities=forbidden(), minimum_trust=1
        )


def test_invalid_minimum_trust_is_rejected_even_without_candidates():
    with pytest.raises(ValueError):
        choose_runtime([], project_id="p", required_capabilities=[], minimum_trust=True)


def test_facade_bounds_operation_identity_without_stringifying_it():
    class Opaque:
        def __str__(self):
            pytest.fail("opaque operation stringified")

    assert facade.run_operation(Opaque(), {})["valid"] is False


def test_supported_empty_selection_abstains_consistently():
    assert route({}, [])["abstained"]
    assert compose_team({}, [], 1)["primary"] is None
    assert choose([])["valid"] is False
