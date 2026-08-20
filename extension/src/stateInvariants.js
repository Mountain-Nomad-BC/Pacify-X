'use strict';

const crypto = require('crypto');

const SCHEMA_VERSION = '1.2';
const TASK_STATUSES = new Set(['planned', 'ready', 'claimed', 'in_progress', 'waiting', 'blocked', 'completed', 'reconciled', 'released']);
const CLAIM_STATUSES = new Set(['active', 'expired', 'released']);
const PLAN_STATUSES = new Set(['active', 'superseded', 'completed']);
const SESSION_STATUSES = new Set(['active', 'stale']);
const CLAIM_MODES = new Set(['exclusive', 'shared', 'informational']);
const CLAIM_AUTHORITIES = new Set(['local', 'speculative', 'team_authoritative', 'stale']);
const MEMORY_COUNTERS = ['session_records', 'project_records', 'state_records', 'system_candidates'];

function sha(value) {
  return crypto.createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex');
}

function fail(code, detail) {
  throw new Error(`coordination-invariant:${code}${detail == null ? '' : `:${String(detail)}`}`);
}

function isRecord(value) { return Boolean(value) && typeof value === 'object' && !Array.isArray(value); }
function requireRecord(value, code) { if (!isRecord(value)) fail(code); return value; }
function requireArray(value, code) { if (!Array.isArray(value)) fail(code); return value; }
function requireText(value, code) { if (typeof value !== 'string' || !value.trim()) fail(code); return value; }
function requireEnum(value, choices, code) { if (!choices.has(value)) fail(code, value); return value; }
function requireNonNegativeFinite(value, code, integer = false) {
  if (!Number.isFinite(value) || value < 0 || (integer && !Number.isSafeInteger(value))) fail(code, value);
  return value;
}
function requireUnique(items, selector, code) {
  const seen = new Set();
  for (const item of items) {
    const key = selector(item);
    if (seen.has(key)) fail(code, key);
    seen.add(key);
  }
  return seen;
}

function sealedHash(value, field) {
  const copy = { ...value };
  copy[field] = null;
  return sha(copy);
}

function eventHash(event) {
  const copy = { ...event };
  delete copy.event_sha256;
  return sha(copy);
}

function normalizeTarget(value) {
  let target = requireText(value, 'claim-target-empty').trim().replaceAll('\\', '/').replace(/^\.\//, '').replace(/\/{2,}/g, '/');
  target = target.replace(/\/(\*\*|\*)$/, '').replace(/\/$/, '').toLowerCase();
  if (!target || target.startsWith('/') || target === '..' || target.startsWith('../') || target.includes('/../')) fail('claim-target-invalid', value);
  return target;
}

function overlaps(left, right) {
  const a = normalizeTarget(left); const b = normalizeTarget(right);
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`);
}

function assertActor(actor, code) {
  requireRecord(actor, `${code}-shape`);
  requireText(actor.actor_id, `${code}-actor-id`);
  requireText(actor.session_id, `${code}-session-id`);
  requireText(actor.harness, `${code}-harness`);
}

function assertBudget(task) {
  const budget = requireRecord(task.budget, `budget-shape:${task.id}`);
  for (const field of ['max_minutes', 'max_tokens', 'max_cost_usd']) {
    if (budget[field] !== null) requireNonNegativeFinite(budget[field], `budget-${field}:${task.id}`);
  }
  if (typeof budget.hard_stop !== 'boolean') fail('budget-hard-stop', task.id);
  const usage = requireRecord(task.usage, `usage-shape:${task.id}`);
  for (const field of ['minutes', 'tokens', 'cost_usd']) requireNonNegativeFinite(usage[field], `usage-${field}:${task.id}`);
  const exceeded = (budget.max_minutes !== null && usage.minutes > budget.max_minutes)
    || (budget.max_tokens !== null && usage.tokens > budget.max_tokens)
    || (budget.max_cost_usd !== null && usage.cost_usd > budget.max_cost_usd);
  const expected = exceeded ? (budget.hard_stop ? 'hard_stop' : 'soft_limit') : 'healthy';
  if (usage.status !== expected) fail('usage-status', `${task.id}:${usage.status}:${expected}`);
  if (expected === 'hard_stop' && task.status !== 'blocked') fail('hard-stop-not-blocked', task.id);
}

function assertTaskDag(tasks, taskIds) {
  const visiting = new Set(); const visited = new Set();
  const byId = new Map(tasks.map(task => [task.id, task]));
  const visit = taskId => {
    if (visiting.has(taskId)) fail('task-cycle', taskId);
    if (visited.has(taskId)) return;
    visiting.add(taskId);
    for (const dependency of byId.get(taskId).depends_on) {
      if (!taskIds.has(dependency)) fail('task-dependency-missing', `${taskId}:${dependency}`);
      visit(dependency);
    }
    visiting.delete(taskId); visited.add(taskId);
  };
  for (const task of tasks) visit(task.id);
}

function assertCoordinationState(state, options = {}) {
  requireRecord(state, 'state-shape');
  if (state.schema_version !== SCHEMA_VERSION) fail('schema-version', state.schema_version);
  const project = requireRecord(state.project, 'project-shape');
  requireText(project.id, 'project-id'); requireText(project.root, 'project-root');
  requireNonNegativeFinite(state.revision, 'revision', true);
  if (!Number.isFinite(Date.parse(state.updated_utc))) fail('updated-time', state.updated_utc);
  const plans = requireArray(state.plans, 'plans-shape');
  const tasks = requireArray(state.tasks, 'tasks-shape');
  const claims = requireArray(state.claims, 'claims-shape');
  const sessions = requireArray(state.sessions, 'sessions-shape');
  const planIds = requireUnique(plans, plan => requireText(plan?.id, 'plan-id'), 'plan-id-duplicate');
  const taskIds = requireUnique(tasks, task => requireText(task?.id, 'task-id'), 'task-id-duplicate');
  requireUnique(claims, claim => requireText(claim?.id, 'claim-id'), 'claim-id-duplicate');
  requireUnique(sessions, session => requireText(session?.session_id, 'session-id'), 'session-id-duplicate');

  for (const task of tasks) {
    requireEnum(task.status, TASK_STATUSES, `task-status:${task.id}`);
    requireArray(task.depends_on, `task-dependencies:${task.id}`);
    requireArray(task.claim_targets, `task-targets:${task.id}`).forEach(normalizeTarget);
    requireUnique(task.depends_on, value => requireText(value, `task-dependency:${task.id}`), `task-dependency-duplicate:${task.id}`);
    if (task.owner !== null) assertActor(task.owner, `task-owner:${task.id}`);
    assertBudget(task);
  }
  assertTaskDag(tasks, taskIds);

  let activePlans = 0;
  for (const plan of plans) {
    requireEnum(plan.status, PLAN_STATUSES, `plan-status:${plan.id}`);
    if (plan.status === 'active') activePlans += 1;
    const members = requireArray(plan.task_ids, `plan-task-ids:${plan.id}`);
    requireUnique(members, value => requireText(value, `plan-task-id:${plan.id}`), `plan-task-duplicate:${plan.id}`);
    for (const taskId of members) if (!taskIds.has(taskId)) fail('plan-task-missing', `${plan.id}:${taskId}`);
    const memberIds = new Set(members);
    for (const taskId of members) for (const dependency of tasks.find(task => task.id === taskId).depends_on) {
      if (!memberIds.has(dependency)) fail('plan-dependency-outside-plan', `${plan.id}:${taskId}:${dependency}`);
    }
  }
  if (activePlans > 1) fail('multiple-active-plans', activePlans);
  if (state.active_plan === null) {
    if (activePlans !== 0) fail('active-plan-pointer-missing');
  } else {
    if (!planIds.has(state.active_plan)) fail('active-plan-missing', state.active_plan);
    if (plans.find(plan => plan.id === state.active_plan).status !== 'active') fail('active-plan-status', state.active_plan);
    if (activePlans !== 1) fail('active-plan-count', activePlans);
  }

  const fabric = requireRecord(state.team_fabric, 'team-fabric-shape');
  const fences = requireRecord(fabric.fencing_by_target, 'fencing-map-shape');
  for (const [target, token] of Object.entries(fences)) {
    if (normalizeTarget(target) !== target) fail('fencing-target-not-normalized', target);
    requireNonNegativeFinite(token, `fencing-token:${target}`, true);
  }

  const activeClaims = claims.filter(claim => claim.status === 'active');
  for (const claim of claims) {
    requireEnum(claim.status, CLAIM_STATUSES, `claim-status:${claim.id}`);
    requireEnum(claim.mode, CLAIM_MODES, `claim-mode:${claim.id}`);
    requireEnum(claim.authority, CLAIM_AUTHORITIES, `claim-authority:${claim.id}`);
    if (!taskIds.has(claim.task_id)) fail('claim-task-missing', claim.id);
    assertActor(claim.actor, `claim-actor:${claim.id}`);
    const targets = requireArray(claim.targets, `claim-targets:${claim.id}`).map(normalizeTarget);
    if (!targets.length) fail('claim-targets-empty', claim.id);
    requireUnique(targets, value => value, `claim-target-duplicate:${claim.id}`);
    const tokens = requireRecord(claim.fencing_tokens, `claim-fencing-shape:${claim.id}`);
    const task = tasks.find(item => item.id === claim.task_id);
    for (const target of targets) {
      if (!task.claim_targets.some(declared => target === normalizeTarget(declared) || target.startsWith(`${normalizeTarget(declared)}/`))) fail('claim-outside-task-scope', `${claim.id}:${target}`);
    }
    for (const target of targets) {
      const token = tokens[target];
      requireNonNegativeFinite(token, `claim-fencing-token:${claim.id}:${target}`, true);
      if (token < 1) fail('claim-fencing-token-zero', `${claim.id}:${target}`);
      if (claim.status === 'active' && fences[target] !== token) fail('active-claim-fence-not-current', `${claim.id}:${target}`);
    }
    if (claim.status === 'active') {
      if (!task.owner || task.owner.actor_id !== claim.actor.actor_id || task.owner.session_id !== claim.actor.session_id) fail('active-claim-owner-mismatch', claim.id);
      if (['planned', 'ready', 'released', 'reconciled'].includes(task.status)) fail('active-claim-task-status', `${claim.id}:${task.status}`);
    }
  }
  requireUnique(activeClaims, claim => claim.task_id, 'multiple-active-claims-for-task');
  for (let left = 0; left < activeClaims.length; left += 1) for (let right = left + 1; right < activeClaims.length; right += 1) {
    const a = activeClaims[left]; const b = activeClaims[right];
    if (a.mode === 'informational' || b.mode === 'informational' || (a.mode === 'shared' && b.mode === 'shared')) continue;
    for (const at of a.targets) for (const bt of b.targets) if (overlaps(at, bt)) fail('active-claim-overlap', `${a.id}:${b.id}`);
  }

  for (const session of sessions) {
    assertActor(session, `session:${session.session_id}`);
    requireEnum(session.status, SESSION_STATUSES, `session-status:${session.session_id}`);
  }
  const memory = requireRecord(state.memory, 'memory-counters-shape');
  for (const counter of MEMORY_COUNTERS) requireNonNegativeFinite(memory[counter], `memory-counter:${counter}`, true);

  if (options.requireSeal !== false) {
    if (!/^[a-f0-9]{64}$/.test(String(state.state_hash || ''))) fail('state-seal-format');
    if (state.state_hash !== sealedHash(state, 'state_hash')) fail('state-seal-mismatch');
  }
  return true;
}

function assertEventAncestry(events, expectedStateHash, expectedProjectId = null) {
  requireArray(events, 'event-chain-shape');
  let previous = null; const eventIds = new Set();
  for (const event of events) {
    requireRecord(event, 'event-shape');
    if (event.schema_version !== SCHEMA_VERSION) fail('event-schema', event.event_id);
    requireText(event.event_id, 'event-id');
    if (eventIds.has(event.event_id)) fail('event-id-duplicate', event.event_id);
    eventIds.add(event.event_id);
    if (!Number.isFinite(Date.parse(event.timestamp))) fail('event-time', event.event_id);
    if (expectedProjectId !== null && event.project_id !== expectedProjectId) fail('event-project', event.event_id);
    if (!/^[a-f0-9]{64}$/.test(String(event.before_hash || '')) || !/^[a-f0-9]{64}$/.test(String(event.after_hash || ''))) fail('event-state-hash-format', event.event_id);
    if (!/^[a-f0-9]{64}$/.test(String(event.event_sha256 || '')) || event.event_sha256 !== eventHash(event)) fail('event-seal', event.event_id);
    if (previous && (event.previous_event_sha256 !== previous.event_sha256 || event.before_hash !== previous.after_hash)) fail('event-ancestry', event.event_id);
    previous = event;
  }
  if (previous && previous.after_hash !== expectedStateHash) fail('event-state-head', previous.event_id);
  return true;
}

function assertCoordinationTransition({ previous, next, operation, previousEvents = [], event }) {
  assertCoordinationState(previous, { requireSeal: false });
  assertEventAncestry(previousEvents, previous.state_hash, previous.project.id);
  assertCoordinationState(next);
  if (next.revision !== previous.revision + 1) fail('revision-transition', `${previous.revision}:${next.revision}`);
  if (next.schema_version !== previous.schema_version) fail('schema-transition');
  if (next.project.id !== previous.project.id || next.project.root !== previous.project.root) fail('project-transition');
  const beforeFences = previous.team_fabric.fencing_by_target;
  const afterFences = next.team_fabric.fencing_by_target;
  for (const [target, token] of Object.entries(beforeFences)) {
    if (!(target in afterFences)) fail('fencing-target-removed', target);
    if (!Number.isSafeInteger(afterFences[target]) || afterFences[target] < token) fail('fencing-regression', target);
  }
  const memoryCounter = operation === 'memory-captured' ? event?.result?.layer : null;
  const expectedMemoryField = memoryCounter === 'session' ? 'session_records'
    : memoryCounter === 'project' ? 'project_records'
      : memoryCounter === 'state' ? 'state_records'
        : memoryCounter === 'system_candidate' ? 'system_candidates' : null;
  if (operation === 'memory-captured' && !expectedMemoryField) fail('memory-layer-transition', memoryCounter);
  for (const field of MEMORY_COUNTERS) {
    const expected = previous.memory[field] + (field === expectedMemoryField ? 1 : 0);
    if (next.memory[field] !== expected) fail('memory-counter-transition', `${field}:${previous.memory[field]}:${next.memory[field]}`);
  }
  requireRecord(event, 'new-event-shape');
  if (event.schema_version !== SCHEMA_VERSION) fail('new-event-schema', event.event_id);
  requireText(event.event_id, 'new-event-id');
  if (previousEvents.some(item => item.event_id === event.event_id)) fail('new-event-id-duplicate', event.event_id);
  if (!Number.isFinite(Date.parse(event.timestamp))) fail('new-event-time', event.event_id);
  if (event.project_id !== next.project.id) fail('new-event-project', event.event_id);
  assertActor(event.actor, `new-event-actor:${event.event_id}`);
  if (event.operation !== operation) fail('event-operation', event.operation);
  if (event.before_hash !== previous.state_hash || event.after_hash !== next.state_hash) fail('event-state-link', event.event_id);
  const last = previousEvents.at(-1) || null;
  if (event.previous_event_sha256 !== (last?.event_sha256 || null)) fail('event-previous-link', event.event_id);
  if (event.payload_sha256 !== sha(event.result ?? null)) fail('event-payload-seal', event.event_id);
  if (event.event_sha256 !== eventHash(event)) fail('new-event-seal', event.event_id);
  return true;
}

module.exports = { SCHEMA_VERSION, sha, sealedHash, eventHash, assertCoordinationState, assertEventAncestry, assertCoordinationTransition };
