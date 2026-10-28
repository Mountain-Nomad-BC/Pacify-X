'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { TaskStore } = require('../src/agentHarness/taskStore');
const { ToolBroker } = require('../src/agentHarness/toolBroker');
const { createExecutionContext } = require('../src/agentHarness/executionContext');
const { newId, nowIso, sha256 } = require('../src/agentHarness/ids');

test('tool execution requires the current run-owned execution context', async () => {
  const store = new TaskStore();
  const task = store.createTask({
    goal: 'x', mode: 'DIAGNOSE', maxEffectClass: 'MUTATING', contextBudgetTokens: 1000,
    taskCostCeilingUsd: null, localFirst: true, requireApprovalBeforeBillable: true,
    completionContract: []
  });
  let run = store.createRun(task.taskId);
  run = store.selectWorker(run.runId, 'worker-1', 'fixture');
  const broker = new ToolBroker({ taskStore: store, approvalProvider: async () => false });
  broker.register({ toolId: 'write.fixture', effectClass: 'MUTATING', execute: async () => ({ summary: 'wrote' }) });
  const request = {
    requestId: newId('req'), taskId: task.taskId, runId: run.runId, workerId: 'worker-1',
    toolId: 'write.fixture', effectClass: 'MUTATING', arguments: {}, scopeRefs: [], requestedAt: nowIso()
  };

  await assert.rejects(broker.execute(request, task), /execution-context-required/);
  const context = createExecutionContext({
    run, projectId: 'workspace', sessionId: run.runId, providerId: 'fixture',
    authoritySha256: sha256(task.constraints),
    effectBudgetSha256: sha256({ maxEffectClass: task.constraints.maxEffectClass })
  });
  assert.equal((await broker.execute(request, task, context)).status, 'blocked');
  await assert.rejects(
    broker.execute(request, task, { ...context, root_execution_id: 'other-run' }),
    /execution-context-run-owner-mismatch/
  );
  await assert.rejects(
    broker.execute(request, task, { ...context, provider_id: 'tampered-provider' }),
    /execution-context-digest-mismatch/
  );
});
