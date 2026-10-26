'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { newId } = require('../src/agentHarness/ids');
const { TaskStore } = require('../src/agentHarness/taskStore');
const { BudgetLedger } = require('../src/agentHarness/budgetLedger');
const { WorkerRegistry } = require('../src/agentHarness/workerRegistry');
const { ContextCompiler } = require('../src/agentHarness/contextCompiler');
const { TinyLibrarian } = require('../src/agentHarness/tinyLibrarian');
const { ToolBroker } = require('../src/agentHarness/toolBroker');
const { HarnessController } = require('../src/agentHarness/harnessController');
const { CanonicalEventBus } = require('../src/agentHarness/eventBus');

function makeStore() {
  return new TaskStore({ persistence: { load: () => null, save: () => {} } });
}

class FullTextAdapter {
  async runTurn(input) {
    return { text: 'A'.repeat(5000) + 'tail-marker' };
  }
}

test('PX-AUD-038 conclusionSha256 binds full text not just first 4096 chars', async () => {
  const store = makeStore();
  const bus = new CanonicalEventBus();
  const ledger = new BudgetLedger(() => ({}));
  const registry = new WorkerRegistry();
  const compiler = new ContextCompiler();
  const librarian = new TinyLibrarian();
  const toolBroker = new ToolBroker({ eventBus: bus, approvalProvider: null });
  const harness = new HarnessController({ eventBus: bus, taskStore: store, budgetLedger: ledger, workerRegistry: registry, contextCompiler: compiler, tinyLibrarian: librarian, toolBroker: toolBroker, hostSettings: () => ({}) });
  registry.register({ workerId: 'w1', adapterId: 'a1', providerId: 'p1', modelId: 'm1', displayName: 'W1', costClass: 'local', contextLimit: 100000, locality: 'local', capabilities: { coding: 1, planning: 1, review: 1, classification: 1, toolUse: false, vision: false, structuredOutput: false }, supportedEffectClass: 'READ_ONLY', enabled: true, reliability: 1, latencyClass: 'fast' }, new FullTextAdapter());
  const task = store.createTask({ goal: 'g', mode: 'ASK', maxEffectClass: 'READ_ONLY', contextBudgetTokens: 12000, taskCostCeilingUsd: 0, localFirst: true, requireApprovalBeforeBillable: true });
  const result = await harness.sendTurn({ taskId: task.taskId, message: 'hello' });
  const fullHash = require('../src/agentHarness/ids').sha256('A'.repeat(5000) + 'tail-marker');
  const truncatedHash = require('../src/agentHarness/ids').sha256('A'.repeat(4096));
  assert.equal(result.conclusionSha256, fullHash, 'conclusion hash must bind full text');
  assert.notEqual(result.conclusionSha256, truncatedHash, 'conclusion hash must not be truncated to 4096 chars');
  bus.dispose();
});
