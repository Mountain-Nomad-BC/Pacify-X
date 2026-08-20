'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createExtensionLifecycleHost } = require('../src/extensionLifecycleHost');

function harness(initial = new Map(), manifests = new Map()) {
  let clock = Date.parse('2026-08-17T00:00:00Z');
  const installed = initial;
  const calls = [];
  let sequence = 0;
  const stored = new Map();
  const extensionObject = id => installed.has(id) ? { id, packageJSON: { version: installed.get(id), ...(manifests.get(id) || {}) } } : undefined;
  const extensions = { get all() { return [...installed.keys()].map(extensionObject); }, getExtension: extensionObject };
  const host = createExtensionLifecycleHost({
    now: () => clock,
    uuid: () => `operation-${++sequence}`,
    extensions,
    storage: { get: (key, fallback) => stored.has(key) ? stored.get(key) : fallback, update: async (key, value) => { stored.set(key, value); } },
    commands: { executeCommand: async (command, target) => { calls.push([command, target]); if (command === 'workbench.extensions.uninstallExtension') installed.delete(target); else if (command === 'workbench.extensions.installExtension') { const [id, version] = target.split('@'); installed.set(id, version || '9.9.9'); } } }
  });
  return { host, installed, stored, calls, advance: value => { clock += value; } };
}

test('exact install preview dispatches documented host command and reconciles receipt', async () => {
  const { host, calls } = harness();
  const preview = host.previewInstall({ extension_id: 'Publisher.Demo', version: '1.2.3' });
  assert.equal(preview.exact_target, 'publisher.demo@1.2.3');
  const receipt = await host.executeInstall(preview.token, { approved: true, exact_target: preview.exact_target });
  assert.deepEqual(calls, [['workbench.extensions.installExtension', 'publisher.demo@1.2.3']]);
  assert.equal(receipt.status, 'installed');
  assert.equal(receipt.reconciled, true);
});

test('install refuses invalid identity, installed denominator, substitution, expiry, and absent approval', async () => {
  const current = harness(new Map([['publisher.present', '1.0.0']]));
  assert.throws(() => current.host.previewInstall({ extension_id: '../bad' }), /id-invalid/);
  assert.equal(current.host.previewInstall({ extension_id: 'publisher.present' }).allowed, false);
  const first = current.host.previewInstall({ extension_id: 'publisher.first' });
  await assert.rejects(current.host.executeInstall(first.token, { approved: false, exact_target: first.exact_target }), /approval-required/);
  const second = current.host.previewInstall({ extension_id: 'publisher.second' });
  await assert.rejects(current.host.executeInstall(second.token, { approved: true, exact_target: 'publisher.other' }), /target-substitution/);
  const third = current.host.previewInstall({ extension_id: 'publisher.third' });
  current.advance(5 * 60 * 1000 + 1);
  await assert.rejects(current.host.executeInstall(third.token, { approved: true, exact_target: third.exact_target }), /missing-or-expired/);
  assert.equal(current.calls.length, 0);
});

test('install refuses a newly occupied target immediately before dispatch', async () => {
  const state = harness();
  const preview = state.host.previewInstall({ extension_id: 'publisher.demo' });
  state.installed.set('publisher.demo', '2.0.0');
  await assert.rejects(state.host.executeInstall(preview.token, { approved: true, exact_target: preview.exact_target }), /denominator-changed/);
  assert.equal(state.calls.length, 0);
});

test('exact update binds prior version, dispatches target, and retains rollback identity', async () => {
  const state = harness(new Map([['publisher.demo', '1.2.3']]));
  const preview = state.host.previewUpdate({ extension_id: 'publisher.demo', version: '2.0.0' });
  assert.equal(preview.before_version, '1.2.3');
  assert.equal(preview.rollback_target, 'publisher.demo@1.2.3');
  const receipt = await state.host.executeUpdate(preview.token, { approved: true, exact_target: preview.exact_target });
  assert.deepEqual(state.calls, [['workbench.extensions.installExtension', 'publisher.demo@2.0.0']]);
  assert.equal(receipt.status, 'updated');
  assert.equal(receipt.after_version, '2.0.0');
  assert.equal(receipt.rollback_target, 'publisher.demo@1.2.3');
  assert.equal(receipt.reconciled, true);
});

test('update refuses absent/same/currently changed denominators and target substitution', async () => {
  const state = harness(new Map([['publisher.demo', '1.2.3']]));
  assert.equal(state.host.previewUpdate({ extension_id: 'publisher.absent' }).allowed, false);
  assert.equal(state.host.previewUpdate({ extension_id: 'publisher.demo', version: '1.2.3' }).allowed, false);
  const substituted = state.host.previewUpdate({ extension_id: 'publisher.demo', version: '2.0.0' });
  await assert.rejects(state.host.executeUpdate(substituted.token, { approved: true, exact_target: 'publisher.demo@3.0.0' }), /target-substitution/);
  const changed = state.host.previewUpdate({ extension_id: 'publisher.demo', version: '2.0.0' });
  state.installed.set('publisher.demo', '1.2.4');
  await assert.rejects(state.host.executeUpdate(changed.token, { approved: true, exact_target: changed.exact_target }), /update-denominator-changed/);
  assert.equal(state.calls.length, 0);
});

test('enablement handoff binds exact installed identity, intent, scope, and opens exact native record without claiming mutation', async () => {
  const state = harness(new Map([['publisher.demo', '2.0.0']]));
  const preview = state.host.previewEnablement({ extension_id: 'publisher.demo', desired_action: 'disable', scope: 'workspace' });
  assert.equal(preview.enablement_observed, null);
  assert.match(preview.exact_target, /#disable:workspace$/);
  const receipt = await state.host.executeEnablementHandoff(preview.token, { approved: true, exact_target: preview.exact_target });
  assert.deepEqual(state.calls, [['workbench.extensions.search', '@id:publisher.demo']]);
  assert.equal(receipt.status, 'awaiting-native-manager-action');
  assert.equal(receipt.mutation_dispatched, false);
  assert.equal(receipt.reconciled, false);
});

test('enablement handoff refuses invalid scope, absent extension, substitution, and changed denominator', async () => {
  const state = harness(new Map([['publisher.demo', '2.0.0']]));
  assert.throws(() => state.host.previewEnablement({ extension_id: 'publisher.demo', desired_action: 'disable', scope: 'session' }), /scope-invalid/);
  assert.equal(state.host.previewEnablement({ extension_id: 'publisher.absent', desired_action: 'enable', scope: 'global' }).allowed, false);
  const substituted = state.host.previewEnablement({ extension_id: 'publisher.demo', desired_action: 'enable', scope: 'global' });
  await assert.rejects(state.host.executeEnablementHandoff(substituted.token, { approved: true, exact_target: `${substituted.exact_target}x` }), /target-substitution/);
  const changed = state.host.previewEnablement({ extension_id: 'publisher.demo', desired_action: 'disable', scope: 'global' });
  state.installed.set('publisher.demo', '2.0.1');
  await assert.rejects(state.host.executeEnablementHandoff(changed.token, { approved: true, exact_target: changed.exact_target }), /enablement-denominator-changed/);
});

test('uninstall retains exact rollback identity before documented dispatch and reconciles absence', async () => {
  const state = harness(new Map([['publisher.demo', '2.0.0']]));
  const preview = state.host.previewUninstall({ extension_id: 'publisher.demo' });
  assert.equal(preview.rollback_identity.exact_target, 'publisher.demo@2.0.0');
  const receipt = await state.host.executeUninstall(preview.token, { approved: true, exact_target: preview.exact_target, consumer_impact_acknowledged: false });
  assert.deepEqual(state.calls, [['workbench.extensions.uninstallExtension', 'publisher.demo']]);
  assert.equal(receipt.status, 'uninstalled');
  assert.equal(receipt.reconciled, true);
  assert.equal(state.host.rollbackHistory()[0].custody_state, 'retained-before-uninstall');
});

test('uninstall refuses builtins, missing targets, unacknowledged consumers, and changed denominator', async () => {
  const manifests = new Map([['publisher.consumer', { extensionDependencies: ['publisher.demo'] }], ['vscode.builtin', { isBuiltin: true }]]);
  const state = harness(new Map([['publisher.demo', '2.0.0'], ['publisher.consumer', '1.0.0'], ['vscode.builtin', '1.0.0']]), manifests);
  assert.equal(state.host.previewUninstall({ extension_id: 'publisher.absent' }).allowed, false);
  assert.equal(state.host.previewUninstall({ extension_id: 'vscode.builtin' }).allowed, false);
  const consumers = state.host.previewUninstall({ extension_id: 'publisher.demo' });
  assert.equal(consumers.consumer_ack_required, true);
  await assert.rejects(state.host.executeUninstall(consumers.token, { approved: true, exact_target: consumers.exact_target, consumer_impact_acknowledged: false }), /consumer-impact-acknowledgement-required/);
  const changed = state.host.previewUninstall({ extension_id: 'publisher.demo' });
  state.installed.set('publisher.demo', '2.0.1');
  await assert.rejects(state.host.executeUninstall(changed.token, { approved: true, exact_target: changed.exact_target, consumer_impact_acknowledged: true }), /uninstall-denominator-changed/);
});

test('rollback consumes a retained uninstall identity only after exact-version restoration', async () => {
  const state = harness(new Map([['publisher.demo', '2.0.0']]));
  const uninstall = state.host.previewUninstall({ extension_id: 'publisher.demo' });
  await state.host.executeUninstall(uninstall.token, { approved: true, exact_target: uninstall.exact_target, consumer_impact_acknowledged: false });
  const preview = state.host.previewRollback({ extension_id: 'publisher.demo' });
  assert.equal(preview.exact_target, 'publisher.demo@2.0.0');
  const receipt = await state.host.executeRollback(preview.token, { approved: true, exact_target: preview.exact_target });
  assert.deepEqual(state.calls.at(-1), ['workbench.extensions.installExtension', 'publisher.demo@2.0.0']);
  assert.equal(receipt.status, 'restored');
  assert.equal(receipt.reconciled, true);
  assert.equal(state.host.rollbackHistory()[0].custody_state, 'rollback-consumed');
});

test('rollback refuses missing custody, occupied targets, substitution, and stale custody', async () => {
  const missing = harness();
  assert.equal(missing.host.previewRollback({ extension_id: 'publisher.demo' }).allowed, false);
  const occupied = harness(new Map([['publisher.demo', '2.0.0']]));
  assert.equal(occupied.host.previewRollback({ extension_id: 'publisher.demo' }).allowed, false);
  const state = harness(new Map([['publisher.demo', '2.0.0']]));
  const uninstall = state.host.previewUninstall({ extension_id: 'publisher.demo' });
  await state.host.executeUninstall(uninstall.token, { approved: true, exact_target: uninstall.exact_target, consumer_impact_acknowledged: false });
  const substituted = state.host.previewRollback({ extension_id: 'publisher.demo' });
  await assert.rejects(state.host.executeRollback(substituted.token, { approved: true, exact_target: 'publisher.demo@3.0.0' }), /target-substitution/);
  const stale = state.host.previewRollback({ extension_id: 'publisher.demo' });
  const history = state.host.rollbackHistory(); history[0].custody_state = 'rollback-consumed'; await state.stored.set('px.extensionLifecycle.rollbackHistory', history);
  await assert.rejects(state.host.executeRollback(stale.token, { approved: true, exact_target: stale.exact_target }), /rollback-custody-stale/);
});

test('conflict analysis emits stable typed signals and routes exact resolutions through proven lifecycle gates', async () => {
  const manifests = new Map([
    ['publisher.root', { contributes: { commands: [{ command: 'shared.run' }], keybindings: [{ key: 'ctrl+x', command: 'root.run' }] }, extensionDependencies: ['publisher.missing'] }],
    ['publisher.other', { contributes: { commands: [{ command: 'shared.run' }], keybindings: [{ key: 'ctrl+x', command: 'other.run' }] } }]
  ]);
  const state = harness(new Map([['publisher.root', '1.0.0'], ['publisher.other', '1.0.0']]), manifests);
  const analysis = state.host.conflictQuery({ extension_id: 'publisher.root' });
  assert.equal(analysis.available, true);
  assert.ok(analysis.signals.some(item => item.kind === 'duplicate-command-provider'));
  assert.ok(analysis.signals.some(item => item.kind === 'overlapping-keybinding'));
  assert.ok(analysis.signals.some(item => item.kind === 'missing-extension-dependency'));
  const signal = analysis.signals.find(item => item.kind === 'duplicate-command-provider');
  const preview = state.host.previewConflictResolution({ extension_id: 'publisher.root', signal_id: signal.signal_id, target_extension_id: 'publisher.other', resolution: 'uninstall' });
  const receipt = await state.host.executeConflictResolution(preview.token, { approved: true, exact_target: preview.exact_target });
  assert.equal(receipt.status, 'routed-to-governed-uninstall');
  assert.equal(receipt.mutation_dispatched, false);
  assert.equal(state.calls.length, 0);
});

test('conflict resolution refuses invalid target and a signal that changed after preview', async () => {
  const manifests = new Map([
    ['publisher.root', { contributes: { commands: [{ command: 'shared.run' }] } }],
    ['publisher.other', { contributes: { commands: [{ command: 'shared.run' }] } }]
  ]);
  const state = harness(new Map([['publisher.root', '1.0.0'], ['publisher.other', '1.0.0']]), manifests);
  const signal = state.host.conflictQuery({ extension_id: 'publisher.root' }).signals[0];
  assert.throws(() => state.host.previewConflictResolution({ extension_id: 'publisher.root', signal_id: signal.signal_id, target_extension_id: 'publisher.absent', resolution: 'uninstall' }), /target-not-admitted/);
  const preview = state.host.previewConflictResolution({ extension_id: 'publisher.root', signal_id: signal.signal_id, target_extension_id: 'publisher.other', resolution: 'inspect' });
  manifests.set('publisher.other', { contributes: { commands: [] } });
  await assert.rejects(state.host.executeConflictResolution(preview.token, { approved: true, exact_target: preview.exact_target }), /signal-missing-or-stale/);
});
