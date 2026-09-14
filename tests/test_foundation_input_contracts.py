from __future__ import annotations

import math

import pytest

from runtime.foundation_assurance import (
    ContractSurface,
    compare_contract_surfaces,
    evaluate_numeric_shift,
    validate_dimension_steps,
    plan_runtime_surface_validation,
    gate_model_dataset,
    evaluate_retrieval_readiness,
    RetrievalCase,
)


def surface(owner="service", *, fields=None, required=("id",)):
    return ContractSurface(
        "item", owner, "GET", "/items", fields or {"id": "string"}, required
    )


def test_empty_contract_sides_cannot_claim_compatibility():
    with pytest.raises(ValueError):
        compare_contract_surfaces([], [])


def test_provider_optional_field_does_not_guarantee_consumer_requirement():
    report = compare_contract_surfaces([surface(required=())], [surface("client")])
    assert report["decision"] == "incompatible"


def test_optional_overlap_type_must_still_agree():
    provider = surface(fields={"id": "string", "extra": "integer"})
    consumer = surface("client", fields={"id": "string", "extra": "string"})
    assert (
        compare_contract_surfaces([provider], [consumer])["decision"] == "incompatible"
    )


def test_service_and_client_may_have_different_nonempty_owners():
    assert (
        compare_contract_surfaces([surface()], [surface("client")])["decision"]
        == "compatible"
    )


def test_consumer_owner_cannot_be_empty():
    with pytest.raises(ValueError):
        compare_contract_surfaces([surface()], [surface("")])


@pytest.mark.parametrize("threshold", [math.nan, math.inf, True, "0.25"])
def test_numeric_shift_requires_actual_finite_threshold(threshold):
    with pytest.raises(ValueError):
        evaluate_numeric_shift([1, 2], [3, 4], threshold=threshold)


def test_large_finite_mean_shift_does_not_overflow_variance():
    result = evaluate_numeric_shift([1e308, -1e308], [1e308, -1e308])
    assert result["decision"] == "within_threshold"
    assert math.isfinite(result["score"])


@pytest.mark.parametrize("exponent", [1.5, True, "1"])
def test_dimension_exponents_are_exact_integers(exponent):
    with pytest.raises(ValueError):
        validate_dimension_steps(
            [
                {
                    "operation": "add",
                    "left": {"length": exponent},
                    "right": {"length": exponent},
                    "result": {"length": exponent},
                }
            ]
        )


def test_surface_plan_cannot_accept_empty_check_obligations():
    assert (
        plan_runtime_surface_validation([{"id": "web", "owner": "team", "checks": []}])[
            "decision"
        ]
        == "blocked"
    )


def test_surface_plan_does_not_hide_duplicate_ids():
    row = {"id": "web", "owner": "team", "checks": ["unit"]}
    assert plan_runtime_surface_validation([row, row])["decision"] == "blocked"


def test_dataset_minimum_cannot_admit_empty_metadata():
    with pytest.raises(ValueError):
        gate_model_dataset([], allowed_licenses=["internal"], minimum_records=0)


def test_retrieval_top_k_is_not_a_boolean():
    with pytest.raises(ValueError):
        evaluate_retrieval_readiness(
            [RetrievalCase("one", ("a",))], {"one": ["a"]}, k=True
        )


def test_contract_iterables_stop_after_one_overflow_witness():
    def values():
        for index in range(10001):
            yield ContractSurface(
                "item-" + str(index),
                "service",
                "GET",
                "/items",
                {"id": "string"},
                ("id",),
            )
        pytest.fail("contract iterable consumed beyond bounded overflow witness")

    with pytest.raises(ValueError):
        compare_contract_surfaces(values(), [surface("client")])


def test_contract_aggregate_rejected_before_bulk_dataclass_expansion(monkeypatch):
    import runtime.foundation_assurance as foundation

    original = foundation.asdict
    calls = []

    def checked(item):
        calls.append(item)
        if len(calls) > 150:
            pytest.fail("oversized aggregate reached bulk dataclass expansion")
        return original(item)

    monkeypatch.setattr(foundation, "asdict", checked)
    fields = {"field-" + str(i): "x" * 500 for i in range(128)}
    providers = [
        ContractSurface("item-" + str(i), "service", "GET", "/items", fields, ())
        for i in range(300)
    ]
    with pytest.raises(ValueError):
        compare_contract_surfaces(providers, [surface("client")])


def test_expanded_contract_findings_rejected_before_hash(monkeypatch):
    import runtime.foundation_assurance as foundation

    def forbidden(value):
        pytest.fail("oversized expanded findings reached source hashing")

    monkeypatch.setattr(foundation, "_stable", forbidden)
    left = {str(i): "a" for i in range(128)}
    right = {str(i): "b" for i in range(128)}
    providers = [
        ContractSurface(
            "item-" + str(i) + "x" * 490, "service", "GET", "/items", left, ()
        )
        for i in range(200)
    ]
    consumers = [
        ContractSurface(item.contract_id, "client", "GET", "/items", right, ())
        for item in providers
    ]
    with pytest.raises(ValueError):
        compare_contract_surfaces(providers, consumers)


@pytest.mark.parametrize(
    "change",
    [
        {"checks": ["unit", "unit"]},
        {"mutating": "false"},
        {"id": ""},
        {"owner": ""},
    ],
    ids=["duplicate-check", "text-mutation", "empty-identity", "empty-owner"],
)
def test_surface_obligations_preserve_invalidity(change):
    row = {"id": "web", "owner": "team", "checks": ["unit"], **change}
    try:
        result = plan_runtime_surface_validation([row])
    except ValueError:
        return
    assert result["decision"] == "blocked"


@pytest.mark.parametrize(
    "field,value",
    [
        ("contains_sensitive_data", "false"),
        ("approved_sensitive_use", 1),
        ("record_id", 99),
    ],
    ids=["text-sensitive", "numeric-approval", "numeric-identity"],
)
def test_dataset_fields_cannot_gain_meaning_through_coercion(field, value):
    from runtime.foundation_assurance import TrainingRecord

    row = dict(
        record_id="one",
        content_sha256="a" * 64,
        source_id="source",
        license="internal",
        consent="approved",
        label="ok",
        split="train",
    )
    row[field] = value
    with pytest.raises(ValueError):
        gate_model_dataset(
            [TrainingRecord(**row)], allowed_licenses=["internal"], minimum_records=1
        )


@pytest.mark.parametrize(
    "ranked", [{"one": [1]}, {"one": "a"}], ids=["numeric-id", "scalar-ranking"]
)
def test_retrieval_ids_are_typed_before_ranking(ranked):
    with pytest.raises(ValueError):
        evaluate_retrieval_readiness([RetrievalCase("one", ("a",))], ranked)


def test_same_dimension_declaration_keeps_hash_framing():
    import hashlib
    import json

    value = [
        {
            "operation": "multiply",
            "left": {"L": 1},
            "right": {"T": -1},
            "result": {"L": 1, "T": -1},
        }
    ]
    result = validate_dimension_steps(value)
    expected = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    assert result["decision"] == "valid"
    assert result["steps_sha256"] == expected


def test_identical_subnormal_series_have_zero_mean_shift():
    tiny = float.fromhex("0x0.0000000000001p-1022")
    result = evaluate_numeric_shift([tiny, 2 * tiny], [tiny, 2 * tiny])
    assert result["decision"] == "within_threshold"
    assert result["score"] == 0


def test_cancellation_preserves_small_observed_mean():
    result = evaluate_numeric_shift([1e-300, 2e-300], [1e308, -1e308, 1e-300])
    assert result["score"] == pytest.approx(7 / 3, abs=1e-6)
    assert result["errors"] == ()


@pytest.mark.parametrize(
    "owner",
    ["service\n", "é" * 250 + " " * 20],
    ids=["trailing-control", "padded-utf8"],
)
def test_contract_text_validates_preserved_bytes(owner):
    with pytest.raises(ValueError):
        compare_contract_surfaces([surface(owner)], [surface("client")])


@pytest.mark.parametrize(
    "metric", ["minimum_recall", "minimum_mrr", "minimum_coverage"]
)
def test_retrieval_threshold_uses_unrounded_measurement(metric):
    cases = [RetrievalCase(str(i), ("a",)) for i in range(3)]
    result = evaluate_retrieval_readiness(
        cases,
        {"0": ["a"], "1": ["a"]},
        **{
            "minimum_recall": 0,
            "minimum_mrr": 0,
            "minimum_coverage": 0,
            metric: 0.6666668,
        },
    )
    assert result["decision"] == "blocked"
    assert not result["activation_allowed"]


def test_contract_hash_preserves_supplied_spelling_and_scope_order():
    from dataclasses import asdict, replace
    import hashlib
    import json

    provider = replace(
        surface(" service "), method="get", authorization_scopes=("b", "a")
    )
    consumer = replace(surface("client"), authorization_scopes=("a", "b"))
    result = compare_contract_surfaces([provider], [consumer])
    assert result["decision"] == "compatible"
    expected = hashlib.sha256(
        json.dumps(
            [asdict(provider)], sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()
    assert result["provider_sha256"] == expected


@pytest.mark.parametrize("scale", [1e-300, 1.0, 1e300], ids=["tiny", "unit", "large"])
def test_numeric_shift_matches_independent_finite_reference(scale):
    # Baseline [-2, 0, 2] has variance 8/3; observed mean is 1.
    result = evaluate_numeric_shift([-2 * scale, 0, 2 * scale], [0, 2 * scale])
    assert result["errors"] == ()
    assert result["score"] == pytest.approx(math.sqrt(3 / 8), abs=1e-6)
