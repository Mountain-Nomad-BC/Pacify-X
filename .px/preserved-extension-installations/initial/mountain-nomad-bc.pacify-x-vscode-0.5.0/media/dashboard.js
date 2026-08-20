'use strict';

const vscode = acquireVsCodeApi();
const app = document.getElementById('app');
const shieldUri = app.dataset.shieldUri;
const brandUri = app.dataset.brandUri || shieldUri;

const visibleSurfaces = [
  ['dashboard', 'Dashboard', 'pulse'], ['projects', 'Projects', 'folder'], ['agents', 'Agents', 'agents'],
  ['knowledgeGraph', 'Knowledge Graph', 'graph'], ['skillsTools', 'Skills & Tools', 'tools'], ['workflows', 'Workflows', 'flow'],
  ['plugins', 'Plugin Manager', 'plugin'], ['memory', 'Memory', 'memory'], ['activity', 'Activity', 'activity'],
  ['diagnostics', 'Diagnostics', 'diagnostics'], ['assurance', 'Assurance', 'shield'], ['settings', 'Settings', 'settings']
];
const advancedSurfaces = [['knowledgeCore', 'Knowledge Core', 'knowledge'], ['runtimeCore', 'Runtime Core', 'runtime']];

let state = {
  active: vscode.getState()?.active || 'dashboard', advancedOpen: vscode.getState()?.advancedOpen || false,
  capabilityKind: vscode.getState()?.capabilityKind || 'skills', snapshot: null, coordination: null,
  agentScope: vscode.getState()?.agentScope || 'core', workflowScope: vscode.getState()?.workflowScope || 'core',
  environmentScope: vscode.getState()?.environmentScope || 'graph',
  graphView: vscode.getState()?.graphView || 'capabilities', graphData: null, graphPending: false, graphRequestId: null,
  graphLayout: vscode.getState()?.graphLayout || 'flow', graphInspectorOpen: vscode.getState()?.graphInspectorOpen !== false,
  memoryData: null, memoryPending: false, memoryRequestId: null, memoryQuery: '',
  activityData: null, activityPending: false, activityRequestId: null, activityQuery: '', activityCategory: '', activityStatus: '',
  settings: { showAdvancedSurfaces: Boolean(window.__PX_PREVIEW_ADVANCED__), glassIntensity: 0.66 },
  catalogs: {}, catalogRequests: {}, environmentData: {}, environmentPending: {}, operation: null, clientActor: null
};
let modalCopyText = '';
let modalReturnFocus = null;
let modalTitle = '';
let modalRecord = null;
let modalHumanText = '';
let cleanupState = { inventory: null, selected: new Set(), lastResult: null };
let searchTimer; let graphResizeTimer;
const graphInteraction = {
  x: 0, y: 0, scale: 1, minScale: 0.35, maxScale: 2.4, sceneKey: '', fitted: false,
  pointers: new Map(), dragOrigin: null, pinchOrigin: null
};

const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
const number = value => Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '—';
function bytes(value) {
  const size = Number(value || 0); if (!Number.isFinite(size)) return 'Unavailable'; if (!size) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB']; const power = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
  return `${(size / (1024 ** power)).toFixed(power ? 1 : 0)} ${units[power]}`;
}
function icon(name) {
  const paths = {
    pulse: '<path d="M3 12h4l2-6 4 12 2-6h6"/>', folder: '<path d="M3 7h7l2 2h9v10H3z"/>',
    agents: '<circle cx="9" cy="9" r="3"/><circle cx="17" cy="10" r="2.5"/><path d="M3.5 20c.5-4 2.5-6 5.5-6s5 2 5.5 6M14 15c3.5-.5 5.5 1 6 4"/>',
    graph: '<circle cx="5" cy="12" r="2"/><circle cx="18" cy="5" r="2"/><circle cx="19" cy="18" r="2"/><path d="m7 11 9-5M7 13l10 4M18 7l1 9"/>',
    tools: '<path d="M14 6a4 4 0 0 0-5 5L3 17l4 4 6-6a4 4 0 0 0 5-5l-3 2-3-3z"/>',
    flow: '<rect x="3" y="4" width="6" height="5" rx="1"/><rect x="15" y="15" width="6" height="5" rx="1"/><path d="M9 6.5h4a4 4 0 0 1 4 4V15m0 0-2-2m2 2 2-2"/>',
    plugin: '<path d="M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-6 6v4m-3 0h6"/>',
    memory: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    activity: '<path d="M3 12h4l2-5 4 10 2-5h6"/><circle cx="4" cy="12" r="1"/><circle cx="20" cy="12" r="1"/>',
    diagnostics: '<path d="M4 12h3l2-5 4 10 2-5h5M4 4v16h16"/>',
    shield: '<path d="M12 3 4.5 6v5c0 4.8 3 8 7.5 10 4.5-2 7.5-5.2 7.5-10V6z"/><path d="m9 12 2 2 4-5"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M19 5l-2 2M7 17l-2 2"/>',
    knowledge: '<path d="M4 4h7a3 3 0 0 1 3 3v13a3 3 0 0 0-3-3H4zM20 4h-3a3 3 0 0 0-3 3v13a3 3 0 0 1 3-3h3z"/>',
    runtime: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3m5 0h5"/>'
  };
  return `<svg class="nav-icon icon-${esc(name)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths[name] || paths.pulse}</svg>`;
}
function badge(label, tone = 'neutral') { return `<span class="badge ${tone}">${esc(label)}</span>`; }
function unavailable(label = 'Not instrumented') { return `<span class="unavailable">${esc(label)}</span>`; }
function card(label, value, detail = '', tone = '') {
  return `<article class="metric-card ${esc(tone)}" role="button" tabindex="0" data-action="inspectMetric" data-label="${esc(label)}" data-value="${esc(value)}" data-detail="${esc(detail)}"><span class="metric-label">${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(detail)}</small><i class="inspect-cue">DETAILS</i></article>`;
}
function section(title, kicker, content, extra = '') {
  return `<section class="panel"><div class="panel-heading"><div><span class="eyebrow">${esc(kicker)}</span><h2>${esc(title)}</h2></div><div class="panel-heading-actions">${extra}<button class="panel-control" data-action="inspectPanel" title="Inspect and copy this panel">INSPECT</button></div></div>${content}</section>`;
}
function empty(message) { return `<div class="empty-state"><span class="empty-ring"></span><p>${esc(message)}</p></div>`; }

function showModal(title, kicker, body, actions = '', modalClass = '') {
  modalReturnFocus = document.activeElement;
  const root = document.getElementById('modal-root'); if (!root) return;
  root.innerHTML = `<div class="modal-backdrop"><section class="control-modal ${esc(modalClass)}" role="dialog" aria-modal="true" aria-label="${esc(title)}" tabindex="-1"><header><div><span class="eyebrow">${esc(kicker)}</span><h2>${esc(title)}</h2></div><button class="modal-close" data-action="closeModal" aria-label="Close">×</button></header><div class="modal-body">${body}</div><footer>${actions || '<button class="primary" data-action="closeModal">Done</button>'}</footer></section></div>`;
  root.querySelector('.control-modal')?.focus();
}
function readableValue(value) {
  if (value === null || value === undefined || value === '') return 'Not declared';
  if (Array.isArray(value)) return value.length ? value.map(item => typeof item === 'object' ? JSON.stringify(item) : String(item)).join(', ') : 'None';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}
function humanRecord(record) {
  const priority = ['summary', 'description', 'status', 'kind', 'owner', 'path', 'source', 'effects', 'inputs', 'outputs', 'dependencies', 'provenance', 'license', 'risk', 'sampled_at', 'available', 'error'];
  const keys = [...priority.filter(key => Object.hasOwn(record || {}, key)), ...Object.keys(record || {}).filter(key => !priority.includes(key) && !['details'].includes(key)).sort()];
  return `<dl class="modal-detail">${keys.map(key => `<div><dt>${esc(key.replaceAll('_', ' '))}</dt><dd class="${['path', 'source', 'id', 'key'].includes(key) ? 'mono' : ''}">${esc(readableValue(record[key]))}</dd></div>`).join('')}</dl>`;
}
function showInformationModal(title, kicker, record, humanHtml = '') {
  modalTitle = title;
  modalRecord = record ?? null;
  const machine = JSON.stringify(modalRecord, null, 2);
  modalHumanText = Object.entries(modalRecord || {}).filter(([key]) => key !== 'details').map(([key, value]) => `${key.replaceAll('_', ' ')}: ${readableValue(value)}`).join('\n');
  modalCopyText = modalHumanText;
  const body = `<div class="information-tabs" role="tablist" aria-label="Information format"><button id="info-human-tab" role="tab" aria-selected="true" aria-controls="info-human" tabindex="0" data-action="informationTab" data-tab="human">Human readable</button><button id="info-machine-tab" role="tab" aria-selected="false" aria-controls="info-machine" tabindex="-1" data-action="informationTab" data-tab="machine">Machine readable</button></div><section id="info-human" class="information-panel" role="tabpanel" aria-labelledby="info-human-tab">${humanHtml || humanRecord(modalRecord || {})}</section><section id="info-machine" class="information-panel" role="tabpanel" aria-labelledby="info-machine-tab" hidden><pre class="modal-readout">${esc(machine)}</pre></section>`;
  showModal(title, kicker, body, '<button data-action="copyModal">Copy current view</button><button data-action="exportRecordJson">Export JSON</button><button class="primary" data-action="closeModal">Done</button>', humanHtml.includes('agent-model-layout') ? 'wide-modal' : '');
}
function switchInformationTab(tab) {
  const machine = tab === 'machine';
  document.getElementById('info-human')?.toggleAttribute('hidden', machine);
  document.getElementById('info-machine')?.toggleAttribute('hidden', !machine);
  const humanTab = document.getElementById('info-human-tab'); const machineTab = document.getElementById('info-machine-tab');
  humanTab?.setAttribute('aria-selected', String(!machine)); humanTab?.setAttribute('tabindex', machine ? '-1' : '0');
  machineTab?.setAttribute('aria-selected', String(machine)); machineTab?.setAttribute('tabindex', machine ? '0' : '-1');
  modalCopyText = machine ? JSON.stringify(modalRecord, null, 2) : modalHumanText;
  (machine ? machineTab : humanTab)?.focus();
}
function closeModal() {
  const root = document.getElementById('modal-root'); if (root) root.innerHTML = '';
  modalCopyText = ''; modalTitle = ''; modalRecord = null; modalHumanText = ''; modalReturnFocus?.focus?.(); modalReturnFocus = null;
}

function navButton([id, label, symbol]) {
  const active = state.active === id;
  return `<button class="nav-item${active ? ' active' : ''}" data-surface="${id}" aria-current="${active ? 'page' : 'false'}">${icon(symbol)}<span>${esc(label)}</span></button>`;
}

function render() {
  const s = state.snapshot; const connected = Boolean(s?.connected); const advancedVisible = state.settings.showAdvancedSurfaces;
  if (!advancedVisible && advancedSurfaces.some(([id]) => id === state.active)) state.active = 'dashboard';
  const title = [...visibleSurfaces, ...advancedSurfaces].find(([id]) => id === state.active)?.[1] || 'Dashboard';
  app.className = connected ? 'connected' : 'disconnected';
  app.style.setProperty('--glass-opacity', String(state.settings.glassIntensity || 0.66));
  app.innerHTML = `
    <a class="skip-link" href="#main-content">Skip navigation</a><div class="shell">
      <aside class="control-rail">
        <div class="brand-block"><div class="brand-frame"><img src="${brandUri}" alt="" class="brand-mark"></div><div class="brand-copy"><strong>PACIFY-X</strong><span>CONTROL PLANE</span></div></div>
        <nav class="nav-rail" aria-label="Pacify-X dashboard navigation">
          <div class="primary-nav">${visibleSurfaces.map(navButton).join('')}</div>
          <div class="advanced-wrap"><button class="advanced-toggle${advancedSurfaces.some(([id]) => id === state.active) ? ' active' : ''}" data-action="toggleAdvanced" aria-expanded="${state.advancedOpen}">${icon('runtime')}<span>Advanced</span><b>${advancedVisible ? (state.advancedOpen ? '−' : '+') : 'LOCKED'}</b></button>
          ${advancedVisible && state.advancedOpen ? `<div class="advanced-nav">${advancedSurfaces.map(navButton).join('')}</div>` : ''}</div>
        </nav>
        <div class="rail-status"><span><i class="live-pip"></i>${connected ? 'CANONICAL API' : 'DISCONNECTED'}</span><small>${esc(s?.schemaVersion || 'schema unavailable')}</small></div>
      </aside>
      <main class="workspace" id="main-content" tabindex="-1">
        <header class="cockpit-header">
          <div class="page-identity"><span class="breadcrumb">PACIFY-X / ${advancedSurfaces.some(([id]) => id === state.active) ? 'ADVANCED / ' : ''}${esc(title.toUpperCase())}</span><h1>${esc(title)}</h1></div>
          <div class="telemetry-cell"><span>WORKSPACE</span><strong>${esc(s?.project?.name || 'Awaiting engine')}</strong><small>${esc(s?.source?.mode || 'not resolved')}</small></div>
          <div class="telemetry-cell"><span>BRANCH</span><strong>${esc(s?.git?.branch || s?.project?.branch || '—')}</strong><small>${s?.git?.dirty ? `${number((s.git.staged || 0) + (s.git.unstaged || 0) + (s.git.untracked || 0))} changes` : 'clean/unknown'}</small></div>
          <div class="telemetry-cell"><span>COORDINATION</span><strong>${state.coordination?.state?.active_plan ? 'Plan active' : 'Ready'}</strong><small>${number(state.coordination?.state?.claims?.length || 0)} active claims</small></div>
          <div class="cockpit-actions"><button class="sync-button" data-action="refresh">↻ Sync</button><button class="control-button" data-action="commandCenter">Controls</button><button class="icon-button" data-action="openSettings" title="Settings" aria-label="Settings">⚙</button></div>
        </header>
        <div class="top-status">
          ${badge(connected ? 'LIVE PACIFY-X SOURCE' : 'DISCONNECTED', connected ? 'success' : 'warning')}
          ${badge(s?.provider?.chatGptAuthenticated ? 'CHATGPT AUTH VERIFIED' : 'BILLABLE API FALLBACK OFF', 'info')}
          ${badge(s?.git?.operation === 'none' ? 'GIT BOUNDARY READY' : `GIT ${s?.git?.operation || 'UNKNOWN'}`, s?.git?.operation === 'none' ? 'success' : 'warning')}
          ${badge(s?.runtime?.turbovec?.status || 'TURBOVEC UNKNOWN', s?.runtime?.turbovec?.active ? 'success' : 'neutral')}
          ${badge(s?.enterprise?.catalog_id ? 'MS+ENTERPRISE OFFLINE BOUNDARY' : 'ENTERPRISE UNAVAILABLE', s?.enterprise?.catalog_id ? 'info' : 'neutral')}
        </div>
        <div class="content">${surface(state.active)}</div>
        <footer class="footer"><span><i class="live-pip"></i>${connected ? 'PX CONNECTED' : 'PX DISCONNECTED'}</span><span>Catalog: ${esc(s?.catalogSource || 'unavailable')}</span><span>Context: Level 2 + rolling ledger</span><span>Billable API fallback: Disabled</span><span>${s?.generatedAt ? `Snapshot ${esc(new Date(s.generatedAt).toLocaleTimeString())}` : 'Awaiting snapshot'}</span></footer>
      </main>
    </div><div id="modal-root"></div>`;
  vscode.setState({ active: state.active, advancedOpen: state.advancedOpen, capabilityKind: state.capabilityKind, agentScope: state.agentScope, workflowScope: state.workflowScope, environmentScope: state.environmentScope, graphView: state.graphView, graphLayout: state.graphLayout, graphInspectorOpen: state.graphInspectorOpen });
  ensureSurfaceData();
  if (state.active === 'knowledgeGraph') requestAnimationFrame(prepareGraphInteraction);
}

function surface(id) {
  if (!state.snapshot) return loading();
  const renders = { dashboard, projects, agents, knowledgeGraph, skillsTools, workflows, plugins, memory, activity, diagnostics, assurance, settings, knowledgeCore, runtimeCore };
  return (renders[id] || dashboard)();
}
function loading() { return `<div class="loading"><img src="${shieldUri}" alt=""><span class="scan-line"></span><h2>Reading the Pacify-X control plane</h2><p>Discovery is bounded and read-only.</p></div>`; }

function attentionList() {
  const items = state.snapshot.attention || [];
  return items.length ? `<div class="attention-list">${items.map(item => `<article class="attention ${esc(item.severity)}"><span class="attention-mark"></span><div><strong>${esc(item.title)}</strong><p>${esc(item.detail)}</p></div>${badge(item.severity.toUpperCase(), item.severity === 'warning' ? 'warning' : 'info')}</article>`).join('')}</div>` : empty('No attention items were reported.');
}

function dashboard() {
  const s = state.snapshot; const c = state.coordination?.state;
  return `<section class="hero panel"><div class="watermark"><img src="${shieldUri}" alt=""></div><div class="hero-copy"><span class="eyebrow">PACIFY-X CONTROL PLANE</span><h2>${s.connected ? 'Authoritative operations, coordinated across IDEs.' : 'Connect the Pacify-X engine.'}</h2><p>${s.connected ? `First-class runtime.dashboard_api source · ${esc(s.project.name)} · project-owned rolling handoff.` : esc(s.reason)}</p><div class="hero-actions"><button class="primary" data-action="refresh">Synchronize state</button><button class="secondary" data-surface="workflows">Parallel plan</button><button class="secondary" data-surface="diagnostics">Diagnostics</button></div></div><div class="hero-status"><div class="radar"><span></span><b>PX</b></div><strong>${s.connected ? 'SYSTEMS LINKED' : 'AWAITING ROOT'}</strong><small>${esc(s.source.mode)} · v${esc(s.source.version)}</small></div></section>
  <div class="metric-grid">${card('SKILLS', number(s.counts.skills), 'complete lazy catalog', 'blue')}${card('TOOLS', number(s.counts.tools), 'complete lazy catalog')}${card('AGENTS', number(s.counts.agents), 'complete lazy catalog')}${card('ORCHESTRATIONS', number(s.counts.workflows), 'project + skill + bindings')}${card('GRAPH', number(s.counts.graphRecords), `${number(s.counts.graphEdges)} edges`)}${card('CLAIMS', number(c?.claims?.length || 0), c?.active_plan || 'no active plan')}</div>
  <div class="dashboard-grid">${section('Attention queue', 'SIGNALS REQUIRING REVIEW', attentionList(), `<span class="count-chip">${number(s.attention.length)}</span>`)}${section('Parallel work', 'CURRENT COORDINATION STATE', coordinationSummary())}${section('Core services', 'DISCOVERED STATUS', serviceGrid())}${section('Thermals & sensors', 'LIVE · SOURCE-LABELLED', thermalPanel())}${section('Recent rolling activity', 'PROJECT LEDGER', eventTimeline(8))}</div>`;
}

function projects() {
  const s = state.snapshot; const c = state.coordination?.state;
  return `<div class="metric-grid compact">${card('ACTIVE PROJECT', s.project.name, s.project.branch, 'blue')}${card('SOURCE MODE', s.source.mode, `v${s.source.version}`)}${card('PROJECT MAP', s.project.map?.valid ? 'Available' : 'Unavailable', `${number(s.project.map?.counts?.files)} files`)}${card('STATE HASH', c?.state_hash?.slice(0, 12) || 'Not initialized', 'coordination revision')}</div>
  <div class="two-col wide-left">${section('Project authority', 'CURRENT CONTEXT', `<dl class="detail-list"><div><dt>Engine root</dt><dd class="mono">${esc(s.source.engineRoot || 'Not configured')}</dd></div><div><dt>Project root</dt><dd class="mono">${esc(s.project.path || 'Unavailable')}</dd></div><div><dt>Branch / commit</dt><dd>${esc(s.project.branch)} · ${esc(s.source.commit || 'unknown')}</dd></div><div><dt>Coordination ledger</dt><dd class="mono">${esc(state.coordination?.paths?.root || 'Not initialized')}</dd></div></dl><div class="action-grid"><button class="secondary" data-action="openEngineRoot">Open README</button><button data-action="openCoordinationHandoff">Open handoff</button></div>`)}${section('Ownership boundary', 'SYMBIOTIC CLIENT', `<div class="boundary-stack"><div><b>VS Code-compatible host</b><span>Editor, UI and actor identity</span></div><i>→</i><div><b>Extension typed bridge</b><span>Coordination and safe adapters</span></div><i>→</i><div><b>Pacify-X runtime</b><span>Canonical registries, memory and policy</span></div></div>`)}</div>`;
}

function catalogPanel(kind, title, kicker) {
  const catalog = state.catalogs[kind]; const request = state.catalogRequests[kind] || { query: '', offset: 0, limit: 50, sort: 'label' };
  if (!catalog) return section(title, kicker, `<div class="catalog-loading"><span class="empty-ring"></span><p>Loading a bounded page from runtime.dashboard_api…</p></div>`);
  const rows = catalog.items.map(item => `<button class="catalog-row" data-action="inspectCatalogItem" data-kind="${kind}" data-id="${esc(item.id)}"><span class="catalog-primary"><strong>${esc(item.label)}</strong><small>${esc(item.id)} · ${esc(item.summary || 'No summary')}</small></span><span>${badge(item.kind, 'info')}</span><span>${badge(item.status, item.status === 'active' || item.status === 'admitted' ? 'success' : 'neutral')}</span><span class="catalog-risk">${esc(item.risk || item.effects?.join(', ') || 'bounded')}</span><b>DETAILS</b></button>`).join('');
  const first = catalog.filtered ? catalog.offset + 1 : 0; const last = Math.min(catalog.offset + catalog.items.length, catalog.filtered);
  return section(title, kicker, `<div class="catalog-controls"><label><span class="sr-only">Search ${esc(title)}</span><input data-catalog-search="${kind}" value="${esc(request.query)}" placeholder="Search all ${number(catalog.total)} records"></label><select data-catalog-sort="${kind}" aria-label="Sort ${esc(title)}"><option value="label" ${request.sort === 'label' ? 'selected' : ''}>Name</option><option value="id" ${request.sort === 'id' ? 'selected' : ''}>ID</option><option value="status" ${request.sort === 'status' ? 'selected' : ''}>Status</option><option value="kind" ${request.sort === 'kind' ? 'selected' : ''}>Kind</option></select><span>Showing ${number(first)}–${number(last)} of ${number(catalog.filtered)} (${number(catalog.total)} source records)</span></div><div class="catalog-scroll" role="list">${rows || empty('No records match this filter.')}</div><div class="pager"><button data-action="catalogPrevious" data-kind="${kind}" ${catalog.offset <= 0 ? 'disabled' : ''}>Previous</button><button data-action="catalogNext" data-kind="${kind}" ${catalog.has_more ? '' : 'disabled'}>Next</button></div>`, `<span class="count-chip">${number(catalog.total)}</span>`);
}

function agents() {
  const c = state.coordination?.state;
  const adapters = state.snapshot.teamFabric?.adapters || [];
  const adapterRows = adapters.map(item => `<article class="adapter-row"><div><strong>${esc(item.id)}</strong><small>${esc(item.kind)} · ${esc(item.capabilities.join(', '))}</small></div>${badge(item.status, item.status === 'ready' ? 'success' : item.status === 'disabled' ? 'neutral' : 'warning')}<span>${esc(item.authentication_identity)} / billing ${esc(item.billing_identity)}</span></article>`).join('');
  const enterprise = state.agentScope === 'enterprise';
  return `<div class="metric-grid compact">${card(enterprise ? 'ENTERPRISE AGENTS' : 'REGISTERED', number(enterprise ? state.snapshot.counts.enterprise_agents : state.snapshot.counts.agents), enterprise ? 'separate enterprise catalog' : 'all core source records')}${card('ACTIVE SESSIONS', number(c?.sessions?.filter(item => item.status === 'active').length || 0), 'cross-IDE actors')}${card('WORKER ADAPTERS', number(adapters.length), 'doctor + identity separation')}${card('BILLABLE FALLBACK', 'Disabled', 'no implicit provider')}</div><div class="catalog-tabs"><button data-action="surfaceScope" data-target="agents" data-scope="core" class="${enterprise ? '' : 'active'}">Core fleet</button><button data-action="surfaceScope" data-target="agents" data-scope="enterprise" class="${enterprise ? 'active' : ''}">MS+Enterprise</button></div>${enterprise ? `<div class="two-col wide-left">${catalogPanel('enterprise-agents', 'MS+Enterprise agents', 'SEPARATE NAMESPACE · NO CLOUD AUTHORITY')}${enterprisePackPanel()}</div>` : `<div class="two-col wide-left">${catalogPanel('agents', 'Agent fleet', 'COMPLETE PAGED REGISTRY')}${section('Worker adapters', 'TEAM FABRIC DOCTOR', `<div class="adapter-list">${adapterRows || unavailable()}</div><button class="primary" data-action="teamPackPreview">Audit / stage team package</button>`)}</div>`}`;
}

function enterprisePackPanel() {
  const catalog = state.snapshot.enterprise || {}; const local = state.snapshot.enterpriseState || { pack_states: {}, targets: [] };
  const rows = (catalog.packs || []).map(pack => {
    const enabled = Boolean(local.pack_states?.[pack.id]?.enabled);
    return `<article class="enterprise-pack-row"><div><strong>${esc(pack.name)}</strong><small>${esc(pack.id)} · ${esc(pack.priority)} · ${esc(pack.status)}</small><p>${esc((pack.capabilities || []).join(' · '))}</p></div><div>${badge(enabled ? 'OFFLINE ENABLED' : 'DISABLED', enabled ? 'success' : 'neutral')}<button data-action="enterprisePackToggle" data-pack-id="${esc(pack.id)}" data-enabled="${enabled ? 'false' : 'true'}">${enabled ? 'Disable' : 'Enable metadata'}</button><button data-action="enterpriseTargetConfigure" data-pack-id="${esc(pack.id)}">Target</button></div></article>`;
  }).join('');
  return section('Enterprise packs', 'SEPARATE PROJECT STATE · CONNECTORS STAY OFF', `<div class="enterprise-boundary"><b>Local control plane ready</b><span>Network deny · mutation deny · credential reads deny · billable services disabled</span></div><div class="enterprise-pack-list">${rows || unavailable()}</div><button class="primary" data-action="enterpriseDoctor">Run readiness doctor</button>`, `<span class="count-chip">${number((catalog.packs || []).length)}</span>`);
}

function knowledgeGraph() {
  const s = state.snapshot; const data = state.graphData;
  const graph = graphProjection(data);
  const relationOptions = (data?.relations || data?.available_relations || []).map(value => `<option value="${esc(value)}" ${(data?.requested_relation || data?.requestedRelation) === value ? 'selected' : ''}>${esc(value.replaceAll('_', ' '))}</option>`).join('');
  return `<div class="metric-grid compact">${card('NODES', number(s.counts.graphRecords), 'cognitive map records')}${card('EDGES', number(s.counts.graphEdges), 'typed relationships')}${card('VIEW', state.graphView === 'repository' ? 'Repository' : 'Capabilities', data?.source || 'bounded graph source')}${card('VISIBLE', number(data?.nodes?.length || 0), `${number(data?.edges?.length || 0)} relationships`)}</div>
  <div class="catalog-tabs graph-view-tabs"><button data-action="graphView" data-view="capabilities" class="${state.graphView === 'capabilities' ? 'active' : ''}">Capability map</button><button data-action="graphView" data-view="repository" class="${state.graphView === 'repository' ? 'active' : ''}">Repository / GitHub map</button></div>
  <section class="panel graph-panel"><div class="panel-heading"><div><span class="eyebrow">REAL BOUNDED RELATIONSHIPS</span><h2>${state.graphView === 'repository' ? 'Repository architecture explorer' : 'Knowledge graph explorer'}</h2><p class="graph-heading-note">Follow direction, inspect why, and move through the neighborhood without losing context.</p></div><div class="graph-tools"><input data-graph-search value="${esc(data?.requested_query || data?.requestedQuery || '')}" placeholder="Find a node, file, skill, agent…" aria-label="Search graph"><select data-graph-relation aria-label="Filter relationship"><option value="">All relationships</option>${relationOptions}</select><select data-graph-direction aria-label="Relationship direction"><option value="both" ${data?.direction === 'both' ? 'selected' : ''}>Both directions</option><option value="outgoing" ${data?.direction === 'outgoing' ? 'selected' : ''}>Outgoing</option><option value="incoming" ${data?.direction === 'incoming' ? 'selected' : ''}>Incoming</option></select><button class="primary" data-action="runGraphSearch">Explore</button></div></div>${graph}</section>${catalogPanel('graph', 'Graph record inspector', 'SEARCHABLE CANONICAL RECORDS')}`;
}

function graphPositions(data, ordered, width, height) {
  const center = data.selected; const positions = new Map([[center, { x: width / 2, y: height / 2 }]]);
  const neighbors = ordered.filter(item => item.key !== center);
  if (state.graphLayout === 'orbit') {
    const innerCount = neighbors.length > 14 ? 8 : neighbors.length;
    neighbors.forEach((item, index) => {
      const inner = index < innerCount; const ringIndex = inner ? index : index - innerCount; const ringCount = inner ? innerCount : neighbors.length - innerCount;
      const angle = -Math.PI / 2 + (Math.PI * 2 * ringIndex / Math.max(1, ringCount)) + (inner ? 0 : Math.PI / Math.max(1, ringCount));
      positions.set(item.key, { x: width / 2 + Math.cos(angle) * (inner ? 300 : 510), y: height / 2 + Math.sin(angle) * (inner ? 205 : 315) });
    });
    return positions;
  }
  const incoming = []; const outgoing = []; const contextual = [];
  for (const item of neighbors) {
    const comesIn = (data.edges || []).some(edge => edge.source === item.key && edge.target === center);
    const goesOut = (data.edges || []).some(edge => edge.source === center && edge.target === item.key);
    if (comesIn && !goesOut) incoming.push(item); else if (goesOut && !comesIn) outgoing.push(item); else contextual.push(item);
  }
  const placeLane = (items, side) => {
    const columns = Math.min(3, Math.max(1, Math.ceil(items.length / 9))); const perColumn = Math.ceil(items.length / columns);
    items.forEach((item, index) => {
      const column = Math.floor(index / perColumn); const row = index % perColumn; const rows = Math.min(perColumn, items.length - column * perColumn);
      const spread = columns === 1 ? 0 : 310 / (columns - 1); const x = side === 'left' ? (columns === 1 ? 290 : 150 + column * spread) : (columns === 1 ? width - 290 : width - 150 - column * spread);
      positions.set(item.key, { x, y: 82 + ((height - 164) * (row + 0.5) / Math.max(1, rows)) });
    });
  };
  placeLane(incoming, 'left'); placeLane(outgoing, 'right');
  contextual.forEach((item, index) => positions.set(item.key, { x: width / 2 + ((index % 5) - 2) * 175, y: Math.floor(index / 5) % 2 ? height - 70 : 70 }));
  return positions;
}

function graphProjection(data) {
  if (state.graphPending || !data) return `<div class="graph-loading"><span class="empty-ring"></span><p>Mapping a bounded real neighborhood…</p></div>`;
  if (!data.nodes?.length) return empty('No graph node matched this query. Try a different identifier or clear the relationship filter.');
  const width = 1280; const height = 780; const center = data.selected;
  const ordered = [...data.nodes].sort((a, b) => a.key === center ? -1 : b.key === center ? 1 : a.title.localeCompare(b.title));
  const selected = ordered.find(item => item.key === center) || ordered[0]; const positions = graphPositions(data, ordered, width, height);
  const edges = (data.edges || []).map((edge, index) => {
    const from = positions.get(edge.source); const to = positions.get(edge.target); if (!from || !to) return '';
    const dx = to.x - from.x; const dy = to.y - from.y; const length = Math.max(1, Math.hypot(dx, dy)); const bend = ((index % 5) - 2) * 7;
    const cx = (from.x + to.x) / 2 - (dy / length) * bend; const cy = (from.y + to.y) / 2 + (dx / length) * bend; const edgeId = `graph-edge-${index}`;
    return `<g class="graph-edge-group" data-edge-source="${esc(edge.source)}" data-edge-target="${esc(edge.target)}"><title>${esc(`${edge.source} ${edge.relation.replaceAll('_', ' ')} ${edge.target}. ${edge.why}`)}</title><path id="${edgeId}" d="M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}" marker-end="url(#graph-arrow)"></path><text><textPath href="#${edgeId}" startOffset="54%">${esc(edge.relation.replaceAll('_', ' '))}</textPath></text></g>`;
  }).join('');
  const nodes = ordered.map(item => {
    const point = positions.get(item.key); const isSelected = item.key === center;
    const connections = (data.edges || []).filter(edge => edge.source === item.key || edge.target === item.key).length;
    return `<button class="graph-node actual kind-${esc(item.kind)}${isSelected ? ' core selected' : ''}" style="--x:${point.x}px;--y:${point.y}px" data-action="focusGraphNode" data-node-key="${esc(item.key)}" aria-pressed="${isSelected}" aria-label="${esc(`${item.title}, ${item.kind}, ${item.status}, ${connections} connections`)}" title="${esc(item.summary || item.key)}"><b>${esc(item.title)}</b><span>${esc(item.kind)} · ${esc(item.status)}</span><small>${number(connections)} links</small></button>`;
  }).join('');
  const minimapNodes = ordered.map(item => { const point = positions.get(item.key); return `<i class="${item.key === center ? 'selected' : ''}" style="--mx:${(point.x / width * 100).toFixed(2)}%;--my:${(point.y / height * 100).toFixed(2)}%"></i>`; }).join('');
  const relationships = (data.edges || []).map(edge => {
    const target = edge.source === center ? edge.target : edge.source; const direction = edge.source === center ? 'outgoing' : edge.target === center ? 'incoming' : 'context';
    return `<button class="relationship-row" data-action="focusGraphNode" data-node-key="${esc(target)}"><span class="relationship-direction ${direction}">${direction === 'outgoing' ? 'OUT' : direction === 'incoming' ? 'IN' : 'LINK'}</span><span class="relationship-endpoint"><small>${esc(edge.source)}</small><b>${esc(edge.relation.replaceAll('_', ' '))}</b><small>${esc(edge.target)}</small></span><p>${esc(edge.why)}</p></button>`;
  }).join('');
  const incomingCount = (data.edges || []).filter(edge => edge.target === center).length; const outgoingCount = (data.edges || []).filter(edge => edge.source === center).length;
  const sceneKey = `${data.view}|${center}|${state.graphLayout}|${ordered.map(item => item.key).join('|')}`;
  return `<div class="graph-commandbar"><div class="graph-segmented" role="group" aria-label="Graph layout"><button data-action="graphLayout" data-layout="flow" aria-pressed="${state.graphLayout === 'flow'}">Flow</button><button data-action="graphLayout" data-layout="orbit" aria-pressed="${state.graphLayout === 'orbit'}">Orbit</button></div><div class="graph-zoom-controls" role="group" aria-label="Map zoom"><button data-action="graphZoomOut" aria-label="Zoom out">−</button><output data-graph-zoom aria-live="polite">100%</output><button data-action="graphZoomIn" aria-label="Zoom in">+</button><button data-action="graphFit">Fit</button><button data-action="graphReset">100%</button></div><button class="graph-inspector-toggle" data-action="graphToggleInspector" aria-pressed="${state.graphInspectorOpen}">${state.graphInspectorOpen ? 'Hide' : 'Show'} connections</button><span class="graph-gesture-help">Drag to pan · two-finger scroll to move · pinch or Ctrl+wheel to zoom</span></div><div class="graph-workspace${state.graphInspectorOpen ? '' : ' inspector-collapsed'}"><div class="graph-stage"><div class="graph-canvas" data-graph-canvas data-scene-key="${esc(sceneKey)}" data-scene-width="${width}" data-scene-height="${height}" tabindex="0" role="region" aria-label="Interactive ${esc(data.view)} relationship map. Drag to pan. Pinch, Control plus wheel, or plus and minus keys to zoom."><div class="graph-scene" data-graph-scene style="width:${width}px;height:${height}px"><svg viewBox="0 0 ${width} ${height}" aria-hidden="true" focusable="false"><defs><marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${edges}</svg>${nodes}</div><article class="graph-selection-card"><span>FOCUS NODE</span><strong>${esc(selected?.title || center)}</strong><small>${esc(selected?.key || center)}</small><div><b>${esc(selected?.kind || 'node')}</b><i>${number(incomingCount)} in</i><i>${number(outgoingCount)} out</i></div></article><div class="graph-minimap" aria-hidden="true"><div>${minimapNodes}<span data-graph-minimap-viewport></span></div></div><span class="graph-interaction-status" data-graph-status role="status" aria-live="polite">Map fitted</span>${data.truncated ? '<span class="graph-truncated">Bounded neighborhood</span>' : ''}</div></div><aside class="relationship-inspector" aria-label="Readable relationship list"><header><div><span>CONNECTIONS FOR</span><strong>${esc(selected?.title || center)}</strong><small>${esc(center)}</small></div><div class="relationship-counts"><b>${number(data.edges.length)} total</b><span>${number(incomingCount)} incoming · ${number(outgoingCount)} outgoing</span></div></header><div>${relationships || empty('The selected node has no relationships in this direction/filter.')}</div></aside></div><div class="graph-legend"><span><i class="legend-skill"></i>Skill</span><span><i class="legend-agent"></i>Agent</span><span><i class="legend-file"></i>File / module</span><span><i class="legend-contract"></i>Contract / policy</span><span>Arrow runs source → target. Hover or focus a node to isolate its paths.</span><span>Keyboard: arrows pan · +/− zoom · 0 fits</span></div>`;
}

function graphCanvas() { return app.querySelector('[data-graph-canvas]'); }
function clampGraphScale(value) { return Math.min(graphInteraction.maxScale, Math.max(graphInteraction.minScale, value)); }
function graphStatus(message) { const status = app.querySelector('[data-graph-status]'); if (status) status.textContent = message; }
function applyGraphViewport(message = '') {
  const canvas = graphCanvas(); const scene = canvas?.querySelector('[data-graph-scene]'); if (!canvas || !scene) return;
  scene.style.transform = `translate3d(${graphInteraction.x}px, ${graphInteraction.y}px, 0) scale(${graphInteraction.scale})`;
  const output = app.querySelector('[data-graph-zoom]'); if (output) output.textContent = `${Math.round(graphInteraction.scale * 100)}%`;
  const minimapViewport = canvas.querySelector('[data-graph-minimap-viewport]');
  if (minimapViewport) {
    const width = Number(canvas.dataset.sceneWidth); const height = Number(canvas.dataset.sceneHeight);
    const left = Math.max(0, -graphInteraction.x / graphInteraction.scale); const top = Math.max(0, -graphInteraction.y / graphInteraction.scale);
    minimapViewport.style.left = `${Math.min(100, left / width * 100)}%`; minimapViewport.style.top = `${Math.min(100, top / height * 100)}%`;
    minimapViewport.style.width = `${Math.min(100, canvas.clientWidth / graphInteraction.scale / width * 100)}%`; minimapViewport.style.height = `${Math.min(100, canvas.clientHeight / graphInteraction.scale / height * 100)}%`;
  }
  if (message) graphStatus(message);
}
function fitGraphViewport(message = 'Map fitted') {
  const canvas = graphCanvas(); if (!canvas) return;
  const width = Number(canvas.dataset.sceneWidth); const height = Number(canvas.dataset.sceneHeight); const pad = canvas.clientWidth < 700 ? 18 : 42;
  graphInteraction.scale = clampGraphScale(Math.min((canvas.clientWidth - pad * 2) / width, (canvas.clientHeight - pad * 2) / height));
  graphInteraction.x = (canvas.clientWidth - width * graphInteraction.scale) / 2; graphInteraction.y = (canvas.clientHeight - height * graphInteraction.scale) / 2;
  graphInteraction.fitted = true; applyGraphViewport(message);
}
function resetGraphViewport() {
  const canvas = graphCanvas(); if (!canvas) return; const width = Number(canvas.dataset.sceneWidth); const height = Number(canvas.dataset.sceneHeight);
  graphInteraction.scale = 1; graphInteraction.x = (canvas.clientWidth - width) / 2; graphInteraction.y = (canvas.clientHeight - height) / 2;
  applyGraphViewport('Zoom reset to 100%');
}
function zoomGraphTo(scale, clientX, clientY, message = '') {
  const canvas = graphCanvas(); if (!canvas) return; const rect = canvas.getBoundingClientRect(); const next = clampGraphScale(scale); const old = graphInteraction.scale;
  const localX = Number.isFinite(clientX) ? clientX - rect.left : canvas.clientWidth / 2; const localY = Number.isFinite(clientY) ? clientY - rect.top : canvas.clientHeight / 2;
  const sceneX = (localX - graphInteraction.x) / old; const sceneY = (localY - graphInteraction.y) / old;
  graphInteraction.scale = next; graphInteraction.x = localX - sceneX * next; graphInteraction.y = localY - sceneY * next;
  applyGraphViewport(message || `Zoom ${Math.round(next * 100)}%`);
}
function prepareGraphInteraction() {
  const canvas = graphCanvas(); if (!canvas) return; const key = canvas.dataset.sceneKey;
  if (graphInteraction.sceneKey !== key || !graphInteraction.fitted) {
    graphInteraction.sceneKey = key; fitGraphViewport();
    if (canvas.clientWidth < 520 && graphInteraction.scale < 0.62) zoomGraphTo(0.62, undefined, undefined, 'Focused touch view · use Fit to see all');
  } else applyGraphViewport();
}
function highlightGraphNode(key) {
  const canvas = graphCanvas(); if (!canvas) return; const scene = canvas.querySelector('[data-graph-scene]'); if (!scene) return;
  scene.classList.toggle('has-highlight', Boolean(key));
  for (const node of scene.querySelectorAll('[data-node-key]')) node.classList.toggle('is-highlighted', Boolean(key) && node.dataset.nodeKey === key);
  for (const edge of scene.querySelectorAll('[data-edge-source]')) edge.classList.toggle('is-highlighted', Boolean(key) && (edge.dataset.edgeSource === key || edge.dataset.edgeTarget === key));
}

function requestGraph(updates = {}) {
  const current = { view: state.graphView, node: '', query: '', relation: '', direction: 'both', depth: 1, maxNodes: 24, maxEdges: 48, ...(state.graphData || {}), ...updates };
  const requestId = `graph-${Date.now()}-${Math.random()}`; state.graphRequestId = requestId; state.graphRequest = current; state.graphPending = true;
  vscode.postMessage({ type: 'graphQuery', requestId, view: state.graphView, node: current.node || '', query: current.query || '', relation: current.relation || '', direction: current.direction || 'both', depth: 1, maxNodes: 24, maxEdges: 48 });
}

function skillsTools() {
  const kind = state.capabilityKind;
  const enterprise = kind === 'enterprise-skills';
  return `<div class="metric-grid compact">${card('CORE SKILLS', number(state.snapshot.counts.skills), 'Pacify-X skill packages')}${card('ENTERPRISE SKILLS', number(state.snapshot.counts.enterprise_skills), 'separate enterprise catalog')}${card('TOOLS', number(state.snapshot.counts.tools), 'effect-governed tools')}${card('BILLABLE SERVICES', 'Disabled', 'enterprise default')}</div><div class="catalog-tabs"><button data-action="capabilityTab" data-kind="skills" class="${kind === 'skills' ? 'active' : ''}">Core Skills</button><button data-action="capabilityTab" data-kind="tools" class="${kind === 'tools' ? 'active' : ''}">Core Tools</button><button data-action="capabilityTab" data-kind="enterprise-skills" class="${enterprise ? 'active' : ''}">MS+Enterprise</button></div>
  ${section('Parallel planning coordination', 'EXTENSION-OWNED SKILL', `<div class="skill-feature"><div><strong>parallel-planning-coordination</strong><p>Task DAG → assignment → dependency readiness → file/area claims → IDE dispatch → progress receipts → conflict gate → reconciliation → layered memory.</p></div>${badge('ACTIVE LOCAL', 'success')}</div><div class="gate-stack"><span>Task graph</span><i>→</i><span>Claims</span><i>→</i><span>Dispatch</span><i>→</i><span>Receipts</span><i>→</i><span>Memory</span></div>`, '<button data-surface="workflows" class="secondary small">Open coordination</button>')}
  ${enterprise ? enterprisePackPanel() : ''}${catalogPanel(kind, enterprise ? 'MS+Enterprise skill catalog' : kind === 'skills' ? 'Skill catalog' : 'Tool catalog', enterprise ? 'SEPARATE ENTERPRISE NAMESPACE' : 'COMPLETE FIRST-CLASS SOURCE')}`;
}

function workflows() {
  const enterprise = state.workflowScope === 'enterprise'; const environment = state.workflowScope === 'environment';
  return `<div class="catalog-tabs"><button data-action="surfaceScope" data-target="workflows" data-scope="core" class="${!enterprise && !environment ? 'active' : ''}">Local + Team Fabric</button><button data-action="surfaceScope" data-target="workflows" data-scope="enterprise" class="${enterprise ? 'active' : ''}">MS+Enterprise</button><button data-action="surfaceScope" data-target="workflows" data-scope="environment" class="${environment ? 'active' : ''}">Environment Map</button></div>${environment ? environmentMap() : enterprise ? `${section('Enterprise workflow boundary', 'DETERMINISTIC · DISABLED CONNECTORS', `<div class="gate-stack"><span>Target</span><i>→</i><span>Auth namespace</span><i>→</i><span>Cost / egress</span><i>→</i><span>Human gate</span><i>→</i><span>Receipt</span></div><button class="primary" data-action="enterpriseDoctor">Run readiness doctor</button>`)}${catalogPanel('enterprise-workflows', 'MS+Enterprise orchestrations', 'SEPARATE WORKFLOW CATALOG')}` : `${section('Parallel planning', 'CROSS-IDE COORDINATION PLANE', coordinationBoard(), '<button class="primary small" data-action="newParallelPlan">New plan</button><button class="secondary small" data-action="openCoordinationHandoff">Open handoff</button>')}${catalogPanel('workflows', 'Orchestrations and bindings', 'PROJECT + SKILL + EXECUTION CATALOG')}`}`;
}

function plugins() {
  const extensions = state.environmentData.extensions?.records || [];
  const connectors = state.snapshot.enterprise?.connectors || [];
  const rows = extensions.slice(0, 120).map(item => `<button class="plugin-row" data-action="environmentExtensionDetail" data-extension-id="${esc(item.id)}"><div><strong>${esc(item.name || item.id)}</strong><small>${esc(item.id)} · v${esc(item.version || 'unknown')} · ${esc(item.publisher || 'publisher unknown')}</small></div><span>${badge(item.active ? 'ACTIVE' : 'DETECTED', item.active ? 'success' : 'info')}</span><span>${number(item.capability_count)} capabilities · ${number(item.command_count)} commands</span><span>${number(item.conflict_count)} conflicts</span><b>INSPECT</b></button>`).join('');
  const connectorRows = connectors.map(item => `<article class="plugin-connector"><div><strong>${esc(item.name)}</strong><small>${esc(item.id)}</small></div>${badge(item.status || 'disabled', item.status === 'active' ? 'success' : 'neutral')}<span>${esc(item.requirements || item.description || 'Explicit adapter approval required')}</span></article>`).join('');
  return `<div class="metric-grid compact">${card('VS CODE EXTENSIONS', number(state.snapshot.environment?.summary?.extensions || extensions.length), 'detected; activation is not inferred')}${card('PX SKILL PACKS', number(state.snapshot.counts.skills), 'canonical admission registry')}${card('MCP SERVER', 'Active', 'structured tools + effect annotations')}${card('CONNECTORS', number(connectors.length), 'separate; disabled by default')}</div>
  ${section('Capability catalog contract', 'BOUNDED SEARCH · TYPED MANIFEST · ADMISSION BEFORE ACTIVATION', `<div class="catalog-admission-flow"><span>Discover</span><i>→</i><span>Schema + identity</span><i>→</i><span>License + provenance</span><i>→</i><span>Effects + compatibility</span><i>→</i><span>Quarantine / admit</span><i>→</i><span>Host activation</span></div><div class="catalog-contract-grid"><article><b>Human discovery</b><span>Searchable, paged catalogs with readable purpose, lifecycle, owner, risk, and fit.</span></article><article><b>AI discovery</b><span>Stable IDs, structured content, bounded top results, explicit schemas, and safe next calls.</span></article><article><b>Supply-chain fields</b><span>Version, license, source, digest, signature/SBOM hints, compatibility, effects, and rollback.</span></article><article><b>Authority boundary</b><span>Catalog presence never means installed, admitted, enabled, authenticated, or authorized.</span></article></div>`, '<button data-action="inspectMachineManifest">Inspect machine contract</button>')}
  ${section('Governed plugin manager', 'INVENTORY → PROVENANCE → EFFECTS → COMPATIBILITY → APPROVAL → RECEIPT', `<div class="plugin-boundary"><b>PX inspects before the host changes anything.</b><span>Discovery never grants authority. Install, enable, disable, update, uninstall, network, credentials, and billable effects remain separate approval-bound operations.</span></div><div class="plugin-actions"><button class="primary" data-action="refreshEnvironment">Refresh capability inventory</button><button data-action="openExtensionsView">Open host extension manager</button><button data-action="inspectMachineManifest">AI capability manifest</button></div><div class="plugin-list">${rows || empty('Extension inventory is loading.')}</div>`)}
  ${section('Connector and pack readiness', 'OFFLINE STATUS · NO IMPLICIT CONNECTION', `<div class="plugin-connectors">${connectorRows || unavailable('No connector metadata available.')}</div>`)}`;
}

function environmentMap() {
  const inventory = state.snapshot.environment;
  if (!inventory) return section('Environment capability map', 'DISCOVERY PENDING', empty('The bounded startup inventory is still running.'), '<button class="primary small" data-action="refreshEnvironment">Refresh now</button>');
  const summary = inventory.summary || {}; const dataset = state.environmentData[state.environmentScope];
  const scopes = [['graph', 'Semantic graph'], ['extensions', 'VS Code extensions'], ['tools', 'System tools'], ['python', 'Python packages'], ['npm', 'npm packages']];
  let content = '';
  if (!dataset) content = `<div class="catalog-loading"><span class="empty-ring"></span><p>Lazy-loading the selected hash-verified subject…</p></div>`;
  else if (state.environmentScope === 'extensions') content = (dataset.records || []).map(item => `<button class="environment-row" data-action="environmentExtensionDetail" data-extension-id="${esc(item.id)}"><div><strong>${esc(item.name)}</strong><small>${esc(item.id)} · ${esc(item.version || 'version unavailable')}</small></div>${badge(item.active ? 'ACTIVE' : 'DETECTED', item.active ? 'success' : 'info')}<span>${number(item.capability_count)} capabilities · ${number(item.command_count)} commands · ${number(item.conflict_count)} conflicts</span></button>`).join('');
  else if (state.environmentScope === 'tools') content = (dataset.records || []).map(item => `<article class="environment-row"><div><strong>${esc(item.id)}</strong><small class="mono">${esc(item.command)}</small></div>${badge(item.available ? 'AVAILABLE' : 'ABSENT', item.available ? 'success' : 'neutral')}<span>${esc(item.version || 'probe unavailable')}</span></article>`).join('');
  else if (state.environmentScope === 'python') content = (dataset.records || []).map(item => `<article class="environment-row"><div><strong>${esc(item.name)}</strong><small>Python · ${esc(item.scope)}</small></div>${badge(item.version || 'unknown', 'info')}<span>installed-by → python/pip · available-to → Pacify-X</span></article>`).join('');
  else if (state.environmentScope === 'npm') content = (dataset.records || []).map(item => `<article class="environment-row"><div><strong>${esc(item.name)}</strong><small>npm · ${esc(item.scope)}</small></div>${badge(item.version || 'unknown', 'info')}<span>installed-by → npm · available-to → Pacify-X</span></article>`).join('');
  else content = `<div class="ontology-strip"><div><span>ONTOLOGY CHAIN</span><b>${number(inventory.ontology?.canonical_chain?.length)}</b><small>${esc((inventory.ontology?.canonical_chain || []).join(' → '))}</small></div><div><span>RELATIONS</span><b>${number(inventory.ontology?.predicates?.length)}</b><small>${esc((inventory.ontology?.predicates || []).join(' · '))}</small></div></div><div class="environment-graph">${(dataset?.edges || []).slice(0, 180).map(edge => `<div><span>${esc(edge.from)}</span><b>${esc(edge.predicate)}</b><span>${esc(edge.to)}</span></div>`).join('')}</div>`;
  return `<div class="metric-grid compact">${card('EXTENSIONS', number(summary.extensions), `${number(summary.active_extensions)} active`)}${card('TOOLS', number(summary.available_tools), `${number(summary.system_tools)} probed`)}${card('PACKAGES', number((summary.python_packages || 0) + (summary.npm_global_packages || 0) + (summary.npm_project_packages || 0)), 'Python + npm')}${card('SEMANTIC EDGES', number(summary.graph_edges), `${number(summary.graph_nodes)} typed nodes`)}</div><div class="catalog-tabs environment-tabs">${scopes.map(([id, label]) => `<button data-action="environmentScope" data-scope="${id}" class="${state.environmentScope === id ? 'active' : ''}">${label}</button>`).join('')}</div>${section('Environment capability map', 'HASHED · PROJECT-OWNED · READ-ONLY', `<div class="environment-boundary"><b>${esc(inventory.snapshot_hash)}</b><span>No arbitrary extension activation · no installs · no credentials · no billable calls</span></div><div class="environment-list">${content || unavailable('No records were discovered for this subject.')}</div>`, '<button class="primary small" data-action="refreshEnvironment">Refresh map + graph</button>')}`;
}

function coordinationSummary() {
  const c = state.coordination?.state;
  if (!c) return empty('Coordination is not initialized.');
  const active = c.plans?.find(plan => plan.id === c.active_plan);
  return `<div class="coord-summary"><div><span>ACTIVE PLAN</span><strong>${esc(active?.objective || 'No active plan')}</strong></div><div><span>TASKS</span><strong>${number(active?.task_ids?.length || 0)}</strong></div><div><span>ACTIVE CLAIMS</span><strong>${number(c.claims?.length || 0)}</strong></div><div><span>STATE REVISION</span><strong>${number(c.revision)}</strong></div></div><button class="secondary" data-surface="workflows">Open parallel planning</button>`;
}

function coordinationBoard() {
  const c = state.coordination?.state;
  if (!c) return empty('Initializing the project-owned coordination ledger.');
  const active = c.plans?.find(plan => plan.id === c.active_plan);
  const tasks = active ? c.tasks.filter(task => active.task_ids.includes(task.id)) : [];
  const taskRows = tasks.map(task => {
    const claim = c.claims.find(item => item.task_id === task.id);
    const depsReady = task.depends_on.every(dep => ['completed', 'reconciled'].includes(c.tasks.find(item => item.id === dep)?.status));
    let actions = `<button data-action="copyTaskHandoff" data-task-id="${esc(task.id)}">Dispatch</button>`;
    if (!task.owner && depsReady) actions += `<button class="primary" data-action="claimTask" data-task-id="${esc(task.id)}">Claim here</button>`;
    const ownedHere = task.owner?.actor_id === state.clientActor?.actorId;
    if (ownedHere && ['claimed', 'in_progress', 'waiting', 'blocked'].includes(task.status)) actions += `<button data-action="renewClaim" data-task-id="${esc(task.id)}" data-claim-id="${esc(claim?.id || '')}">Renew</button><button data-action="taskProgress" data-task-id="${esc(task.id)}">Progress</button><button data-action="completeTask" data-task-id="${esc(task.id)}">Complete</button><button data-action="releaseTask" data-task-id="${esc(task.id)}">Release</button>`;
    if (ownedHere && task.status === 'completed') actions += `<button class="primary" data-action="reconcileTask" data-task-id="${esc(task.id)}">Reconcile</button>`;
    return `<article class="task-card"><div class="task-state"><span>${esc(task.id)}</span>${badge(task.status, task.status === 'reconciled' ? 'success' : task.status === 'blocked' ? 'warning' : 'info')}</div><h3>${esc(task.title)}</h3><p>${esc(task.description || 'No description')}</p><div class="task-meta"><span>Depends: ${esc(task.depends_on.join(', ') || 'none')}</span><span>Claims: ${esc(task.claim_targets.join(', ') || 'none')}</span><span>Owner: ${esc(task.owner ? `${task.owner.actor_id} / ${task.owner.harness}` : 'unclaimed')}</span><span>Authority: ${esc(claim?.authority || task.authority_state || 'local')} · ${esc(claim?.mode || 'exclusive')}</span><span>Fence: ${esc(claim?.fencing_tokens ? Object.entries(claim.fencing_tokens).map(([target, token]) => `${target}#${token}`).join(', ') : 'none')}</span><span>Budget: ${esc(task.usage?.status || 'healthy')} · ${number(task.usage?.tokens || 0)} tokens · ${number(task.usage?.minutes || 0)} min</span><span>Lease: ${esc(claim?.expires_utc ? new Date(claim.expires_utc).toLocaleString() : 'none')}</span></div><div class="task-actions">${actions}</div></article>`;
  }).join('');
  return `<div class="plan-header"><div><span>OBJECTIVE</span><strong>${esc(active?.objective || 'No active parallel plan')}</strong></div><div><span>STATE HASH</span><code>${esc(c.state_hash?.slice(0, 20) || 'unavailable')}</code></div></div><div class="task-board">${taskRows || empty('Create a parallel plan to establish dependencies and non-overlapping work claims.')}</div>`;
}

function memory() {
  const canonical = state.snapshot.memory || {}; const portable = state.memoryData || state.coordination?.memory || {};
  const layers = portable.layer_counts || {}; const canonicalAttached = canonical.instrumented === true; const integrity = portable.integrity || {};
  const records = (portable.records || []).map(record => `<button class="memory-record" data-action="inspectMemoryRecord" data-memory-id="${esc(record.memory_id)}"><span><b>${esc(record.kind)}</b><small>${esc(record.layer)} · ${esc(record.lifecycle)} · ${esc(new Date(record.created_utc).toLocaleString())}</small></span><span>${badge(record.epistemic_status || 'unknown', 'info')}</span><code>${esc((record.record_sha256 || record.content_sha256 || '').slice(0, 12))}</code><strong>INSPECT</strong></button>`).join('');
  const canonicalErrors = [canonical.error, ...(canonical.memory_errors || []), ...(canonical.errors || [])].filter(Boolean).map(error => typeof error === 'string' ? error : error.error || error.code || JSON.stringify(error));
  const canonicalBody = `<div class="memory-authority ${canonicalAttached ? 'attached' : 'detached'}"><div><span>CANONICAL AUTHORITY</span><strong>${esc(canonical.authority || 'canonical workspace memory vault')}</strong><p>${canonicalAttached ? 'Lease-bound workspace memory is attached. Certified/trusted records may be retrievable under vault policy.' : 'Detached. Portable project records below are not substituted for canonical memory.'}</p></div>${badge(canonical.status || (canonicalAttached ? 'attached' : 'detached'), canonicalAttached ? 'success' : 'warning')}</div><dl class="detail-list"><div><dt>Workspace root</dt><dd class="mono">${esc(canonical.workspace_root || 'Configure pacifyX.workspaceRoot')}</dd></div><div><dt>Projects / records</dt><dd>${number(canonical.project_count)} / ${number(canonical.record_count)}</dd></div><div><dt>Eligible records</dt><dd>${number(canonical.eligible_record_count)}</dd></div><div><dt>Stored bytes</dt><dd>${canonical.bytes == null ? 'Unknown' : bytes(canonical.bytes)}</dd></div><div><dt>Lifecycle counts</dt><dd>${esc(readableValue(canonical.lifecycle_counts || {}))}</dd></div></dl>${canonicalErrors.length ? `<div class="memory-errors" role="status">${canonicalErrors.map(value => `<p>${esc(value)}</p>`).join('')}</div>` : ''}`;
  const portableBody = `<div class="memory-authority ${integrity.valid === false ? 'detached' : 'attached'}"><div><span>PORTABLE PROJECT AUTHORITY</span><strong>Coordination memory · non-canonical</strong><p>Project-scoped proposed/candidate records support continuity and AI inspection. They never override certified vault memory.</p></div>${badge(integrity.valid === false ? 'INTEGRITY GAP' : 'OBSERVED', integrity.valid === false ? 'warning' : 'info')}</div><div class="memory-integrity"><div><span>RECORDS</span><b>${number(portable.record_count || 0)}</b></div><div><span>SEALED</span><b>${number(integrity.sealed_records || 0)}</b></div><div><span>LEGACY UNSEALED</span><b>${number(integrity.legacy_unsealed_records || 0)}</b></div><div><span>INVALID / DRIFT</span><b>${number((integrity.invalid_records || 0) + (integrity.counter_drift?.length || 0))}</b></div></div><div class="memory-ladder"><div><b>Session</b><span>${number(layers.session || 0)} observations</span></div><i>→</i><div><b>Project</b><span>${number(layers.project || 0)} proposed</span></div><i>→</i><div><b>Resume state</b><span>${number(layers.state || 0)} proposed</span></div><i>→</i><div><b>System candidate</b><span>${number(layers.system_candidate || 0)} review required</span></div></div><div class="action-grid"><button class="primary" data-action="captureMemory">Capture proposed record</button><button data-action="openCoordinationHandoff">Open resume packet</button><button data-action="contextSnapshot">Portable context</button></div>`;
  const browser = `<div class="memory-toolbar"><label><span class="sr-only">Search portable memory</span><input data-memory-search value="${esc(state.memoryQuery)}" placeholder="Search records, kinds, sources…"></label><button data-action="memoryRefresh">Refresh</button><span>${state.memoryPending ? 'Reading…' : `${number(portable.matched_count || 0)} matched · ${bytes(portable.bytes || 0)}`}</span></div><div class="memory-records">${records || empty(state.memoryPending ? 'Reading bounded project records.' : 'No portable memory records match this search.')}</div>`;
  return `<div class="metric-grid compact">${card('CANONICAL VAULT', canonicalAttached ? number(canonical.record_count || 0) : 'Detached', canonicalAttached ? `${number(canonical.eligible_record_count || 0)} eligible` : 'workspace + lease required')}${card('PORTABLE RECORDS', number(portable.record_count || 0), 'project-owned; non-canonical')}${card('INTEGRITY', integrity.valid === false ? 'Review' : portable.instrumented ? 'Valid' : 'Unavailable', `${number(integrity.sealed_records || 0)} sealed`)}${card('SYSTEM CANDIDATES', number(layers.system_candidate || 0), 'never auto-canonical')}</div><div class="two-col">${section('Canonical memory vault', 'CERTIFIED RETRIEVAL AUTHORITY', canonicalBody)}${section('Portable coordination memory', 'CONTINUITY · PROPOSED / CANDIDATE ONLY', portableBody)}</div>${section('Portable record browser', 'BOUNDED SEARCH · HUMAN + JSON INSPECTION', browser)}`;
}

function activity() {
  const data = state.activityData || state.coordination?.activity || {};
  const policy = data.policy || {}; const agents = data.agents || []; const operations = data.active_operations || []; const events = data.events || [];
  const categories = [...new Set(events.map(event => event.category).filter(Boolean))].sort();
  const agentRows = agents.map(agent => `<article class="activity-agent"><span class="activity-presence ${esc(agent.status || 'idle')}"></span><div><strong>${esc(agent.actor_id || 'unknown actor')}</strong><small>${esc(agent.harness || 'unknown harness')} · ${esc(agent.session_id || 'unknown session')}</small></div>${badge((agent.status || 'observed').toUpperCase(), agent.status === 'working' ? 'success' : agent.status === 'attention' ? 'warning' : 'neutral')}<span>${esc(agent.current_operation || 'No active operation')}<small>${agent.last_seen_utc ? esc(new Date(agent.last_seen_utc).toLocaleString()) : 'not observed'}</small></span></article>`).join('');
  const operationRows = operations.map(item => `<button class="active-operation${item.stale ? ' stale' : ''}" data-action="filterActivityCorrelation" data-correlation-id="${esc(item.correlation_id)}"><span class="activity-pulse"></span><div><strong>${esc(item.operation)}</strong><small>${esc(item.actor?.actor_id || 'unknown')} · ${esc(item.category)} · ${esc(item.source)}</small></div><code>${esc(item.correlation_id)}</code>${item.stale ? badge('STALE', 'warning') : badge('RUNNING', 'success')}</button>`).join('');
  const eventRows = events.map(event => `<button class="activity-event" data-action="inspectActivityEvent" data-event-id="${esc(event.event_id)}"><span class="activity-event-state ${esc(event.status)}"></span><div class="activity-event-main"><strong>${esc(event.operation)}</strong><small>${esc(event.actor?.actor_id || 'unknown actor')} · ${esc(event.source)} · ${esc(new Date(event.timestamp).toLocaleString())}</small><span>${(event.scope_refs || []).slice(0, 3).map(scope => `<code>${esc(scope)}</code>`).join('') || '<em>No content or path payload captured</em>'}</span></div><div class="activity-event-meta">${badge(event.category, 'info')}${badge(event.status, ['failed', 'blocked'].includes(event.status) ? 'warning' : event.status === 'succeeded' ? 'success' : 'neutral')}<code>${esc(event.correlation_id)}</code>${event.duration_ms == null ? '' : `<small>${number(event.duration_ms)} ms</small>`}</div></button>`).join('');
  const privacy = `<div class="activity-privacy"><div><span>METADATA-ONLY OBSERVABILITY</span><strong>Actions are visible. Private reasoning and content are not.</strong><p>PX stores lifecycle metadata, relative scope references, correlations, and hashes. It does not retain prompts, file contents, terminal output, secrets, or chain-of-thought.</p></div>${badge(policy.paused ? 'CAPTURE PAUSED' : policy.enabled === false ? 'CAPTURE DISABLED' : 'CAPTURE ACTIVE', policy.paused || policy.enabled === false ? 'warning' : 'success')}<button data-action="activityPause" data-paused="${policy.paused ? 'false' : 'true'}">${policy.paused ? 'Resume capture' : 'Pause capture'}</button></div>`;
  const toolbar = `<div class="activity-toolbar"><label><span class="sr-only">Search activity</span><input data-activity-search value="${esc(state.activityQuery)}" placeholder="Find operation, actor, source, task, scope…"></label><label><span class="sr-only">Filter by category</span><select data-activity-category><option value="">All categories</option>${categories.map(value => `<option value="${esc(value)}" ${state.activityCategory === value ? 'selected' : ''}>${esc(value)}</option>`).join('')}</select></label><label><span class="sr-only">Filter by status</span><select data-activity-status><option value="">All statuses</option>${['started','running','observed','succeeded','failed','blocked','cancelled','idle'].map(value => `<option value="${value}" ${state.activityStatus === value ? 'selected' : ''}>${value}</option>`).join('')}</select></label><button data-action="activityRefresh">Refresh</button><span>${state.activityPending ? 'Reading…' : `${number(data.matched_count || 0)} shown`}</span></div>`;
  const limitations = (data.limitations || []).map(value => `<li>${esc(value)}</li>`).join('');
  return `${privacy}<div class="metric-grid compact">${card('EVENTS', number(data.event_count || 0), `revision ${number(data.revision || 0)}`)}${card('ACTIVE OPS', number(operations.length), 'correlated starts without terminal state')}${card('OBSERVED ACTORS', number(agents.length), 'known + explicitly unknown attribution')}${card('INTEGRITY', data.integrity?.valid === false ? 'Review' : data.integrity ? 'Valid' : 'Unavailable', `${number(data.integrity?.checked_events || 0)} seals checked`)}${card('RETENTION', `${number(policy.retention_days || 30)} days`, policy.automatic_purge ? 'automatic purge enabled' : 'declaration only; no automatic deletion')}</div><div class="two-col">${section('Agent presence', 'WHO IS OBSERVED', `<div class="activity-agent-list">${agentRows || empty('No actor has emitted a durable activity record yet.')}</div>`)}${section('Active operations', 'WHAT IS HAPPENING NOW', `<div class="active-operation-list">${operationRows || empty('No correlated operation is currently active.')}</div>`)}</div>${section('Trace explorer', 'ACTION · ACTOR · CORRELATION · EFFECT', `${toolbar}<div class="activity-events">${eventRows || empty(state.activityPending ? 'Reading the bounded activity ledger.' : 'No events match these filters.')}</div>`)}${section('Capture boundary', 'HONEST INTEGRATION LIMITS', `<ul class="activity-limitations">${limitations}</ul><dl class="detail-list"><div><dt>Authority</dt><dd>${esc(data.authority || 'project-owned observational trace; non-canonical and non-authorizing')}</dd></div><div><dt>Integrity</dt><dd>${esc(data.integrity ? `${data.integrity.valid ? 'valid' : 'review required'} · ${number(data.integrity.checked_events)} checked` : 'unavailable')}</dd></div><div><dt>Event seal</dt><dd class="mono">${esc(data.last_event_sha256 || 'No event seal')}</dd></div><div><dt>Storage</dt><dd class="mono">${esc(data.paths?.root || '.engineering-bootstrap/coordination/activity')}</dd></div></dl>`)}`;
}

function eventTimeline(limit) {
  const events = (state.coordination?.events || []).slice(-limit).reverse();
  return events.length ? `<div class="event-timeline">${events.map(event => `<article><i></i><div><strong>${esc(event.operation)}</strong><span>${esc(event.actor?.actor_id || 'system')} · ${esc(new Date(event.timestamp).toLocaleString())}</span><small>${esc(event.event_id)} · ${esc(event.after_hash?.slice(0, 12) || '')}</small></div></article>`).join('')}</div>` : empty('No rolling events have been recorded.');
}

function diagnostics() {
  const s = state.snapshot; const v = s.validation || { status: 'not-run', detail: 'Not run' };
  return `<div class="metric-grid compact">${card('EXTENSION', 'Operational', 'typed bridge host', 'green')}${card('PACIFY-X API', s.connected ? 'Connected' : 'Disconnected', s.catalogSource, s.connected ? 'green' : 'red')}${card('VALIDATION', v.status, v.detail, v.status === 'passed' ? 'green' : '')}${card('TURBOVEC', s.runtime?.turbovec?.status || 'Unavailable', s.runtime?.turbovec?.fallback || 'deterministic fallback')}</div>
  <div class="two-col wide-left">${section('Control-plane validation', 'PERSISTED BY ENGINE + COMMIT', `<div class="validation-box ${esc(v.status)}"><span class="validation-icon">${v.status === 'passed' ? '✓' : v.status === 'failed' ? '!' : '·'}</span><div><strong>${esc(v.status.toUpperCase())}</strong><p>${esc(v.detail)}</p></div></div><button class="primary" data-action="validate">Run validation</button><p class="fine-print">Runs <code>python -m runtime.cli validate</code> locally with billable provider environment keys stripped.</p>`)}${section('Integration probes', 'HONEST STATUS', serviceGrid())}</div>${catalogPanel('enterprise-integrations', 'MS+Enterprise connector readiness', 'SEPARATE DATA MODEL · NO CONNECTION ATTEMPT')}`;
}

function serviceGrid() {
  const s = state.snapshot; const rows = [
    ['Pacify-X dashboard API', s.connected ? 'Available' : 'Unavailable', s.connected ? 'success' : 'warning'],
    ['Project map', s.project?.map?.valid ? 'Available' : 'Unavailable', s.project?.map?.valid ? 'success' : 'warning'],
    ['Canonical memory vault', s.memory?.instrumented ? 'Attached' : 'Detached; configure workspace + lease', s.memory?.instrumented ? 'success' : 'neutral'],
    ['Portable memory', state.coordination?.memory?.instrumented ? `${number(state.coordination.memory.record_count)} records; non-canonical` : 'Unavailable', state.coordination?.memory?.integrity?.valid ? 'info' : 'warning'],
    ['Cross-IDE ledger', state.coordination ? 'Active' : 'Unavailable', state.coordination ? 'success' : 'warning'],
    ['Ollama', state.settings.ollamaEnabled ? 'Enabled; probe on model request' : 'Disabled', state.settings.ollamaEnabled ? 'info' : 'neutral'],
    ['TurboVec', s.runtime?.turbovec?.status || 'Unavailable', s.runtime?.turbovec?.active ? 'success' : 'neutral'],
    ['MS+Enterprise', s.enterprise?.catalog_id ? 'Offline boundary ready; connectors disabled' : 'Unavailable', s.enterprise?.catalog_id ? 'info' : 'neutral']
  ];
  return `<div class="service-grid">${rows.map(([label, value, tone]) => `<div><span>${esc(label)}</span>${badge(value, tone)}</div>`).join('')}</div>`;
}

function sensorValue(sensor) {
  if (!sensor?.available || !Number.isFinite(Number(sensor.value))) return 'Unavailable';
  const unit = sensor.unit === 'celsius' ? '°C' : sensor.unit === 'percent' ? '%' : sensor.unit === 'watts' ? 'W' : sensor.unit || '';
  return `${Number(sensor.value).toFixed(sensor.metric === 'temperature' ? 1 : 0)}${unit}`;
}
function thermalPanel() {
  const telemetry = state.snapshot.runtime?.hardware?.telemetry;
  if (!telemetry) return empty('Hardware telemetry is unavailable from this engine version.');
  const sensors = telemetry.sensors || [];
  const rows = sensors.map(sensor => `<button class="sensor-row" data-action="inspectSensor" data-sensor-id="${esc(sensor.id)}"><span class="sensor-kind">${esc(sensor.kind)}</span><div><strong>${esc(sensor.device)} · ${esc(sensor.label)}</strong><small>${esc(sensor.source)} · ${esc(sensor.sampled_at || telemetry.sampled_at)}</small></div><b class="${sensor.available ? '' : 'unavailable-value'}">${esc(sensorValue(sensor))}</b></button>`).join('');
  const providers = (telemetry.providers || []).map(provider => `<span class="sensor-provider ${provider.available ? 'available' : ''}">${esc(provider.id)}: ${provider.available ? 'available' : esc(provider.error || 'unavailable')}</span>`).join('');
  return `<div class="sensor-summary"><div><span>AVAILABLE</span><strong>${number(telemetry.available_count)}</strong></div><div><span>TEMPERATURES</span><strong>${number(telemetry.temperature_count)}</strong></div><div><span>SAMPLED</span><strong>${esc(telemetry.sampled_at ? new Date(telemetry.sampled_at).toLocaleTimeString() : 'unknown')}</strong></div></div><div class="sensor-list">${rows || empty('This operating system exposed no readable temperature sensors. Unknown is preserved; values are never estimated.')}</div><div class="sensor-providers">${providers}</div>`;
}

function readinessMatrix() {
  const readiness = state.snapshot.readiness || { dimensions: [], summary: {}, maturity: {} };
  const rows = (readiness.dimensions || []).map(item => `<button class="readiness-row" data-action="inspectReadiness" data-readiness-id="${esc(item.id)}"><span><b>${esc(item.id)}</b><strong>${esc(item.name)}</strong><small>${esc(item.question)}</small></span><span class="readiness-meter" aria-label="${esc(`${item.score} of ${item.maximum}`)}"><i style="--score:${Number(item.score || 0)}"></i></span><span>${badge(`${item.score}/${item.maximum}`, item.status === 'ready' ? 'success' : item.status === 'partial' ? 'warning' : 'neutral')}</span><span>${item.blocking ? badge('CEILING', 'info') : badge(item.status.toUpperCase(), item.status === 'ready' ? 'success' : 'neutral')}</span><b>EXPLAIN</b></button>`).join('');
  const gaps = (readiness.priority_gaps || []).map(value => `<li>${esc(value)}</li>`).join('');
  return `<div class="readiness-summary"><div><span>MATURITY</span><strong>Level ${number(readiness.maturity?.level)}</strong><small>${esc(readiness.maturity?.label || 'Unavailable')}</small></div><div><span>STRUCTURAL CEILING</span><strong>${number(readiness.maturity?.readiness_ceiling)}/5</strong><small>fresh E2E gate required for 5</small></div><div><span>READY DIMENSIONS</span><strong>${number(readiness.summary?.ready)}/9</strong><small>${number(readiness.summary?.partial)} partial</small></div><div><span>OPEN GAPS</span><strong>${number(readiness.summary?.gaps)}</strong><small>explicit, never inferred away</small></div></div><div class="readiness-note"><b>Advisory structural assessment</b><span>${esc(readiness.score_cap_reason || readiness.authority || 'Fresh certification remains separate.')}</span><button data-action="inspectReadinessReport">Human + JSON report</button></div><div class="readiness-table">${rows || empty('Readiness evidence is unavailable from this engine version.')}</div>${gaps ? `<div class="readiness-gaps"><strong>Priority gaps</strong><ol>${gaps}</ol></div>` : ''}`;
}

function agentModelHuman(item) {
  const model = item.agent_model || {};
  const capabilities = model.capabilities || item.tags || [];
  const handoffs = model.handoffs || [];
  const boundaries = model.boundaries || {};
  const stages = [
    ['Identify', model.identity?.role_mode || item.kind],
    ['Match', `${capabilities.length} capabilities`],
    ['Bound', boundaries.risk || item.risk || 'risk unknown'],
    ['Plan', model.lifecycle?.status || item.status],
    ['Handoff', `${handoffs.length} routes`],
    ['Verify', `${model.readiness?.passed || 0}/${model.readiness?.total || 0} fields`]
  ];
  const orbit = stages.map(([label, detail], index) => `<div class="agent-stage stage-${index + 1}"><i></i><b>${esc(label)}</b><span>${esc(detail)}</span></div>`).join('');
  return `<div class="agent-model-layout"><div class="agent-model" role="img" aria-label="Governed agent model showing identity, matching, boundaries, planning, handoffs, and verification"><div class="agent-orbit"></div><div class="agent-core"><span>PX AGENT</span><strong>${esc(model.identity?.name || item.label)}</strong><small>${esc(model.identity?.division || model.identity?.role_mode || 'governed specialist')}</small></div>${orbit}</div><aside class="agent-model-details"><section><span>Purpose</span><p>${esc(item.summary || 'No description declared.')}</p></section><section><span>Capabilities</span><div class="agent-chips">${capabilities.slice(0, 18).map(value => `<b>${esc(value)}</b>`).join('') || unavailable('None declared')}</div></section><section><span>Handoffs</span><p>${esc(handoffs.join(' → ') || 'No handoff routes declared.')}</p></section><section><span>Safety boundary</span><p>${esc((boundaries.avoid_when || []).join(' · ') || 'No explicit avoid-when rule declared.')}</p></section><section><span>Provenance</span><p class="mono">${esc(model.provenance?.manifest_path || model.provenance?.path || item.path || 'Not declared')}</p></section></aside></div>`;
}

function assurance() {
  const s = state.snapshot;
  return `<div class="metric-grid compact">${card('ASSURANCE RECORDS', number(s.counts.assurance), 'Pacify-X API')}${card('CONTRACTS', number(s.counts.contracts), 'JSON schemas')}${card('STATE RECEIPTS', number(state.coordination?.state?.revision || 0), 'hash-linked transitions')}${card('ROLLBACK', 'Documented', 'uninstall + project ledger retained')}</div>${section('Agent readiness matrix', 'NINE DIMENSIONS · EVIDENCE · EXPLICIT CEILING', readinessMatrix())}${section('Canonical ownership map', 'TRUST BOUNDARIES', `<div class="data-table ownership"><div class="table-head"><span>Capability</span><span>Canonical owner</span><span>Status</span><span>UI exposure</span></div>${s.authorities.map(item => `<div class="table-row"><strong>${esc(item.capability)}</strong><span>${esc(item.owner)}</span>${badge(item.status, item.status === 'implemented' ? 'success' : item.status.includes('not') ? 'neutral' : 'warning')}<span>${esc(item.exposure)}</span></div>`).join('')}</div>`)}${section('MS+Enterprise separation', 'DATA MODEL BOUNDARY', `<dl class="detail-list"><div><dt>Catalog</dt><dd>${esc(s.enterprise?.catalog_id || 'Unavailable')}</dd></div><div><dt>State schema</dt><dd>${esc(s.enterprise?.separation?.state_schema || 'Unavailable')}</dd></div><div><dt>Credential storage</dt><dd>${esc(s.enterprise?.separation?.credential_storage || 'Unavailable')}</dd></div><div><dt>Memory import</dt><dd>${esc(s.enterprise?.separation?.canonical_memory_import || 'Unavailable')}</dd></div><div><dt>Billable services</dt><dd>${badge(s.enterprise?.defaults?.billable_services || 'unknown', s.enterprise?.defaults?.billable_services === 'disabled' ? 'success' : 'warning')}</dd></div></dl><button class="primary" data-action="enterpriseDoctor">Certify boundary</button>`)}`;
}

function settings() {
  const s = state.snapshot; const p = state.settings.executionPolicy || {}; const enabled = p.master_enabled === true;
  return `<div class="two-col wide-left">${section('Normal configuration', 'USER SETTINGS', `<dl class="detail-list"><div><dt>Engine root</dt><dd class="mono">${esc(s.source.engineRoot || 'Auto-discovery did not resolve')}</dd></div><div><dt>Refresh interval</dt><dd>${number(state.settings.refreshIntervalSeconds)} seconds</dd></div><div><dt>Advanced surfaces</dt><dd>${state.settings.showAdvancedSurfaces ? 'Visible under collapsed Advanced section' : 'Hidden by default'}</dd></div><div><dt>Context injection cap</dt><dd>${number(state.settings.contextInjectionCapTokens)} tokens</dd></div><div><dt>Coordination root</dt><dd class="mono">${esc(state.coordination?.paths?.root || 'Initialize by opening a workspace')}</dd></div></dl><button class="primary" data-action="openSettings">Open VS Code settings</button>`)}${section('Connections', 'LOCAL-FIRST STATUS', `<div class="service-grid"><div><span>Pacify-X engine</span>${badge(s.connected ? 'Connected' : 'Disconnected', s.connected ? 'success' : 'warning')}</div><div><span>Ollama</span>${badge(state.settings.ollamaEnabled ? 'Local only' : 'Disabled', state.settings.ollamaEnabled ? 'info' : 'neutral')}</div><div><span>Environment graph</span>${badge(s.environment ? `${number(s.environment.summary.graph_nodes)} nodes` : 'Discovering', s.environment ? 'success' : 'info')}</div><div><span>MCP</span>${badge('Context + coordination + environment', 'success')}</div><div><span>Billable provider master</span>${badge(enabled ? 'Guarded opt-in' : 'Disabled', enabled ? 'warning' : 'success')}</div><div><span>Native session transfer</span>${badge('Unsupported; portable resume used', 'neutral')}</div></div>`)}</div>${section('Billable execution guardrails', enabled ? 'MASTER ON · EVERY GATE STILL APPLIES' : 'ZERO-COST DEFAULT · MASTER OFF', `<button class="policy-switch ${enabled ? 'on' : ''}" role="switch" aria-checked="${enabled}" data-action="toggleBillablePolicy" data-enabled="${enabled ? 'false' : 'true'}"><span><b>Cloud / billable provider policy</b><small>${enabled ? 'Permitted for evaluation only; no provider is connected.' : 'No billable provider execution can pass.'}</small></span><strong>${enabled ? 'ON' : 'OFF'}</strong></button><div class="guardrail-grid"><div><span>Cost / task</span><b>$${Number(p.max_cost_per_task_usd || 0).toFixed(2)}</b></div><div><span>Cost / session</span><b>$${Number(p.max_cost_per_session_usd || 0).toFixed(2)}</b></div><div><span>Cost / day</span><b>$${Number(p.max_cost_per_day_usd || 0).toFixed(2)}</b></div><div><span>Token budget</span><b>${number(p.token_budget)}</b></div><div><span>Local-first</span><b>${p.local_first ? 'Required' : 'Optional'}</b></div><div><span>Providers</span><b>${number((p.provider_allowlist || []).length)} allowlisted</b></div><div><span>GPU / CPU / RAM</span><b>${number(p.gpu_memory_ceiling_mb)} MiB · ${number(p.cpu_core_ceiling)} cores · ${number(p.ram_ceiling_mb)} MiB</b></div><div><span>Escalation confidence</span><b>${Number(p.escalation_confidence_threshold || 0).toFixed(2)}</b></div><div><span>Cache / reuse</span><b>${esc(p.cache_reuse_aggressiveness || 'balanced')}</b></div><div><span>Billable approval</span><b>${p.require_approval_before_billable_execution ? 'Always required' : 'Policy disabled'}</b></div></div><p class="fine-print">The master switch never stores credentials or makes a connection. A billable execution remains blocked unless every configured guardrail passes.</p>`, '<button data-action="openSettings">Edit guardrails</button>')}`;
}

function knowledgeCore() {
  const s = state.snapshot;
  return `<div class="advanced-banner"><span>HIDDEN ADVANCED SURFACE</span><strong>WHAT THE SYSTEM KNOWS</strong><p>Full graph/catalog inspection is live. Mutation remains with Pacify-X promotion and memory authorities.</p></div><div class="metric-grid compact">${card('SOURCES', number(s.counts.knowledgeSources), 'authoritative registry')}${card('GRAPH RECORDS', number(s.counts.graphRecords), 'full lazy index')}${card('GRAPH EDGES', number(s.counts.graphEdges), 'typed relationships')}${card('SYSTEM CANDIDATES', number(state.coordination?.state?.memory?.system_candidates || 0), 'not canonical')}</div><div class="two-col">${section('Knowledge lifecycle', 'PROMOTION BOUNDARY', `<div class="memory-ladder"><div><b>L0</b><span>Evidence</span></div><i>→</i><div><b>L1</b><span>Atomic candidate</span></div><i>→</i><div><b>L2</b><span>Index/scene</span></div><i>→</i><div><b>L3</b><span>Reviewed doctrine</span></div></div>`)}${section('Advanced maintenance', 'GOVERNED ACTIONS', `<div class="action-grid"><button data-action="preview" data-command="Validate knowledge">Preview validate</button><button data-action="explainGate">Rebuild index</button><button data-action="explainGate">Promote candidate</button></div><p class="fine-print">No generated knowledge is auto-promoted.</p>`)}</div>`;
}

function runtimeCore() {
  const s = state.snapshot; const p = s.provider || {}; const g = s.git || {}; const d = s.bridge?.decision || { allowed: false, reasons: ['status-unavailable'] };
  return `<div class="advanced-banner red"><span>HIDDEN ADVANCED SURFACE</span><strong>HOW THE SYSTEM ROUTES & EXECUTES</strong><p>Models propose; CPU-authoritative controllers dispose.</p></div><div class="metric-grid compact">${card('MODELS', number(s.counts.models), 'declared; availability preserved')}${card('CPU CORES', number(s.runtime?.hardware?.hardware?.cpu_logical_cores), 'live hardware report')}${card('SYSTEM RAM', bytes(s.runtime?.hardware?.hardware?.system_ram_bytes), 'live hardware report')}${card('VECTOR ROUTE', s.runtime?.turbovec?.status || 'Unavailable', s.runtime?.turbovec?.fallback || 'fallback')}</div>
  <div class="two-col">${section('Provider / context bridge', 'IDENTITY SEPARATION', `<dl class="detail-list provider"><div><dt>Context source</dt><dd>${esc(p.contextSource)}</dd></div><div><dt>Executor</dt><dd>${esc(p.executor)}</dd></div><div><dt>Authentication</dt><dd>${esc(p.authenticationIdentity)}</dd></div><div><dt>Billing / usage</dt><dd>${esc(p.billingIdentity)}</dd></div><div><dt>Handoff</dt><dd>Level 2 + project rolling resume</dd></div></dl><div class="action-grid"><button data-action="contextSnapshot">Open snapshot</button><button class="primary" data-action="continueCodex" ${d.allowed ? '' : 'disabled'}>Continue with Codex</button><button data-action="cancelCodex" ${s.bridge?.active ? '' : 'disabled'}>Cancel run</button></div>`)}${section('Git conflict boundary', 'GIT OWNS REPOSITORY STATE', `<dl class="detail-list"><div><dt>Repository</dt><dd class="mono">${esc(g.repositoryRoot || 'Unavailable')}</dd></div><div><dt>Operation</dt><dd>${esc(g.operation || 'unknown')}</dd></div><div><dt>Changes</dt><dd>${number(g.staged)} staged · ${number(g.unstaged)} unstaged · ${number(g.untracked)} untracked</dd></div><div><dt>Decision</dt><dd>${d.allowed ? badge('Ready', 'success') : badge(`Blocked: ${(d.reasons || []).join(', ')}`, 'warning')}</dd></div></dl>`)}</div>${section('Thermals & sensors', 'LIVE READ-ONLY TELEMETRY', thermalPanel())}${section('MS+Enterprise model providers', 'SEPARATE AUTH + BILLING IDENTITIES', `<div class="adapter-list">${(s.enterprise?.models || []).map(model => `<article class="adapter-row"><div><strong>${esc(model.name)}</strong><small>${esc(model.id)}</small></div>${badge(model.status, model.status === 'disabled' || model.status === 'not-installed' ? 'neutral' : 'warning')}<span>auth ${esc(model.auth_identity)} / billing ${esc(model.billing_identity)}</span></article>`).join('') || unavailable()}</div><button data-action="enterpriseDoctor">Run offline readiness</button>`)}</div><div class="three-col">${section('Coordination', 'TASK CLAIM GATE', coordinationSummary())}${section('Storage & cleanup', 'DISK AUDIT + SAFE CLEANUP', `<p>Generated caches are inventoried twice, hash-compared, selected individually or all-at-once, and receipted.</p><button class="primary" data-action="cleanupManager">Open cleanup manager</button>`)}${section('Recovery', 'FAIL CLOSED', `<button data-action="openCoordinationHandoff">Open resume handoff</button><button data-action="validate">Validate runtime</button>`)}</div>`;
}

function ensureSurfaceData() {
  if (!state.snapshot?.connected) return;
  const kinds = state.active === 'agents' ? [state.agentScope === 'enterprise' ? 'enterprise-agents' : 'agents'] : state.active === 'knowledgeGraph' || state.active === 'knowledgeCore' ? ['graph'] : state.active === 'skillsTools' ? [state.capabilityKind] : state.active === 'workflows' ? (state.workflowScope === 'environment' ? [] : [state.workflowScope === 'enterprise' ? 'enterprise-workflows' : 'workflows']) : state.active === 'diagnostics' ? ['enterprise-integrations'] : [];
  for (const kind of kinds) if (kind && !state.catalogs[kind]) requestCatalog(kind);
  if (state.active === 'workflows' && state.workflowScope === 'environment' && !state.environmentData[state.environmentScope] && !state.environmentPending[state.environmentScope]) {
    state.environmentPending[state.environmentScope] = true; vscode.postMessage({ type: 'environmentQuery', subject: state.environmentScope, offset: 0, limit: 500 });
  }
  if (state.active === 'knowledgeGraph' && !state.graphPending && state.graphData?.view !== state.graphView) requestGraph({ view: state.graphView, node: '', query: '' });
  if (state.active === 'plugins' && !state.environmentData.extensions && !state.environmentPending.extensions) {
    state.environmentPending.extensions = true; vscode.postMessage({ type: 'environmentQuery', subject: 'extensions', offset: 0, limit: 500 });
  }
  if (state.active === 'memory' && !state.memoryData && !state.memoryPending) requestMemory();
  if (state.active === 'activity' && !state.activityData && !state.activityPending) requestActivity();
}
function requestMemory(query = state.memoryQuery) {
  state.memoryQuery = String(query || '').slice(0, 500); state.memoryPending = true;
  const requestId = `memory-${Date.now()}-${Math.random()}`; state.memoryRequestId = requestId;
  vscode.postMessage({ type: 'memoryQuery', requestId, query: state.memoryQuery, limit: 60 });
}
function requestActivity(updates = {}) {
  if (Object.hasOwn(updates, 'query')) state.activityQuery = String(updates.query || '').slice(0, 300);
  if (Object.hasOwn(updates, 'category')) state.activityCategory = String(updates.category || '').slice(0, 120);
  if (Object.hasOwn(updates, 'status')) state.activityStatus = String(updates.status || '').slice(0, 40);
  state.activityPending = true; const requestId = `activity-${Date.now()}-${Math.random()}`; state.activityRequestId = requestId;
  vscode.postMessage({ type: 'activityQuery', requestId, query: state.activityQuery, category: state.activityCategory, status: state.activityStatus, limit: 200 });
}
function requestCatalog(kind, updates = {}) {
  const current = { query: '', status: '', offset: 0, limit: 50, sort: 'label', ...(state.catalogRequests[kind] || {}), ...updates };
  state.catalogRequests[kind] = current; const requestId = `${kind}-${Date.now()}-${Math.random()}`; current.requestId = requestId;
  vscode.postMessage({ type: 'catalogQuery', kind, requestId, ...current });
}

function commandCenter() {
  showModal('Control center', 'OPERABLE LOCAL ACTIONS', `<div class="control-grid"><button data-action="refresh"><b>Synchronize</b><span>Re-read Pacify-X, Git and coordination state.</span></button><button data-action="validate"><b>Validate</b><span>Run the canonical control-plane validator.</span></button><button data-action="newParallelPlan"><b>Parallel plan</b><span>Create a dependency and claim-safe task graph.</span></button><button data-action="openCoordinationHandoff"><b>Resume handoff</b><span>Open the cross-IDE rolling checkpoint.</span></button><button data-action="contextSnapshot"><b>Context snapshot</b><span>Open bounded provider-neutral context.</span></button><button data-action="teamPackPreview"><b>Team package</b><span>Dry-run, inspect collisions, and stage non-canonical candidates.</span></button><button data-action="enterpriseDoctor"><b>MS+Enterprise</b><span>Run the offline boundary and readiness doctor.</span></button><button data-action="cleanupManager"><b>Storage & cleanup</b><span>Audit, select, dispose and retain a receipt.</span></button><button data-action="openSettings"><b>Settings</b><span>Configure local behavior.</span></button></div>`);
}

function newParallelPlanModal() {
  showModal('New parallel plan', 'DEPENDENCY + CLAIM SAFE', `<label class="form-field"><span>Objective</span><textarea id="plan-objective" rows="3" placeholder="What should the coordinated fleet accomplish?"></textarea></label><label class="form-field"><span>Goal / why context</span><input id="plan-goal" placeholder="mission → objective → project"></label><label class="form-field"><span>Tasks — one per line</span><textarea id="plan-tasks" rows="9" placeholder="id | title | dependencies | claims | preferred IDE | preferred agent | max tokens | effect scopes\nui | Build UI |  | media/ | VS Code | frontend agent | 20000 | workspace-read,workspace-write\nruntime | Runtime adapter |  | runtime/ | Antigravity | backend agent | 30000 | workspace-read,process"></textarea></label><p class="modal-note">Overlapping parallel claims are rejected unless dependency-ordered. Declared budgets hard-stop by default.</p>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitParallelPlan">Create governed plan</button>');
}
function parsePlan() {
  const objective = document.getElementById('plan-objective')?.value.trim();
  const lines = document.getElementById('plan-tasks')?.value.split(/\r?\n/).map(line => line.trim()).filter(Boolean) || [];
  const tasks = lines.map((line, index) => {
    const [taskId, title, dependencies, claims, harness, agent, maxTokens, effects] = line.split('|').map(value => value.trim());
    return { id: taskId || `task-${index + 1}`, title: title || taskId, dependsOn: dependencies ? dependencies.split(',').map(value => value.trim()).filter(Boolean) : [], claims: claims ? claims.split(',').map(value => value.trim()).filter(Boolean) : [], harness, agent, goalContext: [document.getElementById('plan-goal')?.value.trim()].filter(Boolean), budget: maxTokens ? { maxTokens: Number(maxTokens), hardStop: true } : {}, effectScopes: effects ? effects.split(',').map(value => value.trim()).filter(Boolean) : ['workspace-read'] };
  });
  if (!objective || !tasks.length) throw new Error('Objective and at least one task are required.');
  return { objective, tasks };
}

function claimTaskModal(taskId) {
  showModal('Claim task', 'LEASE + AUTHORITY', `<input type="hidden" id="claim-task" value="${esc(taskId)}"><label class="form-field"><span>Claim mode</span><select id="claim-mode"><option value="exclusive">Exclusive write lane</option><option value="shared">Shared coordination scope</option><option value="informational">Informational only</option></select></label><label class="form-field"><span>Authority</span><select id="claim-authority"><option value="local">Local authoritative</option><option value="speculative">Offline speculative</option></select></label><label class="form-field"><span>Lease minutes</span><input id="claim-ttl" type="number" min="5" max="1440" value="120"></label><p class="modal-note">A monotonic fencing token is issued for each target. Team-authoritative leases require a separately configured hub and cannot be self-declared here.</p>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitClaimTask">Claim task</button>');
}

function progressModal(taskId, complete = false) {
  showModal(complete ? 'Complete task' : 'Record progress', 'DURABLE PROGRESS RECEIPT', `<input type="hidden" id="progress-task" value="${esc(taskId)}"><input type="hidden" id="progress-status" value="${complete ? 'completed' : 'in_progress'}"><label class="form-field"><span>Summary</span><textarea id="progress-summary" rows="5" placeholder="What changed, what was verified, and what remains?"></textarea></label><div class="two-col"><label class="form-field"><span>Tokens used</span><input id="progress-tokens" type="number" min="0" value="0"></label><label class="form-field"><span>Minutes used</span><input id="progress-minutes" type="number" min="0" value="0"></label></div><label class="form-field"><span>Next action</span><input id="progress-next" placeholder="Exact next safe action"></label>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitTaskProgress">Write receipt</button>');
}
function reconcileModal(taskId) {
  showModal('Reconcile task', 'MERGE / CONFLICT RECEIPT', `<input type="hidden" id="reconcile-task" value="${esc(taskId)}"><label class="form-field"><span>Reconciliation summary</span><textarea id="reconcile-summary" rows="5" placeholder="Acceptance evidence, merge result, conflicts and final state"></textarea></label><label class="checkbox-field"><input id="reconcile-conflicts" type="checkbox"><span>All detected conflicts are resolved</span></label>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitReconcile">Reconcile and release claim</button>');
}
function captureMemoryModal() {
  showModal('Capture portable memory', 'PROJECT-SCOPED · PROPOSED / CANDIDATE', `<label class="form-field"><span>Layer</span><select id="memory-layer"><option value="session">Session observation (proposed)</option><option value="project">Project record (proposed)</option><option value="state">Resume-state record (proposed)</option><option value="system_candidate">System-memory candidate (review required)</option></select></label><label class="form-field"><span>Kind</span><select id="memory-kind"><option>observation</option><option>decision</option><option>failure</option><option>constraint</option><option>next-action</option></select></label><label class="form-field"><span>Concise record</span><textarea id="memory-content" rows="6" required placeholder="Capture a fact, decision, failure, pattern or architecture—not a chat transcript."></textarea></label><p class="modal-note">This appends to project-owned coordination memory. It does not certify, promote, or mutate the canonical vault.</p>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitMemory">Append proposed record</button>');
}

function renderCleanupManager() {
  const inventory = cleanupState.inventory; const candidates = inventory?.candidates || []; const selectedCount = cleanupState.selected.size;
  const rows = candidates.length ? candidates.map(item => `<label class="cleanup-row"><input type="checkbox" data-cleanup-id="${esc(item.id)}" ${cleanupState.selected.has(item.id) ? 'checked' : ''}><span class="cleanup-check"></span><span class="cleanup-path"><strong>${esc(item.relativePath)}</strong><small>${esc(item.category)} · ${number(item.files)} files · ${bytes(item.bytes)} · ${esc(item.treeHash?.slice(0, 12) || '')}</small></span>${badge('HASHED SAFE CACHE', 'success')}</label>`).join('') : empty('No generated caches passed the classifier.');
  const receipt = cleanupState.lastResult?.receipt;
  showModal('Storage & cleanup', 'DISK AUDIT + CLEANUP ORCHESTRATION', `${receipt ? `<div class="cleanup-receipt"><b>Last receipt</b><span>${esc(receipt.cleanup_id)} · ${number(receipt.resources_reclaimed)} reclaimed · ${bytes(receipt.bytes_reclaimed)} · ${esc(receipt.state)}</span></div>` : ''}<div class="cleanup-summary"><div><span>CANDIDATES</span><strong>${number(inventory?.summary?.candidateCount || 0)}</strong></div><div><span>RECLAIMABLE</span><strong>${bytes(inventory?.summary?.bytes || 0)}</strong></div><div><span>SELECTED</span><strong>${number(selectedCount)}</strong></div></div><div class="cleanup-pipeline"><span>Classify</span><i>→</i><span>Select</span><i>→</i><span>Hash gate ×2</span><i>→</i><span>Dispose</span><i>→</i><span>Receipt</span></div><div class="cleanup-toolbar"><button data-action="cleanupSelectAll">${selectedCount === candidates.length && candidates.length ? 'Clear all' : 'Select all'}</button><span>${number(selectedCount)} of ${number(candidates.length)} selected</span></div><div class="cleanup-list">${rows}</div><p class="modal-note">Evidence, quarantine, links, unknown data and protected roots fail closed.</p>`, `<button data-action="refreshCleanup">Rescan</button><button data-action="cleanupRecycle" ${selectedCount ? '' : 'disabled'}>Recycle Bin</button><button class="danger-action" data-action="cleanupPermanent" ${selectedCount ? '' : 'disabled'}>Permanent Delete</button>`);
}

app.addEventListener('click', event => {
  if (event.target.classList.contains('modal-backdrop')) { closeModal(); return; }
  const surfaceButton = event.target.closest('[data-surface]');
  if (surfaceButton) {
    const requested = surfaceButton.dataset.surface;
    if (advancedSurfaces.some(([id]) => id === requested) && !state.settings.showAdvancedSurfaces) { vscode.postMessage({ type: 'openSettings' }); return; }
    state.active = requested; state.advancedOpen = false; render(); document.getElementById('main-content')?.focus(); return;
  }
  const control = event.target.closest('[data-action]'); const action = control?.dataset.action; if (!action) return;
  if (control.disabled) return;
  if (action === 'closeModal') { closeModal(); return; }
  if (action === 'commandCenter') { commandCenter(); return; }
  if (action === 'newParallelPlan') { newParallelPlanModal(); return; }
  if (action === 'submitParallelPlan') { try { vscode.postMessage({ type: 'createParallelPlan', plan: parsePlan() }); closeModal(); } catch (error) { showModal('Plan blocked', 'VALIDATION', `<p>${esc(error.message)}</p>`); } return; }
  if (action === 'capabilityTab') { state.capabilityKind = control.dataset.kind; render(); return; }
  if (action === 'surfaceScope') { if (control.dataset.target === 'agents') state.agentScope = control.dataset.scope; if (control.dataset.target === 'workflows') state.workflowScope = control.dataset.scope; vscode.setState({ active: state.active, advancedOpen: state.advancedOpen, capabilityKind: state.capabilityKind, agentScope: state.agentScope, workflowScope: state.workflowScope, environmentScope: state.environmentScope }); render(); return; }
  if (action === 'catalogPrevious' || action === 'catalogNext') {
    const kind = control.dataset.kind; const current = state.catalogRequests[kind] || { offset: 0, limit: 50 };
    requestCatalog(kind, { offset: Math.max(0, current.offset + (action === 'catalogNext' ? current.limit : -current.limit)) }); return;
  }
  if (action === 'inspectCatalogItem') {
    const kind = control.dataset.kind; const item = state.catalogs[kind]?.items.find(row => row.id === control.dataset.id); if (!item) return;
    const record = { ...item.details, identity: { id: item.id, kind: item.kind, status: item.status, owner: item.owner, path: item.path }, summary: item.summary, effects: item.effects, tags: item.tags, agent_model: item.agent_model || undefined };
    const human = item.agent_model ? agentModelHuman(item) : `<p>${esc(item.summary || 'No summary')}</p><dl class="modal-detail"><div><dt>ID</dt><dd class="mono">${esc(item.id)}</dd></div><div><dt>Owner</dt><dd>${esc(item.owner || 'Not declared')}</dd></div><div><dt>Path</dt><dd class="mono">${esc(item.path || 'Not declared')}</dd></div><div><dt>Effects</dt><dd>${esc(item.effects?.join(', ') || 'None declared')}</dd></div></dl>`;
    showInformationModal(item.label, `${item.kind.toUpperCase()} · ${item.status}`, record, human); return;
  }
  if (action === 'inspectReadiness') { const item = state.snapshot.readiness?.dimensions?.find(row => row.id === control.dataset.readinessId); if (item) showInformationModal(`${item.id} · ${item.name}`, item.blocking ? 'READINESS CEILING DIMENSION' : 'READINESS DIMENSION', item, `<p>${esc(item.question)}</p><div class="readiness-explain"><div><span>Structural score</span><strong>${number(item.score)}/${number(item.maximum)}</strong></div><section><b>Evidence</b><ul>${(item.evidence || []).map(value => `<li>${esc(value)}</li>`).join('') || '<li>No supporting evidence resolved.</li>'}</ul></section><section><b>Open gaps</b><ul>${(item.gaps || []).map(value => `<li>${esc(value)}</li>`).join('') || '<li>No structural gap detected; a fresh E2E certification is still separate.</li>'}</ul></section></div>`); return; }
  if (action === 'inspectReadinessReport') { const report = state.snapshot.readiness; if (report) showInformationModal('Agent readiness matrix', 'ADVISORY STRUCTURAL ASSESSMENT', report, `<p>${esc(report.authority)}</p><p>${esc(report.score_cap_reason)}</p><div class="readiness-lanes"><section><b>Safe now</b><ul>${(report.safe_now || []).map(value => `<li>${esc(value)}</li>`).join('')}</ul></section><section><b>Requires a fresh gate</b><ul>${(report.requires_fresh_gate || []).map(value => `<li>${esc(value)}</li>`).join('')}</ul></section></div>`); return; }
  if (action === 'informationTab') { switchInformationTab(control.dataset.tab); return; }
  if (action === 'exportRecordJson') { vscode.postMessage({ type: 'exportRecordJson', title: modalTitle || 'Pacify-X record', record: modalRecord }); return; }
  if (action === 'graphView') { state.graphView = control.dataset.view; state.graphData = null; requestGraph({ view: state.graphView, node: '', query: '', relation: '', direction: 'both' }); render(); return; }
  if (action === 'graphLayout') { state.graphLayout = control.dataset.layout === 'orbit' ? 'orbit' : 'flow'; graphInteraction.sceneKey = ''; graphInteraction.fitted = false; render(); return; }
  if (action === 'graphToggleInspector') { state.graphInspectorOpen = !state.graphInspectorOpen; graphInteraction.fitted = false; render(); return; }
  if (action === 'graphZoomIn') { zoomGraphTo(graphInteraction.scale * 1.2); return; }
  if (action === 'graphZoomOut') { zoomGraphTo(graphInteraction.scale / 1.2); return; }
  if (action === 'graphFit') { fitGraphViewport(); return; }
  if (action === 'graphReset') { resetGraphViewport(); return; }
  if (action === 'runGraphSearch') { const search = app.querySelector('[data-graph-search]'); const relation = app.querySelector('[data-graph-relation]'); const direction = app.querySelector('[data-graph-direction]'); requestGraph({ node: '', query: search?.value.trim() || '', relation: relation?.value || '', direction: direction?.value || 'both' }); render(); return; }
  if (action === 'focusGraphNode') { requestGraph({ node: control.dataset.nodeKey, query: '', relation: app.querySelector('[data-graph-relation]')?.value || '', direction: app.querySelector('[data-graph-direction]')?.value || 'both' }); render(); return; }
  if (action === 'inspectSensor') { const sensor = state.snapshot?.runtime?.hardware?.telemetry?.sensors?.find(item => item.id === control.dataset.sensorId); if (sensor) showInformationModal(sensor.label, 'LIVE READ-ONLY SENSOR', sensor, `<p>${esc(sensorValue(sensor))}</p><p>${esc(sensor.error || 'The provider returned a current observation.')}</p>`); return; }
  if (action === 'inspectMachineManifest') { showInformationModal('AI capability manifest', 'HUMAN + MACHINE CONTRACT', { schema_version: 'pacify-x.plugin-catalog.v1', counts: state.snapshot.counts, environment: state.snapshot.environment, extensions: state.environmentData.extensions?.records || [], connectors: state.snapshot.enterprise?.connectors || [], mcp: { transport: 'stdio', structured_content: true } }, '<p>The same governed capability inventory used by the UI is available to AI clients as structured JSON through the Pacify-X MCP server. Discovery never grants execution authority.</p>'); return; }
  if (action === 'openExtensionsView') { vscode.postMessage({ type: 'openExtensionsView' }); return; }
  if (action === 'claimTask') { claimTaskModal(control.dataset.taskId); return; }
  if (action === 'submitClaimTask') { vscode.postMessage({ type: 'claimCoordinationTask', taskId: document.getElementById('claim-task').value, mode: document.getElementById('claim-mode').value, authority: document.getElementById('claim-authority').value, ttlMinutes: Number(document.getElementById('claim-ttl').value) }); closeModal(); return; }
  if (action === 'renewClaim') { vscode.postMessage({ type: 'renewCoordinationClaim', taskId: control.dataset.taskId, claimId: control.dataset.claimId, ttlMinutes: 120 }); return; }
  if (action === 'taskProgress') { progressModal(control.dataset.taskId, false); return; }
  if (action === 'completeTask') { progressModal(control.dataset.taskId, true); return; }
  if (action === 'submitTaskProgress') { vscode.postMessage({ type: 'recordTaskProgress', taskId: document.getElementById('progress-task').value, status: document.getElementById('progress-status').value, summary: document.getElementById('progress-summary').value, usage: { tokens: Number(document.getElementById('progress-tokens').value), minutes: Number(document.getElementById('progress-minutes').value) }, nextAction: document.getElementById('progress-next').value }); closeModal(); return; }
  if (action === 'reconcileTask') { reconcileModal(control.dataset.taskId); return; }
  if (action === 'submitReconcile') { vscode.postMessage({ type: 'reconcileCoordinationTask', taskId: document.getElementById('reconcile-task').value, summary: document.getElementById('reconcile-summary').value, conflictsResolved: document.getElementById('reconcile-conflicts').checked }); closeModal(); return; }
  if (action === 'releaseTask') { vscode.postMessage({ type: 'releaseCoordinationTask', taskId: control.dataset.taskId, reason: 'Explicit UI release' }); return; }
  if (action === 'copyTaskHandoff') { vscode.postMessage({ type: 'copyTaskHandoff', taskId: control.dataset.taskId }); return; }
  if (action === 'captureMemory') { captureMemoryModal(); return; }
  if (action === 'submitMemory') { const content = document.getElementById('memory-content').value.trim(); if (!content) { document.getElementById('memory-content').focus(); return; } vscode.postMessage({ type: 'captureCoordinationMemory', layer: document.getElementById('memory-layer').value, kind: document.getElementById('memory-kind').value, content }); closeModal(); return; }
  if (action === 'memoryRefresh') { state.memoryData = null; requestMemory(); render(); return; }
  if (action === 'activityRefresh') { state.activityData = null; requestActivity(); render(); return; }
  if (action === 'activityPause') { vscode.postMessage({ type: 'setActivityPaused', paused: control.dataset.paused === 'true' }); return; }
  if (action === 'filterActivityCorrelation') { requestActivity({ query: control.dataset.correlationId }); render(); return; }
  if (action === 'inspectActivityEvent') {
    const eventRecord = state.activityData?.events?.find(item => item.event_id === control.dataset.eventId); if (!eventRecord) return;
    showInformationModal(eventRecord.operation, `${String(eventRecord.category).toUpperCase()} · ${String(eventRecord.status).toUpperCase()} · METADATA ONLY`, eventRecord, `<p>This record describes an observed action without storing prompts, file contents, terminal output, secrets, or private reasoning.</p><dl class="modal-detail"><div><dt>Actor</dt><dd>${esc(eventRecord.actor?.actor_id)} · ${esc(eventRecord.actor?.harness)}</dd></div><div><dt>Correlation</dt><dd class="mono">${esc(eventRecord.correlation_id)}</dd></div><div><dt>Effect</dt><dd>${esc(eventRecord.effect)}</dd></div><div><dt>Scope references</dt><dd>${esc((eventRecord.scope_refs || []).join(', ') || 'none')}</dd></div><div><dt>Integrity seal</dt><dd class="mono">${esc(eventRecord.event_sha256)}</dd></div></dl>`); return;
  }
  if (action === 'inspectMemoryRecord') { const record = state.memoryData?.records?.find(item => item.memory_id === control.dataset.memoryId); if (record) showInformationModal(record.kind, `${String(record.layer).toUpperCase()} · ${String(record.lifecycle).toUpperCase()} · NON-CANONICAL`, record, `<p>${esc(record.content || 'Content was not requested.')}</p><dl class="modal-detail"><div><dt>Authority</dt><dd>Portable project coordination memory; not canonical</dd></div><div><dt>Evidence</dt><dd class="mono">${esc(record.evidence_locator || record.source_artifact)}</dd></div><div><dt>Record seal</dt><dd class="mono">${esc(record.record_sha256 || 'Legacy unsealed record')}</dd></div><div><dt>Confidence</dt><dd>${esc(readableValue(record.confidence))} · ${esc(record.confidence_method || 'not declared')}</dd></div></dl>`); return; }
  if (action === 'cleanupManager' || action === 'refreshCleanup') { showModal('Storage & cleanup', 'CLASSIFYING CANDIDATES', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Scanning the admitted engine root. No files are changed.</p></div>'); vscode.postMessage({ type: 'scanCleanup' }); return; }
  if (action === 'teamPackPreview') { vscode.postMessage({ type: 'teamPackPreview' }); return; }
  if (action === 'enterprisePackToggle') { vscode.postMessage({ type: 'enterprisePackToggle', packId: control.dataset.packId, enabled: control.dataset.enabled === 'true' }); return; }
  if (action === 'enterpriseTargetConfigure') { vscode.postMessage({ type: 'enterpriseTargetConfigure', packId: control.dataset.packId }); return; }
  if (action === 'enterpriseDoctor') { vscode.postMessage({ type: 'enterpriseDoctor' }); return; }
  if (action === 'toggleBillablePolicy') { vscode.postMessage({ type: 'toggleBillablePolicy', enabled: control.dataset.enabled === 'true' }); return; }
  if (action === 'refreshEnvironment') { state.environmentData = {}; state.environmentPending = {}; vscode.postMessage({ type: 'refreshEnvironment' }); return; }
  if (action === 'environmentScope') { state.environmentScope = control.dataset.scope; vscode.setState({ active: state.active, advancedOpen: state.advancedOpen, capabilityKind: state.capabilityKind, agentScope: state.agentScope, workflowScope: state.workflowScope, environmentScope: state.environmentScope }); render(); return; }
  if (action === 'environmentExtensionDetail') { vscode.postMessage({ type: 'environmentExtensionDetail', extensionId: control.dataset.extensionId }); return; }
  if (action === 'cleanupSelectAll') { const candidates = cleanupState.inventory?.candidates || []; cleanupState.selected = cleanupState.selected.size === candidates.length ? new Set() : new Set(candidates.map(item => item.id)); renderCleanupManager(); return; }
  if (action === 'cleanupRecycle' || action === 'cleanupPermanent') { vscode.postMessage({ type: 'executeCleanup', ids: [...cleanupState.selected], disposition: action === 'cleanupPermanent' ? 'permanent' : 'recycle' }); return; }
  if (action === 'inspectMetric') { const metric = control; showInformationModal(metric.dataset.label, 'METRIC DETAIL', { label: metric.dataset.label, observed_value: metric.dataset.value, source_note: metric.dataset.detail, snapshot_at: state.snapshot?.generatedAt || null }, `<dl class="modal-detail"><div><dt>Observed value</dt><dd>${esc(metric.dataset.value)}</dd></div><div><dt>Source note</dt><dd>${esc(metric.dataset.detail)}</dd></div></dl>`); return; }
  if (action === 'inspectPanel') { const panel = control.closest('.panel'); const title = panel?.querySelector('h2')?.textContent || 'Panel'; const text = (panel?.innerText || '').replace(/\n{3,}/g, '\n\n').trim(); showInformationModal(title, 'PANEL INSPECTOR', { title, surface: state.active, text, snapshot_at: state.snapshot?.generatedAt || null }, `<pre class="modal-readout">${esc(text)}</pre>`); return; }
  if (action === 'copyModal') { vscode.postMessage({ type: 'copyText', text: modalCopyText }); return; }
  if (action === 'explainGate') { showModal('Control requires Pacify-X admission', 'CONTROL REQUIREMENTS', '<p>This mutation must be provided by its canonical Pacify-X controller with policy/admission, preview, execution receipt, resolved state and rollback.</p><div class="gate-stack"><span>Controller</span><i>→</i><span>Policy</span><i>→</i><span>Receipt</span><i>→</i><span>Rollback</span></div>'); return; }
  if (action === 'toggleAdvanced') { if (!state.settings.showAdvancedSurfaces) vscode.postMessage({ type: 'openSettings' }); else { state.advancedOpen = !state.advancedOpen; render(); } return; }
  const messages = { refresh: 'refresh', openSettings: 'openSettings', validate: 'validate', contextSnapshot: 'createContextSnapshot', continueCodex: 'continueCodex', cancelCodex: 'cancelCodex', exportSnapshot: 'exportSnapshot', openCoordinationHandoff: 'openCoordinationHandoff' };
  if (messages[action]) { vscode.postMessage({ type: messages[action] }); return; }
  if (action === 'preview') vscode.postMessage({ type: 'previewGovernedAction', action: control.dataset.command });
  if (action === 'openEngineRoot' && state.snapshot?.source?.engineRoot) vscode.postMessage({ type: 'openFile', path: `${state.snapshot.source.engineRoot}${state.snapshot.source.engineRoot.includes('\\') ? '\\' : '/'}README.md` });
});

app.addEventListener('wheel', event => {
  const canvas = event.target.closest('[data-graph-canvas]'); if (!canvas) return; event.preventDefault();
  if (event.ctrlKey || event.metaKey) { zoomGraphTo(graphInteraction.scale * Math.exp(-event.deltaY * 0.0025), event.clientX, event.clientY); return; }
  graphInteraction.x -= event.shiftKey && !event.deltaX ? event.deltaY : event.deltaX; graphInteraction.y -= event.shiftKey ? 0 : event.deltaY;
  applyGraphViewport('Map panned');
}, { passive: false });

app.addEventListener('dblclick', event => {
  const canvas = event.target.closest('[data-graph-canvas]'); if (!canvas || event.target.closest('.graph-node')) return;
  zoomGraphTo(graphInteraction.scale * 1.3, event.clientX, event.clientY); canvas.focus();
});

app.addEventListener('pointerdown', event => {
  const canvas = event.target.closest('[data-graph-canvas]'); if (!canvas || event.target.closest('.graph-node')) return;
  event.preventDefault(); canvas.focus(); try { canvas.setPointerCapture?.(event.pointerId); } catch {} graphInteraction.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  canvas.classList.add('is-panning');
  if (graphInteraction.pointers.size === 1) graphInteraction.dragOrigin = { clientX: event.clientX, clientY: event.clientY, x: graphInteraction.x, y: graphInteraction.y };
  if (graphInteraction.pointers.size === 2) {
    const [a, b] = [...graphInteraction.pointers.values()]; const rect = canvas.getBoundingClientRect(); const midX = (a.x + b.x) / 2 - rect.left; const midY = (a.y + b.y) / 2 - rect.top;
    graphInteraction.pinchOrigin = { distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)), scale: graphInteraction.scale, sceneX: (midX - graphInteraction.x) / graphInteraction.scale, sceneY: (midY - graphInteraction.y) / graphInteraction.scale };
  }
});

app.addEventListener('pointermove', event => {
  const canvas = graphCanvas(); if (!canvas || !graphInteraction.pointers.has(event.pointerId)) return;
  graphInteraction.pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (graphInteraction.pointers.size >= 2 && graphInteraction.pinchOrigin) {
    const [a, b] = [...graphInteraction.pointers.values()]; const rect = canvas.getBoundingClientRect(); const midX = (a.x + b.x) / 2 - rect.left; const midY = (a.y + b.y) / 2 - rect.top;
    const distance = Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)); const next = clampGraphScale(graphInteraction.pinchOrigin.scale * distance / graphInteraction.pinchOrigin.distance);
    graphInteraction.scale = next; graphInteraction.x = midX - graphInteraction.pinchOrigin.sceneX * next; graphInteraction.y = midY - graphInteraction.pinchOrigin.sceneY * next; applyGraphViewport(`Zoom ${Math.round(next * 100)}%`); return;
  }
  if (graphInteraction.dragOrigin) {
    graphInteraction.x = graphInteraction.dragOrigin.x + event.clientX - graphInteraction.dragOrigin.clientX; graphInteraction.y = graphInteraction.dragOrigin.y + event.clientY - graphInteraction.dragOrigin.clientY; applyGraphViewport('Map panned');
  }
});

function endGraphPointer(event) {
  if (!graphInteraction.pointers.has(event.pointerId)) return; graphInteraction.pointers.delete(event.pointerId);
  const canvas = graphCanvas();
  if (!graphInteraction.pointers.size) { graphInteraction.dragOrigin = null; graphInteraction.pinchOrigin = null; canvas?.classList.remove('is-panning'); return; }
  const remaining = [...graphInteraction.pointers.values()][0]; graphInteraction.pinchOrigin = null; graphInteraction.dragOrigin = { clientX: remaining.x, clientY: remaining.y, x: graphInteraction.x, y: graphInteraction.y };
}
app.addEventListener('pointerup', endGraphPointer); app.addEventListener('pointercancel', endGraphPointer);
app.addEventListener('pointerover', event => { const node = event.target.closest('.graph-node.actual'); if (node) highlightGraphNode(node.dataset.nodeKey); });
app.addEventListener('pointerout', event => { const node = event.target.closest('.graph-node.actual'); if (node && !node.contains(event.relatedTarget)) highlightGraphNode(''); });
app.addEventListener('focusin', event => { const node = event.target.closest('.graph-node.actual'); if (node) highlightGraphNode(node.dataset.nodeKey); });
app.addEventListener('focusout', event => { const node = event.target.closest('.graph-node.actual'); if (node && !node.contains(event.relatedTarget)) highlightGraphNode(''); });

app.addEventListener('input', event => {
  const activityInput = event.target.closest('[data-activity-search]');
  if (activityInput) { clearTimeout(searchTimer); state.activityQuery = activityInput.value; searchTimer = setTimeout(() => requestActivity({ query: activityInput.value }), 250); return; }
  const memoryInput = event.target.closest('[data-memory-search]');
  if (memoryInput) { clearTimeout(searchTimer); state.memoryQuery = memoryInput.value; searchTimer = setTimeout(() => requestMemory(memoryInput.value), 250); return; }
  const input = event.target.closest('[data-catalog-search]'); if (!input) return;
  clearTimeout(searchTimer); const kind = input.dataset.catalogSearch;
  searchTimer = setTimeout(() => requestCatalog(kind, { query: input.value, offset: 0 }), 250);
});
app.addEventListener('change', event => {
  const activityCategory = event.target.closest('[data-activity-category]'); if (activityCategory) { requestActivity({ category: activityCategory.value }); return; }
  const activityStatus = event.target.closest('[data-activity-status]'); if (activityStatus) { requestActivity({ status: activityStatus.value }); return; }
  const checkbox = event.target.closest('[data-cleanup-id]');
  if (checkbox) { if (checkbox.checked) cleanupState.selected.add(checkbox.dataset.cleanupId); else cleanupState.selected.delete(checkbox.dataset.cleanupId); renderCleanupManager(); return; }
  const sort = event.target.closest('[data-catalog-sort]'); if (sort) requestCatalog(sort.dataset.catalogSort, { sort: sort.value, offset: 0 });
});
app.addEventListener('keydown', event => {
  if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('.metric-card')) { event.preventDefault(); event.target.click(); }
  if (event.key === 'Enter' && event.target.matches('[data-graph-search]')) { event.preventDefault(); app.querySelector('[data-action="runGraphSearch"]')?.click(); }
  if (event.target.matches('.graph-node.actual') && ['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'].includes(event.key)) {
    event.preventDefault(); const nodes = [...app.querySelectorAll('.graph-node.actual')]; const index = nodes.indexOf(event.target); const delta = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1; nodes[(index + delta + nodes.length) % nodes.length]?.focus(); return;
  }
  const canvas = event.target.closest('[data-graph-canvas]');
  if (canvas && !event.target.matches('.graph-node.actual')) {
    const panKeys = { ArrowLeft: [64, 0], ArrowRight: [-64, 0], ArrowUp: [0, 64], ArrowDown: [0, -64] };
    if (panKeys[event.key]) { event.preventDefault(); graphInteraction.x += panKeys[event.key][0]; graphInteraction.y += panKeys[event.key][1]; applyGraphViewport('Map panned'); return; }
    if (event.key === '+' || event.key === '=') { event.preventDefault(); zoomGraphTo(graphInteraction.scale * 1.2); return; }
    if (event.key === '-' || event.key === '_') { event.preventDefault(); zoomGraphTo(graphInteraction.scale / 1.2); return; }
    if (event.key === '0' || event.key === 'Home') { event.preventDefault(); fitGraphViewport(); return; }
  }
  if ((event.key === 'ArrowLeft' || event.key === 'ArrowRight') && event.target.matches('[role="tab"][data-action="informationTab"]')) { event.preventDefault(); switchInformationTab(event.target.dataset.tab === 'human' ? 'machine' : 'human'); }
  if (event.key === 'Escape') closeModal();
  const modal = event.target.closest('.control-modal');
  if (modal && event.key === 'Tab') {
    const focusable = [...modal.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex="0"]')];
    if (!focusable.length) return;
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});

window.addEventListener('message', event => {
  const message = event.data;
  if (message.type === 'snapshot') { state.snapshot = message.snapshot; state.settings = message.settings || state.settings; state.coordination = message.coordination || state.coordination; state.activityData = message.coordination?.activity || state.activityData; state.clientActor = message.clientActor || state.clientActor; render(); }
  if (message.type === 'settings') { state.settings = message.settings || state.settings; render(); }
  if (message.type === 'validation' && state.snapshot) { state.snapshot.validation = message.result; render(); }
  if (message.type === 'catalogResult') {
    const kind = message.result.kind; const activeRequest = state.catalogRequests[kind];
    if (!activeRequest || activeRequest.requestId === message.requestId) { state.catalogs[kind] = message.result; render(); }
  }
  if (message.type === 'graphResult' && message.requestId === state.graphRequestId) { const requestedNode = state.graphRequest?.node; state.graphPending = false; state.graphData = message.result; render(); if (requestedNode) [...app.querySelectorAll('[data-node-key]')].find(item => item.dataset.nodeKey === message.result.selected)?.focus(); }
  if (message.type === 'coordination') { state.coordination = message.coordination; state.activityData = message.coordination?.activity || state.activityData; render(); }
  if (message.type === 'coordinationResult') { state.operation = { status: 'complete', result: message.result }; state.memoryData = null; state.activityData = null; if (state.active === 'memory') requestMemory(); if (state.active === 'activity') requestActivity(); }
  if (message.type === 'memoryResult' && message.requestId === state.memoryRequestId) { state.memoryPending = false; state.memoryData = message.result; render(); }
  if (message.type === 'activityResult' && (!message.requestId || message.requestId === state.activityRequestId)) { state.activityPending = false; state.activityData = message.result; render(); }
  if (message.type === 'cleanupCandidates') { cleanupState.inventory = message.inventory; cleanupState.selected = new Set([...cleanupState.selected].filter(id => message.inventory.candidates.some(item => item.id === id))); renderCleanupManager(); }
  if (message.type === 'cleanupResult') { cleanupState.lastResult = message.result; cleanupState.selected = new Set(); renderCleanupManager(); }
  if (message.type === 'teamPackResult') {
    const result = message.result; modalCopyText = JSON.stringify(result, null, 2);
    const summary = message.phase === 'preview' ? `${number(result.totals?.entities)} entities · ${number(result.totals?.collisions)} collisions · ${number(result.totals?.warnings)} warnings` : `${number(result.receipt?.staged_count)} non-canonical candidates staged`;
    showInformationModal(message.phase === 'preview' ? 'Team package dry run' : 'Team package staged', 'TEAM FABRIC ADMISSION', result, `<p>${esc(summary)}</p><p class="modal-note">Canonical registries are unchanged. Promotion still requires Pacify-X admission.</p>`);
  }
  if (message.type === 'enterpriseResult') {
    const doctor = message.operation === 'enterpriseDoctor';
    showInformationModal(doctor ? 'MS+Enterprise readiness' : 'MS+Enterprise state updated', 'SEPARATE OFFLINE CONTROL PLANE', message.result.report || message.result.event || message.result, `<p>${doctor ? 'Local enterprise governance is ready. Cloud connectors remain disabled and no connection was attempted.' : 'The separate enterprise project state was updated. Network, mutation, credential reads, and billable services remain denied.'}</p>`);
  }
  if (message.type === 'environmentInventory') {
    state.snapshot.environment = message.result.inventory; state.snapshot.environmentPaths = message.result.paths; state.environmentData = {}; state.environmentPending = {}; render(); return;
  }
  if (message.type === 'environmentResult') {
    state.environmentPending[message.subject] = false; state.environmentData[message.subject] = message.result; render(); return;
  }
  if (message.type === 'environmentExtensionDetail') {
    const item = message.result.extension; showInformationModal(item.name || item.id, 'RESOURCE → CAPABILITIES → INTERFACE → REQUIREMENTS → EFFECTS → CONFLICTS → POLICY → STATE', item, `<p>${esc(item.integration_status)}. Arbitrary activation was not attempted.</p>${humanRecord(item)}`); return;
  }
  if (message.type === 'cleanupError' || message.type === 'operationError') { state.graphPending = false; render(); showModal('Operation blocked', 'FAIL-CLOSED RESULT', `<p role="alert">${esc(message.error)}</p>`, '<button class="primary" data-action="closeModal">Close</button>'); }
});

window.addEventListener('resize', () => {
  clearTimeout(graphResizeTimer); graphResizeTimer = setTimeout(() => { if (graphCanvas()) fitGraphViewport('Map fitted after resize'); }, 120);
});

render();
vscode.postMessage({ type: 'ready' });
