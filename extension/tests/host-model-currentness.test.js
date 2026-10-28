
'use strict';
const test=require('node:test');const assert=require('node:assert/strict');
const {executeAdmittedHostModel}=require('../src/hostModelExecution');

function fixture({duplicate=false,wrongVendor=false,revoke=false,cancelled=false}={}) {
 let sends=0;let current=true;
 class TextPart{constructor(value){this.value=value;}}
 class ToolPart{}
 class CancellationSource{constructor(){this.token={isCancellationRequested:false};}cancel(){this.token.isCancellationRequested=true;}dispose(){}}
 const model={id:'fixture-model',vendor:wrongVendor?'other':'copilot',family:'fixture-family',version:'fixture-version',maxInputTokens:1000,async countTokens(){return 5;},async sendRequest(){sends++;return {stream:(async function*(){yield new TextPart('{"done":');if(revoke)current=false;yield new TextPart('true}');})()};}};
 const vscode={lm:{async selectChatModels(){return duplicate?[model,model]:[model];},tools:[]},LanguageModelChatMessage:{User:x=>({role:'user',content:x})},LanguageModelTextPart:TextPart,LanguageModelToolCallPart:ToolPart,CancellationTokenSource:CancellationSource};
 const prepared={model:{provider:'vscode-lm',vendor:'copilot',family:'fixture-family',model_id:'fixture-model',version:'fixture-version',max_output_tokens:256},agent_id:'fixture-agent',task:{objective:'fixture'},output_schema:{type:'object'}};
 const options={vscode,prepared,token:{isCancellationRequested:cancelled,onCancellationRequested:()=>({dispose(){}})},assertCurrent:async()=>{if(!current)throw new Error('native-run-revoked');}};
 return {options,get sends(){return sends;}};
}

test('normal host interface preserves exact approved service/model',async()=>{const f=fixture();const r=await executeAdmittedHostModel(f.options);assert.deepEqual(r.output,{done:true});assert.equal(r.model.vendor,'copilot');assert.equal(f.sends,1);});
for(const scenario of [{duplicate:true},{wrongVendor:true},{cancelled:true}])test('host discovery or cancellation cannot substitute authority '+JSON.stringify(scenario),async()=>{const f=fixture(scenario);await assert.rejects(executeAdmittedHostModel(f.options));assert.equal(f.sends,0);});
test('actual currentness callback must succeed before every stream part',async()=>{const f=fixture({revoke:true});await assert.rejects(executeAdmittedHostModel(f.options),/native-run-revoked/);assert.equal(f.sends,1);});
test('caller approval is not a native currentness oracle',async()=>{const f=fixture();delete f.options.assertCurrent;f.options.approved=true;await assert.rejects(executeAdmittedHostModel(f.options),/native-host-currentness/);assert.equal(f.sends,0);});


test('normal PxBridge currentness RPC is read-only and preserves cache generation',async t=>{
 const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
 const {PxBridge}=require('../src/pxBridge');
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'px-host-currentness-'));
 t.after(()=>{assert.ok(path.resolve(root).startsWith(path.resolve(os.tmpdir())+path.sep));fs.rmSync(root,{recursive:true,force:true});});
 fs.mkdirSync(path.join(root,'runtime'));fs.mkdirSync(path.join(root,'registry'));
 fs.writeFileSync(path.join(root,'runtime/dashboard_api.py'),'# fixture');fs.writeFileSync(path.join(root,'registry/tools.json'),'{}');
 let invoked=false;
 const bridge=new PxBridge({engineRoot:root,projectRoot:root,capture:async(command,args)=>{assert.equal(args[args.indexOf('--operation')+1],'check-host-run');invoked=true;return {schema_version:'px.agent-host-run-current/1.0',run_id:'fixture-run',state:'running'};}});
 bridge.invalidate=()=>{throw new Error('read-only currentness must not invalidate every chunk');};
 const result=await bridge.studioOperation('agent','check-host-run',{run_id:'fixture-run'});
 assert.equal(result.state,'running');assert.ok(invoked);bridge.dispose?.();
});
