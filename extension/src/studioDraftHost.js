'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const ALLOCATION_BINDING_KEYS = Object.freeze([
  'schema_version',
  'kind',
  'identity',
  'source_version',
  'source_scope',
  'source_revision_sha256',
  'source_content_sha256',
  'candidate_version',
  'occupied_versions_sha256'
]);
const ALLOCATION_KEYS = Object.freeze([...ALLOCATION_BINDING_KEYS, 'observed_utc']);
const SHA256 = /^[a-f0-9]{64}$/;
const IDENTITY = /^[a-z0-9][a-z0-9._:-]{1,127}$/;
const TRUST_TOKEN = /^(?:source-selection|version-allocation):[a-zA-Z0-9-]{1,160}$/;
const TRUST_OWNER = /^[a-zA-Z0-9._:-]{1,200}$/;
const RECORD_ID = /^[a-zA-Z0-9._:@-]{1,200}$/;
const VERSION = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-.]([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*))?$/;
const MAX_VERSION_COMPONENT = 2147483647n;
const RESTRICTED_STANDARD_SKILL_VALUE = /^(?:enterprise|microsoft|ms|azure|m365|dynamics)(?:[.:/-]|$)/i;
const PRESERVED_ORIGINAL_SCHEMA = 'px.preserved-skill-provenance/1.0';
const PRESERVED_ORIGINAL_KEYS = Object.freeze([
  'body_sha256',
  'file_count',
  'origin',
  'package_relative',
  'schema_version',
  'skill_id',
  'source_version',
  'tree_sha256'
]);
const PRESERVED_PROVENANCE_FIELDS = Object.freeze({
  schema_version: 'preserved_original_schema_version',
  skill_id: 'preserved_original_skill_id',
  source_version: 'preserved_original_source_version',
  origin: 'preserved_original_origin',
  package_relative: 'preserved_original_package_relative',
  tree_sha256: 'preserved_original_tree_sha256',
  body_sha256: 'preserved_original_body_sha256',
  file_count: 'preserved_original_file_count'
});

function isWellFormedUnicode(value) {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1); if (!(next >= 0xdc00 && next <= 0xdfff)) return false; index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}

function canonicalTrustJson(value, seen = new Set()) {
  if (value === null || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'string') { if (!isWellFormedUnicode(value)) throw new TypeError('studio-trust-value-not-json'); return JSON.stringify(value); }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('studio-trust-value-not-json');
    return JSON.stringify(value);
  }
  if (!value || typeof value !== 'object' || seen.has(value)) throw new TypeError('studio-trust-value-not-json');
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null && !Array.isArray(value)) throw new TypeError('studio-trust-value-not-plain-json');
  if (Object.getOwnPropertySymbols(value).length) throw new TypeError('studio-trust-value-not-json');
  seen.add(value);
  try {
    if (Array.isArray(value)) {
      if (Object.keys(value).length !== value.length || !value.every((_item, index) => Object.hasOwn(value, index))) throw new TypeError('studio-trust-value-not-json');
      return `[${value.map(item => canonicalTrustJson(item, seen)).join(',')}]`;
    }
    return `{${Object.keys(value).sort().map(key => {
      if (!isWellFormedUnicode(key)) throw new TypeError('studio-trust-value-not-json');
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (!descriptor?.enumerable || !Object.hasOwn(descriptor, 'value')) throw new TypeError('studio-trust-value-not-json');
      return `${JSON.stringify(key)}:${canonicalTrustJson(descriptor.value, seen)}`;
    }).join(',')}}`;
  } finally { seen.delete(value); }
}

function exactKeys(value, required, optional = []) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const allowed = new Set([...required, ...optional]); const keys = Object.keys(value);
  return required.every(key => Object.hasOwn(value, key)) && keys.every(key => allowed.has(key));
}

function validTrustOwner(owner) {
  return exactKeys(owner, ['originId', 'requestId']) && typeof owner.originId === 'string' && typeof owner.requestId === 'string' && TRUST_OWNER.test(owner.originId) && TRUST_OWNER.test(owner.requestId);
}

function exactPreservedOriginal(value, expected = {}) {
  return exactKeys(value, PRESERVED_ORIGINAL_KEYS)
    && value.schema_version === PRESERVED_ORIGINAL_SCHEMA
    && typeof value.skill_id === 'string' && IDENTITY.test(value.skill_id)
    && validCanonicalVersion(value.source_version)
    && typeof value.origin === 'string' && value.origin.length >= 1 && value.origin.length <= 200 && isWellFormedUnicode(value.origin)
    && typeof value.package_relative === 'string' && validBoundedRelativePath(value.package_relative)
    && /^\.px\/preserved-skills\/(?:initial|pre-promotion|replaced)\/.+/.test(value.package_relative)
    && SHA256.test(value.tree_sha256) && SHA256.test(value.body_sha256)
    && Number.isInteger(value.file_count) && value.file_count >= 1 && value.file_count <= 128
    && (!expected.skill_id || value.skill_id === expected.skill_id)
    && (!expected.source_version || value.source_version === expected.source_version);
}

function preservedOriginalProvenance(value) {
  if (!exactPreservedOriginal(value)) throw new Error('studio-preserved-original-provenance-invalid');
  return Object.freeze(Object.fromEntries(Object.entries(PRESERVED_PROVENANCE_FIELDS).map(([key, field]) => [field, String(value[key])])));
}

function stripReservedPreservedProvenance(value) {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const reserved = new Set(Object.values(PRESERVED_PROVENANCE_FIELDS));
  return Object.fromEntries(Object.entries(source).filter(([key]) => !reserved.has(key)));
}

function exactSourceSelection(value) {
  const keys = ['backup_provenance', 'catalog_kind', 'file_count', 'identity', 'kind', 'package_path', 'package_scope', 'record_id', 'source_content_sha256', 'source_domain', 'source_origin', 'source_revision_sha256', 'source_scope', 'source_version', 'tree_sha256'];
  return exactKeys(value, keys)
    && value.catalog_kind === 'skills' && value.kind === 'skill' && value.source_domain === 'px-standard'
    && ['px-native', 'project-studio'].includes(value.source_origin)
    && (value.backup_provenance === null || exactPreservedOriginal(value.backup_provenance, { skill_id: value.identity, source_version: value.source_version }))
    && (value.backup_provenance === null || (value.source_scope === 'external-authenticated' && value.source_origin === 'px-native'))
    && typeof value.identity === 'string' && IDENTITY.test(value.identity) && validCanonicalVersion(value.source_version)
    && ['studio-physical', 'external-authenticated'].includes(value.source_scope)
    && ((value.source_scope === 'external-authenticated' && value.source_origin === 'px-native') || (value.source_scope === 'studio-physical' && value.source_origin === 'project-studio'))
    && ((value.source_scope === 'external-authenticated' && value.package_scope === 'engine') || (value.source_scope === 'studio-physical' && value.package_scope === 'project-studio'))
    && typeof value.record_id === 'string' && RECORD_ID.test(value.record_id)
    && typeof value.package_path === 'string' && validBoundedRelativePath(value.package_path)
    && ((value.package_scope === 'engine' && /^\.px\/skills\/[^/]+$/.test(value.package_path))
      || (value.package_scope === 'project-studio' && /^\.engineering-bootstrap\/studios\/skills\/[^/]+\/revisions\/[^/]+\/payload$/.test(value.package_path)))
    && SHA256.test(value.source_revision_sha256) && SHA256.test(value.source_content_sha256) && SHA256.test(value.tree_sha256)
    && (value.source_scope !== 'external-authenticated' || value.tree_sha256 === value.source_content_sha256)
    && Number.isInteger(value.file_count) && value.file_count >= 1 && value.file_count <= 128;
}

function createStudioTrustRegistry({ limit = 128, perOriginLimit = 32, ttlMs = 10 * 60_000, now = () => Date.now(), randomUUID = () => crypto.randomUUID() } = {}) {
  if (!Number.isInteger(limit) || limit < 1 || !Number.isInteger(perOriginLimit) || perOriginLimit < 1 || perOriginLimit > limit || !Number.isFinite(ttlMs) || ttlMs < 1) throw new TypeError('studio-trust-registry-bounds-invalid');
  const selections = new Map(); const allocations = new Map();
  const prune = map => { const current = now(); for (const [key, record] of map) if (record.expiresAt <= current) map.delete(key); };
  const register = (map, prefix, value, owner, metadata = {}) => {
    if (!validTrustOwner(owner)) throw new TypeError('studio-trust-owner-invalid');
    prune(selections); prune(allocations);
    if (selections.size + allocations.size >= limit) throw new Error(`studio-${prefix}-registry-capacity-exceeded`);
    let originCount = 0;
    for (const registry of [selections, allocations]) {
      for (const record of registry.values()) if (record.originId === owner.originId) originCount += 1;
    }
    for (const record of map.values()) if (record.originId === owner.originId && record.requestId === owner.requestId) throw new Error(`studio-${prefix}-request-already-registered`);
    if (originCount >= perOriginLimit) throw new Error(`studio-${prefix}-origin-capacity-exceeded`);
    const token = `${prefix}:${randomUUID()}`;
    if (!TRUST_TOKEN.test(token) || map.has(token)) throw new Error(`studio-${prefix}-token-invalid-or-colliding`);
    map.set(token, { serialized: canonicalTrustJson(value), originId: owner.originId, requestId: owner.requestId, expiresAt: now() + ttlMs, ...metadata });
    return token;
  };
  const requireOwner = (record, owner) => {
    if (!validTrustOwner(owner) || record.originId !== owner.originId || record.requestId !== owner.requestId) throw new Error('studio-trust-proof-owner-mismatch');
  };
  const requireExact = (map, token, value, owner, consume) => {
    prune(map);
    const record = typeof token === 'string' ? map.get(token) : undefined;
    if (!record || record.serialized !== canonicalTrustJson(value)) throw new Error('studio-trust-proof-invalid-or-expired');
    requireOwner(record, owner);
    if (consume) map.delete(token);
    return JSON.parse(record.serialized);
  };
  const resolveToken = (map, token, owner, consume = false) => {
    prune(map);
    const record = typeof token === 'string' ? map.get(token) : undefined;
    if (!record) throw new Error('studio-trust-proof-invalid-or-expired');
    requireOwner(record, owner);
    if (consume) map.delete(token);
    return JSON.parse(record.serialized);
  };
  const release = (map, token, owner) => { resolveToken(map, token, owner, true); return true; };
  const ownerFor = (map, token, originId) => {
    prune(map);
    if (typeof originId !== 'string' || !TRUST_OWNER.test(originId)) throw new TypeError('studio-trust-origin-invalid');
    const record = typeof token === 'string' ? map.get(token) : undefined;
    if (!record || record.originId !== originId) throw new Error('studio-trust-proof-invalid-or-origin-mismatch');
    return Object.freeze({ originId: record.originId, requestId: record.requestId });
  };
  const releaseOrigin = originId => {
    if (typeof originId !== 'string' || !TRUST_OWNER.test(originId)) throw new TypeError('studio-trust-origin-invalid');
    let released = 0;
    for (const map of [selections, allocations]) for (const [token, record] of map) if (record.originId === originId) { map.delete(token); released += 1; }
    return released;
  };
  const allocationSourceSelection = (token, owner) => {
    prune(allocations);
    const record = typeof token === 'string' ? allocations.get(token) : undefined;
    if (!record) throw new Error('studio-trust-proof-invalid-or-expired');
    requireOwner(record, owner);
    return typeof record.sourceSelectionSerialized === 'string' ? JSON.parse(record.sourceSelectionSerialized) : null;
  };
  return Object.freeze({
    registerSourceSelection: (value, owner) => { if (!exactSourceSelection(value)) throw new Error('studio-source-selection-invalid'); return register(selections, 'source-selection', value, owner); },
    resolveSourceSelection: (token, expected, owner) => { if (!exactSourceSelection(expected)) throw new Error('studio-source-selection-invalid'); return requireExact(selections, token, expected, owner, false); },
    resolveSourceSelectionToken: (token, owner) => resolveToken(selections, token, owner),
    consumeSourceSelectionToken: (token, owner) => resolveToken(selections, token, owner, true),
    sourceSelectionOwner: (token, originId) => ownerFor(selections, token, originId),
    releaseSourceSelection: (token, owner) => release(selections, token, owner),
    registerVersionAllocation: (kind, allocation, owner, sourceSelection = null) => {
      if (allocation?.kind !== kind || !exactAllocationEnvelope(allocation)) throw new Error('studio-version-allocation-invalid');
      if (sourceSelection !== null && (!exactSourceSelection(sourceSelection) || kind !== 'skill'
        || sourceSelection.identity !== allocation.identity || sourceSelection.source_version !== allocation.source_version
        || sourceSelection.source_scope !== allocation.source_scope || sourceSelection.source_revision_sha256 !== allocation.source_revision_sha256
        || sourceSelection.source_content_sha256 !== allocation.source_content_sha256)) throw new Error('studio-version-allocation-source-selection-mismatch');
      return register(allocations, 'version-allocation', { kind, allocation }, owner, {
        sourceSelectionSerialized: sourceSelection === null ? null : canonicalTrustJson(sourceSelection)
      });
    },
    assertVersionAllocation: (token, kind, allocation, owner) => requireExact(allocations, token, { kind, allocation }, owner, false),
    consumeVersionAllocation: (token, kind, allocation, owner) => requireExact(allocations, token, { kind, allocation }, owner, true),
    resolveVersionAllocationSourceSelection: allocationSourceSelection,
    versionAllocationOwner: (token, originId) => ownerFor(allocations, token, originId),
    releaseVersionAllocation: (token, owner) => release(allocations, token, owner),
    disposeOrigin: releaseOrigin,
    dispose: () => { selections.clear(); allocations.clear(); },
    diagnostics: () => { prune(selections); prune(allocations); return { selections: selections.size, allocations: allocations.size, total: selections.size + allocations.size, limit, per_origin_limit: perOriginLimit, ttl_ms: ttlMs }; }
  });
}

function validCanonicalVersion(value) {
  if (typeof value !== 'string' || value !== value.trim().toLowerCase() || value.length > 96) return false;
  const match = VERSION.exec(value);
  if (!match || match[4]?.length > 64 || match[4]?.split('.').some(part => /^0[0-9]+$/.test(part))) return false;
  try { return [match[1], match[2], match[3]].every(item => BigInt(item) <= MAX_VERSION_COMPONENT); } catch { return false; }
}

function validCanonicalUtc(value) {
  if (typeof value !== 'string' || value.startsWith('0000-') || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(value)) return false;
  const normalized = value.includes('.') ? value : value.replace('Z', '.000Z');
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString() === normalized;
}

function exactAllocationEnvelope(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).sort().join('\0') !== [...ALLOCATION_KEYS].sort().join('\0')) return false;
  return value.schema_version === 'px.studio-version-allocation/1.0'
    && ['agent', 'workflow', 'skill'].includes(value.kind)
    && ['studio-physical', 'external-authenticated'].includes(value.source_scope)
    && (value.source_scope !== 'external-authenticated' || value.kind === 'skill')
    && typeof value.identity === 'string' && IDENTITY.test(value.identity)
    && validCanonicalVersion(value.source_version)
    && validCanonicalVersion(value.candidate_version)
    && SHA256.test(value.source_revision_sha256)
    && SHA256.test(value.source_content_sha256)
    && SHA256.test(value.occupied_versions_sha256)
    && validCanonicalUtc(value.observed_utc);
}

function sameAllocationBinding(left, right) {
  return exactAllocationEnvelope(left) && exactAllocationEnvelope(right) && ALLOCATION_BINDING_KEYS.every(key => left[key] === right[key]);
}

async function postCancellation(postMessage, requestId, kind) {
  await postMessage({ type: 'studioDraftCancelled', requestId, kind });
  return { status: 'cancelled' };
}

async function postConflict(postMessage, requestId, kind, allocation, allocationProof, error) {
  await postMessage({ type: 'studioVersionConflict', requestId, kind, allocation, allocationProof, error });
  return { status: 'conflict', allocation, allocationProof };
}

function samePhysicalDirectory(left, right) {
  if (typeof left !== 'string' || !left || typeof right !== 'string' || !right) return false;
  try {
    return fs.realpathSync.native(path.resolve(left)) === fs.realpathSync.native(path.resolve(right));
  } catch {
    return false;
  }
}

function validCleanupWarnings(value) {
  return value === undefined || (Array.isArray(value) && value.length <= 8 && value.every(item => typeof item === 'string' && item.length > 0 && item.length <= 240));
}

function validBoundedRelativePath(value, nullable = false) {
  if (nullable && value === null) return true;
  if (typeof value !== 'string' || value.length < 1 || Buffer.byteLength(value, 'utf8') > 4096 || !isWellFormedUnicode(value) || path.isAbsolute(value) || value.includes('\\')) return false;
  const parts = value.split('/');
  return parts.length <= 12 && parts.every(part => part && part !== '.' && part !== '..' && part === part.normalize('NFC') && Buffer.byteLength(part, 'utf8') <= 255 && !/[<>:"|?*\u0000-\u001f]/.test(part) && !/[. ]$/.test(part) && !/^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$/i.test(part));
}

function exactFileInventory(value) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 128) return null;
  const observed = new Set(); const rows = [];
  for (const row of value) {
    if (!exactKeys(row, ['bytes', 'path', 'sha256']) || !validBoundedRelativePath(row.path) || !Number.isInteger(row.bytes) || row.bytes < 0 || row.bytes > 512 * 1024 || !SHA256.test(row.sha256) || observed.has(row.path)) return null;
    observed.add(row.path); rows.push({ path: row.path, bytes: row.bytes, sha256: row.sha256 });
  }
  const sorted = [...rows].sort((left, right) => Buffer.compare(Buffer.from(left.path, 'utf8'), Buffer.from(right.path, 'utf8')));
  return rows.every((row, index) => row.path === sorted[index].path) ? rows : null;
}

function sameFileInventory(left, right) {
  const leftRows = exactFileInventory(left); const rightRows = exactFileInventory(right);
  return Boolean(leftRows && rightRows && leftRows.length === rightRows.length && leftRows.every((row, index) => row.path === rightRows[index].path && row.bytes === rightRows[index].bytes && row.sha256 === rightRows[index].sha256));
}

function receiptVariant(result) {
  if (result.created === true && !Object.hasOwn(result, 'idempotent_replay')) return 'created';
  if (result.created === false && result.idempotent_replay === true) return 'recovered';
  return null;
}

function createReceiptDisposition(kind, result, payload, expectedSkillSource = null) {
  if (!result || typeof result !== 'object' || Array.isArray(result) || !validCleanupWarnings(result.cleanup_warnings)) return null;
  try { if (Buffer.byteLength(canonicalTrustJson(result), 'utf8') > 1024 * 1024) return null; } catch { return null; }
  const variant = receiptVariant(result); if (!variant) return null;
  const identity = payload?.[kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : 'skill_id'];
  const version = payload?.version;
  const variantKeys = variant === 'recovered' ? ['idempotent_replay'] : [];
  const optionalKeys = [...variantKeys, ...(result.cleanup_warnings === undefined ? [] : ['cleanup_warnings'])];
  if (kind === 'agent') {
    const keys = ['admission_state', 'agent_id', 'authority_definition_path', 'authority_granted_by_builder', 'authority_state', 'builder_compiler_receipt_path', 'builder_compiler_receipt_sha256', 'builder_graph_explicit', 'builder_graph_path', 'builder_graph_sha256', 'builder_graph_state', 'created', 'created_utc', 'editor_layout_path', 'editor_layout_sha256', 'host_authority_retained', 'instruction_sha256', 'operation', 'record_sha256', 'runtime_state', 'schema_version', 'validation_state', 'version'];
    return exactKeys(result, keys, optionalKeys)
      && result.schema_version === 'px.agent-creation-receipt/1.1'
      && result.operation === 'agent.create_candidate'
      && result.agent_id === identity && result.version === version
      && SHA256.test(result.record_sha256) && SHA256.test(result.instruction_sha256) && validCanonicalUtc(result.created_utc)
      && result.validation_state === 'structurally_valid' && result.admission_state === 'unadmitted' && result.runtime_state === 'stopped'
      && ['defined', 'none'].includes(result.authority_state) && (result.authority_state === 'defined' ? validBoundedRelativePath(result.authority_definition_path) : result.authority_definition_path === null)
      && result.builder_graph_state === 'content-bound' && validBoundedRelativePath(result.builder_graph_path) && SHA256.test(result.builder_graph_sha256)
      && validBoundedRelativePath(result.editor_layout_path) && SHA256.test(result.editor_layout_sha256)
      && validBoundedRelativePath(result.builder_compiler_receipt_path) && SHA256.test(result.builder_compiler_receipt_sha256)
      && typeof result.builder_graph_explicit === 'boolean' && result.authority_granted_by_builder === false && result.host_authority_retained === true ? variant : null;
  }
  if (kind === 'workflow') {
    const keys = ['authority_definition_path', 'authority_state', 'created', 'created_utc', 'definition_sha256', 'definition_state', 'editor_layout_path', 'editor_layout_sha256', 'editor_layout_state', 'host_authority_retained', 'operation', 'path', 'revision_sha256', 'run_state', 'runnable_state', 'schema_version', 'version', 'workflow_id'];
    return exactKeys(result, keys, optionalKeys)
      && result.schema_version === 'px.workflow-revision-receipt/1.2'
      && result.operation === 'workflow.save_revision'
      && result.workflow_id === identity && result.version === version
      && SHA256.test(result.revision_sha256) && SHA256.test(result.definition_sha256)
      && validCanonicalUtc(result.created_utc) && result.definition_state === 'saved' && result.runnable_state === 'unvalidated' && result.run_state === 'never_run'
      && validBoundedRelativePath(result.path) && ['defined', 'none'].includes(result.authority_state) && (result.authority_state === 'defined' ? validBoundedRelativePath(result.authority_definition_path) : result.authority_definition_path === null)
      && result.editor_layout_state === 'content-bound' && validBoundedRelativePath(result.editor_layout_path) && SHA256.test(result.editor_layout_sha256)
      && result.host_authority_retained === true ? variant : null;
  }
  const expectedPreservedOriginal = expectedSkillSource?.preservedOriginal || null;
  const preservedOptional = expectedPreservedOriginal === null ? [] : ['preserved_original'];
  const skillKeys = ['admission_state', 'created', 'draft_state', 'file_count', 'files', 'manifest', 'manifest_sha256', 'payload_root', 'promotion_state', 'schema_version', 'source_authority_token', 'source_tree_sha256'];
  return kind === 'skill' && exactKeys(result, skillKeys, [...optionalKeys, ...preservedOptional])
    && result.schema_version === 'px.skill-draft/1.1'
    && result.manifest && typeof result.manifest === 'object' && !Array.isArray(result.manifest)
    && Buffer.byteLength(canonicalTrustJson(result.manifest), 'utf8') <= 512 * 1024
    && result.manifest.skill_id === identity && result.manifest.version === version
    && result.manifest_sha256 === crypto.createHash('sha256').update(canonicalTrustJson(result.manifest), 'utf8').digest('hex') && SHA256.test(result.source_tree_sha256)
    && result.payload_root === 'payload' && result.draft_state === 'saved' && result.admission_state === 'unadmitted' && result.promotion_state === 'not_promoted'
    && Number.isInteger(result.file_count) && result.file_count >= 1 && result.file_count <= 128 && exactFileInventory(result.files)?.length === result.file_count
    && typeof result.source_authority_token === 'string' && result.source_authority_token.length <= 512
    && expectedSkillSource && result.source_authority_token === expectedSkillSource.sourceToken && result.source_tree_sha256 === expectedSkillSource.treeSha256
    && (expectedPreservedOriginal === null ? !Object.hasOwn(result, 'preserved_original') : canonicalTrustJson(result.preserved_original) === canonicalTrustJson(expectedPreservedOriginal))
    && result.file_count === expectedSkillSource.fileCount && sameFileInventory(result.files, expectedSkillSource.files) ? variant : null;
}

function validCreateReceipt(kind, result, payload, expectedSkillSource = null) {
  return createReceiptDisposition(kind, result, payload, expectedSkillSource) !== null;
}

function validInitialAbsenceReceipt(value, kind, identity) {
  return exactKeys(value, ['absent', 'identity', 'kind', 'observed_utc', 'schema_version'])
    && value.schema_version === 'px.studio-identity-absence/1.0' && value.kind === kind && value.identity === identity
    && value.absent === true && validCanonicalUtc(value.observed_utc);
}

function validateStandardSkillEditorFiles(editorFiles) {
  if (!editorFiles || typeof editorFiles !== 'object' || Array.isArray(editorFiles)) throw new Error('studio-skill-editor-files-invalid');
  let capability;
  try { capability = JSON.parse(String(editorFiles['capability.json'] || '')); }
  catch { throw new Error('studio-skill-capability-json-invalid'); }
  if (!capability || typeof capability !== 'object' || Array.isArray(capability) || capability.domain !== 'px-standard') throw new Error('studio-skill-standard-domain-required:capability.json');
  const restrictedKey = key => /(?:capabilit|credential|namespace|domain)/i.test(key);
  const visit = (value, parentKey = '') => {
    if (typeof value === 'string') {
      if (restrictedKey(parentKey) && RESTRICTED_STANDARD_SKILL_VALUE.test(value.trim())) throw new Error('studio-skill-restricted-domain-reference');
      return;
    }
    if (Array.isArray(value)) { for (const item of value) visit(item, parentKey); return; }
    if (!value || typeof value !== 'object') return;
    for (const [key, item] of Object.entries(value)) {
      visit(item, key);
    }
  };
  visit(capability);
  const yamlText = String(editorFiles['skill.yaml'] || ''); let manifestDomain;
  try {
    const manifest = JSON.parse(yamlText);
    if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) throw new Error('manifest-not-object');
    manifestDomain = manifest.domain;
    visit(manifest);
  } catch (error) {
    if (error?.message === 'studio-skill-restricted-domain-reference') throw error;
    manifestDomain = /^domain\s*:\s*([^#\r\n]+)/m.exec(yamlText)?.[1]?.trim();
    for (const match of yamlText.matchAll(/^(?:\s*)(?:capability(?:_id)?|credential(?:_namespace)?|namespace)\s*:\s*([^#\r\n]+)/gmi)) if (RESTRICTED_STANDARD_SKILL_VALUE.test(match[1].trim())) throw new Error('studio-skill-restricted-domain-reference');
  }
  if (manifestDomain !== 'px-standard') throw new Error('studio-skill-standard-domain-required:skill.yaml');
  return true;
}

async function dispatchStudioCreateMessage(rawMessage, dependencies) {
  const message = dependencies.validateMessage(rawMessage);
  if (message?.type !== 'createStudioDraft') throw new Error('studio-draft-dispatch-message-invalid');
  const originWebview = dependencies.originWebview;
  if (!originWebview || typeof originWebview.postMessage !== 'function') throw new TypeError('studio-draft-origin-webview-invalid');
  return createStudioDraftFromHost(message, { ...dependencies, postMessage: outbound => originWebview.postMessage(outbound) });
}

async function createStudioDraftFromHost(message, dependencies) {
  const {
    bridge,
    postMessage,
    confirmCreate,
    materializeSkillPackage,
    afterCommit,
    reportPostCommitWarning,
    assertVersionAllocation,
    consumeVersionAllocation,
    registerVersionAllocation,
    resolveVersionAllocationSourceSelection,
    reauthenticateVersionAllocationSourceSelection,
    allocationOwner,
    assertInitialCreateAbsent,
    reclaimSkillPackage,
    isVersionConflict
  } = dependencies;
  if (!bridge || typeof postMessage !== 'function' || typeof confirmCreate !== 'function' || typeof materializeSkillPackage !== 'function' || typeof isVersionConflict !== 'function') {
    throw new TypeError('studio-draft-host-dependencies-invalid');
  }

  const kind = String(message?.kind || '');
  const identityKey = kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : kind === 'skill' ? 'skill_id' : '';
  if (!identityKey) throw new Error('studio-draft-kind-invalid');
  const requestId = message.requestId;
  let payload = { ...message.payload };
  const suppliedAllocation = payload.version_allocation;
  const suppliedAllocationProof = payload.version_allocation_proof;
  delete payload.version_allocation_proof;
  const payloadIdentity = String(payload[identityKey] || '').trim().toLowerCase();
  if (kind === 'skill') {
    if (!payload.editor_files) throw new Error('studio-skill-editor-files-required');
    validateStandardSkillEditorFiles(payload.editor_files);
    payload.provenance = stripReservedPreservedProvenance(payload.provenance);
  }

  let allocationSourceSelection = null;
  if (suppliedAllocation) {
    if (typeof assertVersionAllocation !== 'function' || typeof consumeVersionAllocation !== 'function' || typeof registerVersionAllocation !== 'function') throw new TypeError('studio-version-allocation-trust-dependencies-invalid');
    if (!validTrustOwner(allocationOwner)) throw new TypeError('studio-version-allocation-owner-invalid');
    await assertVersionAllocation(suppliedAllocationProof, kind, suppliedAllocation, allocationOwner);
    if (suppliedAllocation.identity !== payloadIdentity || suppliedAllocation.kind !== kind || suppliedAllocation.candidate_version !== payload.version) {
      throw new Error('studio-version-allocation-payload-binding-mismatch');
    }
    if (kind === 'skill' && typeof resolveVersionAllocationSourceSelection === 'function') {
      allocationSourceSelection = await resolveVersionAllocationSourceSelection(suppliedAllocationProof, allocationOwner);
    }
    if (kind === 'skill' && suppliedAllocation.source_scope === 'external-authenticated') {
      if (!exactSourceSelection(allocationSourceSelection)
        || allocationSourceSelection.identity !== suppliedAllocation.identity
        || allocationSourceSelection.source_version !== suppliedAllocation.source_version
        || allocationSourceSelection.source_scope !== suppliedAllocation.source_scope
        || allocationSourceSelection.source_revision_sha256 !== suppliedAllocation.source_revision_sha256
        || allocationSourceSelection.source_content_sha256 !== suppliedAllocation.source_content_sha256) throw new Error('studio-external-skill-allocation-lineage-missing-or-mismatched');
    }
    const freshAllocation = await bridge.nextStudioVersion(
      kind,
      payloadIdentity,
      suppliedAllocation.source_version,
      suppliedAllocation.source_scope,
      suppliedAllocation.source_revision_sha256,
      suppliedAllocation.source_content_sha256
    );
    if (!sameAllocationBinding(freshAllocation, suppliedAllocation)) {
      await consumeVersionAllocation(suppliedAllocationProof, kind, suppliedAllocation, allocationOwner);
      const freshProof = await registerVersionAllocation(kind, freshAllocation, allocationOwner, allocationSourceSelection);
      return postConflict(postMessage, requestId, kind, freshAllocation, freshProof, 'The immutable revision set changed or the selected version does not match the current backend allocation.');
    }
    payload = { ...payload, version_allocation: freshAllocation };
  } else if (suppliedAllocationProof !== undefined) {
    throw new Error('studio-version-allocation-proof-without-allocation');
  } else {
    if (payload.version !== '1.0.0' || typeof assertInitialCreateAbsent !== 'function') throw new Error('studio-initial-create-absence-proof-required');
    const absence = await assertInitialCreateAbsent(kind, payloadIdentity);
    if (!validInitialAbsenceReceipt(absence, kind, payloadIdentity)) throw new Error('studio-initial-create-absence-receipt-invalid');
  }

  if (!await confirmCreate(kind, payload, identityKey)) return postCancellation(postMessage, requestId, kind);
  if (kind === 'skill' && suppliedAllocation?.source_scope === 'external-authenticated') {
    if (typeof reauthenticateVersionAllocationSourceSelection !== 'function') throw new TypeError('studio-external-skill-lineage-reauthentication-unavailable');
    const reauthenticated = await reauthenticateVersionAllocationSourceSelection(allocationSourceSelection);
    if (!exactSourceSelection(reauthenticated)
      || canonicalTrustJson(reauthenticated) !== canonicalTrustJson(allocationSourceSelection)) throw new Error('studio-external-skill-lineage-changed');
    allocationSourceSelection = reauthenticated;
    if (allocationSourceSelection.backup_provenance !== null) payload.provenance = {
      ...payload.provenance,
      ...preservedOriginalProvenance(allocationSourceSelection.backup_provenance)
    };
  }
  if (suppliedAllocation) await consumeVersionAllocation(suppliedAllocationProof, kind, suppliedAllocation, allocationOwner);
  else {
    const absence = await assertInitialCreateAbsent(kind, payloadIdentity);
    if (!validInitialAbsenceReceipt(absence, kind, payloadIdentity)) throw new Error('studio-initial-create-absence-receipt-stale');
  }

  let materialized; let expectedSkillSource;
  if (kind === 'skill') {
    if (!payload.editor_files) throw new Error('studio-skill-editor-files-required');
    materialized = materializeSkillPackage(bridge.projectRoot, payload);
    const materialization = materialized?.materialization;
    const materializationKeys = ['file_count', 'files', 'operation_id', 'resource_relative', 'reused', 'schema_version', 'source_directory', 'tree_sha256'];
    const materializationFiles = exactFileInventory(materialization?.files);
    if (!materialized || typeof materialized.sourceDirectory !== 'string' || !materialized.sourceDirectory || !SHA256.test(materialized.treeSha256) || !Number.isInteger(materialized.fileCount) || materialized.fileCount < 1
      || !exactKeys(materialization, materializationKeys) || materialization.schema_version !== 'px.studio-package-materialization/1.0'
      || typeof materialization.operation_id !== 'string' || !/^[a-f0-9-]{32,64}$/i.test(materialization.operation_id)
      || typeof materialization.resource_relative !== 'string' || !validBoundedRelativePath(materialization.resource_relative.replaceAll('\\', '/')) || typeof materialization.reused !== 'boolean'
      || typeof materialized.reused !== 'boolean' || materialized.reused !== materialization.reused
      || materialization.source_directory !== materialized.sourceDirectory || materialization.tree_sha256 !== materialized.treeSha256
      || materialization.file_count !== materialized.fileCount || !materializationFiles || materializationFiles.length !== materialized.fileCount) throw new Error('studio-skill-materialization-receipt-invalid');
    const admissionPayload = { source_directory: materialized.sourceDirectory, expected_tree_sha256: materialized.treeSha256, expected_file_count: materialized.fileCount };
    const admissionCapability = await bridge.issueStudioApproval('skill', 'admit-source', admissionPayload);
    const admission = await bridge.studioOperation('skill', 'admit-source', { ...admissionPayload, approval_capability: admissionCapability.approval_capability });
    const admissionKeys = ['schema_version', 'source_token', 'source_directory', 'source_tree_sha256', 'file_count'];
    if (!admission || typeof admission !== 'object' || Array.isArray(admission) || Object.keys(admission).sort().join('\0') !== admissionKeys.sort().join('\0') || admission.schema_version !== 'px.skill-source-admission/1.0' || typeof admission.source_token !== 'string' || !admission.source_token || !samePhysicalDirectory(admission.source_directory, materialized.sourceDirectory) || admission.source_tree_sha256 !== materialized.treeSha256 || admission.file_count !== materialized.fileCount) throw new Error('studio-skill-source-admission-receipt-mismatch');
    expectedSkillSource = { sourceToken: admission.source_token, treeSha256: materialized.treeSha256, fileCount: materialized.fileCount, files: materialization.files, preservedOriginal: allocationSourceSelection?.backup_provenance || null };
    const { editor_files: _editorFiles, ...skillPayload } = payload;
    payload = { ...skillPayload, source_directory: admission.source_directory, source_token: admission.source_token };
  }

  const capability = await bridge.issueStudioApproval(kind, 'create', payload);
  payload = { ...payload, approval_capability: capability.approval_capability };
  let result;
  try {
    result = await bridge.createStudioDraft(kind, payload);
  } catch (error) {
    if (!isVersionConflict(error) || !suppliedAllocation) throw error;
    const allocation = await bridge.nextStudioVersion(
      kind,
      payload[identityKey],
      suppliedAllocation.source_version,
      suppliedAllocation.source_scope,
      suppliedAllocation.source_revision_sha256,
      suppliedAllocation.source_content_sha256
    );
    const freshProof = await registerVersionAllocation(kind, allocation, allocationOwner, allocationSourceSelection);
    return postConflict(postMessage, requestId, kind, allocation, freshProof, 'Another immutable revision was published before this save completed.');
  }

  const warnings = [];
  const disposition = createReceiptDisposition(kind, result, payload, expectedSkillSource);
  if (!disposition) {
    warnings.push('studio-draft-commit-receipt-invalid');
    try { await postMessage({ type: 'studioDraftOutcomeUnverified', requestId, kind, warnings: [...warnings] }); }
    catch (error) { warnings.push(`studio-draft-outcome-delivery-failed:${error instanceof Error ? error.message : String(error)}`); }
    if (typeof afterCommit === 'function') {
      try { await afterCommit(); }
      catch (error) { warnings.push(`studio-draft-postcommit-refresh-failed:${error instanceof Error ? error.message : String(error)}`); }
    }
    if (typeof reportPostCommitWarning === 'function') {
      try { await reportPostCommitWarning({ requestId, kind, warnings: [...warnings] }); } catch { /* durable catalog recovery remains authoritative */ }
    }
    return { status: 'commit-outcome-unverified', result: null, warnings };
  }
  if (Array.isArray(result.cleanup_warnings)) warnings.push(...result.cleanup_warnings.map(item => `studio-draft-backend-cleanup-warning:${item}`));
  if (kind === 'skill') {
    if (typeof reclaimSkillPackage !== 'function') warnings.push('studio-draft-materialized-input-reclaim-unavailable');
    else {
      try {
        const reclamation = await reclaimSkillPackage(bridge.projectRoot, materialized, result);
        if (!reclamation || reclamation.reclaimed !== true) warnings.push('studio-draft-materialized-input-reclaim-unverified');
      } catch (error) { warnings.push(`studio-draft-materialized-input-reclaim-failed:${error instanceof Error ? error.message : String(error)}`); }
    }
  }
  try {
    const delivered = await postMessage({ type: 'studioDraftResult', requestId, kind, outcome: disposition, result });
    if (delivered === false) warnings.push('studio-draft-result-not-delivered');
  } catch (error) {
    warnings.push(`studio-draft-result-delivery-failed:${error instanceof Error ? error.message : String(error)}`);
  }
  if (typeof afterCommit === 'function') {
    try { await afterCommit(result); }
    catch (error) { warnings.push(`studio-draft-postcommit-refresh-failed:${error instanceof Error ? error.message : String(error)}`); }
  }
  if (warnings.length && typeof reportPostCommitWarning === 'function') {
    try { await reportPostCommitWarning({ requestId, kind, result, warnings: [...warnings] }); } catch { /* the committed receipt remains authoritative */ }
  }
  return { status: warnings.length ? `${disposition}-with-delivery-warning` : disposition, result, warnings };
}

module.exports = { ALLOCATION_BINDING_KEYS, ALLOCATION_KEYS, PRESERVED_ORIGINAL_SCHEMA, PRESERVED_PROVENANCE_FIELDS, canonicalTrustJson, createReceiptDisposition, createStudioDraftFromHost, createStudioTrustRegistry, dispatchStudioCreateMessage, exactAllocationEnvelope, exactPreservedOriginal, exactSourceSelection, preservedOriginalProvenance, sameAllocationBinding, samePhysicalDirectory, stripReservedPreservedProvenance, validCanonicalUtc, validCanonicalVersion, validCreateReceipt, validInitialAbsenceReceipt, validTrustOwner, validateStandardSkillEditorFiles };
