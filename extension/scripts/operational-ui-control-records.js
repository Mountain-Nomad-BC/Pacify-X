'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { build: buildUiActionManifest } = require('./build-ui-action-inventory');

const CHAIN_STAGES = Object.freeze([
  'open_load',
  'display',
  'user_edit_action',
  'input_validation',
  'authorization',
  'backend_dispatch',
  'runtime_effect',
  'progress_reporting',
  'result_acknowledgement',
  'persistence',
  'reload_reopen',
  'failure_handling',
  'recovery_rollback'
]);

const LIVE_WALK_AUTHORITY = 'live installed VS Code host; read-only observation and reversible unsaved UI interaction only';

function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function sourcePath(reference) {
  return String(reference || '').split(':', 1)[0];
}

function controlLocator(control) {
  const [action, ...variants] = String(control.label || '').split('.');
  if (control.kind === 'action' && action === 'navigate') {
    return { type: 'css', selector: '[data-surface]', instance_key: { attribute: 'data-surface', values: variants } };
  }
  if (control.kind === 'action') {
    return {
      type: 'css',
      selector: `[data-action="${action}"]`,
      instance_key: variants.length ? { type: 'dataset-identity', values: variants } : null
    };
  }
  if (control.kind === 'command') {
    return { type: 'vscode-command', selector: null, instance_key: String(control.label) };
  }
  return { type: 'semantic-control', selector: null, instance_key: String(control.control_id) };
}

function controlContract(control, actionContracts) {
  const [action] = String(control.label || '').split('.');
  if (control.kind === 'action' && action === 'navigate') {
    return {
      mode: 'ui-only', message_type: null, fields: [], effect: 'none-outside-webview',
      authority: 'webview presentation state', acknowledgement: 'active surface and focus update', receipt: null
    };
  }
  if (control.kind === 'action' && actionContracts[action]) {
    const contract = actionContracts[action];
    return {
      mode: contract.mode,
      message_type: contract.inbound_schema?.type || null,
      fields: [...(contract.inbound_schema?.fields || [])],
      effect: contract.effect,
      authority: contract.authority,
      acknowledgement: contract.acknowledgement,
      receipt: contract.receipt
    };
  }
  if (control.kind === 'command') {
    return {
      mode: 'host-command', message_type: String(control.label), fields: [], effect: 'host-ui-or-declared-command-effect',
      authority: 'VS Code command authority', acknowledgement: 'VS Code command completion or surfaced error', receipt: 'host acknowledgement'
    };
  }
  return {
    mode: 'source-owned-semantic', message_type: null, fields: [], effect: mutationEffect(control) || 'observation or local presentation state',
    authority: 'owning source module', acknowledgement: 'typed control observation', receipt: null
  };
}

function buildCurrentSourceControlManifest(inventoryPath) {
  const resolved = path.resolve(inventoryPath);
  const repositoryRoot = path.resolve(__dirname, '..', '..');
  const canonicalInventoryPath = path.join(repositoryRoot, 'registry', 'operational_surface_inventory.json');
  if (resolved !== canonicalInventoryPath) {
    throw new Error('The current-source control manifest requires the canonical operational surface inventory.');
  }
  const inventoryBytes = fs.readFileSync(resolved);
  const inventory = JSON.parse(inventoryBytes.toString('utf8'));
  if (inventory.schema_version !== 'px.operational-surface-inventory/2.0') {
    throw new Error(`Unsupported operational surface inventory schema: ${inventory.schema_version || 'missing'}`);
  }
  if (!inventory.inventory_id || !Array.isArray(inventory.surfaces) || !inventory.surfaces.length) {
    throw new Error('Operational surface inventory must declare an identity and at least one surface.');
  }
  const actionManifest = buildUiActionManifest();
  const actionContracts = Object.fromEntries(actionManifest.actions.map(item => [item.action, item]));
  const controls = [];
  const surfaces = [];
  const controlIds = new Set();
  const surfaceIds = new Set();
  for (const surface of inventory.surfaces) {
    if (!surface?.surface_id || surfaceIds.has(surface.surface_id)) throw new Error(`Invalid or duplicate surface_id: ${surface?.surface_id}`);
    surfaceIds.add(surface.surface_id);
    if (!Array.isArray(surface.controls) || surface.controls.length !== surface.expected_control_count) {
      throw new Error(`Control denominator mismatch for ${surface.surface_id}`);
    }
    const ids = surface.controls.map(control => String(control?.control_id || ''));
    if (sha256(Buffer.from(JSON.stringify(ids))) !== surface.expected_controls_sha256) {
      throw new Error(`Control identity hash mismatch for ${surface.surface_id}`);
    }
    const surfaceControls = [];
    for (const control of surface.controls) {
      if (!control?.control_id || controlIds.has(control.control_id)) throw new Error(`Invalid or duplicate control_id: ${control?.control_id}`);
      controlIds.add(control.control_id);
      const refs = [...(control.source_refs || [])];
      if (!refs.length) throw new Error(`Control has no current-source identity: ${control.control_id}`);
      const sourceFiles = [...new Set(refs.map(sourcePath))].sort().map(relative => {
        const absolute = path.resolve(repositoryRoot, relative);
        const boundary = path.relative(repositoryRoot, absolute);
        if (!relative || boundary.startsWith('..') || path.isAbsolute(boundary) || !fs.existsSync(absolute) || !fs.statSync(absolute).isFile()) {
          throw new Error(`Control source is outside the repository or missing: ${control.control_id}:${relative}`);
        }
        return { path: relative.replaceAll('\\', '/'), source_sha256: sha256(fs.readFileSync(absolute)) };
      });
      const contract = controlContract(control, actionContracts);
      const record = {
        control_id: control.control_id,
        surface_id: surface.surface_id,
        kind: control.kind,
        label: control.label,
        route: { surface_id: surface.surface_id, prerequisites: ['dashboard-connected', `surface:${surface.surface_id}`] },
        locator: controlLocator(control),
        source_identity: { refs, symbols: [String(control.label)], files: sourceFiles },
        interaction: { profiles: interactionProfiles({ ...control, interaction_profiles: surface.interaction_profiles }), effect: contract.effect },
        outbound_contract: contract,
        handler: {
          webview: refs,
          host: contract.mode === 'host' || contract.mode === 'host-command' ? `extension/src/extension.js#${contract.message_type}` : null,
          backend: contract.authority
        },
        lifecycle: { state: 'current', retirement_predecessor: null }
      };
      controls.push(record);
      surfaceControls.push(record.control_id);
    }
    surfaces.push({
      surface_id: surface.surface_id,
      name: surface.name,
      source_files: [...surface.source_files],
      interaction_profiles: [...(surface.interaction_profiles || [])],
      control_ids: surfaceControls
    });
  }
  if (!controls.length) throw new Error('Operational surface inventory contains no controls.');
  const manifest = {
    schema_version: 'px.current-source-control-manifest/1.0',
    manifest_id: `pacify-x-current-source-controls/${inventory.inventory_id}`,
    authority: 'Current repository source identity and declared host contracts; Codex retains host execution authority.',
    source_inventory: {
      path: path.relative(repositoryRoot, resolved).replaceAll('\\', '/'),
      schema_version: inventory.schema_version,
      inventory_id: inventory.inventory_id,
      source_sha256: sha256(inventoryBytes)
    },
    action_contracts: {
      schema_version: actionManifest.schema_version,
      action_count: actionManifest.action_count,
      source_sha256: sha256(Buffer.from(canonical(actionManifest)))
    },
    surfaces,
    controls: controls.sort((left, right) => left.control_id.localeCompare(right.control_id))
  };
  return { ...manifest, manifest_sha256: sha256(Buffer.from(canonical(manifest))) };
}

function loadOperationalSurfaceInventory(inventoryPath) {
  const resolved = path.resolve(inventoryPath);
  const manifest = buildCurrentSourceControlManifest(resolved);
  return {
    path: resolved,
    sha256: manifest.manifest_sha256,
    schema_version: manifest.schema_version,
    inventory_id: manifest.manifest_id,
    surface_count: manifest.surfaces.length,
    control_count: manifest.controls.length,
    source_inventory: manifest.source_inventory,
    manifest,
    controls: manifest.controls.map(control => ({
      ...control,
      source_refs: [...control.source_identity.refs],
      interaction_profiles: [...control.interaction.profiles]
    }))
  };
}

function canonicalSurfaceId(value) {
  return String(value || '')
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .replace(/_/g, '-')
    .toLowerCase();
}

function interactionProfiles(control) {
  if (Array.isArray(control.interaction_profiles) && control.interaction_profiles.length) return [...control.interaction_profiles];
  const label = String(control.label || '').toLowerCase();
  if (control.kind === 'lifecycle' || /(^|\.)(run|start|pause|resume|cancel|stop|reconcile)(\.|$)/.test(label)) return ['durable_run'];
  if (isPotentiallyMutating(control)) return ['write_operation'];
  if (/^(open|copy|reveal|commandcenter|navigate)/.test(label) || control.kind === 'command') return ['host_ui'];
  if (/refresh|inspect|query|search|load|retry/.test(label) || control.kind === 'failure_recovery') return ['read_query'];
  return ['local_view'];
}

function mutationEffect(control) {
  const label = String(control.label || '').toLowerCase();
  if (['persistence', 'reload_reopen', 'failure_recovery', 'lifecycle'].includes(control.kind)) {
    return `${control.kind} may change or reconstruct authoritative/durable state`;
  }
  if (['field', 'form', 'editor', 'gesture', 'menu'].includes(control.kind)) {
    return `${control.kind} may mutate UI draft state and can dispatch an authoritative effect depending on its owning form`;
  }
  if (/delete|remove|uninstall|cleanup|cancel|stop|rollback|release|reconcile/.test(label)) return 'may remove, stop, reconcile, roll back, or otherwise destructively change durable state';
  if (/save|submit|create|update|install|enable|disable|admit|promote|approve|register|capture|write|config|binding|grant|add/.test(label)) return 'may create or change workspace, configuration, catalog, authority, or installed state';
  if (/run|start|resume|pause|test|validate|execute|dispatch/.test(label)) return 'may execute work, consume approval, or change a durable run lifecycle';
  return null;
}

function isPotentiallyMutating(control) {
  return mutationEffect(control) !== null;
}

function runtimeActionIndex(results, sidebar) {
  const index = new Map();
  const add = (surface, action) => {
    const canonical = canonicalSurfaceId(surface);
    if (!canonical || !action?.action) return;
    const key = `${canonical}\u0000${action.action}`;
    if (!index.has(key)) index.set(key, []);
    index.get(key).push(action);
  };
  for (const result of results || []) for (const action of result.visible_actions || []) add(result.surface, action);
  for (const button of sidebar?.buttons || []) add('sidebar', button);
  return index;
}

function actionResolver(control, actionIndex) {
  if (!['action', 'command'].includes(control.kind)) return { status: 'not_resolved', matches: [] };
  const [action, ...variants] = String(control.label || '').split('.');
  const matches = actionIndex.get(`${control.surface_id}\u0000${action}`) || [];
  if (!matches.length) return { status: 'not_rendered', matches: [] };
  if (!variants.length && matches.length === 1) return { status: 'exact', matches };
  const exact = matches.filter(match => {
    const dataset = match.dataset || {};
    const values = new Set(Object.values(dataset).map(value => String(value)));
    return variants.every(variant => variant === 'row' ? Object.keys(dataset).some(key => /id|index|row|key/.test(key)) : values.has(variant));
  });
  return exact.length === 1 ? { status: 'exact', matches: exact } : { status: 'ambiguous', matches };
}

function stageRecords({ blocked, rendered, mutating, attempted, observedAt }) {
  return CHAIN_STAGES.map((stage, index) => {
    if (blocked) return { stage, status: 'blocked', observed_at: observedAt, reason: 'installed host assets differ from the source inventory authority' };
    if (rendered && index < 2) return { stage, status: 'observed', observed_at: observedAt, evidence: 'exact rendered-control resolver match in the live host DOM' };
    if (attempted && stage === 'user_edit_action') return { stage, status: 'observed', observed_at: observedAt, evidence: 'the walker invoked this exact stable control ID' };
    if (mutating && index >= 2) return { stage, status: 'skipped_requires_authority', observed_at: observedAt, reason: 'the current walk has no authority for this control effect' };
    return { stage, status: rendered ? 'not_attempted' : 'not_observed', observed_at: observedAt, reason: rendered ? 'presence alone is not a complete interaction chain' : 'no exact rendered-control resolver match was observed' };
  });
}

function buildPerControlRecords({ inventory, results = [], sidebar = null, hostSourceMismatch = false, authority = LIVE_WALK_AUTHORITY, observedAt = new Date().toISOString(), attemptedControlIds = [] }) {
  const actionIndex = runtimeActionIndex(results, sidebar);
  const attemptedIds = new Set(attemptedControlIds);
  for (const controlId of attemptedIds) {
    if (!inventory.controls.some(control => control.control_id === controlId)) throw new Error(`Walker attempted an unregistered control: ${controlId}`);
  }
  const records = inventory.controls.map(control => {
    const resolver = actionResolver(control, actionIndex);
    const attempted = attemptedIds.has(control.control_id);
    const rendered = resolver.status === 'exact' || attempted;
    const mutating = isPotentiallyMutating(control);
    const effect = mutationEffect(control);
    const terminalDisposition = hostSourceMismatch
      ? 'blocked_host_source_mismatch'
      : attempted
        ? 'observed_only'
      : mutating
        ? 'skipped_requires_authority'
        : rendered
          ? 'observed_only'
          : 'not_rendered';
    const record = {
      control_id: control.control_id,
      surface_id: control.surface_id,
      kind: control.kind,
      label: control.label,
      source_refs: control.source_refs || [],
      interaction_profiles: interactionProfiles(control),
      resolver: {
        type: ['action', 'command'].includes(control.kind) ? 'surface_action_and_variant' : 'inventory_only_no_runtime_selector',
        status: resolver.status,
        match_count: resolver.matches.length
      },
      rendered,
      visible: rendered,
      enabled: rendered && resolver.matches.every(match => match.disabled !== true),
      attempted,
      observed_at: observedAt,
      potentially_mutating: mutating,
      terminal_disposition: terminalDisposition,
      authority,
      declared_effects: effect ? [effect] : ['observation or bounded local-view effect only; no authoritative effect was attempted'],
      observed_effects: [],
      before_state_sha256: null,
      after_state_sha256: null,
      screenshot_references: [],
      stages: stageRecords({ blocked: hostSourceMismatch, rendered, mutating, attempted, observedAt }),
      errors: []
    };
    if (hostSourceMismatch) {
      record.reason = 'The installed VS Code host asset identity does not match the source identity that supplied this control inventory; interaction evidence would apply to the wrong implementation.';
      record.return_condition = 'Install and reload the exact source asset identity, verify the host/source identity receipt matches, then rerun this control under its profile-specific authority and evidence boundary.';
    } else if (mutating) {
      record.reason = effect;
      record.return_condition = 'Provide explicit authority for this exact effect in an isolated disposable target, capture current pre-state digests, register rollback/recovery, and require a typed acknowledgement plus unchanged-or-expected post-state digest.';
    }
    return record;
  }).sort((left, right) => left.control_id.localeCompare(right.control_id));

  const ids = new Set(records.map(record => record.control_id));
  if (records.length !== inventory.control_count || ids.size !== inventory.control_count) {
    throw new Error(`Per-control record reconciliation failed: ${records.length} records / ${ids.size} unique / ${inventory.control_count} expected`);
  }
  const terminalCounts = {};
  for (const record of records) terminalCounts[record.terminal_disposition] = (terminalCounts[record.terminal_disposition] || 0) + 1;
  return {
    schema_version: 'px.operational-ui-control-chain/1.0',
    chain_stages: [...CHAIN_STAGES],
    authority,
    host_source_mismatch: hostSourceMismatch,
    inventory: {
      path: inventory.path,
      sha256: inventory.sha256,
      schema_version: inventory.schema_version,
      inventory_id: inventory.inventory_id,
      surface_count: inventory.surface_count,
      control_count: inventory.control_count
    },
    aggregates: {
      control_count: records.length,
      unique_control_ids: ids.size,
      terminal_dispositions: terminalCounts,
      potentially_mutating: records.filter(record => record.potentially_mutating).length,
      complete_interaction_chains: 0
    },
    controls: records
  };
}

module.exports = {
  CHAIN_STAGES,
  LIVE_WALK_AUTHORITY,
  buildCurrentSourceControlManifest,
  buildPerControlRecords,
  canonicalSurfaceId,
  isPotentiallyMutating,
  loadOperationalSurfaceInventory,
  mutationEffect
};
