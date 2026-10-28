"use strict";
const test=require('node:test'); const assert=require('node:assert/strict');
const {TaskStore}=require('../src/agentHarness/taskStore'); const {ToolBroker}=require('../src/agentHarness/toolBroker');
const {nowIso}=require('../src/agentHarness/ids');
const {createExecutionContext}=require('../src/agentHarness/executionContext');
function fixture(options={}) {
 const store=new TaskStore();const task=store.createTask({goal:'inspect',mode:'DIAGNOSE',maxEffectClass:options.maxEffectClass||'READ_ONLY',contextBudgetTokens:1000,taskCostCeilingUsd:0,localFirst:true,requireApprovalBeforeBillable:true});
 let run=store.createRun(task.taskId);run=store.selectWorker(run.runId,'worker','test');let calls=0;
 const broker=new ToolBroker({taskStore:store,approvalProvider:options.approvalProvider});
 broker.register({toolId:'probe',effectClass:options.effectClass||'READ_ONLY',execute:async()=>{calls++;return {summary:'inspected',output:1,evidence:options.evidence?.(task,run)||[]};}});
 const request={requestId:'request',taskId:task.taskId,runId:run.runId,workerId:'worker',toolId:'probe',effectClass:options.effectClass||'READ_ONLY',arguments:{},scopeRefs:[],requestedAt:nowIso()};
 const executionContext=createExecutionContext({run,projectId:'prj-fixture',sessionId:run.runId,providerId:'fixture',authoritySha256:'a'.repeat(64),effectBudgetSha256:'b'.repeat(64)});
 return {store,task,run,broker,request,executionContext,calls:()=>calls};
}
test('actual task/run/selected worker may execute read-only tool',async()=>{const f=fixture();assert.equal((await f.broker.execute(f.request,f.task,f.executionContext)).status,'succeeded');assert.equal(f.calls(),1);});
for(const field of ['taskId','runId','workerId'])test(`tool rejects foreign ${field} before side effect`,async()=>{const f=fixture();const result=await f.broker.execute({...f.request,[field]:'foreign'},f.task,f.executionContext);assert.equal(result.status,'blocked');assert.equal(f.calls(),0);});
test('caller cannot raise stored effect ceiling by forging task snapshot',async()=>{const f=fixture({effectClass:'MUTATING',approvalProvider:async()=>true});const forged={...f.task,constraints:{...f.task.constraints,maxEffectClass:'HIGH_RISK'}};assert.equal((await f.broker.execute(f.request,forged,f.executionContext)).status,'blocked');assert.equal(f.calls(),0);});
test('truthy approval object is not explicit approval',async()=>{const f=fixture({maxEffectClass:'MUTATING',effectClass:'MUTATING',approvalProvider:async()=>({approved:false})});assert.equal((await f.broker.execute(f.request,f.task,f.executionContext)).status,'blocked');assert.equal(f.calls(),0);});
test('cancellation while approval awaits fences dispatch',async()=>{let approve;let entered;const waiting=new Promise(resolve=>entered=resolve);const f=fixture({maxEffectClass:'MUTATING',effectClass:'MUTATING',approvalProvider:()=>{entered();return new Promise(resolve=>approve=resolve);}});const pending=f.broker.execute(f.request,f.task,f.executionContext);await waiting;f.store.updateTask(f.task.taskId,{status:'cancelled'});approve(true);assert.equal((await pending).status,'blocked');assert.equal(f.calls(),0);});
test('foreign tool evidence cannot publish successful receipt',async()=>{const f=fixture({evidence:()=>[{evidenceId:'e',taskId:'foreign',runId:'foreign',type:'test-result',status:'pass',summary:'external',sourceRef:null,sha256:null,capturedAt:nowIso()}]});const result=await f.broker.execute(f.request,f.task,f.executionContext);assert.equal(result.status,'failed');assert.deepEqual(result.evidence,[]);});
test('missing current store authority fails closed',async()=>{let calls=0;const f=fixture();const b=new ToolBroker();b.register({toolId:'probe',effectClass:'READ_ONLY',execute:async()=>{calls++;return {summary:'unexpected'};}});assert.equal((await b.execute(f.request,f.task,f.executionContext)).status,'blocked');assert.equal(calls,0);});

test('tool dispatch waits for current task policy persistence acknowledgement',async()=>{const f=fixture();let acknowledge;f.store.persistence={save:()=>new Promise(resolve=>acknowledge=resolve)};f.store.updateTask(f.task.taskId,{stage:'VERIFY'});const pending=f.broker.execute(f.request,f.task,f.executionContext);await new Promise(resolve=>setImmediate(resolve));assert.equal(f.calls(),0);acknowledge();assert.equal((await pending).status,'succeeded');});
test('approval receives immutable request arguments and cannot substitute authority',async()=>{let blockedMutation=false;const f=fixture({maxEffectClass:'MUTATING',effectClass:'MUTATING',approvalProvider:async({request})=>{try{request.workerId='foreign';}catch{blockedMutation=true;}return true;}});assert.equal((await f.broker.execute(f.request,f.task,f.executionContext)).status,'succeeded');assert.equal(blockedMutation,true);});


test('tool refuses a missing execution context even with current stored authority',async()=>{const f=fixture();await assert.rejects(f.broker.execute(f.request,f.task),/execution-context-required/);assert.equal(f.calls(),0);});
