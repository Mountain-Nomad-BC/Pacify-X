"""Build the complete count-bearing registry invariant inventory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def record(
    path: str,
    count_key: str,
    collection_key: str,
    rule: str = "length",
    **extra: object,
) -> dict[str, object]:
    producers = {
        "registry/admission_queue.json": "scripts/build_admission_queue.py",
        "registry/agency_agent_registry.json": "runtime/agent_provider.py",
        "registry/artifact_reachability.json": "scripts/build_artifact_reachability.py",
        "registry/contract_ownership.json": "scripts/build_contract_ownership_registry.py",
        "registry/cognitive_map_index.json": "scripts/build_cognitive_index.py",
        "registry/corrective_release_ledger.json": "runtime/corrective_release.py",
        "registry/current_evidence_index.json": "scripts/build_current_evidence_index.py",
        "registry/effect_surface_ownership.json": "scripts/build_effect_surface_ownership.py",
        "registry/external_candidate_graph.json": "scripts/build_external_candidate_registry.py",
        "registry/external_capability_catalog.json": "scripts/build_external_candidate_registry.py",
        "registry/full_repair_ledger.json": "runtime/full_repair.py",
        "registry/graphs/project_stream_dependency_graph.json": "runtime/graph_registry.py",
        "registry/historical_external_references.json": "scripts/build_historical_external_references.py",
        "registry/security_capabilities/native_skill_dispositions.json": "scripts/build_cybersecurity_provider_registry.py",
        "registry/security_capabilities/workflow_dispositions.json": "scripts/build_cybersecurity_provider_registry.py",
        "registry/project_stream_handlers.json": "scripts/reconcile_project_stream_registry.py",
        "registry/project_stream_orchestrations.json": "scripts/reconcile_project_stream_registry.py",
        "registry/python_surface_ownership.json": "scripts/build_python_surface_ownership.py",
        "registry/reference_candidate_admission.json": "scripts/reconcile_reference_candidate_admission.py",
        "registry/semantic_capability_index.json": "scripts/build_semantic_capability_index.py",
        "registry/source_specialty_admission.json": "scripts/migration/admit_capability_mining_skills.py",
        "registry/specialty_map.json": "scripts/build_specialty_map.py",
        "registry/workflow_execution_bindings.json": "runtime/structural_integrity.py",
    }
    producer = producers.get(path, "builders/last_round_assimilation_builder.py")
    return {
        "path": path,
        "count_key": count_key,
        "collection_key": collection_key,
        "rule": rule,
        "schema": "root schema_version plus shared registry-envelope invariant",
        "builder": producer,
        "consumer": "runtime/registry_envelope.py",
        **extra,
    }


def build_inventory() -> dict[str, object]:
    rows = [
        record("registry/admission_queue.json", "candidate_count", "candidates"),
        record("registry/agency_agent_registry.json", "agent_count", "agents"),
        record("registry/artifact_reachability.json", "record_count", "records"),
        record("registry/assurance_capabilities.json", "count", "capabilities"),
        record("registry/contract_ownership.json", "contract_count", "records"),
        record("registry/cognitive_dependency_resolutions.json", "count", "records"),
        record("registry/cognitive_map_index.json", "edge_count", "edges"),
        record("registry/cognitive_map_index.json", "record_count", "records"),
        record("registry/corrective_release_ledger.json", "card_count", "cards"),
        record(
            "registry/current_evidence_index.json",
            "artifact_count",
            "records",
            "filtered",
            field="kind",
            equals="vsix",
        ),
        record(
            "registry/current_evidence_index.json",
            "required_receipt_count",
            "records",
            "filtered",
            field="kind",
            equals="test-receipt",
        ),
        record(
            "registry/current_evidence_index.json",
            "current_required_receipt_count",
            "records",
            "nested_object_filtered",
            nested="receipt_state",
            field="current",
            equals=True,
        ),
        record("registry/current_evidence_index.json", "record_count", "records"),
        record(
            "registry/corrective_release_ledger.json",
            "child_finding_count",
            "cards",
            "child_cards",
        ),
        record(
            "registry/corrective_release_ledger.json",
            "source_card_count",
            "cards",
            "source_cards",
        ),
        record("registry/effect_surface_ownership.json", "record_count", "records"),
        record(
            "registry/engineering_reasoning_expansion.json", "record_count", "records"
        ),
        record("registry/external_candidate_graph.json", "edge_count", "edges"),
        record("registry/external_capability_benchmarks.json", "case_count", "cases"),
        record(
            "registry/external_capability_candidates.json",
            "capability_count",
            "capabilities",
        ),
        record("registry/external_capability_catalog.json", "record_count", "records"),
        record("registry/external_skill_bundles.json", "package_count", "packages"),
        record("registry/full_repair_ledger.json", "card_count", "cards"),
        record(
            "registry/declared_capability_recovery_map.json", "record_count", "records"
        ),
        record("registry/declared_outcome_owners.json", "record_count", "records"),
        record("registry/declared_suite_behavior_cases.json", "case_count", "cases"),
        record("registry/declared_suite_formulas.json", "formula_count", "formulas"),
        record("registry/declared_suite_knowledge.json", "count", "records"),
        record("registry/declared_suite_pack_index.json", "pack_count", "packs"),
        record("registry/declared_suite_pack_metadata.json", "pack_count", "packs"),
        record("registry/declared_suite_schema_contracts.json", "count", "records"),
        record(
            "registry/graphs/project_stream_dependency_graph.json",
            "capability_reference_count",
            "edges",
        ),
        record(
            "registry/graphs/project_stream_dependency_graph.json",
            "node_count",
            "nodes",
        ),
        record(
            "registry/graphs/project_stream_dependency_graph.json",
            "orchestration_count",
            "edges",
            "unique",
            field="source",
        ),
        record(
            "registry/historical_external_references.json", "reference_count", "records"
        ),
        record("registry/metacognitive_capabilities.json", "count", "capabilities"),
        record("registry/metacognitive_capability_owners.json", "count", "records"),
        record("registry/operational_capabilities.json", "count", "capabilities"),
        record("registry/project_stream_capabilities.json", "count", "capabilities"),
        record(
            "registry/project_stream_handlers.json",
            "executable_count",
            "workflows",
            "filtered",
            field="status",
            equals="executable",
        ),
        record(
            "registry/project_stream_handlers.json",
            "plan_only_count",
            "workflows",
            "filtered",
            field="status",
            equals="plan_only",
        ),
        record(
            "registry/project_stream_orchestrations.json", "count", "orchestrations"
        ),
        record(
            "registry/provider_route_scan.json",
            "rescanned_file_count",
            "records",
            "filtered",
            field="scan_state",
            equals="rescanned",
        ),
        record(
            "registry/provider_route_scan.json",
            "reused_file_count",
            "records",
            "filtered",
            field="scan_state",
            equals="reused",
        ),
        record(
            "registry/python_surface_ownership.json",
            "direct_behavior_count",
            "records",
            "filtered",
            field="validation_level",
            equals="direct-isolated-behavior",
        ),
        record(
            "registry/python_surface_ownership.json",
            "evidence_association_count",
            "records",
            "filtered",
            field="validation_level",
            equals="evidence-association",
        ),
        record(
            "registry/python_surface_ownership.json",
            "packaged_file_count",
            "records",
            "filtered",
            field="packaged",
            equals=True,
        ),
        record(
            "registry/python_surface_ownership.json", "python_file_count", "records"
        ),
        record(
            "registry/python_surface_ownership.json",
            "source_only_structural_count",
            "records",
            "filtered",
            field="validation_level",
            equals="source-only-structural",
        ),
        record(
            "registry/python_surface_ownership.json",
            "syntax_valid_count",
            "records",
            "filtered",
            field="syntax_valid",
            equals=True,
        ),
        record(
            "registry/reference_candidate_admission.json",
            "canonical_candidate_count",
            "records",
            "unique",
            field="canonical_id",
        ),
        record(
            "registry/reference_candidate_admission.json",
            "duplicate_source_record_count",
            "records",
            "duplicates",
            field="canonical_id",
        ),
        record(
            "registry/reference_candidate_admission.json",
            "source_record_count",
            "records",
        ),
        record("registry/scheduling_capabilities.json", "count", "capabilities"),
        record("registry/scheduling_capability_owners.json", "count", "records"),
        record("registry/scheduling_policies.json", "count", "policies"),
        record(
            "registry/security_capabilities/domains.json",
            "canonical_domain_count",
            "canonical_counts",
        ),
        record(
            "registry/security_capabilities/domains.json",
            "source_raw_domain_count",
            "raw_counts",
        ),
        record(
            "registry/security_capabilities/native_skill_dispositions.json",
            "count",
            "records",
        ),
        record(
            "registry/security_capabilities/workflow_dispositions.json",
            "count",
            "records",
        ),
        record("registry/semantic_capability_index.json", "record_count", "records"),
        record("registry/service_capability_catalog.json", "record_count", "records"),
        record(
            "registry/service_capability_workflows.json", "workflow_count", "workflows"
        ),
        record("registry/skill_orchestrations.json", "count", "workflows"),
        record(
            "registry/test_group_index.json",
            "parsed_file_count",
            "files",
            "filtered_values",
            field="index_state",
            equals="parsed",
        ),
        record(
            "registry/test_group_index.json",
            "reused_file_count",
            "files",
            "filtered_values",
            field="index_state",
            equals="reused",
        ),
        record(
            "registry/test_group_index.json",
            "test_file_count",
            "groups",
            "nested_length",
            nested="members",
        ),
        record(
            "registry/test_group_index.json",
            "tracked_python_file_count",
            "files",
        ),
        record(
            "registry/source_specialty_admission.json", "source_record_count", "records"
        ),
        record(
            "registry/specialty_map.json",
            "active_candidate_count",
            "categories",
            "nested_filtered",
            nested="specialties",
            field="state",
            equals="active",
        ),
        record(
            "registry/specialty_map.json",
            "candidate_count",
            "categories",
            "nested_length",
            nested="specialties",
        ),
        record(
            "registry/specialty_map.json",
            "deferred_candidate_count",
            "categories",
            "nested_filtered",
            nested="specialties",
            field="state",
            equals="mapped_deferred",
        ),
        record("registry/workflow_execution_bindings.json", "count", "bindings"),
    ]
    return {
        "schema_version": "1.0",
        "policy": "Every count-bearing registry field is derived from its owned collection and validated before certification.",
        "records": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = args.root.resolve() / "registry/registry_envelope_inventory.json"
    rendered = json.dumps(build_inventory(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
            raise SystemExit("registry envelope inventory is stale")
    else:
        path.write_text(rendered, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "valid": True,
                "records": len(build_inventory()["records"]),
                "check": args.check,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
