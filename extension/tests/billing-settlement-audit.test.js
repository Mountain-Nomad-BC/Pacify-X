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
const { HarnessController } = require('../src/agentHarness/harnessController');
const { registerAgentConsole, BUDGET_STATE_KEY, TASK_STATE_KEY } = require('../src/agentHarness/registerAgentConsole');
const { buildPxProviderGatewayInvoker } = require('../src/agentHarness/pxProviderInvoker');
const { createExecutionContext } = require('../src/agentHarness/executionContext');
function usage(overrides = {}) { return { workerId: worker.workerId, providerId: worker.providerId, costClass: worker.costClass,
  inputTokens: 2, outputTokens: 1, totalTokens: 3, actualChargeUsd: 0.25, projectedChargeUsd: null,
  billingIdentityKnown: true, quotaRemaining: null, taskId: task.taskId, runId: 'run', executionId: 'invocation', settlementId: 'a'.repeat(64), ...overrides }; }
function asyncDisk(root, gate = async () => {}) {
  return { load: () => fs.existsSync(path.join(root,'budget.json')) ? JSON.parse(fs.readFileSync(path.join(root,'budget.json'),'utf8')) : null,
    save: async value => { await gate(value); const stage = path.join(root,'owned.prepared');
      const fd = fs.openSync(stage,'w'); try { fs.writeFileSync(fd,JSON.stringify(value)); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
      fs.renameSync(stage,path.join(root,'budget.json')); } };
}

test('asynchronous disk acknowledgment retains settlement deduplication across owner restart', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(),'px-billing-restart-'));
  try {
    const disk = asyncDisk(root);
    const first = new BudgetLedger(policy,{persistence:disk});
    first.reserve({worker,task,runId:'run',executionId:'invocation',projectedChargeUsd:.75});
    await first.flush(); first.record(usage()); await first.flush();
    const restarted = new BudgetLedger(policy,{persistence:asyncDisk(root)});
    restarted.record(usage()); await restarted.flush();
    assert.equal(restarted.receipts.length,1);assert.equal(restarted.reservations.size,0);
    assert.equal(restarted.canAdmit(worker,task,.76).allowed,false);
    assert.throws(()=>restarted.record(usage({actualChargeUsd:.5})),/conflict/);
    assert.throws(()=>restarted.record(usage({settlementId:'b'.repeat(64)})),/already-settled/);
  } finally { fs.rmSync(root,{recursive:true,force:true}); }
});

test('unknown actual costs remain held and cannot silently become zero', async () => {
  const disk=persistence(); const ledger=new BudgetLedger(policy,{persistence:disk});
  ledger.reserve({worker,task,runId:'run',executionId:'invocation',projectedChargeUsd:.5});
  assert.throws(()=>ledger.record(usage({taskId:'other'})),/owner-mismatch/);
  ledger.record(usage({actualChargeUsd:null}));await ledger.flush();
  const next=new BudgetLedger(policy,{persistence:disk});
  assert.equal(next.reservations.size,1);assert.equal(next.canAdmit(worker,task,0).allowed,false);
});

test('failed asynchronous reservation acknowledgment prevents dispatch admission', async () => {
  let fail=false; const ledger=new BudgetLedger(policy,{persistence:{load:()=>null,save:async()=>{if(fail)throw new Error('disk-unavailable');}}});
  await ledger.flush();fail=true;
  await assert.rejects(HarnessController.prototype._reserveUsage.call({budgetLedger:ledger},worker,task,{runId:'run'},{execution_id:'invocation'},.5),/disk-unavailable/);
  assert.throws(()=>ledger.canAdmit(worker,task,0),/disk-unavailable/);
});

test('legacy untracked task spend remains blocked after restart while new owners may reserve', async () => {
  const disk=persistence();const first=new BudgetLedger(policy,{persistence:disk,legacyTaskIds:[task.taskId]});await first.flush();
  const next=new BudgetLedger(policy,{persistence:disk});
  assert.equal(next.canAdmit(worker,task,0).reason,'task-historical-spend-unreconciled');
  assert.equal(next.canAdmit(worker,{...task,taskId:'new-task'},.25).allowed,true);
});

test('financial rows and returned receipts cannot be mutated to evade accumulated spend', () => {
  const ledger=new BudgetLedger(policy,{persistence:persistence()});
  const reservation=ledger.reserve({worker,task,runId:'run',executionId:'invocation',projectedChargeUsd:.75});
  assert.throws(()=>{reservation.microunits=0;},TypeError);
  const receipt=ledger.record(usage());assert.throws(()=>{receipt.actualChargeUsd=0;},TypeError);
  assert.equal(ledger.canAdmit(worker,task,.76).allowed,false);
});

test('sub-microunit task ceiling never rounds upward into extra authority', () => {
  const ledger=new BudgetLedger(policy,{persistence:persistence()});
  assert.equal(ledger.canAdmit(worker,{...task,constraints:{...task.constraints,taskCostCeilingUsd:.0000001}},.0000001).allowed,false);
});

function descriptor(){return {...worker,adapterId:'gateway',displayName:'paid test worker',contextLimit:4096,locality:'remote',
  capabilities:{coding:.5,planning:.5,review:.5,classification:.5},supportedEffectClass:'READ_ONLY',enabled:true,reliability:.8,latencyClass:'unknown'};}
function host(memento,invoke){
  const dispose=()=>({dispose(){}});
  return registerAgentConsole({window:{registerWebviewViewProvider:dispose},commands:{registerCommand:dispose}},
    {workspaceState:memento},{settingsProvider:()=>({executionPolicy:policy()}),gatewayWorkers:[descriptor()],providerGatewayInvoker:invoke});
}
function taskInput(){return {goal:'verify paid dispatch ownership',mode:'ASK',maxEffectClass:'READ_ONLY',contextBudgetTokens:1000,taskCostCeilingUsd:1,localFirst:false,requireApprovalBeforeBillable:false};}

test('actual host registration never invokes a provider before asynchronous reservation acknowledgment', async () => {
  const values=new Map();let release, reserved;const reached=new Promise(resolve=>{reserved=resolve;});
  const pending=new Promise(resolve=>{release=resolve;});let calls=0;
  const memento={get:key=>values.get(key),update:async(key,value)=>{
    if(key===BUDGET_STATE_KEY && value.reservations.length){reserved();await pending;}
    values.set(key,JSON.parse(JSON.stringify(value)));
  }};
  const registered=host(memento,async()=>{calls++;throw new Error('controlled-provider-failure');});
  const t=registered.harness.createTask(taskInput());
  const turn=registered.harness.sendTurn({taskId:t.taskId,message:'inspect',projectedChargeUsd:{[worker.workerId]:.75}});
  try {await reached;assert.equal(calls,0);} finally {release();}
  await assert.rejects(turn,/controlled-provider-failure/);assert.equal(calls,1);
  await registered.harness.budgetLedger.flush();registered.dispose();
  const next=host(memento,async()=>{throw new Error('must-not-dispatch');});
  assert.equal(next.harness.budgetLedger.canAdmit(worker,next.harness.taskStore.requireTask(t.taskId),.75).allowed,false);
  assert.equal(next.harness.budgetLedger.reservations.size,1);next.dispose();
});

test('native invoker carries the reserved invocation identity across the bridge', async () => {
  let payload;const invoke=buildPxProviderGatewayInvoker({profileIdForWorker:()=> 'profile',bridge:{streamChat:async(value,signal,onEvent)=>{payload=value;onEvent({kind:'px_receipt',payload:{controlled:true}});}}});
  await invoke({worker,task,run:{runId:'run'},executionContext:createExecutionContext({run:{runId:'run',revision:1,epoch:1},projectId:'project',sessionId:'run',providerId:'local',authoritySha256:'a'.repeat(64),effectBudgetSha256:'b'.repeat(64)}),message:'inspect'});
  assert.equal(payload.request_id, payload.execution_context.execution_id);assert.equal(payload.correlation_id,'corr-task');
  await assert.rejects(invoke({worker,task,run:{runId:'run'}}),/invocation-owner-required/);
});

const { sha256 } = require('../src/agentHarness/ids');
function canonical(value){if(value && typeof value==='object'){if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}';}return JSON.stringify(value);}
// Controlled receipt fixture exercises host owner binding; real native receipt
// compatibility is independently exercised by test_billing_budget_audit.py.
function controlledOutcome(input){
  const receipt={schema_version:'px.provider-stream-receipt/1.0',invocation_id:input.executionContext.execution_id,
    correlation_id:'corr-'+input.task.taskId,adapter_id:'fixture',provider_id:worker.providerId,model_id:worker.modelId,
    input_sha256:'1'.repeat(64),output_sha256:'2'.repeat(64),budget_receipt_sha256:sha256(input.executionContext.execution_id),
    budget_reservation_receipt_sha256:'3'.repeat(64),started_revision:1,completed_revision:2,billing_state:'actual',currency:'USD',
    input_tokens:2,output_tokens:1,charge_microunits:250000};
  receipt.receipt_sha256=sha256(canonical(receipt));return {value:'controlled completion',receipt};
}

test('registered host settles a typed receipt under the reserved task/run/invocation exactly once', async()=>{
  const values=new Map();const memento={get:key=>values.get(key),update:async(key,value)=>{values.set(key,JSON.parse(JSON.stringify(value)));}};
  const registered=host(memento,async input=>controlledOutcome(input));
  const t=registered.harness.createTask(taskInput());
  const result=await registered.harness.sendTurn({taskId:t.taskId,message:'inspect',projectedChargeUsd:{[worker.workerId]:.75}});
  assert.equal(result.text,'controlled completion');assert.equal(result.run.status,'complete');
  const ledger=registered.harness.budgetLedger;assert.equal(ledger.entries.length,1);assert.equal(ledger.reservations.size,0);
  assert.equal(ledger.entries[0].taskId,t.taskId);assert.equal(ledger.entries[0].runId,result.run.runId);
  assert.equal(values.get(BUDGET_STATE_KEY).entries[0].receipt.actualChargeUsd,.25);
  registered.dispose();
});

test('cancelled paid attempt records its returned typed usage before rejecting late completion', async()=>{
  const values=new Map();let complete,start;const entered=new Promise(resolve=>{start=resolve;});
  const pending=new Promise(resolve=>{complete=resolve;});let input;
  const registered=host({get:key=>values.get(key),update:async(key,value)=>{values.set(key,JSON.parse(JSON.stringify(value)));}},async value=>{input=value;start();await pending;return controlledOutcome(value);});
  const t=registered.harness.createTask(taskInput());
  const turn=registered.harness.sendTurn({taskId:t.taskId,message:'inspect',projectedChargeUsd:{[worker.workerId]:.75}});
  await entered;const run=registered.harness.taskStore.listRuns(t.taskId)[0];
  await registered.harness.cancelRun(run.runId);complete();await assert.rejects(turn,/abort/);
  assert.equal(registered.harness.budgetLedger.reservations.size,0);
  assert.equal(values.get(BUDGET_STATE_KEY).entries[0].receipt.actualChargeUsd,.25);
  assert.equal(registered.harness.taskStore.requireRun(run.runId).status,'cancelled');
  assert.equal(registered.harness.eventBus.snapshot().some(event=>event.type==='worker.completed'),false);
  registered.dispose();
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { DurableBudgetState } = require('../src/agentHarness/durableTaskState');
const { HarnessController } = require('../src/agentHarness/harnessController');
const { createExecutionContext } = require('../src/agentHarness/executionContext');
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
  const localWorker = { ...worker, costClass: 'local' };
  const context = { execution_id: 'invocation' };
  await HarnessController.prototype._reserveUsage.call(owner, localWorker, task, { runId: 'run' }, context, 0);
  await HarnessController.prototype._recordUsage.call(owner, localWorker, task, { runId: 'run' }, context,
    { usage: usage({ costClass: 'local', actualChargeUsd: null, billingIdentityKnown: false }), settlementId: null });
  assert.equal(ledger.entries[0].taskId, task.taskId);
  assert.equal(ledger.entries[0].executionId, context.execution_id);
  assert.equal(ledger.entries[0].receipt.costClass, 'local');
  assert.equal(ledger.reservations.size, 0);
});
});
