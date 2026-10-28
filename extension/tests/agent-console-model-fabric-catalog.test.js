'use strict';
// Focused causal tests for PX-GAP-0001: the Agent Console model selection must be a
// projection of PX's canonical model fabric, not a hardcoded literal, and Auto must
// delegate to the governed router over that same admitted set.
const test = require('node:test');
const assert = require('node:assert/strict');

const { projectFabricCatalog, projectFabricModel } = require('../src/agentHarness/registerAgentConsole');
const { WorkerDescriptor, parse } = require('../src/agentHarness/contracts');
const { chooseWorker } = require('../src/agentHarness/router');
const { buildAgentConsoleProjection } = require('../src/agentHarness/agentConsoleProjection');
const { MESSAGE_VERSION, validateInbound } = require('../src/agentHarness/agentConsoleMessages');

const SHA = 'a'.repeat(64);

// A canonical `runtime.vscode_model_bridge list` answer: two lanes, one unavailable.
function fabricList(overrides = {}) {
  return {
    schema_version: 'px.vscode-model-list/1.0',
    authority_granted: false,
    models: [
      { profile_id: 'control-qwen35-4b-cpu-q6', model_id: 'qwen35-4b-operator', lane: 'control', context_tokens: 8192, max_output_tokens: 2048, session_id: 'local-model-session-1', adapter_id: 'llama-cpp-stream', tool_calling: true, image_input: false, model_sha256: SHA },
      { profile_id: 'deep-qwen3-30b-a3b-hybrid', model_id: 'qwen3-30b-a3b-deep', lane: 'deep', context_tokens: 32768, max_output_tokens: 4096, session_id: 'local-model-session-1', adapter_id: 'llama-cpp-stream', tool_calling: true, image_input: false, model_sha256: 'b'.repeat(64) },
      { profile_id: 'balanced-warm-lane', model_id: 'warm-balanced', lane: 'balanced', context_tokens: 4096, max_output_tokens: 1024, session_id: 'local-model-session-1', adapter_id: 'llama-cpp-stream', tool_calling: false, image_input: false, model_sha256: 'c'.repeat(64), available: false, unavailable_reason: 'profile-not-loaded' },
      ...(overrides.models || [])
    ]
  };
}

test('model catalog is derived from the canonical fabric, including every bridged lane', () => {
  const workers = projectFabricCatalog(fabricList());
  assert.equal(workers.length, 3, 'every certified, loaded lane must be selectable, not a fixed two-entry list');
  assert.deepEqual(workers.map(w => w.bridge.lane).sort(), ['balanced', 'control', 'deep']);
  // A lane PX reports as unavailable is still projected, not silently dropped.
  const warm = workers.find(w => w.bridge.lane === 'balanced');
  assert.equal(warm.enabled, false);
  assert.equal(warm.bridge.available, false);
  assert.equal(warm.bridge.unavailableReason, 'profile-not-loaded');
});

test('projected bridge identity survives the strict worker contract and reaches the operator', () => {
  const [control] = projectFabricCatalog(fabricList()).filter(w => w.bridge.lane === 'control');
  const parsed = parse(WorkerDescriptor, control, 'worker-descriptor');
  assert.equal(parsed.bridge.lane, 'control');
  assert.equal(parsed.bridge.sessionId, 'local-model-session-1');
  assert.equal(parsed.bridge.adapterId, 'llama-cpp-stream');
  assert.equal(parsed.bridge.modelSha256, SHA);
  assert.equal(parsed.bridge.contextTokens, 8192);
  // Bridge identity is display projection only and must grant no extra authority.
  assert.equal(parsed.capabilities.toolUse, false);
  assert.equal(parsed.supportedEffectClass, 'READ_ONLY');
});

test('a lane with no known mapping is still projected rather than dropped', () => {
  const worker = projectFabricModel({ profile_id: 'exotic-lane', model_id: 'exotic', lane: 'experimental', context_tokens: 2048, model_sha256: SHA });
  assert.ok(worker, 'an unmapped lane must not disappear from the catalog');
  assert.equal(worker.bridge.lane, 'experimental');
  assert.equal(worker.contextLimit, 2048);
});

test('malformed or duplicate fabric rows cannot poison or duplicate the catalog', () => {
  const workers = projectFabricCatalog({
    models: [
      { profile_id: 'control-x', model_id: 'a', lane: 'control', model_sha256: SHA },
      { profile_id: 'control-x', model_id: 'a', lane: 'control', model_sha256: SHA },
      { model_id: 'no-profile', lane: 'control' },
      null, 'nonsense', { profile_id: 'ok', model_id: 'b', lane: 'deep', model_sha256: SHA }
    ]
  });
  // Deduplicated by workerId, malformed rows dropped, and ordered deterministically.
  assert.deepEqual(workers.map(w => w.workerId), ['px-fabric-control-x', 'px-fabric-ok']);
});

test('Auto routing selects over the full admitted fabric, not a closed literal', () => {
  const workers = projectFabricCatalog(fabricList()).map(w => parse(WorkerDescriptor, w, 'worker-descriptor'));
  const registry = {
    list: () => workers,
    getHealth: () => ({ status: 'healthy' })
  };
  const budgetLedger = { canAdmit: () => ({ allowed: true }) };
  const task = { mode: 'IMPLEMENT', constraints: { maxEffectClass: 'READ_ONLY', localFirst: true } };

  // The deep lane is the strongest fit for IMPLEMENT and is only present because the
  // catalog came from the fabric.
  const auto = chooseWorker(registry, { task, contextTokens: 100, budgetLedger, requestedWorkerId: 'auto' });
  assert.ok(auto.selected, 'auto must select an admitted worker');
  assert.equal(auto.reason, 'highest-admitted-score');
  assert.equal(auto.evaluated.length, 3, 'auto must evaluate every admitted model');

  // Auto must not select a model PX reports as unavailable.
  const code = chooseWorker(registry, { task, contextTokens: 100, budgetLedger, requestedWorkerId: 'px-fabric-balanced-warm-lane' });
  assert.equal(code.selected, null);
  assert.match(code.reason, /requested-worker-rejected:.*disabled/);
});

test('the console projection carries catalog provenance for the operator', () => {
  const state = {
    workers: projectFabricCatalog(fabricList()).map(w => ({ ...w, health: { status: 'healthy' } })),
    activeTask: null, activeRun: null, librarian: null, context: null, route: null, budget: {}, evidence: [], events: []
  };
  const projected = buildAgentConsoleProjection(state, {
    modelCatalog: { state: 'current', detail: '3 certified, loaded models projected.', source: 'model-fabric', updatedAt: '2026-10-01T00:00:00Z' }
  });
  assert.equal(projected.modelCatalog.source, 'model-fabric');
  assert.equal(projected.workers.length, 3);
  assert.equal(projected.workers.find(w => w.bridge.lane === 'deep').bridge.contextTokens, 32768);
});

test('catalog refresh is an admitted host message and stays contract-bounded', () => {
  assert.equal(validateInbound({ schemaVersion: MESSAGE_VERSION, type: 'refreshModels' }).type, 'refreshModels');
  assert.throws(() => validateInbound({ schemaVersion: MESSAGE_VERSION, type: 'refreshModels', extra: true }), /invalid/);
});

test('the console no longer depends on a hardcoded model literal for its catalog', () => {
  const fs = require('node:fs');
  const path = require('node:path');
  const registerSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'agentHarness', 'registerAgentConsole.js'), 'utf8');
  const viewSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'agentHarness', 'agentConsoleView.js'), 'utf8');
  assert.ok(registerSource.includes('projectFabricCatalog'), 'the console must project the canonical catalog');
  assert.ok(registerSource.includes('refreshModelCatalog'), 'the console must be able to re-query the fabric');
  assert.ok(viewSource.includes('refreshModels'), 'the host must handle a catalog refresh');
});