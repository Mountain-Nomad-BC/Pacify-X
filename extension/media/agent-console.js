'use strict';

const vscode = acquireVsCodeApi();
const protocol = window.__PX_AGENT_PROTOCOL__;
let state = null; let currentMode = 'DIAGNOSE'; let currentWorker = 'auto'; let effect = 'READ_ONLY'; let streamed = ''; let lastStreamRun = null;

function send(type, payload = {}) { vscode.postMessage({ schemaVersion: protocol.message, type, ...payload }); }
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function fmtMoney(value) { return value == null ? 'unknown' : `$${Number(value).toFixed(3)}`; }
function badge(text, cls='') { return `<span class="badge ${cls}">${esc(text)}</span>`; }

function render() {
  const app = document.getElementById('app'); if (!state) { app.innerHTML = `<section class="loading">Starting PX harness…</section>`; return; }
  const task = state.task; const run = state.run; const lib = state.librarian; const ctx = state.context; const route = state.route; const workers = state.workers || [];
  const selected = route?.selectedWorkerId ? workers.find(w => w.workerId === route.selectedWorkerId) : null;
  app.innerHTML = `
    <header class="topbar"><div><div class="eyebrow">PACIFY-X</div><h1>Agent Console</h1></div><div class="health ${selected?.health?.status || 'idle'}">● ${esc(selected?.health?.status || 'IDLE')}</div></header>
    <section class="activity panel">
      <div class="panel-title"><span>TINY / LIBRARIAN</span>${lib ? badge(`${Math.round(lib.confidence*100)}%`) : badge('waiting')}</div>
      <div class="activity-track"><span class="step ${lib?'done':'active'}">classify</span><span>→</span><span class="step ${ctx?'done':''}">retrieve</span><span>→</span><span class="step ${ctx?'done':''}">compile</span><span>→</span><span class="step ${selected?'done':''}">route</span></div>
      <div class="subtle">${lib ? `${esc(lib.intent)} · ${esc(lib.domains.join(', '))}` : 'No classification yet.'}</div>
      <div class="metrics"><span>${ctx ? `${ctx.selectedCount}/${ctx.consideredCount} refs` : '0 refs'}</span><span>${ctx ? `${ctx.suppliedTokens}/${ctx.budgetTokens} ctx` : '0 ctx'}</span><span>${lib ? `${Math.round(lib.durationMs)}ms` : '—'}</span></div>
      <details><summary>Inspect librarian artifact</summary><pre>${esc(lib ? JSON.stringify(lib,null,2) : 'No artifact yet.')}</pre></details>
    </section>
    <section class="route panel">
      <div class="panel-title"><span>ROUTE</span>${selected ? badge(selected.costClass, selected.costClass) : badge('none')}</div>
      <div class="route-line">${selected ? `<strong>${esc(selected.displayName)}</strong><span>${esc(selected.providerId)} / ${esc(selected.modelId)}</span>` : '<strong>No admitted worker selected</strong>'}</div>
      <div class="metrics"><span>${state.budget?.totalTokens || 0} tokens</span><span>${fmtMoney(state.budget?.actualChargeUsd)}</span><span>${state.budget?.receiptCount || 0} receipts</span></div>
      <details><summary>Admission / route details</summary><div class="route-grid">${(route?.evaluated || []).map(r => `<div class="route-row"><span>${esc(r.displayName)}</span><span>${r.admitted ? badge('admitted','good') : badge(r.reasons.join(', ') || 'rejected','bad')}</span><span>${r.score == null ? '—' : r.score.toFixed(3)}</span></div>`).join('') || '<span class="subtle">No route evaluation yet.</span>'}</div></details>
    </section>
    <section class="transcript" id="transcript">${renderTranscript()}</section>
    <section class="composer panel">
      <div class="composer-controls">
        <select id="mode">${['ASK','PLAN','DIAGNOSE','IMPLEMENT','REVIEW','CAMPAIGN'].map(v => `<option ${v===currentMode?'selected':''}>${v}</option>`).join('')}</select>
        <select id="worker"><option value="auto">AUTO ROUTE</option>${workers.filter(w=>w.enabled).map(w => `<option value="${esc(w.workerId)}" ${w.workerId===currentWorker?'selected':''}>${esc(w.displayName)}</option>`).join('')}</select>
        <select id="effect">${['READ_ONLY','LOW_RISK','MUTATING','HIGH_RISK'].map(v => `<option ${v===effect?'selected':''}>${v}</option>`).join('')}</select>
      </div>
      <textarea id="prompt" rows="4" placeholder="Ask PX…"></textarea>
      <div class="composer-actions"><button id="control">Control Plane</button>${run?.status==='running'?'<button id="cancel" class="danger">Interrupt</button>':''}<button id="send" class="primary">Send</button></div>
    </section>`;
  bind(); requestAnimationFrame(() => { const t=document.getElementById('transcript'); if(t) t.scrollTop=t.scrollHeight; });
}

function renderTranscript() {
  const events = state.events || []; if (!events.length) return `<div class="empty"><h2>PX is ready.</h2><p>Start a task. The sidebar will show classification, context, routing, worker output, tools, evidence and budget events from one PX-owned run.</p></div>`;
  return events.map(e => {
    if (e.type === 'worker.stream.delta') return `<div class="stream">${esc(e.payload?.delta || e.summary)}</div>`;
    const icon = e.type.startsWith('tool.') ? '⌁' : e.type.startsWith('context.') ? '▣' : e.type.startsWith('librarian.') ? '◇' : e.type.includes('failed') ? '!' : e.type.includes('completed') ? '✓' : '•';
    const cls = e.status === 'failed' ? 'bad' : e.status === 'succeeded' ? 'good' : e.status === 'blocked' ? 'warn' : '';
    let detail = '';
    if (e.type === 'worker.completed' && e.payload?.text) detail = `<div class="assistant-text">${esc(e.payload.text)}</div>`;
    if (e.type === 'turn.started') detail = `<div class="user-text">${esc(e.summary)}</div>`;
    return `<article class="event ${cls}"><div class="event-icon">${icon}</div><div><div class="event-head"><span>${esc(e.type)}</span><time>${new Date(e.emittedAt).toLocaleTimeString()}</time></div><div class="event-summary">${esc(e.summary)}</div>${detail}</div></article>`;
  }).join('');
}

function bind() {
  const mode=document.getElementById('mode'), worker=document.getElementById('worker'), eff=document.getElementById('effect'), prompt=document.getElementById('prompt');
  mode.onchange=()=>{currentMode=mode.value}; worker.onchange=()=>{currentWorker=worker.value}; eff.onchange=()=>{effect=eff.value};
  document.getElementById('send').onclick=()=>{ const message=prompt.value.trim(); if(!message)return; send('sendTurn',{taskId:state.task?.taskId||null,runId:null,message,mode:currentMode,workerId:currentWorker,maxEffectClass:effect}); prompt.value=''; };
  prompt.onkeydown=e=>{ if((e.ctrlKey||e.metaKey)&&e.key==='Enter') document.getElementById('send').click(); };
  document.getElementById('control').onclick=()=>send('openControlPlane'); const cancel=document.getElementById('cancel'); if(cancel) cancel.onclick=()=>send('cancelRun',{runId:state.run.runId});
}

window.addEventListener('message', event => { const msg=event.data; if(msg?.schemaVersion!==protocol.message)return; if(msg.type==='snapshot'){state=msg.state;render();} else if(msg.type==='event'){ /* snapshot follows; preserve ordering */ } else if(msg.type==='error'){ console.error('PX Agent Console',msg.code,msg.detail); } });
send('ready',{assetProtocol:protocol.asset}); render();
