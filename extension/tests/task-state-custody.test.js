'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { TaskStore } = require('../src/agentHarness/taskStore');
const { WorkerRegistry } = require('../src/agentHarness/workerRegistry');

function input(id = 'task') { return { taskId: id, goal: 'verify owned task state', mode: 'DIAGNOSE' }; }

test('failed synchronous save cannot publish a task mutation', () => {
  let refuse = false;
  const store = new TaskStore({ persistence: { synchronous: true, save: () => {
    if (refuse) throw new Error('disk-refused');
  } } });
  const task = store.createTask(input());
  const before = JSON.stringify(task);
  refuse = true;
  assert.throws(() => store.updateTask(task.taskId, { goal: 'uncommitted goal' }), /disk-refused/);
  assert.equal(JSON.stringify(store.tasks.get(task.taskId)), before);
});

test('cancelled task cannot return to implementation or start a run', () => {
  const store = new TaskStore();
  const task = store.createTask(input());
  store.updateTask(task.taskId, { status: 'cancelled', stage: 'CANCELLED' });
  assert.throws(() => store.updateTask(task.taskId, { stage: 'IMPLEMENT' }), /terminal/);
  assert.throws(() => store.createRun(task.taskId), /terminal/);
});

test('only one live run can own a task', () => {
  const store = new TaskStore();
  const task = store.createTask(input());
  const run = store.createRun(task.taskId);
  assert.throws(() => store.createRun(task.taskId), /already.*run/);
  store.updateRun(run.runId, { status: 'complete' });
  assert.notEqual(store.createRun(task.taskId).runId, run.runId);
});

test('task and run identities cannot be rebound by an update', () => {
  const store = new TaskStore();
  const task = store.createTask(input());
  const run = store.createRun(task.taskId);
  assert.throws(() => store.updateTask(task.taskId, { taskId: 'another-task' }), /identity/);
  assert.throws(() => store.updateRun(run.runId, { taskId: 'another-task' }), /identity/);
  assert.throws(() => store.updateRun(run.runId, { runId: 'another-run' }), /identity/);
});

test('corrupt persisted state is refused rather than silently replaced with empty state', () => {
  let saves = 0;
  assert.throws(() => new TaskStore({ persistence: {
    load: () => ({ schemaVersion: 'damaged', tasks: [], runs: [] }),
    save: () => { saves += 1; }
  } }), /snapshot/);
  assert.equal(saves, 0);
});

test('persistence rejection prevents further dispatch-facing reads', async () => {
  const store = new TaskStore({ persistence: { save: async () => { throw new Error('async-disk-refused'); } } });
  const task = store.createTask(input());
  await assert.rejects(store.flush(), /async-disk-refused/);
  assert.throws(() => store.requireTask(task.taskId), /async-disk-refused/);
  assert.equal(store.tasks.size, 0);
});

function worker() { return { workerId: 'worker', adapterId: 'test', providerId: 'provider', modelId: 'model',
  displayName: 'owned worker', costClass: 'local', contextLimit: 1024, locality: 'local',
  capabilities: { coding: .5, planning: .5, review: .5, classification: .5 },
  supportedEffectClass: 'READ_ONLY', enabled: true, reliability: .5, latencyClass: 'unknown' }; }

test('stale disposable cannot delete a replacement worker registration', () => {
  const registry = new WorkerRegistry();
  const stale = registry.register(worker(), { runTurn: async () => {} });
  const replacement = { runTurn: async () => {} };
  registry.register(worker(), replacement);
  stale.dispose();
  assert.equal(registry.adapter('worker'), replacement);
});

test('late health response cannot overwrite replacement worker health', async () => {
  const registry = new WorkerRegistry();
  let finish;
  registry.register(worker(), { runTurn: async () => {}, health: () => new Promise(resolve => { finish = resolve; }) });
  const refresh = registry.refreshHealth();
  registry.register(worker(), { runTurn: async () => {} });
  registry.setHealth('worker', { status: 'replacement-health' });
  finish({ status: 'stale-health' });
  await refresh;
  assert.equal(registry.getHealth('worker').status, 'replacement-health');
});

function harness(adapter, persistence = null) {
  const { HarnessController } = require('../src/agentHarness/harnessController');
  const { CanonicalEventBus } = require('../src/agentHarness/eventBus');
  const { BudgetLedger } = require('../src/agentHarness/budgetLedger');
  const { ContextCompiler } = require('../src/agentHarness/contextCompiler');
  const { TinyLibrarian } = require('../src/agentHarness/tinyLibrarian');
  const workerRegistry = new WorkerRegistry();
  workerRegistry.register(worker(), adapter);
  return new HarnessController({ taskStore: new TaskStore({ persistence }), workerRegistry,
    eventBus: new CanonicalEventBus(), budgetLedger: new BudgetLedger(),
    contextCompiler: new ContextCompiler(), tinyLibrarian: new TinyLibrarian() });
}

test('controller does not dispatch before worker selection is durably acknowledged', async () => {
  let acknowledge;
  const blocked = new Promise(resolve => { acknowledge = resolve; });
  let called = false;
  const owner = harness({ runTurn: async () => { called = true; return { text: 'completed' }; } },
    { save: async state => { if (state.runs.some(run => run.activeWorkerId)) await blocked; } });
  const turn = owner.sendTurn({ goal: 'verify local dispatch', message: 'inspect local data' });
  try {
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(called, false);
  } finally { acknowledge(); }
  await turn;
  assert.equal(called, true);
});

test('cancellation settles usage but cannot publish completion or late deltas', async () => {
  let finish, late;
  const waiting = new Promise(resolve => { finish = resolve; });
  const owner = harness({ runTurn: async input => { late = input.onEvent; return waiting; }, interrupt: async () => {} });
  const task = owner.createTask(input());
  const turn = owner.sendTurn({ taskId: task.taskId, message: 'inspect local data' });
  await new Promise(resolve => setImmediate(resolve));
  const run = owner.taskStore.listRuns(task.taskId)[0];
  assert.equal(await owner.cancelRun(run.runId), true);
  finish({ text: 'late result', usage: { inputTokens: 2, outputTokens: 1, totalTokens: 3 } });
  await assert.rejects(turn, /abort/);
  assert.equal(owner.budgetLedger.receipts.length, 1);
  assert.equal(owner.taskStore.requireRun(run.runId).status, 'cancelled');
  assert.equal(owner.eventBus.snapshot().some(event => event.type === 'worker.completed'), false);
  const count = owner.eventBus.sequence;
  late({ type: 'worker.stream.delta', payload: { delta: 'stale' } });
  assert.equal(owner.eventBus.sequence, count);
});

test('controller rejects a run belonging to another task before dispatch', async () => {
  let called = false;
  const owner = harness({ runTurn: async () => { called = true; return { text: 'wrong owner' }; } });
  const first = owner.createTask(input('first'));
  const second = owner.createTask(input('second'));
  const run = owner.taskStore.createRun(second.taskId);
  await assert.rejects(owner.sendTurn({ taskId: first.taskId, runId: run.runId, message: 'inspect' }), /owner-mismatch/);
  assert.equal(called, false);
});

test('returned task values cannot mutate persisted ownership or constraints', () => {
  const store=new TaskStore();const task=store.createTask(input());
  assert.throws(()=>{task.constraints.taskCostCeilingUsd=999;},TypeError);
  assert.throws(()=>{task.taskId='rebound';},TypeError);
  const run=store.createRun(task.taskId);assert.throws(()=>{run.taskId='other';},TypeError);
});

test('restart cannot redispatch a worker-selected run with unknown previous effects', async()=>{
  let snapshot;const store=new TaskStore({persistence:{save:value=>{snapshot=JSON.parse(JSON.stringify(value));}}});
  const task=store.createTask(input());const run=store.createRun(task.taskId);store.selectWorker(run.runId,'worker','selected before crash');
  let called=false;const owner=harness({runTurn:async()=>{called=true;return {text:'unsafe replay'};}},{load:()=>snapshot,save:()=>{}});
  await assert.rejects(owner.sendTurn({taskId:task.taskId,runId:run.runId,message:'resume',resume:true}),/recovery-required/);
  assert.equal(called,false);
});

test('cancel request has a bound while unsettled adapter remains fenced from replacement', async()=>{
  let finish,start;const entered=new Promise(resolve=>{start=resolve;});const pending=new Promise(resolve=>{finish=resolve;});
  const owner=harness({runTurn:async()=>{start();return pending;},interrupt:()=>new Promise(()=>{})});
  owner.cancelInterruptTimeoutMs=20;
  const task=owner.createTask(input());const turn=owner.sendTurn({taskId:task.taskId,message:'inspect'});
  const settled=assert.rejects(turn,/abort/);await entered;
  const run=owner.taskStore.listRuns(task.taskId)[0];let timer;
  try {
    const response=await Promise.race([owner.cancelRun(run.runId),new Promise(resolve=>{timer=setTimeout(()=>resolve('unbounded'),150);})]);
    assert.equal(response,true);
    await assert.rejects(owner.sendTurn({taskId:task.taskId,message:'replacement'}),/task-already-executing/);
    assert.equal(owner.eventBus.snapshot().some(e=>e.type==='worker.interrupt.unsettled'),true);
  } finally {clearTimeout(timer);finish({text:'late'});await settled;owner.dispose();}
});
