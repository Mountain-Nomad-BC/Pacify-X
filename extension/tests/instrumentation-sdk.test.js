'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { buildOperationEvent, instrumentOperation } = require('../src/instrumentationSdk');

function fixture() {
  return {
    sdk_version: 'px.instrumentation-sdk/1', schema_version: 'px.operation-event/1', event_id: 'evt-node', correlation_id: 'corr-sdk-parity', parent_correlation_id: null,
    actor: { actor_id: 'extension', actor_kind: 'extension', session_id: 'session-sdk', harness: 'node-test', accountable_owner: 'pacify-x' },
    work: { project_id: 'pacify-x', task_id: 'O02', claim_id: null, orchestration_id: null },
    source: { route_id: 'extension.command', component: 'src.extension', host_id: null, coverage_tier: 'C' },
    operation: { name: 'sdk-node', lifecycle: 'completed', result: 'success' },
    effects: { declared: ['read'], observed: ['read'], scope_refs: ['project:pacify-x'] }, provider: null,
    time: { observed_at: '2026-08-11T19:00:00Z', started_at: null, duration_ms: 1, freshness: 'live' },
    integrity: { input_sha256: null, output_sha256: null, previous_event_sha256: null }, capture: { classification: 'metadata_only', payload_included: false }
  };
}

test('instrumentation SDK refuses unknown versions', () => {
  const value = fixture(); value.sdk_version = 'px.instrumentation-sdk/999';
  assert.throws(() => buildOperationEvent(value), /unsupported instrumentation SDK version/);
});

test('instrumentation SDK emits correlated start and completion', async () => {
  const events = [];
  const value = await instrumentOperation(fixture(), event => events.push(event), async () => 42);
  assert.equal(value, 42);
  assert.deepEqual(events.map(event => [event.operation.lifecycle, event.operation.result]), [['started', 'pending'], ['completed', 'success']]);
  assert.ok(events.every(event => event.correlation_id === 'corr-sdk-parity'));
});
