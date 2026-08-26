'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { observeMcpRuntime } = require('../src/mcpRuntimeObservation');

const registration = { status: 'registered_unverified', registered: true, runtime_verified: false };
const nowMs = Date.parse('2026-08-25T19:00:00.000Z');
const event = {
  event_id: 'act-mcp-success', timestamp: '2026-08-25T18:59:00.000Z', category: 'mcp',
  source: 'pacify-x-mcp', status: 'succeeded', operation: 'pacify_context_snapshot',
  metadata: { server_version: '0.6.56' }
};

test('requires a fresh exact-version successful MCP invocation in an integrity-valid ledger', () => {
  const observed = observeMcpRuntime(registration, { integrity: { valid: true }, events: [event] }, '0.6.56', { nowMs });
  assert.equal(observed.runtime_verified, true);
  assert.equal(observed.status, 'runtime_verified');
  assert.equal(observed.evidence_event_id, event.event_id);
  assert.equal(observeMcpRuntime(registration, { integrity: { valid: true }, events: [{ ...event, status: 'started' }] }, '0.6.56', { nowMs }).runtime_verified, false);
  assert.equal(observeMcpRuntime(registration, { integrity: { valid: true }, events: [event] }, '0.6.55', { nowMs }).runtime_verified, false);
  assert.equal(observeMcpRuntime(registration, { integrity: { valid: false }, events: [event] }, '0.6.56', { nowMs }).runtime_verified, false);
  assert.equal(observeMcpRuntime(registration, { integrity: { valid: true }, events: [event] }, '0.6.56', { nowMs: nowMs + 25 * 60 * 60 * 1000 }).runtime_verified, false);
});

test('registration absence cannot be promoted by retained activity', () => {
  const observed = observeMcpRuntime({ status: 'unsupported', registered: false }, { integrity: { valid: true }, events: [event] }, '0.6.56', { nowMs });
  assert.equal(observed.runtime_verified, false);
  assert.equal(observed.status, 'unsupported');
});
