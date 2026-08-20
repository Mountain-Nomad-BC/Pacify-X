'use strict';

const crypto = require('crypto');
const { analyzeExtensionConflicts } = require('./extensionConflictAnalyzer');

const EXTENSION_ID = /^[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9-]{0,127}$/;
const VERSION = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-.][a-z0-9][a-z0-9.-]{0,63})?$/;
const TOKEN_TTL_MS = 5 * 60 * 1000;
const MAX_TOKENS = 64;
const ROLLBACK_HISTORY_KEY = 'px.extensionLifecycle.rollbackHistory';

function exactId(value) {
  const id = String(value || '').trim().toLowerCase();
  if (!EXTENSION_ID.test(id)) throw new Error('extension-lifecycle-id-invalid');
  return id;
}

function exactVersion(value) {
  if (value == null || String(value).trim() === '') return null;
  const version = String(value).trim().toLowerCase();
  if (!VERSION.test(version)) throw new Error('extension-lifecycle-version-invalid');
  return version;
}

function installedVersion(extensions, id) {
  const extension = extensions.getExtension(id);
  return extension ? String(extension.packageJSON?.version || '').trim() || null : null;
}

function reverseConsumers(extensions, id) {
  const records = [];
  for (const extension of Array.isArray(extensions.all) ? extensions.all : []) {
    const owner = String(extension?.id || '').toLowerCase();
    if (!owner || owner === id) continue;
    const manifest = extension.packageJSON || {};
    if (Array.isArray(manifest.extensionDependencies) && manifest.extensionDependencies.map(value => String(value).toLowerCase()).includes(id)) records.push({ extension_id: owner, relationship: 'extension-dependency' });
    if (Array.isArray(manifest.extensionPack) && manifest.extensionPack.map(value => String(value).toLowerCase()).includes(id)) records.push({ extension_id: owner, relationship: 'extension-pack-member' });
  }
  return records.sort((left, right) => `${left.extension_id}:${left.relationship}`.localeCompare(`${right.extension_id}:${right.relationship}`));
}

function createExtensionLifecycleHost({ commands, extensions, storage = null, now = () => Date.now(), uuid = () => crypto.randomUUID() }) {
  if (typeof commands?.executeCommand !== 'function' || typeof extensions?.getExtension !== 'function') throw new TypeError('extension-lifecycle-host-dependencies-invalid');
  const previews = new Map();

  function prune() {
    const current = now();
    for (const [token, preview] of previews) if (preview.expires_at_ms <= current) previews.delete(token);
    while (previews.size >= MAX_TOKENS) previews.delete(previews.keys().next().value);
  }

  function previewInstall(input = {}) {
    prune();
    const extension_id = exactId(input.extension_id);
    const version = exactVersion(input.version);
    const before_version = installedVersion(extensions, extension_id);
    if (before_version) return {
      schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false,
      action: 'install', extension_id, reason: 'extension-already-installed',
      handoff: 'Use the governed update operation for an installed extension.'
    };
    const exact_target = version ? `${extension_id}@${version}` : extension_id;
    const token = uuid();
    const preview = {
      schema_version: 'px.extension-lifecycle-preview/1.0', allowed: true,
      action: 'install', token, extension_id, version, exact_target,
      before_version: null, effect: 'install', network_expected: !input.vsix,
      authority: 'PX governs exact scope and evidence; VS Code retains native install, publisher-trust, and security authority.',
      expires_at_ms: now() + TOKEN_TTL_MS
    };
    previews.set(token, preview);
    return { ...preview, expires_at_ms: undefined };
  }

  function previewUpdate(input = {}) {
    prune();
    const extension_id = exactId(input.extension_id);
    const version = exactVersion(input.version);
    const before_version = installedVersion(extensions, extension_id);
    if (!before_version) return {
      schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false,
      action: 'update', extension_id, reason: 'extension-not-installed',
      handoff: 'Use the governed install operation before requesting an update.'
    };
    if (version === before_version) return {
      schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false,
      action: 'update', extension_id, before_version, reason: 'extension-target-already-current',
      handoff: 'Choose a different exact version or leave the version empty for the host-selected latest compatible release.'
    };
    const exact_target = version ? `${extension_id}@${version}` : extension_id;
    const token = uuid();
    const preview = {
      schema_version: 'px.extension-lifecycle-preview/1.0', allowed: true,
      action: 'update', token, extension_id, version, exact_target, before_version,
      rollback_target: `${extension_id}@${before_version}`,
      compatibility_gate: 'VS Code enforces target engine compatibility and native security policy during update; PX does not pre-claim Marketplace compatibility.',
      effect: 'update-installed-extension', network_expected: true,
      authority: 'PX governs exact scope, prior identity, confirmation, and evidence; VS Code retains native update, compatibility, publisher-trust, signature, and security authority.',
      expires_at_ms: now() + TOKEN_TTL_MS
    };
    previews.set(token, preview);
    return { ...preview, expires_at_ms: undefined };
  }

  function previewEnablement(input = {}) {
    prune();
    const extension_id = exactId(input.extension_id);
    const desired_action = String(input.desired_action || '');
    const scope = String(input.scope || '');
    if (!['enable', 'disable'].includes(desired_action)) throw new Error('extension-lifecycle-enablement-action-invalid');
    if (!['workspace', 'global'].includes(scope)) throw new Error('extension-lifecycle-enablement-scope-invalid');
    const before_version = installedVersion(extensions, extension_id);
    if (!before_version) return {
      schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false,
      action: desired_action, scope, extension_id, reason: 'extension-not-installed',
      handoff: 'Only an installed extension can be focused in the native enablement manager.'
    };
    const exact_target = `${extension_id}@${before_version}#${desired_action}:${scope}`;
    const token = uuid();
    const preview = {
      schema_version: 'px.extension-lifecycle-preview/1.0', allowed: true,
      action: 'enablement-handoff', desired_action, scope, token, extension_id,
      before_version, exact_target, activation_observed: Boolean(extensions.getExtension(extension_id)?.isActive),
      enablement_observed: null,
      limitation: 'The stable VS Code extension API reports activation, not workspace/global enablement, and exposes no documented direct per-extension enable/disable mutation. PX will focus the exact native-manager record and observe a later extension-host change without claiming the mutation itself.',
      authority: 'PX governs exact identity, desired action, scope, confirmation, and evidence; the VS Code extension manager retains enablement authority.',
      expires_at_ms: now() + TOKEN_TTL_MS
    };
    previews.set(token, preview);
    return { ...preview, expires_at_ms: undefined };
  }

  function previewUninstall(input = {}) {
    prune();
    const extension_id = exactId(input.extension_id);
    const extension = extensions.getExtension(extension_id);
    const before_version = installedVersion(extensions, extension_id);
    if (!extension || !before_version) return { schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false, action: 'uninstall', extension_id, reason: 'extension-not-installed', handoff: 'Refresh the installed-extension inventory before requesting uninstall.' };
    if (Boolean(extension.packageJSON?.isBuiltin || extension_id.startsWith('vscode.'))) return { schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false, action: 'uninstall', extension_id, before_version, reason: 'builtin-extension-uninstall-refused', handoff: 'Pacify-X does not dispatch uninstall for a built-in host extension.' };
    if (typeof storage?.get !== 'function' || typeof storage?.update !== 'function') return { schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false, action: 'uninstall', extension_id, before_version, reason: 'rollback-custody-unavailable', handoff: 'Durable host storage is required before uninstall can be admitted.' };
    const consumers = reverseConsumers(extensions, extension_id);
    const exact_target = `${extension_id}@${before_version}#uninstall`;
    const token = uuid();
    const preview = {
      schema_version: 'px.extension-lifecycle-preview/1.0', allowed: true, action: 'uninstall', token,
      extension_id, before_version, exact_target, consumers, consumer_ack_required: consumers.length > 0,
      rollback_identity: { extension_id, version: before_version, exact_target: `${extension_id}@${before_version}`, source_availability: 'host-marketplace-or-original-source-not-yet-verified' },
      rollback_limit: 'PX retains the exact prior identity before dispatch. Reinstall still depends on the host accepting that exact version from a trusted available source; an installed directory is not treated as a signed package artifact.',
      authority: 'PX governs exact scope, consumer disclosure, rollback identity custody, confirmation, and evidence; VS Code retains native uninstall and security authority.',
      expires_at_ms: now() + TOKEN_TTL_MS
    };
    previews.set(token, preview);
    return { ...preview, expires_at_ms: undefined };
  }

  function previewRollback(input = {}) {
    prune();
    const extension_id = exactId(input.extension_id);
    if (installedVersion(extensions, extension_id)) return { schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false, action: 'rollback', extension_id, reason: 'rollback-target-occupied', handoff: 'Rollback after uninstall requires the exact extension identity to be absent.' };
    const history = rollbackHistory();
    const retained = [...history].reverse().find(item => item?.extension_id === extension_id && item?.custody_state === 'retained-before-uninstall');
    if (!retained) return { schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false, action: 'rollback', extension_id, reason: 'eligible-rollback-identity-unavailable', handoff: 'No unconsumed retained-before-uninstall identity exists for this extension.' };
    const token = uuid();
    const preview = {
      schema_version: 'px.extension-lifecycle-preview/1.0', allowed: true, action: 'rollback', token,
      extension_id, version: retained.version, exact_target: retained.exact_target,
      retained_operation_id: retained.operation_id, custody_state: retained.custody_state,
      source_availability: retained.source_availability,
      source_gate: 'The exact historical version remains unverified until VS Code accepts and exposes it. PX will not consume custody on command failure, reload-pending state, or wrong-version observation.',
      authority: 'PX governs retained identity selection, exact target, confirmation, restored-version verification, and custody consumption; VS Code retains native source, compatibility, signature, trust, and install authority.',
      expires_at_ms: now() + TOKEN_TTL_MS
    };
    previews.set(token, preview);
    return { ...preview, expires_at_ms: undefined };
  }

  function conflictQuery(input = {}) {
    const extension_id = exactId(input.extension_id);
    if (!extensions.getExtension(extension_id)) return { schema_version: 'px.extension-conflict-analysis/1.0', extension_id, installed_extension_count: Array.isArray(extensions.all) ? extensions.all.length : 0, signal_count: 0, signals: [], available: false, reason: 'extension-not-installed' };
    return { ...analyzeExtensionConflicts(extensions.all, extension_id), available: true, generated_utc: new Date(now()).toISOString() };
  }

  function previewConflictResolution(input = {}) {
    prune();
    const extension_id = exactId(input.extension_id);
    const target_extension_id = exactId(input.target_extension_id);
    const signal_id = String(input.signal_id || '');
    const resolution = String(input.resolution || '');
    if (!['inspect', 'disable-workspace', 'disable-global', 'uninstall', 'install-target'].includes(resolution)) throw new Error('extension-conflict-resolution-invalid');
    const analysis = conflictQuery({ extension_id });
    const signal = analysis.signals.find(item => item.signal_id === signal_id);
    if (!signal) throw new Error('extension-conflict-signal-missing-or-stale');
    if (!signal.resolution_targets.includes(target_extension_id) || !signal.recommended_resolutions.includes(resolution)) throw new Error('extension-conflict-resolution-target-not-admitted');
    const token = uuid();
    const exact_target = `conflict:${signal_id}:${resolution}:${target_extension_id}`;
    const preview = { schema_version: 'px.extension-conflict-resolution-preview/1.0', allowed: true, action: 'conflict-resolution', token, extension_id, signal, signal_id, target_extension_id, resolution, exact_target, effect: ['uninstall', 'install-target'].includes(resolution) ? 'route-to-governed-lifecycle-preview' : resolution === 'inspect' ? 'open-exact-native-record' : 'route-to-governed-enablement-preview', authority: 'PX binds current signal, exact target, and resolution route; every mutation enters its existing governed lifecycle preview and VS Code native approval boundary.', expires_at_ms: now() + TOKEN_TTL_MS };
    previews.set(token, preview);
    return { ...preview, expires_at_ms: undefined };
  }

  async function executeInstall(token, approval = {}) {
    prune();
    const preview = previews.get(String(token || ''));
    if (!preview || preview.action !== 'install') throw new Error('extension-lifecycle-preview-missing-or-expired');
    previews.delete(preview.token);
    if (approval.approved !== true) throw new Error('extension-lifecycle-explicit-approval-required');
    if (String(approval.exact_target || '') !== preview.exact_target) throw new Error('extension-lifecycle-target-substitution');
    if (installedVersion(extensions, preview.extension_id) !== preview.before_version) throw new Error('extension-lifecycle-install-denominator-changed');
    await commands.executeCommand('workbench.extensions.installExtension', preview.exact_target);
    const observed = installedVersion(extensions, preview.extension_id);
    const expectedObserved = !preview.version || observed === preview.version;
    return {
      schema_version: 'px.extension-lifecycle-receipt/1.0', operation_id: uuid(),
      action: 'install', extension_id: preview.extension_id, exact_target: preview.exact_target,
      before_version: preview.before_version, after_version: observed,
      status: observed && expectedObserved ? 'installed' : 'pending-host-reload-or-refresh',
      reconciled: Boolean(observed && expectedObserved), command: 'workbench.extensions.installExtension',
      authority: preview.authority, completed_utc: new Date(now()).toISOString()
    };
  }

  async function executeUpdate(token, approval = {}) {
    prune();
    const preview = previews.get(String(token || ''));
    if (!preview || preview.action !== 'update') throw new Error('extension-lifecycle-preview-missing-or-expired');
    previews.delete(preview.token);
    if (approval.approved !== true) throw new Error('extension-lifecycle-explicit-approval-required');
    if (String(approval.exact_target || '') !== preview.exact_target) throw new Error('extension-lifecycle-target-substitution');
    if (installedVersion(extensions, preview.extension_id) !== preview.before_version) throw new Error('extension-lifecycle-update-denominator-changed');
    await commands.executeCommand('workbench.extensions.installExtension', preview.exact_target);
    const observed = installedVersion(extensions, preview.extension_id);
    const expectedObserved = Boolean(observed && (!preview.version || observed === preview.version));
    return {
      schema_version: 'px.extension-lifecycle-receipt/1.0', operation_id: uuid(),
      action: 'update', extension_id: preview.extension_id, exact_target: preview.exact_target,
      before_version: preview.before_version, after_version: observed,
      rollback_target: preview.rollback_target,
      status: expectedObserved ? (observed === preview.before_version ? 'host-reconciled-no-version-change' : 'updated') : 'pending-host-reload-or-refresh',
      reconciled: expectedObserved, command: 'workbench.extensions.installExtension',
      compatibility_gate: preview.compatibility_gate, authority: preview.authority,
      completed_utc: new Date(now()).toISOString()
    };
  }

  async function executeEnablementHandoff(token, approval = {}) {
    prune();
    const preview = previews.get(String(token || ''));
    if (!preview || preview.action !== 'enablement-handoff') throw new Error('extension-lifecycle-preview-missing-or-expired');
    previews.delete(preview.token);
    if (approval.approved !== true) throw new Error('extension-lifecycle-explicit-approval-required');
    if (String(approval.exact_target || '') !== preview.exact_target) throw new Error('extension-lifecycle-target-substitution');
    if (installedVersion(extensions, preview.extension_id) !== preview.before_version) throw new Error('extension-lifecycle-enablement-denominator-changed');
    await commands.executeCommand('workbench.extensions.search', `@id:${preview.extension_id}`);
    return {
      schema_version: 'px.extension-lifecycle-receipt/1.0', operation_id: uuid(),
      action: 'enablement-handoff', desired_action: preview.desired_action, scope: preview.scope,
      extension_id: preview.extension_id, before_version: preview.before_version,
      exact_target: preview.exact_target, status: 'awaiting-native-manager-action',
      reconciled: false, mutation_dispatched: false,
      command: 'workbench.extensions.search', query: `@id:${preview.extension_id}`,
      return_condition: 'Complete the requested enable/disable action in the exact native-manager record; PX will observe and refresh on the next extension-host change but will not infer enablement from activation.',
      authority: preview.authority, completed_utc: new Date(now()).toISOString()
    };
  }

  async function executeUninstall(token, approval = {}) {
    prune();
    const preview = previews.get(String(token || ''));
    if (!preview || preview.action !== 'uninstall') throw new Error('extension-lifecycle-preview-missing-or-expired');
    previews.delete(preview.token);
    if (approval.approved !== true) throw new Error('extension-lifecycle-explicit-approval-required');
    if (String(approval.exact_target || '') !== preview.exact_target) throw new Error('extension-lifecycle-target-substitution');
    if (preview.consumer_ack_required && approval.consumer_impact_acknowledged !== true) throw new Error('extension-lifecycle-consumer-impact-acknowledgement-required');
    if (installedVersion(extensions, preview.extension_id) !== preview.before_version) throw new Error('extension-lifecycle-uninstall-denominator-changed');
    const operation_id = uuid();
    const prior = storage.get(ROLLBACK_HISTORY_KEY, []);
    const history = Array.isArray(prior) ? prior.filter(item => item && typeof item === 'object').slice(-63) : [];
    const retained = { schema_version: 'px.extension-rollback-identity/1.0', operation_id, extension_id: preview.extension_id, version: preview.before_version, exact_target: preview.rollback_identity.exact_target, source_availability: preview.rollback_identity.source_availability, custody_state: 'retained-before-uninstall', recorded_utc: new Date(now()).toISOString() };
    await storage.update(ROLLBACK_HISTORY_KEY, [...history, retained]);
    const observedHistory = storage.get(ROLLBACK_HISTORY_KEY, []);
    if (!Array.isArray(observedHistory) || !observedHistory.some(item => item?.operation_id === operation_id && item?.exact_target === retained.exact_target)) throw new Error('extension-lifecycle-rollback-custody-verification-failed');
    await commands.executeCommand('workbench.extensions.uninstallExtension', preview.extension_id);
    const observed = installedVersion(extensions, preview.extension_id);
    return { schema_version: 'px.extension-lifecycle-receipt/1.0', operation_id, action: 'uninstall', extension_id: preview.extension_id, exact_target: preview.exact_target, before_version: preview.before_version, after_version: observed, rollback_identity: retained, consumers: preview.consumers, status: observed ? 'pending-host-reload-or-refresh' : 'uninstalled', reconciled: !observed, command: 'workbench.extensions.uninstallExtension', authority: preview.authority, completed_utc: new Date(now()).toISOString() };
  }

  async function executeRollback(token, approval = {}) {
    prune();
    const preview = previews.get(String(token || ''));
    if (!preview || preview.action !== 'rollback') throw new Error('extension-lifecycle-preview-missing-or-expired');
    previews.delete(preview.token);
    if (approval.approved !== true) throw new Error('extension-lifecycle-explicit-approval-required');
    if (String(approval.exact_target || '') !== preview.exact_target) throw new Error('extension-lifecycle-target-substitution');
    if (installedVersion(extensions, preview.extension_id)) throw new Error('extension-lifecycle-rollback-target-occupied');
    const history = rollbackHistory();
    const index = history.findIndex(item => item?.operation_id === preview.retained_operation_id && item?.extension_id === preview.extension_id && item?.exact_target === preview.exact_target && item?.custody_state === 'retained-before-uninstall');
    if (index < 0) throw new Error('extension-lifecycle-rollback-custody-stale');
    const operation_id = uuid();
    await commands.executeCommand('workbench.extensions.installExtension', preview.exact_target);
    const observed = installedVersion(extensions, preview.extension_id);
    const reconciled = observed === preview.version;
    if (reconciled) {
      history[index] = { ...history[index], custody_state: 'rollback-consumed', rollback_operation_id: operation_id, restored_utc: new Date(now()).toISOString(), source_availability: 'verified-by-host-exact-version-observation' };
      await storage.update(ROLLBACK_HISTORY_KEY, history.slice(-64));
      const confirmed = storage.get(ROLLBACK_HISTORY_KEY, []).find(item => item?.operation_id === preview.retained_operation_id);
      if (confirmed?.custody_state !== 'rollback-consumed' || confirmed?.rollback_operation_id !== operation_id) throw new Error('extension-lifecycle-rollback-consumption-verification-failed');
    }
    return { schema_version: 'px.extension-lifecycle-receipt/1.0', operation_id, action: 'rollback', extension_id: preview.extension_id, exact_target: preview.exact_target, before_version: null, after_version: observed, retained_operation_id: preview.retained_operation_id, custody_state: reconciled ? 'rollback-consumed' : 'retained-before-uninstall', source_availability: reconciled ? 'verified-by-host-exact-version-observation' : preview.source_availability, status: reconciled ? 'restored' : 'pending-host-reload-or-refresh', reconciled, command: 'workbench.extensions.installExtension', authority: preview.authority, completed_utc: new Date(now()).toISOString() };
  }

  async function executeConflictResolution(token, approval = {}) {
    prune();
    const preview = previews.get(String(token || ''));
    if (!preview || preview.action !== 'conflict-resolution') throw new Error('extension-lifecycle-preview-missing-or-expired');
    previews.delete(preview.token);
    if (approval.approved !== true) throw new Error('extension-lifecycle-explicit-approval-required');
    if (String(approval.exact_target || '') !== preview.exact_target) throw new Error('extension-lifecycle-target-substitution');
    const current = conflictQuery({ extension_id: preview.extension_id });
    const signal = current.signals.find(item => item.signal_id === preview.signal_id);
    if (!signal || !signal.resolution_targets.includes(preview.target_extension_id) || !signal.recommended_resolutions.includes(preview.resolution)) throw new Error('extension-conflict-signal-missing-or-stale');
    let status;
    let command = null;
    if (preview.resolution === 'inspect') {
      command = 'workbench.extensions.search';
      await commands.executeCommand(command, `@id:${preview.target_extension_id}`);
      status = 'exact-native-record-opened';
    } else if (preview.resolution === 'uninstall') status = 'routed-to-governed-uninstall';
    else if (preview.resolution === 'install-target') status = 'routed-to-governed-install';
    else status = 'routed-to-governed-enablement';
    return { schema_version: 'px.extension-conflict-resolution-receipt/1.0', operation_id: uuid(), action: 'conflict-resolution', extension_id: preview.extension_id, signal_id: preview.signal_id, signal, target_extension_id: preview.target_extension_id, resolution: preview.resolution, exact_target: preview.exact_target, status, reconciled: false, mutation_dispatched: false, command, lifecycle_route: status.startsWith('routed-to-governed-') ? status.slice('routed-to-governed-'.length) : null, authority: preview.authority, completed_utc: new Date(now()).toISOString() };
  }

  function rollbackHistory() {
    const value = typeof storage?.get === 'function' ? storage.get(ROLLBACK_HISTORY_KEY, []) : [];
    return Array.isArray(value) ? value.map(item => ({ ...item })) : [];
  }

  return Object.freeze({ previewInstall, executeInstall, previewUpdate, executeUpdate, previewEnablement, executeEnablementHandoff, previewUninstall, executeUninstall, previewRollback, executeRollback, conflictQuery, previewConflictResolution, executeConflictResolution, rollbackHistory, pendingCount: () => previews.size });
}

module.exports = { createExtensionLifecycleHost, exactId, exactVersion };
