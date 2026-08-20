'use strict';

const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const test = require('node:test');
const {
  coordinationPaths, createParallelPlan, claimTask, readCoordination, registerSession, hash
} = require('../src/coordinationManager');
const {
  assertCoordinationState, assertCoordinationTransition, eventHash, sha
} = require('../src/stateInvariants');

const actorA = { actorId: 'actor-a', sessionId: 'session-a', harness: 'VS Code', accountableOwner: 'tester' };
const actorB = { actorId: 'actor-b', sessionId: 'session-b', harness: 'Codex', accountableOwner: 'tester' };

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-state-invariants-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function reseal(state) { state.state_hash = null; state.state_hash = hash(state); return state; }

function claimedState(t) {
  const root = fixture(t);
  createParallelPlan(root, actorA, { objective: 'invariant fixture', tasks: [
    { id: 'left', title: 'Left', claims: ['src/left'], budget: { maxTokens: 100 } },
    { id: 'right', title: 'Right', claims: ['src/right'] }
  ] });
  claimTask(root, actorA, { taskId: 'left' });
  claimTask(root, actorB, { taskId: 'right' });
  return { root, state: readCoordination(root).state };
}

test('semantic state guard rejects hostile DAG, ownership, overlap, fencing, budget, memory, and seal mutations', t => {
  const { state } = claimedState(t);
  assert.equal(assertCoordinationState(state), true);

  const cycle = reseal(clone(state)); cycle.tasks.find(item => item.id === 'left').depends_on = ['left']; reseal(cycle);
  assert.throws(() => assertCoordinationState(cycle), /task-cycle/);

  const owner = clone(state); owner.tasks.find(item => item.id === 'left').owner.session_id = 'forged-session'; reseal(owner);
  assert.throws(() => assertCoordinationState(owner), /active-claim-owner-mismatch/);

  const overlap = clone(state); const right = overlap.claims.find(item => item.task_id === 'right');
  overlap.tasks.find(item => item.id === 'right').claim_targets = ['src/left/child'];
  right.targets = ['src/left/child']; right.fencing_tokens = { 'src/left/child': 1 };
  overlap.team_fabric.fencing_by_target['src/left/child'] = 1; reseal(overlap);
  assert.throws(() => assertCoordinationState(overlap), /active-claim-overlap/);

  const fence = clone(state); fence.team_fabric.fencing_by_target['src/left'] += 1; reseal(fence);
  assert.throws(() => assertCoordinationState(fence), /active-claim-fence-not-current/);

  const budget = clone(state); budget.tasks.find(item => item.id === 'left').usage.tokens = 101; reseal(budget);
  assert.throws(() => assertCoordinationState(budget), /usage-status/);

  const memory = clone(state); memory.memory.project_records = -1; reseal(memory);
  assert.throws(() => assertCoordinationState(memory), /memory-counter/);

  const unsealed = clone(state); unsealed.revision += 1;
  assert.throws(() => assertCoordinationState(unsealed), /state-seal-mismatch/);
});

test('transition guard rejects revision and monotonic-fencing regressions', t => {
  const root = fixture(t); const previous = readCoordination(root).state;
  const next = clone(previous); next.revision += 1; next.updated_utc = new Date(Date.now() + 1).toISOString(); reseal(next);
  const event = {
    schema_version: '1.2', event_id: 'pxe-fixture', timestamp: next.updated_utc, operation: 'session-heartbeat',
    project_id: next.project.id, actor: { actor_id: 'actor', session_id: 'session', harness: 'test', accountable_owner: 'tester' },
    before_hash: previous.state_hash, after_hash: next.state_hash, authority: 'local', previous_event_sha256: null,
    payload_sha256: sha({}), result: {}
  };
  event.event_sha256 = eventHash(event);
  assert.equal(assertCoordinationTransition({ previous, next, operation: 'session-heartbeat', previousEvents: [], event }), true);

  const badRevision = reseal({ ...clone(next), revision: previous.revision + 2, state_hash: null });
  const badRevisionEvent = { ...event, after_hash: badRevision.state_hash }; badRevisionEvent.event_sha256 = eventHash(badRevisionEvent);
  assert.throws(() => assertCoordinationTransition({ previous, next: badRevision, operation: 'session-heartbeat', previousEvents: [], event: badRevisionEvent }), /revision-transition/);

  const fencedPrevious = clone(previous); fencedPrevious.team_fabric.fencing_by_target['src/a'] = 3; reseal(fencedPrevious);
  const fencedNext = clone(fencedPrevious); fencedNext.revision += 1; fencedNext.team_fabric.fencing_by_target['src/a'] = 2; reseal(fencedNext);
  const fencedEvent = { ...event, before_hash: fencedPrevious.state_hash, after_hash: fencedNext.state_hash }; fencedEvent.event_sha256 = eventHash(fencedEvent);
  assert.throws(() => assertCoordinationTransition({ previous: fencedPrevious, next: fencedNext, operation: 'session-heartbeat', previousEvents: [], event: fencedEvent }), /fencing-regression/);
});

test('invalid authoritative semantics fail before state, event, receipt, handoff, or memory publication', t => {
  const root = fixture(t); registerSession(root, actorA); const paths = coordinationPaths(root);
  const state = JSON.parse(fs.readFileSync(paths.state, 'utf8'));
  state.memory.project_records = -1; reseal(state);
  fs.writeFileSync(paths.state, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  const beforeState = fs.readFileSync(paths.state);
  const beforeEvents = fs.existsSync(paths.events) ? fs.readFileSync(paths.events) : null;
  const beforeReceipts = fs.readdirSync(paths.receipts);
  const beforeHandoff = fs.existsSync(paths.handoffJson) ? fs.readFileSync(paths.handoffJson) : null;
  const beforeMemory = fs.existsSync(paths.memory.project) ? fs.readFileSync(paths.memory.project) : null;
  assert.throws(() => registerSession(root, actorA), /memory-counter/);
  assert.deepEqual(fs.readFileSync(paths.state), beforeState);
  assert.equal(fs.existsSync(paths.events), beforeEvents !== null);
  if (beforeEvents) assert.deepEqual(fs.readFileSync(paths.events), beforeEvents);
  assert.deepEqual(fs.readdirSync(paths.receipts), beforeReceipts);
  assert.equal(fs.existsSync(paths.handoffJson), beforeHandoff !== null);
  if (beforeHandoff) assert.deepEqual(fs.readFileSync(paths.handoffJson), beforeHandoff);
  assert.equal(fs.existsSync(paths.memory.project), beforeMemory !== null);
  if (beforeMemory) assert.deepEqual(fs.readFileSync(paths.memory.project), beforeMemory);
});

test('tampered event seal and ancestry fail before the next publication', t => {
  const root = fixture(t); createParallelPlan(root, actorA, { objective: 'event chain', tasks: [{ id: 'task', title: 'Task', claims: ['src/task'] }] });
  const paths = coordinationPaths(root); const stateBefore = fs.readFileSync(paths.state); const receiptsBefore = fs.readdirSync(paths.receipts);
  const records = fs.readFileSync(paths.events, 'utf8').trim().split(/\r?\n/).map(JSON.parse);
  records[0].operation = 'tampered-operation';
  fs.writeFileSync(paths.events, `${records.map(JSON.stringify).join('\n')}\n`, 'utf8');
  const eventsBefore = fs.readFileSync(paths.events);
  assert.throws(() => registerSession(root, actorA), /event-seal/);
  assert.deepEqual(fs.readFileSync(paths.state), stateBefore);
  assert.deepEqual(fs.readFileSync(paths.events), eventsBefore);
  assert.deepEqual(fs.readdirSync(paths.receipts), receiptsBefore);
});

test('resealed event with a false state ancestry link still fails closed', t => {
  const root = fixture(t);
  createParallelPlan(root, actorA, { objective: 'event ancestry', tasks: [{ id: 'task', title: 'Task', claims: ['src/task'] }] });
  registerSession(root, actorA);
  const paths = coordinationPaths(root); const stateBefore = fs.readFileSync(paths.state); const receiptsBefore = fs.readdirSync(paths.receipts);
  const records = fs.readFileSync(paths.events, 'utf8').trim().split(/\r?\n/).map(JSON.parse);
  records[1].before_hash = 'f'.repeat(64);
  records[1].event_sha256 = eventHash(records[1]);
  fs.writeFileSync(paths.events, `${records.map(JSON.stringify).join('\n')}\n`, 'utf8');
  const eventsBefore = fs.readFileSync(paths.events);
  assert.throws(() => registerSession(root, actorA), /event-ancestry/);
  assert.deepEqual(fs.readFileSync(paths.state), stateBefore);
  assert.deepEqual(fs.readFileSync(paths.events), eventsBefore);
  assert.deepEqual(fs.readdirSync(paths.receipts), receiptsBefore);
});

test('same actor id from a different session cannot mutate an owned claim', t => {
  const root = fixture(t);
  createParallelPlan(root, actorA, { objective: 'session ownership', tasks: [{ id: 'task', title: 'Task', claims: ['src/task'] }] });
  claimTask(root, actorA, { taskId: 'task' });
  const imposter = { ...actorA, sessionId: 'different-session' };
  const { recordProgress, reconcileTask, releaseTask } = require('../src/coordinationManager');
  assert.throws(() => recordProgress(root, imposter, { taskId: 'task', status: 'completed', summary: 'forged' }), /owning-actor-or-session/);
  assert.throws(() => releaseTask(root, imposter, { taskId: 'task' }), /owning-actor-or-session/);
  assert.throws(() => reconcileTask(root, imposter, { taskId: 'task' }), /owning-actor-or-session/);
});
