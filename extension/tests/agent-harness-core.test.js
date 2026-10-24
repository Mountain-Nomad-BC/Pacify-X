'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { CanonicalEventBus } = require('../src/agentHarness/eventBus');
const { TaskStore } = require('../src/agentHarness/taskStore');
const { BudgetLedger } = require('../src/agentHarness/budgetLedger');
const { WorkerRegistry } = require('../src/agentHarness/workerRegistry');
const { WorkerDescriptor, parse } = require('../src/agentHarness/contracts');
const { chooseWorker } = require('../src/agentHarness/router');
const { ContextCompiler } = require('../src/agentHarness/contextCompiler');
const { HarnessController } = require('../src/agentHarness/harnessController');
const { TinyLibrarian } = require('../src/agentHarness/tinyLibrarian');
const { evaluateCompletion } = require('../src/agentHarness/completionEvaluator');
const { MockAdapter } = require('../src/agentHarness/adapters/mock');

function task(store, overrides={}) { return store.createTask({ goal:'debug the hanging test', mode:'DIAGNOSE', maxEffectClass:'READ_ONLY', contextBudgetTokens:1200, taskCostCeilingUsd:0.2, localFirst:true, requireApprovalBeforeBillable:true, completionContract:[], ...overrides }); }

test('worker registry accepts an explicit provider profile and only declared latency classes', () => {
  const descriptor = {
    workerId: 'profiled-local', adapterId: 'gateway', providerId: 'px-governed',
    modelId: 'model', profileId: 'control-profile', displayName: 'Profiled local',
    costClass: 'local', contextLimit: 8192, locality: 'local',
    capabilities: { coding: 0.5, planning: 0.5, review: 0.5, classification: 0.5 },
    supportedEffectClass: 'READ_ONLY', enabled: true, reliability: 0.5,
    latencyClass: 'unknown'
  };
  const registry = new WorkerRegistry();
  registry.register(descriptor, new MockAdapter());
  assert.equal(registry.get('profiled-local').profileId, 'control-profile');
  assert.throws(
    () => parse(WorkerDescriptor, { ...descriptor, latencyClass: 'bounded' }, 'worker-descriptor'),
    /worker-descriptor-invalid:latencyClass:/
  );
});

test('canonical event bus is bounded and monotonic', () => { const bus=new CanonicalEventBus({maxEvents:50}); for(let i=0;i<70;i++)bus.emit('test.event',{summary:String(i)}); const rows=bus.snapshot(); assert.equal(rows.length,50); assert.ok(rows.every((r,i)=>i===0||r.sequence>rows[i-1].sequence)); });

test('router never selects a deterministically rejected worker', () => { const store=new TaskStore(); const t=task(store); const ledger=new BudgetLedger(()=>({master_enabled:false,provider_allowlist:[]})); const registry=new WorkerRegistry(); registry.register({workerId:'paid',adapterId:'x',providerId:'paid-provider',modelId:'m',displayName:'Paid',costClass:'billable-api',contextLimit:10000,locality:'remote',capabilities:{coding:1,planning:1,review:1,classification:1,toolUse:false,vision:false,structuredOutput:false},supportedEffectClass:'READ_ONLY',enabled:true,reliability:1,latencyClass:'fast'},new MockAdapter()); registry.register({workerId:'local',adapterId:'x',providerId:'local-provider',modelId:'m2',displayName:'Local',costClass:'local',contextLimit:10000,locality:'local',capabilities:{coding:.5,planning:.5,review:.5,classification:.5,toolUse:false,vision:false,structuredOutput:false},supportedEffectClass:'READ_ONLY',enabled:true,reliability:.8,latencyClass:'medium'},new MockAdapter()); const route=chooseWorker(registry,{task:t,contextTokens:100,budgetLedger:ledger,requiredToolUse:false,requestedWorkerId:'auto',projectedChargeUsd:{},failureCounts:{}}); assert.equal(route.selected.workerId,'local'); assert.ok(route.evaluated.find(r=>r.worker.workerId==='paid').reasons.includes('billable-disabled')); });

test('context compiler dedupes and honors budget', async()=>{ const store=new TaskStore(); const t=task(store,{contextBudgetTokens:500}); const compiler=new ContextCompiler(); const pack=await compiler.compile({task:t,librarian:{retrievalRequired:false},explicitRefs:[{refId:'a',kind:'x',label:'A',content:'x'.repeat(80)},{refId:'b',kind:'x',label:'B',content:'x'.repeat(80)}]}); assert.equal(pack.selectedCount,1); assert.ok(pack.suppliedTokens>=20); });

test('context compiler rejects a budget smaller than the task instruction', async()=>{ const store=new TaskStore(); const t=task(store,{contextBudgetTokens:50}); const compiler=new ContextCompiler(); await assert.rejects(compiler.compile({task:t,librarian:{retrievalRequired:false}}),/task-instruction-exceeds-context-budget/); });

test('context compiler reserves request message, output, and protocol tokens before selecting refs', async()=>{ const store=new TaskStore(); const t=task(store,{contextBudgetTokens:1200}); const compiler=new ContextCompiler(); const pack=await compiler.compile({task:t,librarian:{retrievalRequired:false},requestReserveTokens:500}); assert.equal(pack.budgetTokens,700); assert.ok(pack.suppliedTokens<=700); });

test('context compiler rejects request reservations beyond the task budget', async()=>{ const store=new TaskStore(); const t=task(store,{contextBudgetTokens:1200}); const compiler=new ContextCompiler(); await assert.rejects(compiler.compile({task:t,librarian:{retrievalRequired:false},requestReserveTokens:1200}),/provider-request-reserve-exceeds-context-budget/); });

test('context compiler rejects a non-integer or non-finite request reservation', async()=>{ const store=new TaskStore(); const t=task(store,{contextBudgetTokens:1200}); const compiler=new ContextCompiler(); for(const requestReserveTokens of [NaN,Infinity,1.5,-1]) await assert.rejects(compiler.compile({task:t,librarian:{retrievalRequired:false},requestReserveTokens}),/provider-request-reserve-invalid/); });

test('cancelling a mesh run aborts all branches and interrupts each active worker', async()=>{ const abort=new AbortController(); const branchA=new AbortController(); const branchB=new AbortController(); const interrupted=[]; const events=[]; let run={runId:'run-1',taskId:'task-1',status:'running'}; const controller=Object.create(HarnessController.prototype); controller.active=new Map([['run-1',{abort,controllers:new Map([[0,branchA],[1,branchB]]),branchWorkerIds:new Map([[0,'worker-a'],[1,'worker-b']])}]]); controller.taskStore={requireRun:()=>run,updateRun:(_id,patch)=>{run={...run,...patch};return run;},flush:async()=>{}}; controller.workerRegistry={adapter:id=>({interrupt:async()=>{interrupted.push(id);return true;}})}; controller.eventBus={emit:(type,event)=>events.push({type,...event})}; assert.equal(await controller.cancelRun('run-1'),true); assert.equal(run.status,'cancelled'); assert.equal(abort.signal.aborted,true); assert.equal(branchA.signal.aborted,true); assert.equal(branchB.signal.aborted,true); assert.deepEqual(interrupted.sort(),['worker-a','worker-b']); assert.equal(events.length,0); });

test('local mesh refuses tasks with a non-read-only effect budget', async () => {
  const controller = Object.create(HarnessController.prototype);
  controller.taskStore = {
    requireTask: () => ({ taskId: 'task-mesh', constraints: { maxEffectClass: 'MUTATING' } })
  };

  await assert.rejects(
    controller.sendMeshTurn({ taskId: 'task-mesh', branches: [{}] }),
    /mesh-read-only-task-required/
  );
});

test('mesh cancellation reports worker interruption failures without undoing cancellation', async()=>{ let run={runId:'run-2',taskId:'task-2',status:'running'}; const events=[]; const controller=Object.create(HarnessController.prototype); controller.active=new Map([['run-2',{controllers:new Map(),branchWorkerIds:new Map([[0,'worker-failed']])}]]); controller.taskStore={requireRun:()=>run,updateRun:(_id,patch)=>{run={...run,...patch};return run;},flush:async()=>{}}; controller.workerRegistry={adapter:()=>({interrupt:async()=>{throw new Error('adapter-interrupt-error');}})}; controller.eventBus={emit:(type,event)=>events.push({type,...event})}; assert.equal(await controller.cancelRun('run-2'),true); assert.equal(run.status,'cancelled'); assert.equal(events.length,1); assert.equal(events[0].type,'worker.interrupt.result'); assert.equal(events[0].status,'failed'); assert.equal(events[0].payload.reason,'adapter-interrupt-error'); });

test('a mesh branch discards late provider output and events after cancellation', async()=>{ const abort=new AbortController(); let completeTurn; let onEvent; const emitted=[]; const descriptor={workerId:'worker-late',adapterId:'mock',providerId:'local',modelId:'m',displayName:'Late worker',costClass:'local',contextLimit:8192,locality:'local',capabilities:{coding:1,planning:1,review:1,classification:1,toolUse:false,vision:false,structuredOutput:false},supportedEffectClass:'READ_ONLY',enabled:true,reliability:1,latencyClass:'fast'}; const adapter={runTurn:async request=>{onEvent=request.onEvent;return new Promise(resolve=>{completeTurn=resolve;});}}; const contexts=[]; const controller=Object.create(HarnessController.prototype); controller.active=new Map([['run-3',{controllers:new Map([[0,abort]]),branchWorkerIds:new Map()}]]); controller.workerRegistry={list:()=>[descriptor],getHealth:()=>({status:'healthy'}),adapter:()=>adapter}; controller.budgetLedger={canAdmit:()=>({allowed:true})}; controller.eventBus={setExecutionContext:(_id,context)=>contexts.push(context),clearExecutionContext:()=>{},emit:(type,event)=>emitted.push({type,...event})}; controller.projectId='workspace'; const task={taskId:'task-3',mode:'DIAGNOSE',constraints:{maxEffectClass:'READ_ONLY',taskCostCeilingUsd:null,localFirst:true,requireApprovalBeforeBillable:true}}; const run={runId:'run-3',epoch:1,revision:1,round:0}; const branch=controller._runMeshBranch({task,run,meshId:'mesh-3',branchIndex:0,branchRequest:{workerId:'worker-late'},contextPack:{suppliedTokens:100},requestReserveTokens:100,message:'hello'}); await Promise.resolve(); abort.abort(); onEvent({type:'worker.stream.delta',payload:{delta:'late'}}); completeTurn({text:'late result'}); const result=await branch; assert.equal(result.state,'cancelled'); assert.equal(result.text,undefined); assert.equal(result.conclusion,''); assert.equal(contexts.length,1); assert.deepEqual(emitted,[]); });

test('single-turn cancellation discards late provider output and events', async () => {
  const taskStore = new TaskStore();
  const currentTask = task(taskStore);
  const run = taskStore.createRun(currentTask.taskId);
  const events = [];
  let completeTurn;
  let onEvent;
  const descriptor = {
    workerId: 'worker-late-single', adapterId: 'mock', providerId: 'local',
    modelId: 'm', displayName: 'Late worker', costClass: 'local',
    contextLimit: 8192, locality: 'local',
    capabilities: {
      coding: 1, planning: 1, review: 1, classification: 1,
      toolUse: false, vision: false, structuredOutput: false
    },
    supportedEffectClass: 'READ_ONLY', enabled: true, reliability: 1,
    latencyClass: 'fast'
  };
  const adapter = {
    runTurn: request => {
      onEvent = request.onEvent;
      return new Promise(resolve => { completeTurn = resolve; });
    },
    interrupt: async () => true
  };
  const workerRegistry = new WorkerRegistry();
  workerRegistry.register(descriptor, adapter);
  const controller = new HarnessController({
    taskStore,
    workerRegistry,
    eventBus: {
      emit: (type, event) => events.push({ type, ...event }),
      setExecutionContext: () => {},
      clearExecutionContext: () => {}
    },
    tinyLibrarian: {
      classify: async () => ({
        stage: 'PLAN', skillCandidates: [], confidence: 1,
        intent: 'test', domains: []
      }),
      recall: async () => []
    },
    contextCompiler: {
      compile: async () => ({
        selectedCount: 0, consideredCount: 0, suppliedTokens: 0,
        budgetTokens: 1200, refs: []
      })
    },
    budgetLedger: {
      canAdmit: () => ({ allowed: true }),
      summary: () => ({})
    },
    projectId: 'project'
  });
  const pending = controller.sendTurn({
    taskId: currentTask.taskId, runId: run.runId, message: 'hello'
  });
  for (let attempts = 0; !completeTurn && attempts < 20; attempts++) {
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.equal(typeof completeTurn, 'function');

  await controller.cancelRun(run.runId);
  onEvent({ type: 'worker.stream.delta', payload: { delta: 'late' } });
  completeTurn({ text: 'late result' });
  await assert.rejects(pending, /turn-aborted/);

  assert.equal(taskStore.requireRun(run.runId).status, 'cancelled');
  assert.equal(events.some(event => event.type === 'worker.completed'), false);
  assert.equal(events.some(event => event.payload?.delta === 'late'), false);
});

test('mesh disposal aborts branches and discards their late completion',async()=>{ const abort=new AbortController(); let completeTurn; const descriptor={workerId:'worker-disposed',adapterId:'mock',providerId:'local',modelId:'m',displayName:'Disposed worker',costClass:'local',contextLimit:8192,locality:'local',capabilities:{coding:1,planning:1,review:1,classification:1,toolUse:false,vision:false,structuredOutput:false},supportedEffectClass:'READ_ONLY',enabled:true,reliability:1,latencyClass:'fast'}; const adapter={runTurn:async()=>new Promise(resolve=>{completeTurn=resolve;})}; const controller=Object.create(HarnessController.prototype); controller.active=new Map([['run-4',{controllers:new Map([[0,abort]]),branchWorkerIds:new Map()}]]); controller.workerRegistry={list:()=>[descriptor],getHealth:()=>({status:'healthy'}),adapter:()=>adapter}; controller.budgetLedger={canAdmit:()=>({allowed:true})}; controller.eventBus={setExecutionContext:()=>{},clearExecutionContext:()=>{},dispose:()=>{}}; controller.projectId='workspace'; const task={taskId:'task-4',mode:'DIAGNOSE',constraints:{maxEffectClass:'READ_ONLY',taskCostCeilingUsd:null,localFirst:true,requireApprovalBeforeBillable:true}}; const run={runId:'run-4',epoch:1,revision:1,round:0}; const branch=controller._runMeshBranch({task,run,meshId:'mesh-4',branchIndex:0,branchRequest:{workerId:'worker-disposed'},contextPack:{suppliedTokens:100},requestReserveTokens:100,message:'hello'}); await Promise.resolve(); controller.dispose(); assert.equal(abort.signal.aborted,true); assert.equal(controller.active.size,0); completeTurn({text:'late result'}); assert.equal((await branch).state,'cancelled'); });

test('mesh cancellation reports worker interruption timeout without undoing cancellation',async()=>{ let run={runId:'run-5',taskId:'task-5',status:'running'}; const events=[]; const controller=Object.create(HarnessController.prototype); controller.active=new Map([['run-5',{controllers:new Map(),branchWorkerIds:new Map([[0,'worker-timeout']])}]]); controller.taskStore={requireRun:()=>run,updateRun:(_id,patch)=>{run={...run,...patch};return run;},flush:async()=>{}}; controller.workerRegistry={adapter:()=>({interrupt:()=>new Promise(()=>{})})}; controller.eventBus={emit:(type,event)=>events.push({type,...event})}; assert.equal(await controller.cancelRun('run-5'),true); assert.equal(run.status,'cancelled'); assert.equal(events.length,1); assert.equal(events[0].type,'worker.interrupt.result'); assert.equal(events[0].status,'info'); assert.equal(events[0].payload.interruptStatus,'timeout'); });

test('tiny librarian fallback produces visible structured classification',async()=>{const store=new TaskStore();const t=task(store);const lib=await new TinyLibrarian().classify(t,'pytest is hanging in test_structural_integrity.py');assert.equal(lib.intent,'debug-test-hang');assert.ok(lib.domains.includes('python'));assert.equal(lib.source,'deterministic-fallback');});

test('completion requires execution evidence and ignores prose',()=>{const store=new TaskStore();const t=task(store,{completionContract:[{id:'test-pass',required:true,label:'Targeted test passed',evidenceTypes:['test-result']}]});assert.equal(evaluateCompletion(t,[]).complete,false);assert.equal(evaluateCompletion(t,[{evidenceId:'e1',taskId:t.taskId,runId:'run-1',type:'test-result',status:'pass',summary:'pass',sourceRef:null,sha256:null,capturedAt:new Date().toISOString()}]).complete,true);});
