'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { HarnessController, assertPersonalContextDispatchUnavailable } = require('../src/agentHarness/harnessController');
const { ContextCompiler } = require('../src/agentHarness/contextCompiler');
const { TaskStore } = require('../src/agentHarness/taskStore');

for (const [label, ref] of Object.entries({ kind: {kind:'personal-use-context'}, source: {source:'personal-store:1:abc'}, provenance: {content:JSON.stringify({copy_kind:'ephemeral-personal-context'})}, requirement: {content:JSON.stringify({requires_current_native_use_before_provider_dispatch:true})} })) {
  test(`provider boundary denies ${label} personal copy marker`, () => {
    assert.throws(() => assertPersonalContextDispatchUnavailable({refs:[ref]}), /not-commissioned/);
  });
}
test('ordinary context remains dispatchable', () => {
  assert.doesNotThrow(() => assertPersonalContextDispatchUnavailable({refs:[{kind:'cognitive-reference',source:'engine:cognitive-map',content:'ordinary'}]}));
});
test('normal turn refuses normalized personal copy before cache and provider effects', async () => {
  const store = new TaskStore();
  const task = store.createTask({goal:'fixture',mode:'DIAGNOSE',maxEffectClass:'READ_ONLY',contextBudgetTokens:12000});
  let providerCalls=0;
  const events=[];
  const controller = new HarnessController({taskStore:store,
    workerRegistry:{list:()=>[],adapter:()=>({runTurn:async()=>{providerCalls++;}})},
    contextCompiler:new ContextCompiler({retrievalProvider:async()=>[{kind:'ordinary',source:'engine:fixture',content:JSON.stringify({copy_kind:'ephemeral-personal-context',content:{name:'private fixture'}})}]}),
    tinyLibrarian:{classify:async()=>({stage:'PLAN',skillCandidates:[],confidence:1,intent:'fixture',domains:[],retrievalRequired:true}),recall:async()=>[]},
    eventBus:{emit:(type,event)=>events.push({type,...event}),clearExecutionContext:()=>{}},budgetLedger:{},projectId:'fixture'});
  await assert.rejects(controller.sendTurn({taskId:task.taskId,message:'fixture'}), /not-commissioned/);
  assert.equal(providerCalls,0); assert.equal(controller.lastContext.size,0);
  assert.equal(events.some(event=>event.type==='context.compiled'),false);
  assert.equal(JSON.stringify(events).includes('private fixture'),false);
  assert.equal(store.snapshot().runs[0].lastError,'personal-context-provider-transport-not-commissioned');
});

test('mesh branch refuses personal context before its adapter starts', async () => {
  let calls=0;
  const descriptor={workerId:'fixture-worker',adapterId:'mock',providerId:'local',modelId:'fixture',displayName:'Fixture',costClass:'local',contextLimit:8192,locality:'local',capabilities:{coding:1,planning:1,review:1,classification:1,toolUse:false,vision:false,structuredOutput:false},supportedEffectClass:'READ_ONLY',enabled:true,reliability:1,latencyClass:'fast'};
  const controller=Object.create(HarnessController.prototype);
  const abort=new AbortController();
  controller.active=new Map([['fixture-run',{controllers:new Map([[0,abort]]),branchWorkerIds:new Map()}]]);
  controller.workerRegistry={list:()=>[descriptor],getHealth:()=>({status:'healthy'}),adapter:()=>({runTurn:async()=>{calls++;return {text:'forbidden'};}})};
  controller.budgetLedger={canAdmit:()=>({allowed:true})};
  controller.eventBus={setExecutionContext:()=>{},clearExecutionContext:()=>{},emit:()=>{}};
  controller.projectId='fixture';
  const result=await controller._runMeshBranch({task:{taskId:'fixture-task',mode:'DIAGNOSE',constraints:{maxEffectClass:'READ_ONLY',taskCostCeilingUsd:null,localFirst:true,requireApprovalBeforeBillable:true}},run:{runId:'fixture-run',epoch:1,revision:1,round:0},meshId:'fixture-mesh',branchIndex:0,branchRequest:{workerId:'fixture-worker'},contextPack:{suppliedTokens:100,refs:[{source:'personal-store:1:sha'}]},requestReserveTokens:100,message:'fixture'});
  assert.equal(result.state,'failed'); assert.equal(calls,0);
});
