'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { projectWorkflowTrace } = require('../src/workflowTraceProjection');

const controllerSource = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '90-controller.js'), 'utf8');

const identity = Object.freeze({
  workflow_id: 'workflow:demo',
  version: '2.1.0',
  revision_sha256: 'a'.repeat(64),
  run_id: 'run-one'
});

test('projects direct node receipts without inventing absent fields', () => {
  const result = projectWorkflowTrace({
    ...identity,
    state: 'failed',
    node_receipts: [
      {
        node_id: 'step:branch', state: 'skipped', kind: 'task', attempts: [],
        skip_reason: 'incoming_condition_disabled', disabled_required_ports: ['value']
      },
      {
        node_id: 'step:work', state: 'failed', attempts: [{ attempt: 1, failure_type: 'RuntimeError', correlation_id: 'corr-1' }],
        duration_ms: 42, approval_execution: { required: true, host_consumed: true }
      }
    ]
  }, { expectedIdentity: identity });

  assert.equal(result.action, 'replace');
  assert.deepEqual(result.identity, identity);
  assert.deepEqual(result.nodes['step:branch'], {
    node_id: 'step:branch', state: 'skipped', kind: 'task', skip_reason: 'incoming_condition_disabled',
    attempt_count: 0, disabled_required_ports: ['value']
  });
  assert.deepEqual(result.nodes['step:work'], {
    node_id: 'step:work', state: 'failed', attempt_count: 1, duration_ms: 42,
    approval_execution: { required: true, host_consumed: true },
    failure: { failure_type: 'RuntimeError', correlation_id: 'corr-1' }
  });
  assert.equal(Object.hasOwn(result.nodes['step:branch'], 'duration_ms'), false);
  assert.equal(result.metadata.run_state, 'failed');
});

test('projects authenticated durable checkpoint receipts and recovery metadata', () => {
  const result = projectWorkflowTrace({
    subject_id: identity.workflow_id,
    version: identity.version,
    revision_sha256: identity.revision_sha256,
    run_id: identity.run_id,
    state: 'paused',
    checkpoint: {
      node_receipts: [{ node_id: 'step:one', state: 'succeeded', attempts: [{ attempt: 1 }] }],
      ready_nodes: ['step:two'], next_node: 'step:two',
      recovery: 'resume from the last completed node with fresh node approvals'
    }
  }, { expectedIdentity: identity });

  assert.equal(result.action, 'replace');
  assert.equal(result.nodes['step:one'].attempt_count, 1);
  assert.deepEqual(result.metadata.ready_nodes, ['step:two']);
  assert.equal(result.metadata.next_node, 'step:two');
  assert.match(result.metadata.recovery, /resume from/);
});

test('does not relabel a successful attempt correlation as a failure', () => {
  const result = projectWorkflowTrace({
    ...identity,
    node_receipts: [{ node_id: 'step:one', state: 'succeeded', attempts: [{ attempt: 1, correlation_id: 'corr-success' }] }]
  }, { expectedIdentity: identity });
  assert.equal(result.action, 'replace');
  assert.equal(Object.hasOwn(result.nodes['step:one'], 'failure'), false);
});

test('rejects incomplete workflow-only identity', () => {
  const result = projectWorkflowTrace({ workflow_id: identity.workflow_id, node_receipts: [] });
  assert.equal(result.action, 'clear');
  assert.equal(result.reason, 'trace-identity-incomplete');
});

test('clears a result from another revision before projecting receipts', () => {
  const result = projectWorkflowTrace({
    ...identity, revision_sha256: 'b'.repeat(64),
    node_receipts: [{ node_id: 'step:wrong', state: 'succeeded' }]
  }, { expectedIdentity: identity, currentIdentity: identity });
  assert.equal(result.action, 'clear');
  assert.equal(result.reason, 'editor-identity-mismatch');
  assert.deepEqual(result.nodes, {});
});

test('does not replace the current run unless the caller explicitly admits a new run', () => {
  const next = { ...identity, run_id: 'run-two' };
  const refused = projectWorkflowTrace({ ...next, node_receipts: [] }, { expectedIdentity: identity, currentIdentity: identity });
  assert.equal(refused.action, 'clear');
  assert.equal(refused.reason, 'current-run-identity-mismatch');

  const accepted = projectWorkflowTrace({ ...next, node_receipts: [] }, { expectedIdentity: identity, currentIdentity: identity, allowNewRun: true });
  assert.equal(accepted.action, 'replace');
  assert.equal(accepted.identity.run_id, 'run-two');
});

test('run lists refresh only the already selected exact run', () => {
  const matching = { ...identity, checkpoint: { node_receipts: [{ node_id: 'step:one', state: 'succeeded' }] } };
  const result = projectWorkflowTrace({ runs: [{ ...identity, run_id: 'run-other' }, matching] }, { expectedIdentity: identity, currentIdentity: identity });
  assert.equal(result.action, 'replace');
  assert.equal(result.reason, 'current-run-refreshed-from-list');
  assert.equal(result.nodes['step:one'].state, 'succeeded');

  const noSelection = projectWorkflowTrace({ runs: [matching] }, { expectedIdentity: identity });
  assert.equal(noSelection.action, 'unchanged');
  assert.equal(noSelection.reason, 'no-current-run-in-list');
});

test('browser controller consumes durable checkpoints through revision and run bound projection', () => {
  assert.match(controllerSource, /Array\.isArray\(value\.checkpoint\?\.node_receipts\)\s*\?\s*value\.checkpoint\.node_receipts/);
  const identitySource = controllerSource.match(/function workflowTraceIdentityOf[\s\S]+?function workflowReceiptFailure/)?.[0] || '';
  for (const field of ['workflow_id', 'version', 'revision_sha256', 'run_id']) assert.match(identitySource, new RegExp(`\\b${field}\\b`));
  assert.match(identitySource, /completeWorkflowTraceIdentity[\s\S]+identity\?\.workflow_id\s*&&\s*identity\?\.version\s*&&\s*identity\?\.run_id/);
  assert.match(identitySource, /workflowTraceIdentityConflict[\s\S]+revision_sha256[\s\S]+run_id/);
  assert.match(controllerSource, /message\.operation === 'runs'[\s\S]+applyWorkflowTraceResult\(message\.result, message\.operation\)/);
  assert.match(controllerSource, /message\.operation === 'status'\) applyWorkflowTraceResult\(message\.result, message\.operation\)/);
  assert.match(controllerSource, /\['run', 'start', 'resume'\]\.includes\(message\.operation\)\) applyWorkflowTraceResult\(message\.result, message\.operation\)/);
});

test('browser controller renders projected attempt failure skip and recovery evidence safely', () => {
  const renderSource = controllerSource.match(/function workflowTraceEvidenceText[\s\S]+?function upgradeWorkflowCanvas/)?.[0] || '';
  const upgradeSource = controllerSource.match(/function upgradeWorkflowCanvas[\s\S]+?function workflowAuthorityHtml/)?.[0] || '';
  for (const field of ['attempt_count', 'skip_reason', 'disabled_required_ports', 'failure', 'recovery']) assert.match(renderSource, new RegExp(`\\b${field}\\b`));
  assert.match(renderSource, /summary\.textContent = detail/);
  assert.match(renderSource, /summary\.title = detail/);
  assert.match(renderSource, /removeAttribute\('aria-description'\)/);
  assert.match(renderSource, /setAttribute\('aria-description', detail\)/);
  assert.match(renderSource, /dataset\.workflowTraceEvidence = 'true'/);
  assert.match(upgradeSource, /annotateWorkflowTraceEvidence\(root\)/);
  assert.doesNotMatch(renderSource, /innerHTML\s*=\s*detail|insertAdjacentHTML\([^\n]*detail/);
});
