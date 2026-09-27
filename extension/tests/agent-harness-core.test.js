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

test('context compiler dedupes and honors budget', async()=>{ const store=new TaskStore(); const t=task(store,{contextBudgetTokens:50}); const compiler=new ContextCompiler(); const pack=await compiler.compile({task:t,librarian:{retrievalRequired:false},explicitRefs:[{refId:'a',kind:'x',label:'A',content:'x'.repeat(80)},{refId:'b',kind:'x',label:'B',content:'y'.repeat(400)}]}); assert.equal(pack.selectedCount,1); assert.ok(pack.suppliedTokens>=20); });

test('tiny librarian fallback produces visible structured classification',async()=>{const store=new TaskStore();const t=task(store);const lib=await new TinyLibrarian().classify(t,'pytest is hanging in test_structural_integrity.py');assert.equal(lib.intent,'debug-test-hang');assert.ok(lib.domains.includes('python'));assert.equal(lib.source,'deterministic-fallback');});

test('completion requires execution evidence and ignores prose',()=>{const store=new TaskStore();const t=task(store,{completionContract:[{id:'test-pass',required:true,label:'Targeted test passed',evidenceTypes:['test-result']}]});assert.equal(evaluateCompletion(t,[]).complete,false);assert.equal(evaluateCompletion(t,[{evidenceId:'e1',taskId:t.taskId,runId:'run-1',type:'test-result',status:'pass',summary:'pass',sourceRef:null,sha256:null,capturedAt:new Date().toISOString()}]).complete,true);});
