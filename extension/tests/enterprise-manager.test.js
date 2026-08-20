'use strict';

const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const test = require('node:test');
const { initializeEnterprise, setPackEnabled, configureTarget, setExecutionPolicy, evaluateBillableExecution, enterpriseDoctor } = require('../src/enterpriseManager');

const catalog = {
  separation: { canonical_memory_import: 'explicit-reviewed-promotion-only' },
  defaults: { offline_startup_required: true, billable_services: 'disabled', network_egress: 'deny', mutation: 'deny', credential_reads_on_load: false },
  packs: [{ id: 'ms-enterprise/governance', default_enabled: true }, { id: 'ms-enterprise/azure-foundry', default_enabled: false }],
  connectors: [{ id: 'azure', status: 'disabled' }], models: [{ id: 'local', auth_identity: 'local', billing_identity: 'none' }]
};
function fixture() { return fs.mkdtempSync(path.join(os.tmpdir(), 'px-enterprise-')); }

test('enterprise inspection can remain memory-only without initialization writes', () => {
  const root = fixture();
  const result = initializeEnterprise(root, catalog, { persist: false });
  assert.equal(result.state.execution_policy.master_enabled, false);
  assert.equal(fs.existsSync(path.join(root, '.engineering-bootstrap')), false);
  fs.rmSync(root, { recursive: true, force: true });
});

test('enterprise state is stored below a separate project namespace', () => {
  const root = fixture(); const result = initializeEnterprise(root, catalog);
  assert.match(result.paths.state, /\.engineering-bootstrap[\\/]enterprise[\\/]state\.json$/);
  assert.equal(result.state.defaults.billable_services, 'disabled');
  assert.equal(result.state.execution_policy.master_enabled, false);
  assert.equal(result.state.execution_policy.require_approval_before_billable_execution, true);
  assert.equal(result.state.pack_states['ms-enterprise/azure-foundry'].enabled, false);
});

test('pack control changes offline metadata only and retains a hash-linked event', () => {
  const root = fixture(); const result = setPackEnabled(root, catalog, { packId: 'ms-enterprise/azure-foundry', enabled: true });
  assert.equal(result.state.pack_states['ms-enterprise/azure-foundry'].mode, 'offline-metadata-only');
  assert.equal(result.event.operation, 'enterprise-pack-state');
  assert.equal(result.event.after_hash, result.state.state_hash);
});

test('target records keep aliases and namespaces but never credential material', () => {
  const root = fixture(); const result = configureTarget(root, catalog, {
    id: 'azure-dev', packId: 'ms-enterprise/azure-foundry', targetAlias: 'Azure development', tenantAlias: 'tenant-dev', environmentAlias: 'subscription-sandbox'
  });
  assert.equal(result.state.targets[0].credential_material_stored, false);
  assert.equal(result.state.targets[0].network_egress, 'deny');
  assert.equal(result.state.targets[0].mutation, 'deny');
});

test('doctor proves local readiness while cloud connectors remain unavailable', () => {
  const root = fixture(); const result = enterpriseDoctor(root, catalog);
  assert.equal(result.report.valid, true);
  assert.equal(result.report.local_control_plane_ready, true);
  assert.equal(result.report.cloud_connectors_ready, false);
  assert.equal(result.report.checks.length, 11);
  assert.equal(fs.readdirSync(result.paths.evidence).length, 1);
});

test('billable policy remains separately stored and every configured guardrail is enforced', () => {
  const root = fixture();
  const saved = setExecutionPolicy(root, catalog, {
    master_enabled: true, max_cost_per_task_usd: 1, max_cost_per_session_usd: 2, max_cost_per_day_usd: 3,
    token_budget: 1000, local_first: true, provider_allowlist: ['provider.test'], gpu_memory_ceiling_mb: 1024,
    cpu_core_ceiling: 4, ram_ceiling_mb: 2048, escalation_confidence_threshold: 0.9,
    cache_reuse_aggressiveness: 'aggressive', require_approval_before_billable_execution: true
  });
  assert.equal(saved.state.execution_policy.master_enabled, true);
  assert.equal(saved.state.defaults.billable_services, 'disabled');
  const allowed = evaluateBillableExecution(saved.state.execution_policy, {
    provider: 'provider.test', expected_cost_usd: 0.5, session_spend_usd: 0.5, day_spend_usd: 1,
    tokens: 900, local_available: false, route: 'provider', gpu_memory_mb: 512, cpu_cores: 2, ram_mb: 1024,
    escalation_confidence: 0.95, approval_granted: true
  });
  assert.equal(allowed.allowed, true);
  const blocked = evaluateBillableExecution(saved.state.execution_policy, {
    provider: 'provider.denied', expected_cost_usd: 4, tokens: 2000, local_available: true, route: 'provider',
    gpu_memory_mb: 2048, cpu_cores: 8, ram_mb: 4096, escalation_confidence: 0.2, approval_granted: false
  });
  for (const reason of ['provider-not-allowlisted', 'task-cost-cap', 'token-budget', 'local-route-available', 'gpu-ceiling', 'cpu-ceiling', 'ram-ceiling', 'confidence-threshold', 'explicit-approval-required']) assert.ok(blocked.reasons.includes(reason), reason);
});
