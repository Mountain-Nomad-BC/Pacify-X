'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeMessages, PxLanguageModelProvider } = require('../src/pxLanguageModelProvider');

function vscodeHarness() {
  return {
    EventEmitter: class { constructor(){ this.event=()=>({dispose(){}}); } fire(){} dispose(){} },
    LanguageModelChatMessageRole: { Assistant: 2 },
    LanguageModelTextPart: class { constructor(value){ this.value=value; } },
    LanguageModelToolCallPart: class { constructor(callId,name,input){ this.callId=callId; this.name=name; this.input=input; } }
  };
}
function token(){ return { isCancellationRequested:false, onCancellationRequested(){ return {dispose(){}}; } }; }

test('provider advertises only bridge-admitted model metadata', async () => {
  const bridge={ listModels: async()=>({models:[{profile_id:'deep',model_id:'qwen3-30b',lane:'deep',profile_sha256:'a'.repeat(64),context_tokens:8192,max_output_tokens:2048,tool_calling:true,image_input:false}]}) };
  const provider=new PxLanguageModelProvider(vscodeHarness(),bridge);
  const rows=await provider.provideLanguageModelChatInformation({},token());
  assert.equal(rows.length,1); assert.equal(rows[0].id,'deep'); assert.equal(rows[0].capabilities.toolCalling,true);
});

test('mixed VS Code history is reduced to bounded canonical text without granting tool authority', () => {
  const vscode=vscodeHarness();
  const messages=[{role:2,content:[{value:'prior'},{callId:'c1',name:'lookup',input:{q:'x'}}]},{role:1,content:[{callId:'c1',content:[{value:'result'}]}]}];
  const rows=normalizeMessages(vscode,messages);
  assert.equal(rows[0].role,'assistant'); assert.match(rows[0].content,/PX_TOOL_CALL/); assert.match(rows[1].content,/PX_TOOL_RESULT/);
});

test('provider streams text and tool calls while suppressing reasoning deltas', async () => {
  const vscode=vscodeHarness(); const output=[]; let received;
  const bridge={
    streamChat: async(payload,_token,onEvent)=>{ received=payload; onEvent({kind:'reasoning_delta',payload:{text:'hidden'}}); onEvent({kind:'text_delta',payload:{text:'hello'}}); onEvent({kind:'tool_call_start',payload:{call_id:'c1',name:'lookup'}}); onEvent({kind:'tool_call_delta',payload:{call_id:'c1',arguments_delta:'{"q":"x"}'}}); onEvent({kind:'tool_call_end',payload:{call_id:'c1',name:'lookup',arguments:{q:'x'}}}); },
    countTokens: async()=>({exact:true,input_tokens:7})
  };
  const provider=new PxLanguageModelProvider(vscode,bridge);
  await provider.provideLanguageModelChatResponse({id:'control',maxOutputTokens:128},[{role:1,content:[{value:'hi'}]}],{tools:[{name:'lookup',description:'read',inputSchema:{type:'object'}}]}, {report:p=>output.push(p)}, token());
  assert.equal(received.profile_id,'control'); assert.equal(received.tools[0].name,'lookup');
  assert.equal(output.length,2); assert.equal(output[0].value,'hello'); assert.equal(output[1].name,'lookup'); assert.deepEqual(output[1].input,{q:'x'});
  assert.equal(await provider.provideTokenCount({id:'control'},'hello',token()),7);
});

test('provider forwards the VS Code cancellation token to the PX bridge', async () => {
  const vscode=vscodeHarness(); const marker=token(); let seen;
  const bridge={streamChat:async(_payload,t)=>{seen=t;}};
  const provider=new PxLanguageModelProvider(vscode,bridge);
  await provider.provideLanguageModelChatResponse({id:'control',maxOutputTokens:32},[{role:1,content:[{value:'x'}]}],{}, {report(){}}, marker);
  assert.equal(seen,marker);
});
