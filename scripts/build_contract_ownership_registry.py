"""Build the explicit one-record-per-contract ownership registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT_OWNERS = {
    "project-impact.schema.json": (
        "runtime/project_impact.py",
        ["runtime/project_impact.py", "runtime/cli.py"],
        "runtime_enforced",
        ["tests/test_project_mapping.py"],
    ),
    "project-map.schema.json": (
        "runtime/project_intelligence.py",
        ["runtime/project_intelligence.py"],
        "runtime_enforced",
        ["tests/test_project_mapping.py"],
    ),
    "authorization-request.schema.json": (
        "runtime/execution_contract.py",
        ["runtime/cli.py"],
        "runtime_enforced",
        ["tests/test_trust_boundaries.py"],
    ),
    "authoritative-skill-contract.schema.json": (
        ".agents/skills/govern-operating-kernel/scripts/authoritative_skill_compiler.py",
        [
            ".agents/skills/govern-operating-kernel/scripts/authoritative_skill_compiler.py"
        ],
        "runtime_enforced",
        ["tests/test_authoritative_skill_compiler.py"],
    ),
    "builder-contract.schema.json": (
        "builders/common.py",
        ["builders/skill_builder.py", "builders/orchestration_builder.py"],
        "builder_boundary",
        ["tests/test_wave5_builders.py"],
    ),
    "capability-contract.schema.json": (
        "runtime/registry.py",
        ["builders/skill_builder.py"],
        "runtime_registry_boundary",
        ["tests/test_config_and_registry.py"],
    ),
    "candidate-admission-request.schema.json": (
        "runtime/admission_controller.py",
        ["runtime/cli.py"],
        "runtime_enforced",
        ["tests/test_trust_boundaries.py"],
    ),
    "commissioning-questionnaire.schema.json": (
        "runtime/commissioning.py",
        ["runtime/commissioning.py"],
        "runtime_enforced",
        ["tests/test_commissioning_questionnaire.py"],
    ),
    "containment-action.schema.json": (
        "runtime/assurance_controls.py",
        ["runtime/assurance_controls.py"],
        "runtime_control_equivalent",
        ["tests/test_assurance_controls.py"],
    ),
    "evidence-record.schema.json": (
        "runtime/evidence_assembler.py",
        ["runtime/evidence_assembler.py"],
        "runtime_control_equivalent",
        ["tests/test_evidence_assembler.py"],
    ),
    "evidence-reference.schema.json": (
        "runtime/external_evidence.py",
        ["runtime/external_evidence.py"],
        "runtime_enforced",
        ["tests/test_external_evidence.py"],
    ),
    "external-tool-intake.schema.json": (
        "runtime/tool_intake.py",
        ["runtime/tool_intake.py"],
        "runtime_enforced",
        ["tests/test_tool_intake.py"],
    ),
    "engineering-process-record.schema.json": (
        "runtime/process_memory.py",
        ["runtime/process_memory.py"],
        "runtime_enforced",
        ["tests/test_process_memory.py"],
    ),
    "integration-contract.schema.json": (
        "runtime/integration_registry.py",
        ["runtime/integration_registry.py", "registry/integrations.json"],
        "runtime_registry_boundary",
        ["tests/test_retrieval_and_models.py"],
    ),
    "knowledge-source.schema.json": (
        "runtime/retrieval.py",
        ["runtime/retrieval.py"],
        "runtime_control_equivalent",
        ["tests/test_retrieval_and_models.py"],
    ),
    "model-contract.schema.json": (
        "runtime/models.py",
        ["runtime/models.py"],
        "runtime_registry_boundary",
        ["tests/test_retrieval_and_models.py"],
    ),
    "orchestration-contract.schema.json": (
        "runtime/graphs.py",
        ["builders/orchestration_builder.py"],
        "builder_and_registry_boundary",
        ["tests/test_graphs_and_orchestrations.py"],
    ),
    "outcome-verification-request.schema.json": (
        "runtime/outcome_verifier.py",
        ["runtime/cli.py"],
        "runtime_enforced",
        ["tests/test_trust_boundaries.py"],
    ),
    "policy-contract.schema.json": (
        "runtime/execution_contract.py",
        ["runtime/execution_contract.py"],
        "runtime_control_equivalent",
        ["tests/test_execution_contract.py"],
    ),
    "project-management.schema.json": (
        "runtime/project_management.py",
        ["runtime/project_management.py"],
        "runtime_enforced",
        ["tests/test_commissioning_apply.py"],
    ),
    "runtime-assurance.schema.json": (
        "runtime/cognitive_assurance.py",
        ["runtime/cognitive_assurance.py"],
        "runtime_control_equivalent",
        ["tests/test_cognitive_assurance.py"],
    ),
    "skeptical-certification.schema.json": (
        "runtime/assurance_controls.py",
        ["runtime/assurance_controls.py"],
        "runtime_control_equivalent",
        ["tests/test_assurance_controls.py"],
    ),
    "skill-package.schema.json": (
        "runtime/lazy_loader.py",
        ["builders/skill_builder.py"],
        "runtime_registry_boundary",
        ["tests/test_skill_library.py"],
    ),
    "source-capability-audit.schema.json": (
        "runtime/capability_assimilation.py",
        [
            ".agents/skills/audit-source-capabilities/scripts/audit_source_capabilities.py"
        ],
        "runtime_registry_boundary",
        [
            "tests/test_capability_assimilation.py",
            "tests/test_capability_mining_skills.py",
        ],
    ),
    "source-intake-event.schema.json": (
        "runtime/intake_lifecycle.py",
        ["runtime/intake_lifecycle.py"],
        "runtime_control_equivalent",
        ["tests/test_intake_lifecycle.py"],
    ),
    "tool-contract.schema.json": (
        "runtime/registry.py",
        ["registry/tools.json"],
        "runtime_registry_boundary",
        ["tests/test_config_and_registry.py"],
    ),
    "trusted-evidence-record.schema.json": (
        "runtime/trusted_evidence.py",
        ["runtime/trusted_evidence.py"],
        "runtime_enforced",
        ["tests/test_trust_boundaries.py"],
    ),
    "ui-context.schema.json": (
        "runtime/classifier.py",
        ["runtime/classifier.py"],
        "runtime_control_equivalent",
        ["tests/test_runtime_wave4.py"],
    ),
    "validation-contract.schema.json": (
        "runtime/outcome_verifier.py",
        ["runtime/outcome_verifier.py"],
        "runtime_control_equivalent",
        ["tests/test_outcome_verifier.py"],
    ),
}

PROJECT_OWNERS = {
    "active-session.schema.json": ("runtime/workspace_manager.py", "runtime_enforced"),
    "agent-memory-provider-certificate.schema.json": (
        "runtime/provider_certification.py",
        "typed_runtime_equivalent",
    ),
    "agent_record.schema.json": (
        "runtime/project_control_plane.py",
        "typed_runtime_equivalent",
    ),
    "capability_record.schema.json": (
        "runtime/project_control_plane.py",
        "typed_runtime_equivalent",
    ),
    "decision_record.schema.json": (
        "runtime/project_control_plane.py",
        "typed_runtime_equivalent",
    ),
    "lock_record.schema.json": ("runtime/file_lock.py", "typed_runtime_equivalent"),
    "memory_note.schema.json": ("runtime/memory_fabric.py", "typed_runtime_equivalent"),
    "orchestration_record.schema.json": (
        "runtime/project_stream_orchestrator.py",
        "typed_runtime_equivalent",
    ),
    "project-scope-envelope.schema.json": (
        "runtime/project_stream_controls.py",
        "runtime_enforced_via_active_session",
    ),
    "project_record.schema.json": (
        "runtime/commissioning.py",
        "typed_runtime_equivalent",
    ),
    "quarantine_record.schema.json": (
        "runtime/project_control_plane.py",
        "typed_runtime_equivalent",
    ),
    "repository_record.schema.json": (
        "runtime/project_control_plane.py",
        "typed_runtime_equivalent",
    ),
    "transfer_package.schema.json": (
        "runtime/project_stream_controls.py",
        "typed_runtime_equivalent",
    ),
    "workflow-request.schema.json": (
        "runtime/workspace_manager.py",
        "runtime_control_equivalent",
    ),
    "workspace-binding.schema.json": (
        "runtime/workspace_manager.py",
        "runtime_enforced",
    ),
    "workspace-registry.schema.json": (
        "runtime/workspace_manager.py",
        "runtime_enforced",
    ),
    "workspace_config.schema.json": (
        "runtime/workspace_manager.py",
        "runtime_enforced",
    ),
    "workstream.schema.json": (
        "runtime/project_control_plane.py",
        "typed_runtime_equivalent",
    ),
    "durable-goal-state.schema.json": ("runtime/durable_state.py", "runtime_enforced"),
}

AGENT_OWNERS = {
    "agency-agent-manifest.schema.json": ["registry/agency_agent_registry.json"],
    "agent-evidence-receipt.schema.json": ["runtime/agent_provider.py"],
    "agent-handoff.schema.json": ["runtime/agent_provider.py"],
    "agent-result.schema.json": ["runtime/agent_provider.py"],
    "agent-route-plan.schema.json": ["runtime/agent_provider.py", "runtime/cli.py"],
    "agent-task-envelope.schema.json": ["runtime/agent_provider.py", "runtime/cli.py"],
    "fleet-readiness.schema.json": ["runtime/agent_fleet_controls.py"],
    "terminal-session-adapter.schema.json": ["runtime/agent_fleet_controls.py"],
}

TRANSCRIPT_OWNERS = {
    "transcript-profile.schema.json": [
        "runtime/transcript_analysis.py",
        "runtime/cli.py",
    ],
    "transcript-source.schema.json": ["runtime/transcript_analysis.py"],
    "transcript-record.schema.json": [
        "runtime/transcript_analysis.py",
        "runtime/cli.py",
    ],
    "transcript-ontology.schema.json": ["runtime/transcript_analysis.py"],
}

MEMORY_OWNERS = {
    "memory-event.schema.json": ["runtime/memory_intelligence.py"],
    "memory-loadout.schema.json": [
        "runtime/memory_intelligence.py",
        "runtime/agent_provider.py",
    ],
    "memory-offload-pointer.schema.json": ["runtime/memory_intelligence.py"],
    "memory-promotion-decision.schema.json": [
        "runtime/memory_intelligence.py",
        "runtime/memory_vault.py",
    ],
    "memory-recall-package.schema.json": ["runtime/memory_intelligence.py"],
    "memory-evaluation-fixture.schema.json": ["runtime/memory_intelligence.py"],
    "memory-remediation-plan.schema.json": ["runtime/memory_remediation.py"],
}

EXTERNAL_CAPABILITY_OWNERS = {
    "external-capability-candidate.schema.json": [
        "runtime/external_capability_provider.py"
    ],
    "selective-stage-plan.schema.json": [
        "runtime/external_capability_provider.py",
        "runtime/cli.py",
    ],
    "hook-decision.schema.json": ["runtime/external_capability_provider.py"],
    "session-snapshot.schema.json": ["runtime/external_capability_provider.py"],
    "routing-economics.schema.json": ["runtime/external_capability_provider.py"],
    "backend-service-capability.schema.json": ["runtime/backend_capabilities.py"],
}

REASONING_OWNERS = {
    "decision-frontier.schema.json": [
        "runtime/project_reasoning/frontier.py",
        "runtime/cli.py",
    ],
    "glossary-audit.schema.json": [
        "runtime/project_reasoning/glossary_audit.py",
        "runtime/cli.py",
    ],
    "module-depth-audit.schema.json": [
        "runtime/project_reasoning/deep_module_audit.py",
        "runtime/cli.py",
    ],
    "independent-hypothesis-panel.schema.json": ["runtime/reasoning_controls.py"],
    "communication-budget.schema.json": ["runtime/reasoning_controls.py"],
    "specification-lifecycle.schema.json": ["runtime/durable_state.py"],
}

COGNITIVE_OWNERS = {
    "behavioral-delta-certificate.schema.json": ["runtime/behavioral_certification.py"],
    "shadow-behavior-comparison.schema.json": ["runtime/behavioral_certification.py"],
}

KNOWLEDGE_REFINERY_OWNERS = {
    "portable-inventory.schema.json": [
        "runtime/knowledge_refinery.py",
        "runtime/cli.py",
    ],
    "novelty-report.schema.json": ["runtime/knowledge_refinery.py", "runtime/cli.py"],
    "merge-plan.schema.json": ["runtime/knowledge_refinery.py", "runtime/cli.py"],
    "graph-audit.schema.json": ["runtime/knowledge_refinery.py", "runtime/cli.py"],
}


def build(root: Path) -> dict[str, object]:
    existing_path = root / "registry/contract_ownership.json"
    existing = {
        str(item["path"]): item
        for item in (
            json.loads(existing_path.read_text(encoding="utf-8")).get("records", [])
            if existing_path.is_file()
            else []
        )
    }
    records = []
    for path in sorted((root / "contracts").rglob("*.json")):
        relative = path.relative_to(root).as_posix()
        name = path.name
        schema = json.loads(path.read_text(encoding="utf-8"))
        if path.parent.name == "completion":
            owner, enforcement = (
                "runtime/completion_controls.py",
                "completion_control_runtime_boundary",
            )
            producers = ["runtime/completion_controls.py"]
            tests = ["tests/test_completion_controls.py"]
        elif path.parent.name == "knowledge_refinery":
            owner, enforcement = (
                "runtime/knowledge_refinery.py",
                "knowledge_refinery_runtime_boundary",
            )
            producers = KNOWLEDGE_REFINERY_OWNERS[name]
            tests = ["tests/test_knowledge_refinery.py"]
        elif path.parent.name == "cognitive" and name in COGNITIVE_OWNERS:
            producers = COGNITIVE_OWNERS[name]
            owner, enforcement = producers[0], "observable_behavior_runtime_boundary"
            tests = ["tests/test_clean_room_capabilities.py"]
        elif path.parent.name == "reasoning":
            producers = REASONING_OWNERS[name]
            owner, enforcement = producers[0], "engineering_reasoning_runtime_boundary"
            tests = [
                "tests/test_project_reasoning.py",
                "tests/test_clean_room_capabilities.py",
            ]
        elif path.parent.name == "external_capabilities":
            producers = EXTERNAL_CAPABILITY_OWNERS[name]
            owner, enforcement = producers[0], "external_candidate_runtime_boundary"
            tests = [
                "tests/test_external_capability_provider.py",
                "tests/test_clean_room_capabilities.py",
            ]
        elif path.parent.name == "security_capabilities":
            owner, enforcement = (
                "runtime/cybersecurity_provider.py",
                "security_provider_runtime_boundary",
            )
            producers = ["runtime/cybersecurity_provider.py", "runtime/cli.py"]
            tests = ["tests/test_cybersecurity_provider.py"]
        elif path.parent.name == "memory":
            producers = MEMORY_OWNERS[name]
            owner, enforcement = producers[0], "memory_lifecycle_runtime_boundary"
            tests = [
                "tests/test_memory_intelligence.py",
                "tests/test_clean_room_capabilities.py",
            ]
        elif path.parent.name == "transcripts":
            owner, enforcement = (
                "runtime/transcript_analysis.py",
                "transcript_runtime_boundary",
            )
            producers = TRANSCRIPT_OWNERS[name]
            tests = ["tests/test_transcript_analysis.py"]
        elif path.parent.name == "agents":
            producers = AGENT_OWNERS[name]
            owner, enforcement = producers[0], "agent_runtime_boundary"
            tests = [
                "tests/test_agent_provider.py",
                "tests/test_clean_room_capabilities.py",
            ]
        elif path.parent.name == "project_stream":
            owner, enforcement = PROJECT_OWNERS[name]
            producers = [owner]
            tests = [
                "tests/test_contract_runtime.py",
                "tests/test_temp2_completeness.py",
            ]
        elif path.parent.name == "research_ops":
            owner, enforcement = "runtime/research_assimilation.py", "runtime_enforced"
            producers = [
                "runtime/knowledge_foundry.py",
                "runtime/research_assimilation.py",
            ]
            tests = [
                "tests/test_contract_runtime.py",
                "tests/test_research_contract_admission.py",
            ]
        elif name in ROOT_OWNERS:
            owner, producers, enforcement, tests = ROOT_OWNERS[name]
        elif relative in existing:
            prior = existing[relative]
            owner = prior["owner"]
            producers = list(prior.get("producers", []))
            enforcement = prior["enforcement"]
            tests = list(prior.get("tests", []))
        else:
            raise ValueError(f"contract has no ownership rule: {relative}")
        records.append(
            {
                "path": relative,
                "contract_id": schema.get("$id"),
                "contract_version": "1.0.0",
                "title": schema.get("title", name),
                "owner": owner,
                "producers": producers,
                "consumers": ["runtime/contracts.py"],
                "enforcement": enforcement,
                "packaged": True,
                "tests": list(
                    dict.fromkeys(["tests/test_contract_runtime.py", *tests])
                ),
            }
        )
    return {
        "schema_version": "2.0",
        "policy": "Every shipped schema has one explicit owner and an honest enforcement classification.",
        "contract_count": len(records),
        "records": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    result = build(root)
    target = root / "registry" / "contract_ownership.json"
    target.write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({"contract_count": result["contract_count"]}, indent=2))
