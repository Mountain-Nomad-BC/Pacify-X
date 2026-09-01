'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { SidebarViewProvider, normalizeSidebarPreferences } = require('../src/sidebarView');
const { MESSAGE_SCHEMA_VERSION, SIDEBAR_ASSET_PROTOCOL } = require('../src/sidebarMessages');

function rendered(revision) {
  return {
    schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'rendered', assetProtocol: SIDEBAR_ASSET_PROTOCOL, revision, visibleComponentCount: 10,
    waveCount: 2, taskCount: 4, agentCount: 1, orchestrationCount: 1, recentCount: 3,
    attentionCount: 1, providerCount: 2, connected: true
  };
}

test('sidebar workspace preferences admit only bounded exact identities', async () => {
  assert.deepEqual(normalizeSidebarPreferences({ expandedWaveIds: ['wave-1', 'wave-1', '../escape', 'x'.repeat(161)], expandedTaskIds: ['task:1', null], selectedProviderId: '../provider' }), { expandedWaveIds: ['wave-1'], expandedTaskIds: ['task:1'], selectedProviderId: null });
  assert.deepEqual(normalizeSidebarPreferences(null), { expandedWaveIds: [], expandedTaskIds: [], selectedProviderId: null });
  let stored = null;
  const provider = new SidebarViewProvider({}, { workspaceState: { get: () => ({ expandedWaveIds: ['wave-1'], injected: 'ignored' }), update: async (_key, value) => { stored = value; } } });
  await provider.savePreferences({ expandedTaskIds: ['task:1', '../bad'], selectedProviderId: 'provider:one', extra: 'ignored' });
  assert.deepEqual(stored, { expandedWaveIds: ['wave-1'], expandedTaskIds: ['task:1'], selectedProviderId: 'provider:one' });
});

test('sidebar preference mutation publishes canonical host state only after durable storage completes', async () => {
  let releaseUpdate;
  const updatePending = new Promise(resolve => { releaseUpdate = resolve; });
  let stored = {};
  const provider = new SidebarViewProvider({}, {
    workspaceState: {
      get: () => stored,
      update: async (_key, value) => { await updatePending; stored = value; }
    }
  });
  provider.snapshot = { marker: 'current' };
  const pushes = [];
  provider.pushSnapshot = async (snapshot, force) => { pushes.push({ snapshot, force }); };

  const mutation = provider.receive({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'toggleWave', waveId: 'wave-1', expanded: true });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(pushes.length, 0, 'host must not acknowledge preference state before workspace storage completes');
  releaseUpdate();
  await mutation;
  assert.deepEqual(stored.expandedWaveIds, ['wave-1']);
  assert.deepEqual(pushes, [{ snapshot: provider.snapshot, force: true }]);
});

test('S02/S03 host inspection accepts only the current strict sidebar render acknowledgement', async () => {
  let ready = 0;
  const provider = new SidebarViewProvider({}, { workspaceState: { get: () => ({}), update: async () => {} } }, { onReady: async () => { ready += 1; } });
  provider.lastEnvelope = { projection: { revision: 42 } };

  await provider.receive({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'ready', assetProtocol: SIDEBAR_ASSET_PROTOCOL });
  await provider.receive(rendered(41));
  assert.equal(provider.inspect().render_ack_count, 0, 'stale renderer acknowledgement must not promote installed evidence');
  await provider.receive(rendered(42));

  const inspection = provider.inspect();
  assert.equal(ready, 1);
  assert.equal(inspection.ready_count, 1);
  assert.equal(inspection.render_ack_count, 1);
  assert.equal(inspection.rendered.revision, 42);
  assert.equal(inspection.rendered.visibleComponentCount, 10);
  assert.equal(inspection.rendered.taskCount, 4);
});

test('S04 rejection evidence is bounded and content-free while retaining the discriminator', async () => {
  const posted = [];
  const provider = new SidebarViewProvider({}, { workspaceState: { get: () => ({}), update: async () => {} } });
  provider.view = { visible: true, webview: { postMessage: async message => { posted.push(message); } } };
  await provider.receive({ schemaVersion: MESSAGE_SCHEMA_VERSION, type: 'futureMessage', secret: 'must-not-appear' });
  const inspection = provider.inspect();
  assert.equal(inspection.contract_rejection_count, 1);
  assert.match(inspection.last_contract_rejection.detail, /observedType=futureMessage/);
  assert.match(inspection.last_contract_rejection.detail, /keys=schemaVersion\|secret\|type/);
  assert.doesNotMatch(inspection.last_contract_rejection.detail, /must-not-appear/);
  assert.equal(posted.at(-1).type, 'error');
});
