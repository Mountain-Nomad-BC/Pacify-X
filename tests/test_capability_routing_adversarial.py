from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.capability_routing import certify_router
from runtime.skill_navigator import CapabilitySummary


ROOT = Path(__file__).parents[1]


def _one_case():
    return {
        "thresholds": {"precision_at_1": 0.0, "precision_at_3": 0.0, "precision_at_5": 0.0},
        "cases": [{"case_id": "disk", "query": "disk capacity", "expected": ["disk-capacity-analyzer"], "must_not_return": []}],
    }


@pytest.mark.parametrize("thresholds", [None, {}, {"precision_at_1": 1.0},
    {"precision_at_1": True, "precision_at_3": 0.0, "precision_at_5": 0.0},
    {"precision_at_1": float("nan"), "precision_at_3": 0.0, "precision_at_5": 0.0},
    {"precision_at_1": -1.0, "precision_at_3": 0.0, "precision_at_5": 0.0},
])
def test_router_receipt_requires_complete_finite_thresholds(thresholds):
    corpus = _one_case()
    corpus["thresholds"] = thresholds
    with pytest.raises(ValueError):
        certify_router(corpus, _records(), index_revision="test", project_revision=None)


@pytest.mark.parametrize("mutation", ["duplicate-case", "unknown-expected", "string-expected", "overlap"])
def test_router_receipt_rejects_ambiguous_case_denominator(mutation):
    corpus = _one_case()
    case = corpus["cases"][0]
    if mutation == "duplicate-case":
        corpus["cases"].append(dict(case))
    elif mutation == "unknown-expected":
        case["expected"] = ["unknown"]
    elif mutation == "string-expected":
        case["expected"] = "disk-capacity-analyzer"
    else:
        case["must_not_return"] = list(case["expected"])
    with pytest.raises(ValueError):
        certify_router(corpus, _records(), index_revision="test", project_revision=None)


def test_zero_thresholds_cannot_certify_an_empty_returned_denominator(monkeypatch):
    monkeypatch.setattr("runtime.capability_routing.route_task", lambda *a, **k: SimpleNamespace(ranked=()))
    receipt = certify_router(_one_case(), _records(), index_revision="test", project_revision=None)
    assert not receipt["valid"]
    assert receipt["threshold_pass"]
    assert not receipt["coverage_pass"]
    assert receipt["covered_case_count"] == 0
    assert receipt["case_count"] == 1


def _records():
    values = (
        CapabilitySummary("disk-capacity-analyzer", "analyze disk storage capacity growth", capability_tags=("disk", "storage", "capacity")),
        CapabilitySummary("personal-growth-coach", "coach personal emotional growth", capability_tags=("personal", "coaching"), negative_matches=("disk storage", "capacity growth")),
        CapabilitySummary("process-debugger", "debug crashing operating system process", capability_tags=("operating", "system", "process")),
        CapabilitySummary("n8n-workflow-debugger", "debug n8n automation workflow", capability_tags=("n8n", "workflow"), negative_matches=("operating system process",)),
        CapabilitySummary("agent-memory-retrieval", "optimize AI agent memory retrieval", capability_tags=("ai", "agent", "memory", "retrieval")),
        CapabilitySummary("database-storage-manager", "manage database table storage", capability_tags=("database", "storage")),
        CapabilitySummary("ml-model-state-inspector", "inspect machine learning model checkpoint state", capability_tags=("machine", "learning", "checkpoint")),
        CapabilitySummary("product-domain-modeler", "design product business domain model", capability_tags=("product", "business"), negative_matches=("model checkpoint state", "machine learning")),
        CapabilitySummary("safe-data-reviewer", "review and preserve data without mutation", capability_tags=("review", "preserve", "data")),
        CapabilitySummary("unsafe-data-deleter", "delete data", negative_matches=("preserving", "without deleting"), risk="R4", reviewed_by=()),
        CapabilitySummary("current-deployment-skill", "deploy governed service release", supersedes=("stale-deployment-skill",)),
        CapabilitySummary("stale-deployment-skill", "deploy governed service release", status="deprecated"),
    )
    return {item.capability_id: item for item in values}


def test_fixed_adversarial_router_corpus_passes_all_metrics_and_exclusions():
    corpus = json.loads(
        (ROOT / "tests/fixtures/adversarial_router_corpus.json").read_text(encoding="utf-8")
    )
    receipt = certify_router(
        corpus,
        _records(),
        index_revision="semantic-index-fixture-v1",
        project_revision="project-map-fixture-v1",
    )
    assert receipt["valid"], receipt
    assert receipt["must_not_return_pass"]
    assert receipt["deterministic_ties"]
    assert all(row["top1_correct"] for row in receipt["case_outcomes"])
    assert receipt["corpus_sha256"] and receipt["index_revision"]
