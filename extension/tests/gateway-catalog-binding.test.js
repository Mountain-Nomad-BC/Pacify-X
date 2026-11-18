'use strict';
const test=require('node:test');const assert=require('node:assert/strict');
const {registerAgentConsole}=require('../src/agentHarness/registerAgentConsole');
const {buildPxProviderGatewayInvoker}=require('../src/agentHarness/pxProviderInvoker');
const {McpModelFabricBridge}=require('../src/mcpModelFabricBridge');
const {sha256}=require('../src/agentHarness/ids');
const template={workerId:'native-worker',adapterId:'px-provider-gateway',providerId:'px-governed',modelId:'friendly-model',profileId:'profile',displayName:'Native fixture',costClass:'local',contextLimit:8192,locality:'local',capabilities:{coding:.5,planning:.5,review:.5,classification:.5},supportedEffectClass:'READ_ONLY',enabled:true,reliability:.8,latencyClass:'unknown'};
const row={profile_id:'profile',provider_id:'llama.cpp',adapter_id:'llama-cpp-stream',model_id:'friendly-model',model_sha256:'a'.repeat(64),profile_sha256:'b'.repeat(64),context_tokens:4096,max_output_tokens:512,lane:'control'};
function canonical(v){if(v && typeof v==='object')return Array.isArray(v)?'['+v.map(canonical).join(',')+']':'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';return JSON.stringify(v);}
function receipt(request){let value={schema_version:'px.provider-stream-receipt/1.0',provider_id:row.provider_id,model_id:row.model_sha256,adapter_id:row.adapter_id,invocation_id:request.request_id,correlation_id:request.correlation_id,input_sha256:'1'.repeat(64),output_sha256:'2'.repeat(64),budget_receipt_sha256:'3'.repeat(64),budget_reservation_receipt_sha256:'4'.repeat(64),started_revision:1,completed_revision:2,input_tokens:3,output_tokens:1,charge_microunits:0,currency:'USD',billing_state:'local_non_billable'};value.receipt_sha256=sha256(canonical(value));return value;}
function register(catalog,observe=()=>{},fabric=false){
 const values=new Map();const bridge=new McpModelFabricBridge({pythonPath:()=>'/controlled',engineRoot:()=>process.cwd(),projectRoot:()=>process.cwd(),runner:async input=>{
  if(input.operation==='list')return catalog();observe(input.payload);input.onEvent({kind:'text_delta',payload:{text:'native controlled response'}});input.onEvent({kind:'px_receipt',payload:receipt(input.payload)});return {completed:true};}});
 const disposable=()=>({dispose(){}});
 return registerAgentConsole({window:{registerWebviewViewProvider:disposable},commands:{registerCommand:disposable}},
  {workspaceState:{get:key=>values.get(key),update:async(key,value)=>{values.set(key,JSON.parse(JSON.stringify(value)));}}},
  {gatewayWorkers:[template],...(fabric ? {modelFabricLister:()=>bridge.listModels()} : {gatewayWorkerCatalog:()=>bridge.listModels()}),providerGatewayInvoker:buildPxProviderGatewayInvoker({bridge,profileIdForWorker:w=>w.profileId})});
}
function input(){return {goal:'verify native profile binding',mode:'ASK',maxEffectClass:'READ_ONLY',contextBudgetTokens:1200};}

test('actual registered host resolves native provider/model digest before strict receipt verification',async()=>{
 let request;const owner=register(async()=>({schema_version:'px.vscode-model-list/1.0',authority_granted:false,models:[row]}),value=>{request=value;});
 try{
  const result=await owner.harness.sendTurn({...input(),message:'inspect'});
  assert.equal(result.text,'native controlled response');assert.equal(result.run.status,'complete');
  assert.equal(owner.harness.workerRegistry.get(template.workerId).providerId,'llama.cpp');
  assert.equal(owner.harness.workerRegistry.get(template.workerId).modelId,row.model_sha256);
  assert.equal(request.max_output_tokens,512);
 }finally{owner.dispose();}
});

test('absent, invalidated or declared-unavailable profiles never dispatch stale template identities',async()=>{
 let models=[row],calls=0;const owner=register(async()=>({schema_version:'px.vscode-model-list/1.0',authority_granted:false,models}),()=>{calls++;});
 try{
  await owner.harness.sendTurn({...input(),message:'first'});assert.equal(calls,1);
  models=[{...row,available:false}];
  const second=await owner.harness.sendTurn({...input(),message:'second'});
  assert.equal(second.blocked,true);assert.equal(calls,1);
 }finally{owner.dispose();}
});

test('failed catalog refresh disables workers instead of replaying previous routing metadata',async()=>{
 let failed=false,calls=0;const owner=register(async()=>{if(failed)throw new Error('controlled catalog failure');return {schema_version:'px.vscode-model-list/1.0',authority_granted:false,models:[row]};},()=>{calls++;});
 try{
  await owner.harness.sendTurn({...input(),message:'first'});failed=true;
  await assert.rejects(owner.harness.sendTurn({...input(),message:'second'}),/catalog/);
  assert.equal(owner.harness.workerRegistry.get(template.workerId).enabled,false);
  assert.equal(calls,1);
 }finally{owner.dispose();}
});

test('canonical fabric host dispatches its exact native digest and clears removed profiles',async()=>{
 let models=[{...row,session_id:'local-model-session-fixture'}],calls=0,executionContext;
 const owner=register(async()=>({schema_version:'px.vscode-model-list/1.0',authority_granted:false,models}),payload=>{calls++;executionContext=payload.execution_context;},true);
 try{
  const result=await owner.harness.sendTurn({...input(),message:'first'});
  assert.equal(result.run.status,'complete');assert.equal(calls,1);
  assert.equal(executionContext.schema_version,'px.execution-context/1.0');
  assert.equal(typeof executionContext.context_sha256,'string');
  assert.equal(executionContext.provider_id,'llama.cpp');
  assert.equal(executionContext.authority_granted,false);
  const worker=owner.harness.workerRegistry.get('px-fabric-profile');
  assert.equal(worker.modelId,row.model_sha256);assert.equal(worker.maxOutputTokens,512);
  assert.equal(worker.capabilities.toolUse,false);
  assert.equal(owner.harness.eventBus.executionContexts.size,0);
  models=[];
  const blocked=await owner.harness.sendTurn({...input(),message:'second'});
  assert.equal(blocked.blocked,true);assert.equal(calls,1);
  assert.equal(owner.harness.workerRegistry.list().length,0);
 }finally{owner.dispose();}
});

test('canonical fabric refuses incomplete, conflicting or failed current identity before dispatch',async()=>{
 const valid={...row,session_id:'local-model-session-fixture'};
 let models=[valid],fail=false,calls=0;
 const owner=register(async()=>{if(fail)throw new Error('catalog failed');return {schema_version:'px.vscode-model-list/1.0',authority_granted:false,models};},()=>{calls++;},true);
 try{
  await owner.harness.sendTurn({...input(),message:'first'});assert.equal(calls,1);
  for(const mutation of [{profile_sha256:null},{session_id:null},{provider_id:'foreign'},{max_output_tokens:8193},{available:false}]){
   models=[{...valid,...mutation}];
   assert.equal((await owner.harness.sendTurn({...input(),message:'denied'})).blocked,true);
  }
  models=[valid,{...valid,model_sha256:'c'.repeat(64)}];
  assert.equal((await owner.harness.sendTurn({...input(),message:'ambiguous'})).blocked,true);
  assert.equal(owner.modelCatalog.state,'unavailable');
  fail=true;
  assert.equal((await owner.harness.sendTurn({...input(),message:'unavailable'})).blocked,true);
  assert.equal(owner.harness.workerRegistry.list().length,0);assert.equal(calls,1);
 }finally{owner.dispose();}
});
