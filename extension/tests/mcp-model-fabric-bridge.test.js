'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const { McpModelFabricBridge }=require('../src/mcpModelFabricBridge');

test('bridge delegates only named PX model-client operations with explicit roots', async()=>{
  const calls=[]; const runner=async input=>{calls.push(input); return input.operation==='list'?{models:[]}:{ok:true};};
  const bridge=new McpModelFabricBridge({pythonPath:()=>'/python',engineRoot:()=>'/engine',projectRoot:()=>'/project',runner});
  await bridge.listModels({}); await bridge.countTokens({profile_id:'p'},{}); await bridge.streamChat({profile_id:'p',deadline_ms:1000},{},()=>{});
  assert.deepEqual(calls.map(x=>x.operation),['list','count','chat']);
  assert.equal(calls[0].engineRoot,require('path').resolve('/engine'));
  assert.equal(calls[2].timeoutMs,6000);
});

test('bridge fails before spawning when PX roots are unavailable', async()=>{
  const bridge=new McpModelFabricBridge({engineRoot:()=>'',projectRoot:()=>'',runner:async()=>{throw new Error('must not run');}});
  assert.throws(()=>bridge.listModels({}),/engine-root-unavailable/);
});
