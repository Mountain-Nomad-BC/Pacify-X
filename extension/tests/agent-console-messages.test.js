'use strict';
const test=require('node:test'); const assert=require('node:assert/strict');
const {MESSAGE_VERSION,ASSET_PROTOCOL,validateInbound}=require('../src/agentHarness/agentConsoleMessages');
test('agent console protocol rejects unknown fields and unsafe IDs',()=>{assert.equal(validateInbound({schemaVersion:MESSAGE_VERSION,type:'ready',assetProtocol:ASSET_PROTOCOL}).type,'ready');assert.throws(()=>validateInbound({schemaVersion:MESSAGE_VERSION,type:'cancelRun',runId:'../x'}),/invalid/);assert.throws(()=>validateInbound({schemaVersion:MESSAGE_VERSION,type:'refresh',extra:true}),/invalid/);});
