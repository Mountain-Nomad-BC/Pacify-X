'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { PxBridge, STUDIO_VERSION_CONFLICT_REASONS, captureJson, exactStudioVersionConflictError, snapshotSourceFingerprint, snapshotSourceWatchStamp, studioProcessError } = require('../src/pxBridge');
const { generateApprovalKey } = require('../src/studioApprovalHost');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-bridge-cache-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, 'runtime'), { recursive: true });
  fs.mkdirSync(path.join(root, 'registry'), { recursive: true });
  fs.writeFileSync(path.join(root, 'runtime', 'dashboard_api.py'), '# fixture\n');
  fs.writeFileSync(path.join(root, 'registry', 'tools.json'), '{"tools":[]}\n');
  return root;
}

function raw(revision) {
  return { schema_version: '2.0.0', generated_at: `2026-08-11T00:00:0${revision}Z`, connected: true, mode: 'canonical-dashboard-api', source: { root: 'fixture', version: '1.0.0' }, counts: {}, project: {}, attention: [], providerActivity: [{ providerId: 'p', requestCount: revision }], runtime: {}, memory: {}, coordination: {}, readiness: {}, enterprise: {} };
}

test('snapshot cache uses source fingerprints, TTL, and stale-while-revalidate', async t => {
  const root = fixture(t); let now = 1000; let executions = 0;
  const bridge = new PxBridge({ engineRoot: root, projectRoot: root, cacheTtlMs: 5000, now: () => now, capture: async () => raw(++executions) });
  const first = await bridge.snapshot();
  assert.equal(first.cache.status, 'miss'); assert.equal(executions, 1); assert.equal(first.providerActivity[0].requestCount, 1);
  const hit = await bridge.snapshot();
  assert.equal(hit.cache.status, 'hit'); assert.equal(executions, 1);
  now += 5001;
  const stale = await bridge.snapshot();
  assert.equal(stale.cache.status, 'stale-hit'); assert.equal(stale.cache.refresh_pending, true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(executions, 2);
  const refreshed = await bridge.snapshot();
  assert.equal(refreshed.cache.status, 'hit'); assert.equal(refreshed.providerActivity[0].requestCount, 2);
  fs.writeFileSync(path.join(root, 'registry', 'tools.json'), '{"tools":[{"id":"changed"}]}\n');
  const changed = await bridge.snapshot();
  assert.equal(changed.cache.status, 'miss'); assert.equal(changed.cache.invalidation_reason, 'source-fingerprint-changed'); assert.equal(executions, 3);
  bridge.dispose();
});

test('ten forced equivalent snapshots coalesce into one governed execution', async t => {
  const root = fixture(t); let executions = 0; let release;
  const gate = new Promise(resolve => { release = resolve; });
  const bridge = new PxBridge({ engineRoot: root, projectRoot: root, capture: async () => { executions += 1; await gate; return raw(executions); } });
  const requests = Array.from({ length: 10 }, () => bridge.snapshot({ force: true, reason: 'test-force' }));
  for (let attempt = 0; attempt < 100 && executions === 0; attempt += 1) await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(executions, 1); release(); await Promise.all(requests);
  assert.equal(bridge.diagnostics().governor.metrics.joins, 9);
  bridge.dispose();
});

test('source fingerprinting yields the host event loop and closes its worker', async t => {
  const root = fixture(t); let executions = 0; let eventLoopAdvanced = false;
  const bridge = new PxBridge({ engineRoot: root, projectRoot: root, capture: async () => raw(++executions) });
  const snapshot = bridge.snapshot();
  await new Promise(resolve => setImmediate(() => { eventLoopAdvanced = true; resolve(); }));
  assert.equal(eventLoopAdvanced, true);
  assert.equal((await snapshot).cache.status, 'miss');
  assert.equal(bridge.diagnostics().source_fingerprint.active_workers, 0);
  bridge.dispose();
});

test('snapshot fingerprint is bounded and changes only when watched inputs change', t => {
  const root = fixture(t);
  const before = snapshotSourceFingerprint(root, root);
  const stampBefore = snapshotSourceWatchStamp(root, root);
  fs.writeFileSync(path.join(root, 'unrelated.txt'), 'not watched');
  assert.equal(snapshotSourceFingerprint(root, root), before);
  assert.equal(snapshotSourceWatchStamp(root, root), stampBefore);
  fs.writeFileSync(path.join(root, 'registry', 'tools.json'), '{"tools":[1]}');
  assert.notEqual(snapshotSourceFingerprint(root, root), before);
  assert.notEqual(snapshotSourceWatchStamp(root, root), stampBefore);
});

test('next refresh observes a watched same-size write without waiting one second', async t => {
  const root = fixture(t); const now = 4242; let executions = 0;
  const bridge = new PxBridge({
    engineRoot: root,
    projectRoot: root,
    cacheTtlMs: 5000,
    now: () => now,
    capture: async () => raw(++executions)
  });
  assert.equal((await bridge.snapshot()).cache.status, 'miss');
  assert.equal((await bridge.snapshot()).cache.status, 'hit');
  let metrics = bridge.diagnostics().source_fingerprint;
  assert.deepEqual(
    { watchScans: metrics.watchScans, completeScans: metrics.completeScans, guardedReuses: metrics.guardedReuses },
    { watchScans: 2, completeScans: 1, guardedReuses: 1 }
  );

  const watched = path.join(root, 'registry', 'tools.json');
  const previousStat = fs.statSync(watched);
  fs.writeFileSync(watched, '{"tools":{}}\n');
  fs.utimesSync(watched, previousStat.atime, new Date(previousStat.mtimeMs + 2000));
  const changed = await bridge.snapshot();
  assert.equal(now, 4242);
  assert.equal(changed.cache.status, 'miss');
  assert.equal(changed.cache.invalidation_reason, 'source-fingerprint-changed');
  assert.equal(executions, 2);
  metrics = bridge.diagnostics().source_fingerprint;
  assert.equal(metrics.completeScans, 2);
  assert.equal(metrics.guardedReuses, 1);

  bridge.invalidate('test-explicit-invalidation');
  await bridge.snapshot();
  assert.equal(executions, 3);
  assert.equal(bridge.diagnostics().source_fingerprint.completeScans, 3);
  bridge.dispose();
});

test('watch stamp detects same-size content changes inside extension src without timestamp drift', async t => {
  const root = fixture(t);
  fs.mkdirSync(path.join(root, 'extension', 'src'), { recursive: true });
  const watchedFile = path.join(root, 'extension', 'src', 'bridge-watch-fixture.txt');
  fs.writeFileSync(watchedFile, 'alpha');
  let executions = 0;
  const bridge = new PxBridge({
    engineRoot: root,
    projectRoot: root,
    cacheTtlMs: 5000,
    capture: async () => raw(++executions),
    now: () => 1000
  });
  assert.equal((await bridge.snapshot()).cache.status, 'miss');
  assert.equal(executions, 1);
  const before = snapshotSourceWatchStamp(root, root);
  const previousStat = fs.statSync(watchedFile);
  fs.writeFileSync(watchedFile, 'bravo');
  fs.utimesSync(watchedFile, previousStat.atimeMs / 1000, previousStat.mtimeMs / 1000);
  assert.notEqual(snapshotSourceWatchStamp(root, root), before);
  const changed = await bridge.snapshot();
  assert.equal(changed.cache.status, 'miss');
  assert.equal(executions, 2);
  bridge.dispose();
});

test('watch stamp detects same-size content changes inside watched media style subtree without timestamp drift', async t => {
  const root = fixture(t);
  const watchedFile = path.join(root, 'extension', 'media', 'styles', 'deep-watch.css');
  fs.mkdirSync(path.dirname(watchedFile), { recursive: true });
  fs.writeFileSync(watchedFile, 'alpha');
  let executions = 0;
  const bridge = new PxBridge({
    engineRoot: root,
    projectRoot: root,
    cacheTtlMs: 5000,
    capture: async () => raw(++executions),
    now: () => 1000
  });
  assert.equal((await bridge.snapshot()).cache.status, 'miss');
  assert.equal(executions, 1);
  const before = snapshotSourceWatchStamp(root, root);
  const previousStat = fs.statSync(watchedFile);
  fs.writeFileSync(watchedFile, 'bravo');
  fs.utimesSync(watchedFile, previousStat.atime, previousStat.mtime);
  assert.notEqual(snapshotSourceWatchStamp(root, root), before);
  const changed = await bridge.snapshot();
  assert.equal(changed.cache.status, 'miss');
  assert.equal(executions, 2);
  bridge.dispose();
});

test('verified persistent metadata restores across bridge restart without executing Python', async t => {
  const root = fixture(t); const values = new Map(); let executions = 0;
  const store = { get: key => values.get(key), update: (key, value) => { values.set(key, value); } };
  const first = new PxBridge({ engineRoot: root, projectRoot: root, cacheStore: store, capture: async () => raw(++executions) });
  assert.equal((await first.snapshot()).cache.status, 'miss'); first.dispose();
  const restarted = new PxBridge({ engineRoot: root, projectRoot: root, cacheStore: store, capture: async () => raw(++executions) });
  assert.equal((await restarted.snapshot()).cache.status, 'persistent-hit');
  assert.equal(executions, 1);
  restarted.dispose();
});

test('studio writes require an explicit project, use stdin, and are never result-cached', async t => {
  const root = fixture(t); const calls = [];
  const detached = new PxBridge({ engineRoot: root, capture: async () => ({}) });
  await assert.rejects(() => detached.createStudioDraft('agent', { agent_id: 'demo' }), /explicit project workspace/);
  detached.dispose();
  const bridge = new PxBridge({ engineRoot: root, projectRoot: root, capture: async (_command, args, options) => { calls.push({ args, options }); return { created: true }; } });
  const payload = { agent_id: 'demo', instructions: 'bounded' };
  await bridge.createStudioDraft('agent', payload); await bridge.createStudioDraft('agent', payload);
  await bridge.studioOperation('agent', 'test', payload);
  assert.equal(calls.length, 3);
  assert.ok(calls.every(call => call.args.includes('--payload-stdin')));
  assert.ok(calls.every(call => Buffer.isBuffer(call.options.input)));
  assert.ok(calls.every(call => !call.args.includes('--payload-base64')));
  assert.ok(calls[2].args.includes('test'));
  bridge.dispose();
});

test('committed Studio mutations invalidate catalog state while read-only allocation preserves reuse', async t => {
  const root = fixture(t);
  const bridge = new PxBridge({ engineRoot: root, projectRoot: root, capture: async () => ({ valid: true }) });
  bridge.requestCache.set('studio-lifecycle:agents:old', { createdAt: 1, value: { stale: true } });
  bridge.requestCache.set('catalog:agents:old', { createdAt: 1, value: { stale: true } });
  await bridge.nextStudioVersion('agent', 'agent:demo', '1.0.0', 'studio-physical');
  await bridge.studioIdentityAbsence('agent', 'agent:new');
  assert.equal(bridge.requestCache.size, 2);
  await bridge.studioOperation('agent', 'test', { agent_id: 'agent:demo', version: '1.0.1' });
  assert.equal(bridge.requestCache.size, 0);
  assert.equal(bridge.lastInvalidationReason, 'studio-agent-test-committed');
  bridge.dispose();
});

test('project Studio and PX skill state participate in snapshot source identity', t => {
  const root = fixture(t);
  const before = snapshotSourceFingerprint(root, root);
  fs.mkdirSync(path.join(root, '.px', 'skills', 'demo'), { recursive: true });
  fs.writeFileSync(path.join(root, '.px', 'skill-index.json'), '{"skills":[]}\n');
  fs.writeFileSync(path.join(root, '.px', 'skills', 'demo', 'SKILL.md'), '# demo\n');
  assert.notEqual(snapshotSourceFingerprint(root, root), before);
});

test('Studio next-version bridge sends exact physical and external predecessor envelopes', async t => {
  const root = fixture(t); const calls = [];
  const bridge = new PxBridge({ engineRoot: root, projectRoot: root, capture: async (_command, args, options) => { calls.push({ args, options }); return { allocated: true }; } });
  await bridge.nextStudioVersion('agent', 'agent:physical', '1.0.0', 'studio-physical', 'a'.repeat(64), 'b'.repeat(64));
  await bridge.nextStudioVersion('workflow', 'workflow:physical', '2.0.0', 'studio-physical', 'c'.repeat(64), 'd'.repeat(64));
  await bridge.nextStudioVersion('skill', 'skill:physical', '3.0.0', 'studio-physical', 'e'.repeat(64), 'f'.repeat(64));
  await bridge.nextStudioVersion('skill', 'skill:external', '4.0.0', 'external-authenticated', '1'.repeat(64), '2'.repeat(64));
  assert.equal(calls.length, 4);
  assert.ok(calls.every(call => call.args.includes('next-version')));
  assert.deepEqual(calls.map(call => JSON.parse(call.options.input.toString('utf8'))), [
    { identity: 'agent:physical', source_version: '1.0.0' },
    { identity: 'workflow:physical', source_version: '2.0.0' },
    { identity: 'skill:physical', source_version: '3.0.0' },
    { identity: 'skill:external', source_version: '4.0.0', source_scope: 'external-authenticated', source_revision_sha256: '1'.repeat(64), source_content_sha256: '2'.repeat(64) }
  ]);
  await assert.rejects(() => bridge.nextStudioVersion('skill', 'skill:unknown', '1.0.0', 'physical-ish'), /source scope/);
  await assert.rejects(() => bridge.nextStudioVersion('skill', 'skill:empty', '1.0.0', ''), /source scope/);
  await assert.rejects(() => bridge.nextStudioVersion('agent', 'agent:external', '1.0.0', 'external-authenticated', 'a'.repeat(64), 'b'.repeat(64)), /skill-only/);
  assert.equal(calls.length, 4);
  bridge.dispose();
});

test('Studio conflict stderr is parsed only from the exact structured envelope', () => {
  const error = studioProcessError(JSON.stringify({ schema_version: 'px.studio-operation-error/1.0', code: 'STUDIO_VERSION_CONFLICT', reason: 'allocation-stale' }), 2);
  assert.equal(error.code, 'STUDIO_VERSION_CONFLICT'); assert.equal(error.reason, 'allocation-stale');
  assert.equal(exactStudioVersionConflictError(error), true);
  assert.match(error.message, /^studio-version-conflict:allocation-stale$/);
  const wrapped = studioProcessError(`prefix\n${JSON.stringify({ schema_version: 'px.studio-operation-error/1.0', code: 'STUDIO_VERSION_CONFLICT', reason: 'allocation-stale' })}`, 1);
  assert.equal(wrapped.code, undefined); assert.match(wrapped.message, /prefix/);
  const unknown = studioProcessError(JSON.stringify({ schema_version: 'px.studio-operation-error/1.0', code: 'OTHER', reason: 'allocation-stale' }), 1);
  assert.equal(unknown.code, undefined);
  const unknownReason = studioProcessError(JSON.stringify({ schema_version: 'px.studio-operation-error/1.0', code: 'STUDIO_VERSION_CONFLICT', reason: 'future-open-ended-reason' }), 1);
  assert.equal(unknownReason.code, undefined); assert.match(unknownReason.message, /future-open-ended-reason/);
  const nonStringReason = studioProcessError(JSON.stringify({ schema_version: 'px.studio-operation-error/1.0', code: 'STUDIO_VERSION_CONFLICT', reason: { toString: 'allocation-stale' } }), 1);
  assert.equal(nonStringReason.code, undefined);
  const wrongExit = studioProcessError(JSON.stringify({ schema_version: 'px.studio-operation-error/1.0', code: 'STUDIO_VERSION_CONFLICT', reason: 'allocation-stale' }), 1);
  assert.equal(wrongExit.code, undefined); assert.equal(exactStudioVersionConflictError(wrongExit), false);
});

test('Studio conflict survives an actual bounded child-process round trip only on exit two', async () => {
  const envelope = JSON.stringify({ schema_version: 'px.studio-operation-error/1.0', code: 'STUDIO_VERSION_CONFLICT', reason: 'allocation-stale' });
  await assert.rejects(
    captureJson(process.execPath, ['-e', `process.stderr.write(${JSON.stringify(envelope)}); process.exit(2);`], { timeoutMs: 10_000 }),
    error => exactStudioVersionConflictError(error) && error.reason === 'allocation-stale'
  );
  await assert.rejects(
    captureJson(process.execPath, ['-e', `process.stderr.write(${JSON.stringify(envelope)}); process.exit(1);`], { timeoutMs: 10_000 }),
    error => !exactStudioVersionConflictError(error) && error.code === undefined
  );
});

test('Studio conflict parser owns exhaustive parity with the Python runtime reason set', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '..', '..', 'runtime', 'studio_models.py'), 'utf8');
  const block = /STUDIO_VERSION_CONFLICT_REASONS = frozenset\(\s*\{([\s\S]*?)\}\s*\)/.exec(source);
  assert.ok(block, 'Python Studio conflict reason owner must remain source-visible');
  const pythonReasons = [...block[1].matchAll(/"([a-z0-9-]+)"/g)].map(match => match[1]).sort();
  const bridgeReasons = [...STUDIO_VERSION_CONFLICT_REASONS].sort();
  assert.deepEqual(bridgeReasons, pythonReasons);
  for (const reason of bridgeReasons) {
    const error = studioProcessError(JSON.stringify({ schema_version: 'px.studio-operation-error/1.0', code: 'STUDIO_VERSION_CONFLICT', reason }), 2);
    assert.equal(error.code, 'STUDIO_VERSION_CONFLICT');
    assert.equal(error.reason, reason);
  }
});

test('operational ledger bridge queries are bounded and exact', async t => {
  const root = fixture(t); const calls = [];
  const bridge = new PxBridge({ engineRoot: root, capture: async (_command, args) => { calls.push(args); return { ok: true }; } });
  await bridge.operationalCards({ requestId: 'page-1', query: 'layout', state: 'scoped', severity: 'critical', offset: -4, limit: 1000, evidenceGap: true });
  await bridge.operationalCard({ requestId: 'card-1', gapId: 'PX-OS-096' });
  await bridge.operationalInventory({ requestId: 'inventory-1', surfaceId: 'dashboard' });
  assert.ok(calls[0].includes('operational-cards')); assert.ok(calls[0].includes('--evidence-gap')); assert.equal(calls[0][calls[0].indexOf('--limit') + 1], '100');
  assert.deepEqual(calls[1].slice(-2), ['--gap-id', 'PX-OS-096']);
  assert.deepEqual(calls[2].slice(-2), ['--surface-id', 'dashboard']);
  await assert.rejects(() => bridge.operationalCard({ gapId: '../wrong' }), /gap ID is invalid/);
  bridge.dispose();
});

test('signed payload transport remains bounded without rejecting escape-heavy valid payloads', async t => {
  const root = fixture(t); const calls = [];
  const bridge = new PxBridge({ engineRoot: root, projectRoot: root, capture: async (_command, _args, options) => { calls.push(options.input); return { created: true }; } });
  const unsigned = { value: '\\'.repeat(120 * 1024) };
  const payloadJson = JSON.stringify(unsigned);
  assert.ok(Buffer.byteLength(payloadJson) < 256 * 1024);
  const proof = { claim: {}, payload_json: payloadJson, signature: 'fixture' };
  await bridge.studioOperation('agent', 'create', { ...unsigned, approval_capability: proof });
  assert.equal(calls.length, 1);
  assert.ok(calls[0].length > 256 * 1024);
  assert.ok(calls[0].length < 528 * 1024);
  bridge.dispose();
});

test('studio approval is signed by the host key and Python receives no issuer secret', async t => {
  const root = fixture(t);
  const hostRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-approval-host-'));
  t.after(() => fs.rmSync(hostRoot, { recursive: true, force: true }));
  const projectIdentity = 'px-project-bridge-test';
  const calls = [];
  const capture = async (_command, args, options) => {
    calls.push({ args, options });
    if (args.includes('--describe-verifier')) return {
      project_identity: projectIdentity,
      key_root: hostRoot,
      record_path: path.join(hostRoot, 'approval-verifiers', `${projectIdentity}.json`)
    };
    throw new Error('unexpected capture');
  };
  const material = generateApprovalKey();
  const bridge = new PxBridge({
    engineRoot: root, projectRoot: root, capture,
    approvalKeyProvider: async request => request?.action === 'find' ? null : { active: material, previous: [] }
  });
  const result = await bridge.issueStudioApproval('agent', 'create', { agent_id: 'demo' });
  assert.equal(result.approval_capability.claim.approved_by, 'human:vscode-local-user');
  assert.equal(result.approval_capability.claim.key_id, material.keyId);
  assert.ok(result.approval_capability.signature.length > 300);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.environment, undefined);
  const enrollment = JSON.parse(fs.readFileSync(path.join(hostRoot, 'approval-verifiers', `${projectIdentity}.json`), 'utf8'));
  assert.equal(enrollment.approved_by, 'human:vscode-local-user');
  assert.equal(enrollment.host_surface, 'vscode-extension-host');
  assert.equal(enrollment.key_id, material.keyId);
  bridge.dispose();
});

test('studio verifier uses component-aware containment and supports proven rotation plus explicit recovery', async t => {
  const root = fixture(t); const hostRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-approval-rotate-'));
  t.after(() => fs.rmSync(hostRoot, { recursive: true, force: true }));
  const projectIdentity = 'px-project-rotation-test';
  const descriptor = { project_identity: projectIdentity, key_root: hostRoot, record_path: path.join(hostRoot, 'approval-verifiers', `${projectIdentity}.json`) };
  let ring = { active: generateApprovalKey(), previous: [] }; let recoveryCalls = 0;
  const provider = async request => {
    if (request?.action === 'find') return [ring.active, ...ring.previous].find(item => item.keyId === request.keyId) || null;
    return ring;
  };
  const bridge = new PxBridge({ engineRoot: root, projectRoot: root, capture: async () => descriptor, approvalKeyProvider: provider, approvalRecoveryProvider: async () => { recoveryCalls += 1; return true; } });
  await bridge.issueStudioApproval('agent', 'create', { agent_id: 'first' });
  const first = ring.active; ring = { active: generateApprovalKey(), previous: [first] };
  await bridge.issueStudioApproval('agent', 'create', { agent_id: 'rotated' });
  let enrolled = JSON.parse(fs.readFileSync(descriptor.record_path, 'utf8'));
  assert.equal(enrolled.rotation.mode, 'old-key-proof'); assert.equal(recoveryCalls, 0);
  ring = { active: generateApprovalKey(), previous: [] };
  await bridge.issueStudioApproval('agent', 'create', { agent_id: 'recovered' });
  enrolled = JSON.parse(fs.readFileSync(descriptor.record_path, 'utf8'));
  assert.equal(enrolled.rotation.mode, 'explicit-human-recovery'); assert.equal(recoveryCalls, 1);
  assert.equal(fs.readdirSync(path.join(path.dirname(descriptor.record_path), 'recovery-backups')).length, 1);

  const containedRoot = path.join(root, '..broker');
  const contained = new PxBridge({ engineRoot: root, projectRoot: root, capture: async () => ({ ...descriptor, key_root: containedRoot, record_path: path.join(containedRoot, 'approval-verifiers', `${projectIdentity}.json`) }), approvalKeyProvider: provider });
  await assert.rejects(() => contained.issueStudioApproval('agent', 'create', { agent_id: 'blocked' }), /outside the admitted host boundary/);
  contained.dispose(); bridge.dispose();
});

test('host-signed approval verifies end to end in the Python mutation boundary', async t => {
  const engineRoot = path.resolve(__dirname, '..', '..');
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-host-proof-project-'));
  const keyRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-host-proof-keys-'));
  const previous = process.env.PX_STUDIO_KEY_ROOT;
  process.env.PX_STUDIO_KEY_ROOT = keyRoot;
  t.after(() => {
    if (previous === undefined) delete process.env.PX_STUDIO_KEY_ROOT; else process.env.PX_STUDIO_KEY_ROOT = previous;
    fs.rmSync(projectRoot, { recursive: true, force: true }); fs.rmSync(keyRoot, { recursive: true, force: true });
  });
  const material = generateApprovalKey();
  const bridge = new PxBridge({
    engineRoot, projectRoot, approvalKeyProvider: async request => request?.action === 'find' ? null : { active: material, previous: [] }
  });
  const payload = {
    agent_id: 'agent:host-proof-e2e', version: '1.0.0', project_id: 'project:test',
    owner: 'human:owner', harness_id: 'harness:px', instructions: 'Stay bounded.\n',
    capability_binding_ids: ['binding:test'], effect_grant_ids: ['grant:test'], required_tests: ['identity']
  };
  const approval = await bridge.issueStudioApproval('agent', 'create', payload);
  const result = await bridge.studioOperation('agent', 'create', { ...payload, approval_capability: approval.approval_capability });
  assert.equal(result.created, true); assert.equal(result.agent_id, payload.agent_id);
  await assert.rejects(() => bridge.studioOperation('agent', 'create', { ...payload, approval_capability: approval.approval_capability }), /replay denied/);
  bridge.dispose();
});

test('host-to-Python approval preserves exact valid JSON bytes across edge vectors', async t => {
  const engineRoot = path.resolve(__dirname, '..', '..');
  const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-host-vectors-project-'));
  const keyRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-host-vectors-keys-'));
  const previous = process.env.PX_STUDIO_KEY_ROOT;
  process.env.PX_STUDIO_KEY_ROOT = keyRoot;
  t.after(() => {
    if (previous === undefined) delete process.env.PX_STUDIO_KEY_ROOT; else process.env.PX_STUDIO_KEY_ROOT = previous;
    fs.rmSync(projectRoot, { recursive: true, force: true }); fs.rmSync(keyRoot, { recursive: true, force: true });
  });
  const material = generateApprovalKey();
  const bridge = new PxBridge({
    engineRoot, projectRoot, approvalKeyProvider: async request => request?.action === 'find' ? null : { active: material, previous: [] }
  });
  const vectors = [
    { name: 'decimal-threshold', value: 0.000001 },
    { name: 'scientific-threshold', value: 0.0000001 },
    { name: 'large-decimal-threshold', value: 1e20 },
    { name: 'large-scientific-threshold', value: 1e21 },
    { name: 'negative-zero', value: -0 },
    { name: 'escaped-unicode', value: 'line\u2028separator\\slash"\n' },
    { name: 'utf16-key-order', value: { '\u{10000}': 1, '\uE000': 2 } }
  ];
  for (const [index, vector] of vectors.entries()) {
    const payload = {
      agent_id: `agent:host-vector-${index}`, version: '1.0.0', project_id: 'project:test',
      owner: 'human:owner', harness_id: 'harness:px', instructions: 'Stay bounded.\n',
      capability_binding_ids: ['binding:test'], effect_grant_ids: ['grant:test'], required_tests: ['identity'],
      metadata: { [vector.name]: vector.value }
    };
    const approval = await bridge.issueStudioApproval('agent', 'create', payload);
    const result = await bridge.studioOperation('agent', 'create', { ...payload, approval_capability: approval.approval_capability });
    assert.equal(result.created, true, vector.name);
  }
  bridge.dispose();
});
