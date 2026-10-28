"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { HarnessController } = require("../src/agentHarness/harnessController");
const { WorkerRegistry } = require("../src/agentHarness/workerRegistry");
const { TaskStore } = require("../src/agentHarness/taskStore");
const { BudgetLedger } = require("../src/agentHarness/budgetLedger");
const { ContextCompiler } = require("../src/agentHarness/contextCompiler");
const { TinyLibrarian } = require("../src/agentHarness/tinyLibrarian");
const { CanonicalEventBus } = require("../src/agentHarness/eventBus");
function setup({huge=false, exhausted=false, streamed=false, late=false}={}) {
  let failedCallback=null; const toolHandles=[]; const calls=[]; const registry=new WorkerRegistry();
  for (const [id,service,output] of [["a","service-a",128],["b","service-a",128],["c","service-b",huge?8192:128]]) {
    registry.register({workerId:id,adapterId:"fixture",providerId:service,modelId:`model-${id}`,displayName:id,
      costClass:"local",contextLimit:16384,locality:"local",enabled:true,reliability:1,latencyClass:"fast",
      supportedEffectClass:"READ_ONLY",capabilities:{planning:1,coding:1,review:1,classification:1,toolUse:false,vision:false,structuredOutput:false},
      bridge:{lane:"fixture",maxOutputTokens:output}}, {runTurn:async request=>{calls.push([id,request.executionContext.provider_id,request.run.providerSessionRef]);toolHandles.push(request.toolBroker);
      if(streamed&&id==="a")request.onEvent({type:"worker.stream.delta",payload:{delta:"already-visible"}});
      if(exhausted&&id==="a"){failedCallback=request.onEvent;throw Object.assign(new Error("fixture-quota"),{code:"insufficient_quota"});}
      if(late&&id==="b")failedCallback?.({type:"worker.stream.delta",payload:{delta:"failed-provider-late-output"}});
      request.onEvent({type:"fixture.output",payload:{text:id}});return {text:`answer-${id}`};}});
  }
  const host=new HarnessController({projectId:"fixture",taskStore:new TaskStore(),workerRegistry:registry,
    budgetLedger:new BudgetLedger(()=>({master_enabled:false,provider_allowlist:[]})),tinyLibrarian:new TinyLibrarian(),
    contextCompiler:new ContextCompiler(),eventBus:new CanonicalEventBus()});
  const send=selection=>host.sendTurn({goal:"explain routing",message:"hello",mode:"ASK",maxEffectClass:"READ_ONLY",contextBudgetTokens:2000,...selection});
  return {host,calls,send,toolHandles};
}
test("manual service/model routes exact native worker and is not blocked by another service output reserve",async()=>{
  const {send,calls}=setup({huge:true});const result=await send({serviceId:"service-a",modelId:"model-b",workerId:"b"});
  assert.equal(result.text,"answer-b");assert.deepEqual(calls.map(c=>c[0]),["b"]);assert.equal(calls[0][1],"service-a");
});
test("automatic model rolls past quota exhaustion within the manually selected service",async()=>{
  const {send,calls,host}=setup({exhausted:true});const result=await send({serviceId:"service-a",modelId:"auto",workerId:"auto"});
  assert.equal(result.text,"answer-b");assert.deepEqual(calls.map(c=>c[0]),["a","b"]);
  assert.ok(host.eventBus.snapshot().some(e=>e.type==="route.changed"));
});
test("manual model quota failure preserves exact selection without silently switching",async()=>{
  const {send,calls}=setup({exhausted:true});await assert.rejects(send({serviceId:"service-a",modelId:"model-a",workerId:"a"}),/fixture-quota/);
  assert.deepEqual(calls.map(c=>c[0]),["a"]);
});
test("contradictory service and model selections cannot invoke any adapter",async()=>{
  const {send,calls}=setup();const blocked=await send({serviceId:"service-b",modelId:"model-a",workerId:"a"});assert.equal(blocked.blocked,true);assert.match(blocked.reason,/service-selection/);
  assert.deepEqual(calls,[]);
});
test("automatic service and model routes an admitted candidate",async()=>{
  const {send,calls}=setup();const result=await send({serviceId:"auto",modelId:"auto",workerId:"auto"});
  assert.equal(result.text,"answer-a");assert.deepEqual(calls.map(c=>c[0]),["a"]);
});

test("selected mesh branches reserve only their eligible service models",async()=>{
  const {host,calls}=setup({huge:true});const result=await host.sendMeshTurn({goal:"compare routing",message:"hello",mode:"ASK",maxEffectClass:"READ_ONLY",contextBudgetTokens:2000,
    branches:[{serviceId:"service-a",modelId:"model-a",workerId:"a"},{serviceId:"service-a",modelId:"model-b",workerId:"b"}]});
  assert.equal(result.convergence.completedCount,2,JSON.stringify(result.branchResults));
  const events=host.eventBus.snapshot().filter(e=>e.type==="fixture.output");assert.equal(events.length,2);
  assert.equal(new Set(events.map(e=>e.executionId)).size,2);assert.ok(events.every(e=>e.traceRootId===result.run.runId&&e.executionContextSha256));
  assert.equal(host.eventBus.executionContexts.size,0);assert.deepEqual(calls.map(c=>c[0]).sort(),["a","b"]);
});
test("selected output allowance still cannot exceed the real task token budget",async()=>{
  const {send,calls}=setup({huge:true});await assert.rejects(send({serviceId:"service-b",modelId:"model-c",workerId:"c"}),/provider-request-reserve-exceeds-context-budget/);
  assert.deepEqual(calls,[]);
});

test("mesh quota failure after visible output cannot switch providers and replay work",async()=>{
  const {host,calls}=setup({exhausted:true,streamed:true});const result=await host.sendMeshTurn({goal:"safe rollover",message:"hello",mode:"ASK",maxEffectClass:"READ_ONLY",contextBudgetTokens:2000,
    branches:[{serviceId:"service-a",modelId:"auto",workerId:"auto"}]});
  assert.equal(result.convergence.failedCount,1);assert.deepEqual(calls.map(c=>c[0]),["a"]);
});

test("branch event context rejects a different branch session and tampered digest",()=>{
  const {createExecutionContext}=require("../src/agentHarness/executionContext");const bus=new CanonicalEventBus();
  const context=createExecutionContext({run:{runId:"fixture-run",epoch:1,revision:1},projectId:"fixture",sessionId:"fixture-run:branch-a",providerId:"service-a",authoritySha256:"a".repeat(64),effectBudgetSha256:"b".repeat(64)});
  assert.throws(()=>bus.setExecutionContext("fixture-run",context,{branchId:"branch-b"}),/branch-session-owner/);
  assert.throws(()=>bus.setExecutionContext("fixture-run",{...context,provider_id:"other"},{branchId:"branch-a"}),/digest-mismatch/);
  assert.equal(bus.executionContexts.size,0);
  bus.setExecutionContext("fixture-run",context,{branchId:"branch-a"});
  assert.equal(bus.emit("fixture.event",{runId:"fixture-run",branchId:"branch-a"}).executionId,context.execution_id);
  assert.equal(bus.emit("fixture.event",{runId:"fixture-run",branchId:"branch-b"}).executionId,null);
  bus.clearExecutionContext("fixture-run",{branchId:"branch-a"});assert.equal(bus.executionContexts.size,0);
});

test("automatic service with a manual model routes only services exposing that exact model",async()=>{
  const {send,calls}=setup();const result=await send({serviceId:"auto",modelId:"model-c",workerId:"auto"});
  assert.equal(result.text,"answer-c");assert.deepEqual(calls.map(c=>c[0]),["c"]);assert.equal(calls[0][1],"service-b");
});

for (const mode of ["single","mesh"]) test(`${mode} rollover discards a failed provider's late callback`,async()=>{
  const {host,send,calls}=setup({exhausted:true,late:true});
  if(mode==="single")await send({serviceId:"service-a",modelId:"auto",workerId:"auto"});
  else await host.sendMeshTurn({goal:"safe callback",message:"hello",mode:"ASK",maxEffectClass:"READ_ONLY",contextBudgetTokens:2000,branches:[{serviceId:"service-a",modelId:"auto",workerId:"auto"}]});
  assert.deepEqual(calls.map(c=>c[0]),["a","b"]);
  assert.equal(host.eventBus.snapshot().filter(e=>e.payload?.delta==="failed-provider-late-output").length,0);
});

test("completed single turn refuses tools through a provider-retained broker reference",async()=>{
  const {host,send,toolHandles}=setup();let delegated=0;host.toolBroker={execute:async()=>{delegated++;return {};}};
  await send({serviceId:"service-a",modelId:"model-a",workerId:"a"});
  assert.throws(()=>toolHandles[0].execute("read-file",{}),/worker-attempt-closed/);assert.equal(delegated,0);
});
