'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  evaluateBootstrapActivation,
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

test('focused native-dialog completion requires exact complete Enterprise, Projects, and Plugin mutation probes', () => {
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
  receipt.plugin_mutation_profile = completeProfile('plugin-mutation');
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'completed');
  assert.equal(status.scope_complete, true);
  assert.equal(status.operationally_complete, false);
  assert.equal(status.evaluated_scope, 'native-dialog-boundary');
});

test('focused native-dialog completion fails closed on missing recovery or profile errors', () => {
  const receipt = completeReceipt();
  receipt.focused_profile = 'native-dialog-boundary';
  const stages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const completeProfile = name => ({ observation: { errors: [] }, control_probe: { eligible_control_count: 1, records: [{ control_id: name, rendered: true, attempted: true, errors: [], interaction_chain: Object.fromEntries(stages.map(stage => [stage, { state: 'present' }])) }] } });
  receipt.enterprise_profile = completeProfile('enterprise');
  receipt.projects_profile = completeProfile('projects');
  receipt.plugin_mutation_profile = completeProfile('plugin-mutation');
  receipt.projects_profile.control_probe.records[0].interaction_chain.recovery_rollback = { state: 'missing' };
  receipt.plugin_mutation_profile.observation.errors.push('typed-restoration-mismatch');
  const status = evaluateOperationalWalk(receipt);
  assert.equal(status.terminal_state, 'incomplete');
  const finding = status.issues.find(item => item.code === 'focused-native-dialog-boundary-incomplete');
  assert.ok(finding);
  assert.deepEqual(finding.details.incomplete_profiles.map(item => item.name), ['projects', 'plugin-mutation']);
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
