from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.cognitive_core.causal import analyze as analyze_causal
from runtime.cognitive_core.constraint import solve as solve_constraints
from runtime.cognitive_core.decision import choose
from runtime.cognitive_core.facade import (
    integration_healthcheck,
    run_cognitive_operation,
)
from runtime.cognitive_core.formula_engine import FormulaDefinition, FormulaEngine
from runtime.cognitive_core.index_builder import (
    build_cognitive_index,
    validate_cognitive_index,
)
from runtime.cognitive_core.knowledge import project as project_knowledge
from runtime.cognitive_core.logic import reason
from runtime.cognitive_core.navigator import CognitiveNavigator
from runtime.cognitive_core.probability import bayesian_portfolio, calibration_metrics
from runtime.cognitive_core.temporal import analyze as analyze_temporal


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__import__("os").environ.get("PACIFY_X_TEST_ROOT", ROOT))


def admitted_formula(payload: dict, inputs: dict[str, float], expected: float) -> dict:
    result = {
        **payload,
        "authoritative_source": "test-reviewed equation definition",
        "expected_examples": [
            {"inputs": inputs, "expected": expected, "tolerance": 1e-9}
        ],
        "property_cases": ["test property case"],
        "validation": "tests/test_cognitive_core.py",
    }
    result.setdefault("assumptions", ["test-domain assumptions are explicit"])
    result.setdefault("source", "test")
    return result


def test_logic_is_paraconsistent_and_does_not_explode() -> None:
    result = reason(
        {
            "facts": [
                {
                    "predicate": "powered",
                    "arguments": ["bank-1"],
                    "support_id": "meter",
                },
                {
                    "predicate": "powered",
                    "arguments": ["bank-1"],
                    "negated": True,
                    "support_id": "controller",
                },
            ],
            "rules": [
                {
                    "id": "heat-if-powered",
                    "premises": [{"predicate": "powered", "arguments": ["bank-1"]}],
                    "conclusion": {"predicate": "may-heat", "arguments": ["bank-1"]},
                }
            ],
            "queries": [
                {"predicate": "powered", "arguments": ["bank-1"]},
                {"predicate": "may-heat", "arguments": ["bank-1"]},
                {"predicate": "unrelated", "arguments": ["x"]},
            ],
        }
    )
    assert result["queries"][0]["truth"] == "both"
    assert result["queries"][1]["truth"] == "true"
    assert result["queries"][2]["truth"] == "neither"
    assert len(result["contradictions"]) == 1


def test_bayesian_portfolio_normalizes_and_dampens_dependence() -> None:
    result = bayesian_portfolio(
        {
            "hypotheses": [
                {"id": "element", "prior": 0.5},
                {"id": "contactor", "prior": 0.5},
            ],
            "evidence": [
                {
                    "id": "e1",
                    "dependence_group": "same-meter",
                    "likelihoods": {"element": 0.9, "contactor": 0.2},
                },
                {
                    "id": "e2",
                    "dependence_group": "same-meter",
                    "likelihoods": {"element": 0.9, "contactor": 0.2},
                },
            ],
        }
    )
    posteriors = {item["id"]: item["posterior"] for item in result["hypotheses"]}
    assert sum(posteriors.values()) == pytest.approx(1.0)
    assert posteriors["element"] > posteriors["contactor"]
    assert result["updates"][1]["effective_weight"] < 1.0


def test_causal_backdoor_validation() -> None:
    result = analyze_causal(
        {
            "nodes": ["Z", "X", "Y"],
            "edges": [
                {"source": "Z", "target": "X"},
                {"source": "Z", "target": "Y"},
                {"source": "X", "target": "Y"},
            ],
            "operation": "validate-backdoor",
            "treatment": "X",
            "outcome": "Y",
            "adjustment": ["Z"],
        }
    )
    assert result["valid"]
    assert result["blocks_backdoor_paths"]


def test_temporal_relations_and_state_transitions() -> None:
    result = analyze_temporal(
        {
            "intervals": [
                {
                    "id": "heat",
                    "start": "2026-01-01T00:00:00Z",
                    "end": "2026-01-01T00:10:00Z",
                },
                {
                    "id": "draw",
                    "start": "2026-01-01T00:10:00Z",
                    "end": "2026-01-01T00:20:00Z",
                },
            ],
            "initial_state": "idle",
            "allowed_transitions": {"idle": ["heating"], "heating": ["satisfied"]},
            "events": [
                {"id": "e2", "timestamp": "2026-01-01T00:02:00Z", "state": "satisfied"},
                {"id": "e1", "timestamp": "2026-01-01T00:01:00Z", "state": "heating"},
            ],
        }
    )
    assert result["interval_relations"][0]["relation"] == "meets"
    assert result["ordered_event_ids"] == ["e1", "e2"]
    assert result["valid"]


def test_constraint_solver_finds_only_valid_assignments() -> None:
    result = solve_constraints(
        {
            "variables": {"voltage": [208, 240], "elements": [3, 6], "stage": [1, 2]},
            "constraints": [
                {"type": "eq", "left": {"var": "voltage"}, "right": {"value": 240}},
                {"type": "gte", "left": {"var": "elements"}, "right": {"value": 6}},
                {"type": "neq", "left": {"var": "stage"}, "right": {"value": 1}},
            ],
        }
    )
    assert result["satisfiable"]
    assert result["solutions"] == [{"elements": 6, "stage": 2, "voltage": 240}]


def test_formula_engine_dimensions_sensitivity_and_uncertainty() -> None:
    formula = FormulaDefinition.from_mapping(
        admitted_formula(
            {
                "id": "power",
                "expression": "voltage * current",
                "variables": {
                    "voltage": {"dimension": "M L^2 T^-3 I^-1"},
                    "current": {"dimension": "I"},
                },
                "output_dimension": "M L^2 T^-3",
                "assumptions": ["RMS quantities are consistent"],
                "status": "executable",
                "source": "test",
            },
            {"voltage": 240.0, "current": 10.0},
            2400.0,
        )
    )
    result = FormulaEngine([formula]).evaluate(
        "power",
        {"voltage": 240.0, "current": 10.0},
        standard_uncertainties={"voltage": 1.0, "current": 0.1},
    )
    assert result["result"] == pytest.approx(2400.0)
    assert result["output_dimension"] == "L^2 M^1 T^-3"
    assert result["sensitivities"]["voltage"] == pytest.approx(10.0, rel=1e-5)
    assert result["combined_standard_uncertainty"] > 0


def test_formula_engine_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValueError, match="dimension"):
        FormulaEngine(
            [
                FormulaDefinition.from_mapping(
                    admitted_formula(
                        {
                            "id": "bad",
                            "expression": "distance + duration",
                            "variables": {
                                "distance": {"dimension": "L"},
                                "duration": {"dimension": "T"},
                            },
                            "output_dimension": "L",
                            "assumptions": ["none"],
                            "status": "executable",
                            "source": "test",
                        },
                        {"distance": 1.0, "duration": 1.0},
                        2.0,
                    )
                )
            ]
        )


def test_belief_ledger_preserves_conflict() -> None:
    result = project_knowledge(
        {
            "as_of": "2026-01-02T00:00:00Z",
            "beliefs": [
                {
                    "id": "b1",
                    "subject": "unit",
                    "predicate": "voltage",
                    "value": 208,
                    "scope": "case",
                    "confidence": 0.8,
                },
                {
                    "id": "b2",
                    "subject": "unit",
                    "predicate": "voltage",
                    "value": 240,
                    "scope": "case",
                    "confidence": 0.9,
                },
            ],
        }
    )
    assert len(result["contradictions"]) == 1
    assert result["contradictions"][0]["resolution"].startswith("preserve_conflict")


def test_robust_decision_selector_rejects_infeasible() -> None:
    result = choose(
        {
            "risk_posture": "robust",
            "objectives": [
                {"id": "quality", "direction": "maximize", "weight": 2},
                {"id": "cost", "direction": "minimize", "weight": 1},
            ],
            "candidates": [
                {
                    "id": "a",
                    "metrics": {
                        "quality": {"low": 0.7, "expected": 0.8, "high": 0.9},
                        "cost": 10,
                    },
                },
                {
                    "id": "b",
                    "metrics": {
                        "quality": {"low": 0.85, "expected": 0.86, "high": 0.87},
                        "cost": 12,
                    },
                },
                {
                    "id": "c",
                    "constraint_violations": ["not approved"],
                    "metrics": {"quality": 1.0, "cost": 1},
                },
            ],
        }
    )
    assert result["selected"] in {"a", "b"}
    assert result["rejected"][0]["id"] == "c"


def test_calibration_metrics_are_bounded() -> None:
    result = calibration_metrics([0.1, 0.9, 0.7, 0.2], [0, 1, 1, 0], bins=4)
    assert 0 <= result["brier_score"] <= 1
    assert result["log_loss"] >= 0
    assert 0 <= result["expected_calibration_error"] <= 1


def test_facade_healthcheck_and_unknown_operation() -> None:
    assert integration_healthcheck()["valid"]
    assert not run_cognitive_operation("does-not-exist", {})["valid"]


def test_unified_index_is_deterministic_and_leaf_searchable() -> None:
    index = build_cognitive_index(PROJECT_ROOT)
    validation = validate_cognitive_index(PROJECT_ROOT, index)
    assert validation["valid"], validation
    assert index["kind_counts"]["capability"] >= 228
    assert index["kind_counts"]["script"] >= 61
    assert index["kind_counts"]["formula"] >= 103
    navigator = CognitiveNavigator(index)
    result = navigator.search("finite domain constraint solver", limit=3)
    assert result.hits[0].identifier == "finite-domain-constraint-solver"
    plan = navigator.hydration_plan([result.hits[0].key], dependency_depth=2)
    assert plan["records"][0]["path"] == "runtime/cognitive_core/constraint.py"


def test_checked_in_brain_formula_catalog_compiles() -> None:
    from runtime.contracts import validate_instance

    payload = json.loads(
        (PROJECT_ROOT / "registry" / "brain_formulas.json").read_text(encoding="utf-8")
    )
    for item in payload["formulas"]:
        validate_instance(
            item,
            PROJECT_ROOT / "contracts" / "cognitive" / "formula-definition.schema.json",
        )
    engine = FormulaEngine(
        [FormulaDefinition.from_mapping(item) for item in payload["formulas"]]
    )
    assert len(payload["formulas"]) == 8
    assert engine.evaluate("electrical-power-dc", {"voltage": 240, "current": 10})[
        "result"
    ] == pytest.approx(2400)


def test_built_index_matches_checked_in_projection() -> None:
    checked = PROJECT_ROOT / "registry" / "cognitive_map_index.json"
    if not checked.is_file():
        pytest.skip(
            "checked-in cognitive map is not present in this integration target"
        )
    assert json.loads(checked.read_text(encoding="utf-8")) == build_cognitive_index(
        PROJECT_ROOT
    )


def test_probability_rejects_duplicate_hypotheses_and_impossible_evidence() -> None:
    with pytest.raises(ValueError, match="unique"):
        bayesian_portfolio(
            {"hypotheses": [{"id": "a", "prior": 0.5}, {"id": "a", "prior": 0.5}]}
        )
    with pytest.raises(ValueError, match="zero likelihood"):
        bayesian_portfolio(
            {
                "hypotheses": [{"id": "a", "prior": 0.5}, {"id": "b", "prior": 0.5}],
                "evidence": [{"id": "e", "likelihoods": {"a": 0.0, "b": 0.0}}],
            }
        )


def test_probability_reports_uncertainty_increase_instead_of_clamping_it_away() -> None:
    result = bayesian_portfolio(
        {
            "hypotheses": [{"id": "a", "prior": 0.99}, {"id": "b", "prior": 0.01}],
            "evidence": [
                {"id": "counterevidence", "likelihoods": {"a": 0.01, "b": 0.99}}
            ],
        }
    )
    assert result["uncertainty_increased"]
    assert result["entropy_reduction_bits"] < 0


def test_temporal_requires_timezone_and_orders_equivalent_offsets_by_instant() -> None:
    with pytest.raises(ValueError, match="timezone"):
        analyze_temporal({"events": [{"id": "e1", "timestamp": "2026-01-01T00:00:00"}]})
    result = analyze_temporal(
        {
            "events": [
                {"id": "later", "timestamp": "2026-01-01T00:30:00+00:00"},
                {"id": "earlier", "timestamp": "2025-12-31T20:00:00-04:00"},
            ],
        }
    )
    assert result["ordered_event_ids"] == ["earlier", "later"]


def test_isolated_belief_retains_base_confidence() -> None:
    result = project_knowledge(
        {
            "as_of": "2026-01-02T00:00:00Z",
            "beliefs": [
                {
                    "id": "b1",
                    "subject": "unit",
                    "predicate": "voltage",
                    "value": 240,
                    "confidence": 0.8,
                }
            ],
        }
    )
    assert result["beliefs"][0]["effective_confidence"] == pytest.approx(0.8)


def test_minimax_regret_uses_interval_regret_not_expected_regret() -> None:
    expected = choose(
        {
            "risk_posture": "expected",
            "objectives": [{"id": "quality", "direction": "maximize"}],
            "candidates": [
                {
                    "id": "volatile",
                    "metrics": {"quality": {"low": 0.0, "expected": 0.9, "high": 1.0}},
                },
                {
                    "id": "steady",
                    "metrics": {"quality": {"low": 0.6, "expected": 0.6, "high": 0.6}},
                },
            ],
        }
    )
    minimax = choose(
        {
            "risk_posture": "minimax_regret",
            "objectives": [{"id": "quality", "direction": "maximize"}],
            "candidates": [
                {
                    "id": "volatile",
                    "metrics": {"quality": {"low": 0.0, "expected": 0.9, "high": 1.0}},
                },
                {
                    "id": "steady",
                    "metrics": {"quality": {"low": 0.6, "expected": 0.6, "high": 0.6}},
                },
            ],
        }
    )
    assert expected["selected"] == "volatile"
    assert minimax["selected"] == "steady"


def test_formula_engine_rejects_impossible_covariance() -> None:
    formula = FormulaDefinition.from_mapping(
        admitted_formula(
            {
                "id": "sum",
                "expression": "a + b",
                "variables": {"a": {"dimension": "L"}, "b": {"dimension": "L"}},
                "output_dimension": "L",
                "status": "executable",
            },
            {"a": 1.0, "b": 2.0},
            3.0,
        )
    )
    engine = FormulaEngine([formula])
    with pytest.raises(ValueError, match="violates"):
        engine.evaluate(
            "sum",
            {"a": 1.0, "b": 2.0},
            standard_uncertainties={"a": 1.0, "b": 1.0},
            covariances={"a,b": 2.0},
        )


def test_constraint_truncation_means_an_extra_solution_was_observed() -> None:
    exact = solve_constraints({"variables": {"x": [1, 2]}, "max_solutions": 2})
    truncated = solve_constraints({"variables": {"x": [1, 2, 3]}, "max_solutions": 2})
    assert not exact["truncated"]
    assert truncated["truncated"]


def test_structural_analogy_survives_entity_renaming() -> None:
    from runtime.cognitive_core.analogy import compare

    result = compare(
        {
            "source": {
                "mechanisms": ["pressure transfer"],
                "relation_triples": [
                    {"subject": "pump", "relation": "raises", "object": "pressure"},
                    {"subject": "pressure", "relation": "drives", "object": "flow"},
                ],
            },
            "candidates": [
                {
                    "id": "renamed-same-structure",
                    "mechanisms": ["pressure transfer"],
                    "relation_triples": [
                        {
                            "subject": "compressor",
                            "relation": "raises",
                            "object": "head",
                        },
                        {
                            "subject": "head",
                            "relation": "drives",
                            "object": "mass-flow",
                        },
                    ],
                },
                {
                    "id": "different-structure",
                    "mechanisms": ["pressure transfer"],
                    "relation_triples": [
                        {
                            "subject": "compressor",
                            "relation": "raises",
                            "object": "head",
                        },
                        {
                            "subject": "compressor",
                            "relation": "drives",
                            "object": "mass-flow",
                        },
                    ],
                },
            ],
        }
    )
    assert result["selected"] == "renamed-same-structure"
    assert (
        result["ranked_candidates"][0]["structural_relation_score"]
        > result["ranked_candidates"][1]["structural_relation_score"]
    )


def test_abduction_rejects_invalid_probability_instead_of_clamping() -> None:
    from runtime.cognitive_core.abduction import rank_explanations

    with pytest.raises(ValueError, match="prior"):
        rank_explanations(
            {
                "observations": ["no-heat"],
                "hypotheses": [
                    {"id": "element", "prior": 1.2, "explains": ["no-heat"]}
                ],
            }
        )
