"""Reconcile source candidate claims with current bounded runtime functions."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


PARTIAL_RUNTIME = {
    "architecture-entropy-monitor": ("analyze-engineering-intelligence", "runtime.engineering_intelligence.architecture_drift"),
    "semantic-drift-detector": ("analyze-engineering-intelligence", "runtime.engineering_intelligence.semantic_drift"),
    "future-maintainability-reviewer": ("analyze-engineering-intelligence", "runtime.engineering_intelligence.future_debt"),
    "business-logic-collision-detector": ("analyze-engineering-intelligence", "runtime.engineering_intelligence.knowledge_collisions"),
    "knowledge-collision-detector": ("analyze-engineering-intelligence", "runtime.engineering_intelligence.knowledge_collisions"),
    "autonomous-refactoring-planner": ("analyze-engineering-intelligence", "runtime.engineering_intelligence.refactoring_plan"),
    "engineering-consistency-engine": ("analyze-engineering-intelligence", "runtime.engineering_intelligence.engineering_health"),
    "skill-evolution-manager": ("analyze-engineering-intelligence", "runtime.engineering_intelligence.opportunity_backlog"),
    "knowledge-compiler": ("forge-skills-from-knowledge", "runtime.knowledge_foundry.compile_foundry_bundle"),
    "knowledge-fitness-scorer": ("analyze-engineering-intelligence", "runtime.engineering_intelligence.project_fitness"),
    "runtime-self-auditor": ("audit-ai-runtime-assurance", "runtime.cognitive_assurance.runtime_passport"),
    "certified-memory-manager": ("govern-memory-fabric", "runtime.memory_vault.MemoryVault.transition"),
    "memory-health-monitor": ("govern-memory-fabric", "runtime.memory_vault.MemoryVault.reconcile_indexes"),
    "memory-provider-reliability-adapter": ("govern-memory-fabric", "runtime.provider_certification.run_provider_isolation_suite"),
    "memory-index-reconciler": ("govern-memory-fabric", "runtime.memory_vault.MemoryVault.reconcile_indexes"),
}


def reconcile(value: dict[str, object]) -> dict[str, object]:
    records = value["records"]
    for item in records:
        canonical = item["canonical_id"]
        if canonical not in PARTIAL_RUNTIME or item["delivery_state"] == "active_composed":
            continue
        skill, symbol = PARTIAL_RUNTIME[canonical]
        item["delivery_state"] = "partial_semantic_coverage"
        item["active_mappings"] = sorted(set([*item.get("active_mappings", ()), skill]))
        item["runtime_symbols"] = sorted(set([*item.get("runtime_symbols", ()), symbol]))
        item["boundary"] = "A bounded function exists; the broader named source capability remains unadmitted until its full contract and tests are implemented."
    counts = Counter(item["delivery_state"] for item in records)
    value["delivery_counts"] = dict(sorted(counts.items()))
    canonicals = {item["canonical_id"] for item in records}
    value["canonical_candidate_count"] = len(canonicals)
    value["duplicate_source_record_count"] = len(records) - len(canonicals)
    value["runtime_reconciliation"] = "2026-08-02-structural-recertification"
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path.cwd())
    root = parser.parse_args().root.resolve(); path = root / "registry/reference_candidate_admission.json"
    value = reconcile(json.loads(path.read_text(encoding="utf-8")))
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"delivery_counts": value["delivery_counts"], "canonical_candidate_count": value["canonical_candidate_count"]}, indent=2))
