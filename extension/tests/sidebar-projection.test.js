'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { buildSidebarProjection, authoritativeProgress, projectWaves } = require('../src/sidebarProjection');

const NOW = Date.parse('2026-08-11T18:00:00.000Z');

function fixture(overrides = {}) {
  const tasks = overrides.tasks || [
    { id: 'done', title: 'Certified task', status: 'reconciled', weight: 3, depends_on: [], updated_utc: '2026-08-11T17:58:00Z' },
    { id: 'verify', title: 'Needs reconciliation', status: 'completed', weight: 2, depends_on: ['done'], updated_utc: '2026-08-11T17:59:00Z' },
    { id: 'active', title: 'Live task', status: 'in_progress', weight: 1, depends_on: ['done'], updated_utc: '2026-08-11T18:00:00Z', owner: { session_id: 'live-session' } },
    { id: 'blocked', title: 'Blocked task', status: 'blocked', weight: 1, depends_on: ['verify'], updated_utc: '2026-08-11T18:00:00Z' },
    { id: 'skipped', title: 'Approved skip', status: 'skipped', disposition_approved: true, weight: 99, depends_on: [] }
  ];
  const state = {
    revision: 142, updated_utc: '2026-08-11T18:00:00Z', active_plan: 'plan-live',
    plans: [{ id: 'plan-live', objective: 'Integration hardening', status: 'active', task_ids: tasks.map(item => item.id) }], tasks,
    claims: [{ id: 'claim-live', task_id: 'active', status: 'active', actor: { actor_id: 'codex', session_id: 'live-session' } }],
    sessions: [
      { actor_id: 'codex', display_name: 'Codex', session_id: 'live-session', harness: 'VS Code', status: 'active', heartbeat_utc: '2026-08-11T17:59:45Z' },
      { actor_id: 'stale-agent', session_id: 'stale-session', harness: 'CLI', status: 'active', heartbeat_utc: '2026-08-11T17:53:00Z' },
      { actor_id: 'expired-agent', session_id: 'expired-session', harness: 'CLI', status: 'active', heartbeat_utc: '2026-08-11T17:20:00Z' }
    ], team_fabric: { work_rooms: [] }
  };
  return {
    connected: true, generatedAt: '2026-08-11T18:00:00Z', source: { version: '0.5.0' }, health: { authoritative: true, ready: true }, attention: [],
    coordinationData: { event_log_health: { status: 'healthy' }, state, events: [
      { event_id: 'e1', operation: 'task-progress-recorded', timestamp: '2026-08-11T17:59:00Z', result: { task_id: 'active' } },
      { event_id: 'e2', operation: 'session-heartbeat', timestamp: '2026-08-11T17:59:30Z', result: {} }
    ] },
    ...overrides.snapshot
  };
}

test('S02/S06 weighted progress is authoritative and excludes only approved dispositions', () => {
  const tasks = fixture().coordinationData.state.tasks;
  assert.deepEqual(authoritativeProgress(tasks), { numerator: 3, denominator: 7, percent: 42.9 });
  const projection = buildSidebarProjection(fixture(), { nowMs: NOW });
  assert.equal(projection.execution.progressPercent, 42.9);
  assert.deepEqual(projection.punch, { complete: 1, active: 1, queued: 0, blocked: 1, verifying: 1, excluded: 1, total: 4 });
  assert.equal(projection.execution.completedTasks, 1, 'completed but unreconciled work is verifying, never complete');
  assert.equal(projection.performance.workspaceScan, false);
  assert.ok(projection.performance.projectionMs < 50);
});

test('S07 punch counts follow canonical task state and ignore prose-like labels', () => {
  const snapshot = fixture();
  snapshot.coordinationData.state.tasks[0].title = '0 done / 99 blocked / everything queued';
  const before = buildSidebarProjection(snapshot, { nowMs: NOW });
  assert.deepEqual(before.punch, { complete: 1, active: 1, queued: 0, blocked: 1, verifying: 1, excluded: 1, total: 4 });

  snapshot.coordinationData.state.revision += 1;
  snapshot.coordinationData.state.tasks.find(task => task.id === 'verify').status = 'reconciled';
  snapshot.coordinationData.state.tasks.find(task => task.id === 'blocked').status = 'ready';
  const after = buildSidebarProjection(snapshot, { nowMs: NOW + 1_000 });
  assert.equal(after.revision, 143);
  assert.deepEqual(after.punch, { complete: 2, active: 1, queued: 1, blocked: 0, verifying: 0, excluded: 1, total: 4 });
});

test('S06 creates deterministic dependency waves and preserves bounded subtasks', () => {
  const tasks = fixture().coordinationData.state.tasks;
  tasks[2].subtasks = [{ id: 'sub-one', title: 'Host schema', status: 'reconciled' }, { id: 'sub-two', title: 'Live sync', status: 'in_progress' }];
  const waves = projectWaves(tasks, fixture().coordinationData.state.claims);
  assert.deepEqual(waves.map(wave => wave.id), ['wave-1', 'wave-2', 'wave-3']);
  assert.equal(waves[1].tasks.find(task => task.id === 'active').subtasks.length, 2);
  assert.equal(waves[1].tasks.find(task => task.id === 'active').claimId, 'claim-live');
});

test('S08 filters expired agents, marks retained stale agents, and filters noisy recent events', () => {
  const projection = buildSidebarProjection(fixture(), { nowMs: NOW, agentStaleMs: 5 * 60_000 });
  assert.deepEqual(projection.agents.map(agent => [agent.agentId, agent.state]), [['codex', 'active'], ['stale-agent', 'stale']]);
  assert.equal(projection.recent.length, 1);
  assert.equal(projection.recent[0].kind, 'task-progress-recorded');
  assert.equal(projection.attention.some(item => item.id === 'blocked-tasks'), true);
});

test('S09 provider projection exposes unknown billing, fallback use, budget threshold data, and stale telemetry', () => {
  const snapshot = fixture({ snapshot: { providerActivity: [
    { providerId: 'openai', providerName: 'OpenAI API', providerClass: 'billable-api', connectionState: 'connected', activityState: 'active', billingEnabled: null, fallbackEnabled: true, fallbackActive: true, spendCurrent: 22, budgetLimit: 25, ratePerMinute: .41, currency: 'USD', telemetrySource: 'receipt-ledger', telemetryFreshAt: '2026-08-11T17:59:50Z' },
    { providerId: 'ollama', providerName: 'Ollama', providerClass: 'local', connectionState: 'connected', activityState: 'idle', billingEnabled: false, fallbackEnabled: false, tokenTotal: 900, telemetrySource: 'local-provider', telemetryFreshAt: '2026-08-11T17:59:50Z' },
    { providerId: 'stale', providerName: 'Old gateway', providerClass: 'unknown', connectionState: 'connected', activityState: 'active', telemetrySource: 'old', telemetryFreshAt: '2026-08-11T17:00:00Z' }
  ] } });
  const projection = buildSidebarProjection(snapshot, { nowMs: NOW });
  assert.equal(projection.providerState.providers[0].budgetPercent, 88);
  assert.equal(projection.providerState.providers[0].budgetRemaining, 3);
  assert.equal(projection.providerState.providers[2].stale, true);
  assert.equal(projection.providerState.providers[2].activityState, 'idle');
  assert.equal(projection.attention.some(item => item.id === 'fallback-openai'), true);
  assert.equal(projection.attention.some(item => item.id === 'billing-openai'), true);
});

test('S09 provider subsystem distinguishes unconfigured from unavailable telemetry', () => {
  const unconfigured = buildSidebarProjection(fixture(), { nowMs: NOW });
  assert.equal(unconfigured.providerState.configuredCount, 0);
  assert.equal(unconfigured.status.subsystems.find(item => item.id === 'provider').state, 'unconfigured');

  const configured = fixture({ snapshot: { enterpriseState: { execution_policy: { provider_allowlist: ['openai'] } } } });
  assert.equal(buildSidebarProjection(configured, { nowMs: NOW }).status.subsystems.find(item => item.id === 'provider').state, 'unavailable');
});

test('S10 idle, disconnected, degraded, and recovering states remain distinct', () => {
  const idle = fixture(); idle.coordinationData.state.active_plan = null; idle.coordinationData.state.plans[0].status = 'completed'; idle.coordinationData.state.plans[0].completed_utc = '2026-08-11T17:50:00Z';
  assert.equal(buildSidebarProjection(idle, { nowMs: NOW }).execution, null);
  const disconnected = buildSidebarProjection({ connected: false, generatedAt: '2026-08-11T18:00:00Z', source: {}, health: {}, attention: [] }, { nowMs: NOW });
  assert.equal(disconnected.status.state, 'disconnected');
  const degraded = fixture(); degraded.coordinationData.event_log_health.status = 'degraded';
  assert.equal(buildSidebarProjection(degraded, { nowMs: NOW }).status.state, 'degraded');
  const recovering = fixture({ snapshot: { recovery: { active: true } } });
  assert.equal(buildSidebarProjection(recovering, { nowMs: NOW }).status.state, 'recovering');
});
