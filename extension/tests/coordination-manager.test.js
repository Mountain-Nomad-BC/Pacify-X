'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
  createParallelPlan, claimTask, recordProgress, reconcileTask, releaseTask,
  captureMemory, registerSession, readCoordination, taskHandoff, renewClaim,
  diagnoseWorkStop, workRoom, readMemoryTelemetry
} = require('../src/coordinationManager');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-coordination-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}
const actorA = { actorId: 'actor-a', sessionId: 'session-a', harness: 'VS Code', accountableOwner: 'tester' };
const actorB = { actorId: 'actor-b', sessionId: 'session-b', harness: 'Antigravity', accountableOwner: 'tester' };

test('coordination inspection does not initialize or write an absent store', t => {
  const root = fixture(t); const before = fs.readdirSync(root).sort();
  const result = readCoordination(root);
  assert.equal(result.instrumented, false);
  assert.equal(result.persistence, 'not-initialized-read-only');
  assert.deepEqual(fs.readdirSync(root).sort(), before);
});

test('parallel plan accepts disjoint work and rejects unordered overlapping ancestor scopes', t => {
  const root = fixture(t);
  createParallelPlan(root, actorA, { objective: 'disjoint', tasks: [
    { id: 'ui', title: 'UI', claims: ['media/'] },
    { id: 'runtime', title: 'Runtime', claims: ['runtime/'] }
  ] });
  assert.equal(readCoordination(root).state.tasks.length, 2);
  assert.throws(() => createParallelPlan(root, actorA, { objective: 'conflict', tasks: [
    { id: 'parent', title: 'Parent', claims: ['src/'] },
    { id: 'child', title: 'Child', claims: ['src/feature/file.js'] }
  ] }), /parallel-claim-conflict/);
});

test('dependency ordering permits overlap but blocks checkout until dependency completes', t => {
  const root = fixture(t);
  createParallelPlan(root, actorA, { objective: 'ordered', tasks: [
    { id: 'build', title: 'Build', claims: ['src/'] },
    { id: 'review', title: 'Review', claims: ['src/feature'], dependsOn: ['build'] }
  ] });
  assert.throws(() => claimTask(root, actorB, { taskId: 'review' }), /task-dependencies-incomplete/);
  claimTask(root, actorA, { taskId: 'build' });
  recordProgress(root, actorA, { taskId: 'build', status: 'completed', summary: 'built' });
  reconcileTask(root, actorA, { taskId: 'build', summary: 'verified', conflictsResolved: true });
  const claimed = claimTask(root, actorB, { taskId: 'review' });
  assert.equal(claimed.result.receipt.task_id, 'review');
});

test('active file claims deny a second IDE and owner checks protect progress', t => {
  const root = fixture(t);
  createParallelPlan(root, actorA, { objective: 'first', tasks: [{ id: 'one', title: 'One', claims: ['src/a'] }] });
  claimTask(root, actorA, { taskId: 'one' });
  createParallelPlan(root, actorB, { objective: 'second', tasks: [{ id: 'two', title: 'Two', claims: ['src/a/file.js'] }] });
  assert.throws(() => claimTask(root, actorB, { taskId: 'two' }), /active-claim-conflict/);
  assert.throws(() => recordProgress(root, actorB, { taskId: 'one', status: 'in_progress', summary: 'forged' }), /owning-actor/);
});

test('completion requires explicit reconciliation and releases the task claim', t => {
  const root = fixture(t);
  createParallelPlan(root, actorA, { objective: 'finish', tasks: [{ id: 'task', title: 'Task', claims: ['src/task.js'] }] });
  claimTask(root, actorA, { taskId: 'task' });
  assert.throws(() => reconcileTask(root, actorA, { taskId: 'task', summary: 'early', conflictsResolved: true }), /must-be-completed/);
  recordProgress(root, actorA, { taskId: 'task', status: 'completed', summary: 'tests passed', evidence: ['test:ok'] });
  reconcileTask(root, actorA, { taskId: 'task', summary: 'merged', conflictsResolved: true });
  const state = readCoordination(root).state;
  assert.equal(state.tasks.find(item => item.id === 'task').status, 'reconciled');
  assert.equal(state.claims.length, 0);
  assert.equal(state.active_plan, null);
});

test('rolling state is cross-session resumable and layered memory remains explicit', t => {
  const root = fixture(t);
  registerSession(root, actorA);
  registerSession(root, actorB);
  createParallelPlan(root, actorA, { objective: 'resume elsewhere', tasks: [{ id: 'portable', title: 'Portable', claims: ['docs/'] }] });
  captureMemory(root, actorA, { layer: 'session', kind: 'decision', content: 'Use a typed bridge.' });
  captureMemory(root, actorA, { layer: 'project', kind: 'architecture', content: 'Pacify-X owns registry normalization.' });
  captureMemory(root, actorB, { layer: 'state', kind: 'checkpoint', content: 'Parallel plan accepted.' });
  captureMemory(root, actorB, { layer: 'system_candidate', kind: 'pattern', content: 'Ancestor claims should collide.' });
  assert.throws(() => captureMemory(root, actorA, { layer: 'system', content: 'must fail' }), /must-enter-as-candidate/);
  const resumed = readCoordination(root, { eventLimit: 100 });
  assert.equal(resumed.state.sessions.length, 2);
  assert.deepEqual(resumed.state.memory, { session_records: 1, project_records: 1, state_records: 1, system_candidates: 1 });
  assert.equal(resumed.memory.record_count, 4);
  assert.equal(resumed.memory.integrity.valid, true);
  assert.equal(resumed.memory.canonical, false);
  assert.equal(resumed.memory.records.every(record => record.content === undefined), true);
  const search = readMemoryTelemetry(root, { query: 'typed bridge', includeContent: true });
  assert.equal(search.matched_count, 1);
  assert.equal(search.records[0].content, 'Use a typed bridge.');
  assert.match(search.records[0].record_sha256, /^[a-f0-9]{64}$/);
  assert.equal(fs.existsSync(resumed.paths.handoff_json), true);
  assert.equal(fs.existsSync(resumed.paths.handoff_markdown), true);
  assert.equal(taskHandoff(root, 'portable').task.id, 'portable');
});

test('portable memory validates confidence, provenance hashes, seals, and counter drift', t => {
  const root = fixture(t);
  assert.throws(() => captureMemory(root, actorA, { layer: 'project', kind: 'bad', content: 'bad', confidence: 1.1 }), /confidence-out-of-range/);
  assert.throws(() => captureMemory(root, actorA, { layer: 'project', kind: 'bad', content: 'bad', sourceHash: 'not-a-digest' }), /source-hash-must-be-sha256/);
  fs.writeFileSync(path.join(root, 'evidence.txt'), 'source bytes', 'utf8');
  captureMemory(root, actorA, { layer: 'project', kind: 'decision', content: 'sealed value', confidence: 0.8, sourceArtifact: 'evidence.txt' });
  const telemetry = readMemoryTelemetry(root, { includeContent: true });
  assert.equal(telemetry.integrity.sealed_records, 1);
  assert.equal(telemetry.integrity.valid, true);
  assert.equal(telemetry.records[0].source_hash_method, 'artifact-bytes-sha256');
  assert.equal(telemetry.records[0].source_hash, require('crypto').createHash('sha256').update('source bytes').digest('hex'));
  const file = path.join(root, '.engineering-bootstrap', 'coordination', 'memory', 'project.jsonl');
  fs.appendFileSync(file, `${fs.readFileSync(file, 'utf8').trim().replace('sealed value', 'tampered value')}\n`);
  const tampered = readMemoryTelemetry(root, { includeContent: true });
  assert.equal(tampered.integrity.valid, false);
  assert.equal(tampered.integrity.invalid_records, 1);
  assert.equal(tampered.integrity.counter_drift.length, 0);
  const stateFile = path.join(root, '.engineering-bootstrap', 'coordination', 'state.json');
  const state = JSON.parse(fs.readFileSync(stateFile, 'utf8')); state.memory.project_records = 2; state.state_hash = require('../src/coordinationManager').hash({ ...state, state_hash: null });
  fs.writeFileSync(stateFile, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  assert.equal(readMemoryTelemetry(root).integrity.counter_drift.length, 1);
});

test('explicit task release preserves history while removing ownership', t => {
  const root = fixture(t);
  createParallelPlan(root, actorA, { objective: 'release', tasks: [{ id: 'task', title: 'Task', claims: ['src/'] }] });
  claimTask(root, actorA, { taskId: 'task' });
  releaseTask(root, actorA, { taskId: 'task', reason: 'handoff' });
  const snapshot = readCoordination(root);
  assert.equal(snapshot.state.tasks.find(item => item.id === 'task').owner, null);
  assert.equal(snapshot.state.tasks.find(item => item.id === 'task').status, 'released');
  assert.equal(snapshot.events.some(event => event.operation === 'task-released'), true);
});

test('fencing tokens increase and stale replay is rejected after release and reclaim', t => {
  const root = fixture(t);
  createParallelPlan(root, actorA, { objective: 'fence', tasks: [{ id: 'task', title: 'Task', claims: ['src/fenced.js'] }] });
  const first = claimTask(root, actorA, { taskId: 'task' }).result.receipt;
  renewClaim(root, actorA, { claimId: first.claim_id, fencingTokens: first.fencing_tokens, ttlMinutes: 30 });
  releaseTask(root, actorA, { taskId: 'task', reason: 'handoff' });
  const second = claimTask(root, actorB, { taskId: 'task' }).result.receipt;
  assert.ok(second.fencing_tokens['src/fenced.js'] > first.fencing_tokens['src/fenced.js']);
  assert.throws(() => recordProgress(root, actorB, { taskId: 'task', status: 'in_progress', summary: 'stale', fencingTokens: first.fencing_tokens }), /stale-fencing-token/);
  recordProgress(root, actorB, { taskId: 'task', status: 'in_progress', summary: 'current', fencingTokens: second.fencing_tokens });
});

test('shared and informational modes coexist while exclusive overlap blocks', t => {
  const root = fixture(t);
  createParallelPlan(root, actorA, { objective: 'modes one', tasks: [{ id: 'one', title: 'One', claims: ['docs/shared'] }] });
  claimTask(root, actorA, { taskId: 'one', claimTargets: ['docs/shared'], mode: 'shared' });
  createParallelPlan(root, actorB, { objective: 'modes two', tasks: [{ id: 'two', title: 'Two', claims: ['docs/shared/file.md'] }] });
  claimTask(root, actorB, { taskId: 'two', claimTargets: ['docs/shared/file.md'], mode: 'shared' });
  releaseTask(root, actorB, { taskId: 'two' });
  claimTask(root, actorB, { taskId: 'two', claimTargets: ['docs/shared/file.md'], mode: 'informational' });
  createParallelPlan(root, actorB, { objective: 'modes three', tasks: [{ id: 'three', title: 'Three', claims: ['docs/shared'] }] });
  assert.throws(() => claimTask(root, { ...actorB, sessionId: 'session-c' }, { taskId: 'three', claimTargets: ['docs/shared'], mode: 'exclusive' }), /active-claim-conflict/);
});

test('budget hard stop and resume envelope are durable and diagnosable', t => {
  const root = fixture(t);
  registerSession(root, actorA);
  createParallelPlan(root, actorA, { objective: 'bounded', tasks: [{
    id: 'bounded-task', title: 'Bounded', description: 'Stay within budget', claims: ['src/bounded'],
    goalContext: ['mission: reliable local coordination'], budget: { maxTokens: 100, hardStop: true },
    acceptance: ['receipt retained']
  }] });
  const claimed = claimTask(root, actorA, { taskId: 'bounded-task' }).result.receipt;
  recordProgress(root, actorA, { taskId: 'bounded-task', status: 'in_progress', summary: 'over budget', usage: { tokens: 101 }, fencingTokens: claimed.fencing_tokens });
  const handoff = taskHandoff(root, 'bounded-task');
  assert.equal(handoff.resume_envelope.usage.status, 'hard_stop');
  assert.deepEqual(handoff.resume_envelope.goal_context, ['mission: reliable local coordination']);
  assert.equal(diagnoseWorkStop(root, 'bounded-task').reasons.some(reason => reason.code === 'budget'), true);
  assert.equal(workRoom(root, 'bounded-task').derived, true);
});
