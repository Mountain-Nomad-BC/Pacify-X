'use strict';

// Single browser controller: state composition, interaction dispatch, and host bridge ownership.

const vscode = acquireVsCodeApi();
const app = document.getElementById('app');
const shieldUri = app.dataset.shieldUri;
const brandUri = app.dataset.brandUri || shieldUri;
const components = globalThis.PXDashboard.require('components');
const coreSurfaces = globalThis.PXDashboard.require('coreSurfaces');
const catalogSurfaces = globalThis.PXDashboard.require('catalogSurfaces');
const operationalSurfaces = globalThis.PXDashboard.require('operationalSurfaces');
const systemSurfaces = globalThis.PXDashboard.require('systemSurfaces');
const observabilitySurfaces = globalThis.PXDashboard.require('observabilitySurfaces');
const advancedSurfaceRenderers = globalThis.PXDashboard.require('advancedSurfaces');
const graphSurface = globalThis.PXDashboard.require('graphSurface');
const studioEditors = globalThis.PXDashboard.require('studioEditors');
const agentStructuralChecks = studioEditors.agentStructuralChecks;
const healthState = globalThis.PXDashboard.require('healthState');
const dashboardState = globalThis.PXDashboard.require('state');
const { escapeHtml: esc, number, bytes, badge, unavailable, card, section, empty } = components;

const visibleSurfaces = [
  ['dashboard', 'Dashboard', 'pulse'], ['projects', 'Projects', 'folder'], ['agents', 'Agents', 'agents'],
  ['agent-studio', 'Agent Studio', 'agents'], ['workflow-studio', 'Workflow Studio', 'flow'], ['skill-studio', 'Skill Studio', 'tools'],
  ['knowledgeGraph', 'Knowledge Graph', 'graph'], ['skillsTools', 'Skills & Tools', 'tools'], ['workflows', 'Workflows', 'flow'],
  ['plugins', 'Plugin Manager', 'plugin'], ['memory', 'Memory', 'memory'], ['activity', 'Activity', 'activity'],
  ['diagnostics', 'Diagnostics', 'diagnostics'], ['assurance', 'Assurance', 'shield'], ['studio-lifecycle', 'Studio Lifecycle', 'settings'],
  ['settings', 'Settings', 'settings']
];
const advancedSurfaces = [['knowledgeCore', 'Knowledge Core', 'knowledge'], ['runtimeCore', 'Runtime Core', 'runtime']];

let state = dashboardState.createInitial(vscode.getState() || {}, Boolean(window.__PX_PREVIEW_ADVANCED__));
let modalCopyText = '';
let modalReturnFocus = null;
let modalTitle = '';
let modalRecord = null;
let modalHumanText = '';
let deferredRender = false;
let modalReturnSelector = null;
let cleanupState = { inventory: null, selected: new Set(), lastResult: null };
let studioSession = null;
let studioPendingRun = null;
let studioPendingWorkflowRun = null;
let pendingStudioPreview = null;
let pendingStudioRunQuery = null;
let pendingStudioSetup = null;
let workflowConnectionStart = null;
let workflowScale = 1;
let workflowRunTrace = {};
let workflowTraceIdentity = null;
let workflowTraceMetadata = {};
let studioModelCatalog = [];
let studioEditor = null;
let studioDraftDirty = false;
let studioSelectedNode = '';
let agentSelectedSection = 'identity';
let agentScale = 1;
let agentPersistedGraph = null;
let agentWorkingGraph = null;
let agentGraphDirty = false;
let agentConnectionStart = null;
let studioActiveFile = 'SKILL.md';
let studioSourceRecord = null;
let pendingSkillComparison = null;
let pendingSkillLifecycle = null;
let pendingExtensionLifecycle = null;
let studioVersionAllocation = null;
let studioWorkingSourceBinding = null;
let studioVersionAllocationProof = null;
let studioVersionProofRequestId = null;
let studioAllocationRequest = null;
let studioSaveRequest = null;
const detachedStudioSaveRequests = new Map();
const pendingHostActions = new Map();
let pendingTaskRelease = null;
let studioPackageRequest = null;
let studioPendingSkillPackage = null;
let studioSourceProofRequestId = null;
let searchTimer; let graphResizeTimer; let graphRequestTimer;

function readinessLiveBlockers(snapshot = {}) {
  const blockers = [];
  const state = snapshot || {};
  if (state.extensionIdentity?.matches !== true) {
    blockers.push('Host/source identity mismatch');
  }
  if (state.project?.map?.valid !== true) {
    blockers.push('Project map is unavailable or stale');
  }
  if (state.memory?.retrieval_ready !== true) {
    blockers.push('Canonical memory is not ready');
  }
  if (Number(state.runtime?.core?.counters?.failures || 0) > 0) {
    blockers.push(`${state.runtime.core.counters.failures} runtime failures are retained`);
  }
  if (String(state.environment?.freshness?.state || 'unavailable').toLowerCase() === 'stale') {
    blockers.push('Environment inventory is stale');
  }
  const mcp = state.observability?.mcp || {};
  if (mcp.runtime_verified !== true) {
    blockers.push('MCP runtime verification is not current');
  }
  return blockers;
}

function persistDashboardState() {
  vscode.setState(dashboardState.persistedView(state));
}

function workingStudioSourceBinding() {
  return studioWorkingSourceBinding ? structuredClone(studioWorkingSourceBinding) : null;
}
function persistWorkingStudioDraft() {
  if (!studioDraftDirty || !studioEditor || !['agent', 'workflow', 'skill'].includes(studioEditor.kind)) return;
  const selectedTab = document.querySelector('[data-action="studioEditorTab"][aria-selected="true"]')?.dataset.tab;
  const canonicalInput = selectedTab === 'json' ? document.getElementById('studio-draft-json') : null;
  const envelope = {
    schema_version: 'px.studio-working-draft/1.0',
    kind: studioEditor.kind,
    draft: structuredClone(studioEditor.draft),
    editor_buffer: canonicalInput ? { kind: 'canonical-json', value: canonicalInput.value.slice(0, 524288) } : null,
    source_binding: workingStudioSourceBinding(),
    updated_utc: new Date().toISOString()
  };
  state.workingStudioDrafts = dashboardState.workingStudioDrafts({ ...(state.workingStudioDrafts || {}), [studioEditor.kind]: envelope });
  persistDashboardState();
}
function clearWorkingStudioDraft(kind) {
  if (!state.workingStudioDrafts?.[kind]) return;
  const next = { ...state.workingStudioDrafts }; delete next[kind];
  state.workingStudioDrafts = next; persistDashboardState();
}
function offerWorkingStudioDraft(kind) {
  const envelope = state.workingStudioDrafts?.[kind]; if (!envelope) return false;
  const identity = envelope.draft?.[kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : 'skill_id'] || 'unsaved candidate';
  const sourceWarning = envelope.source_binding ? '<p>This draft was based on an authenticated immutable predecessor. Resume will re-read and authenticate that exact catalog revision before applying the retained overlay.</p>' : '<p>Resume restores only local unsaved editor state. It grants no authority and performs no save or runtime action.</p>';
  const resumeLabel = envelope.source_binding ? 'Reauthenticate and resume' : 'Resume draft';
  showModal('Recover unsaved Studio draft', `${kind.toUpperCase()} · LOCAL RECOVERY · NO AUTHORITY`, `<p><b>${esc(identity)}</b> was retained at ${esc(envelope.updated_utc || 'an unknown time')}.</p>${sourceWarning}`, `<button data-action="discardWorkingStudioDraft" data-kind="${esc(kind)}">Discard retained draft</button><button class="primary" data-action="resumeWorkingStudioDraft" data-kind="${esc(kind)}">${resumeLabel}</button>`);
  return true;
}
function exactWorkingStudioCatalogRecord(kind, binding) {
  if (!binding || !['agent', 'workflow', 'skill'].includes(kind)) return null;
  const catalogKind = kind === 'skill' ? 'skills' : `${kind}s`;
  const identityKey = kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : 'skill_id';
  const item = state.catalogs?.[catalogKind]?.items?.find(candidate => {
    const details = candidate?.details || {};
    return String(details[identityKey] || '').trim().toLowerCase() === binding.identity
      && String(details.version || '').trim().toLowerCase() === binding.source_version
      && studioRecordRevisionSha(candidate) === binding.source_revision_sha256
      && studioRecordContentSha(candidate) === binding.source_content_sha256;
  });
  if (!item) return null;
  const details = item.details || {};
  return {
    ...item,
    ...details,
    identity: { id: item.id, kind: item.kind, status: item.status, owner: item.owner, path: item.path },
    summary: item.summary,
    effects: item.effects,
    tags: item.tags,
    agent_model: item.agent_model || undefined,
    _catalogKind: catalogKind,
    _catalogRecordId: item.id
  };
}
function resumeWorkingStudioDraft(kind) {
  const envelope = state.workingStudioDrafts?.[kind];
  if (!envelope) return;
  if (envelope.source_binding) {
    const record = exactWorkingStudioCatalogRecord(kind, envelope.source_binding);
    if (!record) {
      showModal('Exact predecessor unavailable', 'REFRESH CATALOG · RETAINED DRAFT PRESERVED', '<p>The currently loaded catalog does not contain the exact identity, version, revision hash, and content hash bound to this draft. Refresh the catalog and try Resume again. The retained draft was not discarded or changed.</p>');
      return;
    }
    studioSourceRecord = record;
    studioVersionAllocation = null;
    studioWorkingSourceBinding = null;
    studioVersionAllocationProof = null;
    studioSaveRequest = null;
    studioPackageRequest = null;
    studioPendingSkillPackage = null;
    if (kind === 'skill') requestSkillPackageEditor(record);
    else requestStudioVersionAllocation(kind, record);
    return;
  }
  studioWorkingSourceBinding = null;
  closeModal(); openStudioDraftModal(kind, structuredClone(envelope.draft)); studioDraftDirty = true;
  if (envelope.editor_buffer?.kind === 'canonical-json') {
    const tab = document.querySelector('[data-action="studioEditorTab"][data-tab="json"]'); tab?.click();
    const input = document.getElementById('studio-draft-json'); if (input) input.value = envelope.editor_buffer.value;
  }
  persistWorkingStudioDraft();
}
function workingStudioOverlayDisposition(kind, allocation) {
  const envelope = state.workingStudioDrafts?.[kind];
  if (!envelope?.source_binding) return { status: 'none', envelope: null };
  const binding = envelope.source_binding;
  const identityKey = kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : 'skill_id';
  const exactBinding = allocation && [
    ['source_scope', allocation.source_scope],
    ['identity', allocation.identity],
    ['source_version', allocation.source_version],
    ['source_revision_sha256', allocation.source_revision_sha256],
    ['source_content_sha256', allocation.source_content_sha256]
  ].every(([key, expected]) => binding[key] === expected);
  const exactCandidate = envelope.kind === kind
    && envelope.draft?.[identityKey] === allocation?.identity
    && envelope.draft?.version === allocation?.candidate_version;
  return exactBinding && exactCandidate
    ? { status: 'matched', envelope }
    : { status: 'mismatch', envelope };
}
function openReauthenticatedStudioDraft(kind, seed, allocation) {
  const disposition = workingStudioOverlayDisposition(kind, allocation);
  const restored = disposition.status === 'matched';
  studioWorkingSourceBinding = {
    source_scope: allocation.source_scope,
    identity: allocation.identity,
    source_version: allocation.source_version,
    source_revision_sha256: allocation.source_revision_sha256,
    source_content_sha256: allocation.source_content_sha256
  };
  closeModal(true);
  openStudioDraftModal(kind, restored ? structuredClone(disposition.envelope.draft) : seed);
  const editorRoot = document.querySelector('.studio-editor-root');
  if (disposition.status === 'mismatch') {
    editorRoot?.insertAdjacentHTML('beforebegin', '<div class="identity-warning" role="alert"><div><span>RETAINED OVERLAY NOT APPLIED</span><strong>The reauthenticated predecessor does not exactly match the retained draft binding.</strong><p>The retained draft remains recoverable. Reopen its exact identity, version, revision hash, and content hash before applying it.</p></div></div>');
    return;
  }
  if (!restored) return;
  studioDraftDirty = true;
  editorRoot?.insertAdjacentHTML('beforebegin', '<div class="studio-revision-baseline" role="status"><b>RETAINED OVERLAY RESTORED</b><span>The host reauthenticated the exact immutable predecessor and Pacify-X reapplied only its matching local unsaved overlay. No save or execution occurred.</span></div>');
  const buffer = disposition.envelope.editor_buffer;
  if (buffer?.kind === 'canonical-json' && typeof buffer.value === 'string' && buffer.value.length <= 524288) {
    document.querySelector('[data-action="studioEditorTab"][data-tab="json"]')?.click();
    const input = document.getElementById('studio-draft-json');
    if (input) input.value = buffer.value;
  }
  persistWorkingStudioDraft();
}

const STUDIO_ALLOCATION_KEYS = Object.freeze([
  'schema_version', 'kind', 'identity', 'source_version', 'source_scope',
  'source_revision_sha256', 'source_content_sha256', 'candidate_version',
  'occupied_versions_sha256', 'observed_utc'
]);
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
function studioAllocationRequestId() {
  return globalThis.crypto?.randomUUID?.() || `studio-allocation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
function postHostAction(action, type, payload = {}) {
  const requestId = studioAllocationRequestId();
  pendingHostActions.set(requestId, { action, type, started_utc: new Date().toISOString() });
  while (pendingHostActions.size > 64) pendingHostActions.delete(pendingHostActions.keys().next().value);
  state.operation = { status: 'pending', action, requestId };
  vscode.postMessage({ type, requestId, ...payload });
  return requestId;
}
function rememberDetachedStudioSave(request) {
  if (!request?.requestId || !request?.kind) return;
  detachedStudioSaveRequests.set(request.requestId, request.kind);
  while (detachedStudioSaveRequests.size > 64) detachedStudioSaveRequests.delete(detachedStudioSaveRequests.keys().next().value);
}
function studioSaveResponseDisposition(message) {
  if (studioSaveRequest && message?.requestId === studioSaveRequest.requestId && message?.kind === studioSaveRequest.kind) { studioSaveRequest = null; return 'active'; }
  if (message?.requestId && detachedStudioSaveRequests.get(message.requestId) === message?.kind) { detachedStudioSaveRequests.delete(message.requestId); return 'detached'; }
  return 'unmatched';
}
function resetStudioDetachControls() {
  document.querySelectorAll('[data-action="closeModal"]').forEach(button => { button.textContent = button.closest('footer') ? 'Cancel' : '×'; button.removeAttribute('title'); if (button.classList.contains('modal-close')) button.setAttribute('aria-label', 'Close'); else button.removeAttribute('aria-label'); });
  document.querySelector('[data-studio-detach-notice]')?.remove();
}
function clearConsumedStudioSaveTrust() {
  studioVersionAllocation = null;
  studioVersionAllocationProof = null;
  studioVersionProofRequestId = null;
  studioPendingSkillPackage = null;
  studioSourceProofRequestId = null;
}
function studioRecordIdentity(record, kind) {
  const details = record?.details || record || {}; const identityKey = kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : 'skill_id';
  return String(details[identityKey] || record?.[identityKey] || details.id || (!String(record?.id || '').startsWith('studio:') ? record?.id : '') || '').trim().toLowerCase();
}
function studioRecordRevisionSha(record) {
  const details = record?.details || record || {};
  return String(details.revision_sha256 || details.definition_sha256 || details.manifest_sha256 || details.body_sha256 || details.sha256 || record?.revision_sha256 || record?.sha256 || record?.provenance?.manifest_sha256 || '').trim().toLowerCase();
}
function studioRecordContentSha(record) {
  const details = record?.details || record || {};
  return String(details.source_content_sha256 || details.content_sha256 || record?.source_content_sha256 || record?.content_sha256 || '').trim().toLowerCase();
}
function validStudioAllocation(value, expected = {}) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join('\0') !== [...STUDIO_ALLOCATION_KEYS].sort().join('\0')) return null;
  const normalized = {
    ...value,
    kind: String(value.kind || ''), identity: String(value.identity || '').trim().toLowerCase(),
    source_version: String(value.source_version || '').trim().toLowerCase(), candidate_version: String(value.candidate_version || '').trim().toLowerCase(),
    source_revision_sha256: String(value.source_revision_sha256 || '').trim().toLowerCase(), source_content_sha256: String(value.source_content_sha256 || '').trim().toLowerCase(),
    occupied_versions_sha256: String(value.occupied_versions_sha256 || '').trim().toLowerCase()
  };
  if (normalized.schema_version !== 'px.studio-version-allocation/1.0' || !['agent', 'workflow', 'skill'].includes(normalized.kind) || !['studio-physical', 'external-authenticated'].includes(normalized.source_scope)) return null;
  if (normalized.source_scope === 'external-authenticated' && normalized.kind !== 'skill') return null;
  for (const key of ['identity', 'source_version', 'candidate_version', 'source_revision_sha256', 'source_content_sha256', 'occupied_versions_sha256']) if (value[key] !== normalized[key]) return null;
  if (!studioEditors.validStudioVersion(normalized.source_version) || !studioEditors.validStudioVersion(normalized.candidate_version) || ![normalized.source_revision_sha256, normalized.source_content_sha256, normalized.occupied_versions_sha256].every(item => SHA256_PATTERN.test(item)) || !studioEditors.validCanonicalUtc(normalized.observed_utc)) return null;
  for (const key of ['kind', 'identity', 'source_version', 'source_scope', 'source_revision_sha256', 'source_content_sha256']) {
    if (!Object.hasOwn(expected, key) || typeof expected[key] !== 'string' || normalized[key] !== expected[key]) return null;
  }
  return normalized;
}
function requestStudioVersionAllocation(kind, record, packageResult = null) {
  const details = record?.details || record || {}; const identity = studioRecordIdentity(record, kind); const sourceVersion = String(details.version || record?.version || '').trim().toLowerCase();
  if (['agent', 'workflow'].includes(kind)) {
    const catalogKind = String(record?._catalogKind || ''); const recordId = String(record?._catalogRecordId || '');
    const sourceRevisionSha256 = studioRecordRevisionSha(record); const sourceContentSha256 = studioRecordContentSha(record);
    if (catalogKind !== `${kind}s` || !recordId || !identity || !studioEditors.validStudioVersion(sourceVersion) || !SHA256_PATTERN.test(sourceRevisionSha256) || !SHA256_PATTERN.test(sourceContentSha256)) { showModal('Cannot allocate revision', 'HOST CATALOG SELECTION REQUIRED', '<p>Refresh the catalog and select the exact authenticated Studio revision with its identity, version, revision hash, and content hash again.</p>'); return false; }
    const requestId = studioAllocationRequestId();
    studioAllocationRequest = { requestId, operation: 'loadStudioRevisionEditor', suboperation: null, kind, catalogKind, recordId, identity, source_version: sourceVersion, source_scope: 'studio-physical', source_revision_sha256: sourceRevisionSha256, source_content_sha256: sourceContentSha256 };
    showModal('Loading immutable predecessor', 'HOST-OWNED CATALOG SNAPSHOT · EXACT TREE BINDING', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Re-reading and authenticating the complete physical revision before opening its editor.</p></div>');
    vscode.postMessage({ type: 'loadStudioRevisionEditor', requestId, kind, catalogKind, recordId });
    return true;
  }
  const trustedSelection = kind === 'skill' ? packageResult?.selection : null;
  const sourceRevisionSha256 = kind === 'skill' ? String(trustedSelection?.source_revision_sha256 || '') : studioRecordRevisionSha(record);
  const sourceContentSha256 = kind === 'skill' ? String(trustedSelection?.source_content_sha256 || '') : '';
  const sourceScope = kind === 'skill' ? String(trustedSelection?.source_scope || '') : 'studio-physical';
  const selectionMatches = kind !== 'skill' || (typeof packageResult?.sourceSelectionId === 'string' && trustedSelection?.identity === identity && trustedSelection?.source_version === sourceVersion && ['studio-physical', 'external-authenticated'].includes(sourceScope) && SHA256_PATTERN.test(sourceRevisionSha256) && SHA256_PATTERN.test(sourceContentSha256));
  if (!identity || !studioEditors.validStudioVersion(sourceVersion) || (kind !== 'skill' && !SHA256_PATTERN.test(sourceRevisionSha256)) || !selectionMatches) {
    studioAllocationRequest = null; studioPendingSkillPackage = null;
    showModal('Cannot allocate revision', 'AUTHENTICATED PREDECESSOR REQUIRED', '<p>The selected record does not expose an exact identity, bounded version, revision hash, and content hash. Pacify-X will not claim that an unauthenticated predecessor is preserved.</p>');
    return false;
  }
  const requestId = studioAllocationRequestId();
  studioAllocationRequest = {
    requestId, operation: 'studioOperation', suboperation: 'next-version', kind, identity, source_version: sourceVersion, source_scope: sourceScope,
    source_revision_sha256: sourceRevisionSha256,
    source_content_sha256: sourceContentSha256,
    selected_revision_sha256: sourceRevisionSha256,
    selected_content_sha256: sourceContentSha256,
    source_selection_id: kind === 'skill' ? packageResult.sourceSelectionId : '',
    record: structuredClone(record)
  };
  showModal('Allocating immutable revision', 'BACKEND VERSION CHECK · NO WRITE', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Checking the exact physical revision set and authenticated predecessor before opening the editor.</p></div>');
  const payload = { identity, source_version: sourceVersion };
  if (kind === 'skill') payload.source_selection_id = packageResult.sourceSelectionId;
  vscode.postMessage({ type: 'studioOperation', requestId, kind, operation: 'next-version', payload });
  return true;
}
function requestSkillPackageEditor(record) {
  const catalogKind = String(record?._catalogKind || '');
  const recordId = String(record?._catalogRecordId || '');
  if (catalogKind !== 'skills' || !recordId) {
    showModal('Skill package unavailable', 'SEPARATE DOMAIN OR UNATTESTED SOURCE', '<p>Only a PX-standard package with an independent full-tree attestation can enter this editor. Preserved originals and Microsoft / Enterprise packages remain read-only here.</p>');
    return false;
  }
  const requestId = studioAllocationRequestId();
  studioPackageRequest = Object.freeze({ requestId, catalogKind, recordId, identity: studioRecordIdentity(record, 'skill'), revisionSha256: studioRecordRevisionSha(record), record: structuredClone(record) });
  studioPendingSkillPackage = null;
  studioAllocationRequest = null;
  studioVersionAllocation = null;
  studioVersionAllocationProof = null;
  studioVersionProofRequestId = null;
  studioSourceProofRequestId = null;
  showModal('Loading skill package', 'HOST-OWNED CATALOG READ · FULL-TREE ATTESTATION', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Resolving the exact catalog record, package tree, domain, and provenance in the extension host.</p></div>');
  vscode.postMessage({ type: 'loadSkillPackageEditor', requestId, catalogKind, recordId });
  return true;
}

const BOUNDED_LAYOUT_SELECTOR = '[data-glass-opacity],[data-workflow-scale],[data-workflow-x],[data-agent-scale],[data-agent-x],[data-agent-mini-x],[data-agent-scene-width],[data-graph-x],[data-graph-scene],[data-readiness-score]';
const BOUNDED_LAYOUT_LIMIT = 2048;
function finiteLayoutNumber(value, minimum, maximum, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.min(maximum, Math.max(minimum, numeric)) : fallback;
}
function finiteLayoutText(value, minimum, maximum, fallback) {
  return String(Number(finiteLayoutNumber(value, minimum, maximum, fallback).toFixed(4)));
}
const boundedLayout = (() => {
  let sheet = null; let sequence = 0;
  const records = new Map();
  function styleSheet() {
    if (sheet) return sheet;
    if (typeof CSSStyleSheet !== 'function' || !('adoptedStyleSheets' in document)) throw new Error('Bounded dashboard layout requires constructable CSSStyleSheet support.');
    sheet = new CSSStyleSheet();
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
    return sheet;
  }
  function declarations(element) {
    const values = [];
    if (element.hasAttribute('data-glass-opacity')) values.push(`--glass-opacity:${finiteLayoutText(element.dataset.glassOpacity, 0, 1, .66)}`);
    if (element.hasAttribute('data-workflow-scale')) values.push(`--workflow-scale:${finiteLayoutText(element.dataset.workflowScale, .45, 1.75, 1)}`);
    if (element.hasAttribute('data-workflow-x')) {
      values.push(`--wx:${finiteLayoutText(element.dataset.workflowX, -20000, 20000, 40)}px`);
      values.push(`--wy:${finiteLayoutText(element.dataset.workflowY, -20000, 20000, 40)}px`);
    }
    if (element.hasAttribute('data-agent-scale')) values.push(`--agent-scale:${finiteLayoutText(element.dataset.agentScale, .45, 1.75, 1)}`);
    if (element.hasAttribute('data-agent-x')) {
      values.push(`--ax:${finiteLayoutText(element.dataset.agentX, -100000, 100000, 40)}px`);
      values.push(`--ay:${finiteLayoutText(element.dataset.agentY, -100000, 100000, 40)}px`);
    }
    if (element.hasAttribute('data-agent-mini-x')) {
      values.push(`--amx:${finiteLayoutText(element.dataset.agentMiniX, 0, 140, 0)}px`);
      values.push(`--amy:${finiteLayoutText(element.dataset.agentMiniY, 0, 84, 0)}px`);
    }
    if (element.hasAttribute('data-agent-scene-width')) {
      values.push(`width:${finiteLayoutText(element.dataset.agentSceneWidth, 640, 20000, 920)}px`);
      values.push(`height:${finiteLayoutText(element.dataset.agentSceneHeight, 320, 20000, 470)}px`);
    }
    if (element.hasAttribute('data-graph-x')) {
      values.push(`--x:${finiteLayoutText(element.dataset.graphX, -20000, 20000, 0)}px`);
      values.push(`--y:${finiteLayoutText(element.dataset.graphY, -20000, 20000, 0)}px`);
    }
    if (element.hasAttribute('data-graph-scene')) {
      values.push(`width:${finiteLayoutText(element.dataset.sceneWidth, 320, 20000, 1280)}px`);
      values.push(`height:${finiteLayoutText(element.dataset.sceneHeight, 240, 20000, 780)}px`);
      const x = finiteLayoutText(element.dataset.graphTranslateX, -100000, 100000, 0);
      const y = finiteLayoutText(element.dataset.graphTranslateY, -100000, 100000, 0);
      const scale = finiteLayoutText(element.dataset.graphScale, .08, 2.8, 1);
      values.push(`transform:translate3d(${x}px,${y}px,0) scale(${scale})`);
    }
    if (element.hasAttribute('data-readiness-score')) values.push(`--score:${finiteLayoutText(element.dataset.readinessScore, 0, 5, 0)}`);
    return values.join(';');
  }
  function reset() {
    styleSheet().replaceSync(''); records.clear(); sequence = 0;
  }
  function removeDisconnected() {
    const activeSheet = styleSheet();
    const stale = [...records.entries()].filter(([, record]) => !record.element.isConnected).map(([token, record]) => ({ token, index: Array.prototype.indexOf.call(activeSheet.cssRules, record.rule) })).sort((left, right) => right.index - left.index);
    for (const item of stale) { if (item.index >= 0) activeSheet.deleteRule(item.index); records.delete(item.token); }
  }
  function apply(root = document) {
    if (root === document) reset(); else removeDisconnected();
    const candidates = [];
    if (root?.nodeType === 1 && root.matches?.(BOUNDED_LAYOUT_SELECTOR)) candidates.push(root);
    for (const element of root?.querySelectorAll?.(BOUNDED_LAYOUT_SELECTOR) || []) { if (candidates.length >= BOUNDED_LAYOUT_LIMIT) break; candidates.push(element); }
    const activeSheet = styleSheet(); let applied = 0;
    for (const element of candidates.slice(0, BOUNDED_LAYOUT_LIMIT)) {
      const cssText = declarations(element); if (!cssText) continue;
      let token = element.dataset.pxLayoutRule; let record = token ? records.get(token) : null;
      if (!record || record.element !== element) {
        token = `px-layout-${sequence++}`; element.dataset.pxLayoutRule = token;
        const index = activeSheet.insertRule(`[data-px-layout-rule="${token}"]{${cssText}}`, activeSheet.cssRules.length);
        record = { element, rule: activeSheet.cssRules[index] }; records.set(token, record);
      } else record.rule.style.cssText = cssText;
      applied += 1;
    }
    return Object.freeze({ applied, limit: BOUNDED_LAYOUT_LIMIT });
  }
  return { apply };
})();
globalThis.PXDashboard.define('boundedLayout', boundedLayout);

function workflowTraceText(value) { return value == null ? '' : String(value).trim(); }
function workflowTraceObject(value) { return value && typeof value === 'object' && !Array.isArray(value) ? value : null; }
function workflowTraceHash(value) { return ['revision_sha256', 'content_sha256', 'definition_sha256', 'sha256'].map(field => workflowTraceText(value?.[field])).find(Boolean) || ''; }
function workflowTraceIdentityOf(value, fallback = {}) {
  const row = workflowTraceObject(value) || {}; const prior = workflowTraceObject(fallback) || {};
  return {
    workflow_id: workflowTraceText(row.workflow_id || row.subject_id) || workflowTraceText(prior.workflow_id),
    version: workflowTraceText(row.version) || workflowTraceText(prior.version),
    revision_sha256: workflowTraceHash(row) || workflowTraceText(prior.revision_sha256),
    run_id: workflowTraceText(row.run_id) || workflowTraceText(prior.run_id)
  };
}
function completeWorkflowTraceIdentity(identity) { return Boolean(identity?.workflow_id && identity?.version && identity?.run_id); }
function workflowTraceIdentityConflict(left, right, includeRun = true) {
  if (!left || !right) return false;
  for (const field of ['workflow_id', 'version', 'revision_sha256']) if (left[field] && right[field] && left[field] !== right[field]) return true;
  return Boolean(includeRun && left.run_id && right.run_id && left.run_id !== right.run_id);
}
function sameWorkflowTraceIdentity(left, right) {
  return completeWorkflowTraceIdentity(left) && completeWorkflowTraceIdentity(right) && !workflowTraceIdentityConflict(left, right)
    && left.workflow_id === right.workflow_id && left.version === right.version && left.run_id === right.run_id;
}
function workflowReceiptFailure(receipt) {
  const attempts = Array.isArray(receipt?.attempts) ? receipt.attempts : [];
  const failed = /fail|error|cancel/i.test(workflowTraceText(receipt?.state));
  const source = workflowTraceObject(receipt?.failure) || (failed ? workflowTraceObject(attempts[attempts.length - 1]) : null) || receipt;
  const failure = {};
  for (const field of ['failure_type', 'failure_message', 'failure_correlation_id', 'correlation_id', 'code', 'message']) if (source?.[field] != null && workflowTraceText(source[field])) failure[field] = String(source[field]);
  return Object.keys(failure).length ? failure : null;
}
function projectWorkflowReceipt(receipt) {
  if (!workflowTraceObject(receipt) || !workflowTraceText(receipt.node_id)) return null;
  const row = { node_id: workflowTraceText(receipt.node_id) };
  for (const field of ['state', 'kind', 'skip_reason']) if (workflowTraceText(receipt[field])) row[field] = workflowTraceText(receipt[field]);
  if (Array.isArray(receipt.attempts)) row.attempt_count = receipt.attempts.length;
  else if (Number.isInteger(receipt.attempt_count) && receipt.attempt_count >= 0) row.attempt_count = receipt.attempt_count;
  if (typeof receipt.duration_ms === 'number' && Number.isFinite(receipt.duration_ms) && receipt.duration_ms >= 0) row.duration_ms = receipt.duration_ms;
  if (Array.isArray(receipt.disabled_required_ports)) row.disabled_required_ports = receipt.disabled_required_ports.map(String);
  if (workflowTraceObject(receipt.approval_execution)) row.approval_execution = { ...receipt.approval_execution };
  if (workflowTraceObject(receipt.recovery)) row.recovery = { ...receipt.recovery };
  else if (typeof receipt.recovery === 'string' && receipt.recovery.trim()) row.recovery = receipt.recovery;
  const failure = workflowReceiptFailure(receipt); if (failure) row.failure = failure;
  return row;
}
function projectWorkflowTraceResult(result, { expectedIdentity = {}, currentIdentity = null, allowNewRun = false } = {}) {
  const envelope = workflowTraceObject(result) || {}; let value = workflowTraceObject(envelope.record) || envelope; let fromList = false;
  if (Array.isArray(value.runs)) {
    fromList = true;
    value = completeWorkflowTraceIdentity(currentIdentity) ? workflowTraceObject(value.runs.find(row => sameWorkflowTraceIdentity(workflowTraceIdentityOf(row), currentIdentity))) : null;
    if (!value) return { action: 'unchanged', reason: 'no-current-run-in-list' };
  }
  const expected = workflowTraceIdentityOf(expectedIdentity); const explicit = workflowTraceIdentityOf(value);
  if (workflowTraceIdentityConflict(explicit, expected, false)) return { action: 'clear', reason: 'editor-identity-mismatch' };
  const identity = workflowTraceIdentityOf(value, { ...expected, revision_sha256: expected.revision_sha256 || currentIdentity?.revision_sha256 || '' });
  if (!completeWorkflowTraceIdentity(identity)) return { action: 'clear', reason: 'trace-identity-incomplete' };
  if (completeWorkflowTraceIdentity(currentIdentity) && workflowTraceIdentityConflict(identity, currentIdentity) && (!allowNewRun || workflowTraceIdentityConflict(identity, expected, false))) return { action: 'clear', reason: 'current-run-identity-mismatch' };
  const receipts = Array.isArray(value.node_receipts) ? value.node_receipts : Array.isArray(value.checkpoint?.node_receipts) ? value.checkpoint.node_receipts : [];
  const nodes = {}; for (const receipt of receipts) { const projected = projectWorkflowReceipt(receipt); if (projected) nodes[projected.node_id] = projected; }
  const checkpoint = workflowTraceObject(value.checkpoint) || {}; const metadata = {};
  if (Array.isArray(checkpoint.ready_nodes)) metadata.ready_nodes = checkpoint.ready_nodes.map(String);
  if (Object.hasOwn(checkpoint, 'next_node')) metadata.next_node = checkpoint.next_node == null ? null : String(checkpoint.next_node);
  if (checkpoint.recovery != null) metadata.recovery = workflowTraceObject(checkpoint.recovery) ? { ...checkpoint.recovery } : String(checkpoint.recovery);
  if (workflowTraceObject(value.failure)) metadata.failure = { ...value.failure };
  if (workflowTraceText(value.state || value.run_state || value.status)) metadata.run_state = workflowTraceText(value.state || value.run_state || value.status);
  return { action: 'replace', reason: fromList ? 'current-run-refreshed-from-list' : 'trace-projected', identity, nodes, metadata };
}
function workflowTraceExpectedIdentity() {
  const session = studioSession?.kind === 'workflow' ? studioSession.payload : null;
  const draft = studioEditor?.kind === 'workflow' ? studioEditor.draft : null;
  return workflowTraceIdentityOf(session || draft || {});
}
function clearWorkflowTrace() { workflowTraceIdentity = null; workflowRunTrace = {}; workflowTraceMetadata = {}; }
function applyWorkflowTraceResult(result, operation) {
  const projection = projectWorkflowTraceResult(result, { expectedIdentity: workflowTraceExpectedIdentity(), currentIdentity: workflowTraceIdentity, allowNewRun: ['start', 'run'].includes(operation) });
  if (projection.action === 'clear') clearWorkflowTrace();
  else if (projection.action === 'replace') { workflowTraceIdentity = projection.identity; workflowRunTrace = projection.nodes; workflowTraceMetadata = projection.metadata; }
  return projection;
}
function reconcileWorkflowTraceEditor(draft) {
  if (!workflowTraceIdentity) return;
  if (workflowTraceIdentityConflict(workflowTraceIdentity, workflowTraceIdentityOf(draft), false)) clearWorkflowTrace();
}
const graphInteraction = {
  x: 0, y: 0, scale: 1, minScale: 0.08, maxScale: 2.8, sceneKey: '', fitted: false,
  pointers: new Map(), dragOrigin: null, pinchOrigin: null, viewportFrame: 0, visibilityGeneration: 0
};

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

function showModal(title, kicker, body, actions = '', modalClass = '') {
  modalReturnFocus = document.activeElement;
  modalReturnSelector = modalReturnFocus?.dataset?.action ? `[data-action="${CSS.escape(modalReturnFocus.dataset.action)}"]`
    : modalReturnFocus?.dataset?.surface ? `[data-surface="${CSS.escape(modalReturnFocus.dataset.surface)}"]`
      : modalReturnFocus?.id ? `#${CSS.escape(modalReturnFocus.id)}` : null;
  const root = document.getElementById('modal-root'); if (!root) return;
  root.innerHTML = `<div class="modal-backdrop"><section class="control-modal ${esc(modalClass)}" role="dialog" aria-modal="true" aria-label="${esc(title)}" tabindex="-1"><header><div><span class="eyebrow">${esc(kicker)}</span><h2>${esc(title)}</h2></div><button class="modal-close" data-action="closeModal" aria-label="Close">×</button></header><div class="modal-body">${body}</div><footer>${actions || '<button class="primary" data-action="closeModal">Done</button>'}</footer></section></div>`;
  const lifecycleTarget = root.querySelector('#environment-lifecycle-target');
  if (lifecycleTarget) {
    const exactTarget = lifecycleTarget.value;
    lifecycleTarget.dataset.exactTarget = exactTarget;
    lifecycleTarget.value = '';
    lifecycleTarget.placeholder = exactTarget;
    lifecycleTarget.spellcheck = false;
    if (lifecycleTarget.parentElement?.firstChild) lifecycleTarget.parentElement.firstChild.textContent = 'Type the exact target to authorize this move';
    const execute = root.querySelector('[data-action="executeEnvironmentLifecycle"]');
    if (execute) execute.disabled = true;
  }
  root.querySelector('.control-modal')?.focus();
}
function readableValue(value) {
  if (value === null || value === undefined || value === '') return 'Not declared';
  if (Array.isArray(value)) return value.length ? value.map(item => typeof item === 'object' ? JSON.stringify(item) : String(item)).join(', ') : 'None';
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}

function turbovecDisplay(snapshot) {
  const accelerator = snapshot?.runtime?.turbovec || {};
  if (accelerator.active === true) return { label: 'TURBOVEC ACTIVE', detail: 'Active admitted accelerator', tone: 'success' };
  if (accelerator.available === true) return { label: 'CPU FALLBACK ACTIVE · TURBOVEC UNADMITTED', detail: 'CPU fallback active; TurboVec is installed but not admitted', tone: 'info' };
  return { label: 'CPU FALLBACK ACTIVE · TURBOVEC NOT INSTALLED', detail: 'CPU fallback active; optional TurboVec accelerator is not installed', tone: 'neutral' };
}

function gitDisplay(snapshot) {
  const git = snapshot?.git || {};
  const changeCount = Number(git.staged || 0) + Number(git.unstaged || 0) + Number(git.untracked || 0);
  if (git.operation && git.operation !== 'none') return { label: `GIT ${String(git.operation).toUpperCase()}`, tone: 'warning' };
  if (changeCount > 0) return { label: `GIT IDLE · ${number(changeCount)} CHANGES`, tone: 'info' };
  return { label: 'GIT IDLE · CLEAN', tone: 'success' };
}
function humanRecord(record) {
  const priority = ['summary', 'description', 'status', 'kind', 'owner', 'path', 'source', 'effects', 'inputs', 'outputs', 'dependencies', 'provenance', 'license', 'risk', 'sampled_at', 'available', 'error'];
  const keys = [...priority.filter(key => Object.hasOwn(record || {}, key)), ...Object.keys(record || {}).filter(key => !priority.includes(key) && !['details'].includes(key)).sort()];
  return `<dl class="modal-detail">${keys.map(key => `<div><dt>${esc(key.replaceAll('_', ' '))}</dt><dd class="${['path', 'source', 'id', 'key'].includes(key) ? 'mono' : ''}">${esc(readableValue(record[key]))}</dd></div>`).join('')}</dl>`;
}
function listHuman(title, values, render = value => esc(readableValue(value))) {
  const rows = Array.isArray(values) ? values : [];
  return `<section><b>${esc(title)}</b><ol>${rows.map(value => `<li>${render(value)}</li>`).join('') || '<li>None declared</li>'}</ol></section>`;
}
function workflowHuman(item) {
  const value = item.details || {}; const execution = value.execution_class || 'unclassified';
  const topology = Array.isArray(value.steps) ? value.steps : [];
  const steps = topology.length ? topology : (value.skills || []).map((skill, index) => ({ id: `step-${index + 1}`, skill, depends_on: index ? [`step-${index}`] : [] }));
  return `<p>${esc(item.summary || 'No workflow purpose declared.')}</p><dl class="modal-detail"><div><dt>Machine identity</dt><dd class="mono">${esc(item.id)}</dd></div><div><dt>Artifact class</dt><dd>${esc(item.kind)}</dd></div><div><dt>Execution class</dt><dd>${esc(execution)}</dd></div><div><dt>Executability</dt><dd>${esc(execution === 'bounded_runtime_handler' || execution === 'runtime_binding' ? 'A runtime owner/binding is declared; execution still requires its gates.' : execution === 'validator_only' ? 'Validates a definition; it is not the workflow executor.' : 'Definition only; no executor is claimed.')}</dd></div><div><dt>Runtime owner / entrypoint</dt><dd class="mono">${esc(value.runtime_owner || value.entrypoint || 'None bound')}</dd></div><div><dt>Failure policy</dt><dd>${esc(value.failure_policy || 'Fail-closed behavior not declared')}</dd></div><div><dt>Effects</dt><dd>${esc(item.effects?.join(', ') || 'None declared')}</dd></div></dl>${listHuman('Ordered steps and dependencies', steps, step => `<b>${esc(step.id || 'unnamed')}</b> → ${esc(step.skill || step.capability || 'unbound')} <small>depends on ${esc((step.depends_on || []).join(', ') || 'nothing')}</small>`)}${listHuman('Preflight gates', value.preflight)}${listHuman('Required context', value.required_context)}${listHuman('Outcomes', value.outcomes)}`;
}
function skillHuman(item) {
  const value = item.details || {};
  return `<p>${esc(item.summary || 'No skill purpose declared.')}</p><dl class="modal-detail"><div><dt>Skill ID</dt><dd class="mono">${esc(item.id)}</dd></div><div><dt>Namespace</dt><dd>${esc(value.domain || item.kind)}</dd></div><div><dt>Lifecycle</dt><dd>${esc(item.status)}</dd></div><div><dt>Package / manifest</dt><dd class="mono">${esc(value.package_path || value.manifest_path || value.path || item.path || 'Not declared')}</dd></div><div><dt>Version</dt><dd>${esc(value.version || 'Not declared')}</dd></div><div><dt>Provenance</dt><dd>${esc(readableValue(value.provenance || value.source || 'Not declared'))}</dd></div><div><dt>Effects</dt><dd>${esc(item.effects?.join(', ') || 'None declared')}</dd></div><div><dt>Admission</dt><dd>${esc(value.admission_state || value.status || 'Not admitted by catalog presence')}</dd></div></dl>${listHuman('Capability tags', item.tags)}${listHuman('Contracts', value.contracts)}${listHuman('Tests', value.tests)}${value.backup ? '<p>Original user/vendor source is preserved and is not overwritten by PX canonical adaptation.</p>' : ''}`;
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
function csv(values) { return (Array.isArray(values) ? values : []).join(', '); }
function agentValidationHtml(validation) {
  const warnings = (validation.warnings || []).map(issue => `<span class="studio-warning">${esc(issue)}</span>`).join('');
  return `<b>${validation.valid ? 'Agent candidate passes browser preflight' : `${validation.issues.length} structural issue(s)`}</b>${validation.issues.map(issue => `<span>${esc(issue)}</span>`).join('')}${warnings}<small>${number(validation.counts?.bindings || 0)} bindings · ${number(validation.counts?.grants || 0)} grants · ${number(validation.counts?.tests || 0)} required tests</small>`;
}
function agentStructuralChecksHtml(draft) {
  const selected = new Set(Array.isArray(draft.required_tests) ? draft.required_tests : []);
  const known = new Set(agentStructuralChecks.map(check => check.id));
  const unknown = [...selected].filter(testId => !known.has(testId));
  const checks = agentStructuralChecks.map(check => `<label class="agent-structural-check${selected.has(check.id) ? ' selected' : ''}"><input type="checkbox" data-agent-required-test="${esc(check.id)}" ${selected.has(check.id) ? 'checked' : ''}><span><b>${esc(check.label)}</b><code>${esc(check.id)}</code><small>${esc(check.description)}</small></span></label>`).join('');
  const unknownNotice = unknown.length ? `<p class="studio-warning" role="alert">Unknown imported check IDs: ${esc(unknown.join(', '))}. Remove them in Canonical JSON or replace them with implemented checks.</p>` : '';
  return `<fieldset class="agent-structural-checks"><legend>Required structural preflight checks</legend>${checks}</fieldset>${unknownNotice}<p class="fine-print">Selections become immutable candidate requirements. They do not claim that a check passed.</p>`;
}
function agentModelSectionHtml(draft) {
  const model = draft.model || {};
  const hostRouted = ['vscode-lm', 'pacify-local'].includes(model.provider);
  const availableModels = studioModelCatalog.filter(item => model.provider === 'pacify-local' ? item.vendor === 'pacify-local' : item.vendor !== 'pacify-local');
  const modelOptions = availableModels.map(item => `<option value="${esc(item.id)}" ${model.model_id === item.id ? 'selected' : ''}>${esc(item.name || item.id)} · ${esc(item.vendor || 'host')} / ${esc(item.family || 'unknown')}</option>`).join('');
  const routeState = hostRouted
    ? availableModels.length ? `${availableModels.length} compatible host model${availableModels.length === 1 ? '' : 's'} available.` : 'No compatible host model is currently available; refresh the host catalog or change provider.'
    : 'The deterministic worker executes without an AI model.';
  return `<section class="agent-builder-section" id="agent-model-route"><header><div><span>MODEL RUNTIME</span><h3>Host-retained model route</h3></div><button data-action="refreshHostModels">Refresh host models</button></header><div class="agent-builder-fields"><label><span>Provider</span><select data-agent-model-field="provider"><option value="vscode-lm" ${model.provider === 'vscode-lm' ? 'selected' : ''}>VS Code Language Model API</option><option value="pacify-local" ${model.provider === 'pacify-local' ? 'selected' : ''}>Pacify local / Ollama</option><option value="deterministic" ${model.provider === 'deterministic' ? 'selected' : ''}>Deterministic worker</option></select></label><label><span>Admitted host model</span><select data-agent-host-model ${hostRouted ? '' : 'disabled'}><option value="auto">Automatic admitted match</option>${modelOptions}</select></label><label><span>Vendor</span><input data-agent-model-field="vendor" value="${esc(model.vendor || '')}" placeholder="auto"></label><label><span>Family</span><input data-agent-model-field="family" value="${esc(model.family || '')}" placeholder="gpt-5"></label><label><span>Model ID</span><input data-agent-model-field="model_id" value="${esc(model.model_id || 'auto')}" ${availableModels.length && hostRouted ? 'readonly' : ''}></label><label><span>Version</span><input data-agent-model-field="version" value="${esc(model.version || '')}" placeholder="Exact host version" ${availableModels.length && hostRouted ? 'readonly' : ''}></label><label><span>Max output tokens</span><input type="number" min="1" max="32768" data-agent-model-field="max_output_tokens" value="${Math.max(1, Math.min(32768, Number(model.max_output_tokens) || 4096))}"></label><label><span>Temperature</span><input type="number" min="0" max="2" step="0.1" data-agent-model-field="temperature" value="${Number(model.temperature || 0)}"></label></div><p class="fine-print">${esc(routeState)} VS Code owns execution and account security; PX binds the admitted revision, task, exact route, and output contract around the request.</p></section>`;
}
function drawLegacyAgentTopologyEdges(root) {
  const graph = root?.querySelector?.('.agent-topology'); if (!graph) return;
  graph.querySelector('.agent-topology-links')?.remove();
  const nodes = new Map([...graph.querySelectorAll('[data-agent-section]')].map(node => [node.dataset.agentSection, node]));
  const links = [
    ['identity', 'behavior', 'owns'], ['behavior', 'model', 'prompts'], ['model', 'harness', 'executes through'],
    ['harness', 'capabilities', 'requests'], ['capabilities', 'tools', 'binds'], ['capabilities', 'workflows', 'hands off'],
    ['behavior', 'memory', 'retrieves'], ['tools', 'authority', 'requires'], ['workflows', 'authority', 'requires'], ['memory', 'authority', 'bounded by'],
    ['authority', 'tests', 'preflight'], ['tests', 'approval', 'requires'], ['approval', 'candidate', 'admits']
  ];
  const bounds = graph.getBoundingClientRect(); if (!bounds.width || !bounds.height) return;
  const paths = links.map(([from, to, label]) => { const source = nodes.get(from)?.getBoundingClientRect(); const target = nodes.get(to)?.getBoundingClientRect(); if (!source || !target) return ''; const x1 = source.left + source.width / 2 - bounds.left; const y1 = source.top + source.height / 2 - bounds.top; const x2 = target.left + target.width / 2 - bounds.left; const y2 = target.top + target.height / 2 - bounds.top; const bend = Math.max(22, Math.abs(x2 - x1) * .35); return `<path d="M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}" marker-end="url(#agent-arrow)"><title>${esc(`${from} ${label} ${to}`)}</title></path>`; }).join('');
  graph.insertAdjacentHTML('afterbegin', `<svg class="agent-topology-links" width="${Math.ceil(bounds.width)}" height="${Math.ceil(bounds.height)}" viewBox="0 0 ${Math.ceil(bounds.width)} ${Math.ceil(bounds.height)}" aria-label="Typed agent runtime relationships"><defs><marker id="agent-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${paths}</svg>`);
}
function upgradeLegacyAgentTopology(root) {
  if (studioEditor?.kind !== 'agent' || !root) return;
  const pipeline = root.querySelector('.agent-builder-pipeline');
  if (!pipeline) return;
  const draft = studioEditor.draft; const validation = studioEditors.validateAgent(draft);
  const nodes = [
    ['identity', 'START / IDENTITY', draft.agent_id, '#studio-identity', 'definition'],
    ['behavior', 'BEHAVIOR', 'bounded instructions', '[data-agent-root-field="instructions"]', 'definition'],
    ['model', 'MODEL ROUTE', `${draft.model?.provider || 'unconfigured'} / ${draft.model?.model_id || 'none'}`, '#agent-model-route', 'runtime'],
    ['harness', 'HOST HARNESS', draft.harness_id, '[data-agent-root-field="harness_id"]', 'runtime'],
    ['capabilities', 'SKILLS / CAPABILITIES', `${draft.bindings.length} binding${draft.bindings.length === 1 ? '' : 's'}`, '[data-agent-binding-index] input', 'binding'],
    ['tools', 'TOOLS', draft.tool_binding_ids?.length ? `${draft.tool_binding_ids.length} governed host binding${draft.tool_binding_ids.length === 1 ? '' : 's'}` : 'none declared', '#agent-integrations', 'binding'],
    ['workflows', 'WORKFLOWS / HANDOFFS', draft.handoff_agent_ids?.length ? `${draft.handoff_agent_ids.length} blocked; runtime unresolved` : 'none declared', '#agent-integrations', 'binding'],
    ['memory', 'MEMORY / CONTEXT', draft.memory_binding_ids?.length ? `${draft.memory_binding_ids.length} blocked; runtime unresolved` : 'none declared', '#agent-integrations', 'binding'],
    ['authority', 'SCOPE / AUTHORITY', `${draft.grants.length} grant${draft.grants.length === 1 ? '' : 's'}`, '[data-agent-grant-index] input', 'authority'],
    ['tests', 'PREFLIGHT CONTRACT', `${draft.required_tests.length} required`, '[data-agent-required-test]', 'gate'],
    ['approval', 'HUMAN APPROVAL', 'separate signed operation', '[data-studio-validation]', 'gate'],
    ['candidate', validation.valid ? 'CANDIDATE READY' : 'CANDIDATE BLOCKED', validation.valid ? 'saveable revision' : `${validation.issues.length} issue(s)`, '[data-studio-validation]', validation.valid ? 'terminal' : 'blocked']
  ];
  pipeline.className = 'agent-topology';
  pipeline.setAttribute('aria-label', 'Interactive agent runtime topology');
  pipeline.innerHTML = nodes.map(([id, label, detail, _target, domain]) => `<span class="agent-topology-node domain-${esc(domain)}${agentSelectedSection === id ? ' selected' : ''}" data-legacy-agent-section="${esc(id)}"><span>${esc(label)}</span><strong>${esc(detail)}</strong><small>${domain === 'authority' || domain === 'gate' ? 'governed boundary' : domain === 'terminal' ? 'immutable candidate' : 'historical projection'}</small></span>`).join('');
  requestAnimationFrame(() => drawLegacyAgentTopologyEdges(root));
  const main = root.querySelector('.agent-builder-layout > main'); const model = draft.model || {};
  if (main && !main.querySelector('#agent-model-route')) {
    const availableModels = studioModelCatalog.filter(item => model.provider === 'pacify-local' ? item.vendor === 'pacify-local' : item.vendor !== 'pacify-local');
    const modelOptions = availableModels.map(item => `<option value="${esc(item.id)}" ${model.model_id === item.id ? 'selected' : ''}>${esc(item.name || item.id)} · ${esc(item.vendor || 'host')} / ${esc(item.family || 'unknown')}</option>`).join('');
    const hostRouted = ['vscode-lm', 'pacify-local'].includes(model.provider);
    main.insertAdjacentHTML('afterbegin', `<section class="agent-builder-section" id="agent-model-route"><header><div><span>MODEL RUNTIME</span><h3>Host-retained model route</h3></div><button data-action="refreshHostModels">Refresh host models</button></header><div class="agent-builder-fields"><label><span>Provider</span><select data-agent-model-field="provider"><option value="vscode-lm" ${model.provider === 'vscode-lm' ? 'selected' : ''}>VS Code Language Model API</option><option value="pacify-local" ${model.provider === 'pacify-local' ? 'selected' : ''}>Pacify local / Ollama</option><option value="deterministic" ${model.provider === 'deterministic' ? 'selected' : ''}>Deterministic worker</option></select></label><label><span>Admitted host model</span><select data-agent-host-model ${hostRouted ? '' : 'disabled'}><option value="auto">Automatic admitted match</option>${modelOptions}</select></label><label><span>Vendor</span><input data-agent-model-field="vendor" value="${esc(model.vendor || '')}" placeholder="auto"></label><label><span>Family</span><input data-agent-model-field="family" value="${esc(model.family || '')}" placeholder="gpt-5"></label><label><span>Model ID</span><input data-agent-model-field="model_id" value="${esc(model.model_id || 'auto')}" ${availableModels.length && hostRouted ? 'readonly' : ''}></label><label><span>Max output tokens</span><input type="number" min="1" max="32768" data-agent-model-field="max_output_tokens" value="${number(model.max_output_tokens || 4096)}"></label><label><span>Temperature</span><input type="number" min="0" max="2" step="0.1" data-agent-model-field="temperature" value="${Number(model.temperature || 0)}"></label></div><p class="fine-print">VS Code owns model execution and account security. PX binds the admitted revision, task, exact model route, and output contract around the request.</p></section><section class="agent-builder-section" id="agent-integrations"><header><div><span>TOOLS, MEMORY & HANDOFFS</span><h3>Runtime topology bindings</h3></div></header><div class="agent-builder-fields"><label><span>Tool binding IDs</span><textarea data-agent-list-field="tool_binding_ids" rows="3">${esc(csv(draft.tool_binding_ids))}</textarea></label><label><span>Memory binding IDs</span><textarea data-agent-list-field="memory_binding_ids" rows="3">${esc(csv(draft.memory_binding_ids))}</textarea></label><label><span>Handoff agent IDs</span><textarea data-agent-list-field="handoff_agent_ids" rows="3">${esc(csv(draft.handoff_agent_ids))}</textarea></label></div><div class="agent-builder-fields"><label><span>Input JSON schema</span><textarea data-agent-json-field="input_schema" rows="8">${esc(JSON.stringify(draft.input_schema, null, 2))}</textarea></label><label><span>Output JSON schema</span><textarea data-agent-json-field="output_schema" rows="8">${esc(JSON.stringify(draft.output_schema, null, 2))}</textarea></label></div></section>`);
  }
  const modelRoute = root.querySelector('#agent-model-route');
  const automaticOption = modelRoute?.querySelector('[data-agent-host-model] option[value="auto"]');
  if (automaticOption) {
    automaticOption.disabled = true;
    automaticOption.textContent = 'Select an exact live host model';
  }
  const modelId = modelRoute?.querySelector('[data-agent-model-field="model_id"]');
  if (modelId) {
    modelId.placeholder = 'Select from the live host catalog';
    const modelIdLabel = modelId.closest('label');
    const hostRouted = ['vscode-lm', 'pacify-local'].includes(model.provider);
    if (!modelRoute.querySelector('[data-agent-model-field="version"]')) modelIdLabel?.insertAdjacentHTML('afterend', `<label><span>Version</span><input data-agent-model-field="version" value="${esc(model.version || '')}" placeholder="Exact host version" ${studioModelCatalog.length && hostRouted ? 'readonly' : ''}></label>`);
  }
  const maxOutput = root.querySelector('[data-agent-model-field="max_output_tokens"]');
  if (maxOutput && !maxOutput.value) maxOutput.value = String(Math.max(1, Math.min(32768, Number(model.max_output_tokens) || 4096)));
  const harness = root.querySelector('[data-agent-root-field="harness_id"]')?.closest('.agent-builder-section');
  if (harness && !harness.querySelector('.agent-runtime-truth')) harness.insertAdjacentHTML('beforeend', `<div class="agent-runtime-truth"><b>Runtime truth</b><span>${draft.model?.provider === 'vscode-lm' ? 'This revision invokes a selected VS Code language model through host-retained authority after PX admission and explicit launch approval.' : draft.model?.provider === 'pacify-local' ? 'This revision declares the local Pacify/Ollama route; execution requires an available loopback model provider.' : 'This revision uses the deterministic owned worker and does not invoke an AI model.'}</span></div>`);
  for (const heading of root.querySelectorAll('.agent-builder-side section > b')) if (heading.textContent.trim() === 'Required certification tests') heading.textContent = 'Required structural preflight checks';
}
function agentLayoutMap(draft, graph) {
  const supplied = draft.editor_layout?.layout && typeof draft.editor_layout.layout === 'object' ? draft.editor_layout.layout : draft.editor_layout;
  const layout = supplied && typeof supplied === 'object' && !Array.isArray(supplied) ? supplied : {};
  return Object.fromEntries(graph.nodes.map((node, index) => {
    const point = layout[node.node_id]; const column = index % 4; const row = Math.floor(index / 4);
    return [node.node_id, { x: finiteLayoutNumber(point?.x, -100000, 100000, 36 + column * 224), y: finiteLayoutNumber(point?.y, -100000, 100000, 42 + row * 142) }];
  }));
}
function agentCanonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(agentCanonicalJson).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${agentCanonicalJson(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}
function currentAgentGraph(draft) {
  const persistedValidation = studioEditors.validateAgentBuilderGraph(agentPersistedGraph);
  const basis = agentWorkingGraph && typeof agentWorkingGraph === 'object'
    ? agentWorkingGraph
    : persistedValidation.valid ? agentPersistedGraph : null;
  const graph = studioEditors.synchronizeAgentBuilderGraph(draft, basis);
  agentWorkingGraph = structuredClone(graph); draft.builder_graph = structuredClone(graph);
  const clean = !agentGraphDirty && persistedValidation.valid && agentCanonicalJson(agentPersistedGraph) === agentCanonicalJson(graph);
  return { graph, source: clean ? 'persisted-verified' : 'working-projection' };
}
function agentNodeDetail(node, draft, validation) {
  const values = { identity: draft.agent_id, behavior: `${String(draft.instructions || '').length} instruction characters`, model: `${draft.model?.provider || 'none'} / ${draft.model?.model_id || 'none'}`, harness: draft.harness_id, capabilities: `${draft.capability_binding_ids.length} bindings`, tools: `${draft.tool_binding_ids.length} tools`, handoffs: `${draft.handoff_agent_ids.length} handoffs`, memory: `${draft.memory_binding_ids.length} memories`, contracts: 'typed input and output', authority: `${draft.effect_grant_ids.length} grants`, tests: `${draft.required_tests.length} checks`, candidate: validation.valid ? 'structurally ready' : `${validation.issues.length} issues` };
  return values[node.kind] || node.node_id;
}
function agentInspectorHtml(node, draft, graph) {
  if (!node) return '<section class="agent-node-inspector"><p>Select a graph node to inspect its canonical fields.</p></section>';
  const listField = (label, field) => `<label><span>${label}</span><textarea data-agent-list-field="${field}" rows="4">${esc(csv(draft[field]))}</textarea></label>`;
  const body = node.kind === 'identity' ? `<label><span>Project ID</span><input data-agent-root-field="project_id" value="${esc(draft.project_id)}"></label><p>Agent identity, version, and owner remain in the revision header.</p>`
    : node.kind === 'behavior' ? `<label><span>Bounded instructions</span><textarea data-agent-root-field="instructions" rows="10">${esc(draft.instructions)}</textarea></label>`
    : node.kind === 'model' ? agentModelSectionHtml(draft)
    : node.kind === 'harness' ? `<label><span>Harness ID</span><input data-agent-root-field="harness_id" value="${esc(draft.harness_id)}"></label><p>Host execution authority remains outside this graph.</p>`
    : node.kind === 'capabilities' ? `${listField('Capability binding IDs', 'capability_binding_ids')}${listField('Tool binding IDs', 'tool_binding_ids')}${listField('Memory binding IDs', 'memory_binding_ids')}${listField('Handoff agent IDs', 'handoff_agent_ids')}`
    : node.kind === 'tools' ? listField('Tool binding IDs', 'tool_binding_ids')
    : node.kind === 'handoffs' ? listField('Handoff agent IDs', 'handoff_agent_ids')
    : node.kind === 'memory' ? listField('Memory binding IDs', 'memory_binding_ids')
    : node.kind === 'contracts' ? `<label><span>Input JSON schema</span><textarea data-agent-json-field="input_schema" rows="8">${esc(JSON.stringify(draft.input_schema, null, 2))}</textarea></label><label><span>Output JSON schema</span><textarea data-agent-json-field="output_schema" rows="8">${esc(JSON.stringify(draft.output_schema, null, 2))}</textarea></label>`
    : node.kind === 'authority' ? listField('Effect grant IDs', 'effect_grant_ids')
    : node.kind === 'tests' ? agentStructuralChecksHtml(draft)
    : '<p>This terminal node is derived from the complete AgentSpec. It grants no authority and is not directly editable.</p>';
  const optionalKinds = ['tools', 'handoffs', 'memory']; const editable = optionalKinds.includes(node.kind);
  const availableKinds = optionalKinds.filter(kind => kind === node.kind || !graph.nodes.some(item => item.kind === kind));
  const topologyActions = editable ? `<div class="studio-inline-actions"><label><span>Node type</span><select data-agent-node-kind data-agent-node-id="${esc(node.node_id)}">${availableKinds.map(kind => `<option value="${esc(kind)}" ${kind === node.kind ? 'selected' : ''}>${esc(kind)}</option>`).join('')}</select></label><button class="danger-action" data-action="agentRemoveTopologyNode" data-agent-node-id="${esc(node.node_id)}">Remove node</button></div>` : '<p class="fine-print">Required AgentSpec node. Its stable canonical identity cannot be removed or retyped.</p>';
  return `<section class="agent-node-inspector" data-agent-inspector><header><div><span>SELECTED NODE</span><h3>${esc(node.kind)}</h3><small class="mono">${esc(node.node_id)}</small></div><b>${number(node.ports.length)} ports</b></header>${topologyActions}<div class="agent-inspector-fields">${body}</div></section>`;
}
function agentCanvasHtml(draft, validation) {
  const { graph, source } = currentAgentGraph(draft); const layout = agentLayoutMap(draft, graph); draft.editor_layout = layout;
  if (!graph.nodes.some(node => node.kind === agentSelectedSection)) agentSelectedSection = graph.nodes[0]?.kind || 'identity';
  const selected = graph.nodes.find(node => node.kind === agentSelectedSection);
  const width = Math.max(920, ...Object.values(layout).map(point => point.x + 210)); const height = Math.max(470, ...Object.values(layout).map(point => point.y + 112));
  const nodes = graph.nodes.map(node => { const point = layout[node.node_id]; const ports = node.ports.map(port => { const selected = agentConnectionStart?.node === node.node_id && agentConnectionStart?.port === port.port_id; return `<button type="button" class="agent-node-port ${port.direction}${selected ? ' selected' : ''}" data-action="agentPortConnect" data-direction="${esc(port.direction)}" data-node-id="${esc(node.node_id)}" data-port="${esc(port.port_id)}" title="${esc(`${port.port_id}: ${port.data_type}`)}" aria-pressed="${selected}"><i></i>${esc(port.port_id.replace(/^(?:in|out):/, ''))}</button>`; }).join(''); return `<article class="agent-graph-node domain-${esc(node.kind)}${node.kind === agentSelectedSection ? ' selected' : ''}" draggable="true" data-action="agentSelectNode" data-agent-node-id="${esc(node.node_id)}" data-agent-kind="${esc(node.kind)}" data-agent-x="${point.x}" data-agent-y="${point.y}" aria-pressed="${node.kind === agentSelectedSection}" role="button" tabindex="0"><span>${esc(node.kind.toUpperCase())}</span><strong>${esc(agentNodeDetail(node, draft, validation))}</strong><small>${esc(node.node_id)}</small><span class="agent-node-ports">${ports}</span></article>`; }).join('');
  const minimap = graph.nodes.map(node => { const point = layout[node.node_id]; return `<i data-agent-mini-x="${Math.max(3, Math.min(134, point.x / width * 134))}" data-agent-mini-y="${Math.max(3, Math.min(78, point.y / height * 78))}" title="${esc(node.kind)}"></i>`; }).join('');
  const missingOptional = ['tools', 'handoffs', 'memory'].filter(kind => !graph.nodes.some(node => node.kind === kind));
  const addNodes = missingOptional.map(kind => `<button data-action="agentAddTopologyNode" data-agent-kind="${esc(kind)}">+ ${esc(kind)}</button>`).join('');
  const connectionStatus = agentConnectionStart ? `CONNECTING FROM ${agentConnectionStart.node}.${agentConnectionStart.port}` : 'SELECT AN OUTPUT, THEN A COMPATIBLE INPUT';
  return `<section class="agent-graph-workbench"><header class="agent-canvas-toolbar"><div><b>Executable AgentSpec projection</b><span class="agent-graph-state ${source}">${source === 'persisted-verified' ? 'PERSISTED · VERIFIED' : 'WORKING · PYTHON COMPILE REQUIRED'}</span></div><div role="toolbar" aria-label="Agent graph canvas controls">${addNodes}<button data-action="agentAutoLayout">Auto layout</button><button data-action="agentFit">Fit</button><button data-action="agentZoom" data-delta="-0.1" aria-label="Zoom out">−</button><output aria-live="polite">${Math.round(agentScale * 100)}%</output><button data-action="agentZoom" data-delta="0.1" aria-label="Zoom in">+</button></div></header><div class="agent-connection-status" aria-live="polite"><span>${esc(connectionStatus)}</span>${agentConnectionStart ? '<button data-action="agentCancelConnection">Cancel connection</button>' : ''}</div><div class="agent-graph-grid"><div class="agent-graph-canvas" data-agent-editor-canvas data-agent-scale="${agentScale}" tabindex="0" role="region" aria-label="Editable AgentSpec node graph with ${graph.nodes.length} nodes and ${graph.edges.length} typed working connections. Drag nodes to arrange; select an output and compatible input to connect; Alt plus arrow keys moves the selected node."><div class="agent-graph-scene" data-agent-scene-width="${width}" data-agent-scene-height="${height}">${nodes}</div><button class="agent-graph-minimap" data-action="agentFit" aria-label="Fit complete agent graph">${minimap}</button></div>${agentInspectorHtml(selected, draft, graph)}</div><details class="agent-accessible-topology" open><summary>Editable typed topology · ${graph.nodes.length} nodes · ${graph.edges.length} connections</summary><ol>${graph.edges.map(edge => `<li><code>${esc(edge.source_node)}.${esc(edge.source_port)}</code> ${esc(edge.relation)} <code>${esc(edge.target_node)}.${esc(edge.target_port)}</code><button class="danger-action" data-action="agentRemoveEdge" data-edge-id="${esc(edge.edge_id)}">Disconnect</button></li>`).join('')}</ol></details></section>`;
}
function drawAgentGraphEdges(root) {
  const canvas = root?.querySelector?.('[data-agent-editor-canvas]'); const scene = canvas?.querySelector?.('.agent-graph-scene'); if (!canvas || !scene || studioEditor?.kind !== 'agent') return;
  canvas.dataset.agentScale = finiteLayoutText(agentScale, .45, 1.75, 1); scene.querySelector('.agent-topology-links')?.remove();
  const { graph } = currentAgentGraph(studioEditor.draft); const layout = agentLayoutMap(studioEditor.draft, graph); const width = Math.max(920, ...Object.values(layout).map(point => point.x + 210)); const height = Math.max(470, ...Object.values(layout).map(point => point.y + 112));
  const paths = graph.edges.map(edge => { const source = layout[edge.source_node]; const target = layout[edge.target_node]; if (!source || !target) return ''; const x1 = source.x + 188; const y1 = source.y + 48; const x2 = target.x; const y2 = target.y + 48; const bend = Math.max(48, Math.abs(x2 - x1) * .4); return `<path d="M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}" marker-end="url(#agent-arrow)"><title>${esc(`${edge.source_port} ${edge.relation} ${edge.target_port}`)}</title></path>`; }).join('');
  scene.insertAdjacentHTML('afterbegin', `<svg class="agent-topology-links" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true"><defs><marker id="agent-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${paths}</svg>`); boundedLayout.apply(root);
}
function upgradeAgentTopology(root) {
  if (studioEditor?.kind !== 'agent' || !root) return;
  const pipeline = root.querySelector('.agent-builder-pipeline'); if (pipeline) pipeline.outerHTML = agentCanvasHtml(studioEditor.draft, studioEditors.validateAgent(studioEditor.draft));
  boundedLayout.apply(root); requestAnimationFrame(() => drawAgentGraphEdges(root));
}
function agentEditorHtml(draft) {
  const specValidation = studioEditors.validateAgent(draft);
  const graphValidation = studioEditors.validateAgentBuilderGraph(currentAgentGraph(draft).graph);
  const validation = { ...specValidation, valid: specValidation.valid && graphValidation.valid, issues: [...specValidation.issues, ...graphValidation.issues] };
  const bindings = draft.bindings.map((binding, index) => `<article class="agent-builder-card" data-agent-binding-index="${index}"><header><div><span>CAPABILITY ${index + 1}</span><strong>${esc(binding.binding_id)}</strong></div><button class="danger-action" data-action="agentRemoveBinding" data-index="${index}" ${draft.bindings.length <= 1 ? 'disabled' : ''}>Remove</button></header><div class="agent-builder-fields"><label><span>Binding ID</span><input data-agent-binding-field="binding_id" data-index="${index}" value="${esc(binding.binding_id)}"></label><label><span>Capability ID</span><input data-agent-binding-field="capability_id" data-index="${index}" value="${esc(binding.capability_id)}"></label><label><span>Capability version</span><input data-agent-binding-field="capability_version" data-index="${index}" value="${esc(binding.capability_version)}"></label><label><span>Grant IDs</span><input data-agent-binding-field="effect_grant_ids" data-index="${index}" value="${esc(csv(binding.effect_grant_ids))}"></label><label><span>Cost policy</span><input data-agent-binding-field="cost_policy" data-index="${index}" value="${esc(binding.cost_policy)}"></label><label><span>Egress policy</span><select data-agent-binding-field="egress_policy" data-index="${index}"><option value="deny" ${binding.egress_policy === 'deny' ? 'selected' : ''}>Deny</option><option value="loopback-only" ${binding.egress_policy === 'loopback-only' ? 'selected' : ''}>Loopback only</option><option value="allowlisted" ${binding.egress_policy === 'allowlisted' ? 'selected' : ''}>Allowlisted</option></select></label><label><span>Credential namespace (ID only)</span><input data-agent-binding-field="credential_namespace" data-index="${index}" value="${esc(binding.credential_namespace || '')}" placeholder="None"></label><label><span>Evidence references</span><input data-agent-binding-field="evidence_refs" data-index="${index}" value="${esc(csv(binding.evidence_refs))}"></label></div></article>`).join('');
  const grants = draft.grants.map((grant, index) => `<article class="agent-builder-card grant" data-agent-grant-index="${index}"><header><div><span>AUTHORITY ${index + 1}</span><strong>${esc(grant.grant_id)}</strong></div><button class="danger-action" data-action="agentRemoveGrant" data-index="${index}" ${draft.grants.length <= 1 ? 'disabled' : ''}>Remove</button></header><div class="agent-builder-fields"><label><span>Grant ID</span><input data-agent-grant-field="grant_id" data-index="${index}" value="${esc(grant.grant_id)}"></label><label><span>Declared effects</span><input data-agent-grant-field="effects" data-index="${index}" value="${esc(csv(grant.effects))}"></label><label><span>Bounded scope roots</span><input data-agent-grant-field="scope_roots" data-index="${index}" value="${esc(csv(grant.scope_roots))}"></label><label><span>Approved by</span><input data-agent-grant-field="approved_by" data-index="${index}" value="${esc(grant.approved_by)}"></label><label><span>Evidence references</span><input data-agent-grant-field="evidence_refs" data-index="${index}" value="${esc(csv(grant.evidence_refs))}"></label><label><span>Expires UTC (optional)</span><input data-agent-grant-field="expires_utc" data-index="${index}" value="${esc(grant.expires_utc || '')}" placeholder="YYYY-MM-DDTHH:mm:ssZ"></label></div></article>`).join('');
  const model = draft.model || {};
  const modelSection = `<section class="agent-builder-section" id="agent-model-route"><header><div><span>MODEL RUNTIME</span><h3>Host-retained model route</h3></div></header><div class="agent-builder-fields"><label><span>Provider</span><select data-agent-model-field="provider"><option value="vscode-lm" ${model.provider === 'vscode-lm' ? 'selected' : ''}>VS Code Language Model API</option><option value="pacify-local" ${model.provider === 'pacify-local' ? 'selected' : ''}>Pacify local / Ollama</option><option value="deterministic" ${model.provider === 'deterministic' ? 'selected' : ''}>Deterministic worker</option></select></label><label><span>Vendor</span><input data-agent-model-field="vendor" value="${esc(model.vendor || '')}" placeholder="auto"></label><label><span>Family</span><input data-agent-model-field="family" value="${esc(model.family || '')}" placeholder="gpt-5"></label><label><span>Model ID</span><input data-agent-model-field="model_id" value="${esc(model.model_id || 'auto')}" placeholder="auto"></label><label><span>Max output tokens</span><input type="number" min="1" max="32768" data-agent-model-field="max_output_tokens" value="${number(model.max_output_tokens || 4096)}"></label><label><span>Temperature</span><input type="number" min="0" max="2" step="0.1" data-agent-model-field="temperature" value="${Number(model.temperature || 0)}"></label></div><p class="fine-print">VS Code model execution remains owned by the host and its account/security controls. PX verifies the admitted revision, task, model route, and output contract around that host request.</p></section>`;
  const integrationSection = `<section class="agent-builder-section" id="agent-integrations"><header><div><span>TOOLS, MEMORY & HANDOFFS</span><h3>Runtime topology bindings</h3></div></header><div class="agent-builder-fields"><label><span>Tool binding IDs</span><textarea data-agent-list-field="tool_binding_ids" rows="3">${esc(csv(draft.tool_binding_ids))}</textarea></label><label><span>Memory binding IDs</span><textarea data-agent-list-field="memory_binding_ids" rows="3">${esc(csv(draft.memory_binding_ids))}</textarea></label><label><span>Handoff agent IDs</span><textarea data-agent-list-field="handoff_agent_ids" rows="3">${esc(csv(draft.handoff_agent_ids))}</textarea></label></div><div class="agent-builder-fields"><label><span>Input JSON schema</span><textarea data-agent-json-field="input_schema" rows="8">${esc(JSON.stringify(draft.input_schema, null, 2))}</textarea></label><label><span>Output JSON schema</span><textarea data-agent-json-field="output_schema" rows="8">${esc(JSON.stringify(draft.output_schema, null, 2))}</textarea></label></div></section>`;
  return `<div class="studio-editor-tabs" role="tablist" aria-label="Agent editor view"><button role="tab" aria-selected="true" data-action="studioEditorTab" data-tab="visual">Builder</button><button role="tab" aria-selected="false" data-action="studioEditorTab" data-tab="json">Canonical JSON</button></div><section class="studio-editor-panel" data-studio-panel="visual"><div class="agent-builder-domain" role="note"><strong>PX-STANDARD BUILDER</strong><span>Microsoft, vendor, and enterprise-restricted namespaces are isolated. This editor declares candidate policy; it does not grant host authority, credentials, admission, or execution.</span></div><div class="agent-builder-pipeline" aria-label="Agent candidate lifecycle"><span>Identity</span><i>→</i><span>Behavior</span><i>→</i><span>Capabilities</span><i>→</i><span>Authority</span><i>→</i><span>Tests</span><i>→</i><span>Candidate</span></div><div class="agent-builder-layout"><main><section class="agent-builder-section"><header><div><span>BEHAVIOR</span><h3>Instructions and owned harness</h3></div></header><div class="agent-builder-fields identity"><label><span>Project ID</span><input data-agent-root-field="project_id" value="${esc(draft.project_id)}"></label><label><span>Harness ID</span><input data-agent-root-field="harness_id" value="${esc(draft.harness_id)}"></label><label><span>Lifecycle</span><input value="draft" disabled aria-label="Lifecycle is draft"></label></div><label class="agent-instructions"><span>Bounded instructions</span><textarea data-agent-root-field="instructions" rows="8" spellcheck="true">${esc(draft.instructions)}</textarea></label></section><section class="agent-builder-section"><header><div><span>CAPABILITY BINDINGS</span><h3>What the agent may request</h3></div><button data-action="agentAddBinding">+ Capability</button></header><div class="agent-builder-collection">${bindings}</div></section><section class="agent-builder-section"><header><div><span>EFFECT GRANTS</span><h3>What effects are within declared scope</h3></div><button data-action="agentAddGrant">+ Grant</button></header><div class="agent-builder-collection">${grants}</div></section></main><aside class="agent-builder-side"><section class="studio-validation ${validation.valid ? 'passed' : 'failed'}" data-studio-validation role="status">${agentValidationHtml(validation)}</section><section>${agentStructuralChecksHtml(draft)}</section><section><b>Canonical references</b><dl><div><dt>Bindings</dt><dd>${esc(csv(draft.capability_binding_ids))}</dd></div><div><dt>Grants</dt><dd>${esc(csv(draft.effect_grant_ids))}</dd></div><div><dt>Domain</dt><dd>px-standard</dd></div></dl></section><section><b>Safety boundary</b><ul><li>No secret values are accepted.</li><li>Cost and egress default closed.</li><li>Save creates an immutable candidate only.</li><li>Test, authority registration, admission, and run remain separate signed operations.</li></ul></section></aside></div></section><section class="studio-editor-panel" data-studio-panel="json" hidden><label class="modal-field"><span>Canonical synchronized JSON</span><textarea id="studio-draft-json" rows="26" spellcheck="false">${esc(JSON.stringify(draft, null, 2))}</textarea></label><button data-action="studioApplyJson">Apply JSON to visual builder</button><p class="fine-print">Applying JSON normalizes canonical identities and policies, then reruns the same conservative browser preflight. Python remains authoritative.</p></section>`;
}
function drawWorkflowCanvasEdges(root, draft) {
  const canvas = root?.querySelector?.('[data-workflow-editor-canvas]'); if (!canvas) return;
  canvas.dataset.workflowScale = finiteLayoutText(workflowScale, .45, 1.75, 1);
  boundedLayout.apply(canvas);
  canvas.querySelector('.workflow-edge-layer')?.remove();
  const width = Math.max(720, canvas.clientWidth || 0, ...(draft.nodes || []).map(node => Number(node.position?.x || 0) + 220));
  const height = Math.max(430, canvas.clientHeight || 0, ...(draft.nodes || []).map(node => Number(node.position?.y || 0) + 110));
  const paths = (draft.edges || []).map(edge => { const source = draft.nodes.find(node => node.node_id === edge.source_node); const target = draft.nodes.find(node => node.node_id === edge.target_node); if (!source || !target) return ''; const x1 = Number(source.position?.x || 40) + 178; const y1 = Number(source.position?.y || 40) + 36; const x2 = Number(target.position?.x || 40); const y2 = Number(target.position?.y || 40) + 36; const bend = Math.max(60, Math.abs(x2 - x1) * .45); const labelX = (x1 + x2) / 2; const labelY = (y1 + y2) / 2 - 7; return `<g><path d="M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}" marker-end="url(#workflow-arrow)"><title>${esc(`${edge.source_node}.${edge.source_port} → ${edge.target_node}.${edge.target_port} when ${edge.condition}`)}</title></path><text x="${labelX}" y="${labelY}">${esc(edge.condition || 'always')}</text></g>`; }).join('');
  canvas.insertAdjacentHTML('afterbegin', `<svg class="workflow-edge-layer" viewBox="0 0 ${width} ${height}" width="${Math.round(width * workflowScale)}" height="${Math.round(height * workflowScale)}" aria-label="${number((draft.edges || []).length)} typed workflow connections"><defs><marker id="workflow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${paths}</svg>`);
}
function workflowTraceEvidenceValue(value) {
  if (typeof value === 'string') return value.trim();
  if (!workflowTraceObject(value)) return '';
  try { return JSON.stringify(value); } catch { return ''; }
}
function workflowTraceEvidenceText(trace) {
  const details = [];
  if (Number.isInteger(trace?.attempt_count)) details.push(`${trace.attempt_count} attempt${trace.attempt_count === 1 ? '' : 's'}`);
  if (trace?.skip_reason) details.push(`skip: ${String(trace.skip_reason)}`);
  if (Array.isArray(trace?.disabled_required_ports) && trace.disabled_required_ports.length) details.push(`disabled ports: ${trace.disabled_required_ports.map(String).join(', ')}`);
  const failure = workflowTraceObject(trace?.failure) || {};
  const failureDetail = failure.failure_message || failure.message || failure.failure_type || failure.code;
  if (failureDetail) details.push(`failure: ${String(failureDetail)}`);
  const correlation = failure.failure_correlation_id || failure.correlation_id;
  if (correlation) details.push(`correlation: ${String(correlation)}`);
  const nodeRecovery = workflowTraceEvidenceValue(trace?.recovery);
  if (nodeRecovery) details.push(`recovery: ${nodeRecovery}`);
  const runRecovery = workflowTraceEvidenceValue(workflowTraceMetadata.recovery);
  if (runRecovery && runRecovery !== nodeRecovery) details.push(`run recovery: ${runRecovery}`);
  return details.join(' / ');
}
function annotateWorkflowTraceEvidence(root) {
  for (const node of root?.querySelectorAll?.('.workflow-editor-node[data-node-id]') || []) {
    const body = node.querySelector('.workflow-node-body'); if (!body) continue;
    body.querySelector('[data-workflow-trace-evidence]')?.remove();
    body.removeAttribute('aria-description');
    const trace = workflowRunTrace[node.dataset.nodeId] || {}; const detail = workflowTraceEvidenceText(trace);
    if (!detail) continue;
    const summary = document.createElement('small'); summary.dataset.workflowTraceEvidence = 'true';
    summary.textContent = detail; summary.title = detail;
    body.setAttribute('aria-description', detail);
    body.appendChild(summary);
  }
}
function upgradeWorkflowCanvas(root) {
  const canvas = root?.querySelector?.('[data-workflow-editor-canvas]'); if (!canvas) return;
  if (!canvas.previousElementSibling?.classList.contains('workflow-canvas-toolbar')) canvas.insertAdjacentHTML('beforebegin', `<div class="workflow-canvas-toolbar" role="toolbar" aria-label="Workflow canvas controls"><button data-action="workflowAutoLayout">Auto layout</button><button data-action="workflowFit">Fit</button><button data-action="workflowZoom" data-delta="-0.1" aria-label="Zoom out">−</button><output>${Math.round(workflowScale * 100)}%</output><button data-action="workflowZoom" data-delta="0.1" aria-label="Zoom in">+</button><button data-action="workflowCancelConnection" ${workflowConnectionStart ? '' : 'disabled'}>${workflowConnectionStart ? `Cancel ${esc(workflowConnectionStart.node)}.${esc(workflowConnectionStart.port)}` : 'No connection pending'}</button></div>`);
  canvas.dataset.workflowScale = finiteLayoutText(workflowScale, .45, 1.75, 1);
  const draft = studioEditor?.kind === 'workflow' ? studioEditor.draft : null;
  const inspector = root.querySelector('[data-workflow-inspector]');
  const bindingInput = inspector?.querySelector('[data-workflow-field="executor_binding_id"]');
  if (draft && bindingInput && !inspector.querySelector('[data-workflow-adapter]')) {
    const adapter = draft.executor_adapters?.[bindingInput.value] || '';
    bindingInput.closest('label')?.insertAdjacentHTML('afterend', `<label><span>Closed executor adapter</span><select data-workflow-adapter><option value="">Select exact adapter</option>${['identity', 'increment', 'double', 'sleep', 'fail'].map(value => `<option value="${value}" ${adapter === value ? 'selected' : ''}>${value}</option>`).join('')}</select><small>These are deterministic local adapters, not general-purpose agent tasks.</small></label>`);
  }
  const layout = root.querySelector('.workflow-editor-layout');
  if (draft && layout && !root.querySelector('.workflow-input-contract')) {
    const rows = (draft.run_input_contract || []).map(item => `<li><code>${esc(item.key)}</code><span>${esc(item.value_type)} · ${item.required === false ? 'optional' : 'required'}</span></li>`).join('');
    layout.insertAdjacentHTML('afterend', `<section class="workflow-input-contract"><header><b>Run input contract</b><span>Values remain ephemeral; this typed contract is stored with the revision.</span></header><ol>${rows || '<li>No external inputs; every input is edge-driven.</li>'}</ol></section>`);
  }
  if (draft && layout && !root.querySelector('.workflow-authority-editor')) {
    layout.insertAdjacentHTML('afterend', workflowAuthorityHtml(draft));
  }
  annotateWorkflowTraceEvidence(root);
  boundedLayout.apply(root);
}

const WORKFLOW_ADAPTER_IDS = Object.freeze(['identity', 'increment', 'double', 'sleep', 'fail']);
const workflowAdapterOptions = selected => WORKFLOW_ADAPTER_IDS.map(value => `<option value="${value}" ${selected === value ? 'selected' : ''}>${value}</option>`).join('');

function workflowAuthorityHtml(draft) {
  const bindings = (draft.bindings || []).map((binding, index) => `<article class="agent-builder-card" data-workflow-binding-index="${index}"><header><div><span>EXECUTOR BINDING ${index + 1}</span><strong>${esc(binding.binding_id)}</strong></div><button class="danger-action" data-action="workflowRemoveBinding" data-index="${index}" ${(draft.bindings || []).length <= 1 ? 'disabled' : ''}>Remove</button></header><div class="agent-builder-fields"><label><span>Binding ID</span><input data-workflow-binding-field="binding_id" data-index="${index}" value="${esc(binding.binding_id)}"></label><label><span>Capability ID</span><input data-workflow-binding-field="capability_id" data-index="${index}" value="${esc(binding.capability_id)}"></label><label><span>Capability version</span><input data-workflow-binding-field="capability_version" data-index="${index}" value="${esc(binding.capability_version)}"></label><label><span>Closed executor adapter</span><select data-workflow-binding-adapter data-index="${index}">${workflowAdapterOptions(draft.executor_adapters?.[binding.binding_id] || '')}</select></label><label><span>Grant IDs</span><input data-workflow-binding-field="effect_grant_ids" data-index="${index}" value="${esc(csv(binding.effect_grant_ids))}"></label><label><span>Cost policy</span><input data-workflow-binding-field="cost_policy" data-index="${index}" value="${esc(binding.cost_policy)}"></label><label><span>Egress policy</span><select data-workflow-binding-field="egress_policy" data-index="${index}"><option value="deny" ${binding.egress_policy === 'deny' ? 'selected' : ''}>Deny</option><option value="loopback-only" ${binding.egress_policy === 'loopback-only' ? 'selected' : ''}>Loopback only</option><option value="allowlisted" ${binding.egress_policy === 'allowlisted' ? 'selected' : ''}>Allowlisted</option></select></label><label><span>Credential namespace (ID only)</span><input data-workflow-binding-field="credential_namespace" data-index="${index}" value="${esc(binding.credential_namespace || '')}" placeholder="None"></label><label><span>Evidence references</span><input data-workflow-binding-field="evidence_refs" data-index="${index}" value="${esc(csv(binding.evidence_refs))}"></label></div></article>`).join('');
  const grants = (draft.grants || []).map((grant, index) => `<article class="agent-builder-card grant" data-workflow-grant-index="${index}"><header><div><span>EFFECT GRANT ${index + 1}</span><strong>${esc(grant.grant_id)}</strong></div><button class="danger-action" data-action="workflowRemoveGrant" data-index="${index}" ${(draft.grants || []).length <= 1 ? 'disabled' : ''}>Remove</button></header><div class="agent-builder-fields"><label><span>Grant ID</span><input data-workflow-grant-field="grant_id" data-index="${index}" value="${esc(grant.grant_id)}"></label><label><span>Declared effects</span><input data-workflow-grant-field="effects" data-index="${index}" value="${esc(csv(grant.effects))}"></label><label><span>Bounded scope roots</span><input data-workflow-grant-field="scope_roots" data-index="${index}" value="${esc(csv(grant.scope_roots))}"></label><label><span>Approved by</span><input data-workflow-grant-field="approved_by" data-index="${index}" value="${esc(grant.approved_by)}"></label><label><span>Evidence references</span><input data-workflow-grant-field="evidence_refs" data-index="${index}" value="${esc(csv(grant.evidence_refs))}"></label><label><span>Expires UTC (optional)</span><input data-workflow-grant-field="expires_utc" data-index="${index}" value="${esc(grant.expires_utc || '')}" placeholder="YYYY-MM-DDTHH:mm:ssZ"></label></div></article>`).join('');
  return `<section class="workflow-authority-editor"><header><div><span>EXECUTION AUTHORITY</span><h3>Bindings and effect grants stored with this revision</h3></div><p>These definitions are editable here and authenticated separately before admission. Secret values are never accepted.</p></header><div class="two-col"><section><div class="studio-inline-actions"><b>Executor bindings</b><button data-action="workflowAddBinding">+ Binding</button></div><div class="agent-builder-collection">${bindings || '<p>No executor binding is defined.</p>'}</div></section><section><div class="studio-inline-actions"><b>Effect grants</b><button data-action="workflowAddGrant">+ Grant</button></div><div class="agent-builder-collection">${grants || '<p>No effect grant is defined.</p>'}</div></section></div></section>`;
}

function workflowEditorHtml(draft) {
  const validation = studioEditors.validateWorkflow(draft);
  const selected = draft.nodes.find(node => node.node_id === studioSelectedNode) || draft.nodes[0];
  studioSelectedNode = selected?.node_id || '';
  const nodes = draft.nodes.map(node => {
    const trace = workflowRunTrace[node.node_id] || {};
    const inputs = node.inputs.map(port => `<button class="workflow-port-handle input" data-action="workflowPortConnect" data-node-id="${esc(node.node_id)}" data-port="${esc(port.name)}" data-direction="input" title="Connect to ${esc(node.node_id)}.${esc(port.name)} (${esc(port.data_type)})"><i></i><span>${esc(port.name)}:${esc(port.data_type)}</span></button>`).join('');
    const outputs = node.outputs.map(port => `<button class="workflow-port-handle output${workflowConnectionStart?.node === node.node_id && workflowConnectionStart?.port === port.name ? ' connecting' : ''}" data-action="workflowPortConnect" data-node-id="${esc(node.node_id)}" data-port="${esc(port.name)}" data-direction="output" title="Start connection from ${esc(node.node_id)}.${esc(port.name)} (${esc(port.data_type)})"><span>${esc(port.name)}:${esc(port.data_type)}</span><i></i></button>`).join('');
    return `<article class="workflow-editor-node kind-${esc(node.kind)} trace-${esc(trace.state || 'idle')}${node.node_id === studioSelectedNode ? ' selected' : ''}" data-node-id="${esc(node.node_id)}" data-workflow-x="${esc(finiteLayoutText((node.position?.x ?? 40) * workflowScale, -20000, 20000, 40))}" data-workflow-y="${esc(finiteLayoutText((node.position?.y ?? 40) * workflowScale, -20000, 20000, 40))}" draggable="true"><div class="workflow-node-ports inputs">${inputs}</div><button class="workflow-node-body" data-action="workflowSelectNode" data-node-id="${esc(node.node_id)}" aria-pressed="${node.node_id === studioSelectedNode}" aria-label="Edit ${esc(node.kind)} node ${esc(node.node_id)}"><em>${esc(node.kind)}</em><strong>${esc(node.node_id)}</strong><span>${esc(node.executor_binding_id)}</span><small>${number(node.inputs.length)} in · ${number(node.outputs.length)} out · ${number(node.timeout_seconds)}s</small>${trace.state ? `<mark>${esc(trace.state)}${trace.duration_ms != null ? ` · ${number(trace.duration_ms)}ms` : ''}</mark>` : ''}</button><div class="workflow-node-ports outputs">${outputs}</div></article>`;
  }).join('');
  const edges = draft.edges.map((edge, edgeIndex) => `<li><b>${esc(edge.source_node)}.${esc(edge.source_port)}</b><span>→</span><b>${esc(edge.target_node)}.${esc(edge.target_port)}</b><small>${esc(edge.condition)}</small><button class="danger-action" data-action="workflowRemoveEdge" data-index="${edgeIndex}" aria-label="Remove edge ${esc(edge.source_node)} to ${esc(edge.target_node)}">Remove</button></li>`).join('');
  const sourceEndpoints = draft.nodes.flatMap(node => node.outputs.map(port => `<option value="${esc(`${node.node_id}|${port.name}`)}">${esc(node.node_id)} · ${esc(port.name)}:${esc(port.data_type)}</option>`)).join('');
  const targetEndpoints = draft.nodes.flatMap(node => node.inputs.map(port => `<option value="${esc(`${node.node_id}|${port.name}`)}">${esc(node.node_id)} · ${esc(port.name)}:${esc(port.data_type)}</option>`)).join('');
  const index = draft.nodes.indexOf(selected);
  const portTypes = ['json', 'string', 'integer', 'number', 'boolean', 'object', 'array'];
  const portRows = direction => selected[direction].map((port, portIndex) => `<div class="workflow-port-row"><input data-workflow-port-field="name" data-direction="${direction}" data-index="${portIndex}" value="${esc(port.name)}" aria-label="${direction} port name"><select data-workflow-port-field="data_type" data-direction="${direction}" data-index="${portIndex}" aria-label="${direction} port type">${portTypes.map(type => `<option value="${type}" ${port.data_type === type ? 'selected' : ''}>${type}</option>`).join('')}</select><label title="Required port"><input type="checkbox" data-workflow-port-field="required" data-direction="${direction}" data-index="${portIndex}" ${port.required ? 'checked' : ''}> required</label><button class="danger-action" data-action="workflowRemovePort" data-direction="${direction}" data-index="${portIndex}" ${selected[direction].length <= 1 ? 'disabled' : ''}>Remove</button></div>`).join('');
  const inspector = selected ? `<div class="workflow-node-inspector" data-workflow-inspector><h3>Node inspector</h3><div class="studio-guided-grid"><label><span>Node ID</span><input data-workflow-field="node_id" value="${esc(selected.node_id)}"></label><label><span>Node kind</span><select data-workflow-field="kind"><option value="task" ${selected.kind === 'task' ? 'selected' : ''}>Task</option><option value="validation" ${selected.kind === 'validation' ? 'selected' : ''}>Validation</option><option value="approval" ${selected.kind === 'approval' ? 'selected' : ''}>Approval</option><option value="branch" ${selected.kind === 'branch' ? 'selected' : ''}>Binary branch</option><option value="join" ${selected.kind === 'join' ? 'selected' : ''}>Join / merge</option></select></label></div><label><span>Executor binding</span><input data-workflow-field="executor_binding_id" value="${esc(selected.executor_binding_id)}"></label><label><span>Effect grant IDs</span><input data-workflow-field="effect_grant_ids" value="${esc(csv(selected.effect_grant_ids))}"></label><div class="studio-guided-grid"><label><span>Timeout seconds</span><input type="number" min="1" max="3600" data-workflow-field="timeout_seconds" value="${number(selected.timeout_seconds)}"></label><label><span>Retry limit</span><input type="number" min="0" max="10" data-workflow-field="retry_limit" value="${number(selected.retry_limit)}"></label><label><span>Failure policy</span><select data-workflow-field="failure_policy"><option value="fail-closed" ${selected.failure_policy === 'fail-closed' ? 'selected' : ''}>Fail closed</option><option value="continue" ${selected.failure_policy === 'continue' ? 'selected' : ''}>Continue</option></select></label></div><label class="studio-checkbox"><input type="checkbox" data-workflow-field="approval_required" ${selected.approval_required ? 'checked' : ''}> Require governed human approval</label><label><span>Executor configuration (canonical JSON object)</span><textarea rows="4" data-workflow-field="config" spellcheck="false">${esc(JSON.stringify(selected.config || {}, null, 2))}</textarea></label><div class="workflow-port-editor"><section><b>Inputs</b>${portRows('inputs')}<button data-action="workflowAddPort" data-direction="inputs">Add input</button></section><section><b>Outputs</b>${portRows('outputs')}<button data-action="workflowAddPort" data-direction="outputs">Add output</button></section></div><div class="studio-inline-actions"><button data-action="workflowMoveNode" data-delta="-1" ${index === 0 ? 'disabled' : ''}>Move earlier</button><button data-action="workflowMoveNode" data-delta="1" ${index === draft.nodes.length - 1 ? 'disabled' : ''}>Move later</button><button class="danger-action" data-action="workflowRemoveNode" ${draft.nodes.length <= 1 ? 'disabled' : ''}>Remove node</button></div></div>` : '';
  return `<div class="studio-editor-tabs" role="tablist" aria-label="Workflow editor view"><button role="tab" aria-selected="true" data-action="studioEditorTab" data-tab="visual">Visual graph</button><button role="tab" aria-selected="false" data-action="studioEditorTab" data-tab="json">Canonical JSON</button></div><section class="studio-editor-panel" data-studio-panel="visual"><div class="workflow-editor-layout"><aside class="workflow-palette" aria-label="Node palette"><b>Node palette</b><button draggable="true" data-action="workflowAddNode" data-node-template="task">Task node</button><button draggable="true" data-action="workflowAddNode" data-node-template="validation">Validation step</button><button draggable="true" data-action="workflowAddNode" data-node-template="approval">Approval gate</button><button draggable="true" data-action="workflowAddNode" data-node-template="branch">Binary branch</button><button draggable="true" data-action="workflowAddNode" data-node-template="join">Join / merge</button><p>Branch nodes require truthy and falsy edges from one boolean output. Join nodes wait for at least two predecessors and merge only present optional inputs.</p></aside><div><div class="workflow-editor-canvas" data-workflow-editor-canvas data-control-id="workflow-canvas" role="application" tabindex="0" aria-label="Typed workflow canvas. Drop node types here or use palette buttons.">${nodes}</div><div class="workflow-edge-editor"><b>Typed edges</b><div><select data-edge-source-endpoint aria-label="Source output port">${sourceEndpoints}</select><select data-edge-target-endpoint aria-label="Target input port">${targetEndpoints}</select><select data-edge-condition aria-label="Closed edge condition"><option value="always">always</option><option value="source-present">source-present</option><option value="source-truthy">source-truthy</option><option value="source-falsy">source-falsy</option><option value="never">never</option></select><button data-action="workflowConnectNodes">Connect</button></div><ol>${edges || '<li>No edges. Connect exact typed ports to define data flow.</li>'}</ol></div></div>${inspector}</div><div class="studio-validation ${validation.valid ? 'passed' : 'failed'}" data-studio-validation role="status"><b>${validation.valid ? 'Typed workflow is structurally valid' : `${validation.issues.length} structural issue(s)`}</b>${validation.issues.map(issue => `<span>${esc(issue)}</span>`).join('')}</div></section><section class="studio-editor-panel" data-studio-panel="json" hidden><label class="modal-field"><span>Canonical synchronized JSON</span><textarea id="studio-draft-json" rows="24" spellcheck="false">${esc(JSON.stringify(draft, null, 2))}</textarea></label><button data-action="studioApplyJson">Apply JSON to visual editor</button></section>`;
}

function skillEditorHtml(draft) {
  const validation = studioEditors.validateSkill(draft); const files = draft.editor_files || {};
  if (!Object.hasOwn(files, studioActiveFile)) studioActiveFile = Object.keys(files)[0] || 'SKILL.md';
  const tree = Object.keys(files).sort().map(path => `<button data-action="skillSelectFile" data-file-path="${esc(path)}" aria-pressed="${path === studioActiveFile}" class="${path === studioActiveFile ? 'selected' : ''}"><span>${path.includes('/') ? '└' : '●'}</span>${esc(path)}</button>`).join('');
  const history = state.studioHistory.filter(item => item.kind === 'skill').slice(0, 12).map(item => `<li><b>${esc(item.operation)}</b><span>${esc(item.status)} · ${esc(item.revision || 'revision pending')}</span><small>${esc(item.at)}</small></li>`).join('');
  const baseline = studioSourceRecord ? `Editing as a new immutable revision of ${studioSourceRecord.id || studioSourceRecord.label}. Source bytes are not silently overwritten.` : 'New package. Every file will be written to a bounded project-owned staging tree before admission.';
  return `<div class="skill-editor-layout"><aside class="skill-file-tree" aria-label="Skill package files"><header><b>Package files</b><small>${number(Object.keys(files).length)} files</small></header>${tree}<div class="studio-inline-actions"><button data-action="skillAddFile" data-file-kind="contract">+ Contract</button><button data-action="skillAddFile" data-file-kind="test">+ Test</button><button data-action="skillAddFile" data-file-kind="resource">+ Resource</button></div></aside><section class="skill-text-editor"><header><div><b>${esc(studioActiveFile)}</b><small>UTF-8 text · bounded package-relative path</small></div><button class="danger-action" data-action="skillRemoveFile" ${['SKILL.md', 'capability.json', 'skill.yaml'].includes(studioActiveFile) ? 'disabled' : ''}>Remove</button></header><textarea id="studio-skill-file" data-file-path="${esc(studioActiveFile)}" rows="25" spellcheck="false" aria-label="Edit ${esc(studioActiveFile)}">${esc(files[studioActiveFile] || '')}</textarea></section><aside class="skill-editor-side"><section class="studio-validation ${validation.valid ? 'passed' : 'failed'}" data-studio-validation role="status"><b>${validation.valid ? `${validation.file_count} files pass browser preflight` : `${validation.issues.length} package issue(s)`}</b>${validation.issues.map(issue => `<span>${esc(issue)}</span>`).join('')}</section><section class="skill-diff"><b>Revision diff</b><p>${esc(baseline)}</p><span>${studioSourceRecord ? 'Manifest fields and edited files will create a new candidate; inspect the backend receipt for its exact tree hash.' : 'All files are additions in this first revision.'}</span></section><section class="skill-history"><b>Recent lifecycle history</b><ol>${history || '<li>No Studio receipts recorded in this webview session.</li>'}</ol></section></aside></div>`;
}

function syncSkillEditorFile() {
  if (studioEditor?.kind !== 'skill') return;
  const input = document.getElementById('studio-skill-file');
  if (input?.dataset.filePath) studioEditor.draft.editor_files[input.dataset.filePath] = input.value;
}
function updateAgentValidationBox() {
  if (studioEditor?.kind !== 'agent') return;
  const specValidation = studioEditors.validateAgent(studioEditor.draft);
  const graphValidation = studioEditors.validateAgentBuilderGraph(currentAgentGraph(studioEditor.draft).graph);
  const validation = { ...specValidation, valid: specValidation.valid && graphValidation.valid, issues: [...specValidation.issues, ...graphValidation.issues] }; const box = document.querySelector('[data-studio-validation]');
  if (box) { box.classList.toggle('passed', validation.valid); box.classList.toggle('failed', !validation.valid); box.innerHTML = agentValidationHtml(validation); }
  const save = document.querySelector('[data-control-id="studio-save-candidate"]');
  if (save) { save.disabled = !validation.valid; save.title = validation.valid ? 'Save immutable candidate' : 'Resolve every structural issue before saving'; }
  const graphState = document.querySelector('.agent-graph-state');
  if (graphState) { graphState.classList.remove('persisted-verified'); graphState.classList.add('working-projection'); graphState.textContent = 'WORKING · PYTHON COMPILE REQUIRED'; }
}

function refreshStudioEditor(focusSelector = '') {
  const modal = document.querySelector('.studio-modal .modal-body'); if (!modal || !studioEditor) return;
  const editor = modal.querySelector('.studio-editor-root'); if (!editor) return;
  studioDraftDirty = true;
  persistWorkingStudioDraft();
  editor.innerHTML = studioEditor.kind === 'agent' ? agentEditorHtml(studioEditor.draft) : studioEditor.kind === 'workflow' ? workflowEditorHtml(studioEditor.draft) : skillEditorHtml(studioEditor.draft);
  upgradeAgentTopology(editor);
  if (studioEditor.kind === 'agent') updateAgentValidationBox();
  if (studioEditor.kind === 'workflow') { upgradeWorkflowCanvas(editor); drawWorkflowCanvasEdges(editor, studioEditor.draft); }
  if (focusSelector) editor.querySelector(focusSelector)?.focus();
}
function forkStudioCandidate() {
  if (!studioEditor || !studioVersionAllocation || !['agent', 'workflow', 'skill'].includes(studioEditor.kind)) return;
  const kind = studioEditor.kind; const identityKey = kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : 'skill_id';
  const source = structuredClone(studioVersionAllocation); const draft = structuredClone(studioEditor.draft);
  if (studioVersionAllocationProof && studioVersionProofRequestId) vscode.postMessage({ type: 'releaseStudioTrust', requestId: studioVersionProofRequestId, trustKind: 'version-allocation', proof: studioVersionAllocationProof });
  draft[identityKey] = `${String(source.identity || draft[identityKey] || '').replace(/-fork(?:-[0-9]+)?$/, '')}-fork`;
  draft.version = '1.0.0';
  if (Array.isArray(draft.grants)) draft.grants = draft.grants.map(item => ({ ...item, subject_id: draft[identityKey] }));
  if (Array.isArray(draft.bindings)) draft.bindings = draft.bindings.map(item => ({ ...item, subject_id: draft[identityKey] }));
  const independent = kind === 'skill' ? studioEditors.synchronizeSkillIdentityFiles(draft) : draft;
  studioVersionAllocation = null; studioVersionAllocationProof = null; studioVersionProofRequestId = null; studioWorkingSourceBinding = null; studioPendingSkillPackage = null; studioSourceProofRequestId = null; studioSourceRecord = null;
  openStudioDraftModal(kind, independent); studioDraftDirty = true; persistWorkingStudioDraft();
  document.querySelector('.studio-editor-root')?.insertAdjacentHTML('beforebegin', `<div class="identity-warning" role="status"><div><span>INDEPENDENT FORK DRAFT</span><strong>Content copied from ${esc(source.identity)} @ ${esc(source.source_version)}.</strong><p>The predecessor hashes are context only and grant no lineage, allocation, admission, or authority. This draft must use a distinct identity at version 1.0.0 and pass the physical identity-absence gate before creation.</p></div></div>`);
}
function studioDraftModal(kind, seed = null) {
  const templates = {
    agent: { agent_id: 'agent:my-agent', version: '1.0.0', project_id: 'project:current', owner: 'human:owner', harness_id: 'harness:px', instructions: 'Operate only inside the supplied task and effect grants.\n', capability_binding_ids: ['binding:my-agent'], effect_grant_ids: ['grant:my-agent'], required_tests: ['identity', 'sandbox'], grants: [{ grant_id: 'grant:my-agent', subject_id: 'agent:my-agent', effects: ['read'], scope_roots: ['workspace:current'], approved_by: 'human:owner', evidence_refs: ['receipt:human-approval'], state: 'admitted' }], bindings: [{ binding_id: 'binding:my-agent', subject_kind: 'agent', subject_id: 'agent:my-agent', capability_id: 'capability:local-worker', capability_version: '1.0.0', effect_grant_ids: ['grant:my-agent'], credential_namespace: null, cost_policy: 'non-billable', egress_policy: 'deny', state: 'admitted', evidence_refs: ['receipt:human-approval'] }], lifecycle: 'draft' },
    workflow: { workflow_id: 'workflow:my-workflow', version: '1.0.0', owner: 'human:owner', nodes: [{ node_id: 'step:one', kind: 'task', config: {}, executor_binding_id: 'binding:my-workflow', inputs: [{ name: 'value', data_type: 'string', required: true }], outputs: [{ name: 'value', data_type: 'string', required: true }], effect_grant_ids: ['grant:my-workflow'], failure_policy: 'fail-closed', timeout_seconds: 30, retry_limit: 0, approval_required: false }], edges: [], grants: [{ grant_id: 'grant:my-workflow', subject_id: 'workflow:my-workflow', effects: ['read'], scope_roots: ['workspace:current'], approved_by: 'human:owner', evidence_refs: ['receipt:human-approval'], state: 'admitted' }], bindings: [{ binding_id: 'binding:my-workflow', subject_kind: 'workflow', subject_id: 'workflow:my-workflow', capability_id: 'capability:identity', capability_version: '1.0.0', effect_grant_ids: ['grant:my-workflow'], credential_namespace: null, cost_policy: 'non-billable', egress_policy: 'deny', state: 'admitted', evidence_refs: ['receipt:human-approval'] }], executor_adapters: { 'binding:my-workflow': 'identity' }, run_inputs: { 'step:one.value': 'bounded input' }, lifecycle: 'draft' },
    skill: { skill_id: 'my-skill', version: '1.0.0', owner: 'human:owner', triggers: ['explicit matching task'], non_triggers: ['unrelated task'], permissions: ['read_local'], effects: ['read'], resources: ['resources/README.md'], contracts: ['contracts/input.schema.json'], tests: ['tests/contract.json'], provenance: { source: 'user-selected-directory' }, lifecycle: 'draft' }
  };
  let template = seed && typeof seed === 'object' ? { ...templates[kind], ...seed } : templates[kind]; if (!template) return;
  if (kind === 'workflow') template = studioEditors.normalizeWorkflow(template);
  if (kind === 'skill') template = studioEditors.normalizeSkill(template);
  studioEditor = { kind, draft: template };
  if (kind === 'workflow') reconcileWorkflowTraceEditor(template);
  if (kind === 'workflow') { workflowConnectionStart = null; workflowScale = 1; }
  studioSelectedNode = kind === 'workflow' ? template.nodes[0]?.node_id || '' : '';
  studioActiveFile = 'SKILL.md';
  const identityKey = kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : 'skill_id';
  const topology = kind === 'workflow' ? `<section class="studio-topology" aria-label="Workflow topology preview"><b>Executable topology</b>${template.nodes.map(node => `<article><strong>${esc(node.node_id)}</strong><span>${esc(node.inputs.map(port => `${port.name}:${port.data_type}`).join(', '))} → ${esc(node.outputs.map(port => `${port.name}:${port.data_type}`).join(', '))}</span><small>${esc(node.executor_binding_id)} · ${number(node.timeout_seconds)}s · ${number(node.retry_limit)} retries</small></article>`).join('')}</section>` : '';
  showModal(`${kind[0].toUpperCase()}${kind.slice(1)} Studio`, 'GUIDED EDITOR · VERSIONED CANDIDATE · AUTHORITY SEPARATED', `<p>The guided fields and canonical machine definition describe one immutable revision. Saving never implies admission, activation, promotion, or execution.</p><div class="studio-guided-grid"><label><span>Identity</span><input id="studio-identity" value="${esc(template[identityKey])}" autocomplete="off"></label><label><span>Version</span><input id="studio-version" value="${esc(template.version)}" autocomplete="off"></label><label><span>Owner</span><input id="studio-owner" value="${esc(template.owner)}" autocomplete="off"></label></div>${topology}<details class="studio-machine-editor" open><summary>Machine definition, grants, tests, ports, and policies</summary><label class="modal-field"><span>Canonical JSON</span><textarea id="studio-draft-json" rows="22" spellcheck="false">${esc(JSON.stringify(template, null, 2))}</textarea></label></details><p class="fine-print">${kind === 'skill' ? 'After Save, the host asks you to select the source package. The selected tree is link-checked, attested, copied, and rehashed.' : 'Authority records are authenticated separately. Lifecycle controls appear after this revision is saved.'}</p>`, `<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitStudioDraft" data-kind="${esc(kind)}" data-identity-key="${identityKey}">Save immutable candidate</button>`, 'wide-modal');
}

function studioPayload(control) {
  const input = document.getElementById('studio-draft-json');
  let payload = JSON.parse(input?.value || '');
  const identityKey = control.dataset.identityKey;
  if (identityKey) payload[identityKey] = document.getElementById('studio-identity')?.value?.trim();
  payload.version = document.getElementById('studio-version')?.value?.trim();
  payload.owner = document.getElementById('studio-owner')?.value?.trim();
  if (identityKey && Array.isArray(payload.grants)) payload.grants = payload.grants.map(item => ({ ...item, subject_id: payload[identityKey] }));
  if (identityKey && Array.isArray(payload.bindings)) payload.bindings = payload.bindings.map(item => ({ ...item, subject_id: payload[identityKey] }));
  if (control.dataset.kind === 'skill') payload = studioEditors.synchronizeSkillIdentityFiles(payload);
  return payload;
}

function openStudioDraftModal(kind, seed = null) {
  const templates = {
    agent: { agent_id: 'agent:my-agent', version: '1.0.0', project_id: 'project:current', owner: 'human:owner', harness_id: 'harness:px', instructions: 'Operate only inside the supplied task and effect grants.\n', capability_binding_ids: ['binding:my-agent'], effect_grant_ids: ['grant:my-agent'], required_tests: ['identity', 'sandbox'], grants: [{ grant_id: 'grant:my-agent', subject_id: 'agent:my-agent', effects: ['read'], scope_roots: ['workspace:current'], approved_by: 'human:owner', evidence_refs: ['receipt:human-approval'], state: 'admitted' }], bindings: [{ binding_id: 'binding:my-agent', subject_kind: 'agent', subject_id: 'agent:my-agent', capability_id: 'capability:local-worker', capability_version: '1.0.0', effect_grant_ids: ['grant:my-agent'], credential_namespace: null, cost_policy: 'non-billable', egress_policy: 'deny', state: 'admitted', evidence_refs: ['receipt:human-approval'] }], lifecycle: 'draft' },
    workflow: { workflow_id: 'workflow:my-workflow', version: '1.0.0', owner: 'human:owner', nodes: [{ node_id: 'step:one', kind: 'task', config: {}, executor_binding_id: 'binding:my-workflow', inputs: [{ name: 'value', data_type: 'string', required: true }], outputs: [{ name: 'value', data_type: 'string', required: true }], effect_grant_ids: ['grant:my-workflow'], failure_policy: 'fail-closed', timeout_seconds: 30, retry_limit: 0, approval_required: false }], edges: [], grants: [{ grant_id: 'grant:my-workflow', subject_id: 'workflow:my-workflow', effects: ['read'], scope_roots: ['workspace:current'], approved_by: 'human:owner', evidence_refs: ['receipt:human-approval'], state: 'admitted' }], bindings: [{ binding_id: 'binding:my-workflow', subject_kind: 'workflow', subject_id: 'workflow:my-workflow', capability_id: 'capability:identity', capability_version: '1.0.0', effect_grant_ids: ['grant:my-workflow'], credential_namespace: null, cost_policy: 'non-billable', egress_policy: 'deny', state: 'admitted', evidence_refs: ['receipt:human-approval'] }], executor_adapters: { 'binding:my-workflow': 'identity' }, run_inputs: { 'step:one.value': 'bounded input' }, lifecycle: 'draft' },
    skill: { skill_id: 'my-skill', version: '1.0.0', owner: 'human:owner', triggers: ['explicit matching task'], non_triggers: ['unrelated task'], permissions: ['read_local'], effects: ['read'], resources: ['resources/README.md'], contracts: ['contracts/input.schema.json'], tests: ['tests/contract.json'], provenance: { source: 'studio-guided-editor' }, lifecycle: 'draft' }
  };
  let draft = seed && typeof seed === 'object' ? { ...templates[kind], ...seed } : templates[kind]; if (!draft) return;
  if (seed?.authority_definition_state === 'not-stored-with-revision') { draft.grants = []; draft.bindings = []; if (kind === 'workflow') { draft.executor_adapters = {}; draft.run_inputs = {}; } }
  if (kind === 'agent') { draft = studioEditors.normalizeAgent(draft); draft.lifecycle = 'draft'; agentPersistedGraph = studioEditors.validateAgentBuilderGraph(seed?.builder_graph).valid ? structuredClone(seed.builder_graph) : null; agentWorkingGraph = studioEditors.synchronizeAgentBuilderGraph(draft, agentPersistedGraph); draft.builder_graph = structuredClone(agentWorkingGraph); agentGraphDirty = false; agentConnectionStart = null; agentScale = 1; }
  if (kind === 'workflow') draft = studioEditors.normalizeWorkflow(draft);
  if (kind === 'skill') draft = studioEditors.prepareSkillCandidate(draft);
  if (kind === 'workflow') reconcileWorkflowTraceEditor(draft);
  studioEditor = { kind, draft }; studioDraftDirty = false; studioSelectedNode = kind === 'workflow' ? draft.nodes[0]?.node_id || '' : ''; agentSelectedSection = 'identity'; studioActiveFile = 'SKILL.md';
  const identityKey = kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : 'skill_id';
  let editor = kind === 'agent' ? agentEditorHtml(draft) : kind === 'workflow' ? workflowEditorHtml(draft) : skillEditorHtml(draft);
  if (kind === 'skill' && draft.package_missing_required_files?.length) editor = `<div class="identity-warning" role="alert"><div><span>ORIGINAL PACKAGE IS INCOMPLETE</span><strong>This source cannot become a PX candidate until its missing native files are explicitly authored.</strong><p>${esc(draft.package_missing_required_files.join(', '))}</p></div></div>${editor}`;
  const predecessorBound = Boolean(studioVersionAllocation);
  showModal(`${kind[0].toUpperCase()}${kind.slice(1)} Studio`, 'GUIDED EDITOR · VERSIONED CANDIDATE · AUTHORITY SEPARATED', `<p>The guided fields and canonical definition describe one immutable revision. Saving never implies admission, activation, promotion, or execution.</p><div class="studio-guided-grid"><label><span>Identity</span><input id="studio-identity" value="${esc(draft[identityKey])}" autocomplete="off" ${predecessorBound ? 'readonly aria-readonly="true"' : ''}></label><label><span>Version</span><input id="studio-version" value="${esc(draft.version)}" autocomplete="off" ${predecessorBound ? 'readonly aria-readonly="true"' : ''}></label><label><span>Owner</span><input id="studio-owner" value="${esc(draft.owner)}" autocomplete="off"></label></div><div class="studio-editor-root">${editor}</div><p class="fine-print">${kind === 'skill' ? 'The host materializes these UTF-8 files only inside the selected project’s governed Studio staging root, then link-checks, attests, copies, and rehashes the package.' : 'Authority records are authenticated separately. Lifecycle controls appear after this revision is saved.'}</p>`, `<button data-action="closeModal">Cancel</button>${predecessorBound ? '<button data-action="forkStudioCandidate">Fork content as independent candidate</button>' : ''}<button class="primary" data-action="submitStudioDraft" data-control-id="studio-save-candidate" data-kind="${esc(kind)}" data-identity-key="${identityKey}">Save immutable candidate</button>`, 'wide-modal studio-modal');
  if (seed && studioSourceRecord) {
    const imported = Boolean(studioSourceRecord.import_adapter);
    document.querySelector('.studio-editor-root')?.insertAdjacentHTML('beforebegin', `<div class="studio-revision-baseline" role="status"><b>${imported ? 'IMPORTED INTO AN INDEPENDENT STUDIO CANDIDATE' : 'EDITING AS A NEW IMMUTABLE REVISION'}</b><span>${esc(studioSourceRecord.label || studioSourceRecord.id || (imported ? 'source definition' : 'authenticated Studio revision'))} remains unchanged. Save will publish ${esc(draft[identityKey])} @ ${esc(draft.version)}${imported ? ' without claiming predecessor lineage or inherited authority.' : ' and preserve the prior revision.'}</span></div>`);
  }
  upgradeAgentTopology(document.querySelector('.studio-editor-root'));
  if (kind === 'agent' && !studioModelCatalog.length) vscode.postMessage({ type: 'listHostModels' });
  if (kind === 'workflow') {
    const editor = document.querySelector('.studio-editor-root');
    upgradeWorkflowCanvas(editor);
    drawWorkflowCanvasEdges(editor, draft);
  }
  if (kind === 'agent') updateAgentValidationBox();
  persistWorkingStudioDraft();
}

function beginStudioAuthoring(kind) {
  if (!['agent', 'workflow', 'skill'].includes(kind)) return false;
  studioSourceRecord = null;
  studioVersionAllocation = null;
  studioWorkingSourceBinding = null;
  studioVersionAllocationProof = null;
  studioAllocationRequest = null;
  studioSaveRequest = null;
  studioPackageRequest = null;
  studioPendingSkillPackage = null;
  if (!offerWorkingStudioDraft(kind)) openStudioDraftModal(kind);
  return true;
}

function studioKindForSurface(surface) {
  return ({ 'agent-studio': 'agent', 'workflow-studio': 'workflow', 'skill-studio': 'skill' })[surface] || null;
}

function workflowInputMatches(value, type) {
  return type === 'json' || (type === 'string' && typeof value === 'string') || (type === 'integer' && Number.isInteger(value)) || (type === 'number' && typeof value === 'number' && Number.isFinite(value)) || (type === 'boolean' && typeof value === 'boolean') || (type === 'object' && value && typeof value === 'object' && !Array.isArray(value)) || (type === 'array' && Array.isArray(value));
}

function studioEditorPayload(control) {
  if (control.dataset.kind === 'skill') syncSkillEditorFile();
  let payload = studioEditor?.kind === control.dataset.kind ? structuredClone(studioEditor.draft) : studioPayload(control);
  if (control.dataset.kind === 'workflow' && Array.isArray(payload.nodes)) {
    payload.editor_layout = Object.fromEntries(payload.nodes.map(node => [node.node_id, { x: Number(node.position?.x || 0), y: Number(node.position?.y || 0) }]));
    payload.nodes = payload.nodes.map(({ position: _position, ...node }) => node);
  }
  const identityKey = control.dataset.identityKey;
  if (identityKey) payload[identityKey] = document.getElementById('studio-identity')?.value?.trim();
  payload.version = document.getElementById('studio-version')?.value?.trim(); payload.owner = document.getElementById('studio-owner')?.value?.trim();
  if (control.dataset.kind === 'skill') payload = studioEditors.synchronizeSkillIdentityFiles(payload);
  if (studioVersionAllocation && (String(payload[identityKey] || '').trim().toLowerCase() !== studioVersionAllocation.identity || String(payload.version || '').trim().toLowerCase() !== studioVersionAllocation.candidate_version)) throw new Error('Editing an immutable predecessor cannot change its candidate identity or version. Use the explicit independent fork action instead.');
  if (identityKey && Array.isArray(payload.grants)) payload.grants = payload.grants.map(item => ({ ...item, subject_id: payload[identityKey] }));
  if (identityKey && Array.isArray(payload.bindings)) payload.bindings = payload.bindings.map(item => ({ ...item, subject_id: payload[identityKey] }));
  if (control.dataset.kind === 'agent') {
    const { graph } = currentAgentGraph(payload); const layout = agentLayoutMap(payload, graph);
    payload = studioEditors.agentCandidatePayload(payload, layout, graph);
  }
  if (studioVersionAllocation) {
    if (typeof studioVersionAllocationProof !== 'string' || !studioVersionAllocationProof) throw new Error('The host version-allocation proof is unavailable. Reload the exact predecessor before saving.');
    payload.version_allocation = structuredClone(studioVersionAllocation);
    payload.version_allocation_proof = studioVersionAllocationProof;
  }
  return payload;
}

function studioOperationSucceeded(kind, operation, result) {
  const record = result?.record && typeof result.record === 'object' ? result.record : result;
  if (!record || typeof record !== 'object') return false;
  if (operation === 'test') return record.passed === true;
  if (operation === 'admit' || (kind === 'workflow' && operation === 'validate')) return record.decision === 'admitted';
  if (operation === 'validate') return record.passed === true;
  if (operation === 'preview') return record.eligible === true;
  if (operation === 'dry-run') return record.effects_executed === false && (record.runnable === true || record.eligible === true || record.decision === 'runnable' || record.status === 'ready');
  if (operation === 'promote') return ['promoted', 'canonical', 'succeeded'].includes(String(record.state || record.status || record.decision || '').toLowerCase());
  if (operation === 'rollback') return String(record.state || record.status || '').toLowerCase() === 'rolled-back';
  if (operation === 'run') return ['succeeded', 'completed'].includes(String(record.runtime_state || record.run_outcome || record.state || record.status || '').toLowerCase());
  if (operation === 'start' || operation === 'resume') return Boolean(record.run_id) && ['queued', 'running', 'prepared'].includes(String(record.state || record.runtime_state || record.status || '').toLowerCase());
  if (operation === 'create') return Boolean(record.agent_id || record.workflow_id || record.skill_id || record.path || record.record_path || record.sha256);
  if (operation === 'register-authority') return record.status === 'registered' && record.authenticated === true;
  if (operation === 'approve') return Boolean(record.approval_id);
  return !/fail|error|block|reject|invalid/i.test(String(record.status || record.state || record.decision || ''));
}

function studioLifecycleModal(kind, operation, result) {
  const succeeded = studioOperationSucceeded(kind, operation, result);
  const record = result?.record && typeof result.record === 'object' ? result.record : result;
  const workflowNeedsApproval = studioSession?.kind === 'workflow' && (studioSession.payload.nodes || []).some(node => node.approval_required && !studioSession.payload.approvals?.[node.node_id]);
  const transitions = {
    agent: { create: [['test', 'Run structural preflight']], test: [['register-authority', 'Register authority']], 'register-authority': [['admit', 'Admit revision']], admit: [['preview', 'Preview exact execution'], ['start', 'Start admitted agent']], preview: [['start', 'Start admitted agent']] },
    workflow: { create: [['register-authority', 'Register authority']], 'register-authority': [['validate', 'Validate + admit']], validate: [['dry-run', 'Preview execution plan']], 'dry-run': workflowNeedsApproval ? [['approve', 'Approve next required node']] : [['start', 'Start workflow']], approve: workflowNeedsApproval ? [['approve', 'Approve next required node']] : [['start', 'Start workflow']] },
    skill: { create: [['validate', 'Validate package']], validate: [['admit', 'Admit package']], admit: [['promote', 'Promote canonical']] }
  };
  let actions = succeeded ? transitions[kind]?.[operation] || [] : [];
  if (kind === 'skill' && operation === 'promote' && record?.rollback_available === true && record?.promotion_receipt_relative) actions = [['rollback', 'Rollback to retained prior canonical revision']];
  const buttons = actions.map(([next, label]) => `<button class="${['admit', 'promote', 'start'].includes(next) ? 'primary' : ''}" data-action="studioLifecycle" data-kind="${esc(kind)}" data-operation="${esc(next)}">${esc(label)}</button>`).join('');
  const runOutput = ['start', 'run', 'status', 'resume'].includes(operation) ? `<section class="studio-run-output"><b>Runtime outcome</b><p>${esc(record?.state || record?.runtime_state || record?.run_outcome || record?.status || (operation === 'start' ? 'started' : 'unknown'))}</p>${record?.output ? `<pre>${esc(JSON.stringify(record.output, null, 2))}</pre>` : ''}${record?.error ? `<pre>${esc(JSON.stringify(record.error, null, 2))}</pre>` : ''}${record?.run_id ? studioRunControls(kind, record) : ''}</section>` : '';
  const checkLabels = new Map(agentStructuralChecks.map(check => [check.id, check.label]));
  const preflightResults = kind === 'agent' && operation === 'test' && Array.isArray(record?.test_results)
    ? `<section class="agent-preflight-results"><b>Structural preflight results</b>${record.test_results.map(item => `<article class="${item.known === true && item.passed === true ? 'passed' : 'failed'}"><span aria-hidden="true">${item.known === true && item.passed === true ? '✓' : '×'}</span><div><strong>${esc(checkLabels.get(item.test_id) || item.test_id || 'unknown check')}</strong><code>${esc(item.test_id || 'unknown')}</code><p>${esc(item.reason || (item.passed ? 'Passed.' : 'Did not pass.'))}</p></div></article>`).join('')}</section>`
    : '';
  showInformationModal(`${kind[0].toUpperCase()}${kind.slice(1)} Studio`, `${operation.toUpperCase()} RESULT · ${succeeded ? 'ACCEPTED' : 'NOT ACCEPTED'}`, result, `<p>Lifecycle dimensions remain separate. A next action appears only when this operation's exact success field passed.</p>${preflightResults}${runOutput}${humanRecord(result)}${buttons ? `<div class="action-grid studio-actions">${buttons}</div>` : '<p class="modal-note">No next lifecycle action is eligible from this result.</p>'}`);
}

function resolvedStudioPreviewModal(kind, result) {
  const record = result?.record && typeof result.record === 'object' ? result.record : result;
  const subject = record?.[kind === 'agent' ? 'agent_id' : 'workflow_id'] || 'unknown subject';
  const safe = record?.effects_executed === false;
  const eligible = kind === 'agent' ? record?.eligible === true : ['ready', 'eligible'].includes(String(record?.status || ''));
  const authorityRows = Object.entries(record?.authority_record_hashes || {}).map(([key, value]) => `<li><code>${esc(key)}</code><span class="mono">${esc(value)}</span></li>`).join('');
  let body;
  if (kind === 'agent') {
    const blockers = (record?.blockers || []).map(item => `<li>${esc(item)}</li>`).join('');
    const tools = (record?.tools || []).map(tool => `<article class="catalog-row"><div><strong>${esc(tool.tool_name || tool.binding_id)}</strong><small class="mono">${esc(tool.binding_id)} @ ${esc(tool.capability_version || 'unknown')}</small></div><span>${esc((tool.effect_grant_ids || []).join(', ') || 'no grants')}</span></article>`).join('');
    body = `<div class="identity-warning ${eligible ? '' : 'blocked'}" role="status"><div><span>${eligible ? 'RESOLVED EXECUTION ELIGIBLE' : 'RESOLVED EXECUTION BLOCKED'}</span><strong>${esc(subject)} @ ${esc(record?.version || 'unknown')}</strong><p>${safe ? 'Preview executed no effects. Codex / VS Code host authority remains retained.' : 'The preview did not prove a no-effect boundary.'}</p></div></div><div class="readiness-lanes"><section><b>Model + harness</b><dl class="modal-detail"><div><dt>Provider</dt><dd>${esc(record?.model?.provider || 'unresolved')}</dd></div><div><dt>Model</dt><dd>${esc(record?.model?.model_id || 'unresolved')}</dd></div><div><dt>Harness</dt><dd>${esc(record?.harness_id || 'unresolved')}</dd></div></dl></section><section><b>Blocking conditions</b><ul>${blockers || '<li>None</li>'}</ul></section></div><h3>Resolved tools and grants</h3><div class="catalog-list">${tools || '<p class="empty-state">No host tools are bound.</p>'}</div><div class="readiness-lanes"><section><b>Memory bindings</b><p>${esc((record?.memory_binding_ids || []).join(', ') || 'none')}</p></section><section><b>Handoff agents</b><p>${esc((record?.handoff_agent_ids || []).join(', ') || 'none')}</p></section></div><h3>Input contract</h3><pre class="modal-readout">${esc(JSON.stringify(record?.input_schema || {}, null, 2))}</pre><h3>Output contract</h3><pre class="modal-readout">${esc(JSON.stringify(record?.output_schema || {}, null, 2))}</pre><h3>Authority records used</h3><ul class="diagnostic-trace-list">${authorityRows || '<li>No authority records resolved.</li>'}</ul>`;
  } else {
    const nodes = (record?.nodes || []).map(node => `<article class="catalog-row"><div><strong>${esc(node.node_id)}</strong><small>${esc(node.kind)} · ${esc(node.binding_id)}</small></div><span>${esc((node.effects || []).join(', ') || 'no effects')}</span><small>${node.approval_required ? 'Human approval required' : 'No approval gate'} · ${number(node.timeout_seconds)}s · ${number(node.retry_limit)} retries</small></article>`).join('');
    body = `<div class="identity-warning ${eligible ? '' : 'blocked'}" role="status"><div><span>${eligible ? 'RESOLVED PLAN READY' : 'RESOLVED PLAN BLOCKED'}</span><strong>${esc(subject)} @ ${esc(record?.version || 'unknown')}</strong><p>${safe ? 'Dry-run executed no effects.' : 'The dry-run did not prove a no-effect boundary.'}</p></div></div><p><b>Topological order:</b> ${esc((record?.topological_order || []).join(' → ') || 'unavailable')}</p><div class="catalog-list">${nodes || '<p class="empty-state">No resolved workflow nodes.</p>'}</div><h3>Authority records used</h3><ul class="diagnostic-trace-list">${authorityRows || '<li>No authority records resolved.</li>'}</ul>`;
  }
  const workflowNeedsApproval = kind === 'workflow' && studioSession?.kind === 'workflow'
    && (studioSession.payload.nodes || []).some(node => node.approval_required && !studioSession.payload.approvals?.[node.node_id]);
  const nextOperation = workflowNeedsApproval ? 'approve' : 'start';
  const nextLabel = workflowNeedsApproval ? 'Approve next required node' : `Start exact admitted ${kind}`;
  const startAction = safe && eligible ? `<div class="action-grid studio-actions"><button class="primary" data-action="studioLifecycle" data-kind="${esc(kind)}" data-operation="${nextOperation}">${esc(nextLabel)}</button></div>` : '<p class="modal-note">Execution remains blocked until the exact no-effect preview is eligible.</p>';
  showInformationModal(`${kind === 'agent' ? 'Execution' : 'Workflow'} preview · ${subject}`, `REQUEST-BOUND · ${safe ? 'NO EFFECTS' : 'UNVERIFIED EFFECT BOUNDARY'} · ${eligible ? 'ELIGIBLE' : 'BLOCKED'}`, result, `${body}${startAction}`);
}

function studioRunControls(kind, run) {
  const stateName = String(run?.state || run?.runtime_state || 'unknown');
  const runId = String(run?.run_id || '');
  if (!runId) return '';
  const subject = String(run?.subject_id || run?.agent_id || run?.workflow_id || '');
  const version = String(run?.version || '');
  const identity = ` data-subject-id="${esc(subject)}" data-version="${esc(version)}"`;
  const controls = [`<button data-action="studioRunAction" data-kind="${esc(kind)}" data-operation="status" data-run-id="${esc(runId)}"${identity}>Refresh</button>`];
  if (stateName === 'queued') controls.push(`<button class="danger" data-action="studioRunAction" data-kind="${esc(kind)}" data-operation="cancel" data-run-id="${esc(runId)}">Cancel</button>`);
  if (stateName === 'running') {
    controls.push(`<button data-action="studioRunAction" data-kind="${esc(kind)}" data-operation="pause" data-run-id="${esc(runId)}">Request pause</button>`);
    controls.push(`<button class="danger" data-action="studioRunAction" data-kind="${esc(kind)}" data-operation="cancel" data-run-id="${esc(runId)}">Cancel</button>`);
    controls.push(`<button class="danger" data-action="studioRunAction" data-kind="${esc(kind)}" data-operation="stop" data-run-id="${esc(runId)}">Bounded stop</button>`);
  }
  if (['paused', 'interrupted'].includes(stateName)) controls.push(`<button class="primary" data-action="studioRunAction" data-kind="${esc(kind)}" data-operation="resume" data-run-id="${esc(runId)}"${identity}>Resume</button>`);
  return `<div class="action-grid studio-actions">${controls.join('')}</div>`;
}

function exactStudioCatalogPayload(kind, subject, version) {
  const catalog = state.catalogs[kind === 'agent' ? 'agents' : 'workflows'];
  const item = catalog?.items?.find(row => row.status === 'admitted' && row.details?.lifecycle_authentication?.authenticated === true && String(row.details?.[kind === 'agent' ? 'agent_id' : 'workflow_id'] || '') === subject && String(row.details?.version || '') === version);
  if (!item) return null;
  return kind === 'agent' ? studioEditors.normalizeAgent(item.details) : studioEditors.normalizeWorkflow(item.details);
}

function importCatalogDefinitionIntoStudio(kind, record) {
  const details = record?.details || record || {};
  const rawIdentity = String(details[kind === 'agent' ? 'agent_id' : 'workflow_id'] || record?.id || `${kind}:imported-definition`).trim().toLowerCase();
  let identity = rawIdentity.replace(/[^a-z0-9._:-]+/g, '-').replace(/^-+|-+$/g, '');
  if (!identity.includes(':')) identity = `${kind}:${identity || 'imported-definition'}`;
  const token = identity.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(-72) || `imported-${kind}`;
  const owner = String(details.owner || record?.owner || 'human:vscode-local-user');
  const source = {
    catalog_kind: String(record?._catalogKind || `${kind}s`), record_id: String(record?._catalogRecordId || record?.id || ''),
    source_kind: String(record?.kind || details.catalog_kind || 'definition'), source_status: String(record?.status || details.lifecycle_state || 'declared'),
    source_path: String(record?.path || details.path || ''), imported_as_independent_candidate: true
  };
  studioSourceRecord = { ...record, label: record?.label || identity, import_adapter: source };
  studioVersionAllocation = null; studioWorkingSourceBinding = null; studioVersionAllocationProof = null; studioSaveRequest = null;
  if (kind === 'agent') {
    const grantId = `grant:${token}`; const bindingId = `binding:${token}`;
    openStudioDraftModal('agent', {
      agent_id: identity, version: '1.0.0', project_id: 'project:current', owner, harness_id: 'harness:px',
      instructions: String(details.description || record?.summary || `Adapt ${record?.label || identity} into a bounded executable Studio agent.`),
      capability_binding_ids: [bindingId], effect_grant_ids: [grantId], required_tests: ['identity', 'sandbox'],
      grants: [{ grant_id: grantId, subject_id: identity, effects: ['read'], scope_roots: ['workspace:current'], approved_by: owner, evidence_refs: ['receipt:studio-import-review'], state: 'admitted' }],
      bindings: [{ binding_id: bindingId, subject_kind: 'agent', subject_id: identity, capability_id: 'capability:identity', capability_version: '1.0.0', effect_grant_ids: [grantId], credential_namespace: null, cost_policy: 'non-billable', egress_policy: 'deny', state: 'admitted', evidence_refs: ['receipt:studio-import-review'] }],
      source_definition: structuredClone(details), source_import: source, lifecycle: 'draft'
    });
    return;
  }
  const grantId = `grant:${token}`; const bindingId = `binding:${token}`;
  openStudioDraftModal('workflow', {
    workflow_id: identity, version: '1.0.0', owner,
    nodes: [{ node_id: 'step:imported-definition', kind: 'task', config: {}, executor_binding_id: bindingId, inputs: [{ name: 'value', data_type: 'string', required: true }], outputs: [{ name: 'value', data_type: 'string', required: true }], effect_grant_ids: [grantId], failure_policy: 'fail-closed', timeout_seconds: 30, retry_limit: 0, approval_required: false, position: { x: 120, y: 160 } }],
    edges: [],
    grants: [{ grant_id: grantId, subject_id: identity, effects: ['read'], scope_roots: ['workspace:current'], approved_by: owner, evidence_refs: ['receipt:studio-import-review'], state: 'admitted' }],
    bindings: [{ binding_id: bindingId, subject_kind: 'workflow', subject_id: identity, capability_id: 'capability:identity', capability_version: '1.0.0', effect_grant_ids: [grantId], credential_namespace: null, cost_policy: 'non-billable', egress_policy: 'deny', state: 'admitted', evidence_refs: ['receipt:studio-import-review'] }],
    executor_adapters: { [bindingId]: 'identity' }, run_inputs: { 'step:imported-definition.value': 'bounded input' },
    source_definition: structuredClone(details), source_import: source, lifecycle: 'draft'
  });
}

function studioRunsModal(kind, result) {
  const runs = Array.isArray(result?.runs) ? result.runs : result?.run_id ? [result] : [];
  const rows = runs.map(run => `<article class="catalog-row studio-run-row"><div><strong>${esc(run.subject_id || run.agent_id || run.workflow_id || 'Studio run')}</strong><small class="mono">${esc(run.run_id || 'unknown run')}</small><small>${esc(run.updated_utc || run.created_utc || 'time unavailable')} · sequence ${number(run.sequence || run.control_sequence || 0)}</small><small>${esc(run.authority_state || 'authority unavailable')}</small></div><div>${badge(String(run.state || run.runtime_state || 'unknown'), ['succeeded'].includes(run.state || run.runtime_state) ? 'success' : ['failed', 'cancelled'].includes(run.state || run.runtime_state) ? 'warning' : 'info')}${studioRunControls(kind, run)}</div><details class="studio-run-receipt"><summary>Authenticated runtime head</summary><dl class="modal-detail"><div><dt>Revision</dt><dd class="mono">${esc(run.revision_sha256 || 'unavailable')}</dd></div><div><dt>Request</dt><dd class="mono">${esc(run.request_sha256 || 'unavailable')}</dd></div><div><dt>Last event</dt><dd class="mono">${esc(run.last_event_sha256 || run.control_head_sha256 || 'unavailable')}</dd></div><div><dt>Resume count</dt><dd>${number(run.resume_count || 0)}</dd></div><div><dt>Heartbeat</dt><dd>${esc(run.heartbeat_utc || 'unavailable')}</dd></div></dl><b>Checkpoint</b><pre class="modal-readout">${esc(JSON.stringify(run.checkpoint || {}, null, 2))}</pre>${run.failure ? `<b>Failure</b><pre class="modal-readout">${esc(JSON.stringify(run.failure, null, 2))}</pre>` : ''}</details></article>`).join('');
  const invalid = Array.isArray(result?.invalid) && result.invalid.length ? `<details><summary>${number(result.invalid.length)} unauthenticated or damaged run record(s)</summary>${humanRecord(result.invalid)}</details>` : '';
  showInformationModal(`${kind[0].toUpperCase()}${kind.slice(1)} durable runs`, 'AUTHENTICATED RUN HEADS · REAL LIFECYCLE CONTROLS', result, `<p>${number(runs.length)} authenticated run${runs.length === 1 ? '' : 's'} shown. Controls are enabled only for transitions the durable state machine supports.</p><div class="catalog-list studio-run-list">${rows || '<p class="empty-state">No durable runs exist for this Studio yet.</p>'}</div>${invalid}<div class="action-grid studio-actions"><button data-action="openStudioRuns" data-kind="${esc(kind)}">Refresh run list</button><button data-action="studioRunAction" data-kind="${esc(kind)}" data-operation="reconcile">Reconcile interrupted runs</button></div>`);
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
function cancelPendingStudioRequests() {
  const saveInFlight = Boolean(studioSaveRequest);
  if (saveInFlight) {
    rememberDetachedStudioSave(studioSaveRequest);
    vscode.postMessage({ type: 'detachStudioDraft', requestId: studioSaveRequest.requestId, kind: studioSaveRequest.kind });
  }
  studioSaveRequest = null;
  if (studioPendingSkillPackage?.sourceSelectionId && studioSourceProofRequestId) vscode.postMessage({ type: 'releaseStudioTrust', requestId: studioSourceProofRequestId, trustKind: 'source-selection', proof: studioPendingSkillPackage.sourceSelectionId });
  // Once a save is in flight, the host-side create coordinator owns the proof.
  // Releasing it here races the already-dispatched create and can invalidate a
  // legitimate commit merely because the editor was closed or its panel died.
  if (!saveInFlight && studioVersionAllocationProof && studioVersionProofRequestId) vscode.postMessage({ type: 'releaseStudioTrust', requestId: studioVersionProofRequestId, trustKind: 'version-allocation', proof: studioVersionAllocationProof });
  studioAllocationRequest = null;
  studioPackageRequest = null;
  studioPendingSkillPackage = null;
  studioVersionAllocation = null;
  studioVersionAllocationProof = null;
  studioVersionProofRequestId = null;
  studioSourceProofRequestId = null;
}
function closeModal(preserveStudioTrust = false) {
  if (!preserveStudioTrust) cancelPendingStudioRequests();
  const root = document.getElementById('modal-root'); if (root) root.innerHTML = '';
  modalCopyText = ''; modalTitle = ''; modalRecord = null; modalHumanText = '';
  studioPendingRun = null;
  studioPendingWorkflowRun = null;
  const priorFocus = modalReturnFocus; const returnSelector = modalReturnSelector;
  modalReturnFocus = null; modalReturnSelector = null;
  if (deferredRender) { deferredRender = false; render(); }
  (returnSelector ? app.querySelector(returnSelector) : priorFocus)?.focus?.();
}

function navButton([id, label, symbol]) {
  const active = state.active === id;
  return `<button class="nav-item${active ? ' active' : ''}" data-surface="${id}" aria-label="${esc(label)}" aria-current="${active ? 'page' : 'false'}">${icon(symbol)}<span>${esc(label)}</span></button>`;
}

function finishGraphFocusTransition(entering) {
  const target = entering
    ? app.querySelector('.graph-focus-mode [data-graph-canvas]')
    : app.querySelector('[data-action="graphFocus"]');
  target?.focus();
}

function renderPreservingControl(selector) {
  const current = document.activeElement;
  const restore = Boolean(current?.matches?.(selector));
  const selectionStart = restore && typeof current.selectionStart === 'number' ? current.selectionStart : null;
  const selectionEnd = restore && typeof current.selectionEnd === 'number' ? current.selectionEnd : null;
  render();
  if (!restore) return;
  const next = app.querySelector(selector);
  next?.focus();
  if (selectionStart !== null && typeof next?.setSelectionRange === 'function') {
    const maximum = String(next.value || '').length;
    next.setSelectionRange(Math.min(selectionStart, maximum), Math.min(selectionEnd, maximum));
  }
}

function updateEnvironmentLifecycleGate() {
  const input = document.getElementById('environment-lifecycle-target');
  const acknowledgement = document.getElementById('environment-lifecycle-consumers');
  const execute = app.querySelector('[data-action="executeEnvironmentLifecycle"]');
  if (!input || !execute) return;
  execute.disabled = input.value !== input.dataset.exactTarget || Boolean(acknowledgement && !acknowledgement.checked);
}

function hostActionSummary(operation = state.operation) {
  if (!operation || !operation.status || !operation.action) return '';
  const status = String(operation.status || 'unknown').toLowerCase();
  const action = String(operation.action || 'host-operation').replace(/[^a-z0-9_-]/gi, '-');
  const tone = {
    completed: 'success',
    complete: 'success',
    refused: 'warning',
    cancelled: 'neutral',
    'no-op': 'neutral',
    failed: 'warning',
    unavailable: 'warning',
    pending: 'info'
  }[status] || 'neutral';
  const detail = operation.detail || {};
  const boundary = detail.boundary || {};
  const pieces = [];
  if (detail.objective) {
    const objective = String(detail.objective);
    pieces.push(`objective ${objective.slice(0, 72)}${objective.length > 72 ? '...' : ''}`);
  }
  if (detail.reason) pieces.push(`reason: ${String(detail.reason)}`);
  if (detail.boundary) pieces.push(`boundary: ${String(detail.boundary)}`);
  if (boundary.executorOwner) pieces.push(`executor ${String(boundary.executorOwner)}`);
  if (Object.prototype.hasOwnProperty.call(boundary, 'extensionExecutes')) {
    pieces.push(`extensionExecutes ${String(Boolean(boundary.extensionExecutes))}`);
  }
  if (detail.rule || boundary.rule) pieces.push(String(detail.rule || boundary.rule).slice(0, 72));
  const observed = operation.observedAt ? new Date(operation.observedAt).toLocaleTimeString() : '';
  const summary = pieces.length ? pieces.slice(0, 4).join(' · ') : '';
  const detailMarkup = summary
    ? `<span class="operation-summary-detail">${esc(summary)}${observed ? ` · ${esc(observed)}` : ''}</span>`
    : observed ? `<span class="operation-summary-detail">${esc(observed)}</span>` : '';
  return `<div class="operation-summary" role="status">${badge(`ACTION ${action}`, 'info')} ${badge(`STATUS ${String(status).toUpperCase()}`, tone)}${detailMarkup}</div>`;
}

function render() {
  if (app.querySelector('.control-modal')) { deferredRender = true; return; }
  const s = state.snapshot; const connection = healthState.operational(s || {}); const connected = connection.connected; const identityMatches = Boolean(s?.extensionIdentity?.matches); const operational = connection.state === 'connected'; const certification = healthState.certification(s || {}); const advancedVisible = state.settings.showAdvancedSurfaces;
  if (!advancedVisible && advancedSurfaces.some(([id]) => id === state.active)) state.active = 'dashboard';
  const title = [...visibleSurfaces, ...advancedSurfaces].find(([id]) => id === state.active)?.[1] || 'Dashboard';
  app.className = operational ? 'connected' : connected ? 'connected identity-mismatch' : 'disconnected';
  app.dataset.glassOpacity = finiteLayoutText(state.settings.glassIntensity, 0, 1, .66);
  const turbovec = turbovecDisplay(s);
  const gitState = gitDisplay(s);
  app.innerHTML = `
    <a class="skip-link" href="#main-content">Skip navigation</a><div class="shell">
      <aside class="control-rail">
        <div class="brand-block"><div class="brand-frame"><img src="${brandUri}" alt="" class="brand-mark"></div><div class="brand-copy"><strong>PACIFY-X</strong><span>CONTROL PLANE</span></div></div>
        <nav class="nav-rail" aria-label="Pacify-X dashboard navigation">
          <div class="primary-nav">${visibleSurfaces.map(navButton).join('')}</div>
          <div class="advanced-wrap"><button class="advanced-toggle${advancedSurfaces.some(([id]) => id === state.active) ? ' active' : ''}" data-action="toggleAdvanced" aria-expanded="${state.advancedOpen}">${icon('runtime')}<span>Advanced</span><b>${advancedVisible ? (state.advancedOpen ? '−' : '+') : 'LOCKED'}</b></button>
          ${advancedVisible && state.advancedOpen ? `<div class="advanced-nav">${advancedSurfaces.map(navButton).join('')}</div>` : ''}</div>
        </nav>
        <div class="rail-status"><span><i class="live-pip"></i>${esc(connection.label)}</span><small>${esc(s?.schemaVersion || 'schema unavailable')}</small></div>
      </aside>
      <main class="workspace" id="main-content" tabindex="-1">
        <header class="cockpit-header">
          <div class="page-identity"><span class="breadcrumb">PACIFY-X / ${advancedSurfaces.some(([id]) => id === state.active) ? 'ADVANCED / ' : ''}${esc(title.toUpperCase())}</span><h1>${esc(title)}</h1></div>
          <div class="telemetry-cell workspace-cell"><span>WORKSPACE</span><strong>${esc(s?.project?.name || 'Awaiting engine')}</strong><small>${esc(s?.source?.mode || 'not resolved')}</small></div>
          <div class="telemetry-cell branch-cell"><span>BRANCH</span><strong>${esc(s?.git?.branch || s?.project?.branch || '—')}</strong><small>${s?.git?.dirty ? `${number((s.git.staged || 0) + (s.git.unstaged || 0) + (s.git.untracked || 0))} changes` : 'clean/unknown'}</small></div>
          <div class="telemetry-cell coordination-cell"><span>COORDINATION</span><strong>${state.coordination?.state?.active_plan ? 'Plan active' : 'Ready'}</strong><small>${number(state.coordination?.state?.claims?.length || 0)} active claims</small></div>
          <div class="cockpit-actions"><button class="sync-button" data-action="refresh">↻ Sync</button><button class="control-button" data-action="commandCenter">Controls</button><button class="icon-button" data-action="openSettings" title="Settings" aria-label="Settings">⚙</button></div>
        </header>
        <div class="top-status">
          ${badge(connection.label, connection.tone)}
          ${badge(s?.provider?.chatGptAuthenticated ? 'CODEX LOGIN DETECTED · NOT COPILOT TELEMETRY' : 'BILLABLE API FALLBACK OFF', 'info')}
          ${badge(gitState.label, gitState.tone)}
          ${badge(turbovec.label, turbovec.tone)}
          ${badge(s?.enterprise?.catalog_id ? 'MS+ENTERPRISE OFFLINE BOUNDARY' : 'ENTERPRISE UNAVAILABLE', s?.enterprise?.catalog_id ? 'info' : 'neutral')}
          ${hostActionSummary()}
        </div>
        ${!connected ? `<div class="engine-disconnected-warning" data-engine-disconnected role="alert"><span>ENGINE DISCONNECTED</span><strong>Current operational metrics are unavailable.</strong><p>${esc(s?.reason || s?.health?.reason || 'The Pacify-X engine did not return a current authoritative snapshot.')}</p><small>Any displayed zero is an unavailable fallback, not an observed system value or health claim. Restore the engine connection and sync again.</small></div>` : ''}
        ${connected && !identityMatches ? `<div class="identity-warning" role="alert"><div><span>EXTENSION IDENTITY MISMATCH</span><strong>The loaded VS Code host is not the dashboard source being inspected.</strong><p>${esc((s.extensionIdentity?.mismatch_reasons || ['identity unavailable']).join(' · '))}</p></div><dl><div><dt>Host</dt><dd>v${esc(s.extensionIdentity?.host?.version || 'unknown')} · ${esc((s.extensionIdentity?.host?.asset_sha256 || '').slice(0, 16) || 'no asset hash')}</dd></div><div><dt>Source</dt><dd>v${esc(s.extensionIdentity?.source?.version || 'unknown')} · ${esc((s.extensionIdentity?.source?.asset_sha256 || '').slice(0, 16) || 'no asset hash')}</dd></div><div><dt>Protocol</dt><dd>${esc(s.extensionIdentity?.host?.asset_protocol || 'unknown')} / ${esc(s.extensionIdentity?.host?.message_schema || 'unknown')}</dd></div></dl></div>` : ''}
        <div class="content surface-${esc(state.active)}">${surface(state.active)}</div>
        <footer class="footer"><span><i class="live-pip"></i>${esc(connection.label)}</span><span>Operational view · no completion claim</span><span>Host/source: ${esc(s?.extensionIdentity?.host?.version || 'unknown')} / ${esc(s?.extensionIdentity?.source?.version || 'unknown')}</span><span>Catalog: ${esc(s?.catalogSource || 'unavailable')}</span><span>${s?.generatedAt ? `Snapshot ${esc(new Date(s.generatedAt).toLocaleTimeString())}` : 'Awaiting snapshot'}</span></footer>
      </main>
    </div><div id="modal-root"></div>`;
  if (state.active === 'settings') {
    const settingsContent = app.querySelector('.surface-settings');
    const policy = state.settings.executionPolicy || {};
    const mcp = s?.observability?.mcp || {};
    const metrics = document.createElement('div');
    metrics.className = 'metric-grid compact settings-effective-metrics';
    metrics.innerHTML = `${card('ENGINE CONNECTION', connected ? 'Connected' : 'Disconnected', s?.catalogSource || 'catalog source unavailable', connected ? 'green' : 'red')}${card('MCP RUNTIME', mcp.runtime_verified ? 'Runtime verified' : mcp.registered ? 'Registered, unverified' : String(mcp.status || 'Unavailable'), mcp.detail || 'current MCP observation', mcp.runtime_verified ? 'green' : 'blue')}${card('BILLABLE MASTER', policy.master_enabled === true ? 'Guarded opt-in' : 'Disabled', policy.master_enabled === true ? 'every execution gate still applies' : 'zero-cost default', policy.master_enabled === true ? 'red' : 'green')}${card('CONTEXT CAP', `${number(state.settings.contextInjectionCapTokens)} tokens`, 'effective extension setting')}`;
    settingsContent?.prepend(metrics);
  }
  for (const status of app.querySelectorAll('.catalog-controls > span:last-child, .memory-toolbar > span:last-child, .activity-toolbar > span:last-child')) {
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
  }
  boundedLayout.apply(document);
  persistDashboardState();
  ensureSurfaceData();
  if (state.active === 'knowledgeGraph') requestAnimationFrame(prepareGraphInteraction);
}

function surface(id) {
  if (!state.snapshot) return loading();
  const surfaceContext = { state, shieldUri, attentionList, coordinationSummary, serviceGrid, thermalPanel, eventTimeline, healthState };
  if (coreSurfaces.has(id)) return coreSurfaces.render(id, surfaceContext);
  if (catalogSurfaces.has(id)) return catalogSurfaces.render(id, { state, catalogPanel, enterprisePackPanel });
  if (operationalSurfaces.has(id)) return operationalSurfaces.render(id, { state, catalogPanel, environmentMap, coordinationBoard });
  if (systemSurfaces.has(id)) return systemSurfaces.render(id, { state, serviceGrid, catalogPanel, healthState });
  if (observabilitySurfaces.has(id)) return observabilitySurfaces.render(id, { state, readableValue });
  if (advancedSurfaceRenderers.has(id)) return advancedSurfaceRenderers.render(id, { state, thermalPanel, coordinationSummary });
  if (graphSurface.has(id)) return graphSurface.render({ state, catalogPanel, graphPositions });
  return coreSurfaces.render('dashboard', surfaceContext);
}
function loading() { return `<div class="loading"><img src="${shieldUri}" alt=""><span class="scan-line"></span><h2>Reading the Pacify-X control plane</h2><p>Discovery is bounded and read-only.</p></div>`; }

function attentionList() {
  const items = state.snapshot.attention || [];
  return items.length ? `<div class="attention-list">${items.map(item => `<article class="attention ${esc(item.severity)}"><span class="attention-mark"></span><div><strong>${esc(item.title)}</strong><p>${esc(item.detail)}</p></div>${badge(item.severity.toUpperCase(), item.severity === 'warning' ? 'warning' : 'info')}</article>`).join('')}</div>` : empty('No attention items were reported.');
}

function catalogPanel(kind, title, kicker) {
  const catalog = state.catalogs[kind]; const request = state.catalogRequests[kind] || { query: '', offset: 0, limit: 50, sort: 'label' };
  if (!catalog) return section(title, kicker, `<div class="catalog-loading"><span class="empty-ring"></span><p>Loading a bounded page from runtime.dashboard_api…</p></div>`);
  if (catalog.error) return section(title, kicker, `<div class="memory-errors" role="alert"><p>${esc(catalog.error)}</p><button data-action="catalogRetry" data-kind="${esc(kind)}">Retry this catalog</button></div>`);
  const rows = catalog.items.map(item => `<button class="catalog-row" data-action="inspectCatalogItem" data-kind="${kind}" data-id="${esc(item.id)}"><span class="catalog-primary"><strong>${esc(item.label)}</strong><small>${esc(item.id)} · ${esc(item.summary || 'No summary')}</small></span><span>${badge(item.kind, 'info')}</span><span>${badge(item.status, item.status === 'active' || item.status === 'admitted' ? 'success' : 'neutral')}</span><span class="catalog-risk">${esc(item.risk || item.effects?.join(', ') || 'bounded')}</span><b>DETAILS</b></button>`).join('');
  const first = catalog.filtered ? catalog.offset + 1 : 0; const last = Math.min(catalog.offset + catalog.items.length, catalog.filtered);
  const lifecycleOptions = Object.entries(catalog.status_counts || {}).map(([status, count]) => `<option value="${esc(status)}" ${request.status === status ? 'selected' : ''}>${esc(status.replaceAll('_', ' '))} · ${number(count)}</option>`).join('');
  return section(title, kicker, `<div class="catalog-controls"><label><span class="sr-only">Search ${esc(title)}</span><input data-catalog-search="${kind}" value="${esc(request.query)}" placeholder="Search all ${number(catalog.total)} records"></label><label><span class="sr-only">Filter ${esc(title)} by lifecycle</span><select data-catalog-status="${kind}" aria-label="Filter ${esc(title)} by lifecycle"><option value="">All lifecycle states · ${number(catalog.total)}</option>${lifecycleOptions}</select></label><select data-catalog-sort="${kind}" aria-label="Sort ${esc(title)}"><option value="label" ${request.sort === 'label' ? 'selected' : ''}>Name</option><option value="id" ${request.sort === 'id' ? 'selected' : ''}>ID</option><option value="status" ${request.sort === 'status' ? 'selected' : ''}>Status</option><option value="kind" ${request.sort === 'kind' ? 'selected' : ''}>Kind</option></select><span>Showing ${number(first)}–${number(last)} of ${number(catalog.filtered)} (${number(catalog.total)} source records)</span></div><div class="catalog-scroll" role="list">${rows || empty('No records match this lifecycle and search filter.')}</div><div class="pager"><button data-action="catalogPrevious" data-kind="${kind}" ${catalog.offset <= 0 ? 'disabled' : ''}>Previous</button><button data-action="catalogNext" data-kind="${kind}" ${catalog.has_more ? '' : 'disabled'}>Next</button></div>`, `<span class="count-chip">${number(catalog.total)}</span>`);
}

function enterprisePackPanel() {
  const catalog = state.snapshot.enterprise || {}; const local = state.snapshot.enterpriseState || { pack_states: {}, targets: [] };
  const doctor = local.last_doctor || null; const doctorReady = doctor?.valid === true;
  const rows = (catalog.packs || []).map(pack => {
    const enabled = Boolean(local.pack_states?.[pack.id]?.enabled);
    return `<article class="enterprise-pack-row"><div><strong>${esc(pack.name)}</strong><small>${esc(pack.id)} · ${esc(pack.priority)} · ${esc(pack.status)}</small><p>${esc((pack.capabilities || []).join(' · '))}</p></div><div>${badge(enabled ? 'OFFLINE ENABLED' : 'DISABLED', enabled ? 'success' : 'neutral')}<button data-action="enterprisePackToggle" data-pack-id="${esc(pack.id)}" data-enabled="${enabled ? 'false' : 'true'}">${enabled ? 'Disable' : 'Enable metadata'}</button><button data-action="enterpriseTargetConfigure" data-pack-id="${esc(pack.id)}">Target</button></div></article>`;
  }).join('');
  return section('Enterprise packs', 'SEPARATE PROJECT STATE · CONNECTORS STAY OFF', `<div class="enterprise-boundary"><b>${doctor ? (doctorReady ? 'Local control plane checks passed' : 'Local control plane checks failed') : 'Readiness has not been checked'}</b><span>${doctor ? `${number((doctor.checks || []).filter(item => item.passed).length)} of ${number((doctor.checks || []).length)} local checks passed` : 'Run the offline doctor to evaluate the local boundary'} · cloud connectors remain disabled</span></div><div class="enterprise-pack-list">${rows || unavailable()}</div><button class="primary" data-action="enterpriseDoctor">Run readiness doctor</button>`, `<span class="count-chip">${number((catalog.packs || []).length)}</span>`);
}

function graphPositions(data, ordered, width, height) {
  const center = data.selected; const positions = new Map();
  if (data.mode === 'full' || state.graphLayout === 'community') {
    const groups = new Map();
    for (const item of ordered) {
      const communityId = item.community_id || `${item.kind || 'unknown'}::general`;
      if (!groups.has(communityId)) groups.set(communityId, []);
      groups.get(communityId).push(item);
    }
    const metadata = new Map((data.communities || []).map(item => [item.id, item]));
    const communityIds = [...groups].sort((left, right) => {
      const leftMeta = metadata.get(left[0]); const rightMeta = metadata.get(right[0]);
      return Number(rightMeta?.member_count || right[1].length) - Number(leftMeta?.member_count || left[1].length) || String(leftMeta?.label || left[0]).localeCompare(String(rightMeta?.label || right[0]));
    }).map(([id]) => id);
    const columns = Math.max(1, Math.ceil(Math.sqrt(communityIds.length * 1.35))); const rows = Math.max(1, Math.ceil(communityIds.length / columns));
    const cellWidth = width / columns; const cellHeight = height / rows; const regions = [];
    communityIds.forEach((communityId, communityIndex) => {
      const column = communityIndex % columns; const row = Math.floor(communityIndex / columns); const cx = cellWidth * (column + .5); const cy = cellHeight * (row + .5);
      const items = groups.get(communityId).sort((left, right) => Number(right.degree || 0) - Number(left.degree || 0) || left.title.localeCompare(right.title));
      const maxRadius = Math.max(80, Math.min(cellWidth, cellHeight) / 2 - 76);
      items.forEach((item, index) => {
        if (items.length === 1) { positions.set(item.key, { x: cx, y: cy }); return; }
        const angle = index * 2.399963229728653; const radius = Math.min(maxRadius, 42 + Math.sqrt(index) * 66);
        positions.set(item.key, { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius });
      });
      const meta = metadata.get(communityId) || {}; regions.push({ id: communityId, label: meta.label || communityId, x: column * cellWidth + 24, y: row * cellHeight + 24, width: cellWidth - 48, height: cellHeight - 48, loaded: items.length, total: Number(meta.member_count || items.length) });
    });
    positions.communities = regions;
    return positions;
  }
  positions.set(center, { x: width / 2, y: height / 2 });
  const neighbors = ordered.filter(item => item.key !== center);
  if (state.graphLayout === 'orbit') {
    let offset = 0; let radius = 280;
    while (offset < neighbors.length) {
      const capacity = Math.max(8, Math.floor((Math.PI * 2 * radius) / 210)); const ring = neighbors.slice(offset, offset + capacity);
      ring.forEach((item, index) => { const angle = -Math.PI / 2 + (Math.PI * 2 * index / ring.length) + ((offset / Math.max(1, capacity)) % 2 ? Math.PI / ring.length : 0); positions.set(item.key, { x: width / 2 + Math.cos(angle) * radius, y: height / 2 + Math.sin(angle) * radius }); });
      offset += ring.length; radius += 190;
    }
    return positions;
  }
  const incoming = []; const outgoing = []; const contextual = [];
  for (const item of neighbors) {
    const comesIn = (data.edges || []).some(edge => edge.source === item.key && edge.target === center);
    const goesOut = (data.edges || []).some(edge => edge.source === center && edge.target === item.key);
    if (comesIn && !goesOut) incoming.push(item); else if (goesOut && !comesIn) outgoing.push(item); else contextual.push(item);
  }
  const placeLane = (items, side) => {
    const columns = Math.min(2, Math.max(1, Math.ceil(items.length / 10))); const perColumn = Math.ceil(items.length / columns);
    items.forEach((item, index) => {
      const column = Math.floor(index / perColumn); const row = index % perColumn; const rows = Math.min(perColumn, items.length - column * perColumn);
      const x = side === 'left' ? 150 + column * 205 : width - 150 - column * 205;
      const blockHeight = Math.max(0, (rows - 1) * 112); const y = (height - blockHeight) / 2 + row * 112;
      positions.set(item.key, { x, y });
    });
  };
  placeLane(incoming, 'left'); placeLane(outgoing, 'right');
  const contextColumns = 4; const contextRows = Math.ceil(contextual.length / contextColumns); const contextHeight = Math.max(0, (contextRows - 1) * 112);
  contextual.forEach((item, index) => {
    const column = index % contextColumns; const row = Math.floor(index / contextColumns); const y = (height - contextHeight) / 2 + row * 112;
    positions.set(item.key, { x: width / 2 + (column - 1.5) * 220, y });
  });
  return positions;
}

function graphCanvas() { return app.querySelector('[data-graph-canvas]'); }
function clampGraphScale(value) { return Math.min(graphInteraction.maxScale, Math.max(graphInteraction.minScale, value)); }
function graphStatus(message) { const status = app.querySelector('[data-graph-status]'); if (status) status.textContent = message; }
function graphNodeFrameSize(item, selected, data = state.graphData) {
  if (data?.mode === 'full') return selected ? { width: 164, height: 68 } : { width: 136, height: 54 };
  return selected ? { width: 176, height: 84 } : { width: 152, height: 64 };
}
function orderedGraphNodes(data = state.graphData) {
  const center = data?.selected;
  return [...(data?.nodes || [])].sort((left, right) => left.key === center ? -1 : right.key === center ? 1 : String(left.community_id || '').localeCompare(String(right.community_id || '')) || Number(right.degree || 0) - Number(left.degree || 0) || String(left.title || '').localeCompare(String(right.title || '')));
}
function selectedGraphPoint(canvas = graphCanvas()) {
  if (!canvas || !state.graphData?.nodes?.length) return null;
  const selectedFrame = canvas.querySelector('.graph-node-frame .graph-node.selected')?.closest('.graph-node-frame');
  if (selectedFrame) return { x: Number(selectedFrame.dataset.graphX), y: Number(selectedFrame.dataset.graphY) };
  const width = Number(canvas.dataset.sceneWidth); const height = Number(canvas.dataset.sceneHeight);
  return graphPositions(state.graphData, orderedGraphNodes(), width, height).get(state.graphData.selected) || null;
}
function materializeGraphGeometry() {
  const canvas = graphCanvas(); const scene = canvas?.querySelector('[data-graph-scene]');
  if (!canvas || !scene || scene.querySelector('.graph-node-layer') || !state.graphData?.nodes?.length) return;
  const width = Number(canvas.dataset.sceneWidth); const height = Number(canvas.dataset.sceneHeight); const center = state.graphData.selected;
  const ordered = orderedGraphNodes();
  const positions = graphPositions(state.graphData, ordered, width, height); const namespace = 'http://www.w3.org/2000/svg';
  const nodeLayer = document.createElementNS(namespace, 'svg'); nodeLayer.setAttribute('class', 'graph-node-layer'); nodeLayer.setAttribute('viewBox', `0 0 ${width} ${height}`);
  for (const item of ordered) {
    const node = scene.querySelector(`.graph-node.actual[data-node-key="${CSS.escape(item.key)}"]`); const point = positions.get(item.key); if (!node || !point) continue;
    const selected = item.key === center; const size = graphNodeFrameSize(item, selected); const frameWidth = size.width; const frameHeight = size.height;
    const frame = document.createElementNS(namespace, 'foreignObject'); frame.setAttribute('class', 'graph-node-frame'); frame.setAttribute('x', String(point.x - frameWidth / 2)); frame.setAttribute('y', String(point.y - frameHeight / 2)); frame.setAttribute('width', String(frameWidth)); frame.setAttribute('height', String(frameHeight));
    frame.dataset.nodeKey = item.key; frame.dataset.graphX = String(point.x); frame.dataset.graphY = String(point.y); frame.dataset.graphWidth = String(frameWidth); frame.dataset.graphHeight = String(frameHeight);
    node.classList.add('svg-node'); frame.append(node); nodeLayer.append(frame);
  }
  scene.append(nodeLayer);
  const minimap = canvas.querySelector('.graph-minimap');
  if (minimap) {
    minimap.textContent = ''; const map = document.createElementNS(namespace, 'svg'); map.setAttribute('viewBox', `0 0 ${width} ${height}`); map.setAttribute('aria-hidden', 'true');
    for (const item of ordered) { const point = positions.get(item.key); const dot = document.createElementNS(namespace, 'circle'); dot.setAttribute('cx', String(point.x)); dot.setAttribute('cy', String(point.y)); dot.setAttribute('r', item.key === center ? '18' : '10'); if (item.key === center) dot.setAttribute('class', 'selected'); map.append(dot); }
    const viewport = document.createElementNS(namespace, 'rect'); viewport.setAttribute('data-graph-minimap-viewport', ''); map.append(viewport); minimap.append(map);
  }
}
function scheduleGraphVirtualization() {
  const canvas = graphCanvas(); if (!canvas) return;
  const generation = ++graphInteraction.visibilityGeneration; const scale = graphInteraction.scale;
  const margin = 180 / Math.max(scale, .08); const bounds = { left: -graphInteraction.x / scale - margin, top: -graphInteraction.y / scale - margin, right: (canvas.clientWidth - graphInteraction.x) / scale + margin, bottom: (canvas.clientHeight - graphInteraction.y) / scale + margin };
  const frames = [...canvas.querySelectorAll('.graph-node-frame')]; const selected = state.graphData?.selected; let cursor = 0;
  canvas.classList.toggle('graph-scale-distant', scale < .42); canvas.classList.toggle('graph-scale-near', scale >= .78);
  const processFrames = () => {
    if (generation !== graphInteraction.visibilityGeneration || !canvas.isConnected) return;
    const end = Math.min(frames.length, cursor + 280);
    for (; cursor < end; cursor += 1) {
      const frame = frames[cursor]; const x = Number(frame.dataset.graphX); const y = Number(frame.dataset.graphY); const halfWidth = Number(frame.dataset.graphWidth) / 2; const halfHeight = Number(frame.dataset.graphHeight) / 2;
      const visible = frame.dataset.nodeKey === selected || (x + halfWidth >= bounds.left && x - halfWidth <= bounds.right && y + halfHeight >= bounds.top && y - halfHeight <= bounds.bottom);
      frame.classList.toggle('is-virtualized', !visible);
    }
    if (cursor < frames.length) { requestAnimationFrame(processFrames); return; }
    const visibleKeys = new Set(frames.filter(frame => !frame.classList.contains('is-virtualized')).map(frame => frame.dataset.nodeKey)); const edgeGroups = [...canvas.querySelectorAll('.graph-edge-group')]; let edgeCursor = 0;
    const processEdges = () => {
      if (generation !== graphInteraction.visibilityGeneration || !canvas.isConnected) return;
      const edgeEnd = Math.min(edgeGroups.length, edgeCursor + 420);
      for (; edgeCursor < edgeEnd; edgeCursor += 1) {
        const edge = edgeGroups[edgeCursor]; edge.classList.toggle('is-virtualized', !visibleKeys.has(edge.dataset.edgeSource) && !visibleKeys.has(edge.dataset.edgeTarget));
      }
      if (edgeCursor < edgeGroups.length) requestAnimationFrame(processEdges);
      else requestAnimationFrame(reportGraphRender);
    };
    processEdges();
  };
  requestAnimationFrame(processFrames);
}
function applyGraphViewport(message = '') {
  const canvas = graphCanvas(); const scene = canvas?.querySelector('[data-graph-scene]'); if (!canvas || !scene) return;
  scene.dataset.graphTranslateX = finiteLayoutText(graphInteraction.x, -100000, 100000, 0);
  scene.dataset.graphTranslateY = finiteLayoutText(graphInteraction.y, -100000, 100000, 0);
  scene.dataset.graphScale = finiteLayoutText(graphInteraction.scale, graphInteraction.minScale, graphInteraction.maxScale, 1);
  boundedLayout.apply(scene);
  const output = app.querySelector('[data-graph-zoom]'); if (output) output.textContent = `${Math.round(graphInteraction.scale * 100)}%`;
  const minimapViewport = canvas.querySelector('[data-graph-minimap-viewport]');
  if (minimapViewport) {
    const width = Number(canvas.dataset.sceneWidth); const height = Number(canvas.dataset.sceneHeight);
    const left = Math.max(0, -graphInteraction.x / graphInteraction.scale); const top = Math.max(0, -graphInteraction.y / graphInteraction.scale);
    minimapViewport.setAttribute('x', String(Math.min(width, left))); minimapViewport.setAttribute('y', String(Math.min(height, top)));
    minimapViewport.setAttribute('width', String(Math.min(width, canvas.clientWidth / graphInteraction.scale))); minimapViewport.setAttribute('height', String(Math.min(height, canvas.clientHeight / graphInteraction.scale)));
  }
  scheduleGraphVirtualization();
  if (message) graphStatus(message);
}
function fitGraphViewport(message = 'Map fitted') {
  const canvas = graphCanvas(); if (!canvas) return;
  const width = Number(canvas.dataset.sceneWidth); const height = Number(canvas.dataset.sceneHeight); const pad = canvas.clientWidth < 700 ? 18 : 42;
  graphInteraction.scale = clampGraphScale(Math.min((canvas.clientWidth - pad * 2) / width, (canvas.clientHeight - pad * 2) / height));
  graphInteraction.x = (canvas.clientWidth - width * graphInteraction.scale) / 2; graphInteraction.y = (canvas.clientHeight - height * graphInteraction.scale) / 2;
  graphInteraction.fitted = true; applyGraphViewport(message);
}
function frameReadableGraphViewport(message = 'Readable map view') {
  const canvas = graphCanvas(); if (!canvas) return;
  fitGraphViewport(message);
  const minimumReadableScale = canvas.clientWidth < 560 ? 0.72 : canvas.clientWidth < 900 ? 0.7 : 0.68;
  if (graphInteraction.scale < minimumReadableScale) {
    // A readable zoom of a large full map must anchor the selected record.
    // Zooming around the geometric center can land in an empty gap between
    // community hulls, making a populated graph appear blank.
    const point = selectedGraphPoint(canvas);
    graphInteraction.scale = clampGraphScale(minimumReadableScale);
    if (point) {
      graphInteraction.x = canvas.clientWidth / 2 - point.x * graphInteraction.scale;
      graphInteraction.y = canvas.clientHeight / 2 - point.y * graphInteraction.scale;
    }
    applyGraphViewport(`${message} · selected record centered · Fit shows all`);
  }
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
  materializeGraphGeometry(); const canvas = graphCanvas(); if (!canvas) return; const key = canvas.dataset.sceneKey;
  if (graphInteraction.sceneKey !== key || !graphInteraction.fitted) {
    graphInteraction.sceneKey = key; frameReadableGraphViewport();
  } else applyGraphViewport();
}
function reportGraphRender() {
  const canvas = graphCanvas(); if (!canvas || !state.graphData || state.graphPending) return;
  const canvasRect = canvas.getBoundingClientRect();
  const nodes = [...canvas.querySelectorAll('.graph-node.actual')];
  const width = Number(canvas.dataset.sceneWidth); const height = Number(canvas.dataset.sceneHeight); const center = state.graphData.selected;
  const ordered = orderedGraphNodes();
  const positions = graphPositions(state.graphData, ordered, width, height);
  const nodeRects = ordered.flatMap(item => {
    const point = positions.get(item.key); if (!point) return [];
    const size = graphNodeFrameSize(item, item.key === center); const frameWidth = size.width; const frameHeight = size.height;
    const left = canvasRect.left + graphInteraction.x + (point.x - frameWidth / 2) * graphInteraction.scale;
    const top = canvasRect.top + graphInteraction.y + (point.y - frameHeight / 2) * graphInteraction.scale;
    return [{ left, top, right: left + frameWidth * graphInteraction.scale, bottom: top + frameHeight * graphInteraction.scale, width: frameWidth * graphInteraction.scale, height: frameHeight * graphInteraction.scale }];
  });
  const visibleNodeCount = canvas.querySelectorAll('.graph-node-frame:not(.is-virtualized)').length || nodeRects.filter(rect => rect.width > 0 && rect.height > 0 && rect.right > canvasRect.left && rect.left < canvasRect.right && rect.bottom > canvasRect.top && rect.top < canvasRect.bottom).length;
  vscode.postMessage({ type: 'graphRendered', requestId: state.graphRequestId || '', view: state.graphData.view || state.graphView, nodeCount: nodes.length, edgeCount: canvas.querySelectorAll('.graph-edge-group path').length, visibleNodeCount, canvasWidth: Math.round(canvasRect.width), canvasHeight: Math.round(canvasRect.height) });
}
function highlightGraphNode(key) {
  const canvas = graphCanvas(); if (!canvas) return; const scene = canvas.querySelector('[data-graph-scene]'); if (!scene) return;
  scene.classList.toggle('has-highlight', Boolean(key));
  for (const node of scene.querySelectorAll('[data-node-key]')) node.classList.toggle('is-highlighted', Boolean(key) && node.dataset.nodeKey === key);
  for (const edge of scene.querySelectorAll('[data-edge-source]')) edge.classList.toggle('is-highlighted', Boolean(key) && (edge.dataset.edgeSource === key || edge.dataset.edgeTarget === key));
}

function requestGraph(updates = {}) {
  const data = state.graphData || {}; const fullMode = (updates.mode || state.graphMode) === 'full';
  const current = {
    view: state.graphView, mode: state.graphMode, cluster: state.graphCommunity, node: '', target: state.graphTarget,
    query: data.requested_query || '', relation: data.requested_relation || '', direction: data.direction || 'both',
    kind: state.graphKind, status: state.graphStatus, offset: 0, edgeOffset: 0, depth: state.graphDepth,
    maxNodes: fullMode ? 180 : Math.min(96, 24 * state.graphDepth), maxEdges: fullMode ? 500 : Math.min(192, 48 * state.graphDepth), append: false,
    ...updates
  };
  const requestId = `graph-${Date.now()}-${Math.random()}`; state.graphRequestId = requestId; state.graphRequest = current; state.graphPending = true; state.graphError = null;
  if (updates.append !== true) state.graphLoadAll = false;
  clearTimeout(graphRequestTimer); graphRequestTimer = setTimeout(() => { if (state.graphPending && state.graphRequestId === requestId) { state.graphPending = false; state.graphError = 'The live graph query exceeded its 12-second bound. Retry or open Diagnostics for the retained host error.'; render(); } }, 12000);
  const modes = new Set(['full', 'overview', 'neighborhood', 'path', 'impact', 'dependencies', 'dependents', 'hubs', 'orphans', 'provenance']);
  vscode.postMessage({ type: 'graphQuery', requestId, view: state.graphView, mode: modes.has(current.mode) ? current.mode : 'neighborhood', cluster: current.cluster || '', node: current.node || '', target: current.target || '', query: current.query || '', relation: current.relation || '', direction: current.direction || 'both', kind: current.kind || '', status: current.status || '', offset: Math.max(0, Math.trunc(Number(current.offset || 0))), edgeOffset: Math.max(0, Math.trunc(Number(current.edgeOffset || 0))), depth: current.depth, maxNodes: current.maxNodes, maxEdges: current.maxEdges });
}
function nextGraphPageRequest() {
  const page = state.graphData?.page || {};
  if (state.graphPending || (!page.node_has_more && !page.edge_has_more)) return null;
  return { mode: 'full', cluster: state.graphCommunity, kind: state.graphKind, status: state.graphStatus, offset: page.next_node_offset || 0, edgeOffset: page.next_edge_offset || 0, append: true };
}
function mergeGraphPage(previous, next) {
  if (!previous || previous.mode !== 'full' || next?.mode !== 'full' || previous.view !== next.view) return next;
  const nodes = new Map((previous.nodes || []).map(item => [item.key, item]));
  for (const item of next.nodes || []) nodes.set(item.key, item);
  const edgeKey = edge => `${edge.source}\u0000${edge.relation}\u0000${edge.target}\u0000${edge.source_sha256 || ''}\u0000${edge.source_path || ''}\u0000${JSON.stringify(edge.evidence || [])}\u0000${edge.why || ''}`;
  const edges = new Map((previous.edges || []).map(item => [edgeKey(item), item]));
  for (const item of next.edges || []) edges.set(edgeKey(item), item);
  return {
    ...next,
    selected: nodes.has(previous.selected) ? previous.selected : next.selected,
    nodes: [...nodes.values()], edges: [...edges.values()],
    covered_nodes: nodes.size, covered_edges: edges.size,
    page: { ...(next.page || {}), loaded_nodes: nodes.size, loaded_edges: edges.size }
  };
}

function environmentMap() {
  const inventory = state.snapshot.environment;
  if (!inventory) return section('Environment capability map', 'DISCOVERY PENDING', empty('The bounded startup inventory is still running.'), '<button class="primary small" data-action="refreshEnvironment">Refresh now</button>');
  const summary = inventory.summary || {}; const dataset = state.environmentData[state.environmentScope];
  const scopes = [['graph', 'Semantic graph'], ['extensions', 'VS Code extensions'], ['tools', 'System tools'], ['environments', 'Virtual environments'], ['environment-files', '.env schemas'], ['python', 'Python packages'], ['npm', 'npm packages']];
  let content = '';
  if (!dataset) content = `<div class="catalog-loading"><span class="empty-ring"></span><p>Lazy-loading the selected hash-verified subject…</p></div>`;
  else if (dataset.error) content = `<div class="memory-errors" role="alert"><p>${esc(dataset.error)}</p><button data-action="refreshEnvironment">Refresh the environment inventory</button></div>`;
  else if (state.environmentScope === 'extensions') content = (dataset.records || []).map(item => `<button class="environment-row" data-action="environmentExtensionDetail" data-extension-id="${esc(item.id)}"><div><strong>${esc(item.name)}</strong><small>${esc(item.id)} · ${esc(item.version || 'version unavailable')}</small></div>${badge(item.active ? 'ACTIVE' : 'DETECTED', item.active ? 'success' : 'info')}<span>${number(item.capability_count)} capabilities · ${number(item.command_count)} commands · ${number(item.conflict_count)} conflicts</span></button>`).join('');
  else if (state.environmentScope === 'tools') content = (dataset.records || []).map(item => `<button class="environment-row" data-action="inspectEnvironmentRecord" data-environment-id="${esc(item.id)}"><div><strong>${esc(item.id)}</strong><small class="mono">${esc(item.executable || item.command)}</small></div>${badge(item.available ? 'AVAILABLE' : 'ABSENT', item.available ? 'success' : 'neutral')}<span>${esc(item.version || 'probe unavailable')} · ${esc(item.install_source || 'source unknown')} · ${esc(item.trust?.state || 'trust unknown')}</span></button>`).join('');
  else if (state.environmentScope === 'environments') content = (dataset.records || []).map(item => `<button class="environment-row" data-action="inspectEnvironmentRecord" data-environment-id="${esc(item.id)}"><div><strong>${esc(item.relative_path || item.path)}</strong><small class="mono">${esc(item.interpreter || 'interpreter unavailable')}</small></div>${badge(String(item.state || 'unknown').toUpperCase(), item.active ? 'success' : item.state === 'broken' || item.state === 'wrong-version' ? 'warning' : 'info')}<span>${esc(item.kind)} · Python ${esc(item.python_version || 'unknown')} · ${esc((item.evidence?.active_signals || []).join(', ') || 'no current active-use evidence')}</span></button>`).join('');
  else if (state.environmentScope === 'environment-files') content = (dataset.records || []).map(item => `<button class="environment-row" data-action="inspectEnvironmentRecord" data-environment-id="${esc(item.id)}"><div><strong>${esc(item.relative_path)}</strong><small class="mono">${esc(item.path)}</small></div>${badge(String(item.validation?.status || 'unknown').toUpperCase(), item.validation?.status === 'valid-metadata' ? 'success' : 'warning')}<span>${number(item.variable_count)} names · ${esc(item.exposure?.status || 'exposure unknown')} · values never retained</span></button>`).join('');
  else if (state.environmentScope === 'python') content = (dataset.records || []).map(item => `<article class="environment-row"><div><strong>${esc(item.name)}</strong><small>Python · ${esc(item.scope)}</small></div>${badge(item.version || 'unknown', 'info')}<span>installed-by → python/pip · available-to → Pacify-X</span></article>`).join('');
  else if (state.environmentScope === 'npm') content = (dataset.records || []).map(item => `<article class="environment-row"><div><strong>${esc(item.name)}</strong><small>npm · ${esc(item.scope)}</small></div>${badge(item.version || 'unknown', 'info')}<span>installed-by → npm · available-to → Pacify-X</span></article>`).join('');
  else content = `<div class="ontology-strip"><div><span>ONTOLOGY CHAIN</span><b>${number(inventory.ontology?.canonical_chain?.length)}</b><small>${esc((inventory.ontology?.canonical_chain || []).join(' → '))}</small></div><div><span>RELATIONS</span><b>${number(inventory.ontology?.predicates?.length)}</b><small>${esc((inventory.ontology?.predicates || []).join(' · '))}</small></div></div><div class="environment-graph">${(dataset?.edges || []).slice(0, 180).map(edge => `<div><span>${esc(edge.from)}</span><b>${esc(edge.predicate)}</b><span>${esc(edge.to)}</span></div>`).join('')}</div>`;
  return `<div class="metric-grid compact">${card('EXTENSIONS', number(summary.extensions), `${number(summary.active_extensions)} active`)}${card('TOOLS', number(summary.available_tools), `${number(summary.system_tools)} probed`)}${card('ENVIRONMENTS', number(summary.virtual_environments), `${number(summary.active_virtual_environments)} active`)}${card('.ENV SCHEMAS', number(summary.environment_files), `${number(summary.environment_variables)} variable names`)}</div><div class="environment-freshness"><b>${esc(String(inventory.freshness?.state || 'unknown').toUpperCase())}</b><span>Generation ${number(inventory.freshness?.generation)} · ${number(inventory.freshness?.age_seconds)}s old · discovery ${esc(inventory.discovery?.completeness || 'unknown')}</span></div><div class="catalog-tabs environment-tabs" role="group" aria-label="Environment inventory scope">${scopes.map(([id, label]) => `<button data-action="environmentScope" data-scope="${id}" aria-pressed="${state.environmentScope === id}" class="${state.environmentScope === id ? 'active' : ''}">${label}</button>`).join('')}</div>${section('Environment capability map', 'HASHED · PROJECT-OWNED · READ-ONLY', `<div class="environment-boundary"><b>${esc(inventory.snapshot_hash)}</b><span>No arbitrary extension activation · no installs · no credential values · no billable calls</span></div><div class="environment-list">${content || unavailable('No records were discovered for this subject.')}</div>`, '<button class="primary small" data-action="refreshEnvironment">Refresh map + graph</button>')}`;
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

function eventTimeline(limit) {
  const events = (state.coordination?.events || []).slice(-limit).reverse();
  return events.length ? `<div class="event-timeline">${events.map(event => `<article><i></i><div><strong>${esc(event.operation)}</strong><span>${esc(event.actor?.actor_id || 'system')} · ${esc(new Date(event.timestamp).toLocaleString())}</span><small>${esc(event.event_id)} · ${esc(event.after_hash?.slice(0, 12) || '')}</small></div></article>`).join('')}</div>` : empty('No rolling events have been recorded.');
}

function serviceGrid() {
  const s = state.snapshot; const connection = healthState.operational(s); const rows = [
    ['Pacify-X control plane', connection.label, connection.tone],
    ['Project map', healthState.feature(s, 'projectMap').available ? 'Available' : 'Unavailable', healthState.feature(s, 'projectMap').available ? 'success' : 'warning'],
    ['Canonical memory vault', healthState.feature(s, 'canonicalMemory').available ? 'Attached' : 'Detached; configure workspace + lease', healthState.feature(s, 'canonicalMemory').available ? 'success' : 'neutral'],
    ['Portable memory', state.coordination?.memory?.instrumented ? `${number(state.coordination.memory.record_count)} records; non-canonical` : 'Unavailable', state.coordination?.memory?.integrity?.valid ? 'info' : 'warning'],
    ['Cross-IDE ledger', healthState.feature(s, 'coordination').available ? 'Instrumented' : 'Unavailable', healthState.feature(s, 'coordination').available ? 'success' : 'warning'],
    ['Ollama', state.settings.ollamaEnabled ? 'Enabled; probe on model request' : 'Disabled', state.settings.ollamaEnabled ? 'info' : 'neutral'],
    ['TurboVec', turbovecDisplay(s).detail, turbovecDisplay(s).tone],
    ['MS+Enterprise', healthState.feature(s, 'enterpriseCatalog').available ? 'Catalog available; connectors remain offline' : 'Unavailable', healthState.feature(s, 'enterpriseCatalog').available ? 'info' : 'neutral']
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

function ensureSurfaceData() {
  if (!state.snapshot?.connected) return;
  const kinds = state.active === 'agents' ? [state.agentScope === 'enterprise' ? 'enterprise-agents' : 'agents']
    : state.active === 'agent-studio' ? ['agents']
      : state.active === 'workflow-studio' ? ['workflows']
        : state.active === 'skill-studio' ? ['skills']
          : state.active === 'knowledgeGraph' || state.active === 'knowledgeCore' ? ['graph']
            : state.active === 'skillsTools' ? [state.capabilityKind]
              : state.active === 'workflows' ? (state.workflowScope === 'environment' ? [] : [state.workflowScope === 'enterprise' ? 'enterprise-workflows' : 'workflows'])
                : state.active === 'diagnostics' ? ['enterprise-integrations'] : [];
  for (const kind of kinds) if (kind && !state.catalogs[kind] && !state.catalogRequests[kind]?.requestId) requestCatalog(kind);
  if (state.active === 'workflows' && state.workflowScope === 'environment' && !state.environmentData[state.environmentScope] && !state.environmentPending[state.environmentScope]) {
    state.environmentPending[state.environmentScope] = true; vscode.postMessage({ type: 'environmentQuery', subject: state.environmentScope, offset: 0, limit: 500 });
  }
  if (state.active === 'knowledgeGraph' && !state.graphPending && state.graphData?.view !== state.graphView) requestGraph({ view: state.graphView, mode: 'full', node: '', query: '', offset: 0, edgeOffset: 0 });
  if (state.active === 'plugins' && !state.environmentData.extensions && !state.environmentPending.extensions) {
    state.environmentPending.extensions = true; vscode.postMessage({ type: 'environmentQuery', subject: 'extensions', offset: 0, limit: 500 });
  }
  if (state.active === 'memory' && canonicalMemoryReady() && !state.memoryData && !state.memoryPending) requestMemory();
  if (state.active === 'activity' && !state.activityData && !state.activityPending) requestActivity();
  if (state.active === 'knowledgeCore' && !state.knowledgeData && !state.knowledgePending) requestKnowledge();
}
function canonicalMemoryReady() {
  return state.snapshot?.memory?.retrieval_ready === true;
}
function requestMemory(query = state.memoryQuery) {
  if (!canonicalMemoryReady()) {
    state.memoryPending = false; state.memoryRequestId = null; state.memoryData = null;
    return false;
  }
  state.memoryQuery = String(query || '').slice(0, 500); state.memoryPending = true;
  const requestId = `memory-${Date.now()}-${Math.random()}`; state.memoryRequestId = requestId;
  vscode.postMessage({ type: 'memoryQuery', requestId, query: state.memoryQuery, offset: state.memoryOffset, limit: 60, status: state.memoryStatus, projectId: state.memoryProject, source: state.memorySource });
  return true;
}
function requestActivity(updates = {}) {
  if (Object.hasOwn(updates, 'query')) state.activityQuery = String(updates.query || '').slice(0, 300);
  if (Object.hasOwn(updates, 'category')) state.activityCategory = String(updates.category || '').slice(0, 120);
  if (Object.hasOwn(updates, 'status')) state.activityStatus = String(updates.status || '').slice(0, 40);
  state.activityPending = true; const requestId = `activity-${Date.now()}-${Math.random()}`; state.activityRequestId = requestId;
  vscode.postMessage({ type: 'activityQuery', requestId, query: state.activityQuery, category: state.activityCategory, status: state.activityStatus, limit: 200 });
}
function requestKnowledge(query = state.knowledgeQuery) {
  state.knowledgeQuery = String(query || '').slice(0, 300); state.knowledgePending = true;
  vscode.postMessage({ type: 'studioOperation', kind: 'knowledge', operation: 'browse', payload: { query: state.knowledgeQuery, limit: 200 } });
}
function knowledgeProposalPayload(fields, canonicalRecords = []) {
  const id = String(fields?.id || '').trim(); const kind = String(fields?.kind || '').trim();
  const title = String(fields?.title || '').trim(); const summary = String(fields?.summary || '').trim();
  const source = String(fields?.source || '').trim(); const evidence = String(fields?.evidence || '').trim();
  if (!id || !kind || !summary || !source || !evidence) throw new Error('Record ID, kind, summary, declared source, and evidence reference are required.');
  const matchingHeads = (Array.isArray(canonicalRecords) ? canonicalRecords : []).filter(item => item?.record_id === id);
  if (matchingHeads.length > 1) throw new Error('The current Knowledge snapshot contains ambiguous canonical heads for this record ID. Refresh before proposing an update.');
  const candidate = { id, kind, title: title || id, summary };
  if (matchingHeads.length === 1) {
    const head = String(matchingHeads[0]?.candidate_sha256 || '');
    if (!/^[0-9a-f]{64}$/.test(head)) throw new Error('The current canonical head is malformed. Refresh and repair Knowledge state before proposing an update.');
    candidate.supersedes_sha256 = head;
  }
  return { candidate, source_ids: [source], evidence_refs: [evidence] };
}
function knowledgeProposalModal() {
  const sources = state.snapshot?.knowledgeCore?.records || [];
  const options = sources.filter(item => item.available).map(item => `<option value="${esc(item.id)}">${esc(item.id)} · ${esc(item.kind)}</option>`).join('');
  const evidence = sources.find(item => item.available && item.source_sha256)?.source_sha256;
  showModal('Propose knowledge candidate', 'CANDIDATE ONLY · SOURCE + EVIDENCE BOUND', `<p>This creates a governed candidate. It does not verify, approve, promote, or alter canonical knowledge.</p><p class="fine-print">If the record ID already has one current canonical head, this proposal is automatically bound to that exact head as an immutable update. Ambiguous, malformed, or changed heads fail closed during verification.</p><label class="form-field"><span>Record ID</span><input id="knowledge-id" placeholder="knowledge:decision-name"></label><label class="form-field"><span>Kind</span><input id="knowledge-kind" value="project-knowledge"></label><label class="form-field"><span>Title</span><input id="knowledge-title" placeholder="Human-readable title"></label><label class="form-field"><span>Summary</span><textarea id="knowledge-summary" rows="5" placeholder="Atomic, evidence-grounded statement"></textarea></label><label class="form-field"><span>Declared source</span><select id="knowledge-source">${options}</select></label><label class="form-field"><span>Evidence reference</span><input id="knowledge-evidence" class="mono" value="${evidence ? `sha256:${esc(evidence)}` : ''}" placeholder="sha256:&lt;64 hex&gt; or relative/path#sha256=&lt;64 hex&gt;"></label>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitKnowledgeProposal">Write candidate</button>');
}
function learningPipeline(pipelineId) { return state.knowledgeData?.learning?.pipelines?.find(item => item.pipeline_id === pipelineId); }
function learningJsonField(id, fallback = {}) {
  const control = document.getElementById(id); const value = JSON.parse(control?.value || JSON.stringify(fallback));
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${id} must contain one JSON object.`);
  return value;
}
function postLearningOperation(operation, payload) {
  state.knowledgePending = true;
  vscode.postMessage({ type: 'studioOperation', kind: 'knowledge', operation, payload });
  closeModal();
}
function learningObservationModal(pipelineId = '') {
  const pipeline = learningPipeline(pipelineId); const sources = pipeline?.source_ids || (state.snapshot?.knowledgeCore?.records || []).filter(item => item.available).slice(0, 1).map(item => item.id);
  const environment = state.snapshot?.environment?.content_sha256 || state.snapshot?.provenance?.environment_sha256 || '';
  showModal(pipeline ? 'Append operation evidence' : 'Create experience pipeline', 'HASHED EVIDENCE · NO LEARNED AUTHORITY', `<p>Captures one immutable operation outcome. It does not extract a pattern or change routing behavior. Supply evidence for the operation result itself; a source-file hash is not substituted automatically.</p><input type="hidden" id="learning-pipeline-id" value="${esc(pipelineId)}"><label class="form-field"><span>Operation ID</span><input id="learning-operation-id" placeholder="operation:repair-20260816-01"></label><label class="form-field"><span>Task class</span><input id="learning-task-class" value="repair"></label><label class="form-field"><span>Outcome</span><input id="learning-outcome" placeholder="verification passed; latency 18% lower"></label><div class="modal-detail-grid"><label class="form-field"><span>Metric name</span><input id="learning-metric" value="success_score"></label><label class="form-field"><span>Metric value</span><input id="learning-metric-value" type="number" step="any" value="1"></label></div><label class="form-field"><span>Capabilities (comma separated)</span><input id="learning-capabilities" placeholder="px-debug-repair, px-engineer"></label><label class="form-field"><span>Environment SHA-256</span><input id="learning-environment-sha" class="mono" value="${esc(environment)}" placeholder="64 lowercase hex characters"></label><label class="form-field"><span>Declared source IDs</span><input id="learning-source-ids" value="${esc(sources.join(', '))}" ${pipeline ? 'readonly' : ''}></label><label class="form-field"><span>Operation evidence references (one per line)</span><textarea id="learning-evidence-refs" class="mono" rows="3" placeholder="relative/path#sha256=&lt;actual hash&gt; or sha256:&lt;content hash&gt;"></textarea></label>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitLearningObservation">Capture evidence</button>', 'wide-modal');
}
function learningPatternModal(pipelineId) {
  const pipeline = learningPipeline(pipelineId); const metric = Object.keys(pipeline?.operation_evidence?.[0]?.measurements || {})[0] || '';
  showModal('Extract evidence pattern', 'HASHLESS AGGREGATION · HASHED PATTERN CANDIDATE', `<p>The live aggregation remains hashless. The resulting interpretation is frozen with the complete source-evidence Merkle root.</p><input type="hidden" id="learning-pipeline-id" value="${esc(pipelineId)}"><label class="form-field"><span>Metric shared by all observations</span><input id="learning-pattern-metric" value="${esc(metric)}"></label><label class="policy-switch"><input id="learning-higher-better" type="checkbox" checked><span>Higher values are better</span></label><label class="form-field"><span>Pattern interpretation</span><textarea id="learning-interpretation" rows="4" placeholder="Across this task class, the candidate procedure consistently…"></textarea></label><label class="form-field"><span>Applicability conditions (comma separated)</span><input id="learning-applicability" placeholder="task:repair, environment:windows, failure-signature:x"></label>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitLearningPattern">Freeze pattern</button>');
}
function learningHypothesisModal(pipelineId) {
  const template = JSON.stringify({ id: 'knowledge:method', kind: 'knowledge', title: 'Method revision', summary: 'Describe the evidence-bound procedure.' }, null, 2);
  showModal('Form testable hypothesis', 'TIER 1 INCUMBENT · TIER 2 CHALLENGER', `<p>Both artifacts become immutable revisions. Dependency paths are checked against their declared current hashes now and again at final validation.</p><input type="hidden" id="learning-pipeline-id" value="${esc(pipelineId)}"><label class="form-field"><span>Unit ID</span><input id="learning-unit-id" value="knowledge:method"></label><label class="form-field"><span>Promotable kind</span><select id="learning-unit-kind"><option>knowledge</option><option>memory</option><option>skill</option><option>orchestration</option><option>process</option><option>runtime</option><option>script</option></select></label><label class="form-field"><span>Testable claim</span><textarea id="learning-claim" rows="3" placeholder="For task class X, challenger Y improves metric Z without validation regression."></textarea></label><div class="two-col"><label class="form-field"><span>Incumbent artifact JSON</span><textarea id="learning-incumbent" class="mono" rows="10">${esc(template)}</textarea></label><label class="form-field"><span>Challenger artifact JSON</span><textarea id="learning-challenger" class="mono" rows="10">${esc(template)}</textarea></label></div><label class="form-field"><span>Dependency path → content SHA JSON</span><textarea id="learning-dependencies" class="mono" rows="4">{}</textarea></label>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitLearningHypothesis">Freeze hypothesis</button>', 'wide-modal');
}
function learningTrialModal(pipelineId) {
  showModal('Record bounded A/B trial', 'HASHED TRIAL EVIDENCE · CONSERVATIVE CONFIDENCE', `<p>At least six trials are required. An inconclusive comparison stays in trialing; it is never treated as a pass.</p><input type="hidden" id="learning-pipeline-id" value="${esc(pipelineId)}"><label class="form-field"><span>Winner</span><select id="learning-trial-winner"><option value="challenger">Challenger</option><option value="incumbent">Incumbent</option><option value="tie">Tie</option></select></label><label class="form-field"><span>Trial evidence reference</span><input id="learning-trial-evidence" class="mono" placeholder="sha256:&lt;64 hex&gt; or path#sha256=&lt;64 hex&gt;"></label>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitLearningTrial">Record trial</button>');
}
function learningResearchModal(pipelineId) {
  const references = JSON.stringify([{ uri: 'research:independent-validation', evidence_ref: '', independent: true }], null, 2);
  showModal('Independent research validation', 'REFERENCE EVIDENCE · OPTIONAL TIER 3', `<p>If a better alternative is found, a tier-three artifact is mandatory and must win its own bounded A/B confidence gate.</p><input type="hidden" id="learning-pipeline-id" value="${esc(pipelineId)}"><label class="form-field"><span>Research question</span><textarea id="learning-research-question" rows="3"></textarea></label><label class="form-field"><span>References JSON</span><textarea id="learning-research-references" class="mono" rows="7">${esc(references)}</textarea></label><label class="policy-switch"><input id="learning-better-alternative" type="checkbox"><span>Research found a potentially better alternative</span></label><label class="form-field"><span>Conclusion</span><textarea id="learning-research-conclusion" rows="3"></textarea></label><label class="form-field"><span>Tier-three artifact JSON (required only when checked)</span><textarea id="learning-secondary-artifact" class="mono" rows="7"></textarea></label>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitLearningResearch">Record research gate</button>', 'wide-modal');
}
function learningFinalValidationModal(pipelineId) {
  showModal('Final learning validation', 'DEPENDENCY CURRENT · FINAL EVIDENCE HASH', `<p>This computes a promotion decision only. Passing still admits a non-canonical knowledge proposal that must cross verify, approve, and promote separately.</p><input type="hidden" id="learning-pipeline-id" value="${esc(pipelineId)}"><label class="form-field"><span>Final validation evidence</span><input id="learning-final-evidence" class="mono" placeholder="sha256:&lt;64 hex&gt; or path#sha256=&lt;64 hex&gt;"></label><label class="form-field"><span>Partial units (comma separated, optional)</span><input id="learning-partial-units"></label>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitLearningFinalValidation">Run final gate</button>');
}
function learningReuseModal(pipelineId) {
  showModal('Record measured reuse', 'CUMULATIVE COUNTS · NON-DESTRUCTIVE DECAY', `<p>Enter cumulative reuse totals. A decay decision never deletes or silently rewrites canonical knowledge.</p><input type="hidden" id="learning-pipeline-id" value="${esc(pipelineId)}"><div class="modal-detail-grid"><label class="form-field"><span>Uses</span><input id="learning-reuse-uses" type="number" min="0" value="0"></label><label class="form-field"><span>Successes</span><input id="learning-reuse-successes" type="number" min="0" value="0"></label><label class="form-field"><span>Regressions</span><input id="learning-reuse-regressions" type="number" min="0" value="0"></label></div>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitLearningReuse">Record reuse</button>');
}
function requestCatalog(kind, updates = {}) {
  const current = { query: '', status: '', offset: 0, limit: 50, sort: 'label', ...(state.catalogRequests[kind] || {}), ...updates };
  state.catalogRequests[kind] = current; const requestId = `${kind}-${Date.now()}-${Math.random()}`; current.requestId = requestId;
  vscode.postMessage({ type: 'catalogQuery', kind, requestId, ...current });
}

function invalidateCatalog(kind, updates = {}) {
  delete state.catalogs[kind];
  requestCatalog(kind, updates);
  if (app.querySelector('.control-modal')) deferredRender = true;
  else render();
}

function requestOperationalCards(updates = {}) {
  const request = { ...state.operationalCardsRequest, ...updates };
  request.offset = Math.max(0, Math.trunc(Number(request.offset || 0)));
  request.limit = Math.max(1, Math.min(100, Math.trunc(Number(request.limit || 50))));
  const requestId = `operational-cards-${Date.now()}-${Math.random()}`;
  state.operationalCardsRequest = request; state.operationalCardsRequestId = requestId;
  vscode.postMessage({ type: 'operationalCardsQuery', requestId, query: String(request.query || ''), state: String(request.state || ''), severity: String(request.severity || ''), surface: String(request.surface || ''), owner: String(request.owner || ''), evidenceGap: request.evidenceGap === true, offset: request.offset, limit: request.limit });
}

function commandCenter() {
  showModal('Control center', 'OPERABLE LOCAL ACTIONS', `<div class="control-grid"><button data-action="refresh"><b>Synchronize</b><span>Re-read Pacify-X, Git and coordination state.</span></button><button data-action="validate"><b>Validate</b><span>Run the canonical control-plane validator.</span></button><button data-action="newParallelPlan"><b>Parallel plan</b><span>Create a dependency and claim-safe task graph.</span></button><button data-action="openCoordinationHandoff"><b>Resume handoff</b><span>Open the cross-IDE rolling checkpoint.</span></button><button data-action="contextSnapshot"><b>Context snapshot</b><span>Open bounded provider-neutral context.</span></button><button data-action="teamPackPreview"><b>Team package</b><span>Dry-run, inspect collisions, and stage non-canonical candidates.</span></button><button data-action="enterpriseDoctor"><b>MS+Enterprise</b><span>Run the offline boundary and readiness doctor.</span></button><button data-action="cleanupManager"><b>Storage & cleanup</b><span>Audit, select, dispose and retain a receipt.</span></button><button data-action="openSettings"><b>Settings</b><span>Configure local behavior.</span></button></div>`);
}

function skillSemanticQueryModal(domain = 'px-standard') {
  const skillDomains = ['px-standard', 'microsoft-vendor', 'enterprise-restricted', 'user-preserved'];
  const normalizedDomain = skillDomains.includes(domain) ? domain : 'px-standard';
  showModal('Query the PX skill broker', 'SEMANTIC METADATA FIRST · MAXIMUM THREE RESULTS', `<p class="modal-note">PX searches only the selected domain. No skill body is loaded, admitted, changed, or executed by this query.</p><input type="hidden" id="skill-query-domain" value="${esc(normalizedDomain)}"><label class="form-field"><span>Task or capability needed</span><textarea id="skill-query-goal" rows="5" maxlength="1000" placeholder="Describe the outcome, constraints, and relevant system or failure signature."></textarea></label><dl class="modal-detail"><div><dt>Domain</dt><dd>${esc(normalizedDomain)}</dd></div><div><dt>Result bound</dt><dd>At most 3 eligible metadata candidates</dd></div><div><dt>Body loading</dt><dd>Separate exact-ID action after selection</dd></div></dl>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitSkillQuery">Find eligible skills</button>');
  requestAnimationFrame(() => document.getElementById('skill-query-goal')?.focus());
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
function releaseTaskModal(taskId) {
  showModal('Release task claim', 'EXPLICIT CLAIM DISPOSITION', `<input type="hidden" id="release-task" value="${esc(taskId)}"><p>Releasing this claim returns the task to the coordination pool. Existing task evidence is preserved.</p><label class="form-field"><span>Reason for release</span><textarea id="release-reason" rows="4" maxlength="1000" placeholder="Why is this claim being released, and what should the next owner know?"></textarea></label><label class="checkbox-field"><input id="release-confirm" type="checkbox"><span>I confirm that I am releasing claim ${esc(taskId)}.</span></label><p class="studio-warning" data-release-validation hidden role="alert"></p>`, '<button data-action="closeModal">Cancel</button><button class="danger" data-action="submitReleaseTask">Release claim</button>');
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

function addWorkflowNode(kind = 'task', position = null) {
  if (studioEditor?.kind !== 'workflow') return;
  const admittedKinds = new Set(['task', 'validation', 'approval', 'branch', 'join']);
  if (!admittedKinds.has(kind)) return;
  const draft = studioEditor.draft; const serial = draft.nodes.length + 1; const token = kind === 'validation' ? 'validate' : kind === 'approval' ? 'approve' : kind;
  const config = kind === 'validation' ? { checks: [{ id: 'check:input-exists', source: 'inputs', port: 'value', operator: 'exists' }] } : {};
  const ports = kind === 'branch'
    ? { inputs: [{ name: 'value', data_type: 'boolean', required: true }], outputs: [{ name: 'value', data_type: 'boolean', required: true }] }
    : kind === 'join'
      ? { inputs: [{ name: 'true-value', data_type: 'boolean', required: false }, { name: 'false-value', data_type: 'boolean', required: false }], outputs: [{ name: 'true-value', data_type: 'boolean', required: false }, { name: 'false-value', data_type: 'boolean', required: false }] }
      : { inputs: [{ name: 'value', data_type: 'string', required: true }], outputs: [{ name: 'value', data_type: 'string', required: true }] };
  const node = studioEditors.normalizeWorkflow({ nodes: [{ node_id: `step:${token}-${serial}`, kind, config, executor_binding_id: draft.bindings?.[0]?.binding_id || 'binding:my-workflow', ...ports, effect_grant_ids: draft.grants?.[0]?.grant_id ? [draft.grants[0].grant_id] : [], approval_required: kind === 'approval', position: position || { x: 40 + (serial % 3) * 220, y: 40 + Math.floor(serial / 3) * 140 } }] }).nodes[0];
  draft.nodes.push(node); studioSelectedNode = node.node_id; refreshStudioEditor('[data-workflow-field="node_id"]');
}

function connectWorkflowEdge(sourceNode, sourcePort, targetNode, targetPort, condition = 'always') {
  const draft = studioEditor?.kind === 'workflow' ? studioEditor.draft : null; if (!draft) return;
  const source = draft.nodes.find(node => node.node_id === sourceNode); const target = draft.nodes.find(node => node.node_id === targetNode);
  const output = source?.outputs.find(port => port.name === sourcePort); const input = target?.inputs.find(port => port.name === targetPort); let reason = '';
  if (!source || !target || !output || !input) reason = 'Select an existing source output and target input.';
  else if (sourceNode === targetNode) reason = 'A node cannot connect to itself.';
  else if (output.data_type !== input.data_type) reason = `${output.data_type} cannot drive ${input.data_type}.`;
  else if (draft.edges.some(edge => edge.source_node === sourceNode && edge.source_port === sourcePort && edge.target_node === targetNode && edge.target_port === targetPort)) reason = 'That exact edge already exists.';
  else if (draft.edges.some(edge => edge.target_node === targetNode && edge.target_port === targetPort)) reason = `${targetNode}.${targetPort} already has a driver.`;
  else {
    const adjacency = new Map(draft.nodes.map(node => [node.node_id, []])); for (const edge of draft.edges) adjacency.get(edge.source_node)?.push(edge.target_node);
    const pending = [targetNode]; const visited = new Set(); while (pending.length) { const current = pending.pop(); if (current === sourceNode) { reason = 'That edge would create a workflow cycle.'; break; } if (visited.has(current)) continue; visited.add(current); pending.push(...(adjacency.get(current) || [])); }
  }
  if (reason) { const status = document.querySelector('[data-studio-validation]'); status?.insertAdjacentHTML('beforeend', `<span class="studio-warning">Connection blocked: ${esc(reason)}</span>`); return; }
  draft.edges.push({ source_node: sourceNode, source_port: sourcePort, target_node: targetNode, target_port: targetPort, condition }); workflowConnectionStart = null; refreshStudioEditor('[data-workflow-editor-canvas]');
}
function connectWorkflowEdgeFromControls() {
  const [sourceNode, sourcePort] = (document.querySelector('[data-edge-source-endpoint]')?.value || '').split('|');
  const [targetNode, targetPort] = (document.querySelector('[data-edge-target-endpoint]')?.value || '').split('|');
  connectWorkflowEdge(sourceNode, sourcePort, targetNode, targetPort, document.querySelector('[data-edge-condition]')?.value || 'always');
}

function persistStudioMetadata() {
  persistDashboardState();
}

function agentList(value) { return String(value || '').split(',').map(item => item.trim()).filter(Boolean); }
function updateAgentDraftFromControl(control) {
  if (studioEditor?.kind !== 'agent') return false;
  const draft = studioEditor.draft; const value = control.value;
  if (control.matches?.('[data-agent-root-field],[data-agent-list-field],[data-agent-json-field],[data-agent-model-field],[data-agent-host-model],[data-agent-binding-field],[data-agent-grant-field],[data-agent-required-test]')) agentGraphDirty = true;
  if (control.dataset.agentRequiredTest) {
    const selected = new Set(Array.isArray(draft.required_tests) ? draft.required_tests : []);
    if (control.checked) selected.add(control.dataset.agentRequiredTest); else selected.delete(control.dataset.agentRequiredTest);
    draft.required_tests = agentStructuralChecks.map(check => check.id).filter(testId => selected.has(testId));
    refreshStudioEditor(`[data-agent-required-test="${CSS.escape(control.dataset.agentRequiredTest)}"]`); return true;
  }
  if (control.matches?.('[data-agent-host-model]')) {
    const selected = studioModelCatalog.find(item => item.id === value);
    draft.model.model_id = value || 'auto';
    if (selected) { draft.model.vendor = selected.vendor || ''; draft.model.family = selected.family || ''; draft.model.version = selected.version || ''; }
    refreshStudioEditor('[data-agent-host-model]'); return true;
  }
  if (control.dataset.agentRootField) { draft[control.dataset.agentRootField] = value; updateAgentValidationBox(); return true; }
  if (control.dataset.agentListField) { draft[control.dataset.agentListField] = agentList(value); updateAgentValidationBox(); return true; }
  if (control.dataset.agentModelField) {
    const field = control.dataset.agentModelField;
    draft.model[field] = ['max_output_tokens', 'temperature'].includes(field) ? Number(value) : value.trim();
    if (field === 'provider') {
      draft.harness_id = ['vscode-lm', 'pacify-local'].includes(value) ? 'harness:vscode-lm' : 'harness:px';
      draft.model.vendor = value === 'pacify-local' ? 'pacify-local' : '';
      draft.model.family = '';
      draft.model.model_id = 'auto';
      draft.model.version = 'auto';
      refreshStudioEditor('[data-agent-model-field="provider"]');
      return true;
    }
    updateAgentValidationBox(); return true;
  }
  if (control.dataset.agentJsonField) {
    try { draft[control.dataset.agentJsonField] = JSON.parse(value || '{}'); control.setCustomValidity(''); }
    catch (error) { control.setCustomValidity(`Invalid JSON schema: ${error.message}`); }
    updateAgentValidationBox(); return true;
  }
  if (control.dataset.agentBindingField) {
    const binding = draft.bindings[Number(control.dataset.index)]; if (!binding) return true;
    const field = control.dataset.agentBindingField; const prior = binding[field];
    binding[field] = ['effect_grant_ids', 'evidence_refs'].includes(field) ? agentList(value) : field === 'credential_namespace' ? value.trim() || null : value.trim();
    if (field === 'binding_id') draft.capability_binding_ids = draft.capability_binding_ids.map(id => id === prior ? binding[field] : id);
    updateAgentValidationBox(); return true;
  }
  if (control.dataset.agentGrantField) {
    const grant = draft.grants[Number(control.dataset.index)]; if (!grant) return true;
    const field = control.dataset.agentGrantField; const prior = grant[field];
    grant[field] = ['effects', 'scope_roots', 'evidence_refs'].includes(field) ? agentList(value) : field === 'expires_utc' ? value.trim() || null : value.trim();
    if (field === 'grant_id') { draft.effect_grant_ids = draft.effect_grant_ids.map(id => id === prior ? grant[field] : id); for (const binding of draft.bindings) binding.effect_grant_ids = binding.effect_grant_ids.map(id => id === prior ? grant[field] : id); }
    updateAgentValidationBox(); return true;
  }
  return false;
}

function updateWorkflowValidationBox() {
  if (studioEditor?.kind !== 'workflow') return;
  studioEditor.draft.editor_layout = Object.fromEntries((studioEditor.draft.nodes || []).map(node => [node.node_id, { x: Number(node.position?.x || 0), y: Number(node.position?.y || 0) }]));
  const validation = studioEditors.validateWorkflow(studioEditor.draft); const box = document.querySelector('[data-studio-validation]');
  if (box) { box.classList.toggle('passed', validation.valid); box.classList.toggle('failed', !validation.valid); box.innerHTML = `<b>${validation.valid ? 'Typed workflow is structurally valid' : `${validation.issues.length} structural issue(s)`}</b>${validation.issues.map(issue => `<span>${esc(issue)}</span>`).join('')}`; }
  const save = document.querySelector('[data-control-id="studio-save-candidate"]');
  if (save) { save.disabled = !validation.valid; save.title = validation.valid ? 'Save immutable candidate' : 'Resolve every structural issue before saving'; }
}

function updateWorkflowAuthorityFromControl(control) {
  if (studioEditor?.kind !== 'workflow') return false;
  const draft = studioEditor.draft; const value = control.value;
  if (control.matches('[data-workflow-binding-adapter]')) {
    const binding = draft.bindings[Number(control.dataset.index)]; if (!binding) return true;
    draft.executor_adapters = { ...(draft.executor_adapters || {}), [binding.binding_id]: value };
    draft.authority_definition_state = 'supplied-for-new-revision'; updateWorkflowValidationBox(); return true;
  }
  if (control.dataset.workflowBindingField) {
    const binding = draft.bindings[Number(control.dataset.index)]; if (!binding) return true;
    const field = control.dataset.workflowBindingField; const prior = binding[field];
    const next = ['effect_grant_ids', 'evidence_refs'].includes(field) ? agentList(value) : field === 'credential_namespace' ? value.trim() || null : value.trim();
    if (field === 'binding_id' && draft.bindings.some((item, index) => index !== Number(control.dataset.index) && item.binding_id === next)) { control.setCustomValidity('Workflow binding IDs must be unique.'); control.reportValidity(); return true; }
    control.setCustomValidity(''); binding[field] = next;
    if (field === 'binding_id' && binding[field] !== prior) {
      if (Object.hasOwn(draft.executor_adapters || {}, prior)) { draft.executor_adapters[binding[field]] = draft.executor_adapters[prior]; delete draft.executor_adapters[prior]; }
      for (const node of draft.nodes) if (node.executor_binding_id === prior) node.executor_binding_id = binding[field];
    }
    draft.authority_definition_state = 'supplied-for-new-revision'; updateWorkflowValidationBox(); return true;
  }
  if (control.dataset.workflowGrantField) {
    const grant = draft.grants[Number(control.dataset.index)]; if (!grant) return true;
    const field = control.dataset.workflowGrantField; const prior = grant[field];
    const next = ['effects', 'scope_roots', 'evidence_refs'].includes(field) ? agentList(value) : field === 'expires_utc' ? value.trim() || null : value.trim();
    if (field === 'grant_id' && draft.grants.some((item, index) => index !== Number(control.dataset.index) && item.grant_id === next)) { control.setCustomValidity('Workflow effect grant IDs must be unique.'); control.reportValidity(); return true; }
    control.setCustomValidity(''); grant[field] = next;
    if (field === 'grant_id' && grant[field] !== prior) { for (const binding of draft.bindings) binding.effect_grant_ids = binding.effect_grant_ids.map(id => id === prior ? grant[field] : id); for (const node of draft.nodes) node.effect_grant_ids = node.effect_grant_ids.map(id => id === prior ? grant[field] : id); }
    draft.authority_definition_state = 'supplied-for-new-revision'; updateWorkflowValidationBox(); return true;
  }
  return false;
}

app.addEventListener('click', event => {
  if (event.target.classList.contains('modal-backdrop')) { closeModal(); return; }
  const surfaceButton = event.target.closest('[data-surface]');
  if (surfaceButton) {
    const requested = surfaceButton.dataset.surface;
    if (advancedSurfaces.some(([id]) => id === requested) && !state.settings.showAdvancedSurfaces) { postHostAction('openSettings', 'openSettings'); return; }
    state.active = requested;
    state.advancedOpen = false;
    render();
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
    document.getElementById('main-content')?.focus();
    return;
  }
  const control = event.target.closest('[data-action]'); const action = control?.dataset.action; if (!action) return;
  if (control.disabled) return;
  if (studioEditor?.kind === 'agent' && ['agentAddBinding', 'agentRemoveBinding', 'agentAddGrant', 'agentRemoveGrant', 'agentAddTopologyNode', 'agentRemoveTopologyNode', 'agentAutoLayout'].includes(action)) agentGraphDirty = true;
  if (action === 'closeModal') { closeModal(); return; }
  if (action === 'commandCenter') { commandCenter(); return; }
  if (action === 'inspectMetric') {
    const metric = {
      schema_version: 'px.dashboard-metric/1.0',
      surface: state.active,
      label: String(control.dataset.metricLabel || 'Metric'),
      value: String(control.dataset.metricValue || 'Unavailable'),
      detail: String(control.dataset.metricDetail || ''),
      snapshot_generated_at: state.snapshot?.generatedAt || null,
      authority: 'observational current snapshot; non-authorizing'
    };
    showInformationModal(metric.label, 'OBSERVED METRIC · CURRENT SNAPSHOT', metric, `<p><strong>${esc(metric.value)}</strong></p><p>${esc(metric.detail || 'No additional metric detail is available.')}</p><p class="fine-print">This is a read-only projection of the current dashboard snapshot. It grants no authority and makes no health or certification claim beyond the displayed record.</p>`);
    return;
  }
  if (action === 'newParallelPlan') { newParallelPlanModal(); return; }
  if (action === 'submitParallelPlan') { try { vscode.postMessage({ type: 'createParallelPlan', plan: parsePlan() }); closeModal(); } catch (error) { showModal('Plan blocked', 'VALIDATION', `<p>${esc(error.message)}</p>`); } return; }
  if (action === 'capabilityTab') { state.capabilityKind = control.dataset.kind; render(); return; }
  if (action === 'openStudioDraft') { beginStudioAuthoring(control.dataset.kind); return; }
  if (action === 'setupStudio') { const requestId = studioAllocationRequestId(); pendingStudioSetup = { requestId }; showModal('Setting up Studio', 'ONE CONFIRMATION · TWO EDITABLE REVISIONS · BOUNDED LOCAL RUNS', '<div class="cleanup-loading"><span class="empty-ring"></span><p>The host will create or reuse a local starter agent and workflow, validate their authority, admit them, and run one bounded check for each.</p></div>'); vscode.postMessage({ type: 'setupStudio', requestId }); return; }
  if (action === 'resumeWorkingStudioDraft') { resumeWorkingStudioDraft(control.dataset.kind); return; }
  if (action === 'discardWorkingStudioDraft') { const kind = control.dataset.kind; studioWorkingSourceBinding = null; clearWorkingStudioDraft(kind); closeModal(); openStudioDraftModal(kind); return; }
  if (action === 'refreshHostModels') { vscode.postMessage({ type: 'listHostModels' }); return; }
  if (action === 'openStudioRuns') { const kind = control.dataset.kind; const requestId = studioAllocationRequestId(); pendingStudioRunQuery = { requestId, kind, operation: 'runs' }; showModal('Loading durable runs', 'AUTHENTICATED STUDIO STATE', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Reading authenticated durable run heads and their event-chain anchors.</p></div>'); vscode.postMessage({ type: 'studioOperation', requestId, kind, operation: 'runs', payload: { limit: 100 } }); return; }
  if (action === 'skillSemanticQuery') { skillSemanticQueryModal(control.dataset.domain); return; }
  if (action === 'submitSkillQuery') { const goal = document.getElementById('skill-query-goal')?.value.trim(); const domain = document.getElementById('skill-query-domain')?.value; if (!goal) { document.getElementById('skill-query-goal')?.focus(); return; } showModal('Searching eligible skills', 'BOUNDED SEMANTIC BROKER', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Reading admitted metadata. No skill body is being loaded.</p></div>'); vscode.postMessage({ type: 'skillQuery', goal, domain }); return; }
  if (action === 'hydrateSkillCandidate') { showModal('Loading selected skill', 'EXACT ID · ONE BODY', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Hydrating exactly one admitted skill body.</p></div>'); vscode.postMessage({ type: 'skillHydrate', skill: control.dataset.skillId, domain: control.dataset.domain }); return; }
  if (action === 'compareSkillOriginal') { const skill = String(control.dataset.skillId || ''); if (!/^[a-z0-9][a-z0-9._:-]{1,127}$/.test(skill)) { showModal('Comparison blocked', 'EXACT PX ID REQUIRED', '<p>The selected record does not expose a valid PX-standard skill identity.</p>'); return; } const requestId = `skill-compare-${Date.now()}-${Math.random()}`; pendingSkillComparison = Object.freeze({ requestId, skill }); showModal(`Comparing ${esc(skill)}`, 'VERIFIED PACKAGE TREES · READ ONLY', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Hashing the exact PX package and immutable preserved original. No body is hydrated or changed.</p></div>'); vscode.postMessage({ type: 'skillCompare', requestId, skill }); return; }
  if (action === 'studioRunAction') { const kind = control.dataset.kind; const operation = control.dataset.operation; let payload = operation === 'reconcile' ? { stale_after_seconds: 60 } : { run_id: control.dataset.runId }; if (operation === 'resume') { const subject = control.dataset.subjectId || ''; const version = control.dataset.version || ''; const identityKey = kind === 'agent' ? 'agent_id' : 'workflow_id'; const sessionMatches = studioSession?.kind === kind && String(studioSession.payload?.[identityKey] || '') === subject && String(studioSession.payload?.version || '') === version; if (!sessionMatches) { const exact = exactStudioCatalogPayload(kind, subject, version); if (exact) studioSession = { kind, payload: exact }; } if (!studioSession || studioSession.kind !== kind || String(studioSession.payload?.[identityKey] || '') !== subject || String(studioSession.payload?.version || '') !== version) { showModal('Exact resume context unavailable', 'FAIL CLOSED', `<p>Load the authenticated ${esc(subject)} @ ${esc(version)} revision from its catalog. Resume will not substitute another transient Studio session.</p>`); return; } payload = { ...structuredClone(studioSession.payload), run_id: control.dataset.runId }; } const requestId = studioAllocationRequestId(); pendingStudioRunQuery = { requestId, kind, operation, runId: String(payload.run_id || '') }; vscode.postMessage({ type: 'studioOperation', requestId, kind, operation, payload }); return; }
  if (action === 'openStudioFromCatalog') { const record = studioSourceRecord || modalRecord || {}; const kind = control.dataset.kind; studioVersionAllocation = null; studioWorkingSourceBinding = null; studioVersionAllocationProof = null; studioSaveRequest = null; studioPackageRequest = null; studioPendingSkillPackage = null; closeModal(); requestStudioVersionAllocation(kind, record); return; }
  if (action === 'importCatalogDefinition') { const record = studioSourceRecord || modalRecord || {}; const kind = control.dataset.kind; if (!['agent', 'workflow'].includes(kind)) return; closeModal(); importCatalogDefinitionIntoStudio(kind, record); return; }
  if (action === 'operateStudioRevision') {
    const record = studioSourceRecord || modalRecord || {};
    const details = record.details || record;
    const kind = control.dataset.kind;
    const status = String(record.status || record.identity?.status || '').toLowerCase();
    if (!['agent', 'workflow', 'skill'].includes(kind)) { showModal('Revision is not operable', 'EXACT STUDIO REVISION REQUIRED', '<p>Only an exact durable Studio revision can enter lifecycle or execution context.</p>'); return; }
    if (kind === 'skill' && (String(record._catalogKind || '') !== 'skills' || String(record.kind || '') !== 'studio-skill-revision')) { showModal('Revision is not operable', 'EXACT STUDIO SKILL REQUIRED', '<p>Only an exact PX-standard Skill Studio revision can resume its lifecycle.</p>'); return; }
    const payload = kind === 'agent' ? studioEditors.normalizeAgent(details) : kind === 'workflow' ? studioEditors.normalizeWorkflow(details) : studioEditors.normalizeSkill(details);
    studioSession = { kind, payload };
    if (status === 'candidate') {
      closeModal();
      studioLifecycleModal(kind, 'create', details);
      return;
    }
    if (kind === 'skill') { showModal('Revision is not operable', 'CANDIDATE SKILL REQUIRED', '<p>Only a durable Skill candidate resumes here. Admitted and promoted revisions expose their eligible exact actions separately.</p>'); return; }
    if (details.lifecycle_authentication?.authenticated !== true || status !== 'admitted') { showModal('Revision is not operable', 'AUTHENTICATED ADMISSION REQUIRED', '<p>This revision is neither a resumable durable candidate nor an exact authenticated admitted revision.</p>'); return; }
    const identity = payload[kind === 'agent' ? 'agent_id' : 'workflow_id'];
    closeModal();
    showInformationModal(`${identity} @ ${payload.version}`, 'EXACT AUTHENTICATED REVISION · OPERATIONS READY', payload, `<p>This exact revision is loaded without changing its version. Runtime inputs remain ephemeral.</p>${humanRecord(payload)}<div class="action-grid studio-actions"><button data-action="studioLifecycle" data-kind="${esc(kind)}" data-operation="${kind === 'agent' ? 'preview' : 'dry-run'}">${kind === 'agent' ? 'Preview exact execution' : 'Preview workflow plan'}</button><button class="primary" data-action="studioLifecycle" data-kind="${esc(kind)}" data-operation="start">Start exact revision</button></div>`);
    return;
  }
  if (action === 'loadSkillPackageEditor') { requestSkillPackageEditor(studioSourceRecord || modalRecord || {}); return; }
  if (action === 'submitStudioDraft') { const input = document.getElementById('studio-draft-json') || document.getElementById('studio-skill-file') || document.querySelector('[data-agent-root-field="instructions"]'); try { const payload = studioEditorPayload(control); const validation = control.dataset.kind === 'agent' ? studioEditors.validateAgent(payload) : control.dataset.kind === 'workflow' ? studioEditors.validateWorkflow(payload) : studioEditors.validateSkill(payload); if (!validation.valid) throw new Error(validation.issues.join(' ')); const requestId = studioAllocationRequestId(); studioSession = { kind: control.dataset.kind, payload }; studioSaveRequest = { requestId, kind: control.dataset.kind }; control.disabled = true; control.textContent = 'Awaiting host approval…'; document.querySelectorAll('[data-action="closeModal"]').forEach(button => { if (!button.classList.contains('modal-close')) button.textContent = 'Detach — save may continue'; button.setAttribute('title', 'Closing stops live updates only. An already authorized host operation may still commit.'); button.setAttribute('aria-label', 'Detach from in-flight save; authorized host work may continue'); }); document.querySelector('[data-studio-validation]')?.insertAdjacentHTML('beforeend', '<span class="studio-warning" data-studio-detach-notice>Closing or pressing Escape now detaches this view; it cannot cancel an already authorized host commit.</span>'); vscode.postMessage({ type: 'createStudioDraft', requestId, kind: control.dataset.kind, payload }); } catch (error) { studioSaveRequest = null; input?.setCustomValidity(`Invalid Studio definition: ${error.message}`); input?.reportValidity(); } return; }
  if (action === 'acceptStudioVersionSuggestion') { const allocation = studioVersionAllocation; const version = String(allocation?.candidate_version || ''); if (!studioEditor || !version) return; if (studioEditor.kind === 'skill') syncSkillEditorFile(); studioEditor.draft.version = version; if (studioEditor.kind === 'skill') { studioEditor.draft = studioEditors.synchronizeSkillIdentityFiles(studioEditor.draft); const file = document.getElementById('studio-skill-file'); if (file?.dataset.filePath) file.value = studioEditor.draft.editor_files?.[file.dataset.filePath] || ''; } const input = document.getElementById('studio-version'); if (input) { input.value = version; input.dispatchEvent(new Event('input', { bubbles: true })); } document.querySelector('[data-studio-version-conflict]')?.remove(); const validation = studioEditor.kind === 'agent' ? studioEditors.validateAgent(studioEditor.draft) : studioEditor.kind === 'workflow' ? studioEditors.validateWorkflow(studioEditor.draft) : studioEditors.validateSkill(studioEditor.draft); const save = document.querySelector('[data-action="submitStudioDraft"]'); if (save) { save.disabled = !validation.valid; save.textContent = 'Save immutable candidate'; } persistWorkingStudioDraft(); return; }
  if (action === 'agentPortConnect') {
    if (studioEditor?.kind !== 'agent') return;
    const direction = control.dataset.direction;
    if (direction === 'output') {
      agentConnectionStart = { node: control.dataset.nodeId || '', port: control.dataset.port || '' };
      refreshStudioEditor(`[data-action="agentPortConnect"][data-direction="output"][data-node-id="${CSS.escape(agentConnectionStart.node)}"][data-port="${CSS.escape(agentConnectionStart.port)}"]`);
      return;
    }
    if (direction !== 'input') return;
    if (!agentConnectionStart) {
      const status = document.querySelector('.agent-connection-status span');
      if (status) status.textContent = 'Select an output port before choosing an input.';
      return;
    }
    try {
      const graph = studioEditors.editAgentBuilderEdge(studioEditor.draft, currentAgentGraph(studioEditor.draft).graph, {
        type: 'add',
        source_node: agentConnectionStart.node,
        source_port: agentConnectionStart.port,
        target_node: control.dataset.nodeId || '',
        target_port: control.dataset.port || ''
      });
      agentWorkingGraph = graph;
      studioEditor.draft.builder_graph = structuredClone(graph);
      agentConnectionStart = null;
      agentGraphDirty = true;
      refreshStudioEditor('[data-agent-editor-canvas]');
    } catch (error) {
      const status = document.querySelector('.agent-connection-status span');
      if (status) status.textContent = `Connection blocked: ${error.message}`;
    }
    return;
  }
  if (action === 'agentCancelConnection') { agentConnectionStart = null; refreshStudioEditor('[data-agent-editor-canvas]'); return; }
  if (action === 'agentRemoveEdge') {
    if (studioEditor?.kind !== 'agent') return;
    try {
      const graph = studioEditors.editAgentBuilderEdge(studioEditor.draft, currentAgentGraph(studioEditor.draft).graph, { type: 'remove', edge_id: control.dataset.edgeId || '' });
      agentWorkingGraph = graph;
      studioEditor.draft.builder_graph = structuredClone(graph);
      agentConnectionStart = null;
      agentGraphDirty = true;
      refreshStudioEditor('[data-agent-editor-canvas]');
    } catch (error) { showModal('Agent connection edit blocked', 'CLOSED AGENTSPEC CONNECTION CONTRACT', `<p>${esc(error.message)}</p>`); }
    return;
  }
  if (action === 'agentAddTopologyNode' || action === 'agentRemoveTopologyNode') { try { const edited = studioEditors.editAgentBuilderNode(studioEditor?.draft, currentAgentGraph(studioEditor?.draft).graph, { type: action === 'agentAddTopologyNode' ? 'add' : 'remove', kind: control.dataset.agentKind, node_id: control.dataset.agentNodeId }); studioEditor.draft = edited.draft; agentWorkingGraph = edited.graph; agentSelectedSection = edited.selected_node_id.replace(/^agent-node:/, ''); agentConnectionStart = null; agentGraphDirty = true; refreshStudioEditor(`[data-agent-node-id="${CSS.escape(edited.selected_node_id)}"]`); } catch (error) { showModal('Agent topology edit blocked', 'CLOSED AGENTSPEC NODE CONTRACT', `<p>${esc(error.message)}</p>`); } return; }
  if (action === 'agentSelectNode') { agentSelectedSection = control.dataset.agentKind || 'identity'; refreshStudioEditor(`[data-agent-node-id="${CSS.escape(control.dataset.agentNodeId || '')}"]`); return; }
  if (action === 'agentZoom') { agentScale = Math.max(.45, Math.min(1.75, agentScale + Number(control.dataset.delta || 0))); refreshStudioEditor('[data-agent-editor-canvas]'); return; }
  if (action === 'agentFit') { const canvas = document.querySelector('[data-agent-editor-canvas]'); const scene = canvas?.querySelector('.agent-graph-scene'); const width = Number(scene?.dataset.agentSceneWidth || 920); agentScale = Math.max(.45, Math.min(1, ((canvas?.clientWidth || 920) - 18) / width)); refreshStudioEditor('[data-agent-editor-canvas]'); return; }
  if (action === 'agentAutoLayout') { const graph = currentAgentGraph(studioEditor.draft).graph; studioEditor.draft.editor_layout = Object.fromEntries(graph.nodes.map((node, index) => [node.node_id, { x: 36 + (index % 4) * 224, y: 42 + Math.floor(index / 4) * 142 }])); refreshStudioEditor('[data-agent-editor-canvas]'); return; }
  if (action === 'studioEditorTab') { const tab = control.dataset.tab; document.querySelectorAll('[data-action="studioEditorTab"]').forEach(button => button.setAttribute('aria-selected', String(button === control))); document.querySelectorAll('[data-studio-panel]').forEach(panel => panel.toggleAttribute('hidden', panel.dataset.studioPanel !== tab)); if (tab === 'json' && studioEditor) { if (studioEditor.kind === 'workflow') studioEditor.draft = studioEditors.normalizeWorkflow(studioEditor.draft); const input = document.getElementById('studio-draft-json'); if (input) input.value = JSON.stringify(studioEditor.draft, null, 2); persistWorkingStudioDraft(); } return; }
  if (action === 'forkStudioCandidate') { forkStudioCandidate(); return; }
  if (action === 'studioApplyJson') { const input = document.getElementById('studio-draft-json'); try { const parsed = JSON.parse(input?.value || ''); const nextDraft = studioEditor.kind === 'agent' ? studioEditors.normalizeAgent(parsed) : studioEditors.normalizeWorkflow(parsed); const identityKey = studioEditor.kind === 'agent' ? 'agent_id' : 'workflow_id'; if (studioVersionAllocation && (nextDraft[identityKey] !== studioVersionAllocation.identity || nextDraft.version !== studioVersionAllocation.candidate_version)) throw new Error('Predecessor-bound JSON cannot change the candidate identity or version. Use the explicit independent fork action.'); if (studioEditor.kind === 'agent') { agentWorkingGraph = studioEditors.synchronizeAgentBuilderGraph(nextDraft, parsed.builder_graph); nextDraft.builder_graph = structuredClone(agentWorkingGraph); agentConnectionStart = null; agentGraphDirty = true; } input?.setCustomValidity(''); studioEditor.draft = nextDraft; studioSelectedNode = studioEditor.kind === 'workflow' ? studioEditor.draft.nodes[0]?.node_id || '' : ''; refreshStudioEditor(studioEditor.kind === 'agent' ? '[data-agent-root-field="instructions"]' : '[data-workflow-editor-canvas]'); } catch (error) { input?.setCustomValidity(error.message); input?.reportValidity(); } return; }
  if (action === 'agentAddBinding') { const draft = studioEditor?.draft; if (!draft || studioEditor.kind !== 'agent') return; let index = draft.bindings.length + 1; while (draft.bindings.some(item => item.binding_id === `binding:capability-${index}`)) index += 1; const binding = { binding_id: `binding:capability-${index}`, subject_kind: 'agent', subject_id: draft.agent_id, capability_id: 'capability:local-worker', capability_version: '1.0.0', effect_grant_ids: [draft.grants[0]?.grant_id].filter(Boolean), credential_namespace: null, cost_policy: 'non-billable', egress_policy: 'deny', state: 'candidate', evidence_refs: ['receipt:human-approval'] }; draft.bindings.push(binding); draft.capability_binding_ids.push(binding.binding_id); agentSelectedSection = 'capabilities'; refreshStudioEditor(`[data-agent-binding-index="${draft.bindings.length - 1}"] input`); return; }
  if (action === 'agentRemoveBinding') { const draft = studioEditor?.draft; const index = Number(control.dataset.index); if (!draft || draft.bindings.length <= 1 || !draft.bindings[index]) return; const [removed] = draft.bindings.splice(index, 1); draft.capability_binding_ids = draft.capability_binding_ids.filter(id => id !== removed.binding_id); refreshStudioEditor('[data-action="agentAddBinding"]'); return; }
  if (action === 'agentAddGrant') { const draft = studioEditor?.draft; if (!draft || studioEditor.kind !== 'agent') return; let index = draft.grants.length + 1; while (draft.grants.some(item => item.grant_id === `grant:scope-${index}`)) index += 1; const grant = { grant_id: `grant:scope-${index}`, subject_id: draft.agent_id, effects: ['read'], scope_roots: ['workspace:current'], approved_by: draft.owner, evidence_refs: ['receipt:human-approval'], expires_utc: null, state: 'candidate' }; draft.grants.push(grant); draft.effect_grant_ids.push(grant.grant_id); agentSelectedSection = 'authority'; refreshStudioEditor(`[data-agent-grant-index="${draft.grants.length - 1}"] input`); return; }
  if (action === 'agentRemoveGrant') { const draft = studioEditor?.draft; const index = Number(control.dataset.index); if (!draft || draft.grants.length <= 1 || !draft.grants[index]) return; const [removed] = draft.grants.splice(index, 1); draft.effect_grant_ids = draft.effect_grant_ids.filter(id => id !== removed.grant_id); for (const binding of draft.bindings) binding.effect_grant_ids = binding.effect_grant_ids.filter(id => id !== removed.grant_id); refreshStudioEditor('[data-action="agentAddGrant"]'); return; }
  if (action === 'workflowAddBinding') { const draft = studioEditor?.draft; if (!draft || studioEditor.kind !== 'workflow') return; let index = draft.bindings.length + 1; while (draft.bindings.some(item => item.binding_id === `binding:workflow-${index}`)) index += 1; const binding = { binding_id: `binding:workflow-${index}`, subject_kind: 'workflow', subject_id: draft.workflow_id, capability_id: 'capability:identity', capability_version: '1.0.0', effect_grant_ids: [draft.grants[0]?.grant_id].filter(Boolean), credential_namespace: null, cost_policy: 'non-billable', egress_policy: 'deny', state: 'admitted', evidence_refs: ['receipt:human-approval'] }; draft.bindings.push(binding); draft.executor_adapters[binding.binding_id] = 'identity'; draft.authority_definition_state = 'supplied-for-new-revision'; refreshStudioEditor(`[data-workflow-binding-index="${draft.bindings.length - 1}"] input`); return; }
  if (action === 'workflowRemoveBinding') { const draft = studioEditor?.draft; const index = Number(control.dataset.index); if (!draft || draft.bindings.length <= 1 || !draft.bindings[index]) return; const [removed] = draft.bindings.splice(index, 1); delete draft.executor_adapters[removed.binding_id]; draft.authority_definition_state = 'supplied-for-new-revision'; refreshStudioEditor('[data-action="workflowAddBinding"]'); return; }
  if (action === 'workflowAddGrant') { const draft = studioEditor?.draft; if (!draft || studioEditor.kind !== 'workflow') return; let index = draft.grants.length + 1; while (draft.grants.some(item => item.grant_id === `grant:workflow-${index}`)) index += 1; draft.grants.push({ grant_id: `grant:workflow-${index}`, subject_id: draft.workflow_id, effects: ['read'], scope_roots: ['workspace:current'], approved_by: draft.owner, evidence_refs: ['receipt:human-approval'], expires_utc: null, state: 'admitted' }); draft.authority_definition_state = 'supplied-for-new-revision'; refreshStudioEditor(`[data-workflow-grant-index="${draft.grants.length - 1}"] input`); return; }
  if (action === 'workflowRemoveGrant') { const draft = studioEditor?.draft; const index = Number(control.dataset.index); if (!draft || draft.grants.length <= 1 || !draft.grants[index]) return; const [removed] = draft.grants.splice(index, 1); for (const binding of draft.bindings) binding.effect_grant_ids = binding.effect_grant_ids.filter(id => id !== removed.grant_id); for (const node of draft.nodes) node.effect_grant_ids = node.effect_grant_ids.filter(id => id !== removed.grant_id); draft.authority_definition_state = 'supplied-for-new-revision'; refreshStudioEditor('[data-action="workflowAddGrant"]'); return; }
  if (action === 'workflowPortConnect') {
    if (control.dataset.direction === 'output') {
      workflowConnectionStart = { node: control.dataset.nodeId, port: control.dataset.port };
      refreshStudioEditor(`[data-action="workflowPortConnect"][data-direction="output"][data-node-id="${CSS.escape(control.dataset.nodeId)}"][data-port="${CSS.escape(control.dataset.port)}"]`);
    } else if (workflowConnectionStart) connectWorkflowEdge(workflowConnectionStart.node, workflowConnectionStart.port, control.dataset.nodeId, control.dataset.port, 'always');
    else document.querySelector('[data-studio-validation]')?.insertAdjacentHTML('beforeend', '<span class="studio-warning">Select an output handle first, then the target input handle.</span>');
    return;
  }
  if (action === 'workflowCancelConnection') { workflowConnectionStart = null; refreshStudioEditor('[data-workflow-editor-canvas]'); return; }
  if (action === 'workflowZoom') { workflowScale = Math.max(.45, Math.min(1.75, workflowScale + Number(control.dataset.delta || 0))); refreshStudioEditor('[data-workflow-editor-canvas]'); return; }
  if (action === 'workflowFit') {
    const canvas = document.querySelector('[data-workflow-editor-canvas]'); const nodes = studioEditor?.draft?.nodes || [];
    const maxX = Math.max(240, ...nodes.map(node => Number(node.position?.x || 0) + 220)); const maxY = Math.max(160, ...nodes.map(node => Number(node.position?.y || 0) + 120));
    workflowScale = Math.max(.45, Math.min(1.25, Math.min((canvas?.clientWidth || 720) / maxX, (canvas?.clientHeight || 430) / maxY) * .94));
    refreshStudioEditor('[data-workflow-editor-canvas]'); return;
  }
  if (action === 'workflowAutoLayout') {
    const draft = studioEditor?.draft; if (!draft) return;
    const incoming = new Map(draft.nodes.map(node => [node.node_id, 0])); const outgoing = new Map(draft.nodes.map(node => [node.node_id, []]));
    for (const edge of draft.edges) { incoming.set(edge.target_node, (incoming.get(edge.target_node) || 0) + 1); outgoing.get(edge.source_node)?.push(edge.target_node); }
    const layer = new Map(); const ready = draft.nodes.filter(node => !incoming.get(node.node_id)).map(node => node.node_id).sort();
    while (ready.length) { const id = ready.shift(); for (const next of outgoing.get(id) || []) { layer.set(next, Math.max(layer.get(next) || 0, (layer.get(id) || 0) + 1)); incoming.set(next, incoming.get(next) - 1); if (!incoming.get(next)) ready.push(next); } ready.sort(); }
    const groups = new Map(); for (const node of draft.nodes) { const depth = layer.get(node.node_id) || 0; if (!groups.has(depth)) groups.set(depth, []); groups.get(depth).push(node); }
    for (const [depth, group] of [...groups].sort((a, b) => a[0] - b[0])) group.sort((a, b) => a.node_id.localeCompare(b.node_id)).forEach((node, index) => { node.position = { x: 60 + depth * 270, y: 55 + index * 145 }; });
    workflowScale = 1; refreshStudioEditor('[data-workflow-editor-canvas]'); return;
  }
  if (action === 'workflowAddNode') { addWorkflowNode(control.dataset.nodeTemplate); return; }
  if (action === 'workflowSelectNode') { studioSelectedNode = control.dataset.nodeId; refreshStudioEditor('[data-workflow-field="node_id"]'); return; }
  if (action === 'workflowAddPort') { const node = studioEditor?.draft.nodes.find(item => item.node_id === studioSelectedNode); const direction = control.dataset.direction; if (node && ['inputs', 'outputs'].includes(direction)) { node[direction].push({ name: `${direction === 'inputs' ? 'input' : 'output'}-${node[direction].length + 1}`, data_type: 'string', required: true }); refreshStudioEditor(`[data-action="workflowAddPort"][data-direction="${direction}"]`); } return; }
  if (action === 'workflowRemovePort') { const draft = studioEditor?.draft; const node = draft?.nodes.find(item => item.node_id === studioSelectedNode); const direction = control.dataset.direction; const index = Number(control.dataset.index); if (!node || !['inputs', 'outputs'].includes(direction) || node[direction].length <= 1 || !node[direction][index]) return; const [removed] = node[direction].splice(index, 1); draft.edges = draft.edges.filter(edge => direction === 'inputs' ? !(edge.target_node === node.node_id && edge.target_port === removed.name) : !(edge.source_node === node.node_id && edge.source_port === removed.name)); refreshStudioEditor(`[data-action="workflowAddPort"][data-direction="${direction}"]`); return; }
  if (action === 'workflowMoveNode') { const nodes = studioEditor?.draft.nodes || []; const index = nodes.findIndex(item => item.node_id === studioSelectedNode); const target = index + Number(control.dataset.delta); if (index >= 0 && target >= 0 && target < nodes.length) { [nodes[index], nodes[target]] = [nodes[target], nodes[index]]; refreshStudioEditor(`[data-action="workflowMoveNode"][data-delta="${control.dataset.delta}"]`); } return; }
  if (action === 'workflowRemoveNode') { const draft = studioEditor?.draft; if (draft && draft.nodes.length > 1) { draft.nodes = draft.nodes.filter(item => item.node_id !== studioSelectedNode); draft.edges = draft.edges.filter(edge => edge.source_node !== studioSelectedNode && edge.target_node !== studioSelectedNode); studioSelectedNode = draft.nodes[0].node_id; refreshStudioEditor('[data-workflow-editor-canvas]'); } return; }
  if (action === 'workflowRemoveEdge') { const draft = studioEditor?.draft; const index = Number(control.dataset.index); if (draft?.edges?.[index]) { draft.edges.splice(index, 1); refreshStudioEditor('[data-edge-source-endpoint]'); } return; }
  if (action === 'workflowConnectNodes') { connectWorkflowEdgeFromControls(); return; }
  if (action === 'skillSelectFile') { syncSkillEditorFile(); studioActiveFile = control.dataset.filePath; refreshStudioEditor('#studio-skill-file'); return; }
  if (action === 'skillAddFile') { syncSkillEditorFile(); const prefix = control.dataset.fileKind === 'contract' ? 'contracts/schema' : control.dataset.fileKind === 'test' ? 'tests/case' : 'resources/note'; const extension = control.dataset.fileKind === 'resource' ? '.md' : '.json'; let index = 1; while (Object.hasOwn(studioEditor.draft.editor_files, `${prefix}-${index}${extension}`)) index += 1; studioActiveFile = `${prefix}-${index}${extension}`; studioEditor.draft.editor_files[studioActiveFile] = extension === '.json' ? '{}\n' : '# Resource\n'; refreshStudioEditor('#studio-skill-file'); return; }
  if (action === 'skillRemoveFile') { syncSkillEditorFile(); if (studioEditor?.kind === 'skill' && !['SKILL.md', 'capability.json', 'skill.yaml'].includes(studioActiveFile)) { delete studioEditor.draft.editor_files[studioActiveFile]; studioActiveFile = 'SKILL.md'; refreshStudioEditor('#studio-skill-file'); } return; }
  if (action === 'studioLifecycle') {
    if ((!studioSession || studioSession.kind !== control.dataset.kind) && control.dataset.kind === 'skill' && control.dataset.operation === 'rollback') {
      const source = studioSourceRecord || modalRecord || {}; const details = source.details || source; const lifecycle = details.lifecycle_authentication || {};
      if (lifecycle.authenticated !== true || source.status !== 'promoted' || lifecycle.rollback_available !== true || !lifecycle.promotion_receipt_relative) { showModal('Skill rollback unavailable', 'AUTHENTICATED RETAINED REVISION REQUIRED', '<p>The selected Studio revision does not expose an authenticated current promotion with a retained rollback target.</p>'); return; }
      studioSession = { kind: 'skill', payload: { ...studioEditors.normalizeSkill(details), promotion_receipt: lifecycle.promotion_receipt_relative } };
    }
    if (!studioSession || studioSession.kind !== control.dataset.kind) { showModal('Studio context unavailable', 'FAIL CLOSED', '<p>Reopen the candidate from its exact revision before continuing.</p>'); return; }
    const payload = structuredClone(studioSession.payload); const operation = control.dataset.operation; const requestId = studioAllocationRequestId();
    if (['preview', 'dry-run'].includes(operation)) { const identityKey = control.dataset.kind === 'agent' ? 'agent_id' : 'workflow_id'; pendingStudioPreview = { requestId, kind: control.dataset.kind, operation, subject: String(payload[identityKey] || ''), version: String(payload.version || '') }; showModal('Resolving exact execution contract', 'AUTHENTICATED ADMISSION · NO EFFECTS', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Re-reading the admitted revision, live authority hashes, routes, blockers, schemas, and execution topology.</p></div>'); vscode.postMessage({ type: 'studioOperation', requestId, kind: control.dataset.kind, operation, payload }); return; }
    if (operation === 'start' && control.dataset.kind === 'agent') { studioPendingRun = { requestId, payload }; showModal('Start admitted agent revision', 'EXPLICIT OBJECTIVE · DURABLE RUN', '<label class="modal-field"><span>Objective</span><textarea id="studio-agent-objective" rows="6" maxlength="4000" placeholder="Describe the exact bounded task this admitted revision should perform."></textarea></label><label class="modal-field"><span>Bounded local tool calls (canonical JSON array, optional)</span><textarea id="studio-agent-tool-calls" rows="5" spellcheck="false">[]</textarea></label><p class="modal-note">At most eight admitted local-worker calls are accepted. The host validates the closed tool registry, inputs, grants, and process bounds before execution. PX returns a durable run ID before execution completes so status, pause, and cancel remain usable.</p>', '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitStudioAgentRun">Start with this objective</button>'); return; }
    if (operation === 'start' && control.dataset.kind === 'workflow') { studioPendingWorkflowRun = { requestId, payload }; const contract = (payload.run_input_contract || []).map(item => item.key).filter(Boolean); showModal('Start admitted workflow revision', 'EPHEMERAL INPUTS · DURABLE RUN', `<label class="modal-field"><span>Run inputs (canonical JSON object)</span><textarea id="studio-workflow-inputs" rows="9" spellcheck="false">${esc(JSON.stringify(payload.run_inputs || {}, null, 2))}</textarea></label><p class="modal-note">Expected keys: ${esc(contract.join(', ') || 'defined by root node input ports')}. PX returns a durable run ID before background execution begins.</p>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitStudioWorkflowRun">Start with these inputs</button>'); return; }
    if (operation === 'approve' && control.dataset.kind === 'workflow') {
      const node = payload.nodes?.find(item => item.node_id === studioSelectedNode && item.approval_required && !payload.approvals?.[item.node_id]) || payload.nodes?.find(item => item.approval_required && !payload.approvals?.[item.node_id]);
      if (!node) { showModal('Approval not required', 'NO GOVERNED NODE SELECTED', '<p>Mark a workflow node as requiring governed human approval before issuing a node approval capability.</p>', '<button class="primary" data-action="closeModal">Close</button>'); return; }
      payload.node_id = node.node_id;
    }
    if (control.dataset.kind === 'skill') {
      pendingSkillLifecycle = Object.freeze({ requestId, kind: 'skill', operation, skill: String(payload.skill_id || ''), version: String(payload.version || '') });
      showModal(`${operation[0].toUpperCase()}${operation.slice(1)} skill`, 'REQUEST-BOUND LIFECYCLE OPERATION', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Awaiting the exact host-approved lifecycle receipt.</p></div>');
    } else closeModal();
    vscode.postMessage({ type: 'studioOperation', requestId, kind: control.dataset.kind, operation, payload }); return;
  }
  if (action === 'submitStudioAgentRun') { const objectiveInput = document.getElementById('studio-agent-objective'); const toolCallsInput = document.getElementById('studio-agent-tool-calls'); const objective = objectiveInput?.value.trim() || ''; try { if (!studioPendingRun || !objective) throw new Error('A specific bounded objective is required.'); const toolCalls = JSON.parse(toolCallsInput?.value || '[]'); if (!Array.isArray(toolCalls) || toolCalls.length > 8 || toolCalls.some(call => !call || typeof call !== 'object' || Array.isArray(call) || Object.keys(call).sort().join(',') !== 'input,tool' || typeof call.tool !== 'string')) throw new Error('Tool calls must be a JSON array of at most eight { tool, input } objects.'); const { requestId, payload: pendingPayload } = studioPendingRun; const payload = structuredClone(pendingPayload); payload.task = { objective, tool_calls: toolCalls }; if (studioSession?.kind === 'agent') studioSession.payload.task = structuredClone(payload.task); studioPendingRun = null; vscode.postMessage({ type: 'studioOperation', requestId, kind: 'agent', operation: 'start', payload }); closeModal(); } catch (error) { const input = objective ? toolCallsInput : objectiveInput; input?.setCustomValidity(error.message); input?.reportValidity(); } return; }
  if (action === 'submitStudioWorkflowRun') {
    const input = document.getElementById('studio-workflow-inputs');
    try {
      if (!studioPendingWorkflowRun) throw new Error('Workflow run context is unavailable.');
      const values = JSON.parse(input?.value || '{}');
      if (!values || typeof values !== 'object' || Array.isArray(values)) throw new Error('Run inputs must be a JSON object.');
      for (const item of studioPendingWorkflowRun.payload.run_input_contract || []) {
        if (item.required !== false && !Object.hasOwn(values, item.key)) throw new Error(`Required workflow input is missing: ${item.key}.`);
        if (Object.hasOwn(values, item.key) && !workflowInputMatches(values[item.key], item.value_type)) throw new Error(`${item.key} must be ${item.value_type}.`);
      }
      const { requestId, payload: pendingPayload } = studioPendingWorkflowRun; const payload = structuredClone(pendingPayload); payload.run_inputs = values;
      if (studioSession?.kind === 'workflow') studioSession.payload.run_inputs = structuredClone(values);
      studioPendingWorkflowRun = null; vscode.postMessage({ type: 'studioOperation', requestId, kind: 'workflow', operation: 'start', payload }); closeModal();
    } catch (error) { input?.setCustomValidity(error.message); input?.reportValidity(); }
    return;
  }
  if (action === 'surfaceScope') { if (control.dataset.target === 'agents') state.agentScope = control.dataset.scope; if (control.dataset.target === 'workflows') state.workflowScope = control.dataset.scope; persistDashboardState(); render(); return; }
  if (action === 'catalogPrevious' || action === 'catalogNext') {
    const kind = control.dataset.kind; const current = state.catalogRequests[kind] || { offset: 0, limit: 50 };
    requestCatalog(kind, { offset: Math.max(0, current.offset + (action === 'catalogNext' ? current.limit : -current.limit)) }); return;
  }
  if (action === 'catalogRetry') { const kind = control.dataset.kind; if (!kind) return; invalidateCatalog(kind, { offset: 0 }); return; }
  if (action === 'inspectCatalogItem') {
    const kind = control.dataset.kind; const item = state.catalogs[kind]?.items.find(row => row.id === control.dataset.id); if (!item) return;
    studioPackageRequest = null; studioPendingSkillPackage = null; studioAllocationRequest = null; studioVersionAllocation = null; studioVersionAllocationProof = null; studioSaveRequest = null;
    const record = { ...item.details, identity: { id: item.id, kind: item.kind, status: item.status, owner: item.owner, path: item.path }, summary: item.summary, effects: item.effects, tags: item.tags, agent_model: item.agent_model || undefined };
    studioSourceRecord = { ...item, ...record, _catalogKind: kind, _catalogRecordId: item.id };
    const editableAgent = kind === 'agents' && item.kind === 'studio-agent-revision';
    const editableWorkflow = kind === 'workflows' && item.kind === 'studio-workflow-revision';
    const editableSkill = kind === 'skills' && (
      item.kind === 'studio-skill-revision'
      || (record.domain === 'px-standard' && SHA256_PATTERN.test(String(record.package_tree_sha256 || record.source_tree_sha256 || '')))
    );
    const comparisonAction = ['skills', 'preserved-skills'].includes(kind) && record.backup ? `<button data-action="compareSkillOriginal" data-skill-id="${esc(item.id)}">Compare PX ↔ preserved original</button>` : '';
    const rollbackAction = kind === 'skills' && item.status === 'promoted' && record.lifecycle_authentication?.authenticated === true && record.lifecycle_authentication?.rollback_available === true ? '<button class="danger" data-action="studioLifecycle" data-kind="skill" data-operation="rollback">Rollback to retained prior canonical revision</button>' : '';
    const operateAction = (editableAgent || editableWorkflow) && item.status === 'admitted' && record.lifecycle_authentication?.authenticated === true ? `<button class="primary" data-action="operateStudioRevision" data-kind="${editableAgent ? 'agent' : 'workflow'}">Operate exact admitted revision</button>` : '';
    const resumeCandidateAction = (editableAgent || editableWorkflow || editableSkill) && item.status === 'candidate' ? `<button class="primary" data-action="operateStudioRevision" data-kind="${editableAgent ? 'agent' : editableWorkflow ? 'workflow' : 'skill'}">Continue candidate lifecycle</button>` : '';
    const editAction = editableAgent ? `${resumeCandidateAction}${operateAction}<button class="primary" data-action="openStudioFromCatalog" data-kind="agent">Open in Agent Studio as new revision</button>` : editableWorkflow ? `${resumeCandidateAction}${operateAction}<button class="primary" data-action="openStudioFromCatalog" data-kind="workflow">Open in Workflow Studio as new revision</button>` : kind === 'agents' ? '<button class="primary" data-action="importCatalogDefinition" data-kind="agent">Open in Agent Studio</button><p class="modal-note">This source definition is imported into a new independent Studio candidate. The source stays unchanged and grants no runtime authority.</p>' : kind === 'workflows' ? '<button class="primary" data-action="importCatalogDefinition" data-kind="workflow">Open in Workflow Studio</button><p class="modal-note">This source definition is imported into a new independent visual workflow candidate. Review its node semantics and authority before saving.</p>' : editableSkill ? `${resumeCandidateAction}<button class="primary" data-action="loadSkillPackageEditor" data-kind="skill">Open package in Skill Studio</button>` : kind === 'preserved-skills' ? '<p class="modal-note">Preserved originals remain immutable backup evidence. Create an explicitly provenance-linked standard adaptation instead of editing this backup in place.</p>' : kind === 'microsoft-skills' || kind === 'enterprise-skills' ? '<p class="modal-note">This source stays in the separate Microsoft / Enterprise domain and cannot enter the standard Skill Studio create path.</p>' : kind.includes('skill') ? '<p class="modal-note">This package is read-only until an independent full-tree attestation is available; a body hash alone is not enough to preserve an immutable predecessor.</p>' : '';
    const authorityWarning = ['studio-agent-revision', 'studio-workflow-revision'].includes(item.kind) && record.authority_definition_state === 'not-stored-with-revision' ? '<p class="modal-note">This revision stores authority references, not their original definitions. Explicitly supply and register those definitions before admission or execution.</p>' : '';
    const human = item.agent_model ? `${agentModelHuman(item)}${editAction}${authorityWarning}` : kind.includes('workflow') ? `${workflowHuman(item)}${editAction}` : kind.includes('skill') ? `${skillHuman(item)}<div class="action-grid">${comparisonAction}${rollbackAction}${editAction}</div>` : `<p>${esc(item.summary || 'No summary')}</p><dl class="modal-detail"><div><dt>ID</dt><dd class="mono">${esc(item.id)}</dd></div><div><dt>Owner</dt><dd>${esc(item.owner || 'Not declared')}</dd></div><div><dt>Path</dt><dd class="mono">${esc(item.path || 'Not declared')}</dd></div><div><dt>Effects</dt><dd>${esc(item.effects?.join(', ') || 'None declared')}</dd></div></dl>${editAction}${authorityWarning}`;
    showInformationModal(item.label, `${item.kind.toUpperCase()} · ${item.status}`, record, human); return;
  }
  if (action === 'inspectReadiness') {
    const item = state.snapshot.readiness?.dimensions?.find(row => row.id === control.dataset.readinessId);
    if (!item) return;
    const blockers = readinessLiveBlockers(state.snapshot || {});
    const liveRows = blockers.length
      ? `<section><b>Live operational blockers</b><ul>${blockers.map(value => `<li>${esc(value)}</li>`).join('')}</ul></section>`
      : '';
    const status = item.blocking ? 'READINESS CEILING DIMENSION' : blockers.length ? 'READINESS DIMENSION (LIVE BLOCKERS)' : 'READINESS DIMENSION';
    showInformationModal(`${item.id} · ${item.name}`, status, item, `<p>${esc(item.question)}</p><div class="readiness-explain"><div><span>Structural score</span><strong>${number(item.score)}/${number(item.maximum)}</strong></div><section><b>Evidence</b><ul>${(item.evidence || []).map(value => `<li>${esc(value)}</li>`).join('') || '<li>No supporting evidence resolved.</li>'}</ul></section><section><b>Open gaps</b><ul>${(item.gaps || []).map(value => `<li>${esc(value)}</li>`).join('') || '<li>No structural gap detected; a fresh E2E certification is still separate.</li>'}</ul></section>${liveRows}</div>`); return;
  }
  if (action === 'inspectDiagnosticRecord') { const record = { id: control.dataset.diagnosticId, cause: control.dataset.cause, owner: control.dataset.owner, evidence: control.dataset.evidence, post_repair_verification: control.dataset.verification, authority: 'diagnostic correlation only; not certification' }; showInformationModal(record.id || 'Diagnostic trace', 'CAUSE / OWNER / EVIDENCE / VERIFICATION', record, `<dl class="modal-detail"><div><dt>Cause</dt><dd>${esc(record.cause)}</dd></div><div><dt>Affected owner</dt><dd>${esc(record.owner)}</dd></div><div><dt>Evidence</dt><dd class="mono">${esc(record.evidence)}</dd></div><div><dt>Post-repair verification</dt><dd>${esc(record.post_repair_verification)}</dd></div></dl>`); return; }
  if (action === 'inspectPunchCard') { const gapId = control.dataset.gapId || ''; showModal(`Loading ${esc(gapId)}`, 'EXACT APPEND-ONLY CARD', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Reading the complete canonical history and evidence.</p></div>'); vscode.postMessage({ type: 'operationalCardQuery', requestId: `operational-card-${Date.now()}`, gapId }); return; }
  if (action === 'queryOperationalCards') { requestOperationalCards({ query: document.querySelector('[data-operational-card-search]')?.value.trim() || '', state: document.querySelector('[data-operational-card-state]')?.value || '', severity: document.querySelector('[data-operational-card-severity]')?.value || '', evidenceGap: document.querySelector('[data-operational-card-evidence-gap]')?.checked === true, offset: 0 }); return; }
  if (action === 'operationalCardsPrevious' || action === 'operationalCardsNext') { const page = state.operationalCardsData || state.snapshot?.completion?.operational_punch_cards || {}; const delta = action === 'operationalCardsNext' ? Number(page.limit || 50) : -Number(page.limit || 50); requestOperationalCards({ offset: Math.max(0, Number(page.offset || 0) + delta) }); return; }
  if (action === 'inspectOperationalInventory') { showModal('Loading surface inventory', 'EXACT CONTROL DISPOSITIONS', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Reading registered, disposed, and unresolved controls.</p></div>'); vscode.postMessage({ type: 'operationalInventoryQuery', requestId: `operational-inventory-${Date.now()}`, surfaceId: control.dataset.surfaceId || '' }); return; }
  if (action === 'openPunchSource') { const supplied = String(control.dataset.path || '').replace(/:\d+(?::\d+)?$/, ''); const root = state.snapshot?.source?.engineRoot; if (!supplied || !root) return; const absolute = /^(?:[A-Za-z]:[\\/]|\/)/.test(supplied); postHostAction(action, 'openFile', { path: absolute ? supplied : `${root}${root.includes('\\') ? '\\' : '/'}${supplied}` }); return; }
  if (action === 'inspectReadinessReport') {
    const report = state.snapshot.readiness;
    if (!report) return;
    const blockers = readinessLiveBlockers(state.snapshot || {});
    const title = blockers.length ? 'LIVE READINESS + STRUCTURAL MATRIX' : 'ADVISORY STRUCTURAL ASSESSMENT';
    const blockerSection = blockers.length
      ? `<section><b>Live operational blockers</b><ul>${blockers.map(value => `<li>${esc(value)}</li>`).join('')}</ul></section>`
      : '';
    const reason = blockers.length
      ? 'Live blockers are currently preventing operational readiness despite structural evidence.'
      : 'Fresh certification remains separate.';
    showInformationModal('Agent readiness matrix', title, report, `<p>${esc(report.authority || 'Live readiness evidence is not fully authoritative yet.')}</p><p>${esc(report.score_cap_reason || reason)}</p><div class="readiness-lanes"><section><b>Safe now</b><ul>${(report.safe_now || []).map(value => `<li>${esc(value)}</li>`).join('')}</ul></section><section><b>Requires a fresh gate</b><ul>${(report.requires_fresh_gate || []).map(value => `<li>${esc(value)}</li>`).join('')}</ul></section>${blockerSection}</div>`); return;
  }
  if (action === 'informationTab') { switchInformationTab(control.dataset.tab); return; }
  if (action === 'exportRecordJson') { postHostAction(action, 'exportRecordJson', { title: modalTitle || 'Pacify-X record', record: modalRecord }); return; }
  if (action === 'graphView') { state.graphView = control.dataset.view; state.graphMode = 'full'; state.graphLayout = 'community'; state.graphTarget = ''; state.graphKind = ''; state.graphStatus = ''; state.graphCommunity = ''; state.graphData = null; requestGraph({ view: state.graphView, mode: 'full', cluster: '', node: '', target: '', query: '', relation: '', direction: 'both', kind: '', status: '', offset: 0, edgeOffset: 0 }); render(); return; }
  if (action === 'openRepositoryGraph') { state.active = 'knowledgeGraph'; state.graphView = 'repository'; state.graphMode = 'full'; state.graphLayout = 'community'; state.graphTarget = ''; state.graphCommunity = ''; state.graphData = null; requestGraph({ view: 'repository', mode: 'full', cluster: '', node: '', target: '', query: '', relation: '', direction: 'both', kind: '', status: '', offset: 0, edgeOffset: 0 }); render(); return; }
  if (action === 'openProjectModuleMap') { state.active = 'knowledgeGraph'; state.graphView = 'repository'; state.graphMode = 'full'; state.graphLayout = 'community'; state.graphTarget = ''; state.graphCommunity = ''; state.graphKind = 'file'; state.graphStatus = ''; state.graphData = null; requestGraph({ view: 'repository', mode: 'full', cluster: '', node: '', target: '', query: '', relation: 'imports', direction: 'both', kind: 'file', status: '', offset: 0, edgeOffset: 0 }); render(); return; }
  if (action === 'inspectProjectMapRecord') { const kind = control.dataset.recordKind; const records = state.snapshot?.project?.map?.drilldown?.[kind]; const record = Array.isArray(records) ? records[Number(control.dataset.recordIndex)] : null; if (record) showInformationModal(record.summary || record.name || record.archive_id || 'Project map record', `${String(kind || 'record').toUpperCase()} / SEALED PROJECT MAP`, record, `<p>${esc(record.summary || record.source || 'Bounded record from the current sealed project-map projection.')}</p>${humanRecord(record)}`); return; }
  if (action === 'inspectRuntimeRecord') { const runtime = state.snapshot?.runtime || {}; const sources = { operations: (runtime.core?.operations || []).slice().reverse().slice(0, 12), producers: runtime.core?.producer_trace || [], placements: runtime.execution_placement?.recent || [], providers: state.snapshot?.providerActivity || [], startup: runtime.host_startup?.milestones || [] }; const kind = control.dataset.runtimeKind; const record = sources[kind]?.[Number(control.dataset.runtimeIndex)]; if (record) showInformationModal(record.operation || record.producer || record.providerName || record.operation_id || record.id || 'Runtime record', `${String(kind || 'runtime').toUpperCase()} / CURRENT RUNTIME EVIDENCE`, record, `<p>${esc(record.reason || record.telemetrySource || record.admission || record.evidence_marker || 'Bounded runtime record from the current snapshot.')}</p>${humanRecord(record)}`); return; }
  if (action === 'graphOverview') { state.graphMode = 'full'; state.graphLayout = 'community'; state.graphTarget = ''; state.graphKind = ''; state.graphStatus = ''; state.graphCommunity = ''; state.graphBackStack = []; requestGraph({ mode: 'full', cluster: '', node: '', target: '', query: '', relation: '', direction: 'both', kind: '', status: '', offset: 0, edgeOffset: 0 }); render(); return; }
  if (action === 'buildRepositoryGraph') { vscode.postMessage({ type: 'buildRepositoryGraph' }); return; }
  if (action === 'graphLayout') { state.graphLayout = ['community', 'orbit', 'flow'].includes(control.dataset.layout) ? control.dataset.layout : 'community'; graphInteraction.sceneKey = ''; graphInteraction.fitted = false; render(); return; }
  if (action === 'graphDepth') { state.graphDepth = Math.max(1, Math.min(6, state.graphDepth + Number(control.dataset.delta || 0))); requestGraph({ depth: state.graphDepth, maxNodes: Math.min(96, 24 * state.graphDepth), maxEdges: Math.min(192, 48 * state.graphDepth) }); render(); return; }
  if (action === 'graphToggleInspector') { state.graphInspectorOpen = !state.graphInspectorOpen; graphInteraction.fitted = false; render(); return; }
  if (action === 'graphFocus') { const entering = !state.graphFocusMode; state.graphFocusMode = entering; graphInteraction.fitted = false; render(); finishGraphFocusTransition(entering); return; }
  if (action === 'graphBack') { const node = state.graphBackStack.pop(); if (node) { requestGraph({ node, query: '', relation: app.querySelector('[data-graph-relation]')?.value || '', direction: app.querySelector('[data-graph-direction]')?.value || 'both' }); render(); } return; }
  if (action === 'graphZoomIn') { zoomGraphTo(graphInteraction.scale * 1.2); return; }
  if (action === 'graphZoomOut') { zoomGraphTo(graphInteraction.scale / 1.2); return; }
  if (action === 'graphFit') { fitGraphViewport(); return; }
  if (action === 'graphReset') { resetGraphViewport(); return; }
  if (action === 'graphLoadMore') { state.graphLoadAll = false; const next = nextGraphPageRequest(); if (!next) return; requestGraph(next); render(); return; }
  if (action === 'graphLoadAll') { state.graphLoadAll = true; const next = nextGraphPageRequest(); if (!next) { state.graphLoadAll = false; return; } requestGraph(next); render(); return; }
  if (action === 'graphCommunity') { state.graphMode = 'full'; state.graphLayout = 'community'; state.graphCommunity = control.dataset.communityId || ''; state.graphBackStack = []; state.graphData = null; requestGraph({ mode: 'full', cluster: state.graphCommunity, kind: state.graphKind, status: state.graphStatus, offset: 0, edgeOffset: 0, query: '' }); render(); return; }
  if (action === 'graphClearCommunity') { state.graphMode = 'full'; state.graphLayout = 'community'; state.graphCommunity = ''; state.graphData = null; requestGraph({ mode: 'full', cluster: '', offset: 0, edgeOffset: 0 }); render(); return; }
  if (action === 'graphOpenNeighborhood') { const key = control.dataset.nodeKey || state.graphData?.selected; if (!key) return; state.graphMode = 'neighborhood'; state.graphLayout = 'flow'; state.graphBackStack = []; requestGraph({ mode: 'neighborhood', cluster: '', node: key, query: '', offset: 0, edgeOffset: 0 }); render(); return; }
  if (action === 'inspectGraphRecord') { const key = control.dataset.nodeKey || state.graphData?.selected; const record = state.graphData?.nodes?.find(item => item.key === key); if (record) showInformationModal(record.title || key, `${String(record.kind || 'NODE').toUpperCase()} · GRAPH SOURCE RECORD`, record, `<p>${esc(record.summary || 'No source summary is available.')}</p><dl class="modal-detail"><div><dt>Canonical key</dt><dd class="mono">${esc(record.key)}</dd></div><div><dt>Community</dt><dd>${esc(record.community_id || 'not classified')}</dd></div><div><dt>Owner</dt><dd>${esc(record.owner || 'not declared')}</dd></div><div><dt>Source path</dt><dd class="mono">${esc(record.path || record.source?.path || 'not declared')}</dd></div><div><dt>Source hash</dt><dd class="mono">${esc(record.source_sha256 || 'not declared')}</dd></div><div><dt>Provenance</dt><dd class="mono">${esc(readableValue(record.provenance || record.source || {}))}</dd></div></dl>`); return; }
  if (action === 'graphSaveView') { const query = app.querySelector('[data-graph-search]')?.value.trim() || ''; showModal('Save graph view', 'LOCAL VIEW PRESET · NO AUTHORITY CHANGE', `<label class="modal-field"><span>View name</span><input id="graph-view-name" maxlength="80" value="${esc(query || `${state.graphView} ${state.graphKind || 'all'} view`)}"></label><p class="modal-note">Stores only query, filters, layout, and depth in VS Code webview state. It does not copy graph records.</p>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitGraphSavedView">Save view</button>'); return; }
  if (action === 'submitGraphSavedView') { const name = document.getElementById('graph-view-name')?.value.trim(); if (!name) return; const data = state.graphData || {}; state.graphSavedViews.unshift({ name, view: state.graphView, mode: state.graphMode, target: state.graphTarget, query: data.requested_query || data.requestedQuery || '', relation: data.requested_relation || '', direction: data.direction || 'both', depth: state.graphDepth, layout: state.graphLayout, kind: state.graphKind, status: state.graphStatus, community: state.graphCommunity }); state.graphSavedViews = state.graphSavedViews.slice(0, 12); persistStudioMetadata(); closeModal(); render(); return; }
  if (action === 'graphApplySavedView') { const saved = state.graphSavedViews[Number(control.dataset.viewIndex)]; if (!saved) return; state.graphView = saved.view; state.graphMode = saved.mode || 'full'; state.graphTarget = saved.target || ''; state.graphDepth = saved.depth || 1; state.graphLayout = saved.layout || 'community'; state.graphKind = saved.kind || ''; state.graphStatus = saved.status || ''; state.graphCommunity = saved.community || ''; state.graphData = null; persistStudioMetadata(); requestGraph({ view: saved.view, mode: state.graphMode, cluster: state.graphCommunity, node: '', target: state.graphTarget, query: saved.query || '', relation: saved.relation || '', direction: saved.direction || 'both', kind: state.graphKind, status: state.graphStatus, depth: state.graphDepth, offset: 0, edgeOffset: 0 }); render(); return; }
  if (action === 'graphDeleteSavedView') { state.graphSavedViews.splice(Number(control.dataset.viewIndex), 1); persistStudioMetadata(); render(); return; }
  if (action === 'runGraphSearch') { const search = app.querySelector('[data-graph-search]'); const target = app.querySelector('[data-graph-target]'); const relation = app.querySelector('[data-graph-relation]'); const direction = app.querySelector('[data-graph-direction]'); const analysis = app.querySelector('[data-graph-analysis]'); state.graphBackStack = []; state.graphMode = analysis?.value || 'full'; if (state.graphMode === 'full') state.graphLayout = 'community'; else if (state.graphLayout === 'community') state.graphLayout = 'flow'; state.graphTarget = target?.value.trim() || ''; state.graphData = null; requestGraph({ mode: state.graphMode, cluster: state.graphMode === 'full' ? state.graphCommunity : '', node: '', target: state.graphTarget, query: search?.value.trim() || '', relation: relation?.value || '', direction: direction?.value || 'both', kind: state.graphKind, status: state.graphStatus, offset: 0, edgeOffset: 0 }); renderPreservingControl('[data-graph-search]'); return; }
  if (action === 'selectGraphNode') { const key = control.dataset.nodeKey; if (key && state.graphData?.nodes?.some(item => item.key === key)) { state.graphData = { ...state.graphData, selected: key }; render(); requestAnimationFrame(prepareGraphInteraction); } return; }
  if (action === 'focusGraphNode') { const key = control.dataset.nodeKey; if (!key) return; if (key.startsWith('cluster:')) { state.graphMode = 'full'; state.graphLayout = 'community'; state.graphCommunity = key.slice(8); state.graphData = null; requestGraph({ mode: 'full', cluster: state.graphCommunity, node: '', query: '', offset: 0, edgeOffset: 0 }); render(); return; } const prior = state.graphData?.selected; if (prior && prior !== key) state.graphBackStack.push(prior); state.graphMode = 'neighborhood'; state.graphLayout = 'flow'; requestGraph({ mode: 'neighborhood', cluster: '', node: key, query: '', relation: app.querySelector('[data-graph-relation]')?.value || '', direction: app.querySelector('[data-graph-direction]')?.value || 'both', offset: 0, edgeOffset: 0 }); render(); return; }
  if (action === 'inspectSensor') { const sensor = state.snapshot?.runtime?.hardware?.telemetry?.sensors?.find(item => item.id === control.dataset.sensorId); if (sensor) showInformationModal(sensor.label, 'LIVE READ-ONLY SENSOR', sensor, `<p>${esc(sensorValue(sensor))}</p><p>${esc(sensor.error || 'The provider returned a current observation.')}</p>`); return; }
  if (action === 'inspectMachineManifest') { showInformationModal('AI capability manifest', 'HUMAN + MACHINE CONTRACT', { schema_version: 'pacify-x.plugin-catalog.v1', counts: state.snapshot.counts, environment: state.snapshot.environment, extensions: state.environmentData.extensions?.records || [], connectors: state.snapshot.enterprise?.connectors || [], mcp: { transport: 'stdio', structured_content: true, ...(state.snapshot.observability?.mcp || { status: 'unavailable', registered: false, runtime_verified: false }) } }, '<p>The governed capability inventory can be exposed through the Pacify-X MCP definition when the host reports registration. Registration is not reported as runtime health, and discovery never grants execution authority.</p>'); return; }
  if (action === 'openExtensionsView') { postHostAction(action, 'openExtensionsView'); return; }
  if (action === 'previewExtensionInstall') {
    const extensionId = document.getElementById('extension-install-id')?.value.trim().toLowerCase() || '';
    const version = document.getElementById('extension-install-version')?.value.trim().toLowerCase() || '';
    if (!/^[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9-]{0,127}$/.test(extensionId)) { showModal('Install blocked', 'EXACT PUBLISHER.EXTENSION ID REQUIRED', '<p>Enter the complete Marketplace identity, for example <code>publisher.extension</code>.</p>'); return; }
    const requestId = studioAllocationRequestId(); pendingExtensionLifecycle = { requestId, action: 'install', extensionId };
    vscode.postMessage({ type: 'extensionLifecyclePreview', requestId, extensionId, version }); return;
  }
  if (action === 'executeExtensionInstall') {
    const request = pendingExtensionLifecycle;
    if (!request || request.token !== control.dataset.token || request.exactTarget !== control.dataset.exactTarget) return;
    vscode.postMessage({ type: 'extensionLifecycleExecute', requestId: request.requestId, token: request.token, exactTarget: request.exactTarget }); closeModal(); return;
  }
  if (action === 'previewExtensionUpdate') {
    const extensionId = document.getElementById('extension-update-id')?.value.trim().toLowerCase() || '';
    const version = document.getElementById('extension-update-version')?.value.trim().toLowerCase() || '';
    if (!/^[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9-]{0,127}$/.test(extensionId)) { showModal('Update blocked', 'EXACT INSTALLED PUBLISHER.EXTENSION ID REQUIRED', '<p>Enter the complete installed extension identity.</p>'); return; }
    const requestId = studioAllocationRequestId(); pendingExtensionLifecycle = { requestId, action: 'update', extensionId };
    vscode.postMessage({ type: 'extensionUpdatePreview', requestId, extensionId, version }); return;
  }
  if (action === 'executeExtensionUpdate') {
    const request = pendingExtensionLifecycle;
    if (!request || request.action !== 'update' || request.token !== control.dataset.token || request.exactTarget !== control.dataset.exactTarget) return;
    vscode.postMessage({ type: 'extensionUpdateExecute', requestId: request.requestId, token: request.token, exactTarget: request.exactTarget }); closeModal(); return;
  }
  if (action === 'previewExtensionEnablement') {
    const extensionId = document.getElementById('extension-enablement-id')?.value.trim().toLowerCase() || '';
    const desiredAction = document.getElementById('extension-enablement-action')?.value || '';
    const scope = document.getElementById('extension-enablement-scope')?.value || '';
    if (!/^[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9-]{0,127}$/.test(extensionId)) { showModal('Enablement handoff blocked', 'EXACT INSTALLED PUBLISHER.EXTENSION ID REQUIRED', '<p>Enter the complete installed extension identity.</p>'); return; }
    const requestId = studioAllocationRequestId(); pendingExtensionLifecycle = { requestId, action: 'enablement-handoff', extensionId, desiredAction, scope };
    vscode.postMessage({ type: 'extensionEnablementPreview', requestId, extensionId, desiredAction, scope }); return;
  }
  if (action === 'executeExtensionEnablement') {
    const request = pendingExtensionLifecycle;
    if (!request || request.action !== 'enablement-handoff' || request.token !== control.dataset.token || request.exactTarget !== control.dataset.exactTarget) return;
    vscode.postMessage({ type: 'extensionEnablementExecute', requestId: request.requestId, token: request.token, exactTarget: request.exactTarget, extensionId: request.extensionId, desiredAction: request.desiredAction, scope: request.scope }); closeModal(); return;
  }
  if (action === 'previewExtensionUninstall') {
    const extensionId = document.getElementById('extension-uninstall-id')?.value.trim().toLowerCase() || '';
    if (!/^[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9-]{0,127}$/.test(extensionId)) { showModal('Uninstall blocked', 'EXACT INSTALLED PUBLISHER.EXTENSION ID REQUIRED', '<p>Enter the complete installed extension identity.</p>'); return; }
    const requestId = studioAllocationRequestId(); pendingExtensionLifecycle = { requestId, action: 'uninstall', extensionId };
    vscode.postMessage({ type: 'extensionUninstallPreview', requestId, extensionId }); return;
  }
  if (action === 'executeExtensionUninstall') {
    const request = pendingExtensionLifecycle;
    if (!request || request.action !== 'uninstall' || request.token !== control.dataset.token || request.exactTarget !== control.dataset.exactTarget) return;
    const consumerImpactAcknowledged = document.getElementById('extension-uninstall-consumers')?.checked === true;
    if (request.consumerAckRequired && !consumerImpactAcknowledged) return;
    vscode.postMessage({ type: 'extensionUninstallExecute', requestId: request.requestId, token: request.token, exactTarget: request.exactTarget, extensionId: request.extensionId, consumerImpactAcknowledged }); closeModal(); return;
  }
  if (action === 'previewExtensionRollback') {
    const extensionId = document.getElementById('extension-rollback-id')?.value.trim().toLowerCase() || '';
    if (!/^[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9-]{0,127}$/.test(extensionId)) { showModal('Rollback blocked', 'EXACT ABSENT PUBLISHER.EXTENSION ID REQUIRED', '<p>Enter the exact extension identity that was previously uninstalled through the governed operation.</p>'); return; }
    const requestId = studioAllocationRequestId(); pendingExtensionLifecycle = { requestId, action: 'rollback', extensionId };
    vscode.postMessage({ type: 'extensionRollbackPreview', requestId, extensionId }); return;
  }
  if (action === 'executeExtensionRollback') {
    const request = pendingExtensionLifecycle;
    if (!request || request.action !== 'rollback' || request.token !== control.dataset.token || request.exactTarget !== control.dataset.exactTarget) return;
    vscode.postMessage({ type: 'extensionRollbackExecute', requestId: request.requestId, token: request.token, exactTarget: request.exactTarget, extensionId: request.extensionId }); closeModal(); return;
  }
  if (action === 'queryExtensionConflicts') {
    const extensionId = document.getElementById('extension-conflict-id')?.value.trim().toLowerCase() || '';
    if (!/^[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9-]{0,127}$/.test(extensionId)) { showModal('Conflict analysis blocked', 'EXACT INSTALLED PUBLISHER.EXTENSION ID REQUIRED', '<p>Enter the complete installed extension identity.</p>'); return; }
    const requestId = studioAllocationRequestId(); pendingExtensionLifecycle = { requestId, action: 'conflict-query', extensionId };
    vscode.postMessage({ type: 'extensionConflictQuery', requestId, extensionId }); return;
  }
  if (action === 'previewExtensionConflictResolution') {
    const extensionId = control.dataset.extensionId; const signalId = control.dataset.signalId; const targetExtensionId = control.dataset.targetExtensionId; const resolution = control.dataset.resolution;
    const requestId = studioAllocationRequestId(); pendingExtensionLifecycle = { requestId, action: 'conflict-resolution', extensionId, signalId, targetExtensionId, resolution };
    vscode.postMessage({ type: 'extensionConflictResolutionPreview', requestId, extensionId, signalId, targetExtensionId, resolution }); return;
  }
  if (action === 'executeExtensionConflictResolution') {
    const request = pendingExtensionLifecycle;
    if (!request || request.action !== 'conflict-resolution' || request.token !== control.dataset.token || request.exactTarget !== control.dataset.exactTarget) return;
    vscode.postMessage({ type: 'extensionConflictResolutionExecute', requestId: request.requestId, token: request.token, exactTarget: request.exactTarget }); closeModal(); return;
  }
  if (action === 'claimTask') { claimTaskModal(control.dataset.taskId); return; }
  if (action === 'submitClaimTask') { vscode.postMessage({ type: 'claimCoordinationTask', taskId: document.getElementById('claim-task').value, mode: document.getElementById('claim-mode').value, authority: document.getElementById('claim-authority').value, ttlMinutes: Number(document.getElementById('claim-ttl').value) }); closeModal(); return; }
  if (action === 'renewClaim') { vscode.postMessage({ type: 'renewCoordinationClaim', taskId: control.dataset.taskId, claimId: control.dataset.claimId, ttlMinutes: 120 }); return; }
  if (action === 'taskProgress') { progressModal(control.dataset.taskId, false); return; }
  if (action === 'completeTask') { progressModal(control.dataset.taskId, true); return; }
  if (action === 'submitTaskProgress') { vscode.postMessage({ type: 'recordTaskProgress', taskId: document.getElementById('progress-task').value, status: document.getElementById('progress-status').value, summary: document.getElementById('progress-summary').value, usage: { tokens: Number(document.getElementById('progress-tokens').value), minutes: Number(document.getElementById('progress-minutes').value) }, nextAction: document.getElementById('progress-next').value }); closeModal(); return; }
  if (action === 'reconcileTask') { reconcileModal(control.dataset.taskId); return; }
  if (action === 'submitReconcile') { vscode.postMessage({ type: 'reconcileCoordinationTask', taskId: document.getElementById('reconcile-task').value, summary: document.getElementById('reconcile-summary').value, conflictsResolved: document.getElementById('reconcile-conflicts').checked }); closeModal(); return; }
  if (action === 'releaseTask') { releaseTaskModal(control.dataset.taskId); return; }
  if (action === 'submitReleaseTask') { const taskId = document.getElementById('release-task')?.value || ''; const reason = document.getElementById('release-reason')?.value.trim() || ''; const confirmed = document.getElementById('release-confirm')?.checked === true; const validation = document.querySelector('[data-release-validation]'); if (reason.length < 10 || !confirmed) { if (validation) { validation.hidden = false; validation.textContent = reason.length < 10 ? 'Enter a specific release reason of at least 10 characters.' : 'Confirm the exact task release before continuing.'; } return; } const requestId = studioAllocationRequestId(); pendingTaskRelease = { requestId, taskId, reason, startedAt: new Date().toISOString() }; vscode.postMessage({ type: 'releaseCoordinationTask', requestId, taskId, reason, acknowledgement: { boundary: 'explicit-dashboard-confirmation', confirmed: true, taskId } }); closeModal(); return; }
  if (action === 'copyTaskHandoff') { postHostAction(action, 'copyTaskHandoff', { taskId: control.dataset.taskId }); return; }
  if (action === 'captureMemory') { captureMemoryModal(); return; }
  if (action === 'configureCanonicalMemory') { postHostAction(action, 'configureCanonicalMemory'); return; }
  if (action === 'disconnectCanonicalMemory') { postHostAction(action, 'disconnectCanonicalMemory'); return; }
  if (action === 'submitMemory') { const content = document.getElementById('memory-content').value.trim(); if (!content) { document.getElementById('memory-content').focus(); return; } vscode.postMessage({ type: 'captureCoordinationMemory', layer: document.getElementById('memory-layer').value, kind: document.getElementById('memory-kind').value, content }); closeModal(); return; }
  if (action === 'memoryRefresh') { state.memoryData = null; requestMemory(); render(); return; }
  if (action === 'memoryPrevious') { state.memoryOffset = Math.max(0, state.memoryOffset - 60); requestMemory(); render(); return; }
  if (action === 'memoryNext') { if (state.memoryData?.has_more) state.memoryOffset += 60; requestMemory(); render(); return; }
  if (action === 'activityRefresh') { state.activityData = null; requestActivity(); render(); return; }
  if (action === 'activityPause') { postHostAction(action, 'setActivityPaused', { paused: control.dataset.paused === 'true' }); return; }
  if (action === 'reconcileStaleActivity') { postHostAction(action, 'reconcileStaleActivity'); return; }
  if (action === 'knowledgeRefresh') { state.knowledgeData = null; requestKnowledge(); render(); return; }
  if (action === 'learningObserve') { learningObservationModal(); return; }
  if (action === 'learningAppendEvidence') { learningObservationModal(control.dataset.pipelineId); return; }
  if (action === 'learningPattern') { learningPatternModal(control.dataset.pipelineId); return; }
  if (action === 'learningHypothesis') { learningHypothesisModal(control.dataset.pipelineId); return; }
  if (action === 'learningTrial') { learningTrialModal(control.dataset.pipelineId); return; }
  if (action === 'learningResearch') { learningResearchModal(control.dataset.pipelineId); return; }
  if (action === 'learningFinalValidation') { learningFinalValidationModal(control.dataset.pipelineId); return; }
  if (action === 'learningReuse') { learningReuseModal(control.dataset.pipelineId); return; }
  if (action === 'inspectLearningPipeline') { const pipeline = learningPipeline(control.dataset.pipelineId); if (pipeline) showInformationModal(pipeline.hypothesis?.claim || pipeline.pipeline_id, `${String(pipeline.effective_state || pipeline.state).toUpperCase()} · SIGNED LEARNING HISTORY`, pipeline, `<p>${esc(pipeline.pattern?.interpretation || 'No pattern interpretation has been frozen.')}</p><dl class="modal-detail"><div><dt>Revision</dt><dd class="mono">${esc(pipeline.pipeline_revision_sha256)}</dd></div><div><dt>Evidence</dt><dd>${number((pipeline.operation_evidence || []).length)} operations</dd></div><div><dt>Trials</dt><dd>${number((pipeline.trials || []).length + (pipeline.secondary_trials || []).length)} retained results</dd></div><div><dt>Selected revision</dt><dd class="mono">${esc(pipeline.selected_revision?.revision_sha256 || 'not selected')}</dd></div><div><dt>Promotion decision</dt><dd class="mono">${esc(pipeline.promotion_decision?.record_sha256 || 'not reached')}</dd></div><div><dt>Knowledge proposal</dt><dd class="mono">${esc(pipeline.knowledge_proposal_id || 'not admitted')}</dd></div></dl>`); return; }
  if (action === 'submitLearningObservation') { try { const metric = document.getElementById('learning-metric')?.value.trim(); const metricValue = Number(document.getElementById('learning-metric-value')?.value); if (!metric || !Number.isFinite(metricValue)) throw new Error('A finite named metric is required.'); postLearningOperation('observe-experience', { pipeline_id: document.getElementById('learning-pipeline-id')?.value || '', operation_id: document.getElementById('learning-operation-id')?.value.trim(), task_class: document.getElementById('learning-task-class')?.value.trim(), outcome: document.getElementById('learning-outcome')?.value.trim(), measurements: { [metric]: metricValue }, capability_ids: agentList(document.getElementById('learning-capabilities')?.value), environment_sha256: document.getElementById('learning-environment-sha')?.value.trim(), source_ids: agentList(document.getElementById('learning-source-ids')?.value), evidence_refs: String(document.getElementById('learning-evidence-refs')?.value || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean) }); } catch (error) { document.getElementById('learning-metric-value')?.setCustomValidity(error.message); document.getElementById('learning-metric-value')?.reportValidity(); } return; }
  if (action === 'submitLearningPattern') { postLearningOperation('extract-pattern', { pipeline_id: document.getElementById('learning-pipeline-id')?.value, metric: document.getElementById('learning-pattern-metric')?.value.trim(), higher_is_better: document.getElementById('learning-higher-better')?.checked === true, interpretation: document.getElementById('learning-interpretation')?.value.trim(), applicability: agentList(document.getElementById('learning-applicability')?.value) }); return; }
  if (action === 'submitLearningHypothesis') { try { postLearningOperation('form-hypothesis', { pipeline_id: document.getElementById('learning-pipeline-id')?.value, unit_id: document.getElementById('learning-unit-id')?.value.trim(), kind: document.getElementById('learning-unit-kind')?.value, claim: document.getElementById('learning-claim')?.value.trim(), incumbent_artifact: learningJsonField('learning-incumbent'), challenger_artifact: learningJsonField('learning-challenger'), dependency_sha256: learningJsonField('learning-dependencies') }); } catch (error) { document.getElementById('learning-dependencies')?.setCustomValidity(error.message); document.getElementById('learning-dependencies')?.reportValidity(); } return; }
  if (action === 'submitLearningTrial') { postLearningOperation('record-trial', { pipeline_id: document.getElementById('learning-pipeline-id')?.value, winner: document.getElementById('learning-trial-winner')?.value, evidence_ref: document.getElementById('learning-trial-evidence')?.value.trim() }); return; }
  if (action === 'submitLearningResearch') { try { const rawReferences = JSON.parse(document.getElementById('learning-research-references')?.value || '[]'); if (!Array.isArray(rawReferences)) throw new Error('Research references must be a JSON array.'); const secondaryText = document.getElementById('learning-secondary-artifact')?.value.trim(); postLearningOperation('research-validate', { pipeline_id: document.getElementById('learning-pipeline-id')?.value, question: document.getElementById('learning-research-question')?.value.trim(), references: rawReferences, better_alternative_found: document.getElementById('learning-better-alternative')?.checked === true, conclusion: document.getElementById('learning-research-conclusion')?.value.trim(), secondary_artifact: secondaryText ? JSON.parse(secondaryText) : null }); } catch (error) { document.getElementById('learning-research-references')?.setCustomValidity(error.message); document.getElementById('learning-research-references')?.reportValidity(); } return; }
  if (action === 'submitLearningFinalValidation') { postLearningOperation('final-validate', { pipeline_id: document.getElementById('learning-pipeline-id')?.value, validation_evidence_ref: document.getElementById('learning-final-evidence')?.value.trim(), partial_units: agentList(document.getElementById('learning-partial-units')?.value) }); return; }
  if (action === 'learningAdmit') { postLearningOperation('admit-learning', { pipeline_id: control.dataset.pipelineId }); return; }
  if (action === 'submitLearningReuse') { postLearningOperation('measure-reuse', { pipeline_id: document.getElementById('learning-pipeline-id')?.value, uses: Number(document.getElementById('learning-reuse-uses')?.value), successes: Number(document.getElementById('learning-reuse-successes')?.value), regressions: Number(document.getElementById('learning-reuse-regressions')?.value) }); return; }
  if (action === 'knowledgePropose') { knowledgeProposalModal(); return; }
  if (action === 'submitKnowledgeProposal') {
    const id = document.getElementById('knowledge-id')?.value.trim(); const kind = document.getElementById('knowledge-kind')?.value.trim(); const title = document.getElementById('knowledge-title')?.value.trim(); const summary = document.getElementById('knowledge-summary')?.value.trim(); const source = document.getElementById('knowledge-source')?.value; const evidence = document.getElementById('knowledge-evidence')?.value.trim();
    try {
      const payload = knowledgeProposalPayload({ id, kind, title, summary, source, evidence }, state.knowledgeData?.canonical || []);
      vscode.postMessage({ type: 'studioOperation', kind: 'knowledge', operation: 'propose', payload }); closeModal();
    } catch (error) { showModal('Knowledge proposal blocked', 'CURRENT CANONICAL BINDING REQUIRED', `<p role="alert">${esc(error.message)}</p>`); }
    return;
  }
  if (action === 'knowledgeTransition') {
    const operation = control.dataset.operation; const proposalId = control.dataset.proposalId;
    if (!['verify', 'approve', 'promote'].includes(operation) || !proposalId) return;
    vscode.postMessage({ type: 'studioOperation', kind: 'knowledge', operation, payload: { proposal_id: proposalId } }); return;
  }
  if (action === 'knowledgeReject') { showModal('Reject knowledge candidate', 'GOVERNED TERMINAL DECISION', `<input type="hidden" id="knowledge-proposal-id" value="${esc(control.dataset.proposalId)}"><label class="form-field"><span>Reason</span><textarea id="knowledge-reject-reason" rows="4" placeholder="Evidence-backed rejection reason"></textarea></label>`, '<button data-action="closeModal">Cancel</button><button class="primary" data-action="submitKnowledgeReject">Reject candidate</button>'); return; }
  if (action === 'knowledgeRollback') { showModal('Rollback canonical knowledge', 'RETAINED REVISION · COMPARE-AND-SWAP · EVIDENCE REQUIRED', `<p>This changes only the canonical head. Both the displaced head and target revision remain retained.</p><input type="hidden" id="knowledge-rollback-record" value="${esc(control.dataset.recordId)}"><input type="hidden" id="knowledge-rollback-current" value="${esc(control.dataset.currentSha)}"><input type="hidden" id="knowledge-rollback-target" value="${esc(control.dataset.targetSha)}"><label class="form-field"><span>Evidence references (one per line)</span><textarea id="knowledge-rollback-evidence" rows="5" placeholder="relative/path#sha256=&lt;actual content hash&gt;"></textarea></label>`, '<button data-action="closeModal">Cancel</button><button class="danger" data-action="submitKnowledgeRollback">Authorize rollback</button>'); return; }
  if (action === 'submitKnowledgeRollback') { const recordId = document.getElementById('knowledge-rollback-record')?.value; const expectedHead = document.getElementById('knowledge-rollback-current')?.value; const target = document.getElementById('knowledge-rollback-target')?.value; const evidenceRefs = (document.getElementById('knowledge-rollback-evidence')?.value || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean); if (!recordId || !expectedHead || !target || !evidenceRefs.length) { document.getElementById('knowledge-rollback-evidence')?.focus(); return; } vscode.postMessage({ type: 'studioOperation', kind: 'knowledge', operation: 'rollback', payload: { record_id: recordId, target_sha256: target, expected_head_sha256: expectedHead, evidence_refs: evidenceRefs } }); closeModal(); return; }
  if (action === 'submitKnowledgeReject') { const proposalId = document.getElementById('knowledge-proposal-id')?.value; const reason = document.getElementById('knowledge-reject-reason')?.value.trim(); if (!proposalId || !reason) return; vscode.postMessage({ type: 'studioOperation', kind: 'knowledge', operation: 'reject', payload: { proposal_id: proposalId, reason } }); closeModal(); return; }
  if (action === 'knowledgeRecover') { vscode.postMessage({ type: 'studioOperation', kind: 'knowledge', operation: 'recover', payload: {} }); return; }
  if (action === 'filterActivityCorrelation') { requestActivity({ query: control.dataset.correlationId }); render(); return; }
  if (action === 'inspectActivityEvent') {
    const eventRecord = state.activityData?.events?.find(item => item.event_id === control.dataset.eventId); if (!eventRecord) return;
    showInformationModal(eventRecord.operation, `${String(eventRecord.category).toUpperCase()} · ${String(eventRecord.status).toUpperCase()} · METADATA ONLY`, eventRecord, `<p>This record describes an observed action without storing prompts, file contents, terminal output, secrets, or private reasoning.</p><dl class="modal-detail"><div><dt>Actor</dt><dd>${esc(eventRecord.actor?.actor_id)} · ${esc(eventRecord.actor?.harness)}</dd></div><div><dt>Correlation</dt><dd class="mono">${esc(eventRecord.correlation_id)}</dd></div><div><dt>Effect</dt><dd>${esc(eventRecord.effect)}</dd></div><div><dt>Scope references</dt><dd>${esc((eventRecord.scope_refs || []).join(', ') || 'none')}</dd></div><div><dt>Integrity seal</dt><dd class="mono">${esc(eventRecord.event_sha256)}</dd></div></dl>`); return;
  }
  if (action === 'inspectMemoryRecord') { const record = state.memoryData?.records?.find(item => item.memory_id === control.dataset.memoryId); if (record) { const sourcePath = record.source?.path || record.source_artifact || ''; showInformationModal(record.title || record.memory_type || record.memory_id, `${String(record.layer || 'canonical').toUpperCase()} · ${String(record.lifecycle_state || record.status || 'UNKNOWN').toUpperCase()} · CANONICAL`, record, `<p>${esc(record.summary || 'No canonical summary was stored.')}</p><dl class="modal-detail"><div><dt>Authority</dt><dd>${esc(record.authority || 'Lease-bound canonical workspace memory vault')}</dd></div><div><dt>Source</dt><dd class="mono">${esc(sourcePath || 'Not declared')} · ${esc(record.source?.sha256 || 'hash unavailable')}</dd></div><div><dt>Evidence</dt><dd class="mono">${esc(readableValue(record.evidence || record.evidence_locators || []))}</dd></div><div><dt>Record seal</dt><dd class="mono">${esc(record.record_sha256 || 'Seal unavailable')}</dd></div><div><dt>Lifecycle head</dt><dd class="mono">${esc(record.lifecycle_head_sha256 || 'Lifecycle seal unavailable')}</dd></div><div><dt>Confidence</dt><dd>${esc(readableValue(record.confidence))} · ${esc(record.confidence_method || 'not declared')}</dd></div></dl>${sourcePath ? `<button data-action="openMemorySource" data-path="${esc(sourcePath)}">Open governed source</button>` : ''}`); } return; }
  if (action === 'cleanupManager' || action === 'refreshCleanup') { showModal('Storage & cleanup', 'CLASSIFYING CANDIDATES', '<div class="cleanup-loading"><span class="empty-ring"></span><p>Scanning the admitted engine root. No files are changed.</p></div>'); vscode.postMessage({ type: 'scanCleanup' }); return; }
  if (action === 'teamPackPreview') { vscode.postMessage({ type: 'teamPackPreview' }); return; }
  if (action === 'enterprisePackToggle') { vscode.postMessage({ type: 'enterprisePackToggle', packId: control.dataset.packId, enabled: control.dataset.enabled === 'true' }); return; }
  if (action === 'enterpriseTargetConfigure') { vscode.postMessage({ type: 'enterpriseTargetConfigure', packId: control.dataset.packId }); return; }
  if (action === 'enterpriseDoctor') { vscode.postMessage({ type: 'enterpriseDoctor' }); return; }
  if (action === 'toggleBillablePolicy') { vscode.postMessage({ type: 'toggleBillablePolicy', enabled: control.dataset.enabled === 'true' }); return; }
  if (action === 'refreshEnvironment') { state.environmentData = {}; state.environmentPending = {}; vscode.postMessage({ type: 'refreshEnvironment' }); return; }
  if (action === 'environmentScope') { state.environmentScope = control.dataset.scope; persistDashboardState(); render(); return; }
  if (action === 'environmentExtensionDetail') { vscode.postMessage({ type: 'environmentExtensionDetail', extensionId: control.dataset.extensionId }); return; }
  if (action === 'inspectEnvironmentRecord') {
    const record = state.environmentData[state.environmentScope]?.records?.find(item => item.id === control.dataset.environmentId); if (!record) return;
    const isEnvironmentFile = state.environmentScope === 'environment-files';
    const lifecycleButton = state.environmentScope === 'environment-files' ? `<button class="secondary" data-action="previewEnvironmentLifecycle" data-environment-id="${esc(record.id)}" data-lifecycle-action="archive">Preview safe archive</button>` : state.environmentScope === 'environments' && !record.active && !['active', 'wrong-version'].includes(record.state) ? `<button class="secondary" data-action="previewEnvironmentLifecycle" data-environment-id="${esc(record.id)}" data-lifecycle-action="quarantine">Preview safe quarantine</button>` : state.environmentScope === 'environments' ? '<p class="fine-print">Maintenance is blocked while this environment is selected, active, or version-conflicted.</p>' : '';
    const human = isEnvironmentFile
      ? `<p>Pacify-X stores variable names, requirements, consumers, exposure state, and metadata only. Values and weak value fingerprints are prohibited.</p><dl class="modal-detail"><div><dt>Variables</dt><dd>${esc((record.variables || []).map(item => `${item.name}${item.provider ? ` → ${item.provider}` : ''}${item.required ? ' (required)' : ''}`).join(', ') || 'None')}</dd></div><div><dt>Consumers</dt><dd>${esc((record.variables || []).flatMap(item => item.consumers || []).map(item => item.path).join(', ') || 'None detected')}</dd></div><div><dt>Maintenance authority</dt><dd>Exact-target preview, active-consumer revalidation, confirmation, reversible disposition, and receipt are required before mutation.</dd></div></dl>${lifecycleButton}`
      : `<p>This is a read-only discovery record. Detection does not authorize execution, update, maintenance, or deletion.</p>${humanRecord(record)}${lifecycleButton}`;
    showInformationModal(record.relative_path || record.id, isEnvironmentFile ? 'SECRET-SAFE ENVIRONMENT SCHEMA' : 'SYSTEM RESOURCE RECORD', record, human); return;
  }
  if (action === 'previewEnvironmentLifecycle') { vscode.postMessage({ type: 'environmentLifecyclePreview', subject: state.environmentScope, recordId: control.dataset.environmentId, action: control.dataset.lifecycleAction }); return; }
  if (action === 'executeEnvironmentLifecycle') { const target = document.getElementById('environment-lifecycle-target'); const acknowledgement = document.getElementById('environment-lifecycle-consumers'); if (!target || target.value !== target.dataset.exactTarget || (acknowledgement && !acknowledgement.checked)) return; vscode.postMessage({ type: 'environmentLifecycleExecute', token: control.dataset.token, exactTarget: target.value, consumerImpactAcknowledged: Boolean(acknowledgement?.checked) }); closeModal(); return; }
  if (action === 'cleanupSelectAll') { const candidates = cleanupState.inventory?.candidates || []; cleanupState.selected = cleanupState.selected.size === candidates.length ? new Set() : new Set(candidates.map(item => item.id)); renderCleanupManager(); return; }
  if (action === 'cleanupRecycle' || action === 'cleanupPermanent') { vscode.postMessage({ type: 'executeCleanup', ids: [...cleanupState.selected], disposition: action === 'cleanupPermanent' ? 'permanent' : 'recycle' }); return; }
  if (action === 'copyModal') { postHostAction(action, 'copyText', { text: modalCopyText }); return; }
  if (action === 'toggleAdvanced') { if (!state.settings.showAdvancedSurfaces) postHostAction('openSettings', 'openSettings'); else { state.advancedOpen = !state.advancedOpen; render(); } return; }
  const directMessages = { refresh: 'refresh', validate: 'validate' };
  if (directMessages[action]) { vscode.postMessage({ type: directMessages[action] }); return; }
  const hostMessages = { openSettings: 'openSettings', contextSnapshot: 'createContextSnapshot', continueCodex: 'continueCodex', cancelCodex: 'cancelCodex', openCoordinationHandoff: 'openCoordinationHandoff' };
  if (hostMessages[action]) { postHostAction(action, hostMessages[action]); return; }
  if (action === 'openEngineRoot') { if (state.snapshot?.source?.engineRoot) postHostAction(action, 'openFile', { path: `${state.snapshot.source.engineRoot}${state.snapshot.source.engineRoot.includes('\\') ? '\\' : '/'}README.md` }); else showModal('Engine root unavailable', 'NO CONFIGURED TARGET', '<p>Configure a Pacify-X engine root before opening its README.</p>'); return; }
  if (action === 'openKnowledgeSource') { const root = state.snapshot?.source?.engineRoot; const relative = String(control.dataset.path || ''); if (root && relative) postHostAction(action, 'openFile', { path: `${root}${root.includes('\\') ? '\\' : '/'}${relative}` }); return; }
  if (action === 'openMemorySource') { const root = state.snapshot?.memory?.workspace_root; const supplied = String(control.dataset.path || ''); if (root && supplied) { const absolute = /^(?:[A-Za-z]:[\\/]|\/)/.test(supplied); postHostAction(action, 'openFile', { path: absolute ? supplied : `${root}${root.includes('\\') ? '\\' : '/'}${supplied}` }); } return; }
});

app.addEventListener('wheel', event => {
  const canvas = event.target.closest('[data-graph-canvas]'); if (!canvas) return; event.preventDefault();
  if (event.ctrlKey || event.metaKey) { zoomGraphTo(graphInteraction.scale * Math.exp(-event.deltaY * 0.0025), event.clientX, event.clientY); return; }
  graphInteraction.x -= event.shiftKey && !event.deltaX ? event.deltaY : event.deltaX; graphInteraction.y -= event.shiftKey ? 0 : event.deltaY;
  applyGraphViewport('Map panned');
}, { passive: false });

app.addEventListener('dblclick', event => {
  const canvas = event.target.closest('[data-graph-canvas]'); if (!canvas || event.target.closest('.graph-node, .graph-minimap')) return;
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
app.addEventListener('focusout', event => {
  if (studioEditor?.kind !== 'agent' || !['tool_binding_ids', 'memory_binding_ids', 'handoff_agent_ids'].includes(event.target.dataset?.agentListField)) return;
  requestAnimationFrame(() => { const visual = document.querySelector('[data-studio-panel="visual"]'); if (studioEditor?.kind === 'agent' && visual && !visual.hidden) refreshStudioEditor('[data-agent-editor-canvas]'); });
});

app.addEventListener('input', event => {
  if (event.target.matches('#environment-lifecycle-target')) { updateEnvironmentLifecycleGate(); return; }
  if (studioEditor && ['studio-identity', 'studio-version', 'studio-owner'].includes(event.target.id)) {
    studioDraftDirty = true;
    const identityField = studioEditor.kind === 'agent' ? 'agent_id' : studioEditor.kind === 'workflow' ? 'workflow_id' : 'skill_id';
    const field = event.target.id === 'studio-identity' ? identityField : event.target.id === 'studio-version' ? 'version' : 'owner'; studioEditor.draft[field] = event.target.value.trim();
    if (field === identityField) { for (const grant of studioEditor.draft.grants || []) grant.subject_id = studioEditor.draft[identityField]; for (const binding of studioEditor.draft.bindings || []) binding.subject_id = studioEditor.draft[identityField]; }
    if (studioEditor.kind === 'agent') { agentGraphDirty = true; updateAgentValidationBox(); }
    persistWorkingStudioDraft(); return;
  }
  if (updateAgentDraftFromControl(event.target)) { studioDraftDirty = true; persistWorkingStudioDraft(); return; }
  if (updateWorkflowAuthorityFromControl(event.target)) { studioDraftDirty = true; persistWorkingStudioDraft(); return; }
  if (event.target.matches('#studio-skill-file')) { studioDraftDirty = true; syncSkillEditorFile(); const validation = studioEditors.validateSkill(studioEditor.draft); const box = document.querySelector('[data-studio-validation]'); if (box) { box.classList.toggle('passed', validation.valid); box.classList.toggle('failed', !validation.valid); box.querySelector('b').textContent = validation.valid ? `${validation.file_count} files pass browser preflight` : `${validation.issues.length} package issue(s)`; } persistWorkingStudioDraft(); return; }
  if (event.target.matches('#studio-draft-json') && studioEditor) { studioDraftDirty = true; persistWorkingStudioDraft(); return; }
  const activityInput = event.target.closest('[data-activity-search]');
  if (activityInput) { clearTimeout(searchTimer); state.activityQuery = activityInput.value; searchTimer = setTimeout(() => requestActivity({ query: activityInput.value }), 250); return; }
  const memoryInput = event.target.closest('[data-memory-search]');
  if (memoryInput) { clearTimeout(searchTimer); state.memoryQuery = memoryInput.value; state.memoryOffset = 0; searchTimer = setTimeout(() => requestMemory(memoryInput.value), 250); return; }
  const memoryProject = event.target.closest('[data-memory-project]');
  if (memoryProject) { clearTimeout(searchTimer); state.memoryProject = memoryProject.value; state.memoryOffset = 0; searchTimer = setTimeout(() => requestMemory(), 250); return; }
  const memorySource = event.target.closest('[data-memory-source]');
  if (memorySource) { clearTimeout(searchTimer); state.memorySource = memorySource.value; state.memoryOffset = 0; searchTimer = setTimeout(() => requestMemory(), 250); return; }
  const graphTarget = event.target.closest('[data-graph-target]');
  if (graphTarget) { state.graphTarget = graphTarget.value; return; }
  const input = event.target.closest('[data-catalog-search]'); if (!input) return;
  clearTimeout(searchTimer); const kind = input.dataset.catalogSearch;
  searchTimer = setTimeout(() => requestCatalog(kind, { query: input.value, offset: 0 }), 250);
});
app.addEventListener('change', event => {
  if (event.target.matches('#environment-lifecycle-consumers')) { updateEnvironmentLifecycleGate(); return; }
  if (updateAgentDraftFromControl(event.target)) { studioDraftDirty = true; persistWorkingStudioDraft(); return; }
  const agentNodeKind = event.target.closest('[data-agent-node-kind]');
  if (agentNodeKind && studioEditor?.kind === 'agent') { try { const edited = studioEditors.editAgentBuilderNode(studioEditor.draft, currentAgentGraph(studioEditor.draft).graph, { type: 'retype', node_id: agentNodeKind.dataset.agentNodeId, kind: agentNodeKind.value }); studioEditor.draft = edited.draft; agentWorkingGraph = edited.graph; agentSelectedSection = edited.selected_node_id.replace(/^agent-node:/, ''); agentConnectionStart = null; agentGraphDirty = true; refreshStudioEditor(`[data-agent-node-id="${CSS.escape(edited.selected_node_id)}"]`); } catch (error) { agentNodeKind.setCustomValidity(error.message); agentNodeKind.reportValidity(); } return; }
  if (updateWorkflowAuthorityFromControl(event.target)) { studioDraftDirty = true; persistWorkingStudioDraft(); return; }
  const workflowAdapter = event.target.closest('[data-workflow-adapter]');
  if (workflowAdapter && studioEditor?.kind === 'workflow') { const node = studioEditor.draft.nodes.find(item => item.node_id === studioSelectedNode); if (!node) return; studioEditor.draft.executor_adapters = { ...(studioEditor.draft.executor_adapters || {}), [node.executor_binding_id]: workflowAdapter.value }; studioEditor.draft.authority_definition_state = 'supplied-for-new-revision'; refreshStudioEditor('[data-workflow-adapter]'); return; }
  const workflowPortField = event.target.closest('[data-workflow-port-field]');
  if (workflowPortField && studioEditor?.kind === 'workflow') { const node = studioEditor.draft.nodes.find(item => item.node_id === studioSelectedNode); const direction = workflowPortField.dataset.direction; const port = node?.[direction]?.[Number(workflowPortField.dataset.index)]; if (!port) return; const field = workflowPortField.dataset.workflowPortField; const priorName = port.name; port[field] = field === 'required' ? workflowPortField.checked : workflowPortField.value.trim(); if (field === 'name') for (const edge of studioEditor.draft.edges) { if (direction === 'inputs' && edge.target_node === node.node_id && edge.target_port === priorName) edge.target_port = port.name; if (direction === 'outputs' && edge.source_node === node.node_id && edge.source_port === priorName) edge.source_port = port.name; } studioEditor.draft = studioEditors.normalizeWorkflow(studioEditor.draft); refreshStudioEditor(`[data-workflow-port-field="${field}"][data-direction="${direction}"][data-index="${workflowPortField.dataset.index}"]`); return; }
  const workflowField = event.target.closest('[data-workflow-field]');
  if (workflowField && studioEditor?.kind === 'workflow') { const node = studioEditor.draft.nodes.find(item => item.node_id === studioSelectedNode); if (!node) return; const field = workflowField.dataset.workflowField; const priorId = node.node_id; try { node[field] = field === 'approval_required' ? workflowField.checked : ['timeout_seconds', 'retry_limit'].includes(field) ? Number(workflowField.value) : field === 'effect_grant_ids' ? agentList(workflowField.value) : field === 'config' ? JSON.parse(workflowField.value || '{}') : workflowField.value.trim(); if (field === 'kind') { node.approval_required = node.kind === 'approval'; if (node.kind === 'validation') { node.failure_policy = 'fail-closed'; node.config = { checks: [{ id: 'check:input-exists', source: 'inputs', port: node.inputs?.[0]?.name || 'value', operator: 'exists' }] }; } else node.config = {}; if (node.kind === 'branch') { node.inputs = [{ name: 'value', data_type: 'boolean', required: true }]; node.outputs = [{ name: 'value', data_type: 'boolean', required: true }]; } if (node.kind === 'join') { node.inputs = [{ name: 'true-value', data_type: 'boolean', required: false }, { name: 'false-value', data_type: 'boolean', required: false }]; node.outputs = [{ name: 'true-value', data_type: 'boolean', required: false }, { name: 'false-value', data_type: 'boolean', required: false }]; } studioEditor.draft.edges = studioEditor.draft.edges.filter(edge => edge.source_node !== node.node_id && edge.target_node !== node.node_id); } if (field === 'node_id') { studioSelectedNode = node.node_id; for (const edge of studioEditor.draft.edges) { if (edge.source_node === priorId) edge.source_node = node.node_id; if (edge.target_node === priorId) edge.target_node = node.node_id; } } studioEditor.draft = studioEditors.normalizeWorkflow(studioEditor.draft); refreshStudioEditor(`[data-workflow-field="${field}"]`); } catch (error) { workflowField.setCustomValidity(`Invalid ${field}: ${error.message}`); workflowField.reportValidity(); } return; }
  const graphKind = event.target.closest('[data-graph-kind]'); if (graphKind) { state.graphMode = 'full'; state.graphLayout = 'community'; state.graphKind = graphKind.value; state.graphData = null; persistStudioMetadata(); requestGraph({ mode: 'full', cluster: state.graphCommunity, kind: state.graphKind, status: state.graphStatus, offset: 0, edgeOffset: 0 }); render(); return; }
  const graphStatus = event.target.closest('[data-graph-status-filter]'); if (graphStatus) { state.graphMode = 'full'; state.graphLayout = 'community'; state.graphStatus = graphStatus.value; state.graphData = null; persistStudioMetadata(); requestGraph({ mode: 'full', cluster: state.graphCommunity, kind: state.graphKind, status: state.graphStatus, offset: 0, edgeOffset: 0 }); render(); return; }
  const graphRecord = event.target.closest('[data-graph-record-list]'); if (graphRecord) { const key = graphRecord.value; if (key && state.graphData?.nodes?.some(item => item.key === key)) { state.graphData = { ...state.graphData, selected: key }; render(); requestAnimationFrame(prepareGraphInteraction); } return; }
  const graphAnalysis = event.target.closest('[data-graph-analysis]'); if (graphAnalysis) { state.graphMode = graphAnalysis.value; if (state.graphMode !== 'path') state.graphTarget = ''; persistStudioMetadata(); render(); return; }
  const activityCategory = event.target.closest('[data-activity-category]'); if (activityCategory) { requestActivity({ category: activityCategory.value }); return; }
  const activityStatus = event.target.closest('[data-activity-status]'); if (activityStatus) { requestActivity({ status: activityStatus.value }); return; }
  const memoryStatus = event.target.closest('[data-memory-status]'); if (memoryStatus) { state.memoryStatus = memoryStatus.value; state.memoryOffset = 0; requestMemory(); return; }
  const checkbox = event.target.closest('[data-cleanup-id]');
  if (checkbox) { if (checkbox.checked) cleanupState.selected.add(checkbox.dataset.cleanupId); else cleanupState.selected.delete(checkbox.dataset.cleanupId); renderCleanupManager(); return; }
  const sort = event.target.closest('[data-catalog-sort]'); if (sort) requestCatalog(sort.dataset.catalogSort, { sort: sort.value, offset: 0 });
  const catalogStatus = event.target.closest('[data-catalog-status]'); if (catalogStatus) requestCatalog(catalogStatus.dataset.catalogStatus, { status: catalogStatus.value, offset: 0 });
});
app.addEventListener('keydown', event => {
  if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('.metric-card')) { event.preventDefault(); event.target.click(); }
  if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('.agent-graph-node')) { event.preventDefault(); event.target.click(); return; }
  if (event.key === 'Enter' && event.target.matches('[data-graph-search]')) { event.preventDefault(); app.querySelector('[data-action="runGraphSearch"]')?.click(); }
  if (event.key === 'Enter' && event.target.matches('[data-graph-target]')) { event.preventDefault(); app.querySelector('[data-action="runGraphSearch"]')?.click(); }
  const workflowNode = event.target.closest?.('.workflow-editor-node');
  if (workflowNode && event.altKey && ['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'].includes(event.key)) { event.preventDefault(); studioSelectedNode = workflowNode.dataset.nodeId; const delta = event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 1; app.querySelector(`[data-action="workflowMoveNode"][data-delta="${delta}"]`)?.click(); return; }
  const agentNode = event.target.closest?.('.agent-graph-node');
  if (agentNode && event.altKey && ['ArrowLeft', 'ArrowUp', 'ArrowRight', 'ArrowDown'].includes(event.key) && studioEditor?.kind === 'agent') {
    event.preventDefault(); const graph = currentAgentGraph(studioEditor.draft).graph; const layout = agentLayoutMap(studioEditor.draft, graph); const point = layout[agentNode.dataset.agentNodeId];
    if (point) { const distance = event.shiftKey ? 40 : 10; if (event.key === 'ArrowLeft') point.x -= distance; if (event.key === 'ArrowRight') point.x += distance; if (event.key === 'ArrowUp') point.y -= distance; if (event.key === 'ArrowDown') point.y += distance; studioEditor.draft.editor_layout = layout; agentGraphDirty = true; agentSelectedSection = agentNode.dataset.agentKind; refreshStudioEditor(`[data-agent-node-id="${CSS.escape(agentNode.dataset.agentNodeId)}"]`); }
    return;
  }
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
  const focusedGraph = state.graphFocusMode ? app.querySelector('.graph-focus-mode') : null;
  if (focusedGraph && event.key === 'Tab' && !event.target.closest('.control-modal')) {
    const focusable = [...focusedGraph.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex="0"]')].filter(item => item.getClientRects().length > 0);
    if (focusable.length) {
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }
  const modal = event.target.closest('.control-modal');
  if (modal && event.key === 'Tab') {
    const focusable = [...modal.querySelectorAll('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex="0"]')];
    if (!focusable.length) return;
    const first = focusable[0]; const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  if (document.querySelector('#modal-root [role="dialog"]')) {
    event.preventDefault(); closeModal(); return;
  }
  if (state.graphFocusMode) {
    event.preventDefault(); state.graphFocusMode = false; graphInteraction.fitted = false; render(); finishGraphFocusTransition(false);
  }
});

app.addEventListener('dragstart', event => {
  const palette = event.target.closest('[data-node-template]'); const node = event.target.closest('.workflow-editor-node'); const agentNode = event.target.closest('.agent-graph-node');
  if (palette) event.dataTransfer?.setData('application/x-px-workflow-node', palette.dataset.nodeTemplate);
  if (node) event.dataTransfer?.setData('application/x-px-workflow-existing', node.dataset.nodeId);
  if (agentNode) event.dataTransfer?.setData('application/x-px-agent-node', agentNode.dataset.agentNodeId);
});
app.addEventListener('dragover', event => { if (event.target.closest('[data-workflow-editor-canvas],[data-agent-editor-canvas]')) event.preventDefault(); });
app.addEventListener('drop', event => {
  const agentCanvas = event.target.closest('[data-agent-editor-canvas]');
  if (agentCanvas && studioEditor?.kind === 'agent') {
    event.preventDefault(); const nodeId = event.dataTransfer?.getData('application/x-px-agent-node'); const graph = currentAgentGraph(studioEditor.draft).graph;
    if (!graph.nodes.some(node => node.node_id === nodeId)) return;
    const rect = agentCanvas.getBoundingClientRect(); const layout = agentLayoutMap(studioEditor.draft, graph);
    layout[nodeId] = { x: finiteLayoutNumber((event.clientX - rect.left + agentCanvas.scrollLeft) / agentScale - 94, -100000, 100000, 36), y: finiteLayoutNumber((event.clientY - rect.top + agentCanvas.scrollTop) / agentScale - 48, -100000, 100000, 42) };
    studioEditor.draft.editor_layout = layout; agentGraphDirty = true; agentSelectedSection = nodeId.replace(/^agent-node:/, ''); refreshStudioEditor(`[data-agent-node-id="${CSS.escape(nodeId)}"]`); return;
  }
  const canvas = event.target.closest('[data-workflow-editor-canvas]'); if (!canvas || studioEditor?.kind !== 'workflow') return; event.preventDefault();
  const rect = canvas.getBoundingClientRect(); const position = { x: Math.max(8, Math.round((event.clientX - rect.left + canvas.scrollLeft) / workflowScale - 80)), y: Math.max(8, Math.round((event.clientY - rect.top + canvas.scrollTop) / workflowScale - 30)) };
  const existing = event.dataTransfer?.getData('application/x-px-workflow-existing'); const template = event.dataTransfer?.getData('application/x-px-workflow-node');
  if (existing) { const node = studioEditor.draft.nodes.find(item => item.node_id === existing); if (node) { node.position = position; studioSelectedNode = existing; refreshStudioEditor(`[data-node-id="${CSS.escape(existing)}"]`); } }
  else if (template) addWorkflowNode(template, position);
});

window.addEventListener('message', event => {
  const message = event.data;
  if (!message || typeof message !== 'object') return;
  if (message.type === 'deepLink' && typeof message.route === 'string' && message.route.startsWith('/control-plane')) {
    const route = message.route.slice(0, 1000); const parts = route.split('/').filter(Boolean);
    const decodeRouteId = value => {
      if (typeof value !== 'string' || !value) return null;
      try { return decodeURIComponent(value); } catch { return value; }
    };
    const resolveTaskRecord = ({ tasks, suppliedId }) => {
      if (!suppliedId) return null;
      const directTask = tasks.find(item => item.id === suppliedId);
      if (directTask) return directTask;
      for (const task of tasks) {
        const subtasks = Array.isArray(task.subtasks) ? task.subtasks : [];
        const directSubtask = subtasks.find(item => {
          const subtaskSafeId = item?.id || '';
          return subtaskSafeId === suppliedId || `${task.id}.${subtaskSafeId}` === suppliedId;
        });
        if (directSubtask) return { ...directSubtask, parentTaskId: task.id, parentTaskName: task.name || task.title, parentTaskStatus: task.status };
      }
      if (!suppliedId || !String(suppliedId).includes('.')) return null;
      for (const task of tasks) {
        if (suppliedId.startsWith(`${task.id}.`)) {
          const subtaskHint = suppliedId.slice(task.id.length + 1);
          const subtasks = Array.isArray(task.subtasks) ? task.subtasks : [];
          const subtask = subtasks.find(item => item.id === subtaskHint) || subtasks[Number(subtaskHint.replace(/[^0-9]/g, '')) - 1];
          if (subtask) return { ...subtask, parentTaskId: task.id, parentTaskName: task.name || task.title, parentTaskStatus: task.status };
        }
      }
      const index = suppliedId.lastIndexOf('.');
      if (index <= 0 || index >= suppliedId.length - 1) return null;
      const parentId = suppliedId.slice(0, index);
      const subtaskHint = suppliedId.slice(index + 1);
      const parent = tasks.find(item => item.id === parentId);
      if (!parent || !Array.isArray(parent.subtasks)) return null;
      const subtask = parent.subtasks.find(item => item.id === subtaskHint) || parent.subtasks[Number(subtaskHint.replace(/[^0-9]/g, '')) - 1];
      return subtask ? { ...subtask, parentTaskId: parent.id, parentTaskName: parent.name || parent.title, parentTaskStatus: parent.status } : null;
    };
    const controlPlaneIndex = parts.indexOf('control-plane');
    const routeKind = controlPlaneIndex >= 0 ? parts[controlPlaneIndex + 1] || null : null;
    const studioSurface = ['agent-studio', 'workflow-studio', 'skill-studio'].includes(routeKind) ? routeKind : null;
    const suppliedEntity = message.entity && typeof message.entity === 'object' ? message.entity : null;
    const kind = suppliedEntity?.type || (parts.includes('waves') ? 'wave' : parts.includes('tasks') ? 'task' : parts.includes('orchestrations') ? 'orchestration' : parts.includes('providers') ? 'provider' : parts.includes('agents') ? 'agent' : parts.includes('plans') ? 'plan' : routeKind === 'knowledge-graph' ? 'knowledge-graph' : routeKind === 'attention' ? 'attention' : routeKind);
    // The root control-plane route is navigation, not an entity deep link.
    // Treating its final path segment as an entity ID opened a blocking
    // "UNKNOWN control-plane" modal on every normal dashboard launch.
    const id = suppliedEntity?.id || (routeKind && !studioSurface ? decodeRouteId(parts.at(-1)) : null);
    state.active = studioSurface || (kind === 'knowledge-graph' ? 'knowledgeGraph' : kind === 'agent' ? 'agents' : ['plan', 'wave', 'task', 'orchestration'].includes(kind) ? 'workflows' : kind === 'provider' ? (state.settings.showAdvancedSurfaces ? 'runtimeCore' : 'diagnostics') : kind === 'attention' ? 'diagnostics' : 'dashboard');
    persistDashboardState();
    render();
    const coordination = state.coordination?.state || {}; let record = suppliedEntity?.record && typeof suppliedEntity.record === 'object' ? suppliedEntity.record : null;
    if (!record && kind === 'task') {
      const tasks = [...(coordination.tasks || []), ...(coordination.plans || []).flatMap(item => item.waves || []).flatMap(item => item.tasks || [])];
      const taskRows = tasks.flatMap(task => [task, ...(task.subtasks || []).map(subtask => ({ ...subtask, parentTaskId: task.id, parentTaskName: task.name }))]);
      record = taskRows.find(item => item.id === id) || resolveTaskRecord({ tasks, suppliedId: id });
    }
    else if (!record && kind === 'plan') record = coordination.plans?.find(item => item.id === id);
    else if (!record && kind === 'wave') record = (coordination.waves || []).find(item => item.id === id) || (coordination.plans || []).flatMap(item => item.waves || []).find(item => item.id === id);
    else if (!record && kind === 'agent') record = coordination.sessions?.find(item => item.actor_id === id || item.id === id);
    else if (!record && kind === 'orchestration') record = (coordination.orchestrations || state.coordination?.orchestrations || []).find(item => item.id === id || item.orchestration_id === id);
    else if (!record && kind === 'provider') record = (state.snapshot?.providerActivity || []).find(item => item.id === id || item.provider_id === id || item.providerId === id);
    if (record) showInformationModal(record.title || record.objective || record.name || record.actor_id || id, `SIDEBAR DEEP LINK · ${String(kind).toUpperCase()} OBJECT`, record, humanRecord(record));
    else if (id && kind !== 'knowledge-graph') showInformationModal(id, `SIDEBAR DEEP LINK · ${String(kind || 'UNKNOWN').toUpperCase()}`, { type: kind, id, status: 'not present in the current snapshot' }, '<p>The route opened its owning surface, but this entity is no longer present in the current bounded snapshot. Refresh the source view to reconcile it.</p>');
  }
  if (message.type === 'snapshot') { state.snapshot = message.snapshot; if (!canonicalMemoryReady()) { state.memoryData = null; state.memoryPending = false; state.memoryRequestId = null; } state.settings = message.settings || state.settings; state.coordination = message.coordination || state.coordination; state.activityData = message.coordination?.activity || state.activityData; state.clientActor = message.clientActor || state.clientActor; render(); }
  if (message.type === 'settings') { state.settings = message.settings || state.settings; render(); }
  if (message.type === 'hostModelCatalog') { studioModelCatalog = Array.isArray(message.models) ? message.models : []; if (studioEditor?.kind === 'agent') refreshStudioEditor('[data-agent-host-model]'); }
  if (message.type === 'validation' && state.snapshot) { state.snapshot.validation = message.result; render(); }
  if (message.type === 'catalogResult') {
    const kind = message.result.kind; const activeRequest = state.catalogRequests[kind];
    if (!activeRequest || activeRequest.requestId === message.requestId) { if (activeRequest) delete activeRequest.requestId; state.catalogs[kind] = message.result; renderPreservingControl(`[data-catalog-search="${CSS.escape(kind)}"]`); }
  }
  if (message.type === 'operationalCardsResult' && message.requestId === state.operationalCardsRequestId) { state.operationalCardsData = message.result; renderPreservingControl('[data-operational-card-search]'); return; }
  if (message.type === 'operationalCardResult') {
    const result = message.result || {}; const record = result.card || {};
    const chain = Object.entries(record.interaction_chain || {}).map(([stage, item]) => `<div class="table-row"><strong>${esc(stage.replaceAll('_', ' '))}</strong>${badge(String(item.state || 'unknown').toUpperCase(), item.state === 'present' ? 'success' : item.state === 'not_applicable' ? 'neutral' : item.state === 'partial' ? 'info' : 'warning')}<span>${esc(item.detail || '')}</span><small class="mono">${esc((item.evidence || []).join(' · ') || 'no evidence')}</small></div>`).join('');
    const sources = (record.source_refs || []).map(item => `<div class="action-grid"><button data-action="openPunchSource" data-path="${esc(item.path)}">Open ${esc(item.path)}</button><span class="mono">${esc((item.symbols || []).join(', ') || 'whole file')}</span></div>`).join('');
    const history = (record.history || []).map(item => `<article class="diagnostic-trace"><header><strong>${esc(item.event === 'transition' ? `${item.from} → ${item.to}` : item.event)}</strong><small>${esc(item.timestamp || '')} · ${esc(item.actor || '')}</small></header><p>${esc(item.reason || item.note || '')}</p><ul>${(item.evidence || []).map(evidence => `<li><span class="mono">${esc(evidence.reference || '')}</span> — ${esc(evidence.claim || '')}${evidence.artifact_sha256 ? `<small class="mono"> sha256:${esc(evidence.artifact_sha256)}</small>` : ''}</li>`).join('')}</ul></article>`).join('');
    const arrays = `<dl class="modal-detail"><div><dt>Dependencies</dt><dd>${esc((record.dependencies || []).join(', ') || 'none')}</dd></div><div><dt>Blockers</dt><dd>${esc((record.blockers || []).join(', ') || 'none')}</dd></div><div><dt>Tests required</dt><dd>${esc((record.tests_required || []).join(' · ') || 'none')}</dd></div><div><dt>Completion evidence</dt><dd class="mono">${esc((record.completion_evidence || []).join(' · ') || 'none')}</dd></div><div><dt>Next action</dt><dd>${esc(record.next_action || '')}</dd></div></dl>`;
    closeModal(); showInformationModal(record.gap_id || 'Operational card', `${String(record.current_state || 'unknown').toUpperCase()} · ${String(record.severity || 'unknown').toUpperCase()} · APPEND-ONLY HISTORY`, result, `<p><b>Expected:</b> ${esc(record.expected_behavior || '')}</p><p><b>Observed:</b> ${esc(record.observed_behavior || '')}</p><p><b>Impact:</b> ${esc(record.operational_impact || '')}</p>${arrays}<h3>Source and symbols</h3>${sources || '<p>No source references retained.</p>'}<h3>Interaction chain</h3><div class="data-table">${chain}</div><h3>Complete state history</h3><div class="diagnostic-trace-list">${history}</div>`); return;
  }
  if (message.type === 'operationalInventoryResult') {
    const result = message.result || {}; const surfaces = result.surfaces || [];
    const rows = surfaces.map(item => `<article class="diagnostic-trace"><header><div><strong>${esc(item.surface_id)}</strong><small>${esc(item.name || '')}</small></div>${badge(item.examined ? 'EXAMINED' : 'UNRESOLVED', item.examined ? 'success' : 'warning')}</header><p>${number(item.disposed_control_count ?? Object.keys(item.control_dispositions || {}).length)} / ${number(item.known_control_count ?? (item.known_controls || []).length)} controls have evidence-backed dispositions.</p>${item.known_controls ? `<dl><div><dt>Known controls</dt><dd class="mono">${esc(item.known_controls.join(' · '))}</dd></div><div><dt>Dispositions</dt><dd class="mono">${esc(JSON.stringify(item.control_dispositions || {}))}</dd></div></dl>` : `<button data-action="inspectOperationalInventory" data-surface-id="${esc(item.surface_id)}">Inspect controls</button>`}</article>`).join('');
    closeModal(); showInformationModal('Operational surface inventory', `${number(result.progress?.surfaces_inventoried || 0)} REGISTERED · ${number(result.progress?.controls_not_yet_disposed || 0)} CONTROLS UNRESOLVED`, result, `<div class="diagnostic-trace-list">${rows || '<p>No registered surfaces were returned.</p>'}</div>`); return;
  }
  if (message.type === 'skillQueryResult') {
    const result = message.result || {}; const candidates = Array.isArray(result.candidates) ? result.candidates.slice(0, 3) : [];
    const rows = candidates.map(item => `<article class="skill-query-result"><header><div><b>${esc(item.id)}</b><small>${esc(item.version || 'version unknown')} · ${esc(item.origin || 'origin unknown')}</small></div>${badge(Number(item.score || 0).toFixed(2), 'info')}</header><p>${esc(item.description || 'No description supplied.')}</p><dl><div><dt>Selection</dt><dd>${esc(item.selection_rationale || 'No rationale supplied.')}</dd></div><div><dt>Domain</dt><dd>${esc(item.domain || result.requested_domains?.[0] || 'unknown')}</dd></div><div><dt>Admission</dt><dd>${esc(item.admission || item.status || 'unknown')}</dd></div><div><dt>Original backup</dt><dd class="mono">${esc(item.backup || 'not declared')}</dd></div></dl><button class="primary" data-action="hydrateSkillCandidate" data-skill-id="${esc(item.id)}" data-domain="${esc(item.domain || result.requested_domains?.[0] || 'px-standard')}" ${item.body_available === false ? 'disabled' : ''}>Load this exact skill</button></article>`).join('');
    showInformationModal('Eligible skill candidates', `${esc(String(result.mode || 'semantic').toUpperCase())} · ${number(candidates.length)} OF ${number(result.candidate_limit || 3)} MAXIMUM`, result, `<p>${esc(result.query || '')}</p><div class="skill-query-results">${rows || '<p class="compact-empty">No admitted skill in this domain matched the task. Nothing was hydrated or executed.</p>'}</div>`); return;
  }
  if (message.type === 'skillHydrateResult') {
    const result = message.result || {}; showInformationModal(result.id || 'Hydrated skill', 'READ-ONLY BODY · NOT EXECUTED OR ADMITTED', result, `<dl class="modal-detail"><div><dt>Domain</dt><dd>${esc(result.domain || 'unknown')}</dd></div><div><dt>Origin</dt><dd>${esc(result.origin || 'unknown')}</dd></div><div><dt>Body hash</dt><dd class="mono">${esc(result.body_sha256 || 'unavailable')}</dd></div></dl><pre class="skill-hydrated-body">${esc(result.body || 'No body returned.')}</pre><p class="modal-note">This inspection loaded one exact skill body. It did not execute the skill or change any lifecycle state.</p>`); return;
  }
  if (message.type === 'skillCompareResult') {
    const pending = pendingSkillComparison; const result = message.result || {};
    if (!pending || message.requestId !== pending.requestId || message.skill !== pending.skill || result.skill_id !== pending.skill) return;
    pendingSkillComparison = null;
    const files = result.file_comparison || {}; const changes = Array.isArray(files.changes) ? files.changes : []; const metadata = Array.isArray(result.metadata_changes) ? result.metadata_changes : [];
    const metadataRows = metadata.map(item => `<tr><th>${esc(item.field)}</th><td>${esc(typeof item.px === 'object' ? JSON.stringify(item.px) : String(item.px ?? 'unavailable'))}</td><td>${esc(typeof item.preserved === 'object' ? JSON.stringify(item.preserved) : String(item.preserved ?? 'unavailable'))}</td></tr>`).join('');
    const fileRows = changes.map(item => `<button class="project-map-row"><span><strong>${esc(item.path)}</strong><small class="mono">PX ${esc(item.px_sha256 || 'absent')} · original ${esc(item.preserved_sha256 || 'absent')}</small></span><b>${esc(String(item.state || 'changed').replaceAll('_', ' ').toUpperCase())}</b></button>`).join('');
    showInformationModal(`${result.skill_id} comparison`, `${result.identical ? 'IDENTICAL' : 'DIFFERENT'} · VERIFIED PACKAGE TREES · READ ONLY`, result, `<p>${esc(result.authority || 'Read-only skill custody comparison.')}</p><dl class="detail-list"><div><dt>PX package tree</dt><dd class="mono">${esc(result.px?.package_tree_sha256 || 'unavailable')}</dd></div><div><dt>Preserved tree</dt><dd class="mono">${esc(result.preserved?.package_tree_sha256 || 'unavailable')}</dd></div><div><dt>Files</dt><dd>${number(files.px_file_count)} PX / ${number(files.preserved_file_count)} preserved / ${number(files.changed_file_count)} changed</dd></div><div><dt>Comparison coverage</dt><dd>${number(files.returned_change_count)} / ${number(files.changed_file_count)} changes shown${files.changes_truncated ? ' · truncated' : ''}</dd></div></dl><h4>Metadata differences</h4><div class="comparison-table-wrap"><table class="comparison-table"><thead><tr><th>Field</th><th>PX</th><th>Preserved original</th></tr></thead><tbody>${metadataRows || '<tr><td colspan="3">No compared metadata differs.</td></tr>'}</tbody></table></div><h4>Package file differences</h4><div class="project-map-list">${fileRows || '<p class="compact-empty">No package file differs.</p>'}</div>`); return;
  }
  if (message.type === 'graphResult' && message.requestId === state.graphRequestId) { const request = state.graphRequest || {}; const requestedNode = request.node; clearTimeout(graphRequestTimer); state.graphPending = false; state.graphError = null; state.graphData = request.append ? mergeGraphPage(state.graphData, message.result) : message.result; const next = state.graphLoadAll ? nextGraphPageRequest() : null; if (next) { requestGraph(next); render(); } else { state.graphLoadAll = false; renderPreservingControl('[data-graph-search]'); requestAnimationFrame(prepareGraphInteraction); if (requestedNode) [...app.querySelectorAll('[data-node-key]')].find(item => item.dataset.nodeKey === state.graphData.selected)?.focus(); } }
  if (message.type === 'studioDraftCancelled') { const disposition = studioSaveResponseDisposition(message); if (disposition !== 'active') return; const save = document.querySelector('[data-action="submitStudioDraft"]'); if (save) { save.disabled = false; save.textContent = 'Save immutable candidate'; } resetStudioDetachControls(); const status = document.querySelector('[data-studio-validation]'); status?.insertAdjacentHTML('beforeend', '<span class="studio-warning">Host approval was canceled. The draft remains open and unchanged.</span>'); }
  if (message.type === 'studioDraftResult') {
    const disposition = studioSaveResponseDisposition(message);
    if (!['agent', 'workflow', 'skill'].includes(message.kind) || disposition === 'unmatched') return;
    const catalogKind = `${message.kind}s`; invalidateCatalog(catalogKind, { offset: 0 });
    const outcome = message.outcome === 'recovered' ? 'recover' : 'create';
    state.studioHistory.unshift(studioEditors.historyEntry(message.kind, outcome, message.result)); persistStudioMetadata();
    if (disposition === 'detached') return;
    clearWorkingStudioDraft(message.kind); studioDraftDirty = false;
    // A verified durable result means the host-side create coordinator already
    // consumed every trust proof attached to this save. Clear the local copies
    // before closing so cleanup cannot duplicate-release consumed authority.
    clearConsumedStudioSaveTrust();
    closeModal(); studioLifecycleModal(message.kind, outcome, message.result);
  }
  if (message.type === 'studioSetupResult') { if (!pendingStudioSetup || message.requestId !== pendingStudioSetup.requestId || message.result?.schema_version !== 'px.studio-setup-result/1.0' || message.result.ready !== true) return; pendingStudioSetup = null; invalidateCatalog('agents', { offset: 0 }); invalidateCatalog('workflows', { offset: 0 }); vscode.postMessage({ type: 'refresh' }); showInformationModal('Agent Studio and Workflow Studio are operational', 'ADMITTED · EDITABLE · BOUNDED RUNS SUCCEEDED', message.result, `<p><b>${esc(message.result.agent.identity)} @ ${esc(message.result.agent.version)}</b> is admitted and completed run <span class="mono">${esc(message.result.agent.run_id)}</span>.</p><p><b>${esc(message.result.workflow.identity)} @ ${esc(message.result.workflow.version)}</b> is admitted and completed run <span class="mono">${esc(message.result.workflow.run_id)}</span>.</p><p>Open either catalog record and choose Edit as new revision to change it without overwriting the admitted predecessor.</p>`); return; }
  if (message.type === 'studioDraftOutcomeUnverified') { const disposition = studioSaveResponseDisposition(message); if (!['agent', 'workflow', 'skill'].includes(message.kind) || disposition === 'unmatched') return; const catalogKind = `${message.kind}s`; invalidateCatalog(catalogKind, { offset: 0 }); if (disposition === 'detached') return; resetStudioDetachControls(); const save = document.querySelector('[data-action="submitStudioDraft"]'); if (save) { save.disabled = true; save.textContent = 'Outcome requires catalog refresh'; } const status = document.querySelector('[data-studio-validation]') || document.querySelector('.studio-editor-root'); status?.insertAdjacentHTML('beforeend', '<span class="studio-warning" role="alert">The host could not validate the durable creation receipt. The catalog is refreshing to recover authoritative state; this draft will not be blindly retried.</span>'); return; }
  if (message.type === 'studioVersionConflict') {
    const disposition = studioSaveResponseDisposition(message); if (disposition !== 'active') return;
    resetStudioDetachControls();
    const incomingProof = typeof message.allocationProof === 'string' && /^version-allocation:[a-zA-Z0-9-]{1,160}$/.test(message.allocationProof) ? message.allocationProof : null;
    const currentExpected = studioVersionAllocation && studioEditor?.kind === message.kind && studioVersionAllocation.kind === message.kind ? { kind: message.kind, identity: studioVersionAllocation.identity, source_version: studioVersionAllocation.source_version, source_scope: studioVersionAllocation.source_scope, source_revision_sha256: studioVersionAllocation.source_revision_sha256, source_content_sha256: studioVersionAllocation.source_content_sha256 } : null;
    const allocation = currentExpected ? validStudioAllocation(message.allocation, currentExpected) : null;
    if (!allocation) { if (incomingProof) vscode.postMessage({ type: 'releaseStudioTrust', requestId: message.requestId, trustKind: 'version-allocation', proof: incomingProof }); studioVersionAllocation = null; studioVersionAllocationProof = null; const save = document.querySelector('[data-action="submitStudioDraft"]'); if (save) { save.disabled = true; save.textContent = 'Version check failed'; } const status = document.querySelector('[data-studio-validation]') || document.querySelector('.studio-editor-root'); status?.insertAdjacentHTML('beforeend', '<span class="studio-warning" role="alert">The host returned an invalid or predecessor-unbound version-conflict envelope. The draft remains open and saving stays blocked.</span>'); return; }
    if (typeof message.allocationProof !== 'string' || !/^version-allocation:[a-zA-Z0-9-]{1,160}$/.test(message.allocationProof)) { studioVersionAllocation = null; studioVersionAllocationProof = null; const save = document.querySelector('[data-action="submitStudioDraft"]'); if (save) { save.disabled = true; save.textContent = 'Version proof failed'; } return; }
    studioVersionAllocation = allocation;
    studioVersionAllocationProof = message.allocationProof;
    studioVersionProofRequestId = message.requestId;
    const save = document.querySelector('[data-action="submitStudioDraft"]'); if (save) { save.disabled = true; save.textContent = 'Version changed'; }
    const status = document.querySelector('[data-studio-validation]') || document.querySelector('.studio-editor-root');
    status?.querySelector('[data-studio-version-conflict]')?.remove();
    status?.insertAdjacentHTML('beforeend', `<div class="studio-warning" data-studio-version-conflict role="alert"><span>${esc(message.error || 'The selected version is no longer available.')} The complete draft remains open and unchanged.</span><button data-action="acceptStudioVersionSuggestion">Use ${esc(message.allocation?.candidate_version || 'backend suggestion')}</button></div>`);
    return;
  }
  if (message.type === 'studioOperationResult') {
    if (message.kind === 'skill' && ['validate', 'admit', 'promote', 'rollback'].includes(message.operation)) {
      const pending = pendingSkillLifecycle; const record = message.result?.record && typeof message.result.record === 'object' ? message.result.record : message.result;
      if (!pending || message.requestId !== pending.requestId || message.operation !== pending.operation || String(record?.skill_id || '') !== pending.skill || String(record?.version || '') !== pending.version) return;
      pendingSkillLifecycle = null;
      if (message.operation === 'promote' && studioSession?.kind === 'skill' && record?.promotion_receipt_relative) studioSession.payload.promotion_receipt = record.promotion_receipt_relative;
      state.studioHistory.unshift(studioEditors.historyEntry(message.kind, message.operation, message.result)); invalidateCatalog('skills', { offset: 0 }); persistStudioMetadata(); studioLifecycleModal(message.kind, message.operation, message.result); return;
    }
    if (['preview', 'dry-run'].includes(message.operation)) {
      const pending = pendingStudioPreview;
      if (!pending || message.requestId !== pending.requestId || message.kind !== pending.kind || message.operation !== pending.operation) return;
      const record = message.result?.record && typeof message.result.record === 'object' ? message.result.record : message.result;
      const identityKey = pending.kind === 'agent' ? 'agent_id' : 'workflow_id';
      if (!record || String(record[identityKey] || '') !== pending.subject || String(record.version || '') !== pending.version || record.effects_executed !== false) { pendingStudioPreview = null; showModal('Resolved preview rejected', 'REQUEST, REVISION, OR EFFECT BOUNDARY MISMATCH', '<p>The host result did not bind the exact requested subject and version or did not prove that zero effects executed. No preview was accepted.</p>'); return; }
      pendingStudioPreview = null; state.studioHistory.unshift(studioEditors.historyEntry(message.kind, message.operation, message.result)); persistStudioMetadata(); resolvedStudioPreviewModal(message.kind, message.result); return;
    }
    if (['runs', 'status', 'pause', 'cancel', 'stop', 'reconcile', 'resume'].includes(message.operation)) {
      const pending = pendingStudioRunQuery;
      if (!pending || message.requestId !== pending.requestId || message.kind !== pending.kind || message.operation !== pending.operation) return;
      if (pending.runId && String(message.result?.run_id || '') !== pending.runId) { pendingStudioRunQuery = null; showModal('Runtime state rejected', 'RUN IDENTITY MISMATCH', '<p>The host response did not describe the exact requested durable run. No state was accepted.</p>'); return; }
      pendingStudioRunQuery = null;
    }
    if (message.operation === 'next-version') {
      const request = studioAllocationRequest;
      const allocationProof = typeof message.allocationProof === 'string' && /^version-allocation:[a-zA-Z0-9-]{1,160}$/.test(message.allocationProof) ? message.allocationProof : null;
      if (!request || request.kind !== 'skill' || message.requestId !== request.requestId || message.kind !== request.kind) {
        if (allocationProof && typeof message.requestId === 'string') vscode.postMessage({ type: 'releaseStudioTrust', requestId: message.requestId, trustKind: 'version-allocation', proof: allocationProof });
        return;
      }
      const packageResult = studioPendingSkillPackage; const packageSelection = packageResult?.selection;
      const livePackageMatches = packageResult
        && packageResult.sourceSelectionId === request.source_selection_id
        && packageSelection?.identity === request.identity
        && packageSelection?.source_version === request.source_version
        && packageSelection?.source_scope === request.source_scope
        && packageSelection?.source_revision_sha256 === request.source_revision_sha256
        && packageSelection?.source_content_sha256 === request.source_content_sha256
        && packageSelection?.tree_sha256 === packageResult.treeSha256
        && packageSelection?.file_count === packageResult.fileCount
        && studioRecordIdentity(studioSourceRecord, 'skill') === request.identity
        && studioRecordRevisionSha(studioSourceRecord) === request.selected_revision_sha256
        && studioRecordContentSha(studioSourceRecord) === request.selected_content_sha256;
      const allocation = livePackageMatches ? validStudioAllocation(message.result, request) : null;
      if (!allocation || !allocationProof) { if (allocationProof) vscode.postMessage({ type: 'releaseStudioTrust', requestId: message.requestId, trustKind: 'version-allocation', proof: allocationProof }); if (packageResult?.sourceSelectionId && studioSourceProofRequestId) vscode.postMessage({ type: 'releaseStudioTrust', requestId: studioSourceProofRequestId, trustKind: 'source-selection', proof: packageResult.sourceSelectionId }); studioAllocationRequest = null; studioPendingSkillPackage = null; studioVersionAllocationProof = null; studioSourceProofRequestId = null; showModal('Version allocation rejected', 'STALE OR MALFORMED RESULT', '<p>The backend response did not match the exact request, predecessor, package selection, kind, allocation schema, hashes, or host proof. No editor was opened.</p>'); return; }
      const record = request.record; const details = record.details || record; const kind = request.kind; const identityKey = kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : 'skill_id'; const identity = request.identity;
      studioSourceRecord = record; studioVersionAllocation = allocation; studioVersionAllocationProof = allocationProof; studioVersionProofRequestId = request.requestId; studioSourceProofRequestId = null; studioAllocationRequest = null;
      const seed = { ...details, [identityKey]: identity, version: allocation.candidate_version };
      if (packageResult) Object.assign(seed, { editor_files: packageResult.editor_files, package_missing_required_files: packageResult.missingRequiredFiles || [], provenance: { source: packageResult.packagePath, tree_sha256: packageResult.treeSha256 } });
      studioPendingSkillPackage = null; openReauthenticatedStudioDraft(kind, seed, allocation); return;
    } else if (message.kind === 'knowledge') {
      state.knowledgePending = false;
      if (message.operation === 'browse') { state.knowledgeData = message.result; render(); }
      else { state.studioHistory.unshift(studioEditors.historyEntry(message.kind, message.operation, message.result)); persistStudioMetadata(); state.knowledgeData = null; requestKnowledge(); showInformationModal('Knowledge lifecycle receipt', `${message.operation.toUpperCase()} · GOVERNED RESULT`, message.result, `<p>The controller retained source, evidence, approval, and canonical-head boundaries.</p>${humanRecord(message.result)}`); }
    } else if (message.operation === 'runs') {
      if (message.kind === 'workflow') applyWorkflowTraceResult(message.result, message.operation);
      studioRunsModal(message.kind, message.result);
    } else if (['status', 'pause', 'cancel', 'stop', 'reconcile'].includes(message.operation)) {
      if (message.kind === 'workflow' && message.operation === 'status') applyWorkflowTraceResult(message.result, message.operation);
      state.studioHistory.unshift(studioEditors.historyEntry(message.kind, message.operation, message.result)); persistStudioMetadata();
      if (message.operation === 'reconcile') studioRunsModal(message.kind, { schema_version: 'px.studio-run-reconcile-view/1.0', runs: [], reconciliation: message.result });
      else studioRunsModal(message.kind, message.result);
    } else {
      if (message.kind === 'workflow' && message.operation === 'approve' && studioSession?.kind === 'workflow' && message.nodeId && message.result?.approval_id) studioSession.payload.approvals = { ...(studioSession.payload.approvals || {}), [message.nodeId]: message.result.approval_id };
      if (message.kind === 'skill' && message.operation === 'promote' && studioSession?.kind === 'skill' && message.result?.promotion_receipt_relative) studioSession.payload.promotion_receipt = message.result.promotion_receipt_relative;
      if (message.kind === 'workflow' && ['run', 'start', 'resume'].includes(message.operation)) applyWorkflowTraceResult(message.result, message.operation);
      state.studioHistory.unshift(studioEditors.historyEntry(message.kind, message.operation, message.result)); const catalogKind = `${message.kind}s`; invalidateCatalog(catalogKind, { offset: 0 }); persistStudioMetadata(); studioLifecycleModal(message.kind, message.operation, message.result);
    }
  }
  if (message.type === 'studioRevisionEditorResult') {
    const request = studioAllocationRequest;
    const selection = message.selection;
    if (!request || !['agent', 'workflow'].includes(request.kind) || message.requestId !== request.requestId || message.kind !== request.kind || message.catalogKind !== request.catalogKind || message.recordId !== request.recordId) {
      if (typeof message.requestId === 'string' && typeof message.allocationProof === 'string' && /^version-allocation:[a-zA-Z0-9-]{1,160}$/.test(message.allocationProof)) vscode.postMessage({ type: 'releaseStudioTrust', requestId: message.requestId, trustKind: 'version-allocation', proof: message.allocationProof });
      return;
    }
    const expected = {
      kind: request.kind,
      identity: request.identity,
      source_version: request.source_version,
      source_scope: request.source_scope,
      source_revision_sha256: request.source_revision_sha256,
      source_content_sha256: request.source_content_sha256
    };
    const allocation = validStudioAllocation(message.allocation, expected);
    const allocationProof = typeof message.allocationProof === 'string' && /^version-allocation:[a-zA-Z0-9-]{1,160}$/.test(message.allocationProof) ? message.allocationProof : null;
    const record = selection?.record;
    const identityKey = request.kind === 'agent' ? 'agent_id' : 'workflow_id';
    const selectionMatches = selection?.kind === request.kind && selection?.catalog_kind === request.catalogKind && selection?.record_id === request.recordId && selection?.identity === request.identity && selection?.source_version === request.source_version && selection?.source_revision_sha256 === request.source_revision_sha256 && selection?.source_content_sha256 === request.source_content_sha256;
    const recordMatches = record && typeof record === 'object' && !Array.isArray(record) && record[identityKey] === request.identity && record.version === request.source_version && studioRecordRevisionSha(record) === request.source_revision_sha256 && studioRecordContentSha(record) === request.source_content_sha256;
    if (!allocation || !allocationProof || !selectionMatches || !recordMatches) {
      if (allocationProof) vscode.postMessage({ type: 'releaseStudioTrust', requestId: message.requestId, trustKind: 'version-allocation', proof: allocationProof });
      showModal('Revision response rejected', 'AWAITING EXACT HOST SNAPSHOT', '<p>The host response did not match the identity, version, revision hash, content hash, catalog record, or proof captured by the active request. The original request remains pending and no editor state was replaced.</p>'); return;
    }
    studioSourceRecord = { ...record, _catalogKind: request.catalogKind, _catalogRecordId: request.recordId };
    studioVersionAllocation = allocation; studioVersionAllocationProof = allocationProof; studioVersionProofRequestId = request.requestId; studioAllocationRequest = null;
    const seed = { ...record, [identityKey]: selection.identity, version: allocation.candidate_version };
    openReauthenticatedStudioDraft(request.kind, seed, allocation); return;
  }
  if (message.type === 'skillPackageEditorResult') {
    const request = studioPackageRequest;
    const currentRecordMatches = request && studioRecordIdentity(studioSourceRecord, 'skill') === request.identity && studioRecordRevisionSha(studioSourceRecord) === request.revisionSha256;
    const resultMatches = message.selection?.record_id === request?.recordId && message.selection?.catalog_kind === request?.catalogKind && message.selection?.tree_sha256 === message.result?.treeSha256 && message.selection?.file_count === message.result?.fileCount;
    if (!request || message.requestId !== request.requestId || message.catalogKind !== request.catalogKind || message.recordId !== request.recordId || !currentRecordMatches || !resultMatches || typeof message.sourceSelectionId !== 'string') {
      if (typeof message.requestId === 'string' && typeof message.sourceSelectionId === 'string' && /^source-selection:[a-zA-Z0-9-]{1,160}$/.test(message.sourceSelectionId)) vscode.postMessage({ type: 'releaseStudioTrust', requestId: message.requestId, trustKind: 'source-selection', proof: message.sourceSelectionId });
      return;
    }
    studioPackageRequest = null;
    const record = request.record;
    studioPendingSkillPackage = { ...message.result, sourceSelectionId: message.sourceSelectionId, selection: structuredClone(message.selection) };
    studioSourceProofRequestId = request.requestId;
    studioVersionAllocation = null;
    studioVersionAllocationProof = null;
    requestStudioVersionAllocation('skill', record, studioPendingSkillPackage);
  }
  if (message.type === 'coordination') { state.coordination = message.coordination; state.activityData = message.coordination?.activity || state.activityData; render(); }
  if (message.type === 'coordinationResult') { if (message.operation === 'releaseCoordinationTask') { if (!pendingTaskRelease || message.requestId !== pendingTaskRelease.requestId || message.authorization?.taskId !== pendingTaskRelease.taskId) return; state.operation = { status: 'complete', action: 'releaseTask', requestId: message.requestId, authorization: message.authorization, result: message.result }; pendingTaskRelease = null; showInformationModal('Task claim released', 'REQUEST-BOUND RELEASE RECEIPT', { authorization: message.authorization, receipt: message.result }, '<p>The exact task claim was released after a reason and explicit confirmation were supplied. Existing coordination evidence was preserved.</p>'); } else state.operation = { status: 'complete', result: message.result }; state.memoryData = null; state.activityData = null; if (state.active === 'memory') requestMemory(); if (state.active === 'activity') requestActivity(); }
  if (message.type === 'memoryResult' && message.requestId === state.memoryRequestId) { state.memoryPending = false; state.memoryData = message.result; renderPreservingControl('[data-memory-search]'); }
  if (message.type === 'graphBuildResult') { state.graphData = null; requestGraph({ view: 'repository', node: '', query: '' }); render(); }
  if (message.type === 'activityResult' && (!message.requestId || message.requestId === state.activityRequestId)) { state.activityPending = false; state.activityData = message.result; renderPreservingControl('[data-activity-search]'); }
  if (message.type === 'activityReconciliationResult') { const pending = pendingHostActions.get(message.requestId); if (!pending || pending.type !== 'reconcileStaleActivity') return; pendingHostActions.delete(message.requestId); state.operation = { status: 'completed', action: pending.action, requestId: message.requestId, detail: message.authorization || {} }; state.activityData = null; requestActivity(); showInformationModal('Stale activity reconciled', 'APPEND-ONLY TERMINAL EVIDENCE', { authorization: message.authorization, receipt: message.result }, `<p>${number(message.result.reconciled_count || 0)} stale operation${message.result.reconciled_count === 1 ? '' : 's'} received sealed terminal events. Prior activity evidence was preserved.</p><p>The write followed an explicit host-modal acknowledgement bound to this request. Cancellation would have left the ledger unchanged.</p>`); }
  if (message.type === 'cleanupCandidates') { cleanupState.inventory = message.inventory; cleanupState.selected = new Set([...cleanupState.selected].filter(id => message.inventory.candidates.some(item => item.id === id))); renderCleanupManager(); }
  if (message.type === 'cleanupResult') { cleanupState.lastResult = message.result; cleanupState.selected = new Set(); renderCleanupManager(); }
  if (message.type === 'teamPackResult') {
    const result = message.result; modalCopyText = JSON.stringify(result, null, 2);
    const summary = message.phase === 'preview' ? `${number(result.totals?.entities)} entities · ${number(result.totals?.collisions)} collisions · ${number(result.totals?.warnings)} warnings` : `${number(result.receipt?.staged_count)} non-canonical candidates staged`;
    showInformationModal(message.phase === 'preview' ? 'Team package dry run' : 'Team package staged', 'TEAM FABRIC ADMISSION', result, `<p>${esc(summary)}</p><p class="modal-note">Canonical registries are unchanged. Promotion still requires Pacify-X admission.</p>`);
  }
  if (message.type === 'enterpriseResult') {
    const doctor = message.operation === 'enterpriseDoctor';
    const report = message.result.report; const doctorReady = report?.valid === true;
    showInformationModal(doctor ? 'MS+Enterprise readiness' : 'MS+Enterprise state updated', 'SEPARATE OFFLINE CONTROL PLANE', report || message.result.event || message.result, `<p>${doctor ? (doctorReady ? 'Local enterprise governance checks passed. Cloud connectors remain disabled and no connection was attempted.' : 'One or more local enterprise governance checks failed. Cloud connectors remain disabled and no connection was attempted.') : 'The separate enterprise project state was updated. Network, mutation, credential reads, and billable services remain denied.'}</p>`);
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
  if (message.type === 'extensionLifecyclePreview') {
    const request = pendingExtensionLifecycle; const preview = message.result;
    if (!request || message.requestId !== request.requestId || request.extensionId !== preview?.extension_id) return;
    if (!preview?.allowed) { pendingExtensionLifecycle = null; showInformationModal('Extension install blocked', 'FAIL-CLOSED HOST LIFECYCLE', preview || {}, `<p>${esc(preview?.reason || 'Install is not currently eligible.')}</p><p>${esc(preview?.handoff || 'No install command was dispatched.')}</p>`); return; }
    pendingExtensionLifecycle = { ...request, token: preview.token, exactTarget: preview.exact_target };
    showModal('Confirm extension installation', 'NETWORK + INSTALL EFFECT · VS CODE HOST AUTHORITY', `<p>VS Code will resolve publisher trust, signature/security policy, Marketplace access, and the native installation.</p><dl class="modal-detail"><div><dt>Exact target</dt><dd class="mono">${esc(preview.exact_target)}</dd></div><div><dt>Prior version</dt><dd>Not installed</dd></div><div><dt>Authority</dt><dd>${esc(preview.authority)}</dd></div></dl>`, `<button data-action="closeModal">Cancel</button><button class="danger" data-action="executeExtensionInstall" data-token="${esc(preview.token)}" data-exact-target="${esc(preview.exact_target)}">Authorize native install</button>`); return;
  }
  if (message.type === 'extensionLifecycleResult') {
    const request = pendingExtensionLifecycle; if (!request || message.requestId !== request.requestId) return; pendingExtensionLifecycle = null;
    const cancelled = message.result?.status === 'cancelled';
    showInformationModal('Extension install result', cancelled ? 'NATIVE INSTALL CANCELLED' : message.result?.reconciled ? 'HOST RESULT RECONCILED' : 'HOST REFRESH OR RELOAD REQUIRED', message.result || {}, `<p>${cancelled ? 'No extension install command was dispatched.' : message.result?.reconciled ? `VS Code reports ${esc(message.result.extension_id)} at version ${esc(message.result.after_version)}.` : 'The host accepted the operation but the installed extension is not yet observable in this extension-host generation. Refresh or restart extensions before treating it as installed.'}</p>`); return;
  }
  if (message.type === 'extensionUpdatePreview') {
    const request = pendingExtensionLifecycle; const preview = message.result;
    if (!request || request.action !== 'update' || message.requestId !== request.requestId || request.extensionId !== preview?.extension_id) return;
    if (!preview?.allowed) { pendingExtensionLifecycle = null; showInformationModal('Extension update blocked', 'FAIL-CLOSED HOST LIFECYCLE', preview || {}, `<p>${esc(preview?.reason || 'Update is not currently eligible.')}</p><p>${esc(preview?.handoff || 'No update command was dispatched.')}</p>`); return; }
    pendingExtensionLifecycle = { ...request, token: preview.token, exactTarget: preview.exact_target };
    showModal('Confirm extension update', 'NETWORK + UPDATE EFFECT · VS CODE HOST AUTHORITY', `<p>${esc(preview.compatibility_gate)}</p><dl class="modal-detail"><div><dt>Current version</dt><dd class="mono">${esc(preview.before_version)}</dd></div><div><dt>Exact host target</dt><dd class="mono">${esc(preview.exact_target)}</dd></div><div><dt>Rollback identity</dt><dd class="mono">${esc(preview.rollback_target)}</dd></div><div><dt>Authority</dt><dd>${esc(preview.authority)}</dd></div></dl>`, `<button data-action="closeModal">Cancel</button><button class="danger" data-action="executeExtensionUpdate" data-token="${esc(preview.token)}" data-exact-target="${esc(preview.exact_target)}">Authorize native update</button>`); return;
  }
  if (message.type === 'extensionUpdateResult') {
    const request = pendingExtensionLifecycle; if (!request || request.action !== 'update' || message.requestId !== request.requestId) return; pendingExtensionLifecycle = null;
    const cancelled = message.result?.status === 'cancelled';
    showInformationModal('Extension update result', cancelled ? 'NATIVE UPDATE CANCELLED' : message.result?.reconciled ? 'HOST RESULT RECONCILED' : 'HOST REFRESH OR RELOAD REQUIRED', message.result || {}, `<p>${cancelled ? 'No extension update command was dispatched.' : message.result?.reconciled ? `VS Code reports ${esc(message.result.extension_id)} at version ${esc(message.result.after_version)}. Rollback identity: ${esc(message.result.rollback_target)}.` : 'The host accepted the update but the target version is not yet observable. Refresh or restart extensions before treating it as updated.'}</p>`); return;
  }
  if (message.type === 'extensionEnablementPreview') {
    const request = pendingExtensionLifecycle; const preview = message.result;
    if (!request || request.action !== 'enablement-handoff' || message.requestId !== request.requestId || request.extensionId !== preview?.extension_id) return;
    if (!preview?.allowed) { pendingExtensionLifecycle = null; showInformationModal('Enablement handoff blocked', 'FAIL-CLOSED HOST BOUNDARY', preview || {}, `<p>${esc(preview?.reason || 'The native record cannot be focused.')}</p>`); return; }
    pendingExtensionLifecycle = { ...request, token: preview.token, exactTarget: preview.exact_target };
    showModal('Confirm native enablement handoff', 'EXACT ID + SCOPE · NO IMPLIED MUTATION', `<p>${esc(preview.limitation)}</p><dl class="modal-detail"><div><dt>Extension</dt><dd class="mono">${esc(preview.extension_id)}@${esc(preview.before_version)}</dd></div><div><dt>Requested action</dt><dd>${esc(preview.desired_action)} · ${esc(preview.scope)}</dd></div><div><dt>Activation observed</dt><dd>${preview.activation_observed ? 'active in this host generation' : 'not active in this host generation'}</dd></div></dl>`, `<button data-action="closeModal">Cancel</button><button class="primary" data-action="executeExtensionEnablement" data-token="${esc(preview.token)}" data-exact-target="${esc(preview.exact_target)}">Open exact native record</button>`); return;
  }
  if (message.type === 'extensionEnablementResult') {
    const request = pendingExtensionLifecycle; if (!request || request.action !== 'enablement-handoff' || message.requestId !== request.requestId) return;
    if (message.result?.status === 'cancelled') pendingExtensionLifecycle = null;
    showInformationModal('Extension enablement handoff', message.result?.status === 'cancelled' ? 'NATIVE HANDOFF CANCELLED' : 'AWAITING NATIVE MANAGER ACTION', message.result || {}, `<p>${esc(message.result?.status === 'cancelled' ? 'The native extension record was not opened.' : message.result?.return_condition || 'Complete the action in the native manager.')}</p>`); return;
  }
  if (message.type === 'extensionEnablementObserved') {
    const request = pendingExtensionLifecycle; if (!request || request.action !== 'enablement-handoff' || message.requestId !== request.requestId) return; pendingExtensionLifecycle = null;
    showInformationModal('Extension host change observed', 'PERSISTED REFRESH · ENABLEMENT NOT INFERRED', message.result || {}, '<p>An extension-host change was observed after the exact native handoff and the inventory was refreshed. This is temporal correlation, not proof that activation equals enablement; inspect the native record for final scope state.</p>'); return;
  }
  if (message.type === 'extensionUninstallPreview') {
    const request = pendingExtensionLifecycle; const preview = message.result;
    if (!request || request.action !== 'uninstall' || message.requestId !== request.requestId || request.extensionId !== preview?.extension_id) return;
    if (!preview?.allowed) { pendingExtensionLifecycle = null; showInformationModal('Extension uninstall blocked', 'FAIL-CLOSED HOST LIFECYCLE', preview || {}, `<p>${esc(preview?.reason || 'Uninstall is not currently eligible.')}</p><p>${esc(preview?.handoff || 'No uninstall command was dispatched.')}</p>`); return; }
    pendingExtensionLifecycle = { ...request, token: preview.token, exactTarget: preview.exact_target, consumerAckRequired: Boolean(preview.consumer_ack_required) };
    const consumers = (preview.consumers || []).map(item => `${item.extension_id} (${item.relationship})`);
    showModal('Confirm extension uninstall', 'UNINSTALL EFFECT · DURABLE ROLLBACK IDENTITY · VS CODE AUTHORITY', `<p>${esc(preview.rollback_limit)}</p><dl class="modal-detail"><div><dt>Installed target</dt><dd class="mono">${esc(preview.extension_id)}@${esc(preview.before_version)}</dd></div><div><dt>Rollback identity</dt><dd class="mono">${esc(preview.rollback_identity?.exact_target)}</dd></div><div><dt>Reverse consumers</dt><dd>${esc(consumers.join(', ') || 'None detected in installed manifests')}</dd></div></dl>${preview.consumer_ack_required ? '<label class="policy-switch"><input id="extension-uninstall-consumers" type="checkbox"><span>I reviewed and accept the listed reverse-consumer impact</span></label>' : ''}`, `<button data-action="closeModal">Cancel</button><button class="danger" data-action="executeExtensionUninstall" data-token="${esc(preview.token)}" data-exact-target="${esc(preview.exact_target)}">Authorize native uninstall</button>`); return;
  }
  if (message.type === 'extensionUninstallResult') {
    const request = pendingExtensionLifecycle; if (!request || request.action !== 'uninstall' || message.requestId !== request.requestId) return; pendingExtensionLifecycle = null;
    const cancelled = message.result?.status === 'cancelled';
    showInformationModal('Extension uninstall result', cancelled ? 'NATIVE UNINSTALL CANCELLED' : message.result?.reconciled ? 'HOST ABSENCE RECONCILED' : 'HOST REFRESH OR RELOAD REQUIRED', message.result || {}, `<p>${cancelled ? 'No extension uninstall command was dispatched.' : message.result?.reconciled ? `VS Code no longer reports ${esc(message.result.extension_id)}. Rollback identity ${esc(message.result.rollback_identity?.exact_target)} was retained before dispatch.` : 'The host accepted uninstall but the extension is still observable in this host generation. Refresh or reload before treating it as absent.'}</p>`); return;
  }
  if (message.type === 'extensionRollbackPreview') {
    const request = pendingExtensionLifecycle; const preview = message.result;
    if (!request || request.action !== 'rollback' || message.requestId !== request.requestId || request.extensionId !== preview?.extension_id) return;
    if (!preview?.allowed) { pendingExtensionLifecycle = null; showInformationModal('Extension rollback blocked', 'FAIL-CLOSED RETAINED IDENTITY GATE', preview || {}, `<p>${esc(preview?.reason || 'Rollback is not currently eligible.')}</p><p>${esc(preview?.handoff || 'No reinstall command was dispatched.')}</p>`); return; }
    pendingExtensionLifecycle = { ...request, token: preview.token, exactTarget: preview.exact_target };
    showModal('Confirm exact extension rollback', 'NETWORK + INSTALL EFFECT · RETAINED IDENTITY · VS CODE AUTHORITY', `<p>${esc(preview.source_gate)}</p><dl class="modal-detail"><div><dt>Exact reinstall target</dt><dd class="mono">${esc(preview.exact_target)}</dd></div><div><dt>Retained operation</dt><dd class="mono">${esc(preview.retained_operation_id)}</dd></div><div><dt>Custody</dt><dd>${esc(preview.custody_state)}</dd></div><div><dt>Source availability</dt><dd>${esc(preview.source_availability)}</dd></div></dl>`, `<button data-action="closeModal">Cancel</button><button class="danger" data-action="executeExtensionRollback" data-token="${esc(preview.token)}" data-exact-target="${esc(preview.exact_target)}">Authorize exact rollback</button>`); return;
  }
  if (message.type === 'extensionRollbackResult') {
    const request = pendingExtensionLifecycle; if (!request || request.action !== 'rollback' || message.requestId !== request.requestId) return; pendingExtensionLifecycle = null;
    const cancelled = message.result?.status === 'cancelled';
    showInformationModal('Extension rollback result', cancelled ? 'NATIVE ROLLBACK CANCELLED' : message.result?.reconciled ? 'EXACT VERSION RESTORED' : 'HOST REFRESH OR RELOAD REQUIRED', message.result || {}, `<p>${cancelled ? 'No exact-version reinstall command was dispatched.' : message.result?.reconciled ? `VS Code reports ${esc(message.result.extension_id)} at ${esc(message.result.after_version)} and the retained identity is now consumed.` : 'The host accepted exact reinstall but the expected version is not yet observable. Custody remains retained until verification succeeds.'}</p>`); return;
  }
  if (message.type === 'extensionConflictResult') {
    const request = pendingExtensionLifecycle; const result = message.result;
    if (!request || request.action !== 'conflict-query' || message.requestId !== request.requestId || request.extensionId !== result?.extension_id) return;
    if (!result.available) { pendingExtensionLifecycle = null; showInformationModal('Conflict analysis unavailable', 'EXACT INSTALLED ID REQUIRED', result || {}, `<p>${esc(result?.reason || 'The extension is not currently installed.')}</p>`); return; }
    const cards = (result.signals || []).slice(0, 40).map(signal => {
      const routes = (signal.resolution_targets || []).flatMap(target => (signal.recommended_resolutions || []).map(resolution => `<button data-action="previewExtensionConflictResolution" data-extension-id="${esc(result.extension_id)}" data-signal-id="${esc(signal.signal_id)}" data-target-extension-id="${esc(target)}" data-resolution="${esc(resolution)}">${esc(resolution)} · ${esc(target)}</button>`)).join('');
      return `<article class="plugin-connector"><div><strong>${esc(signal.kind)}</strong><small>${esc(signal.signal_id)} · ${esc(signal.severity)}</small></div><span>${esc(signal.resource)}</span><span>${esc((signal.extension_ids || []).join(', '))}</span><div class="action-grid">${routes}</div></article>`;
    }).join('');
    showModal('Extension conflict analysis', `${number(result.signal_count)} LIVE SIGNALS · EXACT ROUTES`, cards || '<p>No current typed conflict or consumer-impact signal was found for this exact extension.</p>', '<button data-action="closeModal">Close</button>'); return;
  }
  if (message.type === 'extensionConflictResolutionPreview') {
    const request = pendingExtensionLifecycle; const preview = message.result;
    if (!request || request.action !== 'conflict-resolution' || message.requestId !== request.requestId || request.signalId !== preview?.signal_id || request.targetExtensionId !== preview?.target_extension_id) return;
    pendingExtensionLifecycle = { ...request, token: preview.token, exactTarget: preview.exact_target };
    showModal('Confirm conflict resolution route', 'CURRENT SIGNAL · EXACT TARGET · SEPARATE MUTATION GATE', `<dl class="modal-detail"><div><dt>Signal</dt><dd class="mono">${esc(preview.signal_id)}</dd></div><div><dt>Kind/resource</dt><dd>${esc(preview.signal?.kind)} · ${esc(preview.signal?.resource)}</dd></div><div><dt>Target</dt><dd class="mono">${esc(preview.target_extension_id)}</dd></div><div><dt>Resolution route</dt><dd>${esc(preview.resolution)} · ${esc(preview.effect)}</dd></div></dl><p>${esc(preview.authority)}</p>`, `<button data-action="closeModal">Cancel</button><button class="primary" data-action="executeExtensionConflictResolution" data-token="${esc(preview.token)}" data-exact-target="${esc(preview.exact_target)}">Authorize exact route</button>`); return;
  }
  if (message.type === 'extensionConflictResolutionResult') {
    const request = pendingExtensionLifecycle; const result = message.result;
    if (!request || request.action !== 'conflict-resolution' || message.requestId !== request.requestId) return;
    if (result?.status === 'routed-to-governed-install') {
      const requestId = studioAllocationRequestId(); pendingExtensionLifecycle = { requestId, action: 'install', extensionId: result.target_extension_id }; vscode.postMessage({ type: 'extensionLifecyclePreview', requestId, extensionId: result.target_extension_id, version: '' }); return;
    }
    if (result?.status === 'routed-to-governed-uninstall') {
      const requestId = studioAllocationRequestId(); pendingExtensionLifecycle = { requestId, action: 'uninstall', extensionId: result.target_extension_id }; vscode.postMessage({ type: 'extensionUninstallPreview', requestId, extensionId: result.target_extension_id }); return;
    }
    if (result?.status === 'routed-to-governed-enablement') {
      const desiredAction = 'disable'; const scope = result.resolution === 'disable-global' ? 'global' : 'workspace'; const requestId = studioAllocationRequestId(); pendingExtensionLifecycle = { requestId, action: 'enablement-handoff', extensionId: result.target_extension_id, desiredAction, scope }; vscode.postMessage({ type: 'extensionEnablementPreview', requestId, extensionId: result.target_extension_id, desiredAction, scope }); return;
    }
    pendingExtensionLifecycle = null;
    showInformationModal('Conflict resolution result', result?.status === 'cancelled' ? 'ROUTE CANCELLED' : 'EXACT NATIVE RECORD OPENED', result || {}, `<p>${esc(result?.status === 'cancelled' ? 'No conflict route was executed.' : 'The exact target record was opened. No mutation or resolution is claimed until a governed lifecycle operation completes and fresh analysis removes the signal.')}</p>`); return;
  }
  if (message.type === 'environmentLifecyclePreview') {
    const preview = message.result;
    if (!preview?.allowed) { showInformationModal('Environment action blocked', 'FAIL-CLOSED LIFECYCLE GATE', preview || {}, `<p>${esc(preview?.reason || 'The resource cannot be managed by Pacify-X.')}</p><p>${esc(preview?.handoff || 'No mutation occurred.')}</p>`); return; }
    const consumers = preview.consumers || [];
    showModal('Confirm reversible environment disposition', 'EXACT TARGET · TWO SNAPSHOTS · IMMEDIATE REVALIDATION', `<p>The resource will be moved into project-owned quarantine. Nothing is permanently deleted.</p><dl class="modal-detail"><div><dt>Target</dt><dd class="mono">${esc(preview.target)}</dd></div><div><dt>Entries</dt><dd>${number(preview.entry_count)}</dd></div><div><dt>Consumers</dt><dd>${esc(consumers.join(', ') || 'None detected')}</dd></div><div><dt>Snapshot</dt><dd class="mono">${esc(preview.snapshot_sha256)}</dd></div></dl><label>Type or preserve the exact target<input id="environment-lifecycle-target" value="${esc(preview.target)}" autocomplete="off"></label>${preview.consumer_ack_required ? '<label class="policy-switch"><input id="environment-lifecycle-consumers" type="checkbox"><span>I reviewed and accept the listed consumer impact</span></label>' : ''}`, `<button data-action="closeModal">Cancel</button><button class="danger" data-action="executeEnvironmentLifecycle" data-token="${esc(preview.token)}">Move to quarantine</button>`); return;
  }
  if (message.type === 'environmentLifecycleResult') { showInformationModal('Environment resource quarantined', 'REVERSIBLE DISPOSITION RECEIPT', message.result, '<p>The exact target was moved into project-owned quarantine after immediate snapshot revalidation. The receipt contains no environment values.</p>'); return; }
  if (message.type === 'hostActionResult') {
    const pending = pendingHostActions.get(message.requestId);
    if (!pending || pending.type !== message.operation) return;
    pendingHostActions.delete(message.requestId);
    state.operation = { status: message.disposition, action: pending.action, requestId: message.requestId, detail: message.detail || {}, observedAt: message.observedAt };
    render(); return;
  }
  if (message.type === 'cleanupError' || message.type === 'operationError') {
    const requestId = message.requestId;
    if (message.operation === 'releaseCoordinationTask') {
      if (!pendingTaskRelease || requestId !== pendingTaskRelease.requestId) return;
      pendingTaskRelease = null;
    }
    const pendingHostAction = requestId ? pendingHostActions.get(requestId) : null;
    if (pendingHostAction) {
      if (pendingHostAction.type !== message.operation) return;
      pendingHostActions.delete(requestId);
      state.operation = { status: 'failed', action: pendingHostAction.action, requestId, error: String(message.error || 'Host operation failed closed.') };
    }
    if (message.operation === 'setupStudio') { if (!pendingStudioSetup || requestId !== pendingStudioSetup.requestId) return; pendingStudioSetup = null; showModal('Studio setup blocked', 'NO PARTIAL SUCCESS CLAIMED', `<p role="alert">${esc(message.error || 'The Studio setup operation failed closed.')}</p><p>Any immutable step that completed remains visible in the catalogs; refresh and retry will reuse matching revisions rather than overwrite them.</p>`); return; }
    if (message.operation === 'loadSkillPackageEditor') {
      const request = studioPackageRequest;
      if (!request || requestId !== request.requestId || message.catalogKind !== request.catalogKind || message.recordId !== request.recordId) return;
      studioPackageRequest = null; studioPendingSkillPackage = null;
      showModal('Skill package load blocked', 'REQUEST-BOUND FAILURE', `<p role="alert">${esc(message.error || 'The selected package could not be read.')}</p>`); return;
    }
    if (message.operation === 'loadStudioRevisionEditor') {
      const request = studioAllocationRequest;
      if (!request || request.operation !== 'loadStudioRevisionEditor' || request.suboperation !== null || !['agent', 'workflow'].includes(request.kind) || requestId !== request.requestId || message.kind !== request.kind || !request.catalogKind || !request.recordId || message.catalogKind !== request.catalogKind || message.recordId !== request.recordId) return;
      studioAllocationRequest = null; studioVersionAllocation = null; studioVersionAllocationProof = null; studioVersionProofRequestId = null;
      showModal('Revision load blocked', 'REQUEST-BOUND FAILURE', `<p role="alert">${esc(message.error || 'The selected immutable revision could not be authenticated and loaded.')}</p>`); return;
    }
    if (message.operation === 'studioOperation' && message.kind === 'skill' && ['validate', 'admit', 'promote', 'rollback'].includes(message.suboperation)) {
      const request = pendingSkillLifecycle;
      if (!request || requestId !== request.requestId || message.suboperation !== request.operation) return;
      pendingSkillLifecycle = null;
      showModal('Skill lifecycle operation blocked', 'REQUEST-BOUND FAILURE · NO RESULT ACCEPTED', `<p role="alert">${esc(message.error || 'The skill lifecycle operation failed closed.')}</p>`); return;
    }
    if (message.operation === 'skillCompare') {
      const request = pendingSkillComparison;
      if (!request || requestId !== request.requestId || message.skill !== request.skill) return;
      pendingSkillComparison = null;
      showModal('Skill comparison blocked', 'REQUEST-BOUND FAILURE · NO CHANGES MADE', `<p role="alert">${esc(message.error || 'The PX and preserved-original packages could not be compared.')}</p>`); return;
    }
    // Trust release is cleanup-only. Expiry and panel-origin disposal remain the
    // authoritative fallback, so a late release failure must not reopen a modal.
    if (message.operation === 'releaseStudioTrust') return;
    if (message.operation === 'studioOperation' && ['preview', 'dry-run'].includes(message.suboperation)) {
      if (!pendingStudioPreview || requestId !== pendingStudioPreview.requestId) return;
      pendingStudioPreview = null;
    }
    if (message.operation === 'studioOperation' && ['runs', 'status', 'pause', 'cancel', 'stop', 'reconcile', 'resume'].includes(message.suboperation)) {
      if (!pendingStudioRunQuery || requestId !== pendingStudioRunQuery.requestId) return;
      pendingStudioRunQuery = null;
    }
    if (message.operation === 'studioOperation' && message.suboperation === 'next-version') {
      const request = studioAllocationRequest;
      if (!request || request.operation !== 'studioOperation' || request.suboperation !== 'next-version' || requestId !== request.requestId || message.kind !== request.kind) return;
      studioAllocationRequest = null; studioPendingSkillPackage = null; studioSourceProofRequestId = null;
      showModal('Version allocation blocked', 'REQUEST-BOUND FAILURE', `<p role="alert">${esc(message.error || 'The immutable revision allocation failed.')}</p>`); return;
    }
    const stale = Boolean(requestId && (
      (message.operation === 'graphQuery' && requestId !== state.graphRequestId) ||
      (message.operation === 'memoryQuery' && requestId !== state.memoryRequestId) ||
      (message.operation === 'activityQuery' && requestId !== state.activityRequestId) ||
      (message.operation === 'catalogQuery' && requestId !== state.catalogRequests[message.kind]?.requestId)
    ));
    if (stale) return;
    if (message.operation === 'createStudioDraft') { const disposition = studioSaveResponseDisposition(message); if (disposition !== 'active') return; const save = document.querySelector('[data-action="submitStudioDraft"]'); if (save) { save.disabled = false; save.textContent = 'Save immutable candidate'; } resetStudioDetachControls(); const status = document.querySelector('[data-studio-validation]'); status?.insertAdjacentHTML('beforeend', `<span class="studio-warning">Host operation failed closed: ${esc(message.error || 'Unknown error')}</span>`); return; }
    if (message.operation === 'graphQuery') { clearTimeout(graphRequestTimer); state.graphPending = false; state.graphError = `Live graph query failed closed: ${message.error}`; }
    if (message.operation === 'memoryQuery') { state.memoryPending = false; state.memoryData = { records: [], matched_count: 0, error: String(message.error || 'Canonical memory query failed.') }; }
    if (message.operation === 'activityQuery') { state.activityPending = false; state.activityData = { events: [], active_operations: [], stale_operations: [], live_agents: [], error: String(message.error || 'Activity query failed.') }; }
    if (message.operation === 'studioOperation' && message.kind === 'knowledge') { state.knowledgePending = false; state.knowledgeData = { proposals: [], canonical: [], error: String(message.error || 'Knowledge controller query failed.') }; }
    if (message.operation === 'environmentQuery') {
      if (message.subject) { state.environmentPending[message.subject] = false; state.environmentData[message.subject] = { records: [], error: String(message.error || 'Environment query failed.') }; }
      else for (const subject of Object.keys(state.environmentPending)) state.environmentPending[subject] = false;
    }
    if (message.operation === 'catalogQuery' && message.kind) {
      state.catalogs[message.kind] = { kind: message.kind, items: [], total: 0, filtered: 0, offset: 0, limit: 50, has_more: false, error: String(message.error || 'Catalog query failed.') };
    }
    render(); showModal('Operation blocked', 'FAIL-CLOSED RESULT', `<p role="alert">${esc(message.error)}</p>`, '<button class="primary" data-action="closeModal">Close</button>');
  }
});

window.addEventListener('resize', () => {
  clearTimeout(graphResizeTimer); graphResizeTimer = setTimeout(() => { if (graphCanvas()) frameReadableGraphViewport('Map reframed after resize'); }, 120);
});

render();
vscode.postMessage({ type: 'ready' });
