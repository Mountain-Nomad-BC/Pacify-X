'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const STATE_SCHEMA = 'px.ms-enterprise.state/1.0';
const CACHE_REUSE_LEVELS = new Set(['off', 'conservative', 'balanced', 'aggressive']);

const DEFAULT_EXECUTION_POLICY = Object.freeze({
  master_enabled: false,
  max_cost_per_task_usd: 0,
  max_cost_per_session_usd: 0,
  max_cost_per_day_usd: 0,
  token_budget: 12000,
  local_first: true,
  provider_allowlist: [],
  gpu_memory_ceiling_mb: 0,
  cpu_core_ceiling: 4,
  ram_ceiling_mb: 8192,
  escalation_confidence_threshold: 0.85,
  cache_reuse_aggressiveness: 'balanced',
  require_approval_before_billable_execution: true
});

function now() { return new Date().toISOString(); }
function sha(value) { return crypto.createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex'); }
function enterpriseRoot(projectRoot) { return path.join(path.resolve(projectRoot), '.engineering-bootstrap', 'enterprise'); }
function pathsFor(projectRoot) {
  const root = enterpriseRoot(projectRoot);
  return { root, state: path.join(root, 'state.json'), events: path.join(root, 'events.jsonl'), evidence: path.join(root, 'evidence') };
}
function safeId(value, label = 'identifier') {
  const result = String(value || '').trim();
  if (!/^[a-z0-9][a-z0-9./_-]{0,159}$/i.test(result) || result.includes('..')) throw new Error(`Invalid enterprise ${label}.`);
  return result;
}
function safeAlias(value, label) {
  const result = String(value || '').trim();
  if (!result || result.length > 120 || /[\r\n\0]/.test(result)) throw new Error(`Invalid enterprise ${label}.`);
  return result;
}
function boundedNumber(value, label, minimum, maximum, integer = false) {
  const result = Number(value);
  if (!Number.isFinite(result) || result < minimum || result > maximum || (integer && !Number.isInteger(result))) throw new Error(`Invalid enterprise ${label}.`);
  return result;
}
function normalizeExecutionPolicy(input = {}) {
  const providerAllowlist = [...new Set((Array.isArray(input.provider_allowlist) ? input.provider_allowlist : []).map(item => safeId(item, 'provider id')))];
  const cacheReuse = String(input.cache_reuse_aggressiveness ?? DEFAULT_EXECUTION_POLICY.cache_reuse_aggressiveness);
  if (!CACHE_REUSE_LEVELS.has(cacheReuse)) throw new Error('Invalid enterprise cache reuse aggressiveness.');
  return {
    master_enabled: Boolean(input.master_enabled),
    max_cost_per_task_usd: boundedNumber(input.max_cost_per_task_usd ?? 0, 'task cost ceiling', 0, 1000000),
    max_cost_per_session_usd: boundedNumber(input.max_cost_per_session_usd ?? 0, 'session cost ceiling', 0, 1000000),
    max_cost_per_day_usd: boundedNumber(input.max_cost_per_day_usd ?? 0, 'daily cost ceiling', 0, 1000000),
    token_budget: boundedNumber(input.token_budget ?? DEFAULT_EXECUTION_POLICY.token_budget, 'token budget', 0, 1000000000, true),
    local_first: input.local_first !== false,
    provider_allowlist: providerAllowlist,
    gpu_memory_ceiling_mb: boundedNumber(input.gpu_memory_ceiling_mb ?? DEFAULT_EXECUTION_POLICY.gpu_memory_ceiling_mb, 'GPU memory ceiling', 0, 1048576, true),
    cpu_core_ceiling: boundedNumber(input.cpu_core_ceiling ?? DEFAULT_EXECUTION_POLICY.cpu_core_ceiling, 'CPU core ceiling', 1, 4096, true),
    ram_ceiling_mb: boundedNumber(input.ram_ceiling_mb ?? DEFAULT_EXECUTION_POLICY.ram_ceiling_mb, 'RAM ceiling', 128, 16777216, true),
    escalation_confidence_threshold: boundedNumber(input.escalation_confidence_threshold ?? DEFAULT_EXECUTION_POLICY.escalation_confidence_threshold, 'escalation confidence threshold', 0, 1),
    cache_reuse_aggressiveness: cacheReuse,
    require_approval_before_billable_execution: input.require_approval_before_billable_execution !== false
  };
}
function defaultState(catalog = {}) {
  const packStates = {};
  for (const pack of catalog.packs || []) packStates[pack.id] = { enabled: Boolean(pack.default_enabled), mode: 'offline-metadata-only', updated_utc: null };
  return {
    schema_version: STATE_SCHEMA, authority: 'Pacify-X local enterprise boundary', revision: 0,
    defaults: { network_egress: 'deny', mutation: 'deny', billable_services: 'disabled', credential_reads: 'deny' },
    execution_policy: normalizeExecutionPolicy(DEFAULT_EXECUTION_POLICY),
    pack_states: packStates, targets: [], connector_states: {}, last_doctor: null, created_utc: now(), updated_utc: now(), state_hash: null
  };
}
function seal(state) {
  const copy = { ...state, state_hash: null };
  return { ...copy, state_hash: sha(copy) };
}
function atomicWrite(target, value) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.${crypto.randomUUID()}.tmp`;
  try { fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' }); fs.renameSync(temporary, target); }
  finally { try { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); } catch {} }
}
function appendEvent(paths, operation, beforeHash, state, detail = {}) {
  const event = {
    schema_version: 'px.ms-enterprise.event/1.0', event_id: `ent-${crypto.randomUUID()}`, timestamp: now(),
    operation, authority: 'local', before_hash: beforeHash || null, after_hash: state.state_hash, detail
  };
  fs.mkdirSync(paths.root, { recursive: true });
  fs.appendFileSync(paths.events, `${JSON.stringify(event)}\n`, 'utf8');
  return event;
}
function loadEnterpriseState(projectRoot, catalog = {}) {
  const paths = pathsFor(projectRoot);
  let state;
  try { state = JSON.parse(fs.readFileSync(paths.state, 'utf8')); } catch { state = defaultState(catalog); }
  if (state.schema_version !== STATE_SCHEMA) throw new Error(`Unsupported enterprise state schema: ${state.schema_version}`);
  const expected = seal(state).state_hash;
  if (state.state_hash && state.state_hash !== expected) throw new Error('Enterprise state integrity check failed.');
  let migrated = false;
  if (!state.execution_policy) { state.execution_policy = normalizeExecutionPolicy(DEFAULT_EXECUTION_POLICY); migrated = true; }
  if (!state.pack_states) { state.pack_states = {}; migrated = true; }
  for (const pack of catalog.packs || []) if (!state.pack_states[pack.id]) { state.pack_states[pack.id] = { enabled: Boolean(pack.default_enabled), mode: 'offline-metadata-only', updated_utc: null }; migrated = true; }
  return { paths, state: state.state_hash && !migrated ? state : seal(state), migrated };
}
function initializeEnterprise(projectRoot, catalog = {}) {
  const loaded = loadEnterpriseState(projectRoot, catalog);
  if (!fs.existsSync(loaded.paths.state) || loaded.migrated) atomicWrite(loaded.paths.state, loaded.state);
  return loaded;
}
function mutate(projectRoot, catalog, operation, detail, update) {
  const loaded = initializeEnterprise(projectRoot, catalog);
  const before = loaded.state.state_hash;
  const next = JSON.parse(JSON.stringify(loaded.state));
  update(next);
  next.revision += 1; next.updated_utc = now();
  const sealed = seal(next); atomicWrite(loaded.paths.state, sealed);
  const event = appendEvent(loaded.paths, operation, before, sealed, detail);
  return { paths: loaded.paths, state: sealed, event };
}
function setPackEnabled(projectRoot, catalog, input) {
  const packId = safeId(input.packId, 'pack id');
  const pack = (catalog.packs || []).find(item => item.id === packId);
  if (!pack) throw new Error('Unknown enterprise pack.');
  const enabled = Boolean(input.enabled);
  return mutate(projectRoot, catalog, 'enterprise-pack-state', { pack_id: packId, enabled, mode: 'offline-metadata-only' }, state => {
    state.pack_states[packId] = { enabled, mode: 'offline-metadata-only', updated_utc: now() };
  });
}
function configureTarget(projectRoot, catalog, input) {
  const target = {
    id: safeId(input.id || `target-${crypto.randomUUID()}`, 'target id'),
    pack_id: safeId(input.packId, 'pack id'), target_alias: safeAlias(input.targetAlias, 'target alias'),
    tenant_alias: safeAlias(input.tenantAlias, 'tenant alias'), environment_alias: safeAlias(input.environmentAlias, 'environment alias'),
    auth_namespace: safeAlias(input.authNamespace || 'external-secret-store', 'auth namespace'),
    billing_namespace: safeAlias(input.billingNamespace || 'explicit-enterprise-account', 'billing namespace'),
    network_egress: 'deny', mutation: 'deny', credential_material_stored: false, status: 'configured-offline', updated_utc: now()
  };
  if (!(catalog.packs || []).some(item => item.id === target.pack_id)) throw new Error('Unknown enterprise pack.');
  return mutate(projectRoot, catalog, 'enterprise-target-configured', { target_id: target.id, pack_id: target.pack_id }, state => {
    const index = state.targets.findIndex(item => item.id === target.id);
    if (index >= 0) state.targets[index] = target; else state.targets.push(target);
  });
}
function setExecutionPolicy(projectRoot, catalog, input) {
  const policy = normalizeExecutionPolicy(input);
  const loaded = initializeEnterprise(projectRoot, catalog);
  if (JSON.stringify(loaded.state.execution_policy) === JSON.stringify(policy)) return { ...loaded, event: null, unchanged: true };
  return mutate(projectRoot, catalog, 'enterprise-execution-policy', {
    master_enabled: policy.master_enabled,
    local_first: policy.local_first,
    provider_count: policy.provider_allowlist.length,
    require_approval: policy.require_approval_before_billable_execution
  }, state => { state.execution_policy = policy; });
}
function evaluateBillableExecution(policyInput, request = {}) {
  const policy = normalizeExecutionPolicy(policyInput);
  const provider = String(request.provider || '').trim();
  const expectedCost = boundedNumber(request.expected_cost_usd ?? 0, 'expected cost', 0, 1000000);
  const reasons = [];
  if (!policy.master_enabled) reasons.push('billable-master-disabled');
  if (!provider || !policy.provider_allowlist.includes(provider)) reasons.push('provider-not-allowlisted');
  if (policy.max_cost_per_task_usd <= 0 || expectedCost > policy.max_cost_per_task_usd) reasons.push('task-cost-cap');
  if (policy.max_cost_per_session_usd <= 0 || Number(request.session_spend_usd || 0) + expectedCost > policy.max_cost_per_session_usd) reasons.push('session-cost-cap');
  if (policy.max_cost_per_day_usd <= 0 || Number(request.day_spend_usd || 0) + expectedCost > policy.max_cost_per_day_usd) reasons.push('daily-cost-cap');
  if (boundedNumber(request.tokens ?? 0, 'requested tokens', 0, 1000000000, true) > policy.token_budget) reasons.push('token-budget');
  if (policy.local_first && request.local_available === true && request.route !== 'local') reasons.push('local-route-available');
  if (boundedNumber(request.gpu_memory_mb ?? 0, 'requested GPU memory', 0, 1048576, true) > policy.gpu_memory_ceiling_mb) reasons.push('gpu-ceiling');
  if (boundedNumber(request.cpu_cores ?? 1, 'requested CPU cores', 1, 4096, true) > policy.cpu_core_ceiling) reasons.push('cpu-ceiling');
  if (boundedNumber(request.ram_mb ?? 128, 'requested RAM', 128, 16777216, true) > policy.ram_ceiling_mb) reasons.push('ram-ceiling');
  if (boundedNumber(request.escalation_confidence ?? 0, 'escalation confidence', 0, 1) < policy.escalation_confidence_threshold) reasons.push('confidence-threshold');
  if (policy.require_approval_before_billable_execution && request.approval_granted !== true) reasons.push('explicit-approval-required');
  return { allowed: reasons.length === 0, reasons, provider, expected_cost_usd: expectedCost, policy };
}
function enterpriseDoctor(projectRoot, catalog = {}) {
  const loaded = initializeEnterprise(projectRoot, catalog);
  const checks = [
    { id: 'separate-schema', passed: loaded.state.schema_version === STATE_SCHEMA, detail: loaded.state.schema_version },
    { id: 'separate-state-root', passed: loaded.paths.root.endsWith(path.join('.engineering-bootstrap', 'enterprise')), detail: loaded.paths.root },
    { id: 'offline-startup', passed: catalog.defaults?.offline_startup_required === true, detail: 'enterprise services are not startup dependencies' },
    { id: 'billable-default', passed: catalog.defaults?.billable_services === 'disabled' && loaded.state.defaults.billable_services === 'disabled', detail: 'disabled' },
    { id: 'egress-default', passed: catalog.defaults?.network_egress === 'deny' && loaded.state.defaults.network_egress === 'deny', detail: 'deny' },
    { id: 'mutation-default', passed: catalog.defaults?.mutation === 'deny' && loaded.state.defaults.mutation === 'deny', detail: 'deny' },
    { id: 'credential-load', passed: catalog.defaults?.credential_reads_on_load === false, detail: 'no credential reads on load' },
    { id: 'guardrail-policy', passed: JSON.stringify(normalizeExecutionPolicy(loaded.state.execution_policy)) === JSON.stringify(loaded.state.execution_policy) && loaded.state.execution_policy?.require_approval_before_billable_execution === true, detail: `${loaded.state.execution_policy?.master_enabled ? 'master enabled' : 'master off'}; approval required` },
    { id: 'connector-defaults', passed: (catalog.connectors || []).every(item => ['disabled', 'not-installed'].includes(item.status)), detail: `${(catalog.connectors || []).length} connectors disabled or absent` },
    { id: 'identity-separation', passed: (catalog.models || []).every(item => item.billing_identity && item.auth_identity), detail: 'authentication and billing namespaces explicit' },
    { id: 'memory-boundary', passed: catalog.separation?.canonical_memory_import === 'explicit-reviewed-promotion-only', detail: catalog.separation?.canonical_memory_import }
  ];
  const report = { schema_version: 'px.ms-enterprise.doctor/1.0', generated_utc: now(), valid: checks.every(item => item.passed), local_control_plane_ready: true, cloud_connectors_ready: false, checks };
  const result = mutate(projectRoot, catalog, 'enterprise-readiness-doctor', { valid: report.valid }, state => { state.last_doctor = report; });
  fs.mkdirSync(result.paths.evidence, { recursive: true });
  const receipt = { ...report, state_hash: result.state.state_hash, receipt_sha256: null };
  receipt.receipt_sha256 = sha(receipt);
  atomicWrite(path.join(result.paths.evidence, `readiness-${Date.now()}.json`), receipt);
  return { ...result, report, receipt };
}

module.exports = {
  STATE_SCHEMA, DEFAULT_EXECUTION_POLICY, enterpriseRoot, pathsFor, defaultState, normalizeExecutionPolicy,
  loadEnterpriseState, initializeEnterprise, setPackEnabled, configureTarget, setExecutionPolicy,
  evaluateBillableExecution, enterpriseDoctor
};
