'use strict';

const SNAPSHOT_SCHEMA_VERSION = 'px.sidebar.snapshot/1.0';
const AGENT_STALE_MS = 5 * 60_000;
const AGENT_RETENTION_MS = 15 * 60_000;
const PROVIDER_STALE_MS = 2 * 60_000;
const MAX_WAVES = 12;
const MAX_TASKS = 80;
const MAX_SUBTASKS = 12;

const COMPLETE = new Set(['reconciled']);
const ACTIVE = new Set(['claimed', 'in_progress', 'active', 'running']);
const VERIFYING = new Set(['completed', 'verifying']);
const BLOCKED = new Set(['blocked', 'failed']);
const QUEUED = new Set(['planned', 'ready', 'released', 'queued', 'waiting']);
const DISPOSITIONED = new Set(['cancelled', 'skipped']);

function boundedText(value, fallback = '', limit = 240) {
  const text = String(value ?? fallback).replace(/[\u0000-\u001f\u007f]/g, ' ').trim();
  return (text || fallback).slice(0, limit);
}

function safeId(value, fallback = 'unknown') {
  const text = String(value ?? '').trim();
  return /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(text) ? text : fallback;
}

function finite(value, fallback = null) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function timestamp(value) {
  const parsed = Date.parse(String(value || ''));
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : null;
}

function statusGroup(status) {
  const value = String(status || 'queued').toLowerCase();
  if (COMPLETE.has(value)) return 'complete';
  if (ACTIVE.has(value)) return 'active';
  if (VERIFYING.has(value)) return 'verifying';
  if (BLOCKED.has(value)) return value === 'failed' ? 'failed' : 'blocked';
  if (DISPOSITIONED.has(value)) return value;
  return QUEUED.has(value) ? 'queued' : 'queued';
}

function approvedDisposition(task) {
  const group = statusGroup(task.status);
  if (!DISPOSITIONED.has(group)) return false;
  return task.disposition_approved === true || task.disposition?.approved === true;
}

function taskWeight(task) {
  const value = finite(task.weight ?? task.task_weight, 1);
  return value > 0 && value <= 1_000_000 ? value : 1;
}

function authoritativeProgress(tasks) {
  const eligible = tasks.filter(task => !approvedDisposition(task));
  const denominator = eligible.reduce((sum, task) => sum + taskWeight(task), 0);
  const numerator = eligible.filter(task => statusGroup(task.status) === 'complete').reduce((sum, task) => sum + taskWeight(task), 0);
  return {
    numerator,
    denominator,
    percent: denominator ? Math.round((numerator / denominator) * 1000) / 10 : null
  };
}

function dependencyLevels(tasks) {
  const byId = new Map(tasks.map(task => [String(task.id), task]));
  const memo = new Map();
  const visit = (task, stack = new Set()) => {
    if (memo.has(task.id)) return memo.get(task.id);
    if (stack.has(task.id)) return 0;
    const next = new Set(stack); next.add(task.id);
    const dependencies = (task.depends_on || []).map(id => byId.get(String(id))).filter(Boolean);
    const level = dependencies.length ? Math.max(...dependencies.map(item => visit(item, next))) + 1 : 0;
    memo.set(task.id, Math.min(MAX_WAVES - 1, level));
    return level;
  };
  for (const task of tasks) visit(task);
  return memo;
}

function taskRow(task) {
  const group = statusGroup(task.status);
  const taskId = safeId(task.id, 'task');
  const subtasks = (Array.isArray(task.subtasks) ? task.subtasks : []).slice(0, MAX_SUBTASKS).map((subtask, index) => {
    const subtaskId = safeId(subtask.id, `${taskId}-subtask-${index + 1}`);
    return {
      id: safeId(`${taskId}.${subtaskId}`, `${taskId}.subtask-${index + 1}`),
      name: boundedText(subtask.title || subtask.name, `Subtask ${index + 1}`),
      status: statusGroup(subtask.status),
      progressPercent: statusGroup(subtask.status) === 'complete' ? 100 : null
    };
  });
  return {
    id: taskId, name: boundedText(task.title || task.id, 'Untitled task'), status: group,
    weight: taskWeight(task), progressPercent: group === 'complete' ? 100 : null,
    claimId: null, updatedAt: timestamp(task.updated_utc), subtasks
  };
}

function projectWaves(tasks, claims) {
  const levels = dependencyLevels(tasks);
  const groups = new Map();
  for (const task of tasks.slice(0, MAX_TASKS)) {
    const explicit = safeId(task.wave_id || '', '');
    const level = levels.get(task.id) || 0;
    const id = explicit || `wave-${level + 1}`;
    if (!groups.has(id)) groups.set(id, { id, level, name: boundedText(task.wave_name, `Wave ${level + 1}`), tasks: [] });
    const row = taskRow(task);
    row.claimId = safeId(claims.find(claim => claim.task_id === task.id)?.id || '', '') || null;
    groups.get(id).tasks.push(row);
  }
  return [...groups.values()].sort((left, right) => left.level - right.level || left.id.localeCompare(right.id)).slice(0, MAX_WAVES).map((wave, index) => {
    const progress = authoritativeProgress(wave.tasks.map(task => ({ status: task.status, weight: task.weight })));
    return { id: wave.id, name: wave.name || `Wave ${index + 1}`, index: index + 1, status: wave.tasks.every(task => task.status === 'complete') ? 'complete' : wave.tasks.some(task => ['active', 'verifying', 'blocked', 'failed'].includes(task.status)) ? 'active' : 'queued', progressPercent: progress.percent, tasks: wave.tasks };
  });
}

function punch(tasks) {
  const counts = { complete: 0, active: 0, queued: 0, blocked: 0, verifying: 0, excluded: 0 };
  for (const task of tasks) {
    if (approvedDisposition(task)) { counts.excluded += 1; continue; }
    const group = statusGroup(task.status);
    if (group === 'complete') counts.complete += 1;
    else if (group === 'active') counts.active += 1;
    else if (group === 'blocked' || group === 'failed') counts.blocked += 1;
    else if (group === 'verifying') counts.verifying += 1;
    else counts.queued += 1;
  }
  return { ...counts, total: counts.complete + counts.active + counts.queued + counts.blocked + counts.verifying };
}

function activeAgents(state, tasks, nowMs, staleMs) {
  const claims = state.claims || [];
  const taskById = new Map(tasks.map(task => [task.id, task]));
  return (state.sessions || []).map(session => {
    const heartbeat = timestamp(session.heartbeat_utc || session.last_heartbeat_at);
    const age = heartbeat ? Math.max(0, nowMs - Date.parse(heartbeat)) : Infinity;
    const claim = claims.find(item => item.status === 'active' && item.actor?.session_id === session.session_id);
    const task = claim ? taskById.get(claim.task_id) : tasks.find(item => item.owner?.session_id === session.session_id);
    const taskStatus = statusGroup(task?.status);
    return {
      agentId: safeId(session.actor_id, 'unknown-agent'), displayName: boundedText(session.display_name || session.actor_id, 'Unknown agent'),
      type: boundedText(session.type || session.harness, 'agent', 80), host: boundedText(session.host, '', 120) || null,
      ide: boundedText(session.harness, '', 120) || null, taskId: task ? safeId(task.id, 'task') : null,
      taskName: task ? boundedText(task.title || task.id, 'Task') : null, claimId: claim ? safeId(claim.id, 'claim') : null,
      orchestrationId: safeId(claim?.orchestration_id || '', '') || null,
      state: age > staleMs ? 'stale' : taskStatus === 'blocked' ? 'blocked' : taskStatus === 'verifying' ? 'verifying' : claim ? 'active' : 'waiting',
      progressPercent: taskStatus === 'complete' ? 100 : null, lastHeartbeatAt: heartbeat, heartbeatAgeMs: Number.isFinite(age) ? Math.round(age) : null
    };
  }).filter(agent => agent.state !== 'stale' || (agent.heartbeatAgeMs != null && agent.heartbeatAgeMs <= AGENT_RETENTION_MS)).slice(0, 12);
}

const RECENT_OPERATIONS = new Set(['parallel-plan-created', 'task-claimed', 'task-progress-recorded', 'task-reconciled', 'task-released', 'task-lease-renewed', 'orchestration-started', 'orchestration-updated', 'orchestration-completed', 'orchestration-failed', 'validation-completed', 'provider-request-completed', 'provider-request-failed', 'provider-fallback-activated']);

function recentEvents(events) {
  return (events || []).filter(event => RECENT_OPERATIONS.has(String(event.operation || ''))).slice(-5).reverse().map(event => ({
    id: safeId(event.event_id, 'event'), kind: safeId(event.operation, 'event'),
    label: boundedText(String(event.operation || 'event').replaceAll('-', ' '), 'Operational event'),
    state: /failed/.test(event.operation || '') ? 'failed' : /progress|started|claimed|updated/.test(event.operation || '') ? 'active' : 'complete',
    occurredAt: timestamp(event.timestamp), entityType: event.result?.task_id ? 'task' : event.result?.plan_id ? 'plan' : null,
    entityId: safeId(event.result?.task_id || event.result?.plan_id || '', '') || null
  }));
}

function activeOrchestrations(snapshot) {
  const candidates = snapshot.orchestrations || snapshot.coordinationData?.state?.orchestrations || snapshot.coordinationData?.state?.team_fabric?.work_rooms || [];
  return candidates.filter(item => ['running', 'waiting', 'verifying', 'blocked', 'recovering', 'active'].includes(String(item.status || item.state || '').toLowerCase())).slice(0, 8).map(item => ({
    id: safeId(item.id, 'orchestration'), name: boundedText(item.name || item.title || item.id, 'Orchestration'), state: String(item.status || item.state || 'running').toLowerCase() === 'active' ? 'running' : String(item.status || item.state || 'running').toLowerCase(), updatedAt: timestamp(item.updated_utc || item.updatedAt)
  }));
}

function providerProjection(snapshot, nowMs) {
  const telemetry = Array.isArray(snapshot.providerActivity) ? snapshot.providerActivity : [];
  const providers = telemetry.slice(0, 12).map(item => {
    const freshAt = timestamp(item.telemetryFreshAt || item.telemetry_fresh_at);
    const stale = !freshAt || nowMs - Date.parse(freshAt) > PROVIDER_STALE_MS;
    const spend = finite(item.spendCurrent ?? item.spend_current);
    const limit = finite(item.budgetLimit ?? item.budget_limit);
    const percent = finite(item.budgetPercent ?? item.budget_percent, spend != null && limit > 0 ? (spend / limit) * 100 : null);
    const providerClass = ['billable-api', 'subscription', 'enterprise-budget', 'local', 'unknown'].includes(item.providerClass || item.provider_class) ? (item.providerClass || item.provider_class) : 'unknown';
    return {
      providerId: safeId(item.providerId || item.provider_id, 'unknown-provider'), providerName: boundedText(item.providerName || item.provider_name, 'Unknown provider'), providerClass,
      connectionState: stale ? 'unknown' : boundedText(item.connectionState || item.connection_state, 'unknown', 24).toLowerCase(),
      activityState: stale ? 'idle' : boundedText(item.activityState || item.activity_state, 'idle', 24).toLowerCase(),
      billingEnabled: typeof (item.billingEnabled ?? item.billing_enabled) === 'boolean' ? (item.billingEnabled ?? item.billing_enabled) : null,
      fallbackEnabled: typeof (item.fallbackEnabled ?? item.fallback_enabled) === 'boolean' ? (item.fallbackEnabled ?? item.fallback_enabled) : null,
      fallbackActive: item.fallbackActive === true || item.fallback_active === true,
      currentTaskId: safeId(item.currentTaskId || item.current_task_id || '', '') || null,
      currentTaskName: boundedText(item.currentTaskName || item.current_task_name, '', 240) || null,
      currentAgentName: boundedText(item.currentAgentName || item.current_agent_name, '', 160) || null,
      spendCurrent: spend, budgetLimit: limit,
      budgetRemaining: finite(item.budgetRemaining ?? item.budget_remaining, spend != null && limit != null ? Math.max(0, limit - spend) : null),
      budgetPercent: percent == null ? null : Math.max(0, Math.round(percent * 10) / 10),
      tokenTotal: finite(item.tokenTotal ?? item.token_total), tokenBudget: finite(item.tokenBudget ?? item.token_budget),
      requestCount: finite(item.requestCount ?? item.request_count), ratePerMinute: finite(item.ratePerMinute ?? item.rate_per_minute),
      currency: boundedText(item.currency, '', 8) || null, telemetrySource: boundedText(item.telemetrySource || item.telemetry_source, 'unknown', 120),
      telemetryFreshAt: freshAt, stale
    };
  }).sort((left, right) => {
    const priority = provider => provider.fallbackActive ? 0 : provider.activityState === 'active' && !provider.stale ? 1 : provider.stale ? 3 : 2;
    return priority(left) - priority(right) || left.providerName.localeCompare(right.providerName);
  });
  const policy = snapshot.enterpriseState?.execution_policy || {};
  const configuredCount = new Set([...(policy.provider_allowlist || []), ...providers.map(item => item.providerId)]).size;
  return { providers, configuredCount, telemetryAvailable: telemetry.length > 0, activeCount: providers.filter(item => item.activityState === 'active' && !item.stale).length };
}

function operationalStatus(snapshot, coordination) {
  if (!snapshot?.connected) return 'disconnected';
  if (snapshot.recovery?.active || snapshot.health?.state === 'recovering') return 'recovering';
  if (snapshot.health?.state === 'blocked') return 'blocked';
  if (coordination?.event_log_health?.status === 'degraded' || snapshot.health?.reason || snapshot.health?.authoritative !== true || snapshot.health?.ready !== true) return 'degraded';
  return 'connected';
}

function runtimeSubsystemState(snapshot) {
  if (!snapshot?.connected) return 'unavailable';
  if (snapshot.health?.state === 'blocked' || snapshot.health?.state === 'recovering') return 'degraded';
  return snapshot.health?.authoritative === true && snapshot.health?.ready === true ? 'healthy' : 'degraded';
}

function coordinationSubsystemState(coordination) {
  const status = String(coordination?.event_log_health?.status || '').toLowerCase();
  if (status === 'degraded') return 'degraded';
  if (status === 'healthy' || status === 'valid') return 'healthy';
  return coordination?.state ? 'degraded' : 'unavailable';
}

function buildSidebarProjection(snapshot = {}, options = {}) {
  const started = process.hrtime.bigint();
  const nowMs = Number.isFinite(options.nowMs) ? options.nowMs : Date.now();
  const coordination = snapshot.coordinationData || options.coordination || null;
  const state = coordination?.state || {};
  const activePlan = (state.plans || []).find(plan => plan.id === state.active_plan) || null;
  const planTasks = activePlan ? (state.tasks || []).filter(task => activePlan.task_ids.includes(task.id)) : [];
  const progress = authoritativeProgress(planTasks);
  const waves = projectWaves(planTasks, state.claims || []);
  const punchCard = punch(planTasks);
  const agents = activeAgents(state, planTasks, nowMs, finite(options.agentStaleMs, AGENT_STALE_MS));
  const orchestrations = activeOrchestrations(snapshot);
  const recent = recentEvents(coordination?.events);
  const providerState = providerProjection(snapshot, nowMs);
  const attention = [...(snapshot.attention || [])].slice(0, 12).map((item, index) => ({
    id: safeId(item.id, `attention-${index + 1}`), severity: ['info', 'warning', 'error', 'critical'].includes(item.severity) ? item.severity : 'warning',
    title: boundedText(item.title, 'Attention required'), detail: boundedText(item.detail, '', 500) || null, entityType: null, entityId: null
  }));
  if (punchCard.blocked && !attention.some(item => item.id === 'blocked-tasks')) attention.push({ id: 'blocked-tasks', severity: 'error', title: `${punchCard.blocked} blocked task${punchCard.blocked === 1 ? '' : 's'}`, detail: null, entityType: 'plan', entityId: activePlan ? safeId(activePlan.id, 'plan') : null });
  for (const provider of providerState.providers) {
    if (provider.fallbackActive) attention.push({ id: `fallback-${provider.providerId}`, severity: 'critical', title: `Billable fallback in use: ${provider.providerName}`, detail: null, entityType: 'provider', entityId: provider.providerId });
    if (provider.activityState === 'active' && provider.providerClass !== 'local' && provider.billingEnabled == null) attention.push({ id: `billing-${provider.providerId}`, severity: 'warning', title: `Billing identity unverified: ${provider.providerName}`, detail: 'Active route has incomplete billing telemetry.', entityType: 'provider', entityId: provider.providerId });
  }
  const status = operationalStatus(snapshot, coordination);
  const lastPlan = !activePlan ? [...(state.plans || [])].reverse().find(plan => plan.status === 'completed') : null;
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
  return {
    schemaVersion: SNAPSHOT_SCHEMA_VERSION, revision: Math.max(0, Math.trunc(finite(state.revision, 0))), generatedAt: new Date(nowMs).toISOString(),
    status: {
      state: status, label: status.toUpperCase(), connected: snapshot.connected === true, version: boundedText(snapshot.source?.version, 'unavailable', 40),
      revision: Math.max(0, Math.trunc(finite(state.revision, 0))), reason: boundedText(snapshot.reason || snapshot.health?.reason, '', 500) || null,
      lastConnectedAt: timestamp(snapshot.generatedAt), subsystems: [
        { id: 'runtime', label: 'Runtime', state: runtimeSubsystemState(snapshot) },
        { id: 'coordination', label: 'Coordination', state: coordinationSubsystemState(coordination) },
        {
          id: 'provider', label: 'Provider telemetry',
          state: providerState.telemetryAvailable ? 'healthy' : providerState.configuredCount > 0 ? 'unavailable' : 'unconfigured'
        }
      ]
    },
    execution: activePlan ? {
      planId: safeId(activePlan.id, 'plan'), planName: boundedText(activePlan.objective, 'Active plan', 300),
      currentWaveId: waves.find(wave => wave.status === 'active')?.id || waves.find(wave => wave.status !== 'complete')?.id || null,
      currentWaveName: waves.find(wave => wave.status === 'active')?.name || waves.find(wave => wave.status !== 'complete')?.name || null,
      completedTasks: punchCard.complete, totalEligibleTasks: punchCard.total, activeTasks: punchCard.active,
      blockedTasks: punchCard.blocked, queuedTasks: punchCard.queued, verifyingTasks: punchCard.verifying,
      progressPercent: progress.percent, activeAgentCount: agents.filter(agent => agent.state !== 'stale').length,
      activeOrchestrationCount: orchestrations.length, stateRevision: Math.max(0, Math.trunc(finite(state.revision, 0))), lastUpdatedAt: timestamp(state.updated_utc) || new Date(nowMs).toISOString()
    } : null,
    lastRun: lastPlan ? { planId: safeId(lastPlan.id, 'plan'), planName: boundedText(lastPlan.objective, 'Completed plan'), completedAt: timestamp(lastPlan.completed_utc), completedTasks: (lastPlan.task_ids || []).filter(id => statusGroup((state.tasks || []).find(task => task.id === id)?.status) === 'complete').length, totalTasks: (lastPlan.task_ids || []).length } : null,
    waves, punch: punchCard, agents, orchestrations, recent, attention: attention.slice(0, 12), providerState,
    ui: { expandedWaveIds: (options.expandedWaveIds || []).map(id => safeId(id, '')).filter(Boolean).slice(0, 40), expandedTaskIds: (options.expandedTaskIds || []).map(id => safeId(id, '')).filter(Boolean).slice(0, 80), selectedProviderId: safeId(options.selectedProviderId || '', '') || null },
    performance: { projectionMs: Math.round(elapsedMs * 100) / 100, source: 'single-bounded-host-snapshot', workspaceScan: false }
  };
}

module.exports = { SNAPSHOT_SCHEMA_VERSION, buildSidebarProjection, authoritativeProgress, statusGroup, projectWaves };
