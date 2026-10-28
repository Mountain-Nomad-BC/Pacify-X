
'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {CodexAppServerAdapter}=require('../src/agentHarness/adapters/codexAppServer');
const {createExecutionContext}=require('../src/agentHarness/executionContext');

// Recording wire fixture only: it does not stand in for native custody evidence.
function fixture({status='completed',usage=true,reroute=false,wrongManual=false,stale=false,serverRequest=false,runId='fixture-run'}={}) {
 const context=createExecutionContext({run:{runId,epoch:1,revision:1},projectId:'p',sessionId:'s',providerId:'codex',authoritySha256:'a'.repeat(64),effectBudgetSha256:'b'.repeat(64)});
 let listener;const sent=[];let current=true;let closes=0;let settlements=0;
 const notify=(method,params)=>queueMicrotask(()=>listener(JSON.stringify({method,params})));
 const handle={modelId:wrongManual?'other-model':'approved-fixture-model',protocolSchemaSha256:'c'.repeat(64),subscribe(fn){listener=fn;return()=>{listener=()=>{};};},async writeLine(line){
  const m=JSON.parse(line);sent.push(m);if(!m.id)return;
  let result={};
  if(m.method==='thread/start')result={thread:{id:'fixture-thread'}};
  if(m.method==='turn/start')result={turn:{id:'fixture-turn',status:'inProgress'}};
  queueMicrotask(()=>listener(JSON.stringify({id:m.id,result})));
  if(m.method==='turn/start')setTimeout(()=>{
   const base={threadId:'fixture-thread',turnId:'fixture-turn'};
   notify('item/agentMessage/delta',{...base,turnId:'foreign-turn',delta:'unrelated'});
   if(stale)current=false;
   if(serverRequest)queueMicrotask(()=>listener(JSON.stringify({id:'approval-1',method:'item/commandExecution/requestApproval',params:{...base,itemId:'effect-1'}})));
   if(reroute)notify('model/rerouted',{...base,fromModel:handle.modelId,toModel:'foreign-model'});
   notify('item/agentMessage/delta',{...base,delta:'hello'});
   if(usage)notify('thread/tokenUsage/updated',{...base,tokenUsage:{last:{inputTokens:3,outputTokens:1,totalTokens:4},total:{inputTokens:100,outputTokens:100,totalTokens:200}}});
   notify('turn/completed',{threadId:'fixture-thread',turn:{id:'fixture-turn',status}});
  },2);
 }};
 const owner={async open(){return handle;},async assertCurrent(actual){assert.equal(actual.context_sha256,context.context_sha256);if(!current)throw new Error('native-owner-revoked');},async settle(){settlements++;return {fixture:'recording-native-owner-contract-only'};},async close(){closes++;}};
 const adapter=new CodexAppServerAdapter({nativeOwner:owner,rpcTimeoutMs:100});
 const input={executionContext:context,run:{runId},preparedGroupReference:{schema_version:'px.prepared-group-reference/1.0',plan_id:'task-plan-'+ 'd'.repeat(24),plan_sha256:'e'.repeat(64)},serviceId:'codex',modelId:'approved-fixture-model',message:'bounded question',onEvent:()=>{}};
 return {adapter,input,owner,handle,sent,get closes(){return closes;},get settlements(){return settlements;}};
}

test('uncommissioned adapter does not probe or launch a process',async()=>{
 const cp=require('node:child_process');const original=cp.spawnSync;let calls=0;cp.spawnSync=()=>{calls++;return {status:0,stdout:'fake version'};};
 try{assert.equal((await new CodexAppServerAdapter().health()).status,'unavailable');assert.equal(calls,0);}finally{cp.spawnSync=original;}
});

test('recording native protocol preserves exact manual model and per-turn usage',async()=>{
 const f=fixture();const out=await f.adapter.runTurn(f.input);assert.equal(out.text,'hello');assert.equal(out.usage.inputTokens,3);assert.equal(f.settlements,1);assert.equal(f.closes,1);
 assert.equal(f.sent.find(m=>m.method==='thread/start').params.model,f.input.modelId);assert.equal(f.sent.find(m=>m.method==='turn/start').params.model,f.input.modelId);
 assert.equal(f.sent.find(m=>m.method==='initialize').params.capabilities.experimentalApi,false);
});

for(const options of [{status:'failed'},{status:'interrupted'},{usage:false},{reroute:true},{wrongManual:true},{stale:true},{serverRequest:true}])test('unclosed or substituted native protocol cannot settle '+JSON.stringify(options),async()=>{
 const f=fixture(options);await assert.rejects(f.adapter.runTurn(f.input));assert.equal(f.settlements,0);assert.equal(f.closes,1);
});

test('caller approval boolean and unsigned hints cannot replace a prepared reference',async()=>{
 const f=fixture();delete f.input.preparedGroupReference;f.input.approved=true;await assert.rejects(f.adapter.runTurn(f.input),/prepared-reference/);assert.equal(f.sent.length,0);
});

test('wrong execution cancellation cannot interrupt another owned turn',async()=>{
 const f=fixture();assert.equal(await f.adapter.interrupt({...f.input.executionContext,execution_id:'foreign'}),false);assert.equal(f.sent.length,0);
});

test('native open failure still reconciles scope and cleanup cannot mask primary',async()=>{
 const f=fixture();const primary=new Error('native-open-uncertain');f.owner.open=async()=>{throw primary;};f.owner.close=async(context,handle)=>{assert.equal(handle,null);throw new Error('custody-uncertain');};
 await assert.rejects(f.adapter.runTurn(f.input),error=>error===primary && error.custodyCleanupError.message==='custody-uncertain');
});


test('concurrent recording executions retain independent thread/turn and cleanup owners',async()=>{
 const first=fixture({runId:'first-run'}),second=fixture({runId:'second-run'});
 const owners=new Map([[first.input.executionContext.execution_id,first.owner],[second.input.executionContext.execution_id,second.owner]]);
 const broker={open:request=>owners.get(request.executionContext.execution_id).open(request),assertCurrent:(context,handle)=>owners.get(context.execution_id).assertCurrent(context,handle),settle:request=>owners.get(request.executionContext.execution_id).settle(request),close:(context,handle)=>owners.get(context.execution_id).close(context,handle)};
 const adapter=new CodexAppServerAdapter({nativeOwner:broker,rpcTimeoutMs:100});
 const results=await Promise.all([adapter.runTurn(first.input),adapter.runTurn(second.input)]);
 assert.deepEqual(results.map(x=>x.text),['hello','hello']);assert.equal(first.closes,1);assert.equal(second.closes,1);assert.equal(adapter.executions.size,0);
});
