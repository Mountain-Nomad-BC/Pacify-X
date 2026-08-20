'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { MESSAGE_SCHEMA_VERSION, SIDEBAR_ASSET_PROTOCOL, validateSidebarInbound, validateSidebarOutbound, describeSidebarInboundRejection } = require('../src/sidebarMessages');
const { buildSidebarProjection } = require('../src/sidebarProjection');

test('S04 inbound sidebar schema is versioned, strict, bounded, and ID-only', () => {
  assert.deepEqual(validateSidebarInbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'openEntity', entityType: 'task', entityId: 'S04' }), { schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'openEntity', entityType: 'task', entityId: 'S04' });
  assert.deepEqual(validateSidebarInbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'ready', assetProtocol: SIDEBAR_ASSET_PROTOCOL }), { schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'ready', assetProtocol: SIDEBAR_ASSET_PROTOCOL });
  assert.throws(() => validateSidebarInbound({ schemaVersion: 'px.sidebar.message/2.0', type: 'ready', assetProtocol: SIDEBAR_ASSET_PROTOCOL }), /invalid/);
  assert.throws(() => validateSidebarInbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'ready', assetProtocol: SIDEBAR_ASSET_PROTOCOL, extra: true }), /unrecognized_keys/);
  assert.deepEqual(validateSidebarInbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'rendered', assetProtocol: SIDEBAR_ASSET_PROTOCOL, revision: 42, visibleComponentCount: 10, waveCount: 2, taskCount: 4, agentCount: 1, orchestrationCount: 1, recentCount: 3, attentionCount: 1, providerCount: 2, connected: true }), { schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'rendered', assetProtocol: SIDEBAR_ASSET_PROTOCOL, revision: 42, visibleComponentCount: 10, waveCount: 2, taskCount: 4, agentCount: 1, orchestrationCount: 1, recentCount: 3, attentionCount: 1, providerCount: 2, connected: true });
  assert.throws(() => validateSidebarInbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'rendered', assetProtocol: SIDEBAR_ASSET_PROTOCOL, revision: 42, visibleComponentCount: 2, waveCount: 2, taskCount: 4, agentCount: 1, orchestrationCount: 1, recentCount: 3, attentionCount: 1, providerCount: 2, connected: true }), /invalid/);
  assert.throws(() => validateSidebarInbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'openEntity', entityType: 'task', entityId: '../outside' }), /invalid_format/);
  assert.throws(() => validateSidebarInbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'openEntity', entityType: 'task', entityId: 'x'.repeat(161) }), /too_big/);
  assert.throws(() => validateSidebarInbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'toggleWave', waveId: 'wave-1', expanded: Number.NaN }), /invalid_type/);
  assert.throws(() => validateSidebarInbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'openEntity', entityType: 'task', entityId: 'safe', path: 'C:/secret' }), /unrecognized_keys/);
  const detail = describeSidebarInboundRejection({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'futureMessage', secret: 'redacted-value' }, new Error('sidebar-inbound-message-invalid:type:invalid_union'));
  assert.match(detail, /code=unsupported-message-type/);
  assert.match(detail, /observedType=futureMessage/);
  assert.doesNotMatch(detail, /redacted-value/);
  const staleAsset = describeSidebarInboundRejection({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'ready', assetProtocol: 'px.sidebar.asset/1.1' }, new Error('invalid'));
  assert.match(staleAsset, /code=stale-or-unsupported-asset-protocol/);
  const staleSchema = describeSidebarInboundRejection({ schemaVersion: 'px.sidebar.message/1.0', type: 'ready', assetProtocol: SIDEBAR_ASSET_PROTOCOL }, new Error('invalid'));
  assert.match(staleSchema, /code=stale-or-unsupported-message-schema/);
});

test('S04 outbound host messages reject unknown fields and unsupported projection versions', () => {
  const projection = buildSidebarProjection({ connected: false, generatedAt: '2026-08-11T18:00:00Z', source: {}, health: {}, attention: [] }, { nowMs: Date.parse('2026-08-11T18:00:00Z') });
  const capabilities = { renderAcknowledgement: true, assetProtocol: SIDEBAR_ASSET_PROTOCOL };
  assert.equal(validateSidebarOutbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'snapshot', capabilities, projection }).projection.schemaVersion, 'px.sidebar.snapshot/1.0');
  assert.throws(() => validateSidebarOutbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'snapshot', capabilities, projection: { ...projection, schemaVersion: 'px.sidebar.snapshot/9.0' } }), /invalid_value/);
  assert.throws(() => validateSidebarOutbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'snapshot', projection }), /invalid_type/);
  assert.throws(() => validateSidebarOutbound({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'error', code: 'error', detail: 'x', extra: true }), /unrecognized_keys/);
});
