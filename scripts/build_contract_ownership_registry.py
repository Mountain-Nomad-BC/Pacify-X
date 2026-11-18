"""Build the explicit one-record-per-contract ownership registry."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.guarded_registry_projection import publish_guarded_registry_projection  # noqa: E402


ROOT_OWNERS = {
    # Functional ownership, not direct consumption: no module imports, references or
    # depends on this schema document or its id (verified: zero references across
    # runtime/, scripts/, tests/ and extension/src/). The declared owner is the module
    # that constructs the node config and enforces this schema's own `execution_mode`
    # const ("prepared-model-group") in native code at runtime/studio_models.py:931
    # and :964, then routes it to the semantic parser it names below. The parser,
    # runtime/workflow_group_config.py, is recorded as a related enforcement
    # component rather than a second owner: it performs the deeper validation without
    # referencing the schema either.
    'workflow-model-group-node-config.schema.json': (
        'runtime/studio_models.py',
        ['runtime/studio_models.py'],
        'functional_owner_related_semantic_enforcement',
        ['tests/test_workflow_group_config.py'],
    ),
    'work-disposition.schema.json': ('runtime/work_disposition.py', ['runtime/work_disposition.py', 'runtime/model_convergence.py'], 'explicit_terminal_work_denominator_boundary', ['tests/test_group_convergence_boundary.py']),
    'remote_model_attachment.schema.json': ('runtime/remote_model_attachment.py', ['runtime/remote_model_attachment.py', 'runtime/model_attachment.py'], 'typed_remote_service_identity_boundary', ['tests/test_model_attachment.py', 'tests/test_model_group_preparation.py', 'tests/test_remote_attachment_identity.py']),
    'model-execution-group.schema.json': ('runtime/model_execution_group.py', ['runtime/model_execution_group.py', 'runtime/task_execution_plan.py'], 'bounded_group_declaration_boundary', ['tests/test_model_execution_group.py', 'tests/test_model_group_preparation.py']),
    'generation-bound-verdict.schema.json': ('runtime/generation_bound_verdict.py', ['runtime/generation_bound_verdict.py'], 'exact_candidate_dependency_verdict_boundary', ['tests/test_generation_bound_verdict.py']),
    'model-group-preparation.schema.json': ('runtime/model_group_preparation.py', ['runtime/model_group_preparation.py', 'runtime/task_execution_plan.py'], 'exact_member_preparation_boundary', ['tests/test_model_group_preparation.py']),
    'member-execution-input.schema.json': ('runtime/model_group_preparation.py', ['runtime/model_group_preparation.py', 'runtime/agent_runtime.py'], 'exact_member_input_boundary', ['tests/test_model_group_preparation.py']),
    'model-branch-artifact.schema.json': ('runtime/model_branch_artifacts.py', ['runtime/model_branch_artifacts.py', 'runtime/agent_runtime.py'], 'committed_member_evidence_boundary', ['tests/test_model_group_preparation.py']),
    'cancellation-scope.schema.json': ('runtime/cancellation_scope.py', ['runtime/cancellation_scope.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_agent_governed_integration.py']),
    # Producers/consumers verified by call chain, not by history:
    #   context_generation.py defines ContextGenerationVector and validates records.
    #   dependency_invalidation.py:context_vector_for_dependencies(...) constructs it.
    #   librarian_semantic_map.py imports ContextGenerationVector (:26) and builds one
    #     in _map_context (:419-420), serving it as generation_vector() (:339-340) and
    #     evaluating currentness on it (:342-344). It also hashes every contract file
    #     as generic metadata input, but that is inventory, not semantic use, so it is
    #     listed as a producer/consumer because of the typed construction above.
    #   projection_gate.py is listed: evaluate_projection(projection_id, recorded:
    #     ContextGenerationVector, current: ContextGenerationVector) (:46-51) rejects
    #     anything that is not an observed typed vector and compares project/scope
    #     (:53), deriving recorded_vector_sha256/current_vector_sha256 for the status.
    #     It consumes the generation surface semantically; it is not a producer.
    'context-generation-vector.schema.json': (
        'runtime/context_generation.py',
        ['runtime/context_generation.py', 'runtime/dependency_invalidation.py',
         'runtime/librarian_semantic_map.py'],
        'typed_scoped_archivist_metadata_boundary',
        ['tests/test_contract_runtime.py', 'tests/test_context_generation.py',
         'tests/test_contract_ownership_registry.py'],
    ),
    'dependency-identity.schema.json': ('runtime/dependency_identity.py', ['runtime/dependency_identity.py', 'runtime/dependency_invalidation.py'], 'canonical_dependency_observation_boundary', ['tests/test_contract_runtime.py', 'tests/test_dependency_invalidation.py', 'tests/test_dependency_contracts.py']),
    'execution-context.schema.json': ('runtime/execution_context.py', ['runtime/execution_context.py', 'runtime/vscode_model_bridge.py'], 'execution_identity_and_currentness_boundary', ['tests/test_contract_runtime.py', 'tests/test_execution_context.py', 'tests/test_agent_governed_integration.py']),
    # Declared by the merged tree but absent from this table originally, so `build()`
    # refused to guess. Each owner was found from the contract's own
    # `schema_version` const or filename stem in runtime/, not assumed:
    #   px.governed-exception/1.0       -> runtime/governed_exception.py
    #   px.model-router-preset*/1.0     -> runtime/model_router_preset.py
    #
    # VERSIONED COMPATIBILITY CONTRACT, verified rather than assumed.
    #
    # context-generation-vector.schema.json is the canonical 1.0 contract;
    # execution-generation-vector.schema.json is the 2.0 compatibility contract for the
    # SAME runtime semantic surface. It is not an independent implementation and it is
    # not retired. Evidence:
    #   * 2.0 differs from 1.0 only by widening the vector: 14 components versus 9,
    #     adding model_execution_group_revision, model_contract_set_revision,
    #     gremlin_revision, network_policy_revision and workflow_adapter_revision.
    #   * runtime/context_generation.py implements both versions on one code path:
    #     :11-21 declares SCHEMA_VERSION 1.0 plus EXECUTION_LINEAGE_COMPONENTS, :60
    #     emits the 2.0 const when lineage components are present, :85 selects the
    #     component set, and :94-96 accepts either const when reading.
    #   * Each document validates only against its own contract; a 1.0 vector is
    #     rejected by the 2.0 schema and vice versa.
    #   * 32 contexts declare px.context-generation-vector/2.0, so backward
    #     compatibility is required.
    # One owner and one producer: the shared runtime. No second runtime path exists.
    'execution-generation-vector.schema.json': (
        'runtime/context_generation.py',
        ['runtime/context_generation.py'],
        'versioned_compatibility_contract_shared_runtime_surface',
        ['tests/test_contract_runtime.py', 'tests/test_context_generation.py',
         'tests/test_contract_ownership_registry.py'],
    ),
    'governed-exception.schema.json': ('runtime/governed_exception.py', ['runtime/governed_exception.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_model_pool.py']),
    'model-router-preset-format.schema.json': ('runtime/model_router_preset.py', ['runtime/model_router_preset.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_refines_mesh_integration.py']),
    'model-router-preset.schema.json': ('runtime/model_router_preset.py', ['runtime/model_router_preset.py', 'runtime/local_model_runtime.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_refines_mesh_integration.py']),
    'gremlin-containment-proof.schema.json': ('runtime/gremlin/containment.py', ['runtime/gremlin/containment.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_gremlin_containment.py']),
    'gremlin-host-configuration.schema.json': ('runtime/gremlin/host_configuration.py', ['runtime/gremlin/host_configuration.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_gremlin_host_configuration.py']),
    'gremlin-recovery-authority.schema.json': ('runtime/gremlin/recovery_authority.py', ['runtime/gremlin/recovery_authority.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_gremlin_recovery_authority.py']),
    'gremlin-recovery-replay-ledger.schema.json': ('runtime/gremlin/recovery_authority.py', ['runtime/gremlin/recovery_authority.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_gremlin_recovery_authority.py']),
    'gremlin-runtime-identity.schema.json': ('runtime/gremlin/runtime_identity.py', ['runtime/gremlin/runtime_identity.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_gremlin_runtime_identity.py']),
    'isolated-agent-sandbox.schema.json': ('runtime/isolated_sandbox.py', ['runtime/isolated_sandbox.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_isolated_agent_sandbox.py']),
    # projection-status is owned by projection_gate.py (evaluate_projection derives it)
    # and produced jointly: librarian_semantic_map.py builds the status document through
    # projection_status() using the gate's evaluation (:343-344). projection_gate.py is
    # also a verified CONSUMER of both generation-vector versions (see CONSUMERS).
    'projection-status.schema.json': (
        'runtime/projection_gate.py',
        ['runtime/projection_gate.py', 'runtime/librarian_semantic_map.py'],
        'typed_scoped_archivist_metadata_boundary',
        ['tests/test_contract_runtime.py', 'tests/test_projection_gate.py',
         'tests/test_contract_ownership_registry.py'],
    ),
    'workflow-resume-decision.schema.json': ('runtime/workflow_resume.py', ['runtime/workflow_resume.py'], 'runtime_enforced', ['tests/test_contract_runtime.py', 'tests/test_workflow_resume.py']),
    "agent_handoff_packet.schema.json": (
        "runtime/agent_handoff.py",
        ["runtime/agent_handoff.py", "runtime/agent_runtime.py"],
        "agent_runtime_boundary",
        ["tests/test_agent_handoff.py", "tests/test_agent_governed_integration.py"],
    ),
    "capability_semantic_profile.schema.json": (
        "runtime/capability_semantics.py",
        ["runtime/capability_semantics.py", "runtime/semantic_index.py"],
        "runtime_enforced",
        ["tests/test_capability_semantics.py"],
    ),
    "foundry_candidate_skill.schema.json": (
        "runtime/foundry_studio_bridge.py",
        ["runtime/foundry_studio_bridge.py", "runtime/knowledge_foundry.py"],
        "runtime_enforced",
        ["tests/test_foundry_studio_bridge.py"],
    ),
    "memory_query_plan.schema.json": (
        "runtime/memory_broker.py",
        ["runtime/memory_broker.py", "runtime/agent_runtime.py"],
        "memory_lifecycle_runtime_boundary",
        ["tests/test_memory_broker.py", "tests/test_agent_governed_integration.py"],
    ),
    "model_attachment.schema.json": (
        "runtime/model_attachment.py",
        ["runtime/model_attachment.py", "runtime/execution_placement.py"],
        "runtime_enforced",
        ["tests/test_model_attachment.py", "tests/test_execution_placement.py"],
    ),
    "provider_execution_policy.schema.json": (
        "runtime/provider_gateway.py",
        ["runtime/provider_gateway.py", "extension/src/providerExecutionPolicy.js"],
        "runtime_enforced",
        ["tests/test_provider_gateway.py", "extension/tests/provider-execution-policy.test.js"],
    ),
    "task_execution_plan.schema.json": (
        "runtime/task_execution_plan.py",
        ["runtime/task_execution_plan.py", "runtime/capability_routing.py"],
        "runtime_enforced",
        ["tests/test_task_execution_plan.py"],
    ),
    "local-model-runtime.schema.json": (
        "runtime/local_model_runtime.py",
        ["runtime/local_model_runtime.py"],
        "local_model_lifecycle_runtime_boundary",
        ["tests/test_local_model_runtime.py"],
    ),
    "assurance-probe.schema.json": (
        "runtime/behavioral_assurance.py",
        ["runtime/behavioral_assurance.py"],
        "runtime_enforced",
        ["tests/test_behavioral_assurance.py"],
    ),
    "benchmark-custody.schema.json": (
        "runtime/benchmark_operations.py",
        ["runtime/benchmark_operations.py"],
        "runtime_enforced",
        ["tests/test_benchmark_operations.py"],
    ),
    "benchmark-execution-profile.schema.json": (
        "runtime/benchmark_operations.py",
        ["runtime/benchmark_operations.py"],
        "runtime_enforced",
        ["tests/test_benchmark_operations.py"],
    ),
    "benchmark-failure.schema.json": (
        "runtime/benchmark_operations.py",
        ["runtime/benchmark_operations.py"],
        "runtime_enforced",
        ["tests/test_benchmark_operations.py"],
    ),
    "coverage-frontier-event.schema.json": (
        "runtime/behavioral_assurance.py",
        ["runtime/behavioral_assurance.py"],
        "runtime_enforced",
        ["tests/test_behavioral_assurance.py"],
    ),
    "evaluation-lineage.schema.json": (
        "runtime/behavioral_assurance.py",
        ["runtime/behavioral_assurance.py"],
        "runtime_enforced",
        ["tests/test_behavioral_assurance.py"],
    ),
    "failure-attribution.schema.json": (
        "runtime/behavioral_assurance.py",
        ["runtime/behavioral_assurance.py"],
        "runtime_enforced",
        ["tests/test_behavioral_assurance.py"],
    ),
    "hardware-equivalence.schema.json": (
        "runtime/hardware_routing.py",
        ["runtime/hardware_routing.py"],
        "runtime_enforced",
        ["tests/test_hardware_routing.py"],
    ),
    "improvement-candidate.schema.json": (
        "runtime/behavioral_assurance.py",
        ["runtime/behavioral_assurance.py"],
        "runtime_enforced",
        ["tests/test_behavioral_assurance.py"],
    ),
    "retry-budget.schema.json": (
        "runtime/benchmark_operations.py",
        ["runtime/benchmark_operations.py"],
        "runtime_enforced",
        ["tests/test_benchmark_operations.py"],
    ),
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
        ".px/skills/govern-operating-kernel/scripts/authoritative_skill_compiler.py",
        [
            ".px/skills/govern-operating-kernel/scripts/authoritative_skill_compiler.py"
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
            ".px/skills/audit-source-capabilities/scripts/audit_source_capabilities.py"
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
    "semantic-memory-envelope.schema.json": [
        "runtime/semantic_memory.py",
        "runtime/memory_fabric.py",
        "runtime/memory_intelligence.py",
        "runtime/project_stream_orchestrator.py",
    ],
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

# Every rule below is declared here rather than inherited from the previously published
# registry: a build must be derivable from source alone and must fail closed on a
# contract that has no explicit rule (see tests/test_contract_ownership_registry_source.py).
DECLARED_SUITE_OWNERS = {
    "ai-bom.schema.json",
    "approval.schema.json",
    "assumption.schema.json",
    "claim.schema.json",
    "compatibility-record.schema.json",
    "decision-record.schema.json",
    "evaluation-case.schema.json",
    "evaluation-result.schema.json",
    "failure.schema.json",
    "incident.schema.json",
    "memory-record.schema.json",
    "recovery-plan.schema.json",
    "task-state.schema.json",
    "trace-link.schema.json",
}

COGNITIVE_DIR_OWNERS = {
    "brain-capability.schema.json": (
        "runtime/cognitive_core/index_builder.py",
        "cognitive_runtime_boundary",
    ),
    "cognitive-index.schema.json": (
        "runtime/cognitive_core/index_builder.py",
        "cognitive_runtime_boundary",
    ),
    "formula-definition.schema.json": (
        "runtime/cognitive_core/formula_engine.py",
        "cognitive_runtime_boundary",
    ),
    "reasoning-request.schema.json": (
        "runtime/cognitive_core/facade.py",
        "cognitive_runtime_boundary",
    ),
}

COGNITIVE_DIR_PRODUCERS = {
    "brain-capability.schema.json": ["registry/brain_capabilities.json"],
    "cognitive-index.schema.json": ["scripts/build_cognitive_index.py"],
    "formula-definition.schema.json": ["registry/brain_formulas.json"],
    "reasoning-request.schema.json": ["runtime/cli.py"],
}

OPERATIONS_DIR_OWNERS = {
    # Both boundaries are implemented, so both are named rather than picking one.
    # Traced in runtime/remote_provider_profiles.py:load_profiles:
    #   :49-50 StudioAuthorityStore.verify_receipt authenticates the HMAC receipt
    #          (runtime/studio_authority.py:284 verify) and rejects a record signed for
    #          another project or with a bad mac;
    #   :51-57 approved state, approver and non-expired configuration required;
    #   :58-61 validate_instance(config, contracts/operations/remote-provider-profile.schema.json)
    #          validates the document against this very contract.
    # Configuration therefore never admits a provider (module docstring) but it is
    # only useable after receipt authentication AND contract validation.
    "remote-provider-profile.schema.json": (
        "runtime/remote_provider_profiles.py",
        "signed_remote_profile_runtime_boundary",
    ),
    "health-model-registry.schema.json": ("runtime/health_model.py", "runtime_control_equivalent"),
    "health-report.schema.json": ("runtime/health_model.py", "runtime_control_equivalent"),
    "operation-event.schema.json": (
        "runtime/operational_visibility.py",
        "runtime_control_equivalent",
    ),
    "os-observer-registry.schema.json": (
        "runtime/operational_observers.py",
        "runtime_control_equivalent",
    ),
    "provider-adapter-registry.schema.json": (
        "runtime/provider_gateway.py",
        "runtime_control_equivalent",
    ),
    "provider-budget-policy.schema.json": (
        "runtime/provider_budget.py",
        "runtime_control_equivalent",
    ),
    "route-observer-registry.schema.json": (
        "runtime/operational_visibility.py",
        "runtime_control_equivalent",
    ),
    "local-model-runtime.schema.json": (
        "runtime/local_model_runtime.py",
        "local_model_lifecycle_runtime_boundary",
    ),
}

OPERATIONS_DIR_PRODUCERS = {
    # Only studio_authority produces the record: it signs it at creation. The profile
    # module reads runtime-core/remote-models/profiles.json (verified: CONFIG is used
    # solely at :45) and is the owner/consumer, never a producer.
    "remote-provider-profile.schema.json": ["runtime/studio_authority.py"],
    "health-model-registry.schema.json": ["registry/health_taxonomy.json"],
    "health-report.schema.json": ["runtime/health_model.py"],
    "operation-event.schema.json": ["runtime/operational_visibility.py"],
    "os-observer-registry.schema.json": ["registry/os_observer_registry.json"],
    "provider-adapter-registry.schema.json": ["registry/provider_adapters.json"],
    "provider-budget-policy.schema.json": ["registry/provider_budget_policy.json"],
    "route-observer-registry.schema.json": ["registry/operation_route_registry.json"],
    "local-model-runtime.schema.json": ["runtime/local_model_runtime.py"],
}

OPERATIONS_DIR_TESTS = {
    "remote-provider-profile.schema.json": "tests/test_remote_profile_catalog.py",
    "health-model-registry.schema.json": "tests/test_health_model.py",
    "health-report.schema.json": "tests/test_health_model.py",
    "operation-event.schema.json": "tests/test_operational_visibility.py",
    "os-observer-registry.schema.json": "tests/test_operational_observers.py",
    "provider-adapter-registry.schema.json": "tests/test_provider_gateway.py",
    "provider-budget-policy.schema.json": "tests/test_provider_budget.py",
    "route-observer-registry.schema.json": "tests/test_operational_visibility.py",
    "local-model-runtime.schema.json": "tests/test_local_model_runtime.py",
}

SEMANTIC_DIR_OWNERS = {
    # Canonical identity is owned by the registry that derives it: identity is a
    # function of the identity basis, never of a filesystem location, so the
    # owner is the module that performs that derivation and its durable snapshot.
    "semantic-entity.schema.json": (
        "runtime/semantic_entity.py",
        ["runtime/semantic_entity.py", "runtime/librarian_semantic_map.py"],
        "runtime_enforced",
        ["tests/test_semantic_entity_contract.py", "tests/test_librarian_semantic_map.py"],
    ),
    # The remaining semantic surfaces were declared by the merged tree. Each
    # owner below was located from the contract's own `schema_version` const in
    # runtime/, so the rule is derived from source rather than assumed:
    #   px.compact-address/1.0        -> runtime/compact_address.py
    #   px.semantic-locator/2.0       -> runtime/semantic_locator.py
    #   px.semantic-relation/1.0      -> runtime/semantic_locator.py
    #   px.source-census-binding/1.0  -> runtime/semantic_surfaces.py
    "compact-address-record.schema.json": (
        "runtime/compact_address.py",
        ["runtime/compact_address.py", "runtime/librarian_semantic_map.py"],
        "runtime_enforced",
        ["tests/test_contract_runtime.py", "tests/test_librarian_semantic_map.py"],
    ),
    "locator-record.schema.json": (
        "runtime/semantic_locator.py",
        ["runtime/semantic_locator.py", "runtime/librarian_semantic_map.py"],
        "runtime_enforced",
        ["tests/test_contract_runtime.py", "tests/test_librarian_semantic_map.py"],
    ),
    "relation-record.schema.json": (
        "runtime/semantic_locator.py",
        ["runtime/semantic_locator.py", "runtime/librarian_semantic_map.py"],
        "runtime_enforced",
        ["tests/test_contract_runtime.py", "tests/test_librarian_semantic_map.py"],
    ),
    "source-census-binding.schema.json": (
        "runtime/semantic_surfaces.py",
        ["runtime/semantic_surfaces.py", "runtime/semantic_taxonomy_census.py",
         "runtime/semantic_prefreeze_census.py"],
        "runtime_enforced",
        ["tests/test_contract_runtime.py", "tests/test_semantic_surfaces.py"],
    ),
}

# Explicit consumer lists. runtime/contracts.py (the validator) is added for every
# record automatically; these name the modules that actually read the surface's
# semantic content. Verified by call chain, never copied from history.
CONSUMERS = {
    "semantic-entity.schema.json": ["runtime/contracts.py", "runtime/librarian_semantic_map.py"],
    "compact-address-record.schema.json": ["runtime/contracts.py", "runtime/librarian_semantic_map.py"],
    "locator-record.schema.json": ["runtime/contracts.py", "runtime/librarian_semantic_map.py"],
    "relation-record.schema.json": ["runtime/contracts.py", "runtime/librarian_semantic_map.py"],
    "source-census-binding.schema.json": [
        "runtime/contracts.py", "runtime/semantic_taxonomy_census.py",
        "runtime/semantic_prefreeze_census.py",
    ],
    # load_profiles authenticates the signed receipt, then validates the document
    # against this exact schema at runtime/remote_provider_profiles.py:58-61.
    # None of these re-implements validation: group_provider_adapters.py:38,44 and
    # remote_model_bridge.py:9,14,51 all obtain profiles through load_profiles, so they
    # consume the surface only via the enforced signed-receipt + contract-validation path.
    "remote-provider-profile.schema.json": [
        "runtime/remote_provider_profiles.py", "runtime/group_provider_adapters.py",
        "runtime/remote_model_bridge.py",
    ],
    # librarian_semantic_map builds a ContextGenerationVector through
    # dependency_invalidation.context_vector_for_dependencies and evaluates
    # currentness on it; that is semantic consumption, not generic hashing.
    "context-generation-vector.schema.json": [
        "runtime/context_generation.py", "runtime/dependency_invalidation.py",
        "runtime/projection_gate.py",
    ],
    # projection_gate.py evaluates currentness FROM two typed ContextGenerationVector
    # instances and derives recorded_vector_sha256/current_vector_sha256; librarian
    # imports evaluate_projection and consumes the returned ProjectionStatus in
    # projection_status()/assert_current() (:343-349).
    "projection-status.schema.json": [
        "runtime/projection_gate.py", "runtime/librarian_semantic_map.py",
    ],
    # The 2.0 compatibility contract shares the entire 1.0 semantic surface, so its
    # consumers are the same verified modules, not a new set.
    "execution-generation-vector.schema.json": [
        "runtime/context_generation.py", "runtime/dependency_invalidation.py",
        "runtime/projection_gate.py",
    ],
}


CONTROL_OWNERS = {
    "certification-readiness.schema.json": (
        "runtime/certification_readiness.py",
        ["runtime/certification_readiness.py", "scripts/bootstrap_certification.py"],
        "runtime_control_equivalent",
        ["tests/test_certification_readiness.py"],
    ),
    "execution-package.schema.json": (
        "runtime/capability_routing.py",
        ["runtime/capability_routing.py"],
        "runtime_enforced",
        ["tests/test_capability_routing.py"],
    ),
    "task-envelope.schema.json": (
        "runtime/capability_routing.py",
        ["runtime/capability_routing.py"],
        "runtime_enforced",
        ["tests/test_capability_routing.py"],
    ),
}


def build(root: Path) -> dict[str, object]:
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
        elif path.parent.name == "learning":
            if name == "shared-contribution.schema.json":
                owner, enforcement = ("runtime/shared_contributions.py", "shared_learning_lineage_runtime_boundary")
                producers = ["runtime/shared_contributions.py", "runtime/learning_promotion.py", "runtime/process_memory.py"]
                tests = ["tests/test_shared_contributions.py"]
            elif name == "verification-record.schema.json":
                owner, enforcement = ("runtime/shared_contributions.py", "shared_learning_verification_runtime_boundary")
                producers = ["runtime/shared_contributions.py", "runtime/learning_promotion.py"]
                tests = ["tests/test_shared_contributions.py"]
            elif name == "observation-pack.schema.json":
                owner, enforcement = ("runtime/observation_projection.py", "evidence_projection_runtime_boundary")
                producers = ["runtime/observation_projection.py", "runtime/evidence_reducer.py", "runtime/memory_intelligence.py"]
                tests = ["tests/test_observation_projection.py", "tests/test_evidence_reducer.py"]
            else:
                raise ValueError(f"learning contract has no ownership rule: {relative}")
        elif path.parent.name == "nsai":
            owner, enforcement = (
                "runtime/nsai_knowledge.py",
                "nsai_single_object_knowledge_boundary",
            )
            producers = [
                "runtime/nsai_knowledge.py",
                "runtime/knowledge_foundry.py",
                "runtime/knowledge_refinery.py",
                "runtime/cognitive_core/index_builder.py",
            ]
            tests = [
                "tests/test_nsai_knowledge.py",
                "tests/test_nsai_knowledge_foundry_materialization.py",
            ]
        elif path.parent.name == "persistent_memory":
            owner, enforcement = (
                "runtime/persistent_memory_provider.py",
                "external_persistent_memory_read_boundary",
            )
            producers = [
                "runtime/persistent_memory_provider.py",
                "runtime/external_capability_provider.py",
            ]
            tests = [
                "tests/test_persistent_memory_provider.py",
                "tests/test_persistent_memory_workflow.py",
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
        elif path.parent.name == "semantic":
            if name not in SEMANTIC_DIR_OWNERS:
                raise ValueError(
                    f"no source-authentic owner rule for semantic contract {name}; "
                    "declare it in SEMANTIC_DIR_OWNERS rather than publishing a guess"
                )
            owner, producers, enforcement, tests = SEMANTIC_DIR_OWNERS[name]
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
        elif path.parent.name == "project_revision_succession":
            owner, enforcement = (
                "runtime/project_revision_succession.py",
                "revision_succession_runtime_boundary",
            )
            producers = [owner, "runtime/revision_campaign_lifecycle.py"]
            tests = ["tests/test_project_revision_succession.py"]
        elif name in DECLARED_SUITE_OWNERS:
            owner, enforcement = (
                "runtime/declared_suite.py",
                "declared_suite_runtime_boundary",
            )
            producers = ["builders/declared_suite_support_builder.py"]
            tests = ["tests/test_declared_suite_support.py"]
        elif name in ROOT_OWNERS:
            owner, producers, enforcement, tests = ROOT_OWNERS[name]
        elif name in CONTROL_OWNERS:
            owner, producers, enforcement, tests = CONTROL_OWNERS[name]
        elif path.parent.name == "cognitive":
            owner, enforcement = COGNITIVE_DIR_OWNERS[name]
            producers = COGNITIVE_DIR_PRODUCERS[name]
            tests = ["tests/test_cognitive_core.py"]
        elif path.parent.name == "metacognitive":
            owner, enforcement = (
                "runtime/metacognitive_evolution/facade.py",
                "metacognitive_runtime_boundary",
            )
            producers = ["builders/last_round_assimilation_builder.py"]
            tests = ["tests/test_metacognitive_evolution.py"]
        elif path.parent.name == "scheduling":
            owner, enforcement = (
                "runtime/capability_scheduler.py",
                "scheduling_runtime_boundary",
            )
            producers = ["builders/last_round_assimilation_builder.py"]
            tests = ["tests/test_capability_scheduler.py"]
        elif path.parent.name == "operations":
            owner, enforcement = OPERATIONS_DIR_OWNERS[name]
            producers = OPERATIONS_DIR_PRODUCERS[name]
            tests = [OPERATIONS_DIR_TESTS[name]]
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
                "consumers": (
                    ["runtime/contracts.py", "runtime/project_revision_succession.py",
                     "runtime/revision_campaign_lifecycle.py", "runtime/test_profiles.py"]
                    if path.parent.name == "project_revision_succession"
                    else CONSUMERS.get(name, ["runtime/contracts.py"])
                ),
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
        "records": sorted(records, key=lambda record: record["path"]),
    }


def dump_result(result: dict[str, object]) -> str:
    '''Canonical serialisation of a build result (sorted records, stable formatting).'''
    ordered = dict(result)
    ordered["records"] = sorted(
        result["records"], key=lambda record: record["path"]  # type: ignore[index]
    )
    return json.dumps(ordered, indent=2) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Publish the ownership image only through the admitted projection boundary.

    Like every other guarded registry builder, a missing admission fails closed at
    argument parsing. Publication itself re-validates the admission, takes native
    custody of its lease, effect intent and temporary workspace, and read back
    verifies the exact image before settlement.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission-event-id", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    result = build(root)
    publish_guarded_registry_projection(
        root,
        "registry/contract_ownership.json",
        result,
        admission_event_id=args.admission_event_id,
    )
    print(json.dumps({"contract_count": result["contract_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
