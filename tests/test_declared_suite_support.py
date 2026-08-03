import json
import copy
from pathlib import Path

import pytest

from runtime.contracts import ContractValidationError, build_minimal_instance, validate_instance
from runtime.declared_suite import plan_outcome
from runtime.declared_suite_formulas import (
    FORMULAS,
    certification_coverage,
    confidence_combination_independent,
    expected_plan_utility,
    kv_cache_bytes,
    mutation_score,
    population_stability_index,
    precision_recall_f1,
    reciprocal_rank_fusion,
    validate_formula_registry,
    weighted_source_quality,
)


ROOT = Path(__file__).resolve().parents[1]


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_reconstructed_contracts_are_owned_valid_and_reject_empty_objects():
    ownership = load("registry/contract_ownership.json")
    paths = [record["path"] for record in ownership["records"] if record["owner"] == "runtime/declared_suite.py"]
    assert len(paths) == 14
    for relative in paths:
        path = ROOT / relative
        instance = build_minimal_instance(path)
        validate_instance(instance, path)
        with pytest.raises(ContractValidationError):
            validate_instance({}, path)


def test_formula_registry_resolves_to_auditable_implementations():
    registry = load("registry/declared_suite_formulas.json")
    assert validate_formula_registry(registry)["valid"]
    assert registry["formula_count"] == len(registry["formulas"]) == len(FORMULAS) == 18
    assert certification_coverage(3, 4) == 0.75
    assert confidence_combination_independent([0.5, 0.5]) == 0.75
    assert expected_plan_utility([{"probability": 0.5, "utility": 2}, {"probability": 0.5, "utility": 0}], 0.25) == 0.75
    assert kv_cache_bytes(2, 10, 4, 8, 2) == 2560
    assert mutation_score(8, 10) == 0.8
    assert population_stability_index([0.5, 0.5], [0.5, 0.5]) == 0.0
    assert precision_recall_f1(8, 2, 2) == {"precision": 0.8, "recall": 0.8, "f1": pytest.approx(0.8)}
    assert reciprocal_rank_fusion([["a", "b"], ["b", "a"]])[0]["id"] == "a"
    assert weighted_source_quality([{"quality": 1.0, "weight": 1}, {"quality": 0.0, "weight": 1}]) == 0.5
    with pytest.raises(ValueError):
        certification_coverage(1, 0)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda value: value.pop("formula_count"), "missing fields"),
        (lambda value: value.__setitem__("formula_count", 999), "does not match"),
        (lambda value: value.__setitem__("count", value.pop("formula_count")), "missing fields"),
        (lambda value: value["formulas"].append(copy.deepcopy(value["formulas"][0])), "duplicate formula IDs"),
        (lambda value: value["formulas"][0].__setitem__("id", "missing-implementation"), "missing formula implementations"),
    ],
)
def test_formula_registry_rejects_contract_drift(mutation, expected):
    registry = load("registry/declared_suite_formulas.json")
    mutation(registry)
    result = validate_formula_registry(registry)
    assert not result["valid"]
    assert any(expected in error for error in result["errors"])


def test_formula_registry_serialization_is_deterministic():
    registry = load("registry/declared_suite_formulas.json")
    rendered = json.dumps(registry, indent=2, sort_keys=True) + "\n"
    assert rendered == json.dumps(json.loads(rendered), indent=2, sort_keys=True) + "\n"


def test_pack_registries_metadata_templates_and_dependency_graph_are_complete():
    pack_index = load("registry/declared_suite_pack_index.json")
    assert pack_index["pack_count"] == len(pack_index["packs"]) == 7
    assert sum(len(pack["skills"]) for pack in pack_index["packs"].values()) == 134
    assert sum(len(pack["scripts"]) for pack in pack_index["packs"].values()) == 61
    assert sum(len(pack["orchestrations"]) for pack in pack_index["packs"].values()) == 62
    assert {pack["status"] for pack in pack_index["packs"].values()} == {"implemented_and_certified"}
    metadata = load("registry/declared_suite_pack_metadata.json")
    assert metadata["pack_count"] == 7
    graph = load("registry/declared_suite_dependency_graph.json")
    assert len(graph["nodes"]) == 7 and len(graph["edges"]) == 12
    for name in ("certification", "task", "tool-contract"):
        assert load(f"templates/declared_suite/{name}.json")


def test_all_generated_behavior_cases_have_positive_and_negative_results():
    suite = load("registry/declared_suite_behavior_cases.json")
    assert suite["case_count"] == len(suite["cases"]) == 257
    for case in suite["cases"]:
        kind, outcome_id = case["id"].split(":", 1)
        assert plan_outcome(ROOT, kind, outcome_id, case["positive"])["valid"]
        assert not plan_outcome(ROOT, kind, outcome_id, case["negative"])["valid"]


def test_every_support_card_has_a_concrete_product_target():
    ledger = load("registry/declared_suite_reconstruction.json")
    cards = [card for card in ledger["cards"] if card["class"] == "supporting_artifact"]
    assert len(cards) == 118
    for card in cards:
        assert card["implementation_targets"]
        for target in card["implementation_targets"]:
            assert (ROOT / target).exists(), (card["card_id"], target)
