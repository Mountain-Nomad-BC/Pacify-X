'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  evaluateBootstrapActivation,
  evaluateLauncherTerminal,
  evaluateOperationalWalk,
  exitCodeForTerminalState,
  normalizeProcessOutput
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
  assert.equal(status.terminal_state, 'completed');
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
