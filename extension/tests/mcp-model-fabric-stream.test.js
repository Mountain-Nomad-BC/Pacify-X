'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const cp = require('node:child_process');
const {EventEmitter} = require('node:events');
const {PassThrough} = require('node:stream');
const {defaultRunner} = require('../src/mcpModelFabricBridge');

// Controlled child transport: this exercises the real defaultRunner parser and
// consumer lifecycle, not a provider connection or commissioned host.
function run(t, chunks, {code=0, token, onEvent}={}) {
  t.mock.method(cp, 'spawn', () => {
    const child = new EventEmitter();
    child.stdin = new PassThrough(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
    queueMicrotask(() => { for (const chunk of chunks) child.stdout.write(chunk); child.emit('close', code); });
    return child;
  });
  return defaultRunner({operation:'chat',payload:{},pythonPath:'unused-fixture',engineRoot:process.cwd(),projectRoot:process.cwd(),token,onEvent,timeoutMs:1000});
}
const failure = {type:'failure',failure:{schema_version:'px.provider-client-failure/1.0',failure_type:'QuotaExceeded',retryable:true,failure_class:'quota',upstream_status:429,retry_after_seconds:2}};
const receipt = JSON.stringify({type:'receipt',receipt:{status:'completed'}});

test('real stream parser preserves typed provider failure with or without final newline', async t => {
  for (const newline of ['', '\n']) {
    const text=JSON.stringify(failure)+newline;
    await assert.rejects(run(t,[text.slice(0,17),text.slice(17)],{code:1}),e=>e.code==='rate_limit_exceeded' && e.status===429 && e.retryAfterSeconds===2);
    t.mock.restoreAll();
  }
});
test('real stream parser rejects output after a failure terminal', async t => {
  await assert.rejects(run(t,[JSON.stringify(failure)+'\n'+receipt+'\n']),{code:'PX_MODEL_CLIENT_PROTOCOL'});
});
test('real stream parser rejects a missing terminal receipt', async t => {
  await assert.rejects(run(t,[JSON.stringify({type:'event',event:{kind:'text_delta',payload:{text:'partial'}}})+'\n']),{code:'PX_MODEL_CLIENT_PROTOCOL'});
});
test('real stream completion awaits asynchronous receipt consumer', async t => {
  const seen=[];
  await run(t,[receipt],{onEvent:async e=>{await new Promise(resolve=>setImmediate(resolve));seen.push(e.kind);}});
  assert.deepEqual(seen,['px_receipt']);
});
test('aborted AbortSignal refuses launch', async t => {
  const controller=new AbortController(); controller.abort(); let called=false;
  t.mock.method(cp,'spawn',()=>{called=true;throw new Error('must not spawn');});
  await assert.rejects(defaultRunner({token:controller.signal}),{code:'PX_MODEL_CLIENT_CANCELLED'});
  assert.equal(called,false);
});
