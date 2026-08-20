'use strict';

const crypto = require('crypto');

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}

function signalId(value) {
  return `extension-conflict:${crypto.createHash('sha256').update(canonical(value)).digest('hex').slice(0, 24)}`;
}

function extensionRecords(extensions) {
  return (Array.isArray(extensions) ? extensions : []).map(extension => ({
    id: String(extension?.id || '').trim().toLowerCase(),
    version: String(extension?.packageJSON?.version || '').trim() || null,
    manifest: extension?.packageJSON || {}
  })).filter(item => item.id);
}

function analyzeExtensionConflicts(extensions, requestedId) {
  const records = extensionRecords(extensions);
  const installed = new Set(records.map(item => item.id));
  const resources = new Map();
  const add = (kind, resource, provider, detail = {}) => {
    const normalized = String(resource || '').trim().toLowerCase();
    if (!normalized) return;
    const key = `${kind}\0${normalized}`;
    if (!resources.has(key)) resources.set(key, { kind, resource: normalized, providers: [] });
    resources.get(key).providers.push({ extension_id: provider, ...detail });
  };
  const missing = [];
  const reverse = [];
  for (const record of records) {
    const contributes = record.manifest.contributes || {};
    for (const item of Array.isArray(contributes.commands) ? contributes.commands : []) add('duplicate-command-provider', item?.command, record.id);
    for (const item of Array.isArray(contributes.keybindings) ? contributes.keybindings : []) {
      const keys = [item?.key, item?.mac, item?.linux, item?.win].filter(Boolean).map(value => String(value).toLowerCase()).sort().join('|');
      add('overlapping-keybinding', `${keys}::${String(item?.when || '').trim().toLowerCase()}`, record.id, { command: String(item?.command || '') });
    }
    for (const item of Array.isArray(contributes.debuggers) ? contributes.debuggers : []) add('duplicate-debugger-provider', item?.type, record.id);
    for (const item of Array.isArray(contributes.customEditors) ? contributes.customEditors : []) add('duplicate-custom-editor-provider', item?.viewType, record.id);
    for (const item of Array.isArray(contributes.taskDefinitions) ? contributes.taskDefinitions : []) add('duplicate-task-provider', item?.type, record.id);
    for (const item of Array.isArray(contributes.authentication) ? contributes.authentication : []) add('duplicate-authentication-provider', item?.id, record.id);
    for (const item of Array.isArray(contributes.languages) ? contributes.languages : []) add('language-provider-overlap', item?.id, record.id);
    for (const group of Object.values(contributes.views && typeof contributes.views === 'object' ? contributes.views : {})) for (const item of Array.isArray(group) ? group : []) add('duplicate-view-provider', item?.id, record.id);
    for (const dependency of Array.isArray(record.manifest.extensionDependencies) ? record.manifest.extensionDependencies : []) {
      const dependencyId = String(dependency).toLowerCase();
      if (!installed.has(dependencyId)) missing.push({ kind: 'missing-extension-dependency', resource: dependencyId, owner: record.id });
      else reverse.push({ kind: 'reverse-extension-dependency', resource: dependencyId, owner: record.id });
    }
  }
  const signals = [];
  for (const value of resources.values()) {
    const extensionIds = [...new Set(value.providers.map(item => item.extension_id))].sort();
    if (value.providers.length < 2) continue;
    const identity = { kind: value.kind, resource: value.resource, providers: value.providers.slice().sort((a, b) => canonical(a).localeCompare(canonical(b))) };
    signals.push({ signal_id: signalId(identity), category: value.kind === 'language-provider-overlap' ? 'provider-overlap' : 'contribution-conflict', severity: value.kind === 'overlapping-keybinding' ? 'high' : 'medium', ...identity, extension_ids: extensionIds, resolution_targets: extensionIds, recommended_resolutions: ['inspect', 'disable-workspace', 'disable-global', 'uninstall'] });
  }
  for (const item of missing) {
    const identity = { kind: item.kind, resource: item.resource, owner: item.owner };
    signals.push({ signal_id: signalId(identity), category: 'dependency-conflict', severity: 'high', ...identity, extension_ids: [item.owner], resolution_targets: [item.resource], recommended_resolutions: ['install-target', 'inspect'] });
  }
  for (const item of reverse) {
    const identity = { kind: item.kind, resource: item.resource, owner: item.owner };
    signals.push({ signal_id: signalId(identity), category: 'consumer-impact', severity: 'info', ...identity, extension_ids: [item.resource, item.owner].sort(), resolution_targets: [item.owner], recommended_resolutions: ['inspect'] });
  }
  const exact = String(requestedId || '').trim().toLowerCase();
  const filtered = exact ? signals.filter(item => item.extension_ids.includes(exact) || item.resource === exact || item.owner === exact) : signals;
  const ordered = filtered.sort((left, right) => `${left.severity}:${left.kind}:${left.resource}:${left.signal_id}`.localeCompare(`${right.severity}:${right.kind}:${right.resource}:${right.signal_id}`));
  return {
    schema_version: 'px.extension-conflict-analysis/1.0', extension_id: exact || null,
    installed_extension_count: records.length, signal_count: ordered.length,
    signals: ordered.slice(0, 1000), truncated: ordered.length > 1000
  };
}

module.exports = { analyzeExtensionConflicts, signalId };
