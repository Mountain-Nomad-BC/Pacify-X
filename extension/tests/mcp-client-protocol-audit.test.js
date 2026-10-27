'use strict';
const test=require('node:test');const assert=require('node:assert/strict');
const cp=require('node:child_process');const {EventEmitter}=require('node:events');const {PassThrough}=require('node:stream');
const {defaultRunner}=require('../src/mcpModelFabricBridge');
const {buildPxProviderGatewayInvoker}=require('../src/agentHarness/pxProviderInvoker');
function controlledChild(t,output){
 const original=cp.spawn;let spawned=0;
 cp.spawn=()=>{spawned++;const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.stdin={end(){queueMicrotask(()=>{child.stdout.write(output);child.emit('close',0);});}};child.kill=()=>{queueMicrotask(()=>child.emit('close',1));return true;};return child;};
 t.after(()=>{cp.spawn=original;});return ()=>spawned;
}
function run(events){return defaultRunner({operation:'chat',payload:{},pythonPath:'/controlled',engineRoot:process.cwd(),projectRoot:process.cwd(),timeoutMs:1000,onEvent:event=>events.push(event)});}
for(const ending of ['','\n'])test(`trailing receipt uses the same handler as newline framing ${JSON.stringify(ending)}`,async t=>{
 controlledChild(t,JSON.stringify({type:'receipt',receipt:{fixture:true}})+ending);
 const events=[];await run(events);assert.deepEqual(events,[{kind:'px_receipt',payload:{fixture:true}}]);
});
for(const ending of ['','\n'])test(`unsupported final envelope never becomes successful chat ${JSON.stringify(ending)}`,async t=>{
 controlledChild(t,JSON.stringify({type:'failure',reason:'controlled rejection'})+ending);
 await assert.rejects(run([]),/unsupported|protocol/i);
});

test('data after receipt and missing receipt cannot claim completed chat',async t=>{
 controlledChild(t,JSON.stringify({type:'receipt',receipt:{fixture:true}})+'\n'+JSON.stringify({type:'event',event:{kind:'text_delta',payload:{text:'late'}}}));
 await assert.rejects(run([]),/receipt|protocol|terminal/i);
});

test('consumer exception becomes a rejected owned operation rather than uncaught callback',async t=>{
 controlledChild(t,JSON.stringify({type:'receipt',receipt:{fixture:true}}));
 await assert.rejects(defaultRunner({operation:'chat',payload:{},pythonPath:'/controlled',engineRoot:process.cwd(),projectRoot:process.cwd(),timeoutMs:1000,onEvent(){throw new Error('controlled consumer failure');}}),/consumer|protocol/i);
});

test('harness AbortSignal is adapted to the native bridge cancellation-token interface',async()=>{
 const controller=new AbortController();let token;let called;
 const entered=new Promise(resolve=>{called=resolve;});
 const invoke=buildPxProviderGatewayInvoker({profileIdForWorker:()=> 'profile',bridge:{streamChat:async(payload,value)=>{
  token=value;called();return new Promise((resolve,reject)=>{
   const registration=value?.onCancellationRequested?.(()=>{registration.dispose();reject(Object.assign(new Error('controlled abort'),{name:'AbortError'}));});
  });}}});
 const turn=invoke({worker:{},task:{taskId:'task'},run:{runId:'run'},message:'inspect',executionContext:{execution_id:'invocation'},signal:controller.signal});
 const result=turn.then(()=> 'success',error=>error.name);await entered;controller.abort();let timer;
 try{assert.equal(await Promise.race([result,new Promise(resolve=>{timer=setTimeout(()=>resolve('unbounded'),150);})]),'AbortError');}
 finally{clearTimeout(timer);}
 assert.equal(token.isCancellationRequested,true);
});
