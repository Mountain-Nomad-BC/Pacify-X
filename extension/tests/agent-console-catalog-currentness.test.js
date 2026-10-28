'use strict';
const test=require('node:test'); const assert=require('node:assert/strict');
const {registerAgentConsole}=require('../src/agentHarness/registerAgentConsole');
const {chooseWorker}=require('../src/agentHarness/router');
function host(options={}) {
 const noop={dispose(){}};
 const vscode={window:{registerWebviewViewProvider:()=>noop},commands:{registerCommand:()=>noop}};
 const context={workspaceState:{get:(_key,fallback)=>fallback,update:async()=>{}},extensionPath:'.'};
 return registerAgentConsole(vscode,context,{providerGatewayInvoker:async()=>{throw new Error('no live provider');},...options});
}
const listed={schema_version:'px.vscode-model-list/1.0',authority_granted:false,models:[{profile_id:'fixture',model_id:'fixture-model',lane:'control',context_tokens:8192,max_output_tokens:1024,model_sha256:'a'.repeat(64),provider_id:'llama.cpp'}]};
function route(console, selection={}) {return chooseWorker(console.harness.workerRegistry,{task:{mode:'DIAGNOSE',constraints:{maxEffectClass:'READ_ONLY',localFirst:true}},contextTokens:100,budgetLedger:{canAdmit:()=>({allowed:true})},...selection});}
test('failed current catalog invalidates previously selectable manual and Auto workers',async()=>{
 let fail=false;const console=host({modelFabricLister:async()=>{if(fail)throw new Error('fixture catalog unavailable');return listed;}});
 await console.refreshModelCatalog(); assert.equal(console.harness.workerRegistry.list().length,1);
 fail=true;await console.refreshModelCatalog(); assert.equal(console.modelCatalog.state,'unavailable');
 assert.equal(route(console).selected,null);
 assert.equal(route(console,{requestedWorkerId:'px-fabric-fixture'}).selected,null);
 assert.equal(console.harness.workerRegistry.list().length,0);console.dispose();
});
test('missing invoker remains unavailable even when canonical listing succeeds',async()=>{
 const console=host({modelFabricLister:async()=>listed,providerGatewayInvoker:null});
 await console.refreshModelCatalog(); assert.equal(console.modelCatalog.state,'unavailable');
 assert.equal(console.harness.workerRegistry.list().length,0);console.dispose();
});
test('older successful response cannot resurrect workers after newer failed refresh',async()=>{
 const pending=[];const console=host({modelFabricLister:()=>new Promise((resolve,reject)=>pending.push({resolve,reject}))});
 const older=console.refreshModelCatalog();const newer=console.refreshModelCatalog();
 pending[2].reject(new Error('latest unavailable'));await newer;
 pending[1].resolve(listed);await older;
 pending[0].resolve(listed);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(console.modelCatalog.state,'unavailable');assert.equal(console.harness.workerRegistry.list().length,0);console.dispose();
});
