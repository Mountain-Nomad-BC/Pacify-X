'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createExtensionLifecycleHost } = require('../src/extensionLifecycleHost');
const { createPhysicalExtensionCatalog } = require('../src/extensionPhysicalCatalog');

function harness(initial = new Map(), manifests = new Map(), localTargets = new Map()) {
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
    commands: { executeCommand: async (command, target) => { calls.push([command, target]); if (command === 'workbench.extensions.uninstallExtension') installed.delete(target); else if (command === 'workbench.extensions.installExtension') { const local = localTargets.get(String(target)); if (local && !local.defer) installed.set(local.id, local.version); else if (!local) { const [id, version] = String(target).split('@'); installed.set(id, version || '9.9.9'); } } } }
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

test('local VSIX install, update, uninstall, and rollback bind exact bytes without network', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-local-vsix-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const v1 = path.join(root, 'fixture-1.0.0.vsix'); const v2 = path.join(root, 'fixture-2.0.0.vsix');
  fs.writeFileSync(v1, 'owned-local-vsix-v1'); fs.writeFileSync(v2, 'owned-local-vsix-v2');
  const targets = new Map([[v1, { id: 'px-owned.fixture', version: '1.0.0' }], [v2, { id: 'px-owned.fixture', version: '2.0.0' }]]);
  const state = harness(new Map(), new Map(), targets);
  const install = state.host.previewInstall({ extension_id: 'px-owned.fixture', version: '1.0.0', local_vsix_path: v1 });
  assert.equal(install.network_expected, false); assert.match(install.local_source.sha256, /^[0-9a-f]{64}$/);
  assert.equal((await state.host.executeInstall(install.token, { approved: true, exact_target: install.exact_target })).after_version, '1.0.0');
  const update = state.host.previewUpdate({ extension_id: 'px-owned.fixture', version: '2.0.0', local_vsix_path: v2 });
  assert.equal((await state.host.executeUpdate(update.token, { approved: true, exact_target: update.exact_target })).after_version, '2.0.0');
  const uninstall = state.host.previewUninstall({ extension_id: 'px-owned.fixture' });
  assert.equal(uninstall.rollback_identity.source_availability, 'hash-bound-local-vsix');
  await state.host.executeUninstall(uninstall.token, { approved: true, exact_target: uninstall.exact_target, consumer_impact_acknowledged: false });
  const rollback = state.host.previewRollback({ extension_id: 'px-owned.fixture' });
  assert.equal(rollback.local_source.path, v2);
  const restored = await state.host.executeRollback(rollback.token, { approved: true, exact_target: rollback.exact_target });
  assert.equal(restored.after_version, '2.0.0'); assert.equal(restored.reconciled, true);
});

test('reload-pending local VSIX source becomes rollback-eligible only after exact inventory convergence', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-local-vsix-pending-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const v2 = path.join(root, 'fixture-2.0.0.vsix');
  fs.writeFileSync(v2, 'owned-local-vsix-v2-pending');
  const state = harness(
    new Map([['px-owned.fixture', '1.0.0']]),
    new Map(),
    new Map([[v2, { id: 'px-owned.fixture', version: '2.0.0', defer: true }]])
  );
  const update = state.host.previewUpdate({ extension_id: 'px-owned.fixture', version: '2.0.0', local_vsix_path: v2 });
  const pending = await state.host.executeUpdate(update.token, { approved: true, exact_target: update.exact_target });
  assert.equal(pending.status, 'pending-host-reload-or-refresh');
  assert.equal(state.host.previewUninstall({ extension_id: 'px-owned.fixture' }).rollback_identity.source_availability, 'host-marketplace-or-original-source-not-yet-verified');
  state.installed.set('px-owned.fixture', '2.0.0');
  const converged = state.host.previewUninstall({ extension_id: 'px-owned.fixture' });
  assert.equal(converged.rollback_identity.source_availability, 'hash-bound-local-vsix');
  assert.equal(converged.rollback_identity.local_source.path, v2);
  state.installed.set('px-owned.fixture', '3.0.0');
  assert.equal(state.host.previewUninstall({ extension_id: 'px-owned.fixture' }).rollback_identity.source_availability, 'host-marketplace-or-original-source-not-yet-verified');
});

test('reload-pending rollback receipt preserves exact retained local source without consuming custody', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-local-vsix-rollback-pending-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const v2 = path.join(root, 'fixture-2.0.0.vsix');
  fs.writeFileSync(v2, 'owned-local-vsix-v2-rollback-pending');
  const target = { id: 'px-owned.fixture', version: '2.0.0' };
  const state = harness(new Map(), new Map(), new Map([[v2, target]]));
  const install = state.host.previewInstall({ extension_id: 'px-owned.fixture', version: '2.0.0', local_vsix_path: v2 });
  await state.host.executeInstall(install.token, { approved: true, exact_target: install.exact_target });
  const uninstall = state.host.previewUninstall({ extension_id: 'px-owned.fixture' });
  await state.host.executeUninstall(uninstall.token, { approved: true, exact_target: uninstall.exact_target, consumer_impact_acknowledged: false });
  target.defer = true;
  const rollback = state.host.previewRollback({ extension_id: 'px-owned.fixture' });
  const pending = await state.host.executeRollback(rollback.token, { approved: true, exact_target: rollback.exact_target });
  assert.equal(pending.status, 'pending-host-reload-or-refresh');
  assert.equal(pending.reconciled, false);
  assert.equal(pending.custody_state, 'retained-before-uninstall');
  assert.equal(pending.source_availability, 'hash-bound-local-vsix');
  assert.deepEqual(pending.local_source, rollback.local_source);
  assert.equal(state.host.rollbackHistory()[0].custody_state, 'retained-before-uninstall');
});

test('local VSIX execution fails closed when previewed bytes change', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-local-vsix-tamper-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const vsix = path.join(root, 'fixture.vsix'); fs.writeFileSync(vsix, 'before');
  const state = harness(new Map(), new Map(), new Map([[vsix, { id: 'px-owned.fixture', version: '1.0.0' }]]));
  const preview = state.host.previewInstall({ extension_id: 'px-owned.fixture', version: '1.0.0', local_vsix_path: vsix });
  fs.writeFileSync(vsix, 'after');
  await assert.rejects(state.host.executeInstall(preview.token, { approved: true, exact_target: preview.exact_target }), /local-vsix-bytes-changed/);
  assert.equal(state.calls.length, 0);
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

test('lifecycle receipts reconcile update, uninstall, and rollback from physical state while the loaded catalog remains stale', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-lifecycle-physical-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const writeManifest = (directory, version) => {
    const target = path.join(root, directory); fs.mkdirSync(target, { recursive: true });
    fs.writeFileSync(path.join(target, 'package.json'), JSON.stringify({ publisher: 'publisher', name: 'demo', version }));
    return target;
  };
  const current = path.join(root, 'pacify-x.control-plane-0.6.77'); fs.mkdirSync(current);
  fs.writeFileSync(path.join(current, 'package.json'), JSON.stringify({ publisher: 'pacify-x', name: 'control-plane', version: '0.6.77' }));
  const v1 = writeManifest('publisher.demo-1.0.0', '1.0.0');
  const loaded = { all: [{ id: 'publisher.demo', extensionPath: v1, packageJSON: { version: '1.0.0' }, isActive: true }] };
  const catalog = createPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: loaded });
  const stored = new Map();
  const host = createExtensionLifecycleHost({
    extensions: catalog,
    storage: { get: (key, fallback) => stored.has(key) ? stored.get(key) : fallback, update: async (key, value) => { stored.set(key, value); } },
    commands: { executeCommand: async (command, target) => {
      if (command === 'workbench.extensions.installExtension' && target === 'publisher.demo@2.0.0') {
        writeManifest('publisher.demo-2.0.0', '2.0.0');
        fs.writeFileSync(path.join(root, '.obsolete'), JSON.stringify({ 'publisher.demo-1.0.0': true }));
      } else if (command === 'workbench.extensions.uninstallExtension' && target === 'publisher.demo') {
        fs.writeFileSync(path.join(root, '.obsolete'), JSON.stringify({ 'publisher.demo-1.0.0': true, 'publisher.demo-2.0.0': true }));
      } else if (command === 'workbench.extensions.installExtension' && target === 'publisher.demo@2.0.0') {
        fs.writeFileSync(path.join(root, '.obsolete'), JSON.stringify({ 'publisher.demo-1.0.0': true, 'publisher.demo-2.0.0': false }));
      }
    } }
  });
  const update = host.previewUpdate({ extension_id: 'publisher.demo', version: '2.0.0' });
  const updated = await host.executeUpdate(update.token, { approved: true, exact_target: update.exact_target });
  assert.equal(updated.status, 'updated'); assert.equal(updated.after_version, '2.0.0'); assert.equal(updated.reconciled, true);
  const uninstall = host.previewUninstall({ extension_id: 'publisher.demo' });
  const removed = await host.executeUninstall(uninstall.token, { approved: true, exact_target: uninstall.exact_target, consumer_impact_acknowledged: false });
  assert.equal(removed.status, 'uninstalled'); assert.equal(removed.after_version, null); assert.equal(removed.reconciled, true);
  const rollback = host.previewRollback({ extension_id: 'publisher.demo' });
  const restored = await host.executeRollback(rollback.token, { approved: true, exact_target: rollback.exact_target });
  assert.equal(restored.status, 'restored'); assert.equal(restored.after_version, '2.0.0'); assert.equal(restored.reconciled, true);
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
