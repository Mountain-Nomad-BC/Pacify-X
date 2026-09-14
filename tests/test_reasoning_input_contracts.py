"""Reasoning budgets and numeric admission precede expensive work and success."""

from copy import deepcopy
import math
import pytest
from runtime.cognitive_core import abduction, probability, decision, facade
from runtime.cognitive_assurance import detect_runtime_drift, cognitive_ekg
from runtime.behavioral_assurance import assurance_score


def _abduction():
    return {
        "observations": ["seen"],
        "hypotheses": [{"id": "one", "explains": ["seen"], "prior": 0.5}],
    }


def _decision():
    return {
        "objectives": [{"id": "quality", "weight": 1.0}],
        "candidates": [{"id": "one", "metrics": {"quality": 1.0}}],
    }


def test_abduction_frontier_budget_precedes_subset_enumeration(monkeypatch):
    payload = _abduction()
    payload["hypotheses"] = [{"id": f"h{i}", "explains": ["seen"]} for i in range(24)]
    payload["max_combination_size"] = 24
    monkeypatch.setattr(
        abduction,
        "combinations",
        lambda *args: pytest.fail("unadmitted exponential frontier enumerated"),
    )
    with pytest.raises(ValueError):
        abduction.rank_explanations(payload)


@pytest.mark.parametrize("value", [True, 1.5, "2", 0, -1, 25])
def test_abduction_combination_limit_is_exact_bounded_integer(value):
    payload = _abduction()
    payload["max_combination_size"] = value
    with pytest.raises(ValueError):
        abduction.rank_explanations(payload)


def test_abduction_canonicalizes_identity_and_reference_keys_once():
    payload = {
        "observations": ["seen"],
        "hypotheses": [
            {"id": " base ", "explains": [], "prior": 0.9},
            {
                "id": " child ",
                "requires": [" base "],
                "explains": ["seen"],
                "prior": 0.9,
            },
        ],
    }
    assert abduction.rank_explanations(payload)["selected"] == ["base", "child"]


@pytest.mark.parametrize("mutation", ["row", "observation", "prior"])
def test_abduction_does_not_drop_or_coerce_invalid_inputs(mutation):
    payload = _abduction()
    if mutation == "row":
        payload["hypotheses"].append(False)
    elif mutation == "observation":
        payload["observations"] = [False]
    else:
        payload["hypotheses"][0]["prior"] = True
    with pytest.raises(ValueError):
        abduction.rank_explanations(payload)


@pytest.mark.parametrize("outcome", [0.9, 1.9, True, "1"])
def test_calibration_requires_actual_binary_integer_outcomes(outcome):
    with pytest.raises(ValueError):
        probability.calibration_metrics([0.5], [outcome])


@pytest.mark.parametrize("bins", [2.5, "10", 1001])
def test_calibration_bin_work_is_typed_and_bounded(bins):
    with pytest.raises(ValueError):
        probability.calibration_metrics([0.5], [1], bins=bins)


def test_calibration_count_precedes_per_sample_conversion(monkeypatch):
    monkeypatch.setattr(
        probability,
        "ensure_probability",
        lambda *args: pytest.fail("sample conversion before count admission"),
    )
    with pytest.raises(ValueError):
        probability.calibration_metrics([0.5] * 100001, [0] * 100001)


@pytest.mark.parametrize(
    "field,value",
    [("weight", float("nan")), ("weight", True), ("risk_posture", "unsupported")],
)
def test_decision_validates_policy_even_without_eligible_candidates(field, value):
    payload = _decision()
    payload["candidates"][0]["constraint_violations"] = ["blocked"]
    if field == "weight":
        payload["objectives"][0][field] = value
    else:
        payload[field] = value
    with pytest.raises(ValueError):
        decision.choose(payload)


def test_decision_normalizes_large_finite_weights_without_overflow():
    payload = _decision()
    payload["objectives"] = [
        {"id": "quality", "weight": 1e308},
        {"id": "cost", "weight": 1e308},
    ]
    payload["candidates"][0]["metrics"]["cost"] = 1.0
    result = decision.choose(payload)
    assert result["weights"] == {"quality": 0.5, "cost": 0.5}


def test_decision_normalizes_extreme_finite_metric_range():
    payload = _decision()
    payload["candidates"] = [
        {"id": "low", "metrics": {"quality": -1e308}},
        {"id": "high", "metrics": {"quality": 1e308}},
    ]
    result = decision.choose(payload)
    assert result["selected"] == "high"
    assert all(math.isfinite(row["expected_utility"]) for row in result["eligible"])


def _drift_values():
    return {
        name: (0.0,)
        for name in ("behavior", "knowledge", "reasoning", "prompt", "memory")
    }


def test_missing_drift_domain_cannot_pass_at_threshold_one():
    assert detect_runtime_drift({}, {}, threshold=1.0).decision == "drifted"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "0"])
def test_drift_measurements_are_exact_finite_numbers(value):
    baseline = _drift_values()
    observed = deepcopy(baseline)
    observed["memory"] = (value,)
    with pytest.raises(ValueError):
        detect_runtime_drift(baseline, observed)


def _metrics():
    return {
        "evidence_coverage": 1.0,
        "trusted_memory_ratio": 1.0,
        "correction_success": 1.0,
        "poison_rate": 0.0,
        "drift_score": 0.0,
        "benchmark_pass_rate": 1.0,
    }


def test_nan_health_measurement_cannot_be_healthy():
    metrics = _metrics()
    metrics["poison_rate"] = float("nan")
    with pytest.raises(ValueError):
        cognitive_ekg(metrics)


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), True, -1.0, 1.1])
def test_assurance_axis_threshold_is_typed_finite_probability(threshold):
    axes = {
        name: 0.9
        for name in (
            "behavior",
            "evaluator_calibration",
            "evidence_integrity",
            "coverage",
            "regression",
            "operations",
        )
    }
    with pytest.raises(ValueError):
        assurance_score(axes, minimum_axis=threshold)


def test_facade_rejection_does_not_hash_oversized_unadmitted_input(monkeypatch):
    monkeypatch.setattr(
        facade,
        "stable_hash",
        lambda value: pytest.fail("oversized input hashed after rejection"),
    )
    result = facade.run_cognitive_operation(
        "rank-abductive-explanations", {"unexpected": "x" * (8 * 1024 * 1024 + 1)}
    )
    assert result["valid"] is False


def test_interval_midpoint_preserves_equal_smallest_subnormal():
    tiny = math.ulp(0.0)
    assert decision._interval({"low": tiny, "high": tiny}) == (tiny, tiny, tiny)


def test_abduction_top_k_matches_small_exhaustive_ranking():
    payload = {
        "observations": ["a", "b"],
        "hypotheses": [
            {"id": "a", "explains": ["a"], "prior": 0.5},
            {"id": "b", "explains": ["b"], "prior": 0.5},
            {"id": "both", "explains": ["a", "b"], "prior": 0.5},
        ],
        "max_combination_size": 3,
        "max_candidates": 2,
    }
    from itertools import combinations

    expected = []
    for count in range(1, 4):
        for selected in combinations(payload["hypotheses"], count):
            coverage = (
                len(set().union(*(set(item["explains"]) for item in selected))) / 2
            )
            score = (
                coverage
                + 0.04 * sum(math.log(0.5) for _ in selected)
                - 0.08 * (count - 1)
            )
            expected.append((score, coverage, [item["id"] for item in selected]))
    expected.sort(key=lambda row: (-row[0], -row[1], len(row[2]), row[2]))
    result = abduction.rank_explanations(payload)
    assert [row["hypotheses"] for row in result["candidates"]] == [
        row[2] for row in expected[:2]
    ]
    assert result["frontier_evaluated"] == result["valid_candidates"] == 7
    assert result["truncated"] is True


def test_calibration_bucket_boundaries_match_exhaustive_reference():
    values = [0.0, 0.01, 0.29, 0.58, 0.999, 1.0]
    predictions = [
        neighbor
        for value in values
        for neighbor in (
            max(0.0, math.nextafter(value, -math.inf)),
            value,
            min(1.0, math.nextafter(value, math.inf)),
        )
    ]
    outcomes = [index % 2 for index in range(len(predictions))]
    for bins in (2, 7, 10, 100, 1000):
        expected = 0.0
        for bucket in range(bins):
            indices = [
                i
                for i, value in enumerate(predictions)
                if bucket / bins <= value < (bucket + 1) / bins
                or bucket == bins - 1
                and value == 1.0
            ]
            if indices:
                expected += (
                    len(indices)
                    / len(predictions)
                    * abs(
                        sum(predictions[i] for i in indices) / len(indices)
                        - sum(outcomes[i] for i in indices) / len(indices)
                    )
                )
        assert probability.calibration_metrics(predictions, outcomes, bins=bins)[
            "expected_calibration_error"
        ] == pytest.approx(expected, abs=1e-14)


def test_voi_rejects_unrepresentable_derived_value_before_result_hash(monkeypatch):
    monkeypatch.setattr(
        probability,
        "stable_hash",
        lambda value: pytest.fail("nonfinite derived result hashed"),
    )
    with pytest.raises(ValueError):
        probability.expected_value_of_information(
            {
                "baseline_expected_utility": -1e308,
                "tests": [
                    {
                        "id": "large",
                        "outcomes": [
                            {"probability": 1.0, "best_expected_utility": 1e308}
                        ],
                    }
                ],
            }
        )


def test_drift_threshold_uses_measurement_before_display_rounding():
    baseline = _drift_values()
    observed = deepcopy(baseline)
    observed["memory"] = (0.20000001,)
    report = detect_runtime_drift(baseline, observed, threshold=0.2)
    assert "memory" in report.drift_types


def test_invalid_late_hypothesis_is_rejected_before_any_search(monkeypatch):
    payload = _abduction()
    payload["hypotheses"].append({"id": "bad", "prior": "0.5"})
    monkeypatch.setattr(
        abduction,
        "combinations",
        lambda *args: pytest.fail("search began before complete numeric admission"),
    )
    with pytest.raises(ValueError):
        abduction.rank_explanations(payload)


def test_facade_rejects_opaque_value_without_stringifying_it():
    class Opaque:
        def __str__(self):
            pytest.fail("opaque input was stringified")

    result = facade.run_cognitive_operation(
        "rank-abductive-explanations", {"unexpected": Opaque()}
    )
    assert result["valid"] is False


def test_out_of_range_axes_keep_rejection_diagnostics_finite():
    axes = {
        name: 1e308
        for name in (
            "behavior",
            "evaluator_calibration",
            "evidence_integrity",
            "coverage",
            "regression",
            "operations",
        )
    }
    result = assurance_score(axes)
    assert not result["admissible"]
    assert math.isfinite(result["score"])


def test_health_ratio_cannot_exceed_its_complete_domain():
    metrics = _metrics()
    metrics["evidence_coverage"] = 2.0
    with pytest.raises(ValueError):
        cognitive_ekg(metrics)
