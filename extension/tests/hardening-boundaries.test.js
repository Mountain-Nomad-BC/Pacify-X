'use strict';

const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const test = require('node:test');
const {
  coordinationPaths, readCoordination, createParallelPlan, tailJsonlDetailed, acquireLock, registerSession
} = require('../src/coordinationManager');
const { processTreeSpawnOptions, terminateProcessTree, terminateProcessTreeAsync } = require('../src/processTree');
const { STUDIO_PROTOCOL, validateWebviewMessage } = require('../src/webviewMessages');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-hardening-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

test('missing authoritative state reads without initialization, while malformed initialized state fails closed', t => {
  const root = fixture(t);
  const initialized = readCoordination(root);
  assert.equal(initialized.state.revision, 0);
  assert.equal(initialized.instrumented, false);
  registerSession(root, { actorId: 'fixture', sessionId: 'fixture', harness: 'test' });
  const paths = coordinationPaths(root);
  fs.writeFileSync(paths.state, '{"schema_version":', 'utf8');
  assert.throws(() => readCoordination(root), /coordination-authoritative-state-corrupt/);
  const evidence = fs.readdirSync(paths.quarantine);
  assert.ok(evidence.some(name => name.endsWith('.corrupt')));
  assert.ok(evidence.some(name => name.endsWith('.receipt.json')));
  assert.equal(fs.readFileSync(paths.state, 'utf8'), '{"schema_version":');
});

test('structurally invalid or cross-workspace authoritative state cannot become a fabricated empty store', t => {
  const root = fixture(t); registerSession(root, {});
  const paths = coordinationPaths(root);
  fs.writeFileSync(paths.state, '{"project":{"root":"C:/elsewhere"},"plans":[],"tasks":[],"claims":[],"sessions":[]}', 'utf8');
  assert.throws(() => readCoordination(root), /workspace-mismatch/);
});

test('authoritative coordination state hash mismatch fails closed with evidence', t => {
  const root = fixture(t); registerSession(root, {}); const initialized = readCoordination(root); const paths = coordinationPaths(root);
  const state = JSON.parse(fs.readFileSync(paths.state, 'utf8')); state.revision = initialized.state.revision + 99;
  fs.writeFileSync(paths.state, JSON.stringify(state), 'utf8');
  assert.throws(() => readCoordination(root), /state-hash-mismatch/);
  assert.ok(fs.readdirSync(paths.quarantine).some(name => name.endsWith('.receipt.json')));
});

test('an old lock owned by a live local process is never stolen and release is token fenced', t => {
  const root = fixture(t); const paths = coordinationPaths(root); registerSession(root, {});
  fs.writeFileSync(paths.lock, JSON.stringify({ token: 'live-owner', pid: process.pid, host: os.hostname(), acquired_utc: '2000-01-01T00:00:00Z' }));
  const ancient = new Date('2000-01-01T00:00:00Z'); fs.utimesSync(paths.lock, ancient, ancient);
  assert.throws(() => acquireLock(paths, 25), /coordination-lock-timeout/);
  fs.unlinkSync(paths.lock);
  const release = acquireLock(paths, 100);
  fs.writeFileSync(paths.lock, JSON.stringify({ token: 'replacement', pid: process.pid, host: os.hostname() }), 'utf8');
  release();
  assert.equal(fs.existsSync(paths.lock), true);
});

test('a provably dead same-host lock is retired with evidence before acquisition', t => {
  const root = fixture(t); const paths = coordinationPaths(root); registerSession(root, {});
  fs.writeFileSync(paths.lock, JSON.stringify({ token: 'dead', pid: 2147483647, host: os.hostname(), acquired_utc: '2000-01-01T00:00:00Z' }));
  const release = acquireLock(paths, 250); release();
  assert.equal(fs.existsSync(paths.lock), false);
  assert.ok(fs.readdirSync(paths.quarantine).some(name => name.endsWith('.stale.receipt.json')));
});

test('JSONL tail preserves the valid prefix and reports a truncated or malformed suffix', t => {
  const root = fixture(t); const file = path.join(root, 'events.jsonl');
  fs.writeFileSync(file, '{"n":1}\n{"n":2}\n{"n":', 'utf8');
  const tail = tailJsonlDetailed(file, 10);
  assert.deepEqual(tail.records, [{ n: 1 }, { n: 2 }]);
  assert.equal(tail.health.status, 'degraded');
  assert.equal(tail.health.reason, 'truncated-final-line');
  assert.equal(tail.health.failed_line, 3);
});

test('coordination mutation refuses to append across a degraded event chain', t => {
  const root = fixture(t); registerSession(root, {}); const paths = coordinationPaths(root);
  fs.writeFileSync(paths.events, '{"event_sha256":"valid-prefix"}\n{"event_sha256":', 'utf8');
  assert.throws(() => createParallelPlan(root, {}, { objective: 'must block', tasks: [{ id: 'x', title: 'x', claims: ['src/x'] }] }), /coordination-event-log-degraded/);
  assert.equal(readCoordination(root).event_log_health.status, 'degraded');
});

test('process-tree termination uses taskkill on Windows and process groups on POSIX', () => {
  const calls = [];
  assert.equal(terminateProcessTree({ pid: 123, kill: () => calls.push('fallback') }, { platform: 'win32', spawnSync: (command, args) => { calls.push([command, args]); return { status: 0 }; } }), true);
  assert.deepEqual(calls[0], ['taskkill', ['/pid', '123', '/t', '/f']]);
  let signal;
  assert.equal(terminateProcessTree({ pid: 456 }, { platform: 'linux', kill: (pid, nextSignal) => { signal = [pid, nextSignal]; } }), true);
  assert.deepEqual(signal, [-456, 'SIGTERM']);
  assert.deepEqual(processTreeSpawnOptions('linux'), { detached: true });
  assert.deepEqual(processTreeSpawnOptions('win32'), {});
});

test('async process termination requests graceful exit without blocking the event loop', async () => {
  const events = new (require('node:events').EventEmitter)(); const calls = [];
  events.pid = 789; events.kill = signal => { calls.push(signal); setImmediate(() => events.emit('close', 0)); return true; };
  const result = await terminateProcessTreeAsync(events, { platform: 'win32', graceMs: 1000, verifyMs: 2000, spawn: () => { throw new Error('escalation should not run'); } });
  assert.equal(result, true);
  assert.deepEqual(calls, ['SIGTERM']);
});

test('webview messages reject unknown operations, fields, dangerous shapes, and invalid bounded fields', () => {
  assert.equal(validateWebviewMessage({ type: 'refresh' }).type, 'refresh');
  assert.equal(validateWebviewMessage({ type: 'setupStudio', requestId: 'studio-setup:one' }).type, 'setupStudio');
  assert.throws(() => validateWebviewMessage({ type: 'setupStudio' }), /field-invalid:requestId/);
  assert.throws(() => validateWebviewMessage({ type: 'setupStudio', requestId: '../bad request' }), /field-invalid:requestId/);
  assert.throws(() => validateWebviewMessage({ type: 'inventedOperation' }), /type-unsupported/);
  assert.throws(() => validateWebviewMessage({ type: 'refresh', surprise: true }), /unknown-fields/);
  assert.throws(() => validateWebviewMessage({ type: 'executeCleanup', ids: ['x'], disposition: 'erase' }), /field-invalid:disposition/);
  assert.throws(() => validateWebviewMessage({ type: 'catalogQuery', limit: Infinity }), /non-finite-number/);
  assert.throws(() => validateWebviewMessage({ type: 'copyText', text: '\ud800' }), /unpaired-surrogate/);
  assert.throws(() => validateWebviewMessage({ type: 'exportRecordJson', record: { ['bad\ud800']: true }, fileName: 'record.json', title: 'Record' }), /key-invalid/);
  assert.throws(() => validateWebviewMessage({ type: 'executeCleanup', ids: Array(1), disposition: 'recycle' }), /array-not-dense-json/);
  assert.throws(() => validateWebviewMessage({ type: 'exportRecordJson', record: { value: undefined }, fileName: 'record.json', title: 'Record' }), /object-type-refused/);
  assert.throws(() => validateWebviewMessage({ type: 'openFile', requestId: 'open-file:path-boundary', path: 'x'.repeat(32769) }), /field-invalid:path/);
  assert.equal(validateWebviewMessage({ type: 'studioOperation', kind: 'agent', operation: 'test', payload: {} }).operation, 'test');
  assert.equal(validateWebviewMessage({ type: 'studioOperation', requestId: 'allocation:one', kind: 'agent', operation: 'next-version', payload: { identity: 'agent:one', source_version: '1.0.0' } }).requestId, 'allocation:one');
  assert.throws(() => validateWebviewMessage({ type: 'studioOperation', kind: 'agent', operation: 'next-version', payload: { identity: 'agent:one', source_version: '1.0.0' } }), /field-invalid:requestId/);
  assert.throws(() => validateWebviewMessage({ type: 'studioOperation', requestId: '../stale request', kind: 'agent', operation: 'next-version', payload: { identity: 'agent:one', source_version: '1.0.0' } }), /field-invalid:requestId/);
  assert.equal(validateWebviewMessage({ type: 'studioOperation', requestId: 'allocation:external', kind: 'skill', operation: 'next-version', payload: { identity: 'skill:one', source_version: '1.0.0', source_selection_id: 'source-selection:123e4567-e89b-12d3-a456-426614174000' } }).payload.identity, 'skill:one');
  assert.equal(validateWebviewMessage({ type: 'studioOperation', requestId: 'allocation:project-skill', kind: 'skill', operation: 'next-version', payload: { identity: 'skill:project', source_version: '1.0.0', source_selection_id: 'source-selection:123e4567-e89b-12d3-a456-426614174001' } }).payload.identity, 'skill:project');
  for (const [identity, sourceVersion] of [
    [' Skill:One ', '1.0.0'], ['skill:UPPER', '1.0.0'], ['x', '1.0.0'],
    ['skill:one', ' 1.0.0 '], ['skill:one', '1.0.0-RC.1'], ['skill:one', '01.0.0'],
    ['skill:one', '2147483648.0.0'], ['skill:one', `1.0.0-${'a'.repeat(65)}`]
  ]) {
    assert.throws(() => validateWebviewMessage({ type: 'studioOperation', requestId: 'allocation:grammar', kind: 'skill', operation: 'next-version', payload: { identity, source_version: sourceVersion } }), /studio-next-version-payload/);
  }
  assert.throws(() => validateWebviewMessage({ type: 'studioOperation', requestId: 'allocation:extra', kind: 'agent', operation: 'next-version', payload: { identity: 'agent:one', source_version: '1.0.0', source_scope: 'studio-physical' } }), /studio-next-version-payload/);
  assert.throws(() => validateWebviewMessage({ type: 'studioOperation', requestId: 'allocation:bleed', kind: 'agent', operation: 'next-version', payload: { identity: 'agent:one', source_version: '1.0.0', source_scope: 'external-authenticated', source_revision_sha256: 'a'.repeat(64), source_content_sha256: 'b'.repeat(64) } }), /studio-next-version-payload/);
  assert.throws(() => validateWebviewMessage({ type: 'studioOperation', requestId: 'allocation:missing-hash', kind: 'skill', operation: 'next-version', payload: { identity: 'skill:one', source_version: '1.0.0', source_scope: 'external-authenticated', source_revision_sha256: 'a'.repeat(64) } }), /studio-next-version-payload/);
  assert.equal(validateWebviewMessage({ type: 'loadSkillPackageEditor', requestId: 'package:one', catalogKind: 'skills', recordId: 'skill:example' }).catalogKind, 'skills');
  assert.equal(validateWebviewMessage({ type: 'loadSkillPackageEditor', requestId: 'package:revision', catalogKind: 'skills', recordId: 'studio:skill:example@1.0.0' }).recordId, 'studio:skill:example@1.0.0');
  assert.throws(() => validateWebviewMessage({ type: 'loadSkillPackageEditor', requestId: 'package:preserved', catalogKind: 'preserved-skills', recordId: 'skill:preserved' }), /field-invalid:catalogKind/);
  assert.throws(() => validateWebviewMessage({ type: 'loadSkillPackageEditor', requestId: 'package:microsoft', catalogKind: 'microsoft-skills', recordId: 'skill:microsoft' }), /field-invalid:catalogKind/);
  assert.throws(() => validateWebviewMessage({ type: 'loadSkillPackageEditor', catalogKind: 'skills', recordId: 'skill:example' }), /field-invalid:requestId/);
  assert.throws(() => validateWebviewMessage({ type: 'loadSkillPackageEditor', requestId: 'package:two', catalogKind: 'skills' }), /field-invalid:recordId/);
  assert.throws(() => validateWebviewMessage({ type: 'loadSkillPackageEditor', requestId: 'package:wrong-kind', catalogKind: 'enterprise-skills', recordId: 'skill:example' }), /field-invalid:catalogKind/);
  assert.equal(validateWebviewMessage({ type: 'loadStudioRevisionEditor', requestId: 'revision:agent', kind: 'agent', catalogKind: 'agents', recordId: 'studio:agent:one' }).kind, 'agent');
  assert.equal(validateWebviewMessage({ type: 'loadStudioRevisionEditor', requestId: 'revision:agent-version', kind: 'agent', catalogKind: 'agents', recordId: 'studio:agent:one@1.0.0' }).recordId, 'studio:agent:one@1.0.0');
  assert.throws(() => validateWebviewMessage({ type: 'loadStudioRevisionEditor', requestId: 'revision:path', kind: 'agent', catalogKind: 'agents', recordId: 'studio/agent/one@1.0.0' }), /field-invalid:recordId/);
  assert.equal(validateWebviewMessage({ type: 'loadStudioRevisionEditor', requestId: 'revision:workflow', kind: 'workflow', catalogKind: 'workflows', recordId: 'studio:workflow:one' }).kind, 'workflow');
  assert.throws(() => validateWebviewMessage({ type: 'loadStudioRevisionEditor', requestId: 'revision:cross', kind: 'agent', catalogKind: 'workflows', recordId: 'studio:agent:one' }), /studio-revision-selection/);
  assert.throws(() => validateWebviewMessage({ type: 'loadStudioRevisionEditor', requestId: 'revision:skill', kind: 'skill', catalogKind: 'skills', recordId: 'studio:skill:one' }), /studio-revision-selection/);
  assert.equal(validateWebviewMessage({ type: 'releaseStudioTrust', requestId: 'allocation:one', trustKind: 'version-allocation', proof: 'version-allocation:123e4567-e89b-12d3-a456-426614174000' }).trustKind, 'version-allocation');
  assert.equal(validateWebviewMessage({ type: 'releaseStudioTrust', requestId: 'package:one', trustKind: 'source-selection', proof: 'source-selection:123e4567-e89b-12d3-a456-426614174001' }).trustKind, 'source-selection');
  assert.throws(() => validateWebviewMessage({ type: 'releaseStudioTrust', requestId: 'package:one', trustKind: 'source-selection', proof: 'version-allocation:wrong-kind' }), /studio-trust-release/);
  assert.equal(validateWebviewMessage({ type: 'createStudioDraft', requestId: 'studio-save:one', kind: 'agent', payload: { agent_id: 'agent:one', version: '1.0.0' } }).requestId, 'studio-save:one');
  assert.equal(validateWebviewMessage({ type: 'detachStudioDraft', requestId: 'studio-save:one', kind: 'agent' }).type, 'detachStudioDraft');
  assert.throws(() => validateWebviewMessage({ type: 'createStudioDraft', requestId: 'studio-save:empty', kind: 'agent', payload: {} }), /studio-create-payload/);
  assert.throws(() => validateWebviewMessage({ type: 'createStudioDraft', kind: 'agent', payload: {} }), /field-invalid:requestId/);
  assert.throws(() => validateWebviewMessage({ type: 'createStudioDraft', requestId: '../stale request', kind: 'agent', payload: {} }), /field-invalid:requestId/);
  assert.equal(validateWebviewMessage({ type: 'studioOperation', kind: 'agent', operation: 'start', payload: {} }).operation, 'start');
  assert.equal(validateWebviewMessage({ type: 'studioOperation', requestId: 'resume:one', kind: 'workflow', operation: 'resume', payload: { run_id: 'run:one' } }).operation, 'resume');
  assert.equal(validateWebviewMessage({ type: 'studioOperation', kind: 'knowledge', operation: 'browse', payload: {} }).operation, 'browse');
  assert.throws(() => validateWebviewMessage({ type: 'studioOperation', kind: 'agent', operation: 'delete', payload: {} }), /studio-operation/);
  assert.throws(() => validateWebviewMessage({ type: 'studioOperation', kind: 'agent', operation: 'test', payload: [] }), /studio-payload/);
  assert.throws(() => validateWebviewMessage({ type: 'studioOperation', kind: 'knowledge', operation: 'start', payload: {} }), /studio-operation/);
  assert.equal(validateWebviewMessage({ type: 'operationalCardQuery', requestId: 'card-1', gapId: 'PX-OS-096' }).gapId, 'PX-OS-096');
  assert.equal(validateWebviewMessage({ type: 'operationalCardsQuery', requestId: 'cards-1', query: '', state: 'scoped', severity: 'critical', surface: '', owner: '', evidenceGap: false, offset: 0, limit: 50 }).limit, 50);
  assert.equal(validateWebviewMessage({ type: 'operationalInventoryQuery', requestId: 'inventory-1', surfaceId: '' }).surfaceId, '');
  assert.throws(() => validateWebviewMessage({ type: 'operationalCardQuery', requestId: 'card-1', gapId: '../wrong' }), /gapId/);
});

test('shipped Studio protocol is an exact projection of the canonical contract', () => {
  const canonical = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', '..', 'registry', 'studio_operations.json'), 'utf8'));
  const shipped = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'resources', 'studio-operations.json'), 'utf8'));
  const packagedRuntime = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', '..', 'runtime', 'studio_operations.json'), 'utf8'));
  assert.deepEqual(shipped, canonical);
  assert.deepEqual(packagedRuntime, canonical);
  assert.deepEqual(STUDIO_PROTOCOL, canonical);
});

test('live graph render acknowledgement is bounded and typed', () => {
  const valid = validateWebviewMessage({ type: 'graphRendered', requestId: 'graph-1', view: 'capabilities', nodeCount: 24, edgeCount: 23, visibleNodeCount: 8, canvasWidth: 900, canvasHeight: 600 });
  assert.equal(valid.visibleNodeCount, 8);
  assert.throws(() => validateWebviewMessage({ ...valid, visibleNodeCount: -1 }), /visibleNodeCount/);
  assert.throws(() => validateWebviewMessage({ ...valid, view: 'enterprise' }), /graph-render-identity/);
});
