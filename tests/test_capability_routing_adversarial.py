from __future__ import annotations

import json
from pathlib import Path

from runtime.capability_routing import certify_router
from runtime.skill_navigator import CapabilitySummary


ROOT = Path(__file__).parents[1]


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
