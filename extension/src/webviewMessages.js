'use strict';

const MAX_MESSAGE_BYTES = 4 * 1024 * 1024;
const MAX_STRING = 1024 * 1024;
const MAX_ARRAY = 2000;
const STUDIO_IDENTITY_PATTERN = /^[a-z0-9][a-z0-9._:-]{1,127}$/;
const STUDIO_RECORD_ID_PATTERN = /^[a-zA-Z0-9._:@-]{1,200}$/;
const STUDIO_VERSION_PATTERN = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-.]([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*))?$/;
const EXTENSION_ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9-]{0,127}$/;
const EXTENSION_VERSION_PATTERN = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-.][a-z0-9][a-z0-9.-]{0,63})?$/;
const MAX_STUDIO_VERSION_COMPONENT = 2147483647n;
const STUDIO_PROTOCOL = require('../resources/studio-operations.json');
if (STUDIO_PROTOCOL.schema_version !== 'px.studio-operation-contract/1.0' || !STUDIO_PROTOCOL.kinds) throw new Error('studio-operation-contract-invalid');

const CONTRACTS = Object.freeze({
  ready: [], refresh: [], openCoordinationHandoff: ['requestId'], openSettings: ['requestId'], configureCanonicalMemory: ['requestId'], buildRepositoryGraph: [], validate: [], createContextSnapshot: ['requestId'], openExtensionsView: ['requestId'], scanCleanup: [], teamPackPreview: [], refreshEnvironment: [], continueCodex: ['requestId'], cancelCodex: ['requestId'], listHostModels: [],
  skillQuery: ['goal', 'domain'], skillHydrate: ['skill', 'domain'], skillCompare: ['requestId', 'skill'], setupStudio: ['requestId'],
  createStudioDraft: ['requestId', 'kind', 'payload'],
  detachStudioDraft: ['requestId', 'kind'],
  loadSkillPackageEditor: ['requestId', 'catalogKind', 'recordId'],
  loadStudioRevisionEditor: ['requestId', 'kind', 'catalogKind', 'recordId'],
  releaseStudioTrust: ['requestId', 'trustKind', 'proof'],
  studioOperation: ['requestId', 'kind', 'operation', 'payload'],
  catalogQuery: ['requestId', 'kind', 'query', 'status', 'offset', 'limit', 'sort'],
  operationalCardsQuery: ['requestId', 'query', 'state', 'severity', 'surface', 'owner', 'evidenceGap', 'offset', 'limit'],
  operationalCardQuery: ['requestId', 'gapId'],
  operationalInventoryQuery: ['requestId', 'surfaceId'],
  graphQuery: ['requestId', 'view', 'mode', 'cluster', 'node', 'target', 'query', 'relation', 'direction', 'kind', 'status', 'offset', 'edgeOffset', 'depth', 'maxNodes', 'maxEdges'],
  graphRendered: ['requestId', 'view', 'nodeCount', 'edgeCount', 'visibleNodeCount', 'canvasWidth', 'canvasHeight'],
  activityQuery: ['requestId', 'query', 'category', 'status', 'limit'],
  setActivityPaused: ['requestId', 'paused'], reconcileStaleActivity: ['requestId'], memoryQuery: ['requestId', 'query', 'offset', 'limit', 'status', 'projectId', 'source'],
  createParallelPlan: ['plan'], claimCoordinationTask: ['taskId', 'claimTargets', 'ttlMinutes', 'mode', 'authority'],
  renewCoordinationClaim: ['taskId', 'claimId', 'ttlMinutes'],
  recordTaskProgress: ['taskId', 'status', 'summary', 'usage', 'nextAction', 'evidence'],
  reconcileCoordinationTask: ['taskId', 'summary', 'conflictsResolved'], releaseCoordinationTask: ['requestId', 'taskId', 'reason', 'acknowledgement'],
  captureCoordinationMemory: ['layer', 'kind', 'content', 'confidence', 'sourceArtifact', 'sourceHash'],
  copyTaskHandoff: ['requestId', 'taskId'], copyText: ['requestId', 'text'], exportRecordJson: ['requestId', 'record', 'fileName', 'title'],
  executeCleanup: ['ids', 'disposition'], enterprisePackToggle: ['packId', 'enabled'], enterpriseTargetConfigure: ['packId'],
  enterpriseDoctor: [], toggleBillablePolicy: ['enabled'], environmentQuery: ['subject', 'query', 'offset', 'limit'],
  environmentExtensionDetail: ['extensionId'], environmentLifecyclePreview: ['subject', 'recordId', 'action'],
  extensionLifecyclePreview: ['requestId', 'extensionId', 'version'],
  extensionLifecycleExecute: ['requestId', 'token', 'exactTarget'],
  extensionUpdatePreview: ['requestId', 'extensionId', 'version'],
  extensionUpdateExecute: ['requestId', 'token', 'exactTarget'],
  extensionEnablementPreview: ['requestId', 'extensionId', 'desiredAction', 'scope'],
  extensionEnablementExecute: ['requestId', 'token', 'exactTarget', 'extensionId', 'desiredAction', 'scope'],
  extensionUninstallPreview: ['requestId', 'extensionId'],
  extensionUninstallExecute: ['requestId', 'token', 'exactTarget', 'extensionId', 'consumerImpactAcknowledged'],
  extensionRollbackPreview: ['requestId', 'extensionId'],
  extensionRollbackExecute: ['requestId', 'token', 'exactTarget', 'extensionId'],
  extensionConflictQuery: ['requestId', 'extensionId'],
  extensionConflictResolutionPreview: ['requestId', 'extensionId', 'signalId', 'targetExtensionId', 'resolution'],
  extensionConflictResolutionExecute: ['requestId', 'token', 'exactTarget'],
  environmentLifecycleExecute: ['token', 'exactTarget', 'consumerImpactAcknowledged'], openFile: ['requestId', 'path']
});

const HOST_ACTION_REQUEST_TYPES = new Set([
  'openCoordinationHandoff', 'openSettings', 'configureCanonicalMemory', 'createContextSnapshot',
  'openExtensionsView', 'continueCodex', 'cancelCodex', 'setActivityPaused',
  'copyTaskHandoff', 'copyText', 'exportRecordJson', 'openFile', 'reconcileStaleActivity', 'setupStudio'
]);

function plainObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function wellFormedUnicode(value) {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) { const next = value.charCodeAt(index + 1); if (!(next >= 0xdc00 && next <= 0xdfff)) return false; index += 1; }
    else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}

function inspectValue(value, state, depth = 0) {
  if (depth > 10) throw new Error('webview-message-depth-exceeded');
  state.nodes += 1; if (state.nodes > 10000) throw new Error('webview-message-node-count-exceeded');
  if (value === null || typeof value === 'boolean') return;
  if (typeof value === 'number') { if (!Number.isFinite(value)) throw new Error('webview-message-non-finite-number'); return; }
  if (typeof value === 'string') { if (value.length > MAX_STRING) throw new Error('webview-message-string-too-large'); if (!wellFormedUnicode(value)) throw new Error('webview-message-string-unpaired-surrogate'); return; }
  if (Array.isArray(value)) {
    if (value.length > MAX_ARRAY) throw new Error('webview-message-array-too-large');
    if (Object.getOwnPropertySymbols(value).length || Object.keys(value).length !== value.length || !value.every((_item, index) => Object.hasOwn(value, index))) throw new Error('webview-message-array-not-dense-json');
    for (const item of value) inspectValue(item, state, depth + 1);
    return;
  }
  if (!plainObject(value)) throw new Error('webview-message-object-type-refused');
  if (Object.getOwnPropertySymbols(value).length) throw new Error('webview-message-object-type-refused');
  for (const key of Object.keys(value)) {
    if (!wellFormedUnicode(key) || key.length > MAX_STRING) throw new Error('webview-message-key-invalid');
    if (['__proto__', 'prototype', 'constructor'].includes(key)) throw new Error('webview-message-dangerous-key');
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor?.enumerable || !Object.hasOwn(descriptor, 'value')) throw new Error('webview-message-object-not-data');
    inspectValue(descriptor.value, state, depth + 1);
  }
}

function validCanonicalStudioVersion(value) {
  if (typeof value !== 'string' || !value || value.length > 96) return false;
  const match = STUDIO_VERSION_PATTERN.exec(value);
  if (!match || match[4]?.length > 64 || match[4]?.split('.').some(part => /^0[0-9]+$/.test(part))) return false;
  try { return [match[1], match[2], match[3]].every(item => BigInt(item) <= MAX_STUDIO_VERSION_COMPONENT); }
  catch { return false; }
}

function validateWebviewMessage(message) {
  if (!plainObject(message)) throw new Error('webview-message-must-be-an-object');
  inspectValue(message, { nodes: 0 });
  if (typeof message.type !== 'string' || !Object.hasOwn(CONTRACTS, message.type)) throw new Error('webview-message-type-unsupported');
  const allowed = new Set(['type', ...CONTRACTS[message.type]]);
  const unknown = Object.keys(message).filter(key => !allowed.has(key));
  if (unknown.length) throw new Error(`webview-message-unknown-fields:${unknown.slice(0, 8).join(',')}`);
  let serialized;
  try { serialized = JSON.stringify(message); } catch { throw new Error('webview-message-not-serializable'); }
  if (Buffer.byteLength(serialized, 'utf8') > MAX_MESSAGE_BYTES) throw new Error('webview-message-too-large');
  for (const key of ['offset', 'edgeOffset', 'limit', 'depth', 'maxNodes', 'maxEdges', 'ttlMinutes', 'confidence', 'nodeCount', 'edgeCount', 'visibleNodeCount', 'canvasWidth', 'canvasHeight']) {
    if (message[key] != null && (typeof message[key] !== 'number' || !Number.isFinite(message[key]))) throw new Error(`webview-message-field-invalid:${key}`);
  }
  if (message.ids != null && (!Array.isArray(message.ids) || message.ids.some(id => typeof id !== 'string' || id.length > 200))) throw new Error('webview-message-field-invalid:ids');
  if (message.claimTargets != null && (!Array.isArray(message.claimTargets) || message.claimTargets.some(item => typeof item !== 'string' || item.length > 512))) throw new Error('webview-message-field-invalid:claimTargets');
  if (message.type === 'executeCleanup' && !['recycle', 'permanent'].includes(message.disposition)) throw new Error('webview-message-field-invalid:disposition');
  if (['createStudioDraft', 'detachStudioDraft', 'studioOperation'].includes(message.type) && !Object.hasOwn(STUDIO_PROTOCOL.kinds, message.kind)) throw new Error('webview-message-field-invalid:studio-kind');
  if (['createStudioDraft', 'studioOperation'].includes(message.type) && !plainObject(message.payload)) throw new Error('webview-message-field-invalid:studio-payload');
  if (message.type === 'studioOperation' && !STUDIO_PROTOCOL.kinds[message.kind].includes(message.operation)) throw new Error('webview-message-field-invalid:studio-operation');
  const boundedStudioRequestId = typeof message.requestId === 'string' && /^[a-zA-Z0-9._:-]{1,200}$/.test(message.requestId);
  if (HOST_ACTION_REQUEST_TYPES.has(message.type) && !boundedStudioRequestId) throw new Error('webview-message-field-invalid:requestId');
  if ((['createStudioDraft', 'detachStudioDraft', 'loadSkillPackageEditor', 'loadStudioRevisionEditor', 'releaseStudioTrust'].includes(message.type) || (message.type === 'studioOperation' && message.operation === 'next-version')) && !boundedStudioRequestId) throw new Error('webview-message-field-invalid:requestId');
  if (message.type === 'releaseCoordinationTask') {
    if (!boundedStudioRequestId || typeof message.taskId !== 'string' || !message.taskId.trim() || message.taskId.length > 200 || typeof message.reason !== 'string' || message.reason.trim().length < 10 || message.reason.length > 1000) throw new Error('webview-message-field-invalid:task-release');
    const acknowledgement = message.acknowledgement;
    if (!plainObject(acknowledgement) || Object.keys(acknowledgement).sort().join('\0') !== ['boundary', 'confirmed', 'taskId'].sort().join('\0') || acknowledgement.boundary !== 'explicit-dashboard-confirmation' || acknowledgement.confirmed !== true || acknowledgement.taskId !== message.taskId) throw new Error('webview-message-field-invalid:task-release-acknowledgement');
  }
  if (message.type === 'studioOperation' && message.requestId != null && !boundedStudioRequestId) throw new Error('webview-message-field-invalid:requestId');
  if (message.type === 'studioOperation' && message.kind === 'skill' && !boundedStudioRequestId) throw new Error('webview-message-field-invalid:requestId');
  if (message.type === 'studioOperation' && ['runs', 'status', 'pause', 'cancel', 'stop', 'reconcile', 'resume'].includes(message.operation)) {
    if (!boundedStudioRequestId) throw new Error('webview-message-field-invalid:requestId');
    const payloadKeys = Object.keys(message.payload).sort().join('\0');
    if (message.operation === 'runs' && (payloadKeys !== 'limit' || !Number.isInteger(message.payload.limit) || message.payload.limit < 1 || message.payload.limit > 100)) throw new Error('webview-message-field-invalid:studio-runs-payload');
    if (['status', 'pause', 'cancel', 'stop'].includes(message.operation) && (payloadKeys !== 'run_id' || typeof message.payload.run_id !== 'string' || !STUDIO_RECORD_ID_PATTERN.test(message.payload.run_id))) throw new Error('webview-message-field-invalid:studio-run-control-payload');
    if (message.operation === 'reconcile' && (payloadKeys !== 'stale_after_seconds' || !Number.isInteger(message.payload.stale_after_seconds) || message.payload.stale_after_seconds < 1 || message.payload.stale_after_seconds > 86400)) throw new Error('webview-message-field-invalid:studio-reconcile-payload');
    if (message.operation === 'resume' && (typeof message.payload.run_id !== 'string' || !STUDIO_RECORD_ID_PATTERN.test(message.payload.run_id))) throw new Error('webview-message-field-invalid:studio-resume-payload');
  }
  if (message.type === 'studioOperation' && message.operation === 'next-version') {
    const keys = Object.keys(message.payload).sort().join('\0');
    const physicalKeys = ['identity', 'source_version'].sort().join('\0');
    const selectedSkillKeys = ['identity', 'source_selection_id', 'source_version'].sort().join('\0');
    const commonValid = typeof message.payload.identity === 'string' && STUDIO_IDENTITY_PATTERN.test(message.payload.identity) && validCanonicalStudioVersion(message.payload.source_version);
    const physicalValid = keys === physicalKeys && ['agent', 'workflow'].includes(message.kind);
    const selectedSkillValid = keys === selectedSkillKeys && message.kind === 'skill' && typeof message.payload.source_selection_id === 'string' && /^source-selection:[a-zA-Z0-9-]{1,160}$/.test(message.payload.source_selection_id);
    if (!commonValid || (!physicalValid && !selectedSkillValid)) throw new Error('webview-message-field-invalid:studio-next-version-payload');
  }
  if (message.type === 'createStudioDraft') {
    const identityKey = message.kind === 'agent' ? 'agent_id' : message.kind === 'workflow' ? 'workflow_id' : 'skill_id';
    if (typeof message.payload[identityKey] !== 'string' || !STUDIO_IDENTITY_PATTERN.test(message.payload[identityKey]) || !validCanonicalStudioVersion(message.payload.version)) throw new Error('webview-message-field-invalid:studio-create-payload');
  }
  if (message.type === 'openFile' && (typeof message.path !== 'string' || message.path.length > 32768)) throw new Error('webview-message-field-invalid:path');
  if (message.type === 'loadSkillPackageEditor' && message.catalogKind !== 'skills') throw new Error('webview-message-field-invalid:catalogKind');
  if (['loadSkillPackageEditor', 'loadStudioRevisionEditor'].includes(message.type) && (typeof message.recordId !== 'string' || !STUDIO_RECORD_ID_PATTERN.test(message.recordId))) throw new Error('webview-message-field-invalid:recordId');
  if (message.type === 'loadStudioRevisionEditor') {
    if (!['agent', 'workflow'].includes(message.kind) || message.catalogKind !== `${message.kind}s`) throw new Error('webview-message-field-invalid:studio-revision-selection');
  }
  if (message.type === 'releaseStudioTrust') {
    if (!['source-selection', 'version-allocation'].includes(message.trustKind) || typeof message.proof !== 'string' || !new RegExp(`^${message.trustKind}:[a-zA-Z0-9-]{1,160}$`).test(message.proof)) throw new Error('webview-message-field-invalid:studio-trust-release');
  }
  if (message.type === 'skillQuery' && (typeof message.goal !== 'string' || !message.goal.trim() || message.goal.length > 1000)) throw new Error('webview-message-field-invalid:goal');
  if (message.type === 'skillHydrate' && (typeof message.skill !== 'string' || !message.skill.trim() || message.skill.length > 200)) throw new Error('webview-message-field-invalid:skill');
  if (message.type === 'skillCompare' && (typeof message.requestId !== 'string' || !message.requestId || message.requestId.length > 200 || typeof message.skill !== 'string' || !STUDIO_IDENTITY_PATTERN.test(message.skill))) throw new Error('webview-message-field-invalid:skill-compare');
  if (message.type === 'operationalCardQuery' && (typeof message.gapId !== 'string' || !/^PX-(?:OS|GAP)-[0-9]{3,}$/.test(message.gapId))) throw new Error('webview-message-field-invalid:gapId');
  if (message.type === 'operationalCardsQuery') {
    for (const key of ['requestId', 'query', 'state', 'severity', 'surface', 'owner']) if (typeof message[key] !== 'string' || message[key].length > (key === 'query' ? 500 : 200)) throw new Error(`webview-message-field-invalid:${key}`);
    if (typeof message.evidenceGap !== 'boolean' || !Number.isInteger(message.offset) || message.offset < 0 || !Number.isInteger(message.limit) || message.limit < 1 || message.limit > 100) throw new Error('webview-message-field-invalid:operational-card-query');
  }
  if (message.type === 'operationalInventoryQuery' && (typeof message.requestId !== 'string' || typeof message.surfaceId !== 'string' || message.surfaceId.length > 160)) throw new Error('webview-message-field-invalid:operational-inventory-query');
  if (['skillQuery', 'skillHydrate'].includes(message.type) && !['px-standard', 'microsoft-vendor', 'enterprise-restricted', 'user-preserved'].includes(message.domain)) throw new Error('webview-message-field-invalid:domain');
  if (['extensionLifecyclePreview', 'extensionUpdatePreview'].includes(message.type)) {
    if (!boundedStudioRequestId) throw new Error('webview-message-field-invalid:requestId');
    if (typeof message.extensionId !== 'string' || !EXTENSION_ID_PATTERN.test(message.extensionId)) throw new Error('webview-message-field-invalid:extensionId');
    if (typeof message.version !== 'string' || message.version.length > 96 || (message.version && !EXTENSION_VERSION_PATTERN.test(message.version))) throw new Error('webview-message-field-invalid:extensionVersion');
  }
  if (['extensionLifecycleExecute', 'extensionUpdateExecute'].includes(message.type)) {
    if (!boundedStudioRequestId) throw new Error('webview-message-field-invalid:requestId');
    if (typeof message.token !== 'string' || !/^[a-zA-Z0-9-]{1,200}$/.test(message.token)) throw new Error('webview-message-field-invalid:extensionLifecycleToken');
    if (typeof message.exactTarget !== 'string' || message.exactTarget.length > 300) throw new Error('webview-message-field-invalid:exactTarget');
    const [extensionId, version, extra] = message.exactTarget.split('@');
    if (extra !== undefined || !EXTENSION_ID_PATTERN.test(extensionId) || (version !== undefined && !EXTENSION_VERSION_PATTERN.test(version))) throw new Error('webview-message-field-invalid:extensionExactTarget');
  }
  if (message.type === 'extensionEnablementPreview') {
    if (!boundedStudioRequestId || typeof message.extensionId !== 'string' || !EXTENSION_ID_PATTERN.test(message.extensionId)) throw new Error('webview-message-field-invalid:extensionEnablementIdentity');
    if (!['enable', 'disable'].includes(message.desiredAction) || !['workspace', 'global'].includes(message.scope)) throw new Error('webview-message-field-invalid:extensionEnablementIntent');
  }
  if (message.type === 'extensionEnablementExecute') {
    if (!boundedStudioRequestId || typeof message.token !== 'string' || !/^[a-zA-Z0-9-]{1,200}$/.test(message.token)) throw new Error('webview-message-field-invalid:extensionLifecycleToken');
    if (typeof message.extensionId !== 'string' || !EXTENSION_ID_PATTERN.test(message.extensionId) || !['enable', 'disable'].includes(message.desiredAction) || !['workspace', 'global'].includes(message.scope)) throw new Error('webview-message-field-invalid:extensionEnablementIntent');
    const expected = `${message.extensionId}@`;
    if (typeof message.exactTarget !== 'string' || !message.exactTarget.startsWith(expected) || !message.exactTarget.endsWith(`#${message.desiredAction}:${message.scope}`) || message.exactTarget.length > 400) throw new Error('webview-message-field-invalid:extensionExactTarget');
  }
  if (message.type === 'extensionUninstallPreview') {
    if (!boundedStudioRequestId || typeof message.extensionId !== 'string' || !EXTENSION_ID_PATTERN.test(message.extensionId)) throw new Error('webview-message-field-invalid:extensionUninstallIdentity');
  }
  if (message.type === 'extensionUninstallExecute') {
    if (!boundedStudioRequestId || typeof message.token !== 'string' || !/^[a-zA-Z0-9-]{1,200}$/.test(message.token)) throw new Error('webview-message-field-invalid:extensionLifecycleToken');
    if (typeof message.extensionId !== 'string' || !EXTENSION_ID_PATTERN.test(message.extensionId) || typeof message.consumerImpactAcknowledged !== 'boolean') throw new Error('webview-message-field-invalid:extensionUninstallIntent');
    if (typeof message.exactTarget !== 'string' || !message.exactTarget.startsWith(`${message.extensionId}@`) || !message.exactTarget.endsWith('#uninstall') || message.exactTarget.length > 400) throw new Error('webview-message-field-invalid:extensionExactTarget');
  }
  if (message.type === 'extensionRollbackPreview') {
    if (!boundedStudioRequestId || typeof message.extensionId !== 'string' || !EXTENSION_ID_PATTERN.test(message.extensionId)) throw new Error('webview-message-field-invalid:extensionRollbackIdentity');
  }
  if (message.type === 'extensionRollbackExecute') {
    if (!boundedStudioRequestId || typeof message.token !== 'string' || !/^[a-zA-Z0-9-]{1,200}$/.test(message.token)) throw new Error('webview-message-field-invalid:extensionLifecycleToken');
    if (typeof message.extensionId !== 'string' || !EXTENSION_ID_PATTERN.test(message.extensionId)) throw new Error('webview-message-field-invalid:extensionRollbackIdentity');
    const [targetId, version, extra] = String(message.exactTarget || '').split('@');
    if (extra !== undefined || targetId !== message.extensionId || !EXTENSION_VERSION_PATTERN.test(version || '')) throw new Error('webview-message-field-invalid:extensionExactTarget');
  }
  if (message.type === 'extensionConflictQuery') {
    if (!boundedStudioRequestId || typeof message.extensionId !== 'string' || !EXTENSION_ID_PATTERN.test(message.extensionId)) throw new Error('webview-message-field-invalid:extensionConflictIdentity');
  }
  if (message.type === 'extensionConflictResolutionPreview') {
    if (!boundedStudioRequestId || typeof message.extensionId !== 'string' || !EXTENSION_ID_PATTERN.test(message.extensionId) || typeof message.targetExtensionId !== 'string' || !EXTENSION_ID_PATTERN.test(message.targetExtensionId)) throw new Error('webview-message-field-invalid:extensionConflictIdentity');
    if (typeof message.signalId !== 'string' || !/^extension-conflict:[a-f0-9]{24}$/.test(message.signalId) || !['inspect', 'disable-workspace', 'disable-global', 'uninstall', 'install-target'].includes(message.resolution)) throw new Error('webview-message-field-invalid:extensionConflictResolution');
  }
  if (message.type === 'extensionConflictResolutionExecute') {
    if (!boundedStudioRequestId || typeof message.token !== 'string' || !/^[a-zA-Z0-9-]{1,200}$/.test(message.token)) throw new Error('webview-message-field-invalid:extensionLifecycleToken');
    if (typeof message.exactTarget !== 'string' || !/^conflict:extension-conflict:[a-f0-9]{24}:(?:inspect|disable-workspace|disable-global|uninstall|install-target):[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9-]{0,127}$/.test(message.exactTarget)) throw new Error('webview-message-field-invalid:extensionExactTarget');
  }
  if (message.exactTarget != null && (typeof message.exactTarget !== 'string' || message.exactTarget.length > 32768)) throw new Error('webview-message-field-invalid:exactTarget');
  if (message.type === 'graphRendered') {
    if (typeof message.requestId !== 'string' || message.requestId.length > 200 || !['capabilities', 'repository'].includes(message.view)) throw new Error('webview-message-field-invalid:graph-render-identity');
    for (const key of ['nodeCount', 'edgeCount', 'visibleNodeCount', 'canvasWidth', 'canvasHeight']) {
      if (!Number.isInteger(message[key]) || message[key] < 0 || message[key] > 100000) throw new Error(`webview-message-field-invalid:${key}`);
    }
  }
  if (message.type === 'graphQuery') {
    const modes = new Set(['full', 'overview', 'neighborhood', 'path', 'impact', 'dependencies', 'dependents', 'hubs', 'orphans', 'provenance']);
    if (typeof message.requestId !== 'string' || !message.requestId || message.requestId.length > 200) throw new Error('webview-message-field-invalid:requestId');
    if (!['capabilities', 'repository'].includes(message.view)) throw new Error('webview-message-field-invalid:view');
    if (!modes.has(message.mode)) throw new Error('webview-message-field-invalid:mode');
    if (!['incoming', 'outgoing', 'both'].includes(message.direction)) throw new Error('webview-message-field-invalid:direction');
    for (const key of ['offset', 'edgeOffset', 'depth', 'maxNodes', 'maxEdges']) {
      if (!Number.isInteger(message[key]) || message[key] < 0) throw new Error(`webview-message-field-invalid:${key}`);
    }
    if (message.offset > 10_000_000 || message.edgeOffset > 10_000_000 || message.depth > 6 || message.maxNodes > 500 || message.maxEdges > 1000) throw new Error('webview-message-field-invalid:graph-bounds');
    for (const key of ['cluster', 'node', 'target', 'query', 'relation', 'kind', 'status']) {
      if (typeof message[key] !== 'string' || message[key].length > (key === 'query' || key === 'node' || key === 'target' ? 500 : 160)) throw new Error(`webview-message-field-invalid:${key}`);
    }
  }
  return message;
}

module.exports = { CONTRACTS, MAX_MESSAGE_BYTES, STUDIO_PROTOCOL, validCanonicalStudioVersion, validateWebviewMessage };
