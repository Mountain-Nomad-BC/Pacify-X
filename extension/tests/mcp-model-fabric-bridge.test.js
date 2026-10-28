'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('fs');
const { McpModelFabricBridge }=require('../src/mcpModelFabricBridge');

test('bridge delegates only named PX model-client operations with explicit roots', async()=>{
  const calls=[]; const runner=async input=>{
    calls.push(input);
    if(input.operation==='list') return {models:[]};
    if(input.operation==='sandbox') return {
      schema_version:'px.isolated-agent-sandbox-result/1.0',
      mode:'ON',
      authority_granted:false,
      policy:{
        schema_version:'px.isolated-agent-sandbox/1.0',
        mode:'ON',
        scope_key:fs.realpathSync(calls[2].projectRoot).replaceAll('\\','/'),
        policy_revision:'sandbox-r1',
        policy_sha256:'0'.repeat(64),
        authority_granted:false,
        network_policy:{default:'deny',allowed_endpoints:['api.example.com']}
      }
    };
    return {ok:true};
  };
  const bridge=new McpModelFabricBridge({pythonPath:()=>'/python',engineRoot:()=>'/engine',projectRoot:()=>process.cwd(),runner});
  await bridge.listModels({});
  await bridge.countTokens({profile_id:'p'},{});
  await bridge.setSandboxMode({
    schema_version:'px.isolated-agent-sandbox-request/1.0',
    mode:'ON',
    allowed_endpoints:['api.example.com']
  },{});
  await bridge.streamChat({profile_id:'p',deadline_ms:1000},{},()=>{});
  assert.deepEqual(calls.map(x=>x.operation),['list','count','sandbox','chat']);
  assert.deepEqual(calls[2].payload,{
    schema_version:'px.isolated-agent-sandbox-request/1.0',
    mode:'ON',
    allowed_endpoints:['api.example.com']
  });
  assert.equal(calls[2].timeoutMs,30000);
  assert.equal(calls[0].engineRoot,require('path').resolve('/engine'));
  assert.equal(calls[3].timeoutMs,6000);
});

test('bridge fails before spawning when PX roots are unavailable', async()=>{
  const bridge=new McpModelFabricBridge({engineRoot:()=>'',projectRoot:()=>'',runner:async()=>{throw new Error('must not run');}});
  assert.throws(()=>bridge.listModels({}),/engine-root-unavailable/);
});

test('bridge rejects an OFF sandbox request carrying an unused allowlist',()=>{
  const bridge=new McpModelFabricBridge({engineRoot:()=>'/engine',projectRoot:()=>process.cwd(),runner:async()=>{throw new Error('must not run');}});
  assert.throws(()=>bridge.setSandboxMode({
    schema_version:'px.isolated-agent-sandbox-request/1.0',
    mode:'OFF',
    allowed_endpoints:['api.example.com']
  },{}),/Sandbox request is invalid/);
});

test('bridge rejects a sandbox request scoped to a different project root',()=>{
  const bridge=new McpModelFabricBridge({engineRoot:()=>'/engine',projectRoot:()=>process.cwd(),runner:async()=>{throw new Error('must not run');}});
  assert.throws(()=>bridge.setSandboxMode({
    schema_version:'px.isolated-agent-sandbox-request/1.0',
    mode:'OFF',
    allowed_endpoints:[],
    scope_key:'another-project'
  },{}),/Sandbox scope does not match the project root/);
});
