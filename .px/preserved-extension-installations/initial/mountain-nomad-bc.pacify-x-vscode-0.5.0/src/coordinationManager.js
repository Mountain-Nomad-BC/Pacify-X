'use strict';

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SCHEMA_VERSION = '1.2';
const MAX_TASKS = 250;
const MAX_EVENTS = 5000;
const MAX_TEXT = 12000;
const CLAIM_TTL_MINUTES = 120;

function now() { return new Date().toISOString(); }
function id(prefix) { return `${prefix}-${crypto.randomUUID()}`; }
function hash(value) { return crypto.createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex'); }
function cleanText(value, limit = MAX_TEXT) { return String(value || '').trim().slice(0, limit); }
function safeId(value, fallbackPrefix = 'item') {
  const result = cleanText(value, 160).toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
  return result || `${fallbackPrefix}-${crypto.randomUUID().slice(0, 8)}`;
}

function coordinationPaths(workspaceRoot) {
  const workspace = path.resolve(workspaceRoot || '');
  if (!workspaceRoot || workspace === path.parse(workspace).root) throw new Error('coordination-workspace-must-be-bounded');
  const root = path.join(workspace, '.engineering-bootstrap', 'coordination');
  return {
    workspace, root, state: path.join(root, 'state.json'), events: path.join(root, 'events.jsonl'),
    lock: path.join(root, '.coordination.lock'), receipts: path.join(root, 'receipts'),
    handoffJson: path.join(root, 'handoff.json'), handoffMarkdown: path.join(root, 'HANDOFF.md'),
    memory: {
      root: path.join(root, 'memory'), project: path.join(root, 'memory', 'project.jsonl'),
      state: path.join(root, 'memory', 'state.jsonl'), systemCandidates: path.join(root, 'memory', 'system-candidates.jsonl'),
      sessions: path.join(root, 'memory', 'sessions')
    }
  };
}

function defaultState(workspaceRoot) {
  return {
    schema_version: SCHEMA_VERSION, project: { id: safeId(path.basename(workspaceRoot), 'project'), root: path.resolve(workspaceRoot) },
    revision: 0, updated_utc: now(), state_hash: null, active_plan: null, plans: [], tasks: [], claims: [], sessions: [],
    memory: { session_records: 0, project_records: 0, state_records: 0, system_candidates: 0 },
    team_fabric: {
      enabled: true, mode: 'local-first', hub: { configured: false, connected: false, authoritative: false },
      fencing_by_target: {}, work_rooms: [], adapters: [], imports: [], budgets: {}
    },
    retrieval: { engine: 'deterministic-lexical', turbovec: { status: 'candidate-not-wired', active: false, reason: 'No admitted local TurboVec adapter was discovered.' } }
  };
}

function migrateState(state) {
  state.schema_version = SCHEMA_VERSION;
  state.plans ||= []; state.tasks ||= []; state.claims ||= []; state.sessions ||= [];
  state.memory ||= { session_records: 0, project_records: 0, state_records: 0, system_candidates: 0 };
  state.team_fabric ||= {};
  state.team_fabric.enabled = true;
  state.team_fabric.mode ||= 'local-first';
  state.team_fabric.hub ||= { configured: false, connected: false, authoritative: false };
  state.team_fabric.fencing_by_target ||= {};
  state.team_fabric.work_rooms ||= [];
  state.team_fabric.adapters ||= [];
  state.team_fabric.imports ||= [];
  state.team_fabric.budgets ||= {};
  return state;
}

function readJson(file, fallback) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return fallback; }
}

function ensureStore(paths) {
  fs.mkdirSync(paths.receipts, { recursive: true });
  fs.mkdirSync(paths.memory.sessions, { recursive: true });
  if (!fs.existsSync(paths.state)) {
    const state = defaultState(paths.workspace);
    state.state_hash = stateHash(state);
    atomicWrite(paths.state, state);
  }
}

function stateHash(state) {
  const copy = { ...state, state_hash: null };
  return hash(copy);
}

function atomicWrite(file, value) {
  const temporary = `${file}.${process.pid}.${crypto.randomUUID()}.tmp`;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  fs.renameSync(temporary, file);
}

function appendJsonl(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, `${JSON.stringify(value)}\n`, 'utf8');
}

function acquireLock(paths, timeoutMs = 4000) {
  ensureStore(paths);
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const fd = fs.openSync(paths.lock, 'wx');
      fs.writeFileSync(fd, JSON.stringify({ pid: process.pid, host: os.hostname(), acquired_utc: now() }));
      return () => { try { fs.closeSync(fd); } catch { /* closed */ } try { fs.unlinkSync(paths.lock); } catch { /* already released */ } };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      try {
        const age = Date.now() - fs.statSync(paths.lock).mtimeMs;
        if (age > 30_000) { fs.unlinkSync(paths.lock); continue; }
      } catch { continue; }
    }
  }
  throw new Error('coordination-lock-timeout');
}

function withState(workspaceRoot, actor, operation, mutator) {
  const paths = coordinationPaths(workspaceRoot);
  const release = acquireLock(paths);
  try {
    const state = migrateState(readJson(paths.state, defaultState(paths.workspace)));
    expireClaims(state); expireSessions(state);
    const beforeHash = state.state_hash || stateHash(state);
    const result = mutator(state, paths);
    state.revision = Number(state.revision || 0) + 1;
    state.updated_utc = now();
    state.state_hash = stateHash(state);
    const previousEvent = tailJsonl(paths.events, 1)[0] || null;
    const event = {
      schema_version: SCHEMA_VERSION, event_id: id('pxe'), timestamp: state.updated_utc, operation,
      project_id: state.project.id, actor: normalizeActor(actor), before_hash: beforeHash, after_hash: state.state_hash,
      authority: result?.authority || 'local', previous_event_sha256: previousEvent?.event_sha256 || null,
      payload_sha256: hash(result?.receipt || result || null), result: result?.receipt || result || null
    };
    event.event_sha256 = hash(event);
    atomicWrite(paths.state, state);
    appendJsonl(paths.events, event);
    writeReceipt(paths, event);
    writeHandoff(paths, state, event);
    return { state: publicState(state), event, result };
  } finally { release(); }
}

function normalizeActor(actor = {}) {
  return {
    actor_id: safeId(actor.actorId || actor.actor_id || 'unknown-actor', 'actor'),
    harness: cleanText(actor.harness || 'unknown-harness', 120), session_id: safeId(actor.sessionId || actor.session_id || 'unknown-session', 'session'),
    accountable_owner: cleanText(actor.accountableOwner || actor.accountable_owner || 'local-user', 160)
  };
}

function normalizeTarget(value) {
  let target = cleanText(value, 512).replaceAll('\\', '/').replace(/^\.\//, '').replace(/\/{2,}/g, '/');
  target = target.replace(/\/(\*\*|\*)$/, '').replace(/\/$/, '');
  if (!target || path.posix.isAbsolute(target) || target === '..' || target.startsWith('../') || target.includes('/../')) throw new Error('invalid-claim-target');
  return target.toLowerCase();
}

function overlap(left, right) {
  const a = normalizeTarget(left); const b = normalizeTarget(right);
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`);
}

function normalizeTask(input, index) {
  const taskId = safeId(input.id || input.task_id || `task-${index + 1}`, 'task');
  const claims = [...new Set([...(input.files || []), ...(input.areas || []), ...(input.claims || [])].map(normalizeTarget))];
  return {
    id: taskId, title: cleanText(input.title || taskId, 300), description: cleanText(input.description, 4000),
    status: 'planned', depends_on: [...new Set((input.dependsOn || input.depends_on || []).map(value => safeId(value, 'task'))) ],
    claim_targets: claims,
    read_scopes: [...new Set((input.readScopes || input.read_scopes || claims).map(normalizeTarget))],
    write_scopes: [...new Set((input.writeScopes || input.write_scopes || claims).map(normalizeTarget))],
    effect_scopes: [...new Set((input.effectScopes || input.effect_scopes || ['workspace-read']).map(value => cleanText(value, 120)).filter(Boolean))],
    goal_context: (input.goalContext || input.goal_context || []).map(value => cleanText(value, 1000)).filter(Boolean),
    budget: normalizeBudget(input.budget), usage: { minutes: 0, tokens: 0, cost_usd: 0, status: 'healthy' },
    authority_state: 'local', worktree: null, branch: null, preferred_harness: cleanText(input.harness || input.preferred_harness, 120) || null,
    preferred_agent: cleanText(input.agent || input.preferred_agent, 200) || null,
    owner: null, progress: [], outputs: [], created_utc: now(), updated_utc: now(), acceptance: (input.acceptance || []).map(value => cleanText(value, 1000)).filter(Boolean)
  };
}

function normalizeBudget(input = {}) {
  const bounded = (value, maximum) => value == null || value === '' ? null : Math.min(maximum, Math.max(0, Number(value)));
  return {
    max_minutes: bounded(input.maxMinutes ?? input.max_minutes, 525600),
    max_tokens: bounded(input.maxTokens ?? input.max_tokens, 1_000_000_000),
    max_cost_usd: bounded(input.maxCostUsd ?? input.max_cost_usd, 1_000_000),
    hard_stop: input.hardStop !== false && input.hard_stop !== false
  };
}

function dependencyClosure(tasks, start) {
  const byId = new Map(tasks.map(task => [task.id, task]));
  const seen = new Set();
  const visit = taskId => {
    if (seen.has(taskId)) return;
    seen.add(taskId);
    for (const dependency of byId.get(taskId)?.depends_on || []) visit(dependency);
  };
  visit(start);
  seen.delete(start);
  return seen;
}

function validateTaskGraph(tasks) {
  if (!tasks.length || tasks.length > MAX_TASKS) throw new Error('parallel-plan-task-count-out-of-range');
  const ids = new Set(tasks.map(task => task.id));
  if (ids.size !== tasks.length) throw new Error('parallel-plan-duplicate-task-id');
  for (const task of tasks) {
    if (!task.claim_targets.length) throw new Error(`parallel-plan-claim-required:${task.id}`);
    for (const dependency of task.depends_on) if (!ids.has(dependency)) throw new Error(`parallel-plan-missing-dependency:${task.id}:${dependency}`);
  }
  const visiting = new Set(); const visited = new Set(); const byId = new Map(tasks.map(task => [task.id, task]));
  const visit = taskId => {
    if (visiting.has(taskId)) throw new Error(`parallel-plan-cycle:${taskId}`);
    if (visited.has(taskId)) return;
    visiting.add(taskId);
    for (const dependency of byId.get(taskId).depends_on) visit(dependency);
    visiting.delete(taskId); visited.add(taskId);
  };
  for (const task of tasks) visit(task.id);
  const conflicts = [];
  for (let left = 0; left < tasks.length; left += 1) for (let right = left + 1; right < tasks.length; right += 1) {
    const a = tasks[left]; const b = tasks[right];
    const ordered = dependencyClosure(tasks, a.id).has(b.id) || dependencyClosure(tasks, b.id).has(a.id);
    if (ordered) continue;
    for (const at of a.claim_targets) for (const bt of b.claim_targets) if (overlap(at, bt)) conflicts.push({ left: a.id, right: b.id, left_target: at, right_target: bt });
  }
  if (conflicts.length) throw new Error(`parallel-claim-conflict:${JSON.stringify(conflicts.slice(0, 12))}`);
}

function createParallelPlan(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'parallel-plan-created', state => {
    const tasks = (input.tasks || []).map(normalizeTask);
    validateTaskGraph(tasks);
    const plan = {
      id: safeId(input.id || `plan-${Date.now()}`, 'plan'), objective: cleanText(input.objective, 4000), status: 'active',
      created_utc: now(), created_by: normalizeActor(actor), task_ids: tasks.map(task => task.id), acceptance: (input.acceptance || []).map(value => cleanText(value, 1000)).filter(Boolean)
    };
    if (!plan.objective) throw new Error('parallel-plan-objective-required');
    if (state.active_plan) {
      const previous = state.plans.find(item => item.id === state.active_plan);
      if (previous && previous.status === 'active') previous.status = 'superseded';
    }
    state.plans.push(plan); state.tasks.push(...tasks); state.active_plan = plan.id;
    return { receipt: { plan_id: plan.id, tasks: tasks.length, claim_conflicts: 0 } };
  });
}

function expireClaims(state) {
  const stamp = Date.now();
  for (const claim of state.claims || []) if (claim.status === 'active' && Date.parse(claim.expires_utc) <= stamp) {
    claim.status = 'expired'; claim.authority = 'stale';
  }
}

function expireSessions(state) {
  const cutoff = Date.now() - 15 * 60_000;
  for (const session of state.sessions || []) {
    if (session.status === 'active' && Date.parse(session.heartbeat_utc || session.started_utc) < cutoff) session.status = 'stale';
  }
}

function taskById(state, taskId) {
  const task = state.tasks.find(item => item.id === safeId(taskId, 'task'));
  if (!task) throw new Error('unknown-coordination-task');
  return task;
}

function claimTask(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'task-claimed', state => {
    const task = taskById(state, input.taskId || input.task_id);
    const principal = normalizeActor(actor);
    const existingOwnedClaim = state.claims.find(item => item.status === 'active' && item.task_id === task.id && item.actor.actor_id === principal.actor_id && item.actor.session_id === principal.session_id);
    if (existingOwnedClaim) return { receipt: { claim_id: existingOwnedClaim.id, task_id: task.id, targets: existingOwnedClaim.targets, expires_utc: existingOwnedClaim.expires_utc, idempotent: true } };
    const existingTaskClaim = state.claims.find(item => item.status === 'active' && item.task_id === task.id);
    if (existingTaskClaim) throw new Error(`task-lease-active:${existingTaskClaim.actor.actor_id}:${existingTaskClaim.actor.session_id}`);
    const incomplete = task.depends_on.filter(dependency => !['completed', 'reconciled'].includes(taskById(state, dependency).status));
    if (incomplete.length) throw new Error(`task-dependencies-incomplete:${incomplete.join(',')}`);
    const targets = (input.claimTargets || input.claim_targets || task.claim_targets).map(normalizeTarget);
    if (!targets.length) throw new Error('task-claim-target-required');
    for (const target of targets) if (!task.claim_targets.some(declared => target === declared || target.startsWith(`${declared}/`))) throw new Error(`task-claim-outside-declared-scope:${target}`);
    const mode = cleanText(input.mode || 'exclusive', 40);
    if (!['exclusive', 'shared', 'informational'].includes(mode)) throw new Error('unsupported-claim-mode');
    const requestedAuthority = cleanText(input.authority || 'local', 40);
    if (!['local', 'speculative', 'team_authoritative'].includes(requestedAuthority)) throw new Error('unsupported-claim-authority');
    if (requestedAuthority === 'team_authoritative' && !cleanText(input.authorityReceipt || input.authority_receipt, 1000)) throw new Error('team-authoritative-claim-requires-hub-receipt');
    const conflicts = [];
    for (const existing of state.claims.filter(item => item.status === 'active' && item.task_id !== task.id)) {
      if (mode === 'informational' || existing.mode === 'informational') continue;
      if (mode === 'shared' && existing.mode === 'shared') continue;
      for (const wanted of targets) for (const held of existing.targets) if (overlap(wanted, held)) conflicts.push({ wanted, held, task_id: existing.task_id, actor: existing.actor, mode: existing.mode || 'exclusive', authority: existing.authority || 'local' });
    }
    if (conflicts.length) throw new Error(`active-claim-conflict:${JSON.stringify(conflicts.slice(0, 12))}`);
    if (task.owner && task.owner.actor_id !== principal.actor_id && !['released', 'planned', 'ready'].includes(task.status)) throw new Error('task-owned-by-another-actor');
    const ttl = Math.min(1440, Math.max(5, Number(input.ttlMinutes || input.ttl_minutes || CLAIM_TTL_MINUTES)));
    const fencingTokens = {};
    for (const target of targets) {
      const next = Number(state.team_fabric.fencing_by_target[target] || 0) + 1;
      state.team_fabric.fencing_by_target[target] = next; fencingTokens[target] = next;
    }
    const claim = {
      id: id('claim'), task_id: task.id, actor: principal, targets, mode, authority: requestedAuthority,
      authority_receipt: cleanText(input.authorityReceipt || input.authority_receipt, 1000) || null,
      fencing_tokens: fencingTokens, acquired_utc: now(), heartbeat_utc: now(),
      expires_utc: new Date(Date.now() + ttl * 60000).toISOString(), status: 'active'
    };
    state.claims.push(claim); task.owner = principal; task.status = 'claimed'; task.authority_state = requestedAuthority; task.updated_utc = now();
    return { authority: requestedAuthority, receipt: { claim_id: claim.id, task_id: task.id, targets, mode, authority: requestedAuthority, fencing_tokens: fencingTokens, expires_utc: claim.expires_utc } };
  });
}

function renewClaim(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'task-lease-renewed', state => {
    const principal = normalizeActor(actor);
    const claim = state.claims.find(item => item.id === cleanText(input.claimId || input.claim_id, 200) && item.status === 'active');
    if (!claim) throw new Error('active-claim-not-found');
    if (claim.actor.actor_id !== principal.actor_id || claim.actor.session_id !== principal.session_id) throw new Error('claim-renewal-requires-owning-session');
    for (const [target, token] of Object.entries(input.fencingTokens || input.fencing_tokens || {})) {
      if (Number(claim.fencing_tokens?.[normalizeTarget(target)]) !== Number(token)) throw new Error(`stale-fencing-token:${target}`);
    }
    const ttl = Math.min(1440, Math.max(5, Number(input.ttlMinutes || input.ttl_minutes || CLAIM_TTL_MINUTES)));
    claim.heartbeat_utc = now(); claim.expires_utc = new Date(Date.now() + ttl * 60000).toISOString();
    return { authority: claim.authority, receipt: { claim_id: claim.id, task_id: claim.task_id, fencing_tokens: claim.fencing_tokens, expires_utc: claim.expires_utc } };
  });
}

function assertFencingToken(state, claim, target, token) {
  const normalized = normalizeTarget(target);
  const issued = Number(claim.fencing_tokens?.[normalized]);
  const current = Number(state.team_fabric.fencing_by_target[normalized]);
  if (!issued || issued !== Number(token) || current !== Number(token)) throw new Error(`stale-fencing-token:${normalized}`);
  return true;
}

function recordProgress(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'task-progress-recorded', state => {
    const task = taskById(state, input.taskId || input.task_id);
    const principal = normalizeActor(actor);
    if (!task.owner || task.owner.actor_id !== principal.actor_id) throw new Error('task-progress-requires-owning-actor');
    const status = cleanText(input.status || 'in_progress', 40);
    if (!['claimed', 'in_progress', 'waiting', 'blocked', 'completed'].includes(status)) throw new Error('unsupported-task-status');
    const claim = state.claims.find(item => item.task_id === task.id && item.status === 'active');
    if (!claim) throw new Error('task-progress-requires-active-claim');
    for (const [target, token] of Object.entries(input.fencingTokens || input.fencing_tokens || {})) assertFencingToken(state, claim, target, token);
    const usageInput = input.usage || {};
    task.usage ||= { minutes: 0, tokens: 0, cost_usd: 0, status: 'healthy' };
    task.usage.minutes += Math.max(0, Number(usageInput.minutes || 0));
    task.usage.tokens += Math.max(0, Number(usageInput.tokens || 0));
    task.usage.cost_usd += Math.max(0, Number(usageInput.costUsd ?? usageInput.cost_usd ?? 0));
    const exceeded = [
      task.budget?.max_minutes != null && task.usage.minutes > task.budget.max_minutes,
      task.budget?.max_tokens != null && task.usage.tokens > task.budget.max_tokens,
      task.budget?.max_cost_usd != null && task.usage.cost_usd > task.budget.max_cost_usd
    ].some(Boolean);
    task.usage.status = exceeded ? (task.budget?.hard_stop ? 'hard_stop' : 'soft_limit') : 'healthy';
    const receipt = {
      id: id('progress'), timestamp: now(), actor: principal, status, summary: cleanText(input.summary, 4000),
      files_changed: (input.filesChanged || input.files_changed || []).map(normalizeTarget), evidence: (input.evidence || []).map(value => cleanText(value, 1000)).filter(Boolean),
      next_action: cleanText(input.nextAction || input.next_action, 2000) || null,
      authority: claim.authority, fencing_tokens: claim.fencing_tokens, usage: { ...task.usage }
    };
    task.progress.push(receipt); task.status = exceeded && task.budget?.hard_stop ? 'blocked' : status; task.updated_utc = receipt.timestamp;
    return { receipt };
  });
}

function reconcileTask(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'task-reconciled', state => {
    const task = taskById(state, input.taskId || input.task_id);
    const principal = normalizeActor(actor);
    if (!task.owner || task.owner.actor_id !== principal.actor_id) throw new Error('task-reconciliation-requires-owning-actor');
    if (task.status !== 'completed') throw new Error('task-must-be-completed-before-reconciliation');
    const receipt = {
      id: id('reconcile'), task_id: task.id, timestamp: now(), actor: principal,
      summary: cleanText(input.summary, 4000), evidence: (input.evidence || []).map(value => cleanText(value, 1000)).filter(Boolean),
      conflicts_resolved: Boolean(input.conflictsResolved ?? input.conflicts_resolved), merge_owner: cleanText(input.mergeOwner || input.merge_owner, 200) || principal.actor_id
    };
    task.status = 'reconciled'; task.outputs.push(receipt); task.updated_utc = receipt.timestamp;
    for (const claim of state.claims) if (claim.task_id === task.id && claim.status === 'active') claim.status = 'released';
    const plan = state.plans.find(item => item.id === state.active_plan);
    if (plan && plan.task_ids.every(taskId => taskById(state, taskId).status === 'reconciled')) { plan.status = 'completed'; plan.completed_utc = now(); state.active_plan = null; }
    return { receipt };
  });
}

function releaseTask(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'task-released', state => {
    const task = taskById(state, input.taskId || input.task_id); const principal = normalizeActor(actor);
    if (!task.owner || task.owner.actor_id !== principal.actor_id) throw new Error('task-release-requires-owning-actor');
    for (const claim of state.claims) if (claim.task_id === task.id && claim.status === 'active') claim.status = 'released';
    task.status = 'released'; task.owner = null; task.updated_utc = now();
    return { receipt: { task_id: task.id, released: true, reason: cleanText(input.reason, 1000) || 'explicit-release' } };
  });
}

function memoryFile(paths, layer, sessionId) {
  if (layer === 'session') return path.join(paths.memory.sessions, `${safeId(sessionId, 'session')}.jsonl`);
  if (layer === 'project') return paths.memory.project;
  if (layer === 'state') return paths.memory.state;
  if (layer === 'system_candidate') return paths.memory.systemCandidates;
  throw new Error('unsupported-memory-layer');
}

function sourceEvidence(workspaceRoot, sourceArtifact, suppliedSourceHash) {
  if (suppliedSourceHash) return { source_hash: suppliedSourceHash, source_hash_method: 'caller-supplied-sha256' };
  const workspace = path.resolve(workspaceRoot); const candidate = path.resolve(workspace, sourceArtifact);
  const withinWorkspace = candidate === workspace || candidate.startsWith(`${workspace}${path.sep}`);
  try {
    const stat = withinWorkspace ? fs.statSync(candidate) : null;
    if (stat?.isFile() && stat.size <= 16 * 1024 * 1024) {
      return { source_hash: crypto.createHash('sha256').update(fs.readFileSync(candidate)).digest('hex'), source_hash_method: 'artifact-bytes-sha256' };
    }
  } catch { /* Preserve the locator without pretending its bytes were observed. */ }
  return { source_hash: crypto.createHash('sha256').update(sourceArtifact, 'utf8').digest('hex'), source_hash_method: 'locator-text-sha256' };
}

function captureMemory(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'memory-captured', (state, paths) => {
    const principal = normalizeActor(actor); const layer = cleanText(input.layer || 'session', 40);
    const content = cleanText(input.content, 6000); if (!content) throw new Error('memory-content-required');
    if (layer === 'system') throw new Error('system-memory-must-enter-as-candidate');
    const sourceArtifact = cleanText(input.sourceArtifact || input.source_artifact || paths.events, 1000);
    const suppliedSourceHash = cleanText(input.sourceHash || input.source_hash, 128).toLowerCase();
    if (suppliedSourceHash && !/^[a-f0-9]{64}$/.test(suppliedSourceHash)) throw new Error('memory-source-hash-must-be-sha256');
    const source = sourceEvidence(paths.workspace, sourceArtifact, suppliedSourceHash);
    const confidence = input.confidence == null ? 1 : Number(input.confidence);
    if (!Number.isFinite(confidence) || confidence < 0 || confidence > 1) throw new Error('memory-confidence-out-of-range');
    const record = {
      schema_version: SCHEMA_VERSION, memory_id: id('memory'), layer, lifecycle: layer === 'system_candidate' ? 'candidate' : 'proposed',
      project_id: state.project.id, actor: principal, created_utc: now(), content, kind: cleanText(input.kind || 'observation', 80),
      epistemic_status: cleanText(input.epistemicStatus || input.epistemic_status || 'observation', 40), confidence,
      confidence_method: cleanText(input.confidenceMethod || input.confidence_method || 'direct-user-or-runtime-entry', 160),
      classification: cleanText(input.classification || 'project-local', 80), acl: ['project'], effective_utc: now(), expiry_utc: input.expiry_utc || null,
      source_artifact: sourceArtifact, source_hash: source.source_hash, source_hash_method: source.source_hash_method,
      evidence_locator: cleanText(input.evidenceLocator || input.evidence_locator || sourceArtifact, 1000), revision: 1,
      supersedes: input.supersedes ? cleanText(input.supersedes, 160) : null, promoted_from: input.promotedFrom || input.promoted_from || null
    };
    record.record_sha256 = hash(record);
    appendJsonl(memoryFile(paths, layer, principal.session_id), record);
    if (layer === 'session') state.memory.session_records += 1;
    if (layer === 'project') state.memory.project_records += 1;
    if (layer === 'state') state.memory.state_records += 1;
    if (layer === 'system_candidate') state.memory.system_candidates += 1;
    return { receipt: { memory_id: record.memory_id, layer, lifecycle: record.lifecycle, source_hash: record.source_hash } };
  });
}

function memoryRecords(paths, state, options = {}) {
  const limit = Math.max(1, Math.min(100, Number(options.limit || 24)));
  const includeContent = options.includeContent === true;
  const query = cleanText(options.query, 500).toLowerCase();
  const specifications = [
    { layer: 'project', file: paths.memory.project },
    { layer: 'state', file: paths.memory.state },
    { layer: 'system_candidate', file: paths.memory.systemCandidates },
    ...(() => { try { return fs.readdirSync(paths.memory.sessions).filter(name => name.endsWith('.jsonl')).sort().map(name => ({ layer: 'session', file: path.join(paths.memory.sessions, name) })); } catch { return []; } })()
  ];
  const records = []; const errors = []; const layerCounts = { session: 0, project: 0, state: 0, system_candidate: 0 };
  const lifecycleCounts = {}; let bytes = 0; let sealed = 0; let legacyUnsealed = 0;
  for (const specification of specifications) {
    if (!fs.existsSync(specification.file)) continue;
    try {
      const stat = fs.statSync(specification.file); bytes += stat.size;
      const lines = fs.readFileSync(specification.file, 'utf8').split(/\r?\n/).filter(Boolean);
      lines.forEach((line, index) => {
        try {
          const record = JSON.parse(line);
          if (!record || typeof record !== 'object' || Array.isArray(record)) throw new Error('record-not-object');
          if (record.project_id !== state.project.id) throw new Error('project-scope-mismatch');
          if (record.layer !== specification.layer) throw new Error('layer-file-mismatch');
          if (!record.memory_id || !record.created_utc || !record.kind || !record.source_artifact || !/^[a-f0-9]{64}$/i.test(String(record.source_hash || ''))) throw new Error('required-provenance-invalid');
          if (record.record_sha256) {
            const { record_sha256: expected, ...payload } = record;
            if (!/^[a-f0-9]{64}$/i.test(String(expected)) || hash(payload) !== expected) throw new Error('record-seal-mismatch');
            sealed += 1;
          } else legacyUnsealed += 1;
          layerCounts[specification.layer] += 1;
          lifecycleCounts[record.lifecycle] = Number(lifecycleCounts[record.lifecycle] || 0) + 1;
          const haystack = `${record.memory_id} ${record.kind} ${record.content} ${record.source_artifact} ${record.evidence_locator}`.toLowerCase();
          if (query && !haystack.includes(query)) return;
          records.push({
            memory_id: record.memory_id, layer: record.layer, lifecycle: record.lifecycle, kind: record.kind,
            created_utc: record.created_utc, epistemic_status: record.epistemic_status, confidence: record.confidence,
            confidence_method: record.confidence_method, classification: record.classification, acl: record.acl,
            source_artifact: record.source_artifact, source_hash: record.source_hash, source_hash_method: record.source_hash_method || 'legacy-unspecified', evidence_locator: record.evidence_locator,
            revision: record.revision, supersedes: record.supersedes, record_sha256: record.record_sha256 || null,
            content_sha256: hash(String(record.content || '')), ...(includeContent ? { content: record.content } : {})
          });
        } catch (error) { errors.push({ file: path.relative(paths.workspace, specification.file).replaceAll('\\', '/'), line: index + 1, code: error.message }); }
      });
    } catch (error) { errors.push({ file: path.relative(paths.workspace, specification.file).replaceAll('\\', '/'), line: null, code: error.message }); }
  }
  const declared = state.memory || {};
  const drift = Object.entries(layerCounts).filter(([layer, count]) => Number(declared[layer === 'session' ? 'session_records' : layer === 'project' ? 'project_records' : layer === 'state' ? 'state_records' : 'system_candidates'] || 0) !== count).map(([layer, observed]) => ({ layer, observed, declared: Number(declared[layer === 'session' ? 'session_records' : layer === 'project' ? 'project_records' : layer === 'state' ? 'state_records' : 'system_candidates'] || 0) }));
  records.sort((left, right) => String(right.created_utc).localeCompare(String(left.created_utc)) || String(left.memory_id).localeCompare(String(right.memory_id)));
  return {
    schema_version: SCHEMA_VERSION, generated_utc: now(), instrumented: true,
    authority: 'project-owned portable coordination memory; non-canonical until admitted by the Pacify-X memory vault',
    canonical: false, retrieval_authority: 'reference-only; proposed and candidate records never override certified memory',
    root: paths.memory.root, record_count: Object.values(layerCounts).reduce((sum, value) => sum + value, 0), matched_count: records.length,
    bytes, layer_counts: layerCounts, lifecycle_counts: lifecycleCounts,
    integrity: { valid: errors.length === 0 && drift.length === 0, sealed_records: sealed, legacy_unsealed_records: legacyUnsealed, invalid_records: errors.length, counter_drift: drift },
    errors, query, limit, records: records.slice(0, limit)
  };
}

function readMemoryTelemetry(workspaceRoot, options = {}) {
  const paths = coordinationPaths(workspaceRoot);
  if (!fs.existsSync(paths.state)) return { schema_version: SCHEMA_VERSION, generated_utc: now(), instrumented: false, authority: 'project-owned portable coordination memory', canonical: false, record_count: 0, records: [], errors: ['coordination-store-not-initialized'] };
  const state = migrateState(readJson(paths.state, defaultState(paths.workspace)));
  return memoryRecords(paths, state, options);
}

function registerSession(workspaceRoot, actor) {
  return withState(workspaceRoot, actor, 'session-heartbeat', state => {
    const principal = normalizeActor(actor); const existing = state.sessions.find(item => item.session_id === principal.session_id);
    if (existing) { existing.heartbeat_utc = now(); existing.status = 'active'; }
    else state.sessions.push({ ...principal, started_utc: now(), heartbeat_utc: now(), status: 'active' });
    return { receipt: { session_id: principal.session_id, project_id: state.project.id } };
  });
}

function readCoordination(workspaceRoot, options = {}) {
  const paths = coordinationPaths(workspaceRoot); ensureStore(paths);
  const state = migrateState(readJson(paths.state, defaultState(paths.workspace))); expireClaims(state); expireSessions(state);
  return { state: publicState(state), events: tailJsonl(paths.events, Math.min(Number(options.eventLimit || 40), 200)), paths: publicPaths(paths), memory: memoryRecords(paths, state, { limit: options.memoryLimit || 12, includeContent: false }) };
}

function tailJsonl(file, limit) {
  try { return fs.readFileSync(file, 'utf8').split(/\r?\n/).filter(Boolean).slice(-limit).map(line => JSON.parse(line)); } catch { return []; }
}

function publicPaths(paths) {
  return { root: paths.root, state: paths.state, events: paths.events, handoff_json: paths.handoffJson, handoff_markdown: paths.handoffMarkdown, memory_root: paths.memory.root };
}

function publicState(state) {
  const copy = JSON.parse(JSON.stringify(state));
  expireClaims(copy);
  copy.claims = copy.claims.filter(claim => claim.status === 'active');
  return copy;
}

function writeReceipt(paths, event) {
  atomicWrite(path.join(paths.receipts, `${event.event_id}.json`), event);
  const files = fs.readdirSync(paths.receipts).filter(name => name.endsWith('.json')).sort();
  if (files.length > MAX_EVENTS) {
    // Receipts are evidence. Retention is reported, never auto-purged.
  }
}

function writeHandoff(paths, state, event) {
  const tasks = state.tasks.filter(task => state.plans.find(plan => plan.id === state.active_plan)?.task_ids.includes(task.id));
  const next = tasks.find(task => ['planned', 'ready', 'released'].includes(task.status) && task.depends_on.every(dep => ['completed', 'reconciled'].includes(taskById(state, dep).status)));
  const packet = {
    schema_version: SCHEMA_VERSION, generated_utc: now(), project: state.project, objective: state.plans.find(plan => plan.id === state.active_plan)?.objective || null,
    phase: state.active_plan ? 'parallel-execution' : 'idle-or-complete', verified_state_hash: state.state_hash,
    tasks, active_claims: state.claims.filter(claim => claim.status === 'active'), last_event: event,
    team_fabric: { mode: state.team_fabric.mode, hub: state.team_fabric.hub, work_rooms: state.team_fabric.work_rooms.length },
    exact_next_action: next ? `Claim task ${next.id}: ${next.title}` : 'Review completed work or create a new parallel plan.',
    memory_refs: [path.relative(paths.workspace, paths.memory.project).replaceAll('\\', '/'), path.relative(paths.workspace, paths.memory.state).replaceAll('\\', '/')],
    event_log: path.relative(paths.workspace, paths.events).replaceAll('\\', '/'), hazards: ['Respect active claims before writing files.', 'System-memory candidates are not canonical until separately reviewed and promoted.']
  };
  packet.sha256 = hash(packet);
  atomicWrite(paths.handoffJson, packet);
  const lines = [
    '# Pacify-X Cross-IDE Handoff', '', `Generated: ${packet.generated_utc}`, `State hash: ${packet.verified_state_hash}`, '',
    '## Objective', '', packet.objective || 'No active plan.', '', '## Exact next action', '', packet.exact_next_action, '',
    '## Tasks', '', ...tasks.map(task => `- [${task.status === 'reconciled' ? 'x' : ' '}] ${task.id} — ${task.title} (${task.status})`), '',
    '## Active claims', '', ...(packet.active_claims.length ? packet.active_claims.map(claim => `- ${claim.task_id}: ${claim.targets.join(', ')} — ${claim.actor.actor_id} / ${claim.actor.harness}`) : ['- None']), '',
    '## Resume contract', '', '- Read `handoff.json` and verify its SHA-256 field.', '- Read active claims before editing.', '- Claim one dependency-ready task before workspace writes.', '- Append progress and reconciliation receipts.', '- Never treat system-memory candidates as canonical facts.', ''
  ];
  fs.writeFileSync(paths.handoffMarkdown, `${lines.join('\n')}\n`, 'utf8');
}

function taskHandoff(workspaceRoot, taskId) {
  const snapshot = readCoordination(workspaceRoot); const task = taskById(snapshot.state, taskId);
  const claim = snapshot.state.claims.find(item => item.task_id === task.id) || null;
  const plan = snapshot.state.plans.find(item => item.task_ids.includes(task.id)) || null;
  return {
    schema_version: SCHEMA_VERSION, project: snapshot.state.project, state_hash: snapshot.state.state_hash,
    resume_envelope: {
      task_id: task.id, task_revision: snapshot.state.revision, objective: task.description || task.title,
      plan_objective: plan?.objective || null, acceptance_criteria: task.acceptance, goal_context: task.goal_context,
      dependencies: task.depends_on, blockers: task.status === 'blocked' ? [task.progress.at(-1)?.summary || 'blocked'] : [],
      read_scopes: task.read_scopes, write_scopes: task.write_scopes, effect_scopes: task.effect_scopes,
      authority_state: task.authority_state, claim: claim ? { id: claim.id, mode: claim.mode, authority: claim.authority, fencing_tokens: claim.fencing_tokens, expires_utc: claim.expires_utc } : null,
      budget: task.budget, usage: task.usage, memory_refs: [snapshot.paths.memory_root], evidence_refs: (task.outputs || []).flatMap(output => output.evidence || []), generated_at: now()
    },
    task, active_claims: snapshot.state.claims, instructions: ['Honor AGENTS.md.', 'Verify dependency completion.', 'Claim the declared file/area scope before writing.', 'Present current fencing tokens with durable progress.', 'Record progress receipts.', 'Complete then reconcile before releasing ownership.'],
    handoff_path: snapshot.paths.handoff_json
  };
}

function diagnoseWorkStop(workspaceRoot, taskId) {
  const snapshot = readCoordination(workspaceRoot, { eventLimit: 100 });
  const task = taskById(snapshot.state, taskId);
  const claim = snapshot.state.claims.find(item => item.task_id === task.id) || null;
  const incomplete = task.depends_on.filter(dependency => !['completed', 'reconciled'].includes(taskById(snapshot.state, dependency).status));
  const ownerSession = task.owner ? snapshot.state.sessions.find(item => item.session_id === task.owner.session_id) : null;
  const reasons = [];
  if (incomplete.length) reasons.push({ code: 'dependencies', detail: incomplete });
  if (task.status === 'blocked') reasons.push({ code: 'task-blocked', detail: task.progress.at(-1)?.summary || null });
  if (task.owner && !claim) reasons.push({ code: 'lease-missing-or-expired', detail: task.owner });
  if (ownerSession && ownerSession.status !== 'active') reasons.push({ code: 'worker-session-stale', detail: ownerSession });
  if (task.usage?.status && task.usage.status !== 'healthy') reasons.push({ code: 'budget', detail: task.usage });
  return { schema_version: SCHEMA_VERSION, task_id: task.id, status: task.status, reasons, next_safe_action: reasons.length ? 'Resolve the first classified boundary; do not blindly retry.' : 'No stop boundary is visible in project coordination state.', state_hash: snapshot.state.state_hash };
}

function workRoom(workspaceRoot, taskId) {
  const snapshot = readCoordination(workspaceRoot, { eventLimit: 200 });
  const handoff = taskHandoff(workspaceRoot, taskId);
  return {
    schema_version: SCHEMA_VERSION, room_id: `task:${handoff.task.id}`, derived: true, authoritative: false,
    binding: { project_id: snapshot.state.project.id, task_id: handoff.task.id, branch: handoff.task.branch, worktree: handoff.task.worktree },
    participants: snapshot.state.sessions, timeline: snapshot.events.filter(event => event.result?.task_id === handoff.task.id),
    authority_note: 'This room is a derived collaboration view. Claims, leases, fencing, Git, and Pacify-X policy remain authoritative.'
  };
}

module.exports = {
  SCHEMA_VERSION, coordinationPaths, normalizeActor, normalizeTarget, overlap, validateTaskGraph, createParallelPlan,
  claimTask, renewClaim, assertFencingToken, recordProgress, reconcileTask, releaseTask, captureMemory, registerSession,
  readCoordination, readMemoryTelemetry, taskHandoff, diagnoseWorkStop, workRoom, hash
};
