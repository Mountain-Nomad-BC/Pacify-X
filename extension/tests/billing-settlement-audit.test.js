'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { BudgetLedger } = require('../src/agentHarness/budgetLedger');
const { AgentConsoleViewProvider } = require('../src/agentHarness/agentConsoleView');
const { PxProviderGatewayAdapter } = require('../src/agentHarness/adapters/pxProviderGateway');

function persistence() {
  let value = null;
  return { synchronous: true, load: () => value && JSON.parse(JSON.stringify(value)),
    save: next => { value = JSON.parse(JSON.stringify(next)); } };
}
const policy = () => ({ master_enabled: true, require_approval_before_billable_execution: false });
const worker = { workerId: 'paid-worker', providerId: 'provider', modelId: 'model', costClass: 'billable-api' };
const task = { taskId: 'task', constraints: { taskCostCeilingUsd: 1, requireApprovalBeforeBillable: false } };

test('unknown, nonfinite and negative billable estimates fail closed', () => {
  const ledger = new BudgetLedger(policy, { persistence: persistence() });
  for (const estimate of [null, undefined, NaN, Infinity, -1, true, '0.1']) {
    assert.equal(ledger.canAdmit(worker, task, estimate).allowed, false);
  }
});

test('concurrent reservations enforce the cumulative ceiling', async () => {
  const ledger = new BudgetLedger(policy, { persistence: persistence() });
  const reserve = id => ledger.reserve({ worker, task, runId: 'run', executionId: id, projectedChargeUsd: 0.75 });
  const results = await Promise.allSettled([
    Promise.resolve().then(() => reserve('invocation-one')),
    Promise.resolve().then(() => reserve('invocation-two')),
  ]);
  assert.equal(results.filter(result => result.status === 'fulfilled').length, 1);
  assert.equal(results.filter(result => result.status === 'rejected').length, 1);
});

test('unsettled reservations survive restart and still consume the task ceiling', () => {
  const disk = persistence();
  const first = new BudgetLedger(policy, { persistence: disk });
  first.reserve({ worker, task, runId: 'run', executionId: 'invocation', projectedChargeUsd: 0.75 });
  const restarted = new BudgetLedger(policy, { persistence: disk });
  assert.equal(restarted.canAdmit(worker, task, 0.75).allowed, false);
});

test('zero policy ceiling is preserved by the view defaults', () => {
  const owner = { harness: { hostSettings: () => ({ executionPolicy: { max_cost_per_task_usd: 0 } }) } };
  assert.equal(AgentConsoleViewProvider.prototype._defaults.call(owner).taskCostCeilingUsd, 0);
});

test('billable work cannot be reserved without durable persistence', () => {
  const ledger = new BudgetLedger(policy);
  assert.throws(() => ledger.reserve({ worker, task, runId: 'run', executionId: 'invocation', projectedChargeUsd: 0.1 }), /persistence/);
});

for (const receipt of [true, {}, { schema_version: 'failure', provider_receipt: {} }, { exact_receipt: false }]) {
  test(`gateway rejects forged settlement ${JSON.stringify(receipt)}`, async () => {
    const adapter = new PxProviderGatewayAdapter({ worker, invokeProvider: async () => ({ value: 'untrusted', receipt }) });
    await assert.rejects(adapter.runTurn({ task, run: { runId: 'run' }, onEvent: () => {} }), /receipt|settlement/);
  });
}

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { DurableBudgetState } = require('../src/agentHarness/durableTaskState');
const { HarnessController } = require('../src/agentHarness/harnessController');
function usage(overrides = {}) { return { workerId: worker.workerId, providerId: worker.providerId, costClass: worker.costClass,
  inputTokens: 2, outputTokens: 1, totalTokens: 3, actualChargeUsd: 0.25, projectedChargeUsd: null,
  billingIdentityKnown: true, quotaRemaining: null, taskId: task.taskId, runId: 'run', executionId: 'invocation', settlementId: 'a'.repeat(64), ...overrides }; }

test('real durable owner retains settlements and rejects duplicate or conflicting charges', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-billing-owner-'));
  try {
    const first = new BudgetLedger(policy, { persistence: new DurableBudgetState(root) });
    first.reserve({ worker, task, runId: 'run', executionId: 'invocation', projectedChargeUsd: 0.75 });
    first.record(usage());
    const next = new BudgetLedger(policy, { persistence: new DurableBudgetState(root) });
    next.record(usage());
    assert.equal(next.receipts.length, 1);
    assert.equal(next.reservations.size, 0);
    assert.equal(next.canAdmit(worker, task, 0.76).allowed, false);
    assert.throws(() => next.record(usage({ actualChargeUsd: 0.5 })), /conflict/);
    assert.throws(() => next.record(usage({ settlementId: 'b'.repeat(64) })), /already-settled/);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('reservation ownership, unknown actual costs and persistence failures fail closed', () => {
  const ledger = new BudgetLedger(policy, { persistence: persistence() });
  ledger.reserve({ worker, task, runId: 'run', executionId: 'invocation', projectedChargeUsd: 0.5 });
  assert.throws(() => ledger.record(usage({ taskId: 'other-task' })), /owner-mismatch/);
  ledger.record(usage({ actualChargeUsd: null }));
  assert.equal(ledger.reservations.size, 1);
  assert.equal(ledger.canAdmit(worker, task, 0).allowed, false);
  const disk = persistence(); const broken = new BudgetLedger(policy, { persistence: disk });
  disk.save = () => { throw new Error('disk-unavailable'); };
  assert.throws(() => broken.reserve({ worker, task, runId: 'run', executionId: 'invocation', projectedChargeUsd: 0.1 }), /disk-unavailable/);
  assert.throws(() => broken.canAdmit(worker, task, 0), /disk-unavailable/);
});

test('controller settlement helper binds task and execution and flushes durable usage', async () => {
  const ledger = new BudgetLedger(policy, { persistence: persistence() });
  const owner = { budgetLedger: ledger };
  const context = { execution_id: 'invocation' };
  await HarnessController.prototype._reserveUsage.call(owner, worker, task, { runId: 'run' }, context, 0.5);
  await HarnessController.prototype._recordUsage.call(owner, worker, task, { runId: 'run' }, context,
    { usage: usage(), settlementId: 'a'.repeat(64) });
  assert.equal(ledger.entries[0].taskId, task.taskId);
  assert.equal(ledger.entries[0].executionId, context.execution_id);
  assert.equal(ledger.reservations.size, 0);
});


test('nonfinite settlement cannot publish a financial snapshot', () => {
  const ledger = new BudgetLedger(policy, { persistence: persistence() });
  ledger.reserve({ worker, task, runId: 'run', executionId: 'invocation', projectedChargeUsd: 0.5 });
  for (const value of [NaN, Infinity, -1]) assert.throws(() => ledger.record(usage({ actualChargeUsd: value })));
  assert.equal(ledger.entries.length, 0);
  assert.equal(ledger.reservations.size, 1);
});
