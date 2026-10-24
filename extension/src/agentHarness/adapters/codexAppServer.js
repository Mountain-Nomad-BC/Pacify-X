
'use strict';

const { ExecutionAdapter, sanitizeRemoteError } = require('./base');
const { newId } = require('../ids');
const { validateExecutionContextForRun } = require('../executionContext');
const MAX_FRAME_BYTES = 524288;

// Protocol client only. Native owner must independently verify signed prepared
// authority, suspended root/process custody and every effect before pipe access.
// No raw spawn, health subprocess, browser proof boolean or HTTP fallback exists.
class CodexAppServerAdapter extends ExecutionAdapter {
  constructor(options = {}) {
    super(options);
    this.owner = options.nativeOwner;
    this.executions = new Map();
  }

  async health() {
    return { status: 'unavailable', detail: 'codex-native-duplex-owner-not-commissioned' };
  }

  _owner() {
    if (!this.owner || ['open','assertCurrent','settle','close'].some(name => typeof this.owner[name] !== 'function'))
      throw new Error('codex-native-duplex-owner-required');
    return this.owner;
  }

  async _write(state, message) {
    await this._owner().assertCurrent(state.context, state.handle);
    if (state.closed) throw new Error('codex-execution-closed');
    const line = JSON.stringify(message);
    if (Buffer.byteLength(line) > MAX_FRAME_BYTES) throw new Error('codex-frame-byte-limit');
    await state.handle.writeLine(line);
  }

  _request(state, method, params) {
    const id = newId('rpc');
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { state.pending.delete(id); reject(new Error(`codex-rpc-timeout:${method}`)); }, this.options.rpcTimeoutMs || 30000);
      const done = fn => value => { clearTimeout(timer); state.pending.delete(id); fn(value); };
      state.pending.set(id, { resolve: done(resolve), reject: done(reject) });
      this._write(state, { method,id,params }).catch(state.pending.get(id).reject);
    });
  }

  async _message(state, line) {
    if (state.closed) return;
    await this._owner().assertCurrent(state.context,state.handle);
    if (typeof line !== 'string' || Buffer.byteLength(line) > MAX_FRAME_BYTES) throw new Error('codex-frame-byte-limit');
    const msg=JSON.parse(line);
    if (!msg || typeof msg !== 'object' || Array.isArray(msg)) throw new Error('codex-frame-object-required');
    if (msg.id != null && (Object.hasOwn(msg,'result') || Object.hasOwn(msg,'error'))) {
      const request=state.pending.get(String(msg.id));
      if (!request) return;
      if (msg.error) request.reject(new Error(`codex-rpc-error:${sanitizeRemoteError(msg.error.message)}`));
      else request.resolve(msg.result);
      return;
    }
    if (msg.id != null) {
      // Each server request remains denied: a read-only sandbox setting does not
      // establish effect containment. Native broker integration is still required.
      await this._write(state,{id:msg.id,error:{code:-32001,message:'PX native effect approval bridge unavailable'}});
      throw new Error('codex-native-effect-approval-unavailable');
    }
    if (!state.turnId) {
      if (state.buffer.length >= 64) throw new Error('codex-pre-turn-frame-limit');
      state.buffer.push(line);return;
    }
    const p=msg.params || {};
    const turn=p.turnId || p.turn?.id;
    if (p.threadId !== state.threadId || turn !== state.turnId) return;
    if (msg.method === 'model/rerouted') throw new Error('codex-unapproved-model-reroute');
    if (msg.method === 'item/agentMessage/delta') {
      if (typeof p.delta !== 'string') throw new Error('codex-text-delta-invalid');
      state.text += p.delta;
      if (Buffer.byteLength(state.text) > 1048576) throw new Error('codex-output-byte-limit');
      state.onEvent({type:'worker.stream.delta',status:'progress',summary:p.delta.slice(0,500),payload:{delta:p.delta,execution_id:state.context.execution_id}});
    } else if (msg.method === 'thread/tokenUsage/updated') {
      const u=p.tokenUsage?.last;
      if (!u || ['inputTokens','outputTokens','totalTokens'].some(k => !Number.isSafeInteger(u[k]) || u[k] < 0)) throw new Error('codex-exact-turn-usage-unavailable');
      state.usage={inputTokens:u.inputTokens,outputTokens:u.outputTokens,totalTokens:u.totalTokens};
    } else if (msg.method === 'turn/completed') {
      if (!['completed','interrupted','failed'].includes(p.turn?.status)) throw new Error('codex-terminal-status-invalid');
      state.status=p.turn.status;state.finished=true;
    }
  }

  async runTurn(input) {
    if(this.disposed)throw new Error('codex-adapter-disposed');
    const context=validateExecutionContextForRun(input.executionContext,input.run?.runId);
    const ref=input.preparedGroupReference;
    if (!ref || ref.schema_version !== 'px.prepared-group-reference/1.0' || !/^task-plan-[0-9a-f]{24}$/.test(ref.plan_id) || !/^[0-9a-f]{64}$/.test(ref.plan_sha256) || Object.keys(ref).length !== 3) throw new Error('codex-exact-prepared-reference-required');
    if (context.provider_id !== 'codex' || (input.serviceId && !['auto','codex'].includes(input.serviceId))) throw new Error('codex-service-identity-mismatch');
    if (this.executions.has(context.execution_id)) throw new Error('codex-execution-already-active');
    const state={context,handle:null,pending:new Map(),buffer:[],threadId:null,turnId:null,text:'',usage:null,status:null,finished:false,closed:false,onEvent:input.onEvent || (()=>{})};
    this.executions.set(context.execution_id,state);
    let primary=null;
    try {
      const owner=this._owner();
      state.handle=await owner.open({executionContext:context,preparedGroupReference:ref,serviceId:'codex',requestedModelId:input.modelId || this.options.model || 'auto'});
      if (!state.handle || ['writeLine','subscribe'].some(k=>typeof state.handle[k] !== 'function') || !state.handle.modelId || !/^[0-9a-f]{64}$/.test(state.handle.protocolSchemaSha256 || '')) throw new Error('codex-native-protocol-handle-invalid');
      const requested=input.modelId || this.options.model;
      if (requested && requested !== 'auto' && requested !== state.handle.modelId) throw new Error('codex-manual-model-substitution');
      state.modelId=state.handle.modelId;
      await owner.assertCurrent(context,state.handle);
      state.unsubscribe=state.handle.subscribe(line=>{
        state.queue=(state.queue || Promise.resolve()).then(()=>this._message(state,line)).catch(error=>{state.failure ||= error;state.finished=true;for(const pending of [...state.pending.values()]) pending.reject(error);});
      });
      await this._request(state,'initialize',{clientInfo:{name:'pacify-x',title:'Pacify-X Agent Console',version:String(this.options.clientVersion || '0.9.0')},capabilities:{experimentalApi:false}});
      await this._write(state,{method:'initialized'});
      const started=await this._request(state,'thread/start',{model:state.modelId,approvalPolicy:'on-request',sandbox:'read-only',ephemeral:true});
      state.threadId=started?.thread?.id;
      if (!state.threadId) throw new Error('codex-thread-id-missing');
      const prompt=[input.contextPack?.instruction || '',...(input.contextPack?.refs || []).filter(r=>r.content).map(r=>`[#${r.refId}]\n${r.content}`),input.message].filter(Boolean).join('\n\n');
      const turn=await this._request(state,'turn/start',{threadId:state.threadId,model:state.modelId,input:[{type:'text',text:prompt,text_elements:[]}]});
      state.turnId=turn?.turn?.id;
      if (!state.turnId) throw new Error('codex-turn-id-missing');
      for(const line of state.buffer.splice(0)) await this._message(state,line);
      while(!state.finished) {
        await owner.assertCurrent(context,state.handle);
        if (input.signal?.aborted || Date.parse(context.deadline_utc) <= Date.now()) {
          await this.interrupt(context);throw Object.assign(new Error('codex-turn-aborted'),{name:'AbortError'});
        }
        await new Promise(resolve=>setTimeout(resolve,10));
      }
      await state.queue;
      if (state.failure) throw state.failure;
      if (state.status !== 'completed') throw new Error(`codex-turn-${state.status}`);
      if (!state.usage) throw new Error('codex-exact-turn-usage-unavailable');
      await owner.assertCurrent(context,state.handle);
      const receipt=await owner.settle({executionContext:context,handle:state.handle,preparedGroupReference:ref,modelId:state.modelId,threadId:state.threadId,turnId:state.turnId,text:state.text,usage:state.usage,providerStatus:state.status});
      if (!receipt) throw new Error('codex-native-settlement-unavailable');
      return {text:state.text,usage:state.usage,providerStatus:state.status,sessionRef:state.threadId,exactReceipt:receipt};
    } catch(error) { primary=error;throw error; }
    finally {
      state.closed=true;
      let cleanupError=null;
      try { state.unsubscribe?.(); } catch(error) { cleanupError=error; }
      for(const pending of [...state.pending.values()]) pending.reject(new Error('codex-execution-closed'));
      if(this.executions.get(context.execution_id) === state)this.executions.delete(context.execution_id);
      try { if(this.owner && typeof this.owner.close === 'function') await this.owner.close(context,state.handle); }
      catch(error) { cleanupError ||= error; }
      if(cleanupError) { if(!primary)throw cleanupError;try{primary.custodyCleanupError=cleanupError;}catch{} }
    }
  }

  async interrupt(context) {
    const state=this.executions.get(context?.execution_id);
    if (!state || state.context.context_sha256 !== context.context_sha256 || !state.turnId) return false;
    await this._request(state,'turn/interrupt',{threadId:state.threadId,turnId:state.turnId});
    return true;
  }

  async dispose() {
    this.disposed=true;
    const failures=[];
    for(const state of this.executions.values()) {
      try { await this.interrupt(state.context); } catch(error) { failures.push(error); }
      state.failure ||= new Error('codex-adapter-disposed');state.finished=true;
    }
    if(failures.length)throw new AggregateError(failures,'codex-interruption-custody-uncertain');
  }

  async createSession() { throw new Error('codex-session-requires-prepared-execution'); }
  async resumeSession() { throw new Error('codex-resume-requires-native-history-authority'); }
}

module.exports={CodexAppServerAdapter};
