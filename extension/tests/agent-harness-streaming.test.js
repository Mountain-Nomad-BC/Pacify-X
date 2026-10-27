'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { OpenAICompatibleAdapter } = require('../src/agentHarness/adapters/openaiCompatible');
const { OllamaAdapter } = require('../src/agentHarness/adapters/ollama');

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function streamResponse(chunks) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    }
  }), { headers: { 'content-type': 'text/event-stream' } });
}

const baseInput = {
  message: 'hi',
  contextPack: { instruction: 'You are a PX-governed worker.', refs: [] },
  signal: { aborted: false },
  onEvent: () => {},
};

function withFetch(response) {
  const orig = globalThis.fetch;
  globalThis.fetch = async () => response;
  return {
    restore: () => { globalThis.fetch = orig; },
  };
}

test('PX-AUD-052 openai CRLF frame separator is parsed across chunks', async t => {
  const restore = withFetch(streamResponse([
    'data:{"choices":[{"delta":{"content":"hel"}}]}\r\n\r\n',
    'data:{"choices":[{"delta":{"content":"lo"}}]}\r\n\r\ndata:[DONE]\r\n\r\n',
  ]));
  t.after(restore);
  const adapter = new OpenAICompatibleAdapter({ baseUrl: 'http://x', model: 'm', getApiKey: async () => 'k' });
  const out = [];
  await adapter.runTurn({ ...baseInput, onEvent: e => { if (e.type === 'worker.stream.delta') out.push(e.payload.delta); } });
  assert.deepEqual(out, ['hel', 'lo']);
});

test('PX-AUD-053 openai truncated stream without terminal throws', async t => {
  const restore = withFetch(streamResponse([
    'data:{"choices":[{"delta":{"content":"partial"}}]}\n\n',
  ]));
  t.after(restore);
  const adapter = new OpenAICompatibleAdapter({ baseUrl: 'http://x', model: 'm', getApiKey: async () => 'k' });
  await assert.rejects(
    adapter.runTurn({ ...baseInput, onEvent: () => {} }),
    /openai-stream-incomplete/
  );
});

test('PX-AUD-053 openai data after terminal throws', async t => {
  const restore = withFetch(streamResponse([
    'data:{"choices":[{"delta":{"content":"ok"}}]}\n\ndata:[DONE]\n\n',
    'data:{"choices":[{"delta":{"content":"after"}}]}\n\n',
  ]));
  t.after(restore);
  const adapter = new OpenAICompatibleAdapter({ baseUrl: 'http://x', model: 'm', getApiKey: async () => 'k' });
  await assert.rejects(
    adapter.runTurn({ ...baseInput, onEvent: () => {} }),
    /openai-stream-data-after-terminal/
  );
});

test('PX-AUD-054 ollama trailing record without newline is consumed', async t => {
  const restore = withFetch(streamResponse([
    '{"message":{"content":"a"}}\n{"done":true,"eval_count":5}',
  ]));
  t.after(restore);
  const adapter = new OllamaAdapter({ baseUrl: 'http://x', model: 'm' });
  const out = [];
  const result = await adapter.runTurn({ ...baseInput, onEvent: e => { if (e.type === 'worker.stream.delta') out.push(e.payload.delta); } });
  assert.deepEqual(out, ['a']);
  assert.equal(result.usage.outputTokens, 5, 'terminal done recognized despite missing trailing newline');
});

test('PX-AUD-055 ollama early EOF without done:true throws', async t => {
  const restore = withFetch(streamResponse([
    '{"message":{"content":"partial"}}\n',
  ]));
  t.after(restore);
  const adapter = new OllamaAdapter({ baseUrl: 'http://x', model: 'm' });
  await assert.rejects(
    adapter.runTurn({ ...baseInput, onEvent: () => {} }),
    /ollama-stream-incomplete/
  );
});

test('PX-AUD-055 ollama explicit done:true is accepted', async t => {
  const restore = withFetch(streamResponse([
    '{"message":{"content":"a"}}\n{"done":true}\n',
  ]));
  t.after(restore);
  const adapter = new OllamaAdapter({ baseUrl: 'http://x', model: 'm' });
  const out = [];
  await adapter.runTurn({ ...baseInput, onEvent: e => { if (e.type === 'worker.stream.delta') out.push(e.payload.delta); } });
  assert.deepEqual(out, ['a']);
});

for(const kind of ['openai','ollama']){
 test(`${kind} malformed frame cancels actual stream source and releases reader custody`,async t=>{
   let cancelled=false;let controller;
   const body=new ReadableStream({start(value){controller=value;value.enqueue(encoder.encode(kind==='openai'?'data:not-json\n\n':'not-json\n'));},cancel(){cancelled=true;}});
   const response=new Response(body);const restore=withFetch(response);t.after(restore);
   const adapter=kind==='openai'?new OpenAICompatibleAdapter({baseUrl:'http://controlled',model:'m',getApiKey:async()=> 'fixture'}):new OllamaAdapter({baseUrl:'http://controlled',model:'m'});
   await assert.rejects(adapter.runTurn(baseInput),SyntaxError);
   assert.equal(cancelled,true);assert.equal(body.locked,false);
 });
 test(`${kind} abort settles a pending stream read and releases transport`,async t=>{
   let cancelled=false;let started;const entered=new Promise(resolve=>{started=resolve;});
   const body=new ReadableStream({pull(){started();},cancel(){cancelled=true;}});
   const restore=withFetch(new Response(body));t.after(restore);
   const controller=new AbortController();
   const adapter=kind==='openai'?new OpenAICompatibleAdapter({baseUrl:'http://controlled',model:'m',getApiKey:async()=> 'fixture'}):new OllamaAdapter({baseUrl:'http://controlled',model:'m'});
   const turn=adapter.runTurn({...baseInput,signal:controller.signal});
   const observed=turn.then(()=> 'completed',error=>error.name);
   await entered;controller.abort();let timer;
   try{assert.equal(await Promise.race([observed,new Promise(resolve=>{timer=setTimeout(()=>resolve('unbounded'),150);})]),'AbortError');}
   finally{clearTimeout(timer);}
   assert.equal(cancelled,true);assert.equal(body.locked,false);
 });
}
