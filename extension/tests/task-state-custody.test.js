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

test('mesh conclusions bind the complete branch text', async () => {
  const text = 'A'.repeat(5000) + 'tail';
  const owner = harness({ runTurn: async () => ({ text }) });
  owner.workerRegistry.register({ ...worker(), contextLimit: 100000 }, { runTurn: async () => ({ text }) });
  try {
    const result = await owner.sendMeshTurn({ goal: 'inspect local data', message: 'inspect', branches: [{ workerId: 'worker' }] });
    assert.equal(result.branchResults[0].state, 'completed');
    assert.equal(result.branchResults[0].conclusionSha256, require('../src/agentHarness/ids').sha256(text));
  } finally { owner.dispose(); }
});

test('all-failed mesh cannot persist or emit successful completion', async () => {
  let persisted, calls = 0;
  const adapter = { runTurn: async () => { calls += 1; throw new Error('fixture provider failure'); } };
  const owner = harness(adapter,
    { save: value => { persisted = JSON.parse(JSON.stringify(value)); } });
  owner.workerRegistry.register({ ...worker(), contextLimit: 100000 }, adapter);
  try {
    const result = await owner.sendMeshTurn({ goal: 'inspect local data', message: 'inspect', branches: [{ workerId: 'worker' }, { workerId: 'worker' }] });
    assert.equal(result.branchResults.every(branch => branch.state === 'failed'), true);
    assert.equal(result.run.status, 'failed');
    assert.equal(calls, 2);
    assert.equal(persisted.runs.find(run => run.runId === result.run.runId).status, 'failed');
    assert.equal(owner.eventBus.snapshot().some(event => event.type === 'mesh.completed'), false);
    const restarted = harness(adapter, { load: () => persisted, save: () => {} });
    try {
      assert.equal(restarted.taskStore.requireRun(result.run.runId).status, 'failed');
      await assert.rejects(restarted.sendMeshTurn({ taskId: result.task.taskId, runId: result.run.runId, message: 'replay', branches: [{ workerId: 'worker' }] }), /terminal-run/);
      assert.equal(calls, 2);
    } finally { restarted.dispose(); }
  } finally { owner.dispose(); }
});

for (const [states, expected] of [
  [['completed', 'completed'], 'complete'],
  [['completed', 'failed'], 'partial'],
  [['cancelled', 'cancelled'], 'cancelled'],
  [['failed', 'cancelled'], 'failed'],
  [['timeout', 'timeout'], 'failed']
]) test(`mesh ${states.join('/')} preserves its terminal outcome`, async () => {
  let calls = 0;
  const adapter = { runTurn: async () => {
    const state = states[calls++];
    if (state === 'completed') return { text: 'answer' };
    throw Object.assign(new Error(`fixture ${state}`), { name: state === 'cancelled' ? 'AbortError' : state === 'timeout' ? 'TimeoutError' : 'Error' });
  } };
  const owner = harness(adapter);
  owner.workerRegistry.register({ ...worker(), contextLimit: 100000 }, adapter);
  try {
    const result = await owner.sendMeshTurn({ goal: 'inspect local data', message: 'inspect', branches: states.map(() => ({ workerId: 'worker' })) });
    assert.equal(calls, states.length);
    assert.equal(result.convergence.outcome, expected);
    assert.equal(result.run.status, expected === 'partial' ? 'failed' : expected);
    assert.equal(result.convergence.quorumMet, expected === 'complete');
    assert.equal(result.convergence.wholeMeshSupport, result.convergence.supportCount / states.length);
    assert.equal(owner.eventBus.snapshot().some(event => event.type === 'mesh.completed'), expected === 'complete');
  } finally { owner.dispose(); }
});

test('one successful branch out of twelve is partial with whole-mesh support', async () => {
  const owner = harness({ runTurn: async () => ({ text: 'answer' }) });
  let index = 0;
  owner._runMeshBranch = async () => {
    const branchIndex = index++;
    return { branchIndex, branchId: `fixture-${branchIndex}`, state: branchIndex === 0 ? 'completed' : 'failed', conclusion: branchIndex === 0 ? 'answer' : '' };
  };
  try {
    const result = await owner.sendMeshTurn({ goal: 'inspect local data', message: 'inspect', branches: Array.from({ length: 12 }, () => ({ workerId: 'worker' })) });
    assert.equal(result.run.status, 'failed');
    assert.equal(result.convergence.outcome, 'partial');
    assert.equal(result.convergence.supportRatio, 1 / 12);
    assert.equal(result.convergence.agreementAmongCompleted, 1);
    assert.equal(result.convergence.quorumMet, false);
  } finally { owner.dispose(); }
});

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

test('mesh cancellation bounds stalled interrupts and retains active ownership', async () => {
  let releaseInterrupt;
  const pending = new Promise(resolve => { releaseInterrupt = resolve; });
  let interrupts = 0;
  const owner = harness({ runTurn: async () => { throw new Error('unexpected dispatch'); },
    interrupt: () => { interrupts++; return pending; } });
  owner.cancelInterruptTimeoutMs = 20;
  const task = owner.createTask(input());
  const run = owner.taskStore.createRun(task.taskId);
  const controllers = new Map([[0, new AbortController()], [1, new AbortController()]]);
  const active = { mesh: true, taskId: task.taskId, controllers,
    branchWorkerIds: new Map([[0, 'worker'], [1, 'worker']]) };
  owner.active.set(run.runId, active);
  const cancellation = owner.cancelRun(run.runId);
  let timer;
  try {
    const result = await Promise.race([cancellation,
      new Promise(resolve => { timer = setTimeout(() => resolve('unbounded'), 200); })]);
    assert.equal(result, true);
    assert.equal(interrupts, 1);
    assert.ok([...controllers.values()].every(controller => controller.signal.aborted));
    assert.equal(owner.taskStore.requireRun(run.runId).status, 'cancelled');
    assert.equal(owner.active.get(run.runId), active);
    const unsettled = owner.eventBus.snapshot().filter(event => event.type === 'worker.interrupt.unsettled');
    assert.equal(unsettled.length, 1);
    assert.equal(unsettled[0].workerId, 'worker');
    assert.equal(unsettled[0].payload.outcome, 'timeout');
    assert.equal(await owner.cancelRun(run.runId), false);
  } finally {
    clearTimeout(timer); releaseInterrupt(); await cancellation;
    owner.active.delete(run.runId); owner.dispose();
  }
});

for (const outcome of ['acknowledged', 'unsupported', 'failed']) {
  test(`mesh cancellation records ${outcome} interrupt outcome`, async () => {
    const owner = harness({ runTurn: async () => { throw new Error('unexpected dispatch'); }, interrupt: () => {
      if (outcome === 'failed') throw new Error('controlled interrupt failure');
      return outcome !== 'unsupported';
    } });
    const task = owner.createTask(input());
    const run = owner.taskStore.createRun(task.taskId);
    owner.active.set(run.runId, { mesh: true, taskId: task.taskId,
      controllers: new Map([[0, new AbortController()]]), branchWorkerIds: new Map([[0, 'worker']]) });
    try {
      assert.equal(await owner.cancelRun(run.runId), true);
      const unsettled = owner.eventBus.snapshot().filter(event => event.type === 'worker.interrupt.unsettled');
      assert.equal(unsettled.length, outcome === 'acknowledged' ? 0 : 1);
      if (unsettled.length) assert.equal(unsettled[0].payload.outcome, outcome);
      assert.equal(owner.active.has(run.runId), true);
    } finally { owner.active.delete(run.runId); owner.dispose(); }
  });
}

for (const status of ['running', 'waiting', 'blocked', 'cancelled']) {
  test(`legacy ${status} snapshot retains recovery custody across repeated loads`, async () => {
    let snapshot;
    const first = new TaskStore({ persistence: { save: value => { snapshot = structuredClone(value); } } });
    const task = first.createTask(input());
    const run = first.createRun(task.taskId);
    snapshot.runs[0].status = status;
    delete snapshot.runs[0].dispatchMode; delete snapshot.runs[0].dispatchPending;
    for (let restart = 0; restart < 2; restart++) {
      const store = new TaskStore({ persistence: { load: () => snapshot, save: value => { snapshot = structuredClone(value); } } });
      assert.equal(store.requiresRecovery(run.runId), true);
      assert.throws(() => store.createRun(task.taskId), /recovery-required/);
      assert.throws(() => store.updateRun(run.runId, { status: 'running' }), /recovery-required/);
      assert.throws(() => store.settleMeshDispatch(run.runId), /recovery-required/);
    }
  });
}

for (const missing of ['dispatchMode', 'dispatchPending']) {
  test(`partially marked dispatch snapshot refuses missing ${missing}`, () => {
    let snapshot;
    const store = new TaskStore({ persistence: { save: value => { snapshot = structuredClone(value); } } });
    const task = store.createTask(input()); store.createRun(task.taskId, { dispatchMode: 'mesh' });
    delete snapshot.runs[0][missing];
    let writes = 0;
    assert.throws(() => new TaskStore({ persistence: { load: () => snapshot, save: () => { writes++; } } }), /persisted-run-invalid/);
    assert.equal(writes, 0);
  });
}

test('legacy migration durably imports validated immutable rows and preserves recovery fences', async () => {
  const fs = require('node:fs'), path = require('node:path');
  const { DurableTaskState } = require('../src/agentHarness/durableTaskState');
  const { migrateLegacyTaskState } = require('../src/agentHarness/legacyTaskMigration');
  const project = path.join(process.env.TMPDIR, 'legacy-migration-native'); fs.mkdirSync(project);
  const source = new TaskStore(); const task = source.createTask(input('legacy-native'));
  const run = source.createRun(task.taskId, { dispatchMode: 'mesh' }); source.beginMeshDispatch(run.runId);
  const snapshot = structuredClone(source.snapshot());
  const store = new TaskStore({ persistence: new DurableTaskState(project) });
  const receipt = await migrateLegacyTaskState(project, { state: snapshot }, store);
  assert.equal(receipt.status, 'MIGRATED');
  assert.deepEqual(receipt.imported_task_ids, [task.taskId]);
  assert.equal(store.requiresRecovery(run.runId), true);
  assert.throws(() => { store.requireTask(task.taskId).goal = 'unowned edit'; }, TypeError);
  const reopened = new TaskStore({ persistence: new DurableTaskState(project) });
  assert.equal(reopened.requiresRecovery(run.runId), true);
  assert.throws(() => reopened.createRun(task.taskId), /recovery-required/);
  const again = await migrateLegacyTaskState(project, snapshot, reopened);
  assert.equal(again.status, 'ALREADY_MIGRATED');
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(project, receipt.retained_source), 'utf8')), snapshot);
  await assert.rejects(migrateLegacyTaskState(project, snapshot, new TaskStore()), /native-image-missing/);
});

test('legacy import rejects a malformed later row without exposing earlier rows', async () => {
  const source = new TaskStore(); source.createTask(input('valid-first'));
  const snapshot = structuredClone(source.snapshot()); snapshot.tasks.push({ taskId: 'invalid-second' });
  let writes = 0; const store = new TaskStore({ persistence: { save: () => { writes++; } } });
  await assert.rejects(store.importLegacySnapshot(snapshot), /persisted-task-invalid/);
  assert.equal(store.listTasks().length, 0); assert.equal(writes, 0);
});

test('legacy import cannot attach a run to a conflicting native task', async () => {
  const source = new TaskStore(); const task = source.createTask(input('same-id')); source.createRun(task.taskId);
  const target = new TaskStore(); const native = target.createTask({ ...input('same-id'), goal: 'native definition' });
  const result = await target.importLegacySnapshot(source.snapshot());
  assert.deepEqual(result, { importedTasks: [], importedRuns: [] });
  assert.equal(target.requireTask(native.taskId).goal, 'native definition'); assert.equal(target.listRuns().length, 0);
});

test('legacy migration awaits durable acknowledgement before publishing its receipt', async () => {
  const fs = require('node:fs'), path = require('node:path');
  const { migrateLegacyTaskState } = require('../src/agentHarness/legacyTaskMigration');
  const project = path.join(process.env.TMPDIR, 'legacy-migration-ack'); fs.mkdirSync(project);
  const source = new TaskStore(); source.createTask(input('await-import'));
  let acknowledge; const pending = new Promise(resolve => { acknowledge = resolve; });
  const target = new TaskStore({ persistence: { save: () => pending } });
  const importing = migrateLegacyTaskState(project, source.snapshot(), target);
  try {
    await new Promise(resolve => setImmediate(resolve));
    const directory = path.join(project, '.agentic_engineering_os_px/runtime-core/agent-console/legacy-migration');
    assert.equal(fs.readdirSync(directory).some(name => name.startsWith('receipt-')), false);
  } finally { acknowledge(); }
  assert.equal((await importing).status, 'MIGRATED');
});
