'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { canonicalTrustJson, createReceiptDisposition, createStudioDraftFromHost, createStudioTrustRegistry, dispatchStudioCreateMessage, exactAllocationEnvelope, sameAllocationBinding, validCanonicalUtc } = require('../src/studioDraftHost');
const { exactStudioVersionConflictError, studioProcessError } = require('../src/pxBridge');
const { digestFiles, fileInventory, materializeSkillPackage, normalizeFiles } = require('../src/studioPackage');

const EDITOR_TREE_SHA256 = 'e'.repeat(64);
const TRUST_OWNER = Object.freeze({ originId: 'panel:fixture', requestId: 'allocation:fixture' });

function allocation(overrides = {}) {
  return {
    schema_version: 'px.studio-version-allocation/1.0',
    kind: 'agent',
    identity: 'agent:demo',
    source_version: '1.0.0',
    source_scope: 'studio-physical',
    source_revision_sha256: 'a'.repeat(64),
    source_content_sha256: 'b'.repeat(64),
    candidate_version: '1.0.1',
    occupied_versions_sha256: 'c'.repeat(64),
    observed_utc: '2026-08-17T00:00:00.000Z',
    ...overrides
  };
}

function sourceSelection(overrides = {}) {
  return {
    backup_provenance: null, catalog_kind: 'skills', file_count: 4, identity: 'skill:demo', kind: 'skill',
    package_path: '.px/skills/demo', package_scope: 'engine', record_id: 'skill:demo', source_content_sha256: 'b'.repeat(64),
    source_domain: 'px-standard', source_origin: 'px-native', source_revision_sha256: 'a'.repeat(64), source_scope: 'external-authenticated',
    source_version: '1.0.0', tree_sha256: 'b'.repeat(64), ...overrides
  };
}

function preservedOriginal(overrides = {}) {
  return {
    schema_version: 'px.preserved-skill-provenance/1.0', skill_id: 'skill:demo', source_version: '1.0.0',
    origin: 'workspace-agents-original', package_relative: '.px/preserved-skills/initial/workspace-original/demo',
    tree_sha256: 'd'.repeat(64), body_sha256: 'f'.repeat(64), file_count: 4, ...overrides
  };
}

function createReceipt(kind, payload, materialized = null, overrides = {}) {
  if (kind === 'agent') return {
    schema_version: 'px.agent-creation-receipt/1.1', operation: 'agent.create_candidate', agent_id: payload.agent_id, version: payload.version,
    record_sha256: '1'.repeat(64), instruction_sha256: '2'.repeat(64), validation_state: 'structurally_valid', admission_state: 'unadmitted', runtime_state: 'stopped',
    authority_state: 'none', authority_definition_path: null, builder_graph_state: 'content-bound', builder_graph_path: 'agents/demo/builder-graph.json', builder_graph_sha256: '3'.repeat(64),
    editor_layout_path: 'agents/demo/editor-layout.json', editor_layout_sha256: '4'.repeat(64), builder_compiler_receipt_path: 'agents/demo/builder-compiler-receipt.json',
    builder_compiler_receipt_sha256: '5'.repeat(64), builder_graph_explicit: false, authority_granted_by_builder: false, host_authority_retained: true, created: true, ...overrides
  };
  if (kind === 'workflow') return {
    schema_version: 'px.workflow-revision-receipt/1.2', operation: 'workflow.save_revision', created_utc: '2026-08-17T00:00:00.000Z', workflow_id: payload.workflow_id, version: payload.version,
    revision_sha256: '6'.repeat(64), definition_sha256: '7'.repeat(64), definition_state: 'saved', runnable_state: 'unvalidated', run_state: 'never_run', path: 'workflows/demo/record.json',
    authority_state: 'none', authority_definition_path: null, editor_layout_state: 'content-bound', editor_layout_path: 'workflows/demo/editor-layout.json', editor_layout_sha256: '8'.repeat(64),
    host_authority_retained: true, created: true, ...overrides
  };
  const original = payload.provenance?.preserved_original_schema_version ? {
    schema_version: payload.provenance.preserved_original_schema_version,
    skill_id: payload.provenance.preserved_original_skill_id,
    source_version: payload.provenance.preserved_original_source_version,
    origin: payload.provenance.preserved_original_origin,
    package_relative: payload.provenance.preserved_original_package_relative,
    tree_sha256: payload.provenance.preserved_original_tree_sha256,
    body_sha256: payload.provenance.preserved_original_body_sha256,
    file_count: Number(payload.provenance.preserved_original_file_count)
  } : null;
  return {
    schema_version: 'px.skill-draft/1.1', manifest: { skill_id: payload.skill_id, version: payload.version },
    manifest_sha256: crypto.createHash('sha256').update(canonicalTrustJson({ skill_id: payload.skill_id, version: payload.version }), 'utf8').digest('hex'),
    source_tree_sha256: materialized.treeSha256, source_authority_token: payload.source_token, files: materialized.materialization.files, file_count: materialized.fileCount,
    payload_root: 'payload', draft_state: 'saved', admission_state: 'unadmitted', promotion_state: 'not_promoted', created: true,
    ...(original ? { preserved_original: original } : {}), ...overrides
  };
}

function harness(overrides = {}) {
  const posts = [];
  const calls = [];
  let latestMaterialized = null;
  const bridge = {
    projectRoot: 'C:/project',
    async nextStudioVersion(...args) { calls.push(['next', ...args]); return allocation({ observed_utc: '2026-08-17T00:00:01.000Z' }); },
    async issueStudioApproval(...args) { calls.push(['approve', ...args]); return { approval_capability: 'capability' }; },
    async studioOperation(...args) { calls.push(['operation', ...args]); return { schema_version: 'px.skill-source-admission/1.0', source_directory: args[2].source_directory, source_token: 'token', source_tree_sha256: args[2].expected_tree_sha256, file_count: args[2].expected_file_count }; },
    async createStudioDraft(...args) { calls.push(['create', ...args]); return createReceipt(args[0], args[1], latestMaterialized); },
    ...overrides.bridge
  };
  return {
    posts,
    calls,
    bridge,
    dependencies: {
      bridge,
      async postMessage(message) { posts.push(message); return overrides.deliveryResult; },
      async confirmCreate() { return overrides.confirmCreate ?? true; },
      materializeSkillPackage(projectRoot, payload) {
        calls.push(['materialize', projectRoot, payload]); const normalized = normalizeFiles(payload.editor_files || {});
        latestMaterialized = { sourceDirectory: process.cwd(), treeSha256: EDITOR_TREE_SHA256, fileCount: normalized.length, reused: false };
        latestMaterialized.materialization = { schema_version: 'px.studio-package-materialization/1.0', operation_id: '123e4567-e89b-12d3-a456-426614174000', source_directory: process.cwd(), resource_relative: 'fixture', tree_sha256: latestMaterialized.treeSha256, file_count: latestMaterialized.fileCount, files: fileInventory(normalized), reused: false };
        return latestMaterialized;
      },
      afterCommit: overrides.afterCommit,
      reportPostCommitWarning: overrides.reportPostCommitWarning,
      allocationOwner: TRUST_OWNER,
      async assertVersionAllocation(token, _kind, _allocation, owner) { if (token !== 'version-allocation:proof' || owner !== TRUST_OWNER) throw new Error('invalid proof'); },
      async consumeVersionAllocation(token, _kind, _allocation, owner) { if (token !== 'version-allocation:proof' || owner !== TRUST_OWNER) throw new Error('invalid proof'); },
      async registerVersionAllocation(_kind, _allocation, owner) { if (owner !== TRUST_OWNER) throw new Error('invalid owner'); return 'version-allocation:fresh'; },
      async resolveVersionAllocationSourceSelection() { return overrides.allocationSourceSelection || null; },
      async reauthenticateVersionAllocationSourceSelection(selection) { return selection; },
      async assertInitialCreateAbsent(kind, identity) { return { schema_version: 'px.studio-identity-absence/1.0', kind, identity, absent: true, observed_utc: '2026-08-17T00:00:00.000Z' }; },
      async reclaimSkillPackage() { return { reclaimed: true }; },
      isVersionConflict: exactStudioVersionConflictError,
      ...overrides.dependencies
    },
    setLatestMaterialized(value) { latestMaterialized = value; }
  };
}

test('host seam revalidates a predecessor allocation immediately before approval and immutable create', async () => {
  const run = harness();
  const supplied = allocation();
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:agent-1', kind: 'agent', payload: { agent_id: 'agent:demo', version: '1.0.1', version_allocation: supplied, version_allocation_proof: 'version-allocation:proof' } }, run.dependencies);
  assert.equal(outcome.status, 'created');
  assert.deepEqual(run.calls[0], ['next', 'agent', 'agent:demo', '1.0.0', 'studio-physical', 'a'.repeat(64), 'b'.repeat(64)]);
  const create = run.calls.find(call => call[0] === 'create');
  assert.equal(create[1], 'agent');
  assert.equal(create[2].version_allocation.observed_utc, '2026-08-17T00:00:01.000Z');
  assert.equal(create[2].approval_capability, 'capability');
  assert.equal(run.posts[0].type, 'studioDraftResult');
  assert.equal(run.posts[0].outcome, 'created');
  assert.equal(run.posts[0].result.agent_id, 'agent:demo');
});

test('host seam refuses a stale allocation before prompting or creating', async () => {
  let prompted = false;
  const run = harness({ bridge: { async nextStudioVersion() { return allocation({ occupied_versions_sha256: 'd'.repeat(64), candidate_version: '1.0.2' }); } } });
  run.dependencies.confirmCreate = async () => { prompted = true; return true; };
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:stale', kind: 'agent', payload: { agent_id: 'agent:demo', version: '1.0.1', version_allocation: allocation(), version_allocation_proof: 'version-allocation:proof' } }, run.dependencies);
  assert.equal(outcome.status, 'conflict');
  assert.equal(prompted, false);
  assert.equal(run.calls.some(call => call[0] === 'create'), false);
  assert.equal(run.posts[0].type, 'studioVersionConflict');
  assert.equal(run.posts[0].allocation.candidate_version, '1.0.2');
});

test('host seam emits a correlated cancellation when create approval is declined', async () => {
  const run = harness({ confirmCreate: false });
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:cancel', kind: 'workflow', payload: { workflow_id: 'workflow:demo', version: '1.0.0' } }, run.dependencies);
  assert.equal(outcome.status, 'cancelled');
  assert.deepEqual(run.posts, [{ type: 'studioDraftCancelled', requestId: 'studio-save:cancel', kind: 'workflow' }]);
  assert.equal(run.calls.length, 0);
});

test('host seam refuses an unbound legacy skill source instead of opening a folder picker', async () => {
  const run = harness();
  await assert.rejects(createStudioDraftFromHost({ requestId: 'studio-save:no-source', kind: 'skill', payload: { skill_id: 'skill:demo', version: '1.0.0' } }, run.dependencies), /studio-skill-editor-files-required/);
  assert.equal(run.calls.length, 0);
});

test('host seam materializes, admits, and strips editor files before skill create', async () => {
  const run = harness();
  const editorFiles = { 'SKILL.md': '# Skill\n', 'capability.json': '{"domain":"px-standard"}\n', 'skill.yaml': 'id: skill:demo\ndomain: px-standard\n' };
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:skill', kind: 'skill', payload: { skill_id: 'skill:demo', version: '1.0.0', editor_files: editorFiles } }, run.dependencies);
  assert.equal(outcome.status, 'created');
  assert.equal(run.calls[0][0], 'materialize');
  const admission = run.calls.find(call => call[0] === 'operation');
  assert.deepEqual(admission.slice(1, 3), ['skill', 'admit-source']);
  assert.equal(admission[3].expected_tree_sha256, EDITOR_TREE_SHA256);
  assert.equal(admission[3].expected_file_count, 3);
  const create = run.calls.find(call => call[0] === 'create');
  assert.equal(Object.hasOwn(create[2], 'editor_files'), false);
  assert.equal(create[2].source_directory, process.cwd());
  assert.equal(create[2].source_token, 'token');
});

test('real package materializer receipt remains exact through host source admission', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-host-materializer-')); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const run = harness(); run.bridge.projectRoot = root; run.dependencies.materializeSkillPackage = (...args) => { const value = materializeSkillPackage(...args); run.setLatestMaterialized(value); return value; };
  const editor_files = { 'SKILL.md': '# Exact\n', 'capability.json': '{"id":"skill:exact","version":"1.0.0","domain":"px-standard"}\n', 'skill.yaml': 'id: skill:exact\nversion: 1.0.0\ndomain: px-standard\n' };
  const expected = digestFiles(normalizeFiles(editor_files));
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:real-materializer', kind: 'skill', payload: { skill_id: 'skill:exact', version: '1.0.0', editor_files } }, run.dependencies);
  assert.equal(outcome.status, 'created');
  const admission = run.calls.find(call => call[0] === 'operation');
  assert.equal(admission[3].expected_tree_sha256, expected);
  assert.equal(admission[3].expected_file_count, 3);
  assert.equal(fs.readFileSync(path.join(admission[3].source_directory, 'SKILL.md'), 'utf8'), '# Exact\n');
});

test('host seam refuses an admission receipt that does not match the approved editor tree', async () => {
  const run = harness({ bridge: { async studioOperation() { return { schema_version: 'px.skill-source-admission/1.0', source_directory: 'C:/admitted', source_token: 'token', source_tree_sha256: 'f'.repeat(64), file_count: 3 }; } } });
  const editor_files = { 'SKILL.md': '# Skill\n', 'capability.json': '{"domain":"px-standard"}\n', 'skill.yaml': 'id: skill:demo\ndomain: px-standard\n' };
  await assert.rejects(createStudioDraftFromHost({ requestId: 'studio-save:tamper', kind: 'skill', payload: { skill_id: 'skill:demo', version: '1.0.0', editor_files } }, run.dependencies), /studio-skill-source-admission-receipt-mismatch/);
  assert.equal(run.calls.some(call => call[0] === 'create'), false);
});

test('allocated physical skill preserves its exact allocation through materialize, admit, and create', async () => {
  const supplied = allocation({ kind: 'skill', identity: 'skill:demo' });
  const run = harness({ bridge: { async nextStudioVersion() { return { ...supplied, observed_utc: '2026-08-17T00:00:01.000Z' }; } } });
  const editor_files = { 'SKILL.md': '# Skill\n', 'capability.json': '{"domain":"px-standard"}\n', 'skill.yaml': 'id: skill:demo\ndomain: px-standard\n' };
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:allocated-skill', kind: 'skill', payload: { skill_id: 'skill:demo', version: '1.0.1', version_allocation: supplied, version_allocation_proof: 'version-allocation:proof', editor_files } }, run.dependencies);
  assert.equal(outcome.status, 'created');
  const create = run.calls.find(call => call[0] === 'create');
  assert.equal(create[2].version_allocation.kind, 'skill');
  assert.equal(create[2].version_allocation.identity, 'skill:demo');
  assert.equal(create[2].version_allocation.source_content_sha256, 'b'.repeat(64));
});

test('host seam returns a fresh correlated allocation after a publication collision', async () => {
  let allocationCalls = 0;
  const run = harness({ bridge: {
    async nextStudioVersion() { allocationCalls += 1; return allocationCalls === 1 ? allocation({ observed_utc: '2026-08-17T00:00:01.000Z' }) : allocation({ candidate_version: '1.0.2', occupied_versions_sha256: 'd'.repeat(64), observed_utc: '2026-08-17T00:00:02.000Z' }); },
    async createStudioDraft() { throw studioProcessError(JSON.stringify({ schema_version: 'px.studio-operation-error/1.0', code: 'STUDIO_VERSION_CONFLICT', reason: 'publication-collision' }), 2); }
  } });
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:collision', kind: 'agent', payload: { agent_id: 'agent:demo', version: '1.0.1', version_allocation: allocation(), version_allocation_proof: 'version-allocation:proof' } }, run.dependencies);
  assert.equal(outcome.status, 'conflict');
  assert.equal(allocationCalls, 2);
  assert.equal(run.posts[0].requestId, 'studio-save:collision');
  assert.equal(run.posts[0].allocation.candidate_version, '1.0.2');
});

test('host seam never recovers a lookalike conflict code without the exact envelope', async () => {
  let allocationCalls = 0;
  const run = harness({ bridge: {
    async nextStudioVersion() { allocationCalls += 1; return allocation(); },
    async createStudioDraft() { const error = new Error('studio-version-conflict:publication-collision'); error.code = 'STUDIO_VERSION_CONFLICT'; error.reason = 'publication-collision'; throw error; }
  } });
  await assert.rejects(
    createStudioDraftFromHost({ requestId: 'studio-save:lookalike', kind: 'agent', payload: { agent_id: 'agent:demo', version: '1.0.1', version_allocation: allocation(), version_allocation_proof: 'version-allocation:proof' } }, run.dependencies),
    error => error.code === 'STUDIO_VERSION_CONFLICT' && !error.studioError
  );
  assert.equal(allocationCalls, 1);
  assert.equal(run.posts.length, 0);
});

test('allocation binding intentionally ignores only observation time', () => {
  assert.equal(sameAllocationBinding(allocation(), allocation({ observed_utc: '2026-08-17T00:01:00.000Z' })), true);
  assert.equal(sameAllocationBinding(allocation(), allocation({ source_content_sha256: 'd'.repeat(64) })), false);
});

test('fresh allocation validation requires the exact envelope and a real canonical UTC instant', () => {
  assert.equal(exactAllocationEnvelope(allocation()), true);
  assert.equal(exactAllocationEnvelope({ ...allocation(), extra: true }), false);
  assert.equal(exactAllocationEnvelope(allocation({ observed_utc: '2026-02-31T00:00:00.000Z' })), false);
  for (const source_scope of ['', 'physical-ish', null]) assert.equal(exactAllocationEnvelope(allocation({ source_scope })), false);
  assert.equal(exactAllocationEnvelope(allocation({ kind: 'agent', source_scope: 'external-authenticated' })), false);
  for (const key of ['source_revision_sha256', 'source_content_sha256', 'occupied_versions_sha256']) {
    assert.equal(exactAllocationEnvelope(allocation({ [key]: 'A'.repeat(64) })), false);
    assert.equal(exactAllocationEnvelope(allocation({ [key]: 'a'.repeat(63) })), false);
    assert.equal(exactAllocationEnvelope(allocation({ [key]: 7 })), false);
  }
  const missingScope = allocation(); delete missingScope.source_scope;
  assert.equal(exactAllocationEnvelope(missingScope), false);
  assert.equal(validCanonicalUtc('2026-08-17T00:00:00Z'), true);
  assert.equal(validCanonicalUtc('2026-08-17T00:00:00.000Z'), true);
  assert.equal(validCanonicalUtc('2026-08-17T00:00:00.00Z'), false);
  assert.equal(validCanonicalUtc('0000-01-01T00:00:00.000Z'), false);
});

test('post-commit delivery and refresh failures cannot turn a committed create into a create failure', async () => {
  const warnings = [];
  const run = harness({ deliveryResult: false, async afterCommit() { throw new Error('refresh unavailable'); }, async reportPostCommitWarning(receipt) { warnings.push(receipt); } });
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:committed', kind: 'workflow', payload: { workflow_id: 'workflow:demo', version: '1.0.0' } }, run.dependencies);
  assert.equal(outcome.status, 'created-with-delivery-warning');
  assert.equal(outcome.result.created, true);
  assert.deepEqual(outcome.warnings, ['studio-draft-result-not-delivered', 'studio-draft-postcommit-refresh-failed:refresh unavailable']);
  assert.equal(warnings.length, 1);
});

test('post-commit delivery exceptions are retained as warnings rather than rethrown', async () => {
  const run = harness();
  run.dependencies.postMessage = async () => { throw new Error('webview disposed'); };
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:disposed', kind: 'agent', payload: { agent_id: 'agent:demo', version: '1.0.0' } }, run.dependencies);
  assert.equal(outcome.status, 'created-with-delivery-warning');
  assert.deepEqual(outcome.warnings, ['studio-draft-result-delivery-failed:webview disposed']);
});

test('host seam rejects a candidate that is not bound to its supplied allocation', async () => {
  const run = harness();
  await assert.rejects(
    createStudioDraftFromHost({ requestId: 'studio-save:misbound', kind: 'agent', payload: { agent_id: 'agent:other', version: '1.0.1', version_allocation: allocation(), version_allocation_proof: 'version-allocation:proof' } }, run.dependencies),
    /studio-version-allocation-payload-binding-mismatch/
  );
  assert.equal(run.calls.length, 0);
  assert.equal(run.posts.length, 0);
});

test('host trust registry is exact, expiring, capacity bounded, and consumes allocation proofs once', () => {
  let clock = 1000; let sequence = 0;
  const trust = createStudioTrustRegistry({ limit: 1, perOriginLimit: 1, ttlMs: 10, now: () => clock, randomUUID: () => `token-${++sequence}` });
  const selection = sourceSelection();
  const selectionId = trust.registerSourceSelection(selection, TRUST_OWNER);
  assert.deepEqual(trust.resolveSourceSelectionToken(selectionId, TRUST_OWNER), selection);
  assert.deepEqual(trust.sourceSelectionOwner(selectionId, TRUST_OWNER.originId), TRUST_OWNER);
  assert.throws(() => trust.registerSourceSelection(sourceSelection({ identity: 'skill:other' }), { ...TRUST_OWNER, requestId: 'allocation:other' }), /capacity-exceeded/);
  assert.deepEqual(trust.consumeSourceSelectionToken(selectionId, TRUST_OWNER), selection);
  assert.throws(() => trust.resolveSourceSelectionToken(selectionId, TRUST_OWNER), /invalid-or-expired/);
  const expiringSelectionId = trust.registerSourceSelection(selection, TRUST_OWNER);
  clock += 11;
  assert.throws(() => trust.resolveSourceSelectionToken(expiringSelectionId, TRUST_OWNER), /invalid-or-expired/);
  const proof = trust.registerVersionAllocation('agent', allocation(), TRUST_OWNER);
  assert.deepEqual(trust.assertVersionAllocation(proof, 'agent', allocation(), TRUST_OWNER).allocation, allocation());
  assert.deepEqual(trust.versionAllocationOwner(proof, TRUST_OWNER.originId), TRUST_OWNER);
  assert.throws(() => trust.releaseVersionAllocation(proof, { originId: 'panel:other', requestId: TRUST_OWNER.requestId }), /owner-mismatch/);
  trust.consumeVersionAllocation(proof, 'agent', allocation(), TRUST_OWNER);
  assert.throws(() => trust.assertVersionAllocation(proof, 'agent', allocation(), TRUST_OWNER), /invalid-or-expired/);
});

test('allocation lineage retains exact preserved-original selection and rejects substitution', () => {
  let sequence = 0;
  const trust = createStudioTrustRegistry({ randomUUID: () => `lineage-${++sequence}` });
  const external = allocation({ kind: 'skill', identity: 'skill:demo', source_scope: 'external-authenticated' });
  const selection = sourceSelection({ backup_provenance: preservedOriginal() });
  const proof = trust.registerVersionAllocation('skill', external, TRUST_OWNER, selection);
  assert.deepEqual(trust.resolveVersionAllocationSourceSelection(proof, TRUST_OWNER), selection);
  assert.throws(
    () => trust.registerVersionAllocation('skill', external, { ...TRUST_OWNER, requestId: 'allocation:substituted' }, sourceSelection({ source_content_sha256: '9'.repeat(64) })),
    /source-selection-mismatch/
  );
  trust.consumeVersionAllocation(proof, 'skill', external, TRUST_OWNER);
  assert.throws(() => trust.resolveVersionAllocationSourceSelection(proof, TRUST_OWNER), /invalid-or-expired/);
});

test('external skill create reauthenticates preserved-original lineage and overwrites reserved caller claims', async () => {
  const original = preservedOriginal();
  const selection = sourceSelection({ backup_provenance: original });
  const external = allocation({ kind: 'skill', identity: 'skill:demo', source_scope: 'external-authenticated' });
  let reauthenticated = 0;
  const run = harness({
    allocationSourceSelection: selection,
    bridge: { async nextStudioVersion() { return { ...external, observed_utc: '2026-08-17T00:00:01.000Z' }; } },
    dependencies: { async reauthenticateVersionAllocationSourceSelection(value) { reauthenticated += 1; return structuredClone(value); } }
  });
  const editor_files = { 'SKILL.md': '# Skill\n', 'capability.json': '{"domain":"px-standard"}\n', 'skill.yaml': 'id: skill:demo\ndomain: px-standard\n' };
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:external-lineage', kind: 'skill', payload: {
    skill_id: 'skill:demo', version: '1.0.1', version_allocation: external, version_allocation_proof: 'version-allocation:proof', editor_files,
    provenance: { source: 'editor', preserved_original_tree_sha256: '0'.repeat(64) }
  } }, run.dependencies);
  assert.equal(outcome.status, 'created');
  assert.equal(reauthenticated, 1);
  const create = run.calls.find(call => call[0] === 'create');
  assert.equal(create[2].provenance.source, 'editor');
  assert.equal(create[2].provenance.preserved_original_tree_sha256, original.tree_sha256);
  assert.deepEqual(outcome.result.preserved_original, original);
});

test('external skill create fails before materialization when preserved-original reauthentication changes', async () => {
  const selection = sourceSelection({ backup_provenance: preservedOriginal() });
  const external = allocation({ kind: 'skill', identity: 'skill:demo', source_scope: 'external-authenticated' });
  const run = harness({
    allocationSourceSelection: selection,
    bridge: { async nextStudioVersion() { return { ...external, observed_utc: '2026-08-17T00:00:01.000Z' }; } },
    dependencies: { async reauthenticateVersionAllocationSourceSelection(value) { return { ...value, backup_provenance: { ...value.backup_provenance, tree_sha256: '9'.repeat(64) } }; } }
  });
  const editor_files = { 'SKILL.md': '# Skill\n', 'capability.json': '{"domain":"px-standard"}\n', 'skill.yaml': 'id: skill:demo\ndomain: px-standard\n' };
  await assert.rejects(
    createStudioDraftFromHost({ requestId: 'studio-save:external-lineage-changed', kind: 'skill', payload: { skill_id: 'skill:demo', version: '1.0.1', version_allocation: external, version_allocation_proof: 'version-allocation:proof', editor_files } }, run.dependencies),
    /studio-external-skill-lineage-changed/
  );
  assert.equal(run.calls.some(call => call[0] === 'materialize'), false);
});

test('source selection accepts the canonical version-qualified Studio record ID and rejects path syntax', () => {
  let sequence = 0; const trust = createStudioTrustRegistry({ randomUUID: () => `record-${++sequence}` });
  const owner = { originId: 'panel:record', requestId: 'package:record' };
  const token = trust.registerSourceSelection(sourceSelection({ record_id: 'studio:skill:demo@1.0.0', source_scope: 'studio-physical', source_origin: 'project-studio', package_scope: 'project-studio', package_path: '.engineering-bootstrap/studios/skills/demo/revisions/1.0.0/payload', source_content_sha256: 'c'.repeat(64), tree_sha256: 'b'.repeat(64) }), owner);
  assert.match(token, /^source-selection:/);
  assert.throws(() => trust.registerSourceSelection(sourceSelection({ record_id: 'studio/skill/demo@1.0.0' }), { ...owner, requestId: 'package:bad-record' }), /source-selection-invalid/);
});

test('malformed resolved create receipt is reported as an unverified durable outcome and not success', async () => {
  const run = harness({ bridge: { async createStudioDraft() { return { created: true }; } } });
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:bad-receipt', kind: 'agent', payload: { agent_id: 'agent:demo', version: '1.0.0' } }, run.dependencies);
  assert.equal(outcome.status, 'commit-outcome-unverified');
  assert.equal(outcome.result, null);
  assert.equal(run.posts[0].type, 'studioDraftOutcomeUnverified');
  assert.equal(run.posts.some(message => message.type === 'studioDraftResult'), false);
});

test('strict trust serialization rejects undefined, non-finite, cyclic, and non-plain values', () => {
  assert.throws(() => canonicalTrustJson([undefined]), /not-json/);
  assert.throws(() => canonicalTrustJson({ value: Number.NaN }), /not-json/);
  assert.throws(() => canonicalTrustJson({ value: '\ud800' }), /not-json/);
  const cyclic = {}; cyclic.self = cyclic; assert.throws(() => canonicalTrustJson(cyclic), /not-json/);
  assert.throws(() => canonicalTrustJson(new Date()), /plain-json/);
  assert.throws(() => canonicalTrustJson(Array(1)), /not-json/);
  const accessor = {}; Object.defineProperty(accessor, 'value', { enumerable: true, get() { return 'not-data'; } });
  assert.throws(() => canonicalTrustJson(accessor), /not-json/);
  assert.equal(canonicalTrustJson({ b: 2, a: [true, null] }), '{"a":[true,null],"b":2}');
});

test('trust release and disposal require the exact originating panel and issuance request', () => {
  let sequence = 0; const trust = createStudioTrustRegistry({ limit: 4, perOriginLimit: 2, randomUUID: () => `release-${++sequence}` });
  const firstOwner = { originId: 'panel:one', requestId: 'package:one' }; const secondOwner = { originId: 'panel:one', requestId: 'package:two' };
  const first = trust.registerSourceSelection(sourceSelection(), firstOwner);
  const second = trust.registerSourceSelection(sourceSelection({ record_id: 'skill:two', identity: 'skill:two' }), secondOwner);
  assert.throws(() => trust.registerSourceSelection(sourceSelection({ record_id: 'skill:three', identity: 'skill:three' }), { originId: 'panel:one', requestId: 'package:three' }), /origin-capacity/);
  assert.throws(() => trust.releaseSourceSelection(first, secondOwner), /owner-mismatch/);
  assert.equal(trust.releaseSourceSelection(first, firstOwner), true);
  assert.equal(trust.disposeOrigin('panel:one'), 1);
  assert.throws(() => trust.resolveSourceSelectionToken(second, secondOwner), /invalid-or-expired/);
});

test('trust capacity and per-origin quotas apply across source and allocation registries', () => {
  let sequence = 0; const trust = createStudioTrustRegistry({ limit: 2, perOriginLimit: 1, randomUUID: () => `combined-${++sequence}` });
  trust.registerSourceSelection(sourceSelection(), { originId: 'panel:one', requestId: 'package:one' });
  assert.throws(() => trust.registerVersionAllocation('agent', allocation(), { originId: 'panel:one', requestId: 'allocation:one' }), /origin-capacity/);
  trust.registerVersionAllocation('agent', allocation(), { originId: 'panel:two', requestId: 'allocation:two' });
  assert.equal(trust.diagnostics().total, 2);
  assert.throws(() => trust.registerSourceSelection(sourceSelection({ identity: 'skill:three', record_id: 'skill:three' }), { originId: 'panel:three', requestId: 'package:three' }), /capacity/);
});

test('exact recovered replay is distinguished from creation and created false alone is unverified', async () => {
  const recovered = harness({ bridge: { async createStudioDraft(kind, payload) { return createReceipt(kind, payload, null, { created: false, idempotent_replay: true }); } } });
  const recoveredOutcome = await createStudioDraftFromHost({ requestId: 'studio-save:recovered', kind: 'agent', payload: { agent_id: 'agent:demo', version: '1.0.0' } }, recovered.dependencies);
  assert.equal(recoveredOutcome.status, 'recovered'); assert.equal(recovered.posts[0].outcome, 'recovered');
  const invalid = harness({ bridge: { async createStudioDraft(kind, payload) { return createReceipt(kind, payload, null, { created: false }); } } });
  const invalidOutcome = await createStudioDraftFromHost({ requestId: 'studio-save:false', kind: 'agent', payload: { agent_id: 'agent:demo', version: '1.0.0' } }, invalid.dependencies);
  assert.equal(invalidOutcome.status, 'commit-outcome-unverified');
});

test('skill receipt must match the admitted source token, tree, file count, and file inventory', async () => {
  const editor_files = { 'SKILL.md': '# Skill\n', 'capability.json': '{"domain":"px-standard"}\n', 'skill.yaml': 'id: skill:demo\ndomain: px-standard\n' };
  for (const corrupt of ['token', 'tree', 'files']) {
    const run = harness({ bridge: { async createStudioDraft(kind, payload) {
      const current = run.calls.find(call => call[0] === 'materialize');
      const normalized = normalizeFiles(current[2].editor_files); const materialized = { treeSha256: EDITOR_TREE_SHA256, fileCount: normalized.length, materialization: { files: fileInventory(normalized) } };
      const receipt = createReceipt(kind, payload, materialized);
      if (corrupt === 'token') receipt.source_authority_token = 'other-token';
      if (corrupt === 'tree') receipt.source_tree_sha256 = 'f'.repeat(64);
      if (corrupt === 'files') receipt.files = receipt.files.map((row, index) => index ? row : { ...row, sha256: 'f'.repeat(64) });
      return receipt;
    } } });
    const outcome = await createStudioDraftFromHost({ requestId: `studio-save:skill-${corrupt}`, kind: 'skill', payload: { skill_id: 'skill:demo', version: '1.0.0', editor_files } }, run.dependencies);
    assert.equal(outcome.status, 'commit-outcome-unverified', corrupt);
  }
});

test('proofless initial create requires two exact absence observations and initial version 1.0.0', async () => {
  let observations = 0; const run = harness({ dependencies: { async assertInitialCreateAbsent(kind, identity) { observations += 1; return { schema_version: 'px.studio-identity-absence/1.0', kind, identity, absent: observations < 2, observed_utc: '2026-08-17T00:00:00.000Z' }; } } });
  await assert.rejects(createStudioDraftFromHost({ requestId: 'studio-save:race', kind: 'agent', payload: { agent_id: 'agent:demo', version: '1.0.0' } }, run.dependencies), /absence-receipt-stale/);
  assert.equal(run.calls.some(call => call[0] === 'create'), false);
  const nonInitial = harness();
  await assert.rejects(createStudioDraftFromHost({ requestId: 'studio-save:noninitial', kind: 'agent', payload: { agent_id: 'agent:new', version: '2.0.0' } }, nonInitial.dependencies), /absence-proof-required/);
});

test('standard skill host boundary rejects absent or restricted package domains before materialization', async () => {
  for (const editor_files of [
    { 'SKILL.md': '# Skill\n', 'capability.json': '{}', 'skill.yaml': 'domain: px-standard\n' },
    { 'SKILL.md': '# Skill\n', 'capability.json': '{"domain":"px-standard","credential_namespace":"microsoft:graph"}', 'skill.yaml': 'domain: px-standard\n' },
    { 'SKILL.md': '# Skill\n', 'capability.json': '{"domain":"px-standard","credential_namespaces":["azure:key-vault"]}', 'skill.yaml': 'domain: px-standard\n' },
    { 'SKILL.md': '# Skill\n', 'capability.json': '{"domain":"px-standard"}', 'skill.yaml': 'domain: enterprise-restricted\n' }
  ]) {
    const run = harness();
    await assert.rejects(createStudioDraftFromHost({ requestId: 'studio-save:domain', kind: 'skill', payload: { skill_id: 'skill:demo', version: '1.0.0', editor_files } }, run.dependencies), /domain|required|restricted/);
    assert.equal(run.calls.length, 0);
  }
});

test('skill materialization and durable receipts are exact, not shape-compatible', async () => {
  const editor_files = { 'SKILL.md': '# Skill\n', 'capability.json': '{"domain":"px-standard"}\n', 'skill.yaml': 'id: skill:demo\ndomain: px-standard\n' };
  const malformedMaterialization = harness({ dependencies: { materializeSkillPackage(_projectRoot, payload) {
    const normalized = normalizeFiles(payload.editor_files); const value = { sourceDirectory: process.cwd(), treeSha256: EDITOR_TREE_SHA256, fileCount: normalized.length, reused: false };
    value.materialization = { schema_version: 'px.studio-package-materialization/1.0', operation_id: '123e4567-e89b-12d3-a456-426614174000', source_directory: process.cwd(), resource_relative: 'fixture', tree_sha256: value.treeSha256, file_count: value.fileCount, files: fileInventory(normalized), reused: false, extra: true };
    return value;
  } } });
  await assert.rejects(createStudioDraftFromHost({ requestId: 'studio-save:materialization-extra', kind: 'skill', payload: { skill_id: 'skill:demo', version: '1.0.0', editor_files } }, malformedMaterialization.dependencies), /materialization-receipt-invalid/);

  const extraReceipt = harness({ bridge: { async createStudioDraft(kind, payload) { return createReceipt(kind, payload, null, { unexpected: true }); } } });
  const outcome = await createStudioDraftFromHost({ requestId: 'studio-save:receipt-extra', kind: 'agent', payload: { agent_id: 'agent:demo', version: '1.0.0' } }, extraReceipt.dependencies);
  assert.equal(outcome.status, 'commit-outcome-unverified');
});

test('create dispatch remains bound to its originating webview instance', async () => {
  const first = []; const second = [];
  const firstRun = harness(); const secondRun = harness();
  await Promise.all([
    dispatchStudioCreateMessage(
      { type: 'createStudioDraft', requestId: 'studio-save:first-origin', kind: 'workflow', payload: { workflow_id: 'workflow:first', version: '1.0.0' } },
      { ...firstRun.dependencies, validateMessage: value => value, originWebview: { async postMessage(message) { first.push(message); return true; } } }
    ),
    dispatchStudioCreateMessage(
      { type: 'createStudioDraft', requestId: 'studio-save:second-origin', kind: 'agent', payload: { agent_id: 'agent:second', version: '1.0.0' } },
      { ...secondRun.dependencies, validateMessage: value => value, originWebview: { async postMessage(message) { second.push(message); return true; } } }
    )
  ]);
  assert.deepEqual(first.map(message => message.requestId), ['studio-save:first-origin']);
  assert.deepEqual(second.map(message => message.requestId), ['studio-save:second-origin']);
  assert.equal(first[0].kind, 'workflow'); assert.equal(second[0].kind, 'agent');
});
