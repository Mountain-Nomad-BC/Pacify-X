'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  evaluateBootstrapActivation,
  dedupeIssues,
  evaluateLauncherTerminal,
  evaluateOperationalWalk,
  exitCodeForTerminalState,
  normalizeProcessOutput,
  validRecoveredAuthorityBoundary
} = require('../scripts/operational-walk-status');

function readyBootstrap() {
  return {
    status: 'ready',
    extension_found: true,
    activation_completed: true,
    command_registered: true,
    command_executed: true
  };
}

function completeReceipt() {
  const surfaceIds = [
    'dashboard-control-plane',
    'agent-studio',
    'workflow-studio',
    'skill-studio',
    'studio-lifecycle',
    'sidebar'
  ];
  const controls = surfaceIds.map((surfaceId, index) => ({
    control_id: `control-${index}`,
    surface_id: surfaceId,
    attempted: true,
    terminal_disposition: 'completed'
  }));
  return {
    endpoint: 'http://127.0.0.1:9333',
    host_source_mismatch: false,
    source_identity: { state: 'verified', method: 'test-runtime-identity-contract' },
    host_errors: [],
    results: [],
    builders: {
      agent: { terminal_disposition: 'completed' },
      workflow: { terminal_disposition: 'completed' }
    },
    modal_surfaces: [
      { surface_id: 'skill-studio', terminal_disposition: 'completed' },
      { surface_id: 'studio-lifecycle', terminal_disposition: 'completed' }
    ],
    sidebar: { buttons: [], provider_missing_message: false, invalid_union_message: false },
    control_chains: {
      inventory: { control_count: controls.length },
      aggregates: { control_count: controls.length, complete_interaction_chains: controls.length },
      controls
    }
  };
}

test('reports completed only when every builder, surface, control, and chain is complete', () => {
  const status = evaluateOperationalWalk(completeReceipt());
  assert.equal(status.terminal_state, 'completed', JSON.stringify(status.issues));
  assert.equal(status.operationally_complete, true);
  assert.equal(status.summary.blocking_issue_count, 0);
  assert.deepEqual(status.coverage.missing_surface_ids, []);
});

test('focused Studio completion is judged by its physical lifecycle receipts, not unrelated full-walk coverage', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'studio-lifecycle';
  receipt.builders.agent = { terminal_disposition: 'focused_profile_not_run' };
  receipt.builders.workflow = { terminal_disposition: 'focused_profile_not_run' };
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  receipt.studio_setup_profile = { observation: { typed_ready_result: true, errors: [] } };
  receipt.studio_candidate_save_profile = { observations: ['agent', 'workflow', 'skill'].map(kind => ({ kind, attempted: true, typed_creation_receipt: true, reopened_catalog_match: true, errors: [] })) };
  receipt.studio_lifecycle_profile = { observations: ['agent', 'workflow', 'skill'].map(kind => ({ kind, exact_catalog_selection: true, operations: [{ operation: 'inspect', valid: true }], durable_run_reopened: kind === 'skill' ? false : true, errors: [] })) };
  receipt.studio_revision_edit_profile = { observations: ['agent', 'workflow', 'skill'].map(kind => ({ kind, attempted: true, editor_bound: true, typed_creation_receipt: true, reopened_catalog_match: true, predecessor_preserved: true, content_changed: true, reopened_editor_content_match: true, errors: [] })) };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed');
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  assert.equal(status.evaluated_scope, 'studio-lifecycle');
  assert.equal(status.summary.blocking_issue_count, 0);
});

test('focused Studio completion fails closed when one physical revision cannot be reopened', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'studio-lifecycle';
  receipt.studio_setup_profile = { observation: { typed_ready_result: true, errors: [] } };
  receipt.studio_candidate_save_profile = { observations: ['agent', 'workflow', 'skill'].map(kind => ({ kind, attempted: true, typed_creation_receipt: true, reopened_catalog_match: true, errors: [] })) };
  receipt.studio_lifecycle_profile = { observations: ['agent', 'workflow', 'skill'].map(kind => ({ kind, exact_catalog_selection: true, operations: [{ valid: true }], durable_run_reopened: !['agent', 'workflow'].includes(kind) || true, errors: [] })) };
  receipt.studio_revision_edit_profile = { observations: ['agent', 'workflow', 'skill'].map(kind => ({ kind, attempted: true, editor_bound: true, typed_creation_receipt: true, reopened_catalog_match: kind !== 'workflow', predecessor_preserved: true, content_changed: true, reopened_editor_content_match: true, errors: [] })) };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'incomplete');
  assert.ok(status.issues.some(item => item.code === 'focused-studio-revision-edit-incomplete'));
});

test('focused catalog pagination requires exact bidirectional paging and restored state', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'catalog-pagination';
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  receipt.catalog_pagination_profile = {
    observations: [{ surface: 'agents', rendered: true, attempted: true, first_page_previous_disabled: true, forward: true, backward: true, restored: true, errors: [] }],
    control_probe: {
      eligible_control_count: 1,
      records: [{ control_id: 'pxui.agents.action.catalogNext', rendered: true, attempted: true, errors: [], interaction_chain: Object.fromEntries(stages.map(stage => [stage, { state: 'present' }])) }]
    }
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed');
  assert.equal(status.scope_complete, true);
  receipt.catalog_pagination_profile.observations[0].restored = false;
  const failed = evaluateOperationalWalk(receipt);
  assert.equal(failed.terminal_state, 'incomplete');
  assert.ok(failed.issues.some(item => item.code === 'focused-catalog-pagination-incomplete'));
});

test('focused coordination-memory completion requires the exact control denominator and restart reconstruction', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'coordination-memory';
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  receipt.coordination_memory_profile = {
    observation: { attempted: true, completed: true, webview_restarted: true, errors: [] },
    control_probe: {
      eligible_control_count: 1,
      records: [{ control_id: 'coordination-memory', rendered: true, attempted: true, errors: [], interaction_chain: Object.fromEntries(stages.map(stage => [stage, { state: 'present' }])) }]
    }
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed');
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  receipt.coordination_memory_profile.observation.webview_restarted = false;
  const failed = evaluateOperationalWalk(receipt);
  assert.equal(failed.terminal_state, 'incomplete');
  assert.ok(failed.issues.some(item => item.code === 'focused-coordination-memory-incomplete'));
});

test('focused host-boundary completion is judged only by its exact typed handoff records', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'host-boundary';
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  const completeChain = { open_load: { state: 'present' }, failure_handling: { state: 'not_applicable' } };
  receipt.host_boundary_profile = {
    observation: { operations: {}, errors: [] },
    control_probe: {
      eligible_control_count: 2,
      records: [
        { control_id: 'open-file', rendered: true, attempted: true, errors: [], interaction_chain: completeChain },
        { control_id: 'open-url', rendered: true, attempted: true, errors: [], interaction_chain: completeChain }
      ]
    }
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed');
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  assert.equal(status.evaluated_scope, 'host-boundary');
});

test('focused host-boundary completion fails closed on a missing rendered action', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'host-boundary';
  receipt.host_boundary_profile = {
    observation: { operations: {}, errors: ['openMemorySource-not-rendered'] },
    control_probe: {
      eligible_control_count: 1,
      records: [{ control_id: 'open-memory', rendered: false, attempted: false, errors: ['not-rendered'], interaction_chain: { open_load: { state: 'missing' } } }]
    }
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'incomplete');
  assert.ok(status.issues.some(item => item.code === 'focused-host-boundary-incomplete'));
});

test('focused Knowledge Graph completion requires exact project reconstruction and saved-view restoration', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'knowledge-graph';
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const completeProfile = (controlId, observation) => ({
    observation: { ...observation, errors: [] },
    control_probe: {
      eligible_control_count: 1,
      records: [{ control_id: controlId, rendered: true, attempted: true, errors: [], interaction_chain: Object.fromEntries(stages.map(stage => [stage, { state: 'present' }])) }]
    }
  });
  receipt.projects_profile = completeProfile('pxui.projects.action.buildRepositoryGraph', {
    completed: true, webview_restarted: true, exact_reconstruction: true
  });
  receipt.knowledge_graph_profile = completeProfile('pxui.knowledge-graph.action.graphDeleteSavedView.row', {
    completed: true,
    invalid_rejected: true,
    saved_view_created: true,
    saved_view_applied: true,
    saved_view_deleted: true,
    webview_restarted: true,
    exact_reconstruction: true,
    restored: true
  });
  const completed = evaluateOperationalWalk(receipt);
  assert.equal(completed.terminal_state, 'completed');
  assert.equal(completed.scope_complete, true);
  assert.equal(completed.operationally_complete, false);
  assert.equal(completed.evaluated_scope, 'knowledge-graph');

  receipt.knowledge_graph_profile.observation.saved_view_deleted = false;
  const failed = evaluateOperationalWalk(receipt);
  assert.equal(failed.terminal_state, 'incomplete');
  assert.ok(failed.issues.some(item => item.code === 'focused-knowledge-graph-incomplete'));
});

test('focused surface capture requires exact first-fold and deep-panel evidence for all installed surfaces', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'surface-capture';
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  const surfaces = ['dashboard', 'projects', 'agents', 'agent-studio', 'workflow-studio', 'skill-studio', 'knowledgeGraph', 'skillsTools', 'workflows', 'plugins', 'memory', 'activity', 'diagnostics', 'assurance', 'studio-lifecycle', 'settings', 'knowledgeCore', 'runtimeCore'];
  receipt.results = surfaces.map(surface => ({
    surface,
    navigation_active: true,
    captures: {
      surface_id: surface,
      first_fold: { screenshot: { status: 'captured' } },
      deep_panel: { screenshot: { status: 'captured' } }
    }
  }));
  const completed = evaluateOperationalWalk(receipt);
  assert.equal(completed.terminal_state, 'completed');
  assert.equal(completed.scope_complete, true);
  assert.equal(completed.operationally_complete, false);
  assert.equal(completed.evaluated_scope, 'surface-capture');

  receipt.results.find(result => result.surface === 'projects').captures.first_fold.screenshot.status = 'failed';
  const failed = evaluateOperationalWalk(receipt);
  assert.equal(failed.terminal_state, 'incomplete');
  const finding = failed.issues.find(item => item.code === 'focused-surface-capture-incomplete');
  assert.deepEqual(finding.details.incomplete_surfaces, ['projects']);
});

test('focused native-dialog completion requires its exact five-profile denominator', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'native-dialog-boundary';
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const completeProfile = name => ({
    observation: { completed: true, errors: [] },
    control_probe: {
      eligible_control_count: 1,
      records: [{
        control_id: name, rendered: true, attempted: true, errors: [],
        interaction_chain: Object.fromEntries(stages.map(stage => [stage, { state: stage === 'progress_reporting' ? 'not_applicable' : 'present' }]))
      }]
    }
  });
  receipt.enterprise_profile = completeProfile('enterprise');
  receipt.projects_profile = completeProfile('projects');
  receipt.knowledge_graph_profile = completeProfile('knowledge-graph');
  receipt.cleanup_recycle_profile = completeProfile('pxui.runtime-core.action.cleanupPermanent');
  receipt.cleanup_recycle_profile.control_probe.records[0].authority_skipped = true;
  Object.assign(receipt.cleanup_recycle_profile.observation, {
    webview_restarted: true, invalid_selection_rejected: true, select_all_round_trip: true,
    permanent_refused_without_authorization: true, permanent_completed: false, reclaimed_absent_after_restart: true
  });
  receipt.cleanup_recycle_profile.control_probe.records[0].interaction_chain.open_load = { state: 'missing' };
  receipt.plugin_mutation_profile = completeProfile('plugin-mutation');
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed');
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  assert.equal(status.evaluated_scope, 'native-dialog-boundary');
  receipt.cleanup_recycle_profile.control_probe.records[0].control_id = 'pxui.runtime-core.action.unknownPermanent';
  const substituted = evaluateOperationalWalk(receipt);
  assert.equal(substituted.terminal_state, 'incomplete');
  assert.ok(substituted.issues.some(item => item.code === 'focused-native-dialog-boundary-incomplete'));
});

test('focused native-dialog completion fails closed on missing recovery or profile errors', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'native-dialog-boundary';
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const completeProfile = name => ({ observation: { errors: [] }, control_probe: { eligible_control_count: 1, records: [{ control_id: name, rendered: true, attempted: true, errors: [], interaction_chain: Object.fromEntries(stages.map(stage => [stage, { state: 'present' }])) }] } });
  receipt.enterprise_profile = completeProfile('enterprise');
  receipt.projects_profile = completeProfile('projects');
  receipt.knowledge_graph_profile = completeProfile('knowledge-graph');
  receipt.cleanup_recycle_profile = completeProfile('pxui.runtime-core.action.cleanupPermanent');
  receipt.cleanup_recycle_profile.control_probe.records[0].authority_skipped = true;
  Object.assign(receipt.cleanup_recycle_profile.observation, {
    webview_restarted: true, invalid_selection_rejected: true, select_all_round_trip: true,
    permanent_refused_without_authorization: true, permanent_completed: false, reclaimed_absent_after_restart: true
  });
  receipt.plugin_mutation_profile = completeProfile('plugin-mutation');
  receipt.projects_profile.control_probe.records[0].interaction_chain.recovery_rollback = { state: 'missing' };
  receipt.knowledge_graph_profile.control_probe.records[0].interaction_chain.reload_reopen = { state: 'missing' };
  receipt.cleanup_recycle_profile.observation.errors.push('cleanup-restoration-mismatch');
  receipt.plugin_mutation_profile.observation.errors.push('typed-restoration-mismatch');
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'incomplete');
  const finding = status.issues.find(item => item.code === 'focused-native-dialog-boundary-incomplete');
  assert.ok(finding);
  assert.deepEqual(finding.details.incomplete_profiles.map(item => item.name), ['projects', 'knowledge-graph', 'cleanup', 'plugin-mutation']);
});

test('focused Plugin lifecycle requires exact rollback and absent-state reconstruction', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'plugin-lifecycle';
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  receipt.plugin_mutation_profile = {
    observation: {
      completed: true, exact_reconstruction: true, cleanup_restored: true,
      uninstall_rollback_reconciled: true, update_rollback_reconciled: true, errors: []
    },
    control_probe: {
      eligible_control_count: 1,
      records: [{ control_id: 'plugin-mutation', rendered: true, attempted: true, errors: [], interaction_chain: Object.fromEntries(stages.map(stage => [stage, { state: 'present' }])) }]
    }
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed', JSON.stringify(status.issues));
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  receipt.plugin_mutation_profile.observation.cleanup_restored = false;
  const failed = evaluateOperationalWalk(receipt);
  assert.equal(failed.terminal_state, 'incomplete');
  assert.ok(failed.issues.some(item => item.code === 'focused-plugin-lifecycle-incomplete'));
});

test('focused Codex handoff completion requires its exact three-control typed probe', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'codex-handoff';
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const chain = Object.fromEntries(stages.map(stage => [stage, { state: ['input_validation', 'persistence', 'reload_reopen'].includes(stage) ? 'not_applicable' : 'present' }]));
  receipt.codex_handoff_profile = {
    observation: { prepared: true, cleared: true, claim_released: true, webview_restarted: true, errors: [] },
    control_probe: {
      eligible_control_count: 3,
      records: ['command', 'continue', 'cancel'].map(control_id => ({ control_id, rendered: true, attempted: true, errors: [], interaction_chain: chain }))
    }
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed', JSON.stringify(status.issues));
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  assert.equal(status.evaluated_scope, 'codex-handoff');
});

test('focused late-card repair requires graph idle recovery and exact Studio trust release checks', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'late-card-repair';
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  receipt.observation_state_profile = {
    observations: {
      'pxui.knowledge-graph.action.graphLoadAll': { rendered: true, attempted: true, cancelled: true, recovered: true, completed: true }
    },
    control_probe: {
      eligible_control_count: 1,
      records: [{
        control_id: 'pxui.knowledge-graph.action.graphLoadAll', rendered: true, attempted: true, errors: [],
        interaction_chain: Object.fromEntries(stages.map(stage => [stage, { state: 'present' }]))
      }]
    }
  };
  receipt.studio_controller_adversarial_profile = {
    completed: true,
    errors: [],
    checks: Object.fromEntries([
      'stale_allocation_ignored',
      'cross_kind_allocation_ignored',
      'cancelled_allocation_cannot_reopen',
      'physical_skill_hash_substitution_rejected',
      'incoming_trust_released',
      'initial_conflict_rejected',
      'editor_preserved'
    ].map(name => [name, true]))
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed', JSON.stringify(status.issues));
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  assert.equal(status.evaluated_scope, 'late-card-repair');
});

test('focused late-card repair fails closed on missing graph recovery or stripped trust proof', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'late-card-repair';
  receipt.observation_state_profile = {
    observations: {
      'pxui.knowledge-graph.action.graphLoadAll': { rendered: true, attempted: true, cancelled: true, recovered: false, completed: false }
    },
    control_probe: { eligible_control_count: 1, records: [] }
  };
  receipt.studio_controller_adversarial_profile = {
    completed: false,
    errors: ['incoming_trust_released:failed'],
    checks: { incoming_trust_released: false }
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'incomplete');
  const finding = status.issues.find(item => item.code === 'focused-late-card-repair-incomplete');
  assert.ok(finding);
  assert.equal(finding.details.observation_complete, false);
  assert.equal(finding.details.controller_complete, false);
  assert.ok(finding.details.failed_controller_checks.includes('incoming_trust_released'));
});

test('focused builder completion requires exact durability and no-effect cleanup for both builders', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'builder';
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  receipt.builders = Object.fromEntries(['agent', 'workflow'].map(kind => [kind, {
    terminal_disposition: 'interaction_complete',
    durability: { verified: true },
    attempted_control_ids: [
      `pxui.${kind === 'agent' ? 'agent' : 'workflow'}-studio.action.studioApplyJson`,
      `pxui.${kind === 'agent' ? 'agent' : 'workflow'}-studio.action.resumeWorkingStudioDraft`
    ],
    cleanup: { modal_closed: true, candidate_saved: false, runtime_executed: false }
  }]));
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed', JSON.stringify(status.issues));
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  assert.equal(status.evaluated_scope, 'builder');
});

test('focused builder completion fails closed on missing recovery or any durable effect', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'builder';
  receipt.builders.agent = {
    terminal_disposition: 'interaction_complete', durability: { verified: false },
    attempted_control_ids: ['pxui.agent-studio.action.studioApplyJson'],
    cleanup: { modal_closed: true, candidate_saved: false, runtime_executed: false }
  };
  receipt.builders.workflow = {
    terminal_disposition: 'interaction_complete', durability: { verified: true },
    attempted_control_ids: ['pxui.workflow-studio.action.studioApplyJson', 'pxui.workflow-studio.action.resumeWorkingStudioDraft'],
    cleanup: { modal_closed: true, candidate_saved: true, runtime_executed: false }
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'incomplete');
  const finding = status.issues.find(item => item.code === 'focused-builder-incomplete');
  assert.ok(finding);
  assert.deepEqual(finding.details.incomplete_builders, ['agent', 'workflow']);
});

test('focused Codex handoff fails closed on denominator mismatch, missing stage, or profile error', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'codex-handoff';
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const chain = Object.fromEntries(stages.map(stage => [stage, { state: 'present' }]));
  receipt.codex_handoff_profile = {
    observation: { errors: ['retained-profile-error'] },
    control_probe: {
      eligible_control_count: 3,
      records: [
        { control_id: 'command', rendered: true, attempted: true, errors: [], interaction_chain: chain },
        { control_id: 'continue', rendered: true, attempted: true, errors: [], interaction_chain: { ...chain, recovery_rollback: { state: 'missing' } } }
      ]
    }
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'incomplete');
  const finding = status.issues.find(item => item.code === 'focused-codex-handoff-incomplete');
  assert.ok(finding);
  assert.equal(finding.details.eligible_control_count, 3);
  assert.equal(finding.details.record_count, 2);
  assert.deepEqual(finding.details.profile_errors, ['retained-profile-error']);
});

test('focused error-indicator completion requires exactly the Memory and Knowledge Core recovery chains', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'error-indicators';
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const chain = Object.fromEntries(stages.map(stage => [stage, { state: ['user_edit_action', 'persistence'].includes(stage) ? 'not_applicable' : 'present', evidence: [`focused-error-indicator:${stage}`] }]));
  receipt.installed_control_probe = {
    eligible_control_count: 2,
    records: [
      'pxui.memory.indicator.queryError',
      'pxui.knowledge-core.indicator.controllerError'
    ].map(control_id => ({ control_id, rendered: true, observed: true, attempted: false, errors: [], interaction_chain: chain }))
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed', JSON.stringify(status.issues));
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  assert.equal(status.evaluated_scope, 'error-indicators');
});

test('focused error-indicator completion fails closed on substitution, incomplete evidence, or retained errors', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'error-indicators';
  const chain = {
    open_load: { state: 'present', evidence: ['focused-error-indicator:open'] },
    recovery_rollback: { state: 'present', evidence: [] }
  };
  receipt.installed_control_probe = {
    eligible_control_count: 2,
    records: [
      { control_id: 'pxui.memory.indicator.queryError', rendered: true, observed: true, errors: [], interaction_chain: chain },
      { control_id: 'pxui.knowledge-core.indicator.substitutedError', rendered: true, observed: true, errors: ['retained-probe-error'], interaction_chain: chain }
    ]
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'incomplete');
  const finding = status.issues.find(item => item.code === 'focused-error-indicators-incomplete');
  assert.ok(finding);
  assert.deepEqual(finding.details.observed_control_ids, [
    'pxui.memory.indicator.queryError',
    'pxui.knowledge-core.indicator.substitutedError'
  ]);
});

test('focused error-indicator completion fails closed when an exact required stage is absent', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'error-indicators';
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const chain = Object.fromEntries(stages.map(stage => [stage, { state: 'present', evidence: [`focused-error-indicator:${stage}`] }]));
  delete chain.failure_handling;
  receipt.installed_control_probe = {
    eligible_control_count: 2,
    records: [
      'pxui.memory.indicator.queryError',
      'pxui.knowledge-core.indicator.controllerError'
    ].map(control_id => ({ control_id, rendered: true, observed: true, errors: [], interaction_chain: chain }))
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'incomplete');
  assert.ok(status.issues.some(item => item.code === 'focused-error-indicators-incomplete'));
});

test('focused workbench-command completion requires every exact command chain', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'workbench-command';
  receipt.control_chains.controls.forEach(control => { control.attempted = false; });
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const chain = Object.fromEntries(stages.map(stage => [stage, { state: ['user_edit_action', 'input_validation', 'persistence', 'reload_reopen'].includes(stage) ? 'not_applicable' : 'present' }]));
  const refusedChain = structuredClone(chain);
  for (const stage of ['authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement']) refusedChain[stage] = { state: 'missing' };
  receipt.installed_workbench_command_profile = {
    eligible_control_count: 2,
    records: [
      { control_id: 'safe-command', rendered: true, observed: true, attempted: true, authority_skipped: false, errors: [], interaction_chain: chain },
      { control_id: 'pxui.dashboard-control-plane.command.pacifyX.refreshEnvironment', rendered: true, observed: true, attempted: true, authority_skipped: true, errors: [], interaction_chain: refusedChain }
    ]
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed', JSON.stringify(status.issues));
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  assert.equal(status.evaluated_scope, 'workbench-command');
});

test('focused workbench-command completion fails closed on a missing rejection chain', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'workbench-command';
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const chain = Object.fromEntries(stages.map(stage => [stage, { state: 'present' }]));
  for (const stage of ['authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement']) chain[stage] = { state: 'missing' };
  chain.failure_handling = { state: 'missing' };
  receipt.installed_workbench_command_profile = {
    eligible_control_count: 1,
    records: [{ control_id: 'pxui.dashboard-control-plane.command.pacifyX.refreshEnvironment', rendered: true, observed: true, attempted: true, authority_skipped: true, errors: [], interaction_chain: chain }]
  };
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'incomplete');
  assert.ok(status.issues.some(item => item.code === 'focused-workbench-command-incomplete'));
});

test('skipped builders, modal surfaces, controls, and chains remain operationally incomplete', () => {
  const receipt = completeReceipt();
  receipt.builders.agent = { terminal_disposition: 'skipped_requires_exact_control_instrumentation' };
  receipt.modal_surfaces = [];
  receipt.control_chains.controls[0].attempted = false;
  receipt.control_chains.aggregates.complete_interaction_chains = 0;
  const status = evaluateOperationalWalk(receipt);
  const codes = new Set(status.issues.map(item => item.code));
  assert.equal(status.terminal_state, 'incomplete');
  assert.equal(status.operationally_complete, false);
  assert.ok(codes.has('agent-builder-incomplete'));
  assert.ok(codes.has('controls-unattempted'));
  assert.ok(codes.has('control-chains-incomplete'));
  assert.ok(codes.has('surfaces-not-observed'));
  assert.deepEqual(status.coverage.missing_surface_ids, ['agent-studio', 'skill-studio', 'studio-lifecycle']);
});

test('readiness accepts only the ten exact rendered and recovered authority boundaries without relabeling them complete', () => {
  const receipt = completeReceipt();
  const ids = [
    'pxui.dashboard-control-plane.command.pacifyX.continueWithCodex',
    'pxui.dashboard-control-plane.command.pacifyX.refreshEnvironment',
    'pxui.dashboard-control-plane.command.pacifyX.refreshOllama',
    'pxui.dashboard-control-plane.command.pacifyX.rotateStudioApprovalIdentity',
    'pxui.dashboard-control-plane.command.pacifyX.validateControlPlane',
    'pxui.dashboard-control-plane.command.validate',
    'pxui.diagnostics.action.dynamicRepair.refreshEnvironment',
    'pxui.diagnostics.action.validate',
    'pxui.runtime-core.action.validate',
    'pxui.runtime-core.action.cleanupPermanent'
  ];
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const boundaries = ids.map(control_id => ({
    control_id, surface_id: control_id.includes('runtime-core') ? 'runtime-core' : 'dashboard-control-plane', kind: control_id.includes('.action.') ? 'action' : 'command',
    rendered: true, visible: true, attempted: true, terminal_disposition: 'skipped_requires_authority', errors: [],
    authority: 'owned isolated host; exact effect withheld', reason: 'the exact effect exceeds this walk authority',
    expected_effect: `exercise ${control_id}`, return_condition: 'grant exact effect authority in the disposable host and rerun with rollback proof',
    stages: stages.map(stage => ({ stage, status: ['failure_handling', 'recovery_rollback'].includes(stage) ? 'observed' : 'not_observed' }))
  }));
  receipt.control_chains.controls.push(...boundaries);
  receipt.control_chains.inventory.control_count += boundaries.length;
  receipt.control_chains.aggregates.control_count += boundaries.length;
  receipt.results.push({ surface: 'runtimeCore', navigation_active: true, terminal_disposition: 'completed' });
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed', JSON.stringify(status.issues));
  assert.equal(status.operationally_complete, true);
  assert.equal(status.coverage.complete_interaction_chains, 6);
  assert.equal(status.coverage.recovered_authority_boundary_count, 10);
  assert.equal(status.coverage.accepted_coverage_count, 16);
  assert.deepEqual(status.coverage.recovered_authority_boundary_ids, [...ids].sort());
  assert.ok(boundaries.every(validRecoveredAuthorityBoundary));
  assert.ok(boundaries.every(control => control.terminal_disposition === 'skipped_requires_authority'));
});

test('readiness rejects unknown, unrendered, errored, unrecovered, and falsely complete authority skips', () => {
  const base = {
    control_id: 'pxui.runtime-core.action.cleanupPermanent', surface_id: 'runtime-core', kind: 'action',
    rendered: true, visible: true, attempted: true, terminal_disposition: 'skipped_requires_authority', errors: [],
    authority: 'owned isolated host; exact effect withheld', reason: 'the exact effect exceeds this walk authority',
    expected_effect: 'exercise the exact permanent cleanup effect', return_condition: 'grant exact destructive authority and rerun with rollback proof',
    stages: [
      { stage: 'open_load', status: 'not_observed' },
      { stage: 'failure_handling', status: 'observed' },
      { stage: 'recovery_rollback', status: 'observed' }
    ]
  };
  assert.equal(validRecoveredAuthorityBoundary(base), true);
  assert.equal(validRecoveredAuthorityBoundary({ ...base, control_id: 'pxui.unknown.action' }), false);
  assert.equal(validRecoveredAuthorityBoundary({ ...base, rendered: false }), false);
  assert.equal(validRecoveredAuthorityBoundary({ ...base, errors: ['fault'] }), false);
  assert.equal(validRecoveredAuthorityBoundary({ ...base, stages: base.stages.filter(stage => stage.stage !== 'recovery_rollback') }), false);
  assert.equal(validRecoveredAuthorityBoundary({ ...base, stages: base.stages.map(stage => ({ ...stage, status: 'observed' })) }), false);
  for (const field of ['authority', 'reason', 'expected_effect', 'return_condition']) {
    assert.equal(validRecoveredAuthorityBoundary({ ...base, [field]: '' }), false);
  }
  for (const invalid of [
    { ...base, control_id: 'pxui.unknown.action' },
    { ...base, rendered: false },
    { ...base, errors: ['fault'] },
    { ...base, stages: base.stages.filter(stage => stage.stage !== 'recovery_rollback') }
  ]) {
    const receipt = completeReceipt();
    receipt.control_chains.controls.push(invalid);
    receipt.control_chains.inventory.control_count += 1;
    receipt.control_chains.aggregates.control_count += 1;
    const status = evaluateOperationalWalk(receipt);
    assert.equal(status.terminal_state, 'incomplete');
    assert.ok(status.issues.some(item => item.code === 'authority-boundaries-invalid'));
    assert.ok(status.issues.some(item => item.code === 'control-chains-incomplete'));
  }
});

test('observation-only controls require complete chains but are not mislabeled as unattempted interactions', () => {
  const receipt = completeReceipt();
  receipt.control_chains.controls.push({
    control_id: 'indicator-observed', surface_id: 'dashboard-control-plane', kind: 'indicator',
    attempted: false, terminal_disposition: 'installed_operational_interaction_complete'
  });
  receipt.control_chains.inventory.control_count += 1;
  receipt.control_chains.aggregates.control_count += 1;
  receipt.control_chains.aggregates.complete_interaction_chains += 1;
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed');
  assert.equal(status.coverage.attemptable_control_count, 6);
  assert.equal(status.coverage.attempted_attemptable_control_count, 6);
  assert.equal(status.coverage.attempted_control_count, 6);
  assert.equal(status.issues.some(item => item.code === 'controls-unattempted'), false);
});

test('source mismatch blocks completion even when coverage is otherwise complete', () => {
  const receipt = completeReceipt();
  receipt.host_source_mismatch = true;
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'blocked');
  assert.equal(status.source_identity.state, 'mismatch');
  assert.ok(status.issues.some(item => item.source === 'source_identity' && item.code === 'host-source-identity-mismatch'));
});

test('absence of a positive loaded-asset identity proof blocks completion', () => {
  const receipt = completeReceipt();
  delete receipt.source_identity;
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'blocked');
  assert.equal(status.source_identity.state, 'reported_match');
  assert.ok(status.issues.some(item => item.code === 'host-source-identity-unverified'));
});

test('page and console errors are normalized and fail the walk', () => {
  const receipt = completeReceipt();
  receipt.host_errors = [
    { source: 'pageerror', message: 'uncaught page failure' },
    { source: 'console', message: 'console contract failure' }
  ];
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'failed');
  assert.deepEqual(new Set(status.issues.map(item => item.source)), new Set(['console', 'page']));
});

test('only the exact external VS Code Mermaid contribution diagnostic is non-blocking', () => {
  const receipt = completeReceipt();
  receipt.host_errors = [{
    source: 'console',
    message: '%c  ERR color: #f33 Tool "renderMermaidDiagram" was not contributed.',
    context: 'console:vscode-file://vscode-app/c:/owned-vscode/resources/app/out/vs/workbench/workbench.desktop.main.js'
  }];
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed');
  assert.equal(status.issues.length, 1);
  assert.equal(status.issues[0].code, 'external-vscode-optional-tool-unavailable');
  assert.equal(status.issues[0].blocking, false);

  for (const changed of [
    { ...receipt.host_errors[0], message: '%c ERR color: #f33 Tool "differentTool" was not contributed.' },
    { ...receipt.host_errors[0], context: 'console:vscode-file://vscode-app/c:/owned-extension/extension.js' }
  ]) {
    const blocked = evaluateOperationalWalk({ ...completeReceipt(), host_errors: [changed] });
    assert.equal(blocked.terminal_state, 'failed');
    assert.equal(blocked.issues[0].code, 'console-error');
    assert.equal(blocked.issues[0].blocking, true);
  }
});

test('only the exact owned fixture Marketplace 404 is non-blocking', () => {
  const exact = {
    source: 'console',
    message: 'Failed to load resource: the server responded with a status of 404 ()',
    context: 'console:https://marketplace.visualstudio.com/_apis/public/gallery/vscode/px-owned/fixture/latest'
  };
  const status = evaluateOperationalWalk({ ...completeReceipt(), host_errors: [exact] });
  assert.equal(status.terminal_state, 'completed');
  assert.equal(status.issues[0].code, 'external-vscode-owned-fixture-marketplace-miss');
  assert.equal(status.issues[0].blocking, false);

  for (const changed of [
    { ...exact, context: exact.context.replace('/px-owned/fixture/', '/px-owned/different/') },
    { ...exact, message: 'Failed to load resource: the server responded with a status of 500 ()' },
    { ...exact, source: 'page' }
  ]) {
    const blocked = evaluateOperationalWalk({ ...completeReceipt(), host_errors: [changed] });
    assert.equal(blocked.terminal_state, 'failed');
    assert.equal(blocked.issues[0].blocking, true);
  }
});

test('only exact external VS Code Windows integration diagnostics are non-blocking', () => {
  const context = 'console:vscode-file://vscode-app/c:/owned-vscode/resources/app/out/vs/workbench/workbench.desktop.main.js';
  const windowsApps = {
    source: 'console', context,
    message: "%c  ERR color: #f33 EPERM: operation not permitted, scandir 'C:\\Users\\Ben\\AppData\\Local\\Microsoft\\WindowsApps': Error: EPERM: operation not permitted, scandir 'C:\\Users\\Ben\\AppData\\Local\\Microsoft\\WindowsApps'"
  };
  const deviceId = {
    source: 'console', context,
    message: '[main 2026-09-07T14:15:35.613Z] Error: Unable to create or open registry key\n    at Object.setDeviceId (C:\\owned\\resources\\app\\node_modules.asar\\@vscode\\deviceid\\dist\\storage.js:100:25)'
  };
  const status = evaluateOperationalWalk({ ...completeReceipt(), host_errors: [windowsApps, deviceId] });
  assert.equal(status.terminal_state, 'completed');
  assert.deepEqual(new Set(status.issues.map(item => item.code)), new Set([
    'external-vscode-windows-app-alias-scan-denied',
    'external-vscode-device-id-registry-unavailable'
  ]));
  for (const changed of [{ ...windowsApps, source: 'pageerror' }, { ...deviceId, context: 'console:vscode-file://vscode-app/c:/owned-extension/extension.js' }]) {
    assert.equal(evaluateOperationalWalk({ ...completeReceipt(), host_errors: [changed] }).terminal_state, 'failed');
  }

  const processIssues = normalizeProcessOutput({
    stderr: "[main 2026-09-07T14:15:35.613Z] Error: Unable to create or open registry key\nEPERM: operation not permitted, scandir 'C:\\Users\\Ben\\AppData\\Local\\Microsoft\\WindowsApps': Error: EPERM: denied",
    walkerExit: { code: 0, signal: null }, processTreeClosedVerified: true
  });
  assert.equal(processIssues.every(item => item.blocking === false), true);
});

test('owned VS Code Marketplace denial is nonblocking only with the explicit sentinel and complete external stack context', () => {
  const stderr = [
    'Error while getting the latest version for the extension mountain-nomad-bc.pacify-x-vscode from https://marketplace.visualstudio.com/_apis/public/gallery/vscode/{publisher}/{name}/latest. Trying the fallback https://www.vscode-unpkg.net/_gallery/{publisher}/{name}/latest Failed',
    'Failed to fetch',
    'Error while getting the latest version for the extension mountain-nomad-bc.pacify-x-vscode. TypeError: Failed to fetch',
    'Failed to fetch: Failed: Failed to fetch',
    '    at iut.queryRawGalleryExtensions (vscode-file://vscode-app/c:/owned-vscode/resources/app/out/vs/workbench/workbench.desktop.main.js:2060:51137)'
  ].join('\n');

  const classified = normalizeProcessOutput({
    stderr,
    walkerExit: { code: 0, signal: null },
    processTreeClosedVerified: true,
    ownedExternalNetworkDenied: true
  });

  assert.equal(classified.length, 1);
  assert.equal(classified[0].code, 'expected-owned-external-network-denial');
  assert.equal(classified[0].blocking, false);

  const withoutSentinel = normalizeProcessOutput({
    stderr,
    walkerExit: { code: 0, signal: null },
    processTreeClosedVerified: true,
    ownedExternalNetworkDenied: false
  });
  assert.ok(withoutSentinel.some(item => item.code === 'stderr-error' && item.blocking === true));

  const productFailure = normalizeProcessOutput({
    stderr: 'Pacify-X dashboard request Failed to fetch',
    walkerExit: { code: 0, signal: null },
    processTreeClosedVerified: true,
    ownedExternalNetworkDenied: true
  });
  assert.ok(productFailure.some(item => item.code === 'stderr-error' && item.blocking === true));
});
test('exact VS Code LM chat-control fetch denial is nonblocking only inside the owned external-network-denied host', () => {
  const exact = '[LM] Failed to request chat control data Failed to fetch';

  const owned = normalizeProcessOutput({
    stderr: exact,
    walkerExit: { code: 0, signal: null },
    processTreeClosedVerified: true,
    ownedExternalNetworkDenied: true
  });

  assert.equal(owned.length, 1);
  assert.equal(owned[0].code, 'expected-owned-lm-external-network-denial');
  assert.equal(owned[0].blocking, false);

  const unowned = normalizeProcessOutput({
    stderr: exact,
    walkerExit: { code: 0, signal: null },
    processTreeClosedVerified: true,
    ownedExternalNetworkDenied: false
  });

  assert.ok(unowned.some(item =>
    item.code === 'stderr-error'
    && item.blocking === true
    && item.message === exact
  ));

  const altered = normalizeProcessOutput({
    stderr: '[LM] Failed to request some other control data Failed to fetch',
    walkerExit: { code: 0, signal: null },
    processTreeClosedVerified: true,
    ownedExternalNetworkDenied: true
  });

  assert.ok(altered.some(item =>
    item.code === 'stderr-error'
    && item.blocking === true
  ));

  const product = normalizeProcessOutput({
    stderr: 'Pacify-X dashboard Failed to fetch',
    walkerExit: { code: 0, signal: null },
    processTreeClosedVerified: true,
    ownedExternalNetworkDenied: true
  });

  assert.ok(product.some(item =>
    item.code === 'stderr-error'
    && item.blocking === true
  ));
});
test('extension-host unresponsive output remains blocking even after recovery', () => {
  const processIssues = normalizeProcessOutput({
    stdout: [
      'Extension host with pid 42 is unresponsive.',
      'Extension host with pid 42 became responsive.',
      'GitHub authentication token is unavailable.'
    ].join('\n'),
    walkerExit: { code: 0, signal: null },
    processTreeClosedVerified: true
  });
  const unresponsive = processIssues.find(item => item.code === 'extension-host-unresponsive');
  const warning = processIssues.find(item => item.code === 'github-token-unavailable');
  assert.equal(unresponsive.source, 'extension_host');
  assert.equal(unresponsive.recovered, true);
  assert.equal(unresponsive.blocking, true);
  assert.equal(warning.blocking, false);
  assert.equal(evaluateOperationalWalk(completeReceipt(), { additionalIssues: processIssues }).terminal_state, 'blocked');
});

test('only the exact paired external Windows Jump List persistence diagnostic is non-blocking', () => {
  const pair = [
    '[20664:0906/102045.946:ERROR:electron\\shell\\browser\\api\\electron_api_app.cc:1430] Failed to commit changes to custom Jump List.',
    '[main 2026-09-06T14:20:45.948Z] updateWindowsJumpList#setJumpList unexpected result: error'
  ];
  const classified = normalizeProcessOutput({ stderr: pair.join('\n'), walkerExit: { code: 0, signal: null }, processTreeClosedVerified: true });
  assert.equal(classified.length, 1);
  assert.equal(classified[0].code, 'external-windows-jump-list-persistence-unavailable');
  assert.equal(classified[0].blocking, false);
  assert.equal(classified[0].occurrences, 2);
  for (const stderr of [pair[0], pair[1], pair.join('\n').replace('custom Jump List', 'project list')]) {
    const blocked = normalizeProcessOutput({ stderr, walkerExit: { code: 0, signal: null }, processTreeClosedVerified: true });
    assert.ok(blocked.some(item => item.code === 'stderr-error' && item.blocking === true));
  }
});

test('launcher requires both semantic completion and verified process closure', () => {
  const walkStatus = evaluateOperationalWalk(completeReceipt());
  assert.equal(evaluateLauncherTerminal({
    walkStatus,
    processTreeClosedVerified: true,
    workerExitVerified: true
  }).terminal_state, 'completed');
  const failed = evaluateLauncherTerminal({
    walkStatus,
    processTreeClosedVerified: false,
    workerExitVerified: true
  });
  assert.equal(failed.terminal_state, 'failed');
  assert.ok(failed.issues.some(item => item.code === 'owner-process-tree-closure-unverified'));
  const cleanupFailed = evaluateLauncherTerminal({
    walkStatus,
    processTreeClosedVerified: true,
    workerExitVerified: true,
    cleanupReclaimed: false
  });
  assert.equal(cleanupFailed.terminal_state, 'failed');
  assert.ok(cleanupFailed.issues.some(item => item.code === 'owned-ephemeral-cleanup-unreclaimed'));
});

test('issue deduplication retains malformed inputs and the strongest blocking verdict', () => {
  const issues = dedupeIssues([
    null,
    'malformed detail',
    { source: 'test', code: 'same', severity: 'info', blocking: false, message: 'same message' },
    { source: 'test', code: 'same', severity: 'critical', blocking: true, message: 'same message' }
  ]);
  assert.ok(issues.some(item => item.code === 'malformed-additional-issue' && item.blocking === true));
  const strongest = issues.find(item => item.code === 'same');
  assert.equal(strongest.blocking, true);
  assert.equal(strongest.severity, 'critical');
  assert.equal(strongest.occurrences, 2);
});

test('launcher cannot promote a failed or focused child scope to operational completion', () => {
  const cases = [
    [{ schema_version: 'px.operational-ui-walk-status/1.0', terminal_state: 'failed', scope_complete: true, operationally_complete: false, issues: [] }, false],
    [{ schema_version: 'px.operational-ui-walk-status/1.0', terminal_state: 'completed', scope_complete: true, operationally_complete: false, issues: [] }, true],
    [{ schema_version: 'px.operational-ui-walk-status/1.0', terminal_state: 'completed', scope_complete: false, operationally_complete: true, issues: [] }, false]
  ];
  for (const [walkStatus, mayCompleteScope] of cases) {
    const result = evaluateLauncherTerminal({
      walkStatus,
      processTreeClosedVerified: true,
      workerExitVerified: true
    });
    assert.equal(result.terminal_state === 'completed', mayCompleteScope);
    assert.equal(result.operationally_complete, false);
    assert.equal(result.issues.some(item => item.code === 'child-walk-not-complete'), !mayCompleteScope);
  }
});

test('verified owned timeout remains blocking without inventing an unverified worker exit', () => {
  const status = evaluateLauncherTerminal({
    walkStatus: null,
    processTreeClosedVerified: true,
    workerExitVerified: true,
    error: new Error('owned-host-timeout')
  });
  assert.equal(status.terminal_state, 'failed');
  assert.ok(status.issues.some(item => item.code === 'walk-status-missing'));
  assert.ok(status.issues.some(item => item.code === 'launcher-error'));
  assert.equal(status.issues.some(item => item.code === 'owned-worker-exit-unverified'), false);
  assert.equal(status.issues.some(item => item.code === 'owner-process-tree-closure-unverified'), false);
});

test('bootstrap activation completes only with the installed extension and isolated storage proven', () => {
  const status = evaluateBootstrapActivation({
    bootstrap: readyBootstrap(),
    storageBoundary: { verified: true }
  });
  assert.equal(status.terminal_state, 'completed');
  assert.equal(status.operationally_complete, true);
  assert.equal(status.summary.blocking_issue_count, 0);
});

test('bootstrap activation fails closed on missing commands or unverified shared storage', () => {
  const bootstrap = readyBootstrap();
  bootstrap.command_executed = false;
  const status = evaluateBootstrapActivation({ bootstrap, storageBoundary: { verified: false } });
  assert.equal(status.terminal_state, 'failed');
  assert.equal(status.operationally_complete, false);
  assert.ok(status.issues.some(item => item.code === 'dashboard-command-not-executed'));
  assert.ok(status.issues.some(item => item.code === 'shared-storage-boundary-unverified'));
});

test('typed walker exit codes cannot disguise incomplete or blocked work as process success', () => {
  assert.equal(exitCodeForTerminalState('completed'), 0);
  assert.equal(exitCodeForTerminalState('failed'), 1);
  assert.equal(exitCodeForTerminalState('incomplete'), 2);
  assert.equal(exitCodeForTerminalState('blocked'), 3);
  assert.equal(normalizeProcessOutput({
    walkerExit: { code: 2, signal: null },
    expectedWalkerExitCode: 2,
    processTreeClosedVerified: true
  }).some(item => item.code === 'walker-process-exit-failed'), false);
  assert.equal(normalizeProcessOutput({
    walkerExit: { code: 0, signal: null },
    expectedWalkerExitCode: 2,
    processTreeClosedVerified: true
  }).some(item => item.code === 'walker-process-exit-failed'), true);
});
