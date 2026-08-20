'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { recordActivity, readActivity, reconcileStaleOperations, sanitizeMetadata, activityPaths, acquireLock, tailEventsDetailed } = require('../src/activityManager');

function workspace(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-activity-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

const actor = { actorId: 'agent-one', sessionId: 'session-one', harness: 'test-harness', accountableOwner: 'local-user' };

test('activity trace is hash-linked and preserves a running operation through observations', t => {
  const root = workspace(t); const correlationId = 'trace-one';
  const started = recordActivity(root, actor, { category: 'agent', operation: 'agent.run', status: 'started', correlationId, effect: 'workspace-write', scopeRefs: [path.join(root, 'src', 'a.js')] });
  const observed = recordActivity(root, actor, { category: 'agent', operation: 'agent.run.step', status: 'observed', correlationId, outputSha256: 'a'.repeat(64) });
  let view = readActivity(root, { limit: 20 });
  assert.equal(view.active_operations.length, 1);
  assert.equal(observed.event.previous_event_sha256, started.event.event_sha256);
  assert.equal(view.events[0].content_captured, false);
  assert.deepEqual(started.event.scope_refs, ['src/a.js']);
  const ended = recordActivity(root, actor, { category: 'agent', operation: 'agent.run', status: 'succeeded', correlationId, durationMs: 42 });
  view = readActivity(root, { limit: 20 });
  assert.equal(view.active_operations.length, 0);
  assert.equal(ended.event.previous_event_sha256, observed.event.event_sha256);
  assert.equal(view.event_count, 3);
  assert.equal(view.integrity.valid, true);
});

test('terminal-session observation never creates working state and stale execution is not active', t => {
  const root = workspace(t);
  recordActivity(root, actor, { category: 'terminal', operation: 'terminal.session', status: 'started', effect: 'process', correlationId: 'terminal-open' });
  let view = readActivity(root);
  assert.equal(view.active_operations.length, 0);
  assert.equal(view.agents[0].status, 'idle');

  recordActivity(root, actor, { category: 'agent', operation: 'agent.run', status: 'started', effect: 'workspace-write', correlationId: 'stale-run' });
  const paths = activityPaths(root); const state = JSON.parse(fs.readFileSync(paths.state, 'utf8'));
  const operation = Object.values(state.active_operations)[0]; operation.last_heartbeat_utc = '2000-01-01T00:00:00.000Z';
  state.agents['agent-one:session-one'].last_seen_utc = '2000-01-01T00:00:00.000Z';
  fs.writeFileSync(paths.state, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  view = readActivity(root);
  assert.equal(view.active_operations.length, 0);
  assert.equal(view.stale_operations.length, 1);
  assert.equal(view.agents[0].status, 'offline');
  assert.equal(view.live_agents.length, 0);
  assert.equal(view.historical_agents.length, 1);
});

test('stale executable operations receive append-only terminal reconciliation evidence', t => {
  const root = workspace(t);
  recordActivity(root, actor, { category: 'agent', operation: 'agent.run', status: 'started', effect: 'workspace-write', correlationId: 'stale-reconcile' });
  const paths = activityPaths(root); const state = JSON.parse(fs.readFileSync(paths.state, 'utf8'));
  const operation = Object.values(state.active_operations)[0]; operation.last_heartbeat_utc = '2000-01-01T00:00:00.000Z';
  fs.writeFileSync(paths.state, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  const before = readActivity(root); const receipt = reconcileStaleOperations(root);
  const after = readActivity(root, { limit: 20 });
  assert.equal(before.event_count, 1);
  assert.equal(receipt.candidate_count, 1);
  assert.equal(receipt.reconciled_count, 1);
  assert.equal(receipt.receipt_sha256.length, 64);
  assert.equal(after.event_count, 2);
  assert.equal(after.active_operations.length, 0);
  assert.equal(after.stale_operations.length, 0);
  assert.equal(after.events[0].status, 'cancelled');
  assert.equal(after.events[0].metadata.terminal_reason, 'stale-operation-reconciled');
  assert.equal(after.integrity.valid, true);
});

test('activity metadata redacts content-bearing and secret-bearing fields', t => {
  const root = workspace(t);
  const result = recordActivity(root, actor, { category: 'mcp', operation: 'mcp.call', status: 'observed', metadata: { prompt: 'private', stdout: 'private', password: 'private', apiKey: 'private', safe_label: 'catalog', nested: { authorization: 'private', count: 2 } } });
  assert.equal(result.event.metadata.prompt, '[redacted]');
  assert.equal(result.event.metadata.stdout, '[redacted]');
  assert.equal(result.event.metadata.password, '[redacted]');
  assert.equal(result.event.metadata.apiKey, '[redacted]');
  assert.equal(result.event.metadata.safe_label, 'catalog');
  assert.equal(result.event.metadata.nested.authorization, '[redacted]');
  assert.equal(sanitizeMetadata({ content: 'never persisted' }).content, '[redacted]');
});

test('paused policy blocks ordinary capture but retains an explicit policy-change record', t => {
  const root = workspace(t); const policy = { paused: true };
  assert.deepEqual(recordActivity(root, actor, { operation: 'editor.document.changed' }, policy), { recorded: false, reason: 'activity-paused' });
  const policyRecord = recordActivity(root, actor, { category: 'policy', operation: 'observability.policy-changed', status: 'observed', metadata: { paused: true } }, policy);
  assert.equal(policyRecord.recorded, true);
  assert.equal(readActivity(root).event_count, 1);
});

test('activity reads are bounded and filter by actor, category, status, operation, and scope', t => {
  const root = workspace(t);
  recordActivity(root, actor, { category: 'editor', operation: 'editor.document.saved', status: 'observed', scopeRefs: [path.join(root, 'README.md')] });
  recordActivity(root, { actorId: 'unknown-actor', sessionId: 'watcher', harness: 'workspace-watcher' }, { category: 'filesystem', operation: 'workspace.file.changed', status: 'observed', scopeRefs: [path.join(root, 'src', 'b.js')] });
  assert.equal(readActivity(root, { category: 'filesystem' }).matched_count, 1);
  assert.equal(readActivity(root, { query: 'unknown-actor' }).matched_count, 1);
  assert.equal(readActivity(root, { query: 'README.md' }).matched_count, 1);
  assert.equal(readActivity(root, { status: 'failed' }).matched_count, 0);
});

test('activity reader reports event tampering instead of trusting the trace', t => {
  const root = workspace(t);
  const recorded = recordActivity(root, actor, { category: 'verification', operation: 'verification.test', status: 'succeeded' });
  const eventPath = recorded.paths.events; const event = JSON.parse(fs.readFileSync(eventPath, 'utf8').trim());
  event.operation = 'tampered.operation'; fs.writeFileSync(eventPath, `${JSON.stringify(event)}\n`, 'utf8');
  const view = readActivity(root);
  assert.equal(view.integrity.valid, false);
  assert.deepEqual(view.integrity.invalid_event_ids, [event.event_id]);
});

test('activity state corruption fails closed with retained evidence instead of fabricating an empty trace', t => {
  const root = workspace(t); recordActivity(root, actor, { operation: 'activity.seed' });
  const paths = activityPaths(root); fs.writeFileSync(paths.state, '{"revision":', 'utf8');
  assert.throws(() => readActivity(root), /activity-authoritative-state-corrupt/);
  assert.throws(() => recordActivity(root, actor, { operation: 'activity.must-block' }), /activity-authoritative-state-corrupt/);
  assert.ok(fs.readdirSync(paths.quarantine).some(name => name.endsWith('.corrupt')));
});

test('repeated same-millisecond corruption observations retain collision-free evidence', t => {
  const root = workspace(t); recordActivity(root, actor, { operation: 'activity.seed' });
  const paths = activityPaths(root); fs.writeFileSync(paths.state, '{"revision":', 'utf8');
  const originalNow = Date.now; Date.now = () => 1786593600000;
  try {
    assert.throws(() => readActivity(root), /activity-authoritative-state-corrupt/);
    assert.throws(() => readActivity(root), /activity-authoritative-state-corrupt/);
  } finally { Date.now = originalNow; }
  const names = fs.readdirSync(paths.quarantine);
  assert.equal(names.filter(name => name.endsWith('.corrupt')).length, 2);
  assert.equal(names.filter(name => name.endsWith('.receipt.json')).length, 2);
});

test('activity JSONL preserves its valid prefix, reports degradation, and blocks append', t => {
  const root = workspace(t); const first = recordActivity(root, actor, { operation: 'activity.seed' });
  fs.appendFileSync(first.paths.events, '{"event_id":', 'utf8');
  const tail = tailEventsDetailed(first.paths.events, 100);
  assert.equal(tail.events.length, 1);
  assert.equal(tail.health.status, 'degraded');
  assert.throws(() => recordActivity(root, actor, { operation: 'activity.must-block' }), /activity-event-log-degraded/);
  assert.equal(readActivity(root).integrity.valid, false);
});

test('activity lock does not steal an old live owner and release is token fenced', t => {
  const root = workspace(t); const paths = activityPaths(root); fs.mkdirSync(paths.root, { recursive: true });
  fs.writeFileSync(paths.lock, JSON.stringify({ token: 'live', pid: process.pid, host: os.hostname() }), 'utf8');
  assert.throws(() => acquireLock(paths, 25), /activity-lock-timeout/);
  fs.unlinkSync(paths.lock);
  const release = acquireLock(paths, 100); fs.writeFileSync(paths.lock, JSON.stringify({ token: 'replacement', pid: process.pid, host: os.hostname() }), 'utf8'); release();
  assert.equal(fs.existsSync(paths.lock), true);
});
