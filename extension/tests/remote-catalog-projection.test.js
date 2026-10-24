'use strict';
const test=require('node:test'); const assert=require('node:assert/strict');
const {projectFabricModel}=require('../src/agentHarness/registerAgentConsole');
const {WorkerDescriptor,parse}=require('../src/agentHarness/contracts');
const {WorkerRegistry}=require('../src/agentHarness/workerRegistry');
const {chooseWorker}=require('../src/agentHarness/router');
const row={profile_id:'custom-profile',provider_id:'custom',adapter_id:'custom-openai-chat',
  model_id:'declared-custom-model',context_tokens:8192,max_output_tokens:1024,lane:'remote',
  bridge_kind:'remote',profile_sha256:'a'.repeat(64),locality:'remote',cost_class:'billable-api',
  available:false,unavailable_reason:'remote-prepared-member-not-implemented',
  capabilities:{coding:.2,planning:.3,review:.4,classification:.5,toolUse:false,vision:false,structuredOutput:false}};
test('normal projection retains explicit remote service/model/config identity unavailable',()=>{
  const worker=parse(WorkerDescriptor,projectFabricModel(row),'worker');
  assert.equal(worker.providerId,'custom'); assert.equal(worker.modelId,row.model_id);
  assert.equal(worker.locality,'remote');assert.equal(worker.costClass,'billable-api');
  assert.equal(worker.bridge.bridgeKind,'remote');assert.equal(worker.bridge.profileSha256,row.profile_sha256);
  assert.equal(worker.bridge.modelSha256,null); assert.equal(worker.enabled,false);
  const registry=new WorkerRegistry();registry.register(worker,{runTurn:async()=>{assert.fail('unavailable remote dispatched');}});
  const input={task:{mode:'DIAGNOSE',constraints:{maxEffectClass:'READ_ONLY',localFirst:true}},contextTokens:100,budgetLedger:{canAdmit:()=>({allowed:true})}};
  assert.equal(chooseWorker(registry,input).selected,null);
  assert.equal(chooseWorker(registry,{...input,requestedServiceId:'custom',requestedModelId:row.model_id}).selected,null);
});
test('remote identity cannot masquerade as local artifact or admit itself',()=>{
  for(const mutation of [{locality:'local'},{cost_class:'local'},{model_sha256:'b'.repeat(64)},{provider_id:'codex'},{profile_sha256:null},{available:true}]) assert.equal(projectFabricModel({...row,...mutation}),null);
  const worker=projectFabricModel(row);
  assert.throws(()=>parse(WorkerDescriptor,{...worker,bridge:{...worker.bridge,profileSha256:null}},'worker'),/worker-invalid:bridge:custom/);
  assert.throws(()=>parse(WorkerDescriptor,{...worker,bridge:{...worker.bridge,modelSha256:'b'.repeat(64)}},'worker'),/worker-invalid:bridge:custom/);
  assert.throws(()=>parse(WorkerDescriptor,{...worker,bridge:{...worker.bridge,bridgeKind:'local'}},'worker'),/worker-invalid:bridge:custom/);
});

for (const [provider_id, adapter_id] of [['openai','openai-responses'],['mistral','mistral-chat'],['claude','claude-anthropic-messages']]) {
 test(`exact ${provider_id} service remains visible unavailable`,()=>{
  const worker=projectFabricModel({...row,provider_id,adapter_id});
  assert.equal(worker.providerId,provider_id);assert.equal(worker.enabled,false);
  assert.equal(projectFabricModel({...row,provider_id,adapter_id:'custom-openai-chat'}),null);
 });
}
