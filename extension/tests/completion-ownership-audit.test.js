'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { TaskStore } = require('../src/agentHarness/taskStore');
const { evaluateCompletion } = require('../src/agentHarness/completionEvaluator');
function fixture() {
  const store = new TaskStore();
  const task = store.createTask({ goal: 'verify', mode: 'DIAGNOSE', maxEffectClass: 'READ_ONLY', contextBudgetTokens: 1000, taskCostCeilingUsd: 0, localFirst: true, requireApprovalBeforeBillable: true, completionContract: [{ id: 'tests', required: true, label: 'Current tests', evidenceTypes: ['test-result'] }] });
  const run = store.createRun(task.taskId);
  const evidence = { evidenceId: 'proof', taskId: task.taskId, runId: run.runId, type: 'test-result', status: 'pass', summary: 'Controlled execution fixture', sourceRef: null, sha256: null, capturedAt: new Date().toISOString() };
  return { store, task, run, evidence };
}
test('valid current-run evidence satisfies the declared requirement', () => {
  const f = fixture(); assert.equal(evaluateCompletion(f.task, [f.evidence], f.run).complete, true);
});
for (const field of ['taskId', 'runId']) test(`foreign ${field} cannot satisfy completion`, () => {
  const f = fixture(); assert.equal(evaluateCompletion(f.task, [{ ...f.evidence, [field]: 'foreign' }], f.run).complete, false);
});
test('missing current run fails closed for required evidence', () => {
  const f = fixture(); assert.equal(evaluateCompletion(f.task, [f.evidence]).complete, false);
});
test('foreign current-run owner fails closed', () => {
  const f = fixture(); assert.equal(evaluateCompletion(f.task, [f.evidence], { ...f.run, taskId: 'foreign' }).complete, false);
});
for (const capturedAt of ['2000-01-01T00:00:00.000Z', '2099-01-01T00:00:00.000Z', 'invalid']) test(`out-of-run timestamp ${capturedAt} cannot satisfy completion`, () => {
  const f = fixture(); assert.equal(evaluateCompletion(f.task, [{ ...f.evidence, capturedAt }], f.run).complete, false);
});
test('conflicting duplicate identity invalidates both records regardless of order', () => {
  const f = fixture(); const failed = { ...f.evidence, status: 'fail' };
  for (const records of [[f.evidence, failed], [failed, f.evidence]]) assert.equal(evaluateCompletion(f.task, records, f.run).complete, false);
});
test('identical retransmission contributes one evidence ID', () => {
  const f = fixture(); const verdict = evaluateCompletion(f.task, [f.evidence, { ...f.evidence }], f.run);
  assert.equal(verdict.complete, true); assert.deepEqual(verdict.requirements[0].evidenceIds, ['proof']);
});
test('malformed evidence does not masquerade as a typed pass', () => {
  const f = fixture(); assert.equal(evaluateCompletion(f.task, [{ type: 'test-result', status: 'pass' }], f.run).complete, false);
});

for (const ownership of ['current', 'foreign-task', 'previous-run']) test(`actual controller completion filters ${ownership} evidence`, async () => {
  const { HarnessController } = require('../src/agentHarness/harnessController');
  const { CanonicalEventBus } = require('../src/agentHarness/eventBus');
  const { BudgetLedger } = require('../src/agentHarness/budgetLedger');
  const { WorkerRegistry } = require('../src/agentHarness/workerRegistry');
  const { ContextCompiler } = require('../src/agentHarness/contextCompiler');
  const { TinyLibrarian } = require('../src/agentHarness/tinyLibrarian');
  const f=fixture(); const registry=new WorkerRegistry();const bus=new CanonicalEventBus();
  const harness=new HarnessController({taskStore:f.store,eventBus:bus,budgetLedger:new BudgetLedger(()=>({})),workerRegistry:registry,contextCompiler:new ContextCompiler(),tinyLibrarian:new TinyLibrarian(),hostSettings:()=>({})});
  registry.register({workerId:'worker',adapterId:'controlled',providerId:'local',modelId:'fixture',displayName:'Controlled test adapter',costClass:'local',contextLimit:12000,locality:'local',capabilities:{coding:1,planning:1,review:1,classification:1},supportedEffectClass:'READ_ONLY',enabled:true,reliability:1,latencyClass:'fast'}, {runTurn:async input=>{
    harness.evidence.set(f.task.taskId,[{...f.evidence,taskId:ownership==='foreign-task'?'foreign':input.task.taskId,runId:ownership==='previous-run'?'previous':input.run.runId,capturedAt:new Date().toISOString()}]);
    return {text:'Controlled turn; evidence is a fixture, not a certified execution receipt.'};
  }});
  try {const result=await harness.sendTurn({taskId:f.task.taskId,runId:f.run.runId,message:'inspect'});assert.equal(result.verdict.complete,ownership==='current');assert.equal(result.run.status,'complete');}
  finally {harness.dispose();}
});
