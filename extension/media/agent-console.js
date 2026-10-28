'use strict';

const vscode = acquireVsCodeApi();
const protocol = window.__PX_AGENT_PROTOCOL__;
let state = null; let currentMode = 'DIAGNOSE'; let currentWorker = 'auto'; let effect = 'READ_ONLY'; let streamed = ''; let lastStreamRun = null;
let currentService = 'auto';
const savedSelection = vscode.getState?.();
if (savedSelection) { currentService = savedSelection.serviceId || 'auto'; currentWorker = savedSelection.workerId || 'auto'; }

function send(type, payload = {}) { vscode.postMessage({ schemaVersion: protocol.message, type, ...payload }); }
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function fmtMoney(value) { return value == null ? 'unknown' : `$${Number(value).toFixed(3)}`; }
function badge(text, cls='') { return `<span class="badge ${cls}">${esc(text)}</span>`; }
function fmtTokens(value) { return Number.isInteger(value) && value > 0 ? `${Math.round(value / 1000)}k` : '—'; }

// Describe exactly what a model bridges to, from canonical owner truth only.
// Nothing here is inferred for display when PX did not report it.
function bridgeLine(w) {
  const b = w.bridge || {};
  const parts = [];
  parts.push(b.lane ? `${b.lane} lane` : (w.providerId || 'unknown service'));
  if (w.modelId) parts.push(w.modelId);
  if (w.contextLimit) parts.push(`${fmtTokens(w.contextLimit)} ctx`);
  if (w.locality) parts.push(w.locality);
  if (b.toolCalling === true) parts.push('tool-capable');
  if (b.imageInput === true) parts.push('vision');
  return parts.join(' · ');
}
function healthTone(w) {
  const h = w.health?.status;
  if (h === 'healthy' || h === 'ready') return 'good';
  if (h === 'unavailable' || h === 'unhealthy') return 'bad';
  if (h === 'degraded') return 'warn';
  return '';
}
function workerOptionLabel(w) {
  const unavailable = w.enabled === false || w.bridge?.available === false;
  return `${unavailable ? '✕ ' : ''}${bridgeLine(w)}${w.health?.status ? ` · ${w.health.status}` : ''}`;
}

// The model selection is a projection of the canonical model fabric, so an empty or failed
// catalog is stated as such instead of silently offering nothing.
function renderModelOptions(workers) {
  workers = workers.filter(w => currentService === 'auto' || w.providerId === currentService);
  const available = workers.filter(w => w.enabled !== false && w.bridge?.available !== false);
  const unavailable = workers.filter(w => w.enabled === false || w.bridge?.available === false);
  if (!workers.length) return `<option value="auto"${currentWorker === 'auto' ? ' selected' : ''}>AUTO MODEL · no models admitted</option>`;
  const group = (rows, label, disabled) => rows.length
    ? `<optgroup label="${esc(label)}"${disabled ? ' disabled' : ''}>${rows.map(w => `<option value="${esc(w.workerId)}"${w.workerId === currentWorker ? ' selected' : ''}${disabled ? ' disabled' : ''}>${esc(workerOptionLabel(w))}</option>`).join('')}</optgroup>`
    : '';
  return `<option value="auto"${currentWorker === 'auto' ? ' selected' : ''}>AUTO MODEL · ${available.length} model${available.length === 1 ? '' : 's'} available</option>`
    + group(available, 'Available', false)
    + group(unavailable, 'Unavailable now', true);
}

function renderServiceOptions(workers) {
  const services = [...new Set(workers.map(w => w.providerId).filter(Boolean))].sort();
  return `<option value="auto"${currentService === 'auto' ? ' selected' : ''}>AUTO SERVICE</option>` +
    services.map(id => `<option value="${esc(id)}"${id === currentService ? ' selected' : ''}>${esc(id)}</option>`).join('');
}

function render() {
  const draft = document.getElementById('prompt')?.value || '';
  const app = document.getElementById('app'); if (!state) { app.innerHTML = `<section class="loading">Starting PX harness…</section>`; return; }
  const task = state.task; const run = state.run; const lib = state.librarian; const ctx = state.context; const route = state.route; const workers = state.workers || [];
  const selected = route?.selectedWorkerId ? workers.find(w => w.workerId === route.selectedWorkerId) : null;
  const catalog = state.modelCatalog || null;
  const catalogText = catalog
    ? `${catalog.source === 'model-fabric' ? 'Models from PX model fabric' : 'Models from static bring-up list'} · ${catalog.detail || 'unknown'}`
    : 'Model catalog provenance unavailable.';
  app.innerHTML = `
    <header class="topbar"><div><div class="eyebrow">PACIFY-X</div><h1>Agent Console</h1></div><div class="health ${selected?.health?.status || 'idle'}">● ${esc(selected?.health?.status || 'IDLE')}</div></header>
    <section class="activity panel">
      <div class="panel-title"><span>PX Archivist</span>${lib ? badge(`${Math.round(lib.confidence*100)}%`) : badge('waiting')}</div>
      <div class="activity-track"><span class="step ${lib?'done':'active'}">classify</span><span>→</span><span class="step ${ctx?'done':''}">retrieve</span><span>→</span><span class="step ${ctx?'done':''}">compile</span><span>→</span><span class="step ${selected?'done':''}">route</span></div>
      <div class="subtle">${lib ? `${esc(lib.intent)} · ${esc(lib.domains.join(', '))}` : 'No classification yet.'}</div>
      <div class="metrics"><span>${ctx ? `${ctx.selectedCount}/${ctx.consideredCount} refs` : '0 refs'}</span><span>${ctx ? `${ctx.suppliedTokens}/${ctx.budgetTokens} ctx` : '0 ctx'}</span><span>${lib ? `${Math.round(lib.durationMs)}ms` : '—'}</span></div>
      <details><summary>Inspect PX Archivist artifact</summary><pre>${esc(lib ? JSON.stringify(lib,null,2) : 'No artifact yet.')}</pre></details>
    </section>
    <section class="panel">
      <details><summary>Inspect a prepared model group</summary>
        <label>Saved plan ID <input id="preparedPlanId" placeholder="task-plan-?" maxlength="34"></label>
        <label>Plan SHA-256 <input id="preparedPlanDigest" placeholder="64 lowercase hexadecimal characters" maxlength="64"></label>
        <button id="inspectPreparedPlan">Inspect saved plan</button>
        <button id="executePreparedGroup">Execute saved group…</button>
        <p class="subtle">Inspection resolves the saved native plan. Execution resolves its single admitted workflow owner and requires host approval, approval consumption and containment.</p>
      </details>
    </section>
    <section class="route panel">
      <div class="panel-title"><span>ROUTE</span>${selected ? badge(selected.costClass, selected.costClass) : badge('none')}</div>
      <div class="route-line">${selected ? `<strong>${esc(selected.displayName)}</strong><span>${esc(bridgeLine(selected))}</span>` : '<strong>No admitted worker selected</strong>'}</div>
      <div class="metrics"><span>${state.budget?.totalTokens || 0} tokens</span><span>${fmtMoney(state.budget?.actualChargeUsd)}</span><span>${state.budget?.receiptCount || 0} receipts</span></div>
      ${route?.reason ? `<div class="subtle">Reason: ${esc(route.reason)}</div>` : ''}
      <details><summary>Admission / route details</summary><div class="route-grid">${(route?.evaluated || []).map(r => `<div class="route-row"><span>${esc(r.displayName)}</span><span>${r.admitted ? badge('admitted','good') : badge(r.reasons.join(', ') || 'rejected','bad')}</span><span>${r.score == null ? '—' : r.score.toFixed(3)}</span></div>`).join('') || '<span class="subtle">No route evaluation yet.</span>'}</div></details>
      <details><summary>Bridged services</summary><div class="route-grid">${(state.workers||[]).map(w => `<div class="route-row"><span>${esc(bridgeLine(w))}</span><span>${badge(w.health?.status || 'unknown', healthTone(w))}</span><span>${w.bridge?.sessionId ? esc(String(w.bridge.sessionId).slice(0,18)) : '—'}</span></div>`).join('') || '<span class="subtle">No bridged services reported.</span>'}</div></details>
    </section>
    <section class="transcript" id="transcript">${renderTranscript()}</section>
    <section class="composer panel">
      <div class="composer-controls">
        <select id="mode">${['ASK','PLAN','DIAGNOSE','IMPLEMENT','REVIEW','CAMPAIGN'].map(v => `<option ${v===currentMode?'selected':''}>${v}</option>`).join('')}</select>
        <label>Service <select id="service" title="Choose an available service or let PX route automatically.">${renderServiceOptions(workers)}</select></label>
        <label>Model <select id="worker" title="Choose an exact model for this service or AUTO MODEL.">${renderModelOptions(workers)}</select></label>
        <select id="effect">${['READ_ONLY','LOW_RISK','MUTATING','HIGH_RISK'].map(v => `<option ${v===effect?'selected':''}>${v}</option>`).join('')}</select>
      </div>
      <div class="catalog-line subtle">${esc(catalogText)} <button id="refreshModels" class="link">Refresh</button></div>
      <textarea id="prompt" rows="4" placeholder="Ask PX…"></textarea>
      <div class="composer-actions"><button id="control">Control Plane</button>${run?.status==='running'?'<button id="cancel" class="danger">Interrupt</button>':''}${run?.status==='waiting'?'<button id="resume">Resume waiting run</button>':''}<button id="send" class="primary">Send</button></div>
    </section>`;
  document.getElementById('prompt').value = draft;
  bind(); requestAnimationFrame(() => { const t=document.getElementById('transcript'); if(t) t.scrollTop=t.scrollHeight; });
}

function renderTranscript() {
  const events = state.events || []; if (!events.length) return `<div class="empty"><h2>PX is ready.</h2><p>Start a task. The sidebar will show classification, context, routing, worker output, tools, evidence and budget events from one PX-owned run.</p></div>`;
  return events.map(e => {
    if (e.type === 'worker.stream.delta') return `<div class="stream">${esc(e.payload?.delta || e.summary)}</div>`;
    const icon = e.type.startsWith('tool.') ? '⌁' : e.type.startsWith('context.') ? '▣' : e.type.startsWith('librarian.') ? '◇' : e.type.includes('failed') ? '!' : e.type.includes('completed') ? '✓' : '•';
    const cls = e.status === 'failed' ? 'bad' : e.status === 'succeeded' ? 'good' : e.status === 'blocked' ? 'warn' : '';
    let detail = '';
    if (e.type === 'group.plan.inspected' && e.payload) detail = `<pre>${esc(JSON.stringify(e.payload,null,2))}</pre>`;
    if (e.type === 'worker.completed' && e.payload?.text) detail = `<div class="assistant-text">${esc(e.payload.text)}</div>`;
    if (e.type === 'turn.started') detail = `<div class="user-text">${esc(e.summary)}</div>`;
    return `<article class="event ${cls}"><div class="event-icon">${icon}</div><div><div class="event-head"><span>${esc(e.type)}</span><time>${new Date(e.emittedAt).toLocaleTimeString()}</time></div><div class="event-summary">${esc(e.summary)}</div>${detail}</div></article>`;
  }).join('');
}

function bind() {
  const mode=document.getElementById('mode'), worker=document.getElementById('worker'), eff=document.getElementById('effect'), prompt=document.getElementById('prompt');
  const persistSelection=()=>vscode.setState?.({serviceId:currentService,workerId:currentWorker});
  const service=document.getElementById('service');
  service.onchange=()=>{currentService=service.value;currentWorker='auto';persistSelection();render();};
  mode.onchange=()=>{currentMode=mode.value}; worker.onchange=()=>{currentWorker=worker.value;persistSelection();}; eff.onchange=()=>{effect=eff.value};
  document.getElementById('send').onclick=()=>{ const message=prompt.value.trim(); if(!message)return; const selected=(state.workers||[]).find(w=>w.workerId===currentWorker); send('sendTurn',{taskId:state.task?.taskId||null,runId:null,message,mode:currentMode,workerId:currentWorker,serviceId:currentService,modelId:selected?.modelId||'auto',maxEffectClass:effect}); prompt.value=''; };
  prompt.onkeydown=e=>{ if((e.ctrlKey||e.metaKey)&&e.key==='Enter') document.getElementById('send').click(); };
  document.getElementById('control').onclick=()=>send('openControlPlane'); const cancel=document.getElementById('cancel'); if(cancel) cancel.onclick=()=>send('cancelRun',{runId:state.run.runId});
  const resume=document.getElementById('resume'); if(resume) resume.onclick=()=>{
    const message=prompt.value.trim(); if(!message){prompt.focus();return;}
    const selected=(state.workers||[]).find(w=>w.workerId===currentWorker);
    send('sendTurn',{taskId:state.task.taskId,runId:state.run.runId,resume:true,message,mode:currentMode,
      workerId:currentWorker,serviceId:currentService,modelId:selected?.modelId||'auto',maxEffectClass:effect}); prompt.value='';
  };
  document.getElementById('inspectPreparedPlan').onclick=()=>{
    const planId=document.getElementById('preparedPlanId'), digest=document.getElementById('preparedPlanDigest');
    if(!/^task-plan-[a-f0-9]{24}$/.test(planId.value)){planId.focus();return;}
    if(!/^[a-f0-9]{64}$/.test(digest.value)){digest.focus();return;}
    send('inspectPreparedGroup',{reference:{schema_version:'px.prepared-group-reference/1.0',plan_id:planId.value,plan_sha256:digest.value}});
  };
  document.getElementById('executePreparedGroup').onclick=()=>{
    const planId=document.getElementById('preparedPlanId'), digest=document.getElementById('preparedPlanDigest');
    if(!/^task-plan-[a-f0-9]{24}$/.test(planId.value)){planId.focus();return;}
    if(!/^[a-f0-9]{64}$/.test(digest.value)){digest.focus();return;}
    send('executePreparedGroup',{reference:{schema_version:'px.prepared-group-reference/1.0',plan_id:planId.value,plan_sha256:digest.value}});
  };
  const refresh=document.getElementById('refreshModels'); if(refresh) refresh.onclick=()=>send('refreshModels');
}

window.addEventListener('message', event => { const msg=event.data; if(msg?.schemaVersion!==protocol.message)return; if(msg.type==='snapshot'){state=msg.state;render();} else if(msg.type==='event'){ /* snapshot follows; preserve ordering */ } else if(msg.type==='error'){ console.error('PX Agent Console',msg.code,msg.detail); } });
send('ready',{assetProtocol:protocol.asset}); render();
