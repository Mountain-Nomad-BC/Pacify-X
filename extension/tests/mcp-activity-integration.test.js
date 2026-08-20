'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { actorAttestation, createMcpActivityIntegration } = require('../src/mcpActivityIntegration');

function harness(overrides = {}) {
  const records = [];
  let sequence = 0;
  const integration = createMcpActivityIntegration({
    recordActivity: (...args) => { records.push(args); return { recorded: true }; },
    workspaceRoot: () => 'C:/bounded/project',
    projectId: () => 'project-1',
    contextEnvelope: () => ({ source: { session_id: 'context-session', surface: 'mcp-test' } }),
    policy: () => ({ captureMcpCalls: true }),
    now: () => '2026-08-11T12:00:00Z',
    uuid: () => `uuid-${++sequence}`,
    processId: 42,
    ...overrides
  });
  return { integration, records };
}

const readOnly = { annotations: { readOnlyHint: true } };

test('MCP middleware emits canonical-contract start and completion for one correlation', async () => {
  const { integration, records } = harness();
  const wrapped = integration.wrapTool('fixture_read', readOnly, async () => ({ ok: true, secret: 'not retained' }));
  assert.deepEqual(await wrapped({ actor_id: 'agent-a', session_id: 'session-a', harness: 'test', accountable_owner: 'owner-a', query: 'private' }), { ok: true, secret: 'not retained' });
  assert.equal(records.length, 2);
  const events = records.map(row => row[2]);
  assert.deepEqual(events.map(event => event.status), ['started', 'succeeded']);
  assert.equal(events[0].correlationId, events[1].correlationId);
  assert.equal(events[0].metadata.identity_attestation, 'self_asserted');
  assert.equal(events[0].metadata.canonical_schema_version, 'px.operation-event/1');
  assert.equal(events[0].metadata.payload_retained, false);
  assert.equal(JSON.stringify(records).includes('private'), false);
  assert.equal(JSON.stringify(records).includes('not retained'), false);
});

test('error lifecycle is emitted without exception text or content hash', async () => {
  const { integration, records } = harness();
  const wrapped = integration.wrapTool('fixture_error', readOnly, async () => { throw new Error('credential-value'); });
  await assert.rejects(() => wrapped({}), /credential-value/);
  assert.deepEqual(records.map(row => row[2].status), ['started', 'failed']);
  assert.equal(JSON.stringify(records).includes('credential-value'), false);
  assert.equal(JSON.stringify(records).includes('error_sha256'), false);
});

test('missing identity is explicitly unattested and reported correlation is only a parent', async () => {
  const { integration, records } = harness();
  const wrapped = integration.wrapTool('pacify_activity_emit', readOnly, async () => 1);
  await wrapped({ correlation_id: 'caller-claims-this' });
  const metadata = records[0][2].metadata;
  assert.equal(metadata.identity_attestation, 'unattested');
  assert.ok(metadata.unattested_fields.includes('actor_id'));
  assert.equal(metadata.reported_correlation_id, 'caller-claims-this');
  assert.notEqual(records[0][2].correlationId, 'caller-claims-this');
});

test('spoofable identity is labeled self-asserted, never verified', () => {
  const attestation = actorAttestation({ actor_id: 'root', session_id: 's', harness: 'h', accountable_owner: 'owner' }, {}, 42);
  assert.equal(attestation.identityAttestation, 'self_asserted');
  assert.notEqual(attestation.identityAttestation, 'verified');
});

test('instrumentation drops degrade health but do not replace tool outcome', async () => {
  const drops = [];
  const { integration } = harness({ recordActivity: () => { throw new Error('ledger unavailable'); }, onDrop: value => drops.push(value) });
  const wrapped = integration.wrapTool('fixture_drop', readOnly, async () => 42);
  assert.equal(await wrapped({}), 42);
  const health = integration.health();
  assert.equal(health.status, 'degraded');
  assert.equal(health.dropped_events, 2);
  assert.equal(health.last_drop_type, 'Error');
  assert.equal(drops.length, 2);
});

test('every registered tool is unique and appears in health inventory', () => {
  const { integration } = harness();
  integration.wrapTool('one', readOnly, async () => null);
  assert.throws(() => integration.wrapTool('one', readOnly, async () => null), /duplicate/);
  assert.deepEqual(integration.health().registered_tools, ['one']);
  assert.equal(integration.health().authority_granted, false);
});
