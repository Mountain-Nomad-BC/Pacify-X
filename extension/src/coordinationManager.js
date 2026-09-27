'use strict';

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { assertCoordinationState, assertCoordinationTransition, assertEventAncestry } = require('./stateInvariants');

const SCHEMA_VERSION = '1.2';
const MAX_TASKS = 250;
const MAX_EVENTS = 5000;
const MAX_TEXT = 12000;
const MAX_EVENT_BYTES = 32 * 1024 * 1024;
const MAX_MEMORY_FILE_BYTES = 16 * 1024 * 1024;
const MAX_MEMORY_TOTAL_BYTES = 64 * 1024 * 1024;
const CLAIM_TTL_MINUTES = 120;
const MAX_WAITS = 1000;
const MAX_WAKES = 2000;
const MAX_MAILBOX_MESSAGES = 2000;
const MAX_MESSAGE_BYTES = 8 * 1024;

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
    publication: path.join(root, '.publication-pending.json'),
    quarantine: path.join(root, 'quarantine'),
    handoffJson: path.join(root, 'handoff.json'), handoffMarkdown: path.join(root, 'HANDOFF.md'),
    memory: {
      root: path.join(root, 'memory'), project: path.join(root, 'memory', 'project.jsonl'),
      state: path.join(root, 'memory', 'state.jsonl'), systemCandidates: path.join(root, 'memory', 'system-candidates.jsonl'),
      sessions: path.join(root, 'memory', 'sessions')
    }
  };
}

function workspacePathIdentity(value) {
  const resolved = path.resolve(value || '');
  let canonical = resolved;
  try {
    canonical = fs.realpathSync.native(resolved);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  return process.platform === 'win32' ? canonical.toLowerCase() : canonical;
}

function defaultState(workspaceRoot) {
  return {
    schema_version: SCHEMA_VERSION, project: { id: safeId(path.basename(workspaceRoot), 'project'), root: path.resolve(workspaceRoot) },
    revision: 0, updated_utc: now(), state_hash: null, active_plan: null, plans: [], tasks: [], claims: [], sessions: [],
    waits: [], wakes: [], mailboxes: {},
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
  state.waits ||= []; state.wakes ||= []; state.mailboxes ||= {};
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

function quarantineCorruptAuthoritativeJson(paths, file, raw, error) {
  fs.mkdirSync(paths.quarantine, { recursive: true });
  const fingerprint = hash(raw);
  const base = `${path.basename(file)}.${new Date().toISOString().replace(/[:.]/g, '-')}.${fingerprint.slice(0, 12)}`;
  const evidence = path.join(paths.quarantine, `${base}.corrupt`);
  const receipt = path.join(paths.quarantine, `${base}.receipt.json`);
  try { fs.writeFileSync(evidence, raw, { encoding: 'utf8', flag: 'wx' }); } catch (writeError) { if (writeError.code !== 'EEXIST') throw writeError; }
  atomicWrite(receipt, {
    schema_version: 'px.authoritative-json-quarantine/1.0', detected_utc: now(), source_path: file,
    evidence_path: evidence, source_sha256: fingerprint, source_bytes: Buffer.byteLength(raw, 'utf8'),
    disposition: 'copied-for-evidence; authoritative-source-left-in-place', reason: cleanText(error?.message || error, 1000)
  });
  return { evidence, receipt, fingerprint };
}

function readAuthoritativeState(paths, options = {}) {
  const corruption = (reason, raw, error) => {
    const fingerprint = hash(raw);
    if (options.persistCorruptionEvidence === false) throw new Error(`${reason}:${fingerprint}:evidence-not-written-read-only`);
    const evidence = quarantineCorruptAuthoritativeJson(paths, paths.state, raw, error);
    throw new Error(`${reason}:${evidence.fingerprint}:${evidence.receipt}`);
  };
  let raw;
  try { raw = fs.readFileSync(paths.state, 'utf8'); }
  catch (error) {
    if (error.code === 'ENOENT') throw new Error('coordination-authoritative-state-missing');
    throw new Error(`coordination-authoritative-state-unreadable:${error.code || error.message}`);
  }
  let state;
  try { state = JSON.parse(raw); }
  catch (error) {
    corruption('coordination-authoritative-state-corrupt', raw, error);
  }
  const structurallyValid = state && typeof state === 'object' && !Array.isArray(state)
    && state.project && typeof state.project === 'object'
    && Array.isArray(state.plans) && Array.isArray(state.tasks) && Array.isArray(state.claims) && Array.isArray(state.sessions);
  if (!structurallyValid) {
    corruption('coordination-authoritative-state-invalid', raw, new Error('invalid-coordination-state-shape'));
  }
  if (workspacePathIdentity(state.project.root) !== workspacePathIdentity(paths.workspace)) {
    corruption('coordination-authoritative-state-workspace-mismatch', raw, new Error('coordination-state-workspace-mismatch'));
  }
  if (state.state_hash && state.state_hash !== stateHash(state)) {
    corruption('coordination-authoritative-state-hash-mismatch', raw, new Error('coordination-state-hash-mismatch'));
  }
  return migrateState(state);
}

function ensureStore(paths) {
  fs.mkdirSync(paths.receipts, { recursive: true });
  fs.mkdirSync(paths.memory.sessions, { recursive: true });
  if (!fs.existsSync(paths.state)) {
    const state = defaultState(paths.workspace);
    state.state_hash = stateHash(state);
    assertCoordinationState(state);
    atomicWrite(paths.state, state);
  }
}

function stateHash(state) {
  const copy = { ...state, state_hash: null };
  return hash(copy);
}

function atomicWrite(file, value) {
  atomicWriteText(file, `${JSON.stringify(value, null, 2)}\n`);
}

function atomicWriteText(file, value) {
  const temporary = `${file}.${process.pid}.${crypto.randomUUID()}.tmp`;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const descriptor = fs.openSync(temporary, 'wx');
  try { fs.writeFileSync(descriptor, value, 'utf8'); fs.fsyncSync(descriptor); } finally { fs.closeSync(descriptor); }
  fs.renameSync(temporary, file);
}

function currentText(file) {
  try { return fs.readFileSync(file, 'utf8'); } catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

function exactFileSlice(file, position, length) {
  if (length <= 0) return Buffer.alloc(0);
  const descriptor = fs.openSync(file, 'r');
  try {
    const buffer = Buffer.alloc(length); let offset = 0;
    while (offset < length) {
      const count = fs.readSync(descriptor, buffer, offset, length - offset, position + offset);
      if (!count) break;
      offset += count;
    }
    return buffer.subarray(0, offset);
  } finally { fs.closeSync(descriptor); }
}

function appendAndSync(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const descriptor = fs.openSync(file, 'a');
  try { fs.writeFileSync(descriptor, text, 'utf8'); fs.fsyncSync(descriptor); } finally { fs.closeSync(descriptor); }
}

function recoverPublication(paths) {
  const raw = currentText(paths.publication);
  if (raw === null) return { recovered: false, artifacts: 0 };
  let journal;
  try { journal = JSON.parse(raw); } catch { throw new Error('coordination-publication-journal-invalid'); }
  if (journal?.schema_version !== 'px.coordination-publication/1.0' || !Array.isArray(journal.artifacts) || !journal.artifacts.length) throw new Error('coordination-publication-journal-invalid');
  for (const artifact of journal.artifacts) {
    const target = path.resolve(paths.root, artifact.relative_path || '');
    if (target === paths.root || !target.startsWith(`${paths.root}${path.sep}`)) throw new Error('coordination-publication-target-outside-root');
    if (artifact.operation === 'append') {
      if (!Number.isSafeInteger(artifact.before_size) || artifact.before_size < 0 || typeof artifact.append_text !== 'string' || hash(artifact.append_text) !== artifact.append_sha256) throw new Error(`coordination-publication-append-invalid:${artifact.relative_path}`);
      const appendBytes = Buffer.from(artifact.append_text, 'utf8');
      let presentSize;
      try { presentSize = fs.statSync(target).size; } catch (error) { if (error.code !== 'ENOENT') throw error; presentSize = 0; }
      const finalSize = artifact.before_size + appendBytes.length;
      if (presentSize > finalSize || presentSize < artifact.before_size) throw new Error(`coordination-publication-ambiguous:${artifact.relative_path}`);
      const beforeTailLength = Math.min(4096, artifact.before_size);
      if (beforeTailLength > 0) {
        const beforeTail = exactFileSlice(target, artifact.before_size - beforeTailLength, beforeTailLength);
        if (hash(beforeTail) !== artifact.before_tail_sha256) throw new Error(`coordination-publication-before-image-mismatch:${artifact.relative_path}`);
      }
      if (presentSize === finalSize) {
        const presentAppend = exactFileSlice(target, artifact.before_size, appendBytes.length);
        if (!presentAppend.equals(appendBytes)) throw new Error(`coordination-publication-ambiguous:${artifact.relative_path}`);
        continue;
      }
      if (presentSize > artifact.before_size) fs.truncateSync(target, artifact.before_size);
      appendAndSync(target, artifact.append_text);
      continue;
    }
    const present = currentText(target); const presentHash = present === null ? null : hash(present);
    if (presentHash === artifact.after_sha256) continue;
    if (presentHash !== artifact.before_sha256) throw new Error(`coordination-publication-ambiguous:${artifact.relative_path}`);
    if (typeof artifact.after_text !== 'string' || hash(artifact.after_text) !== artifact.after_sha256) throw new Error(`coordination-publication-after-image-invalid:${artifact.relative_path}`);
    atomicWriteText(target, artifact.after_text);
  }
  fs.unlinkSync(paths.publication);
  return { recovered: true, artifacts: journal.artifacts.length };
}

function publishTransaction(paths, operation, artifacts) {
  const normalized = artifacts.map(({ file, afterText, appendText }) => {
    const target = path.resolve(file);
    if (target === paths.root || !target.startsWith(`${paths.root}${path.sep}`)) throw new Error('coordination-publication-target-outside-root');
    if (appendText !== undefined) {
      let beforeSize;
      try { beforeSize = fs.statSync(target).size; } catch (error) { if (error.code !== 'ENOENT') throw error; beforeSize = 0; }
      const tailLength = Math.min(4096, beforeSize);
      const beforeTail = tailLength ? exactFileSlice(target, beforeSize - tailLength, tailLength) : Buffer.alloc(0);
      return { operation: 'append', relative_path: path.relative(paths.root, target).replaceAll('\\', '/'), before_size: beforeSize, before_tail_sha256: hash(beforeTail), append_sha256: hash(appendText), append_text: appendText };
    }
    const before = currentText(target);
    return { operation: 'replace', relative_path: path.relative(paths.root, target).replaceAll('\\', '/'), before_sha256: before === null ? null : hash(before), after_sha256: hash(afterText), after_text: afterText };
  });
  atomicWrite(paths.publication, { schema_version: 'px.coordination-publication/1.0', transaction_id: id('coord-tx'), operation, prepared_utc: now(), artifacts: normalized });
  return recoverPublication(paths);
}

function appendJsonl(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, `${JSON.stringify(value)}\n`, 'utf8');
}

function acquireLock(paths, timeoutMs = 4000) {
  ensureStore(paths);
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const token = crypto.randomUUID();
    try {
      fs.writeFileSync(paths.lock, JSON.stringify({ schema_version: 'px.coordination-lock/1.0', token, pid: process.pid, host: os.hostname(), acquired_utc: now() }), { encoding: 'utf8', flag: 'wx' });
      return () => {
        try {
          const current = JSON.parse(fs.readFileSync(paths.lock, 'utf8'));
          if (current.token === token && current.pid === process.pid && current.host === os.hostname()) fs.unlinkSync(paths.lock);
        } catch { /* Missing, replaced, or corrupt locks are never released by a non-owner. */ }
      };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      if (retireProvablyStaleLock(paths)) continue;
    }
  }
  throw new Error('coordination-lock-timeout');
}

function localProcessAlive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try { process.kill(pid, 0); return true; }
  catch (error) { return error.code === 'EPERM'; }
}

function retireProvablyStaleLock(paths) {
  let raw; let stat; let record;
  try { raw = fs.readFileSync(paths.lock, 'utf8'); stat = fs.statSync(paths.lock); }
  catch { return false; }
  try { record = JSON.parse(raw); } catch { record = null; }
  const sameHost = record?.host === os.hostname();
  if (sameHost && localProcessAlive(Number(record.pid))) return false;
  if (record?.host && !sameHost) return false;
  const reason = record ? 'same-host-owner-process-not-alive' : 'malformed-lock-owner-record';
  try {
    const currentStat = fs.statSync(paths.lock);
    const currentRaw = fs.readFileSync(paths.lock, 'utf8');
    if (currentRaw !== raw || currentStat.size !== stat.size || currentStat.mtimeMs !== stat.mtimeMs) return false;
    fs.mkdirSync(paths.quarantine, { recursive: true });
    const retired = path.join(paths.quarantine, `coordination-lock.${Date.now()}.${hash(raw).slice(0, 12)}.stale`);
    fs.renameSync(paths.lock, retired);
    atomicWrite(`${retired}.receipt.json`, { schema_version: 'px.stale-lock-retirement/1.0', retired_utc: now(), reason, source_path: paths.lock, evidence_path: retired, source_sha256: hash(raw) });
    return true;
  } catch { return false; }
}

function withState(workspaceRoot, actor, operation, mutator) {
  const paths = coordinationPaths(workspaceRoot);
  const release = acquireLock(paths);
  try {
    recoverPublication(paths);
    const state = readAuthoritativeState(paths);
    const previous = JSON.parse(JSON.stringify(state));
    // Historical state is validated at its own committed time. Expiry is then
    // applied as the first fenced transition step instead of making recovery
    // impossible merely because wall time advanced.
    assertCoordinationState(previous, { requireSeal: false, nowUtc: previous.updated_utc });
    expireClaims(state); expireSessions(state); expireWaits(state);
    const beforeHash = previous.state_hash || stateHash(previous);
    const priorEvents = tailJsonlDetailed(paths.events, MAX_EVENTS);
    if (priorEvents.health.status === 'degraded') throw new Error(`coordination-event-log-degraded:line-${priorEvents.health.failed_line}`);
    const deferredPublications = [];
    const result = mutator(state, paths, deferredPublications);
    state.revision = Number(state.revision || 0) + 1;
    state.updated_utc = now();
    state.state_hash = stateHash(state);
    const previousEvent = priorEvents.records.at(-1) || null;
    const event = {
      schema_version: SCHEMA_VERSION, event_id: id('pxe'), timestamp: state.updated_utc, operation,
      project_id: state.project.id, actor: normalizeActor(actor), before_hash: beforeHash, after_hash: state.state_hash,
      authority: result?.authority || 'local', previous_event_sha256: previousEvent?.event_sha256 || null,
      payload_sha256: hash(result?.receipt || result || null), result: result?.receipt || result || null
    };
    event.event_sha256 = hash(event);
    assertCoordinationTransition({ previous, next: state, operation, previousEvents: priorEvents.records, event });
    const artifacts = deferredPublications.map(publication => ({ file: publication.file, appendText: `${JSON.stringify(publication.record)}\n` }));
    artifacts.push(
      { file: paths.state, afterText: `${JSON.stringify(state, null, 2)}\n` },
      { file: paths.events, appendText: `${JSON.stringify(event)}\n` },
      { file: path.join(paths.receipts, `${event.event_id}.json`), afterText: `${JSON.stringify(event, null, 2)}\n` },
      ...handoffArtifacts(paths, state, event)
    );
    publishTransaction(paths, operation, artifacts);
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


function expireWaits(state) {
  const stamp = Date.now();
  state.waits ||= [];
  state.wakes ||= [];
  for (const wait of state.waits) {
    if (wait.status !== 'waiting') continue;
    if (!Number.isFinite(Date.parse(wait.expires_utc)) || Date.parse(wait.expires_utc) <= stamp) wait.status = 'expired';
    const task = state.tasks.find(item => item.id === wait.task_id);
    if (!task || ['completed', 'reconciled', 'released'].includes(task.status)) wait.status = 'cancelled';
  }
}

function waitById(state, waitId) {
  const value = cleanText(waitId, 200);
  const wait = state.waits.find(item => item.wait_id === value);
  if (!wait) throw new Error('coordination-wait-not-found');
  return wait;
}

function dependencyGraph(state) {
  return Object.fromEntries(state.tasks.map(task => [task.id, [...task.depends_on]]));
}

function wouldWaitCreateCycle(state, taskId, dependencies) {
  const graph = dependencyGraph(state);
  graph[taskId] = [...new Set([...(graph[taskId] || []), ...dependencies])];
  const visiting = new Set(); const visited = new Set();
  const visit = node => {
    if (visiting.has(node)) return true;
    if (visited.has(node)) return false;
    visiting.add(node);
    for (const child of graph[node] || []) if (visit(child)) return true;
    visiting.delete(node); visited.add(node); return false;
  };
  return visit(taskId);
}

function activeClaimForTask(state, task, principal) {
  const claim = state.claims.find(item => item.task_id === task.id && item.status === 'active');
  if (!claim) throw new Error('coordination-wait-requires-active-claim');
  if (claim.actor.actor_id !== principal.actor_id || claim.actor.session_id !== principal.session_id) throw new Error('coordination-wait-claim-owner-mismatch');
  return claim;
}

function wakeIdentity(wait) {
  return `wake-${hash({ wait_id: wait.wait_id, satisfied_ids: [...wait.satisfied_ids].sort(), checkpoint_id: wait.checkpoint_id }).slice(0, 32)}`;
}

function satisfyWaits(state, triggerType, triggerId, triggerEvidence = []) {
  const produced = [];
  expireWaits(state);
  for (const wait of state.waits) {
    if (wait.status !== 'waiting' || wait.condition_type !== triggerType || !wait.dependency_ids.includes(triggerId)) continue;
    const task = state.tasks.find(item => item.id === wait.task_id);
    if (!task || ['completed', 'reconciled', 'released'].includes(task.status)) { wait.status = 'cancelled'; continue; }
    if (!wait.satisfied_ids.includes(triggerId)) wait.satisfied_ids.push(triggerId);
    const complete = wait.mode === 'any' ? wait.satisfied_ids.length > 0 : wait.dependency_ids.every(item => wait.satisfied_ids.includes(item));
    if (!complete) continue;
    wait.status = 'satisfied'; wait.satisfied_utc = now();
    const wakeId = wakeIdentity(wait);
    let wake = state.wakes.find(item => item.wake_id === wakeId);
    if (!wake) {
      if (state.wakes.length >= MAX_WAKES) throw new Error('coordination-wake-capacity-exceeded');
      wake = {
        wake_id: wakeId, wait_id: wait.wait_id, task_id: wait.task_id, checkpoint_id: wait.checkpoint_id,
        trigger_type: triggerType, trigger_ids: [...wait.satisfied_ids], trigger_evidence: triggerEvidence.map(value => cleanText(value, 1000)).filter(Boolean).slice(0, 32),
        created_utc: now(), status: 'resume_pending', required_actor: wait.actor,
        exact_next_action: wait.exact_next_action || null, cognitive_generation_id: wait.cognitive_generation_id || null,
        fresh_claim_required: !state.claims.some(item => item.task_id === wait.task_id && item.status === 'active')
      };
      state.wakes.push(wake);
    }
    produced.push(wake);
  }
  return produced;
}

function registerWait(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'wait-registered', state => {
    expireWaits(state);
    const principal = normalizeActor(actor);
    const task = taskById(state, input.taskId || input.task_id);
    if (!ownedBy(task, principal)) throw new Error('coordination-wait-requires-owning-actor-or-session');
    if (['completed', 'reconciled', 'released'].includes(task.status)) throw new Error('coordination-wait-task-terminal');
    const claim = activeClaimForTask(state, task, principal);
    exactClaimProof(state, claim, input);
    const checkpointId = cleanText(input.checkpointId || input.checkpoint_id, 240);
    if (!checkpointId) throw new Error('coordination-wait-checkpoint-required');
    const conditionType = cleanText(input.conditionType || input.condition_type, 40);
    if (!['task', 'message', 'resource', 'approval', 'timer', 'model_result'].includes(conditionType)) throw new Error('coordination-wait-condition-unsupported');
    const dependencies = [...new Set((input.dependencyIds || input.dependency_ids || []).map(value => cleanText(value, 240)).filter(Boolean))];
    if (!dependencies.length || dependencies.length > 64) throw new Error('coordination-wait-dependencies-required');
    if (conditionType === 'task') {
      for (const dependency of dependencies) taskById(state, dependency);
      if (wouldWaitCreateCycle(state, task.id, dependencies)) throw new Error('coordination-wait-cycle');
    }
    const mode = cleanText(input.mode || 'all', 20);
    if (!['all', 'any'].includes(mode)) throw new Error('coordination-wait-mode-unsupported');
    const ttl = Math.min(1440, Math.max(1, Number(input.ttlMinutes || input.ttl_minutes || 60)));
    const duplicate = state.waits.find(item => item.status === 'waiting' && item.task_id === task.id && item.condition_type === conditionType
      && item.checkpoint_id === checkpointId && JSON.stringify([...item.dependency_ids].sort()) === JSON.stringify([...dependencies].sort()));
    if (duplicate) return { receipt: { ...duplicate, idempotent: true } };
    if (state.waits.length >= MAX_WAITS) throw new Error('coordination-wait-capacity-exceeded');
    const wait = {
      wait_id: id('wait'), task_id: task.id, actor: principal, claim_id: claim.id, fencing_tokens: { ...claim.fencing_tokens },
      condition_type: conditionType, dependency_ids: dependencies, satisfied_ids: [], mode, checkpoint_id: checkpointId,
      exact_next_action: cleanText(input.exactNextAction || input.exact_next_action, 2000) || null,
      cognitive_generation_id: cleanText(input.cognitiveGenerationId || input.cognitive_generation_id, 256) || null,
      created_utc: now(), expires_utc: new Date(Date.now() + ttl * 60000).toISOString(), status: 'waiting'
    };
    state.waits.push(wait); task.status = 'waiting'; task.updated_utc = now();
    return { authority: claim.authority, receipt: wait };
  });
}

function waitStatus(workspaceRoot, waitId) {
  const snapshot = readCoordination(workspaceRoot, { eventLimit: 20 });
  const wait = waitById(snapshot.state, waitId);
  const wakes = (snapshot.state.wakes || []).filter(item => item.wait_id === wait.wait_id);
  const activeClaim = snapshot.state.claims.find(item => item.task_id === wait.task_id && item.status === 'active') || null;
  return {
    schema_version: SCHEMA_VERSION, wait, wakes,
    resume_packet: wakes.at(-1) ? {
      wait_id: wait.wait_id, wake_id: wakes.at(-1).wake_id, task_id: wait.task_id, checkpoint_id: wait.checkpoint_id,
      trigger_result_ids: wakes.at(-1).trigger_ids, trigger_evidence_ids: wakes.at(-1).trigger_evidence,
      exact_next_action: wakes.at(-1).exact_next_action, fresh_claim_required: !activeClaim,
      active_claim_id: activeClaim?.id || null, cognitive_generation_id: wakes.at(-1).cognitive_generation_id || wait.cognitive_generation_id || null
    } : null,
    authority_granted: false
  };
}

function acknowledgeWake(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'wake-acknowledged', state => {
    expireWaits(state);
    const principal = normalizeActor(actor);
    const wake = state.wakes.find(item => item.wake_id === cleanText(input.wakeId || input.wake_id, 200));
    if (!wake) throw new Error('coordination-wake-not-found');
    if (wake.status === 'acknowledged') return { receipt: { wake_id: wake.wake_id, wait_id: wake.wait_id, task_id: wake.task_id, idempotent: true } };
    const wait = waitById(state, wake.wait_id);
    if (wait.actor.actor_id !== principal.actor_id || wait.actor.session_id !== principal.session_id) throw new Error('coordination-wake-ack-actor-mismatch');
    const task = taskById(state, wake.task_id);
    if (['completed', 'reconciled', 'released'].includes(task.status)) throw new Error('coordination-wake-task-terminal');
    wake.status = 'acknowledged'; wake.acknowledged_utc = now(); wake.acknowledged_by = principal;
    return { receipt: { wake_id: wake.wake_id, wait_id: wake.wait_id, task_id: wake.task_id, checkpoint_id: wake.checkpoint_id, fresh_claim_required: !state.claims.some(item => item.task_id === task.id && item.status === 'active') } };
  });
}

function sendMessage(workspaceRoot, actor, input) {
  let privateDeliveryToken = null;
  const outcome = withState(workspaceRoot, actor, 'message-sent', state => {
    const principal = normalizeActor(actor);
    const recipient = safeId(input.recipientId || input.recipient_id, 'recipient');
    const payload = cleanText(input.payload, MAX_MESSAGE_BYTES);
    if (!payload) throw new Error('coordination-message-payload-required');
    const privacy = cleanText(input.privacyClass || input.privacy_class || 'project', 40);
    if (!['public', 'project', 'private'].includes(privacy)) throw new Error('coordination-message-privacy-unsupported');
    const transport = cleanText(input.recipientTransport || input.recipient_transport || 'local', 40);
    if (!['local', 'remote', 'browser'].includes(transport)) throw new Error('coordination-message-transport-unsupported');
    if (privacy === 'private' && transport !== 'local' && input.egressApproved !== true && input.egress_approved !== true) throw new Error('coordination-private-message-egress-denied');
    const total = Object.values(state.mailboxes).reduce((sum, rows) => sum + (Array.isArray(rows) ? rows.length : 0), 0);
    if (total >= MAX_MAILBOX_MESSAGES) throw new Error('coordination-mailbox-capacity-exceeded');
    state.mailboxes[recipient] ||= [];
    const suppliedId = cleanText(input.messageId || input.message_id, 200);
    if (suppliedId) {
      const existing = state.mailboxes[recipient].find(item => item.message_id === suppliedId);
      if (existing) {
        if (existing.payload_sha256 !== hash(payload) || existing.privacy_class !== privacy || existing.recipient_transport !== transport)
          throw new Error('coordination-message-idempotency-conflict');
        return { receipt: { message_id: existing.message_id, recipient_id: recipient, privacy_class: privacy, payload_sha256: existing.payload_sha256, idempotent: true } };
      }
    }
    const message = {
      message_id: suppliedId || id('msg'), sender: principal, recipient_id: recipient, recipient_transport: transport,
      privacy_class: privacy, payload, payload_sha256: hash(payload), created_utc: now(), status: 'unread',
      evidence_refs: (input.evidence || input.evidence_refs || []).map(value => cleanText(value, 1000)).filter(Boolean).slice(0, 32)
    };
    if (privacy === 'private') {
      privateDeliveryToken = crypto.randomBytes(32).toString('base64url');
      message.private_delivery_token_sha256 = hash(privateDeliveryToken);
    }
    state.mailboxes[recipient].push(message);
    const wakes = satisfyWaits(state, 'message', message.message_id, privacy === 'private' ? [] : message.evidence_refs);
    return { receipt: { message_id: message.message_id, recipient_id: recipient, privacy_class: privacy, payload_sha256: message.payload_sha256, wake_ids: wakes.map(item => item.wake_id) } };
  });
  return privateDeliveryToken ? { ...outcome, private_delivery_token: privateDeliveryToken } : outcome;
}

function readMessages(workspaceRoot, actor, input = {}, options = {}) {
  const paths = coordinationPaths(workspaceRoot);
  const state = fs.existsSync(paths.state) ? readAuthoritativeState(paths, { persistCorruptionEvidence: false }) : defaultState(paths.workspace);
  const principal = normalizeActor(actor);
  const recipient = safeId(input.recipientId || input.recipient_id || principal.actor_id, 'recipient');
  const rows = Array.isArray(state.mailboxes?.[recipient]) ? state.mailboxes[recipient] : [];
  const limit = Math.max(1, Math.min(100, Number(input.limit || 24)));
  return { schema_version: SCHEMA_VERSION, recipient_id: recipient, messages: rows.filter(item => item.status !== 'consumed' && (item.privacy_class !== 'private' || (options.includePrivate === true && privateDeliveryProof(item, input)))).slice(-limit).map(item => {
    const { private_delivery_token_sha256, ...visible } = item;
    return visible;
  }), authority_granted: false };
}

function privateDeliveryProof(message, input) {
  const token = cleanText(input.privateDeliveryToken || input.private_delivery_token, 100);
  if (!message.private_delivery_token_sha256 || !/^[A-Za-z0-9_-]{43}$/.test(token)) return false;
  const expected = Buffer.from(message.private_delivery_token_sha256, 'hex');
  const observed = Buffer.from(hash(token), 'hex');
  return expected.length === observed.length && crypto.timingSafeEqual(expected, observed);
}

function consumeMessage(workspaceRoot, actor, input, options = {}) {
  return withState(workspaceRoot, actor, 'message-consumed', state => {
    const principal = normalizeActor(actor);
    const recipient = safeId(input.recipientId || input.recipient_id || principal.actor_id, 'recipient');
    const rows = Array.isArray(state.mailboxes?.[recipient]) ? state.mailboxes[recipient] : [];
    const message = rows.find(item => item.message_id === cleanText(input.messageId || input.message_id, 200));
    if (!message) throw new Error('coordination-message-not-found');
    if (message.privacy_class === 'private' && (options.allowPrivate === false || !privateDeliveryProof(message, input))) throw new Error('coordination-private-message-requires-delivery-proof');
    if (message.status === 'consumed') return { receipt: { message_id: message.message_id, idempotent: true } };
    message.status = 'consumed'; message.consumed_utc = now(); message.consumed_by = principal;
    return { receipt: { message_id: message.message_id, recipient_id: recipient, consumed: true } };
  });
}

function taskById(state, taskId) {
  const task = state.tasks.find(item => item.id === safeId(taskId, 'task'));
  if (!task) throw new Error('unknown-coordination-task');
  return task;
}

function ownedBy(task, principal) {
  return task.owner?.actor_id === principal.actor_id && task.owner?.session_id === principal.session_id;
}

function exactClaimProof(state, claim, input) {
  const claimId = cleanText(input.claimId || input.claim_id, 200);
  if (!claimId || claimId !== claim.id) throw new Error('claim-proof-id-missing-or-mismatched');
  const supplied = input.fencingTokens || input.fencing_tokens;
  if (!supplied || typeof supplied !== 'object' || Array.isArray(supplied)) throw new Error('claim-proof-fencing-tokens-required');
  const targets = [...claim.targets].map(normalizeTarget).sort();
  const normalizedSupplied = Object.fromEntries(Object.entries(supplied).map(([target, token]) => [normalizeTarget(target), token]));
  const keys = Object.keys(normalizedSupplied).sort();
  if (keys.length !== targets.length || keys.some((target, index) => target !== targets[index])) throw new Error('claim-proof-fencing-denominator-mismatch');
  for (const target of targets) assertFencingToken(state, claim, target, normalizedSupplied[target]);
  return true;
}

function verifiedTeamAuthority(state, task, principal, targets, supplied) {
  const hub = state.team_fabric?.hub || {};
  if (!hub.configured || !hub.connected || !hub.authoritative) throw new Error('team-authority-hub-is-not-authoritative');
  if (!supplied || typeof supplied !== 'object' || Array.isArray(supplied)) throw new Error('team-authority-grant-required');
  const grant = { ...supplied }; const seal = cleanText(grant.grant_sha256, 128).toLowerCase(); delete grant.grant_sha256;
  const expectedTargets = [...targets].sort();
  if (grant.schema_version !== 'px.coordination-authority-grant/1.0'
    || grant.project_id !== state.project.id || grant.task_id !== task.id
    || grant.actor_id !== principal.actor_id || grant.session_id !== principal.session_id
    || !Array.isArray(grant.targets) || JSON.stringify([...grant.targets].map(normalizeTarget).sort()) !== JSON.stringify(expectedTargets)
    || !Number.isFinite(Date.parse(grant.expires_utc)) || Date.parse(grant.expires_utc) <= Date.now()
    || grant.revoked !== false || !/^[a-f0-9]{64}$/.test(seal) || seal !== hash(grant)) {
    throw new Error('team-authority-grant-invalid');
  }
  return { ...grant, grant_sha256: seal };
}

function claimTask(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'task-claimed', state => {
    const task = taskById(state, input.taskId || input.task_id);
    const principal = normalizeActor(actor);
    const existingOwnedClaim = state.claims.find(item => item.status === 'active' && item.task_id === task.id && item.actor.actor_id === principal.actor_id && item.actor.session_id === principal.session_id);
    if (existingOwnedClaim) return { receipt: { claim_id: existingOwnedClaim.id, task_id: task.id, targets: existingOwnedClaim.targets, fencing_tokens: existingOwnedClaim.fencing_tokens, expires_utc: existingOwnedClaim.expires_utc, idempotent: true } };
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
    const authorityGrant = requestedAuthority === 'team_authoritative'
      ? verifiedTeamAuthority(state, task, principal, targets, input.authorityGrant || input.authority_grant)
      : null;
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
      authority_receipt: authorityGrant,
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
    exactClaimProof(state, claim, input);
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
    if (!ownedBy(task, principal)) throw new Error('task-progress-requires-owning-actor-or-session');
    const status = cleanText(input.status || 'in_progress', 40);
    if (!['claimed', 'in_progress', 'waiting', 'blocked', 'completed'].includes(status)) throw new Error('unsupported-task-status');
    const claim = state.claims.find(item => item.task_id === task.id && item.status === 'active');
    if (!claim) throw new Error('task-progress-requires-active-claim');
    if (claim.actor.actor_id !== principal.actor_id || claim.actor.session_id !== principal.session_id) throw new Error('task-progress-claim-owner-mismatch');
    exactClaimProof(state, claim, input);
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
    const wakes = task.status === 'completed' ? satisfyWaits(state, 'task', task.id, receipt.evidence) : [];
    return { receipt: { ...receipt, wake_ids: wakes.map(item => item.wake_id) } };
  });
}

function reconcileTask(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'task-reconciled', state => {
    const task = taskById(state, input.taskId || input.task_id);
    const principal = normalizeActor(actor);
    if (!ownedBy(task, principal)) throw new Error('task-reconciliation-requires-owning-actor-or-session');
    if (task.status !== 'completed') throw new Error('task-must-be-completed-before-reconciliation');
    const activeClaim = state.claims.find(item => item.task_id === task.id && item.status === 'active');
    if (!activeClaim || activeClaim.actor.actor_id !== principal.actor_id || activeClaim.actor.session_id !== principal.session_id) throw new Error('task-reconciliation-requires-owning-claim');
    exactClaimProof(state, activeClaim, input);
    const receipt = {
      id: id('reconcile'), task_id: task.id, timestamp: now(), actor: principal,
      summary: cleanText(input.summary, 4000), evidence: (input.evidence || []).map(value => cleanText(value, 1000)).filter(Boolean),
      conflicts_resolved: Boolean(input.conflictsResolved ?? input.conflicts_resolved), merge_owner: cleanText(input.mergeOwner || input.merge_owner, 200) || principal.actor_id
    };
    task.status = 'reconciled'; task.outputs.push(receipt); task.updated_utc = receipt.timestamp;
    const wakes = satisfyWaits(state, 'task', task.id, receipt.evidence);
    receipt.wake_ids = wakes.map(item => item.wake_id);
    for (const claim of state.claims) if (claim.task_id === task.id && claim.status === 'active') claim.status = 'released';
    const plan = state.plans.find(item => item.id === state.active_plan);
    if (plan && plan.task_ids.every(taskId => taskById(state, taskId).status === 'reconciled')) { plan.status = 'completed'; plan.completed_utc = now(); state.active_plan = null; }
    return { receipt };
  });
}

function releaseTask(workspaceRoot, actor, input) {
  return withState(workspaceRoot, actor, 'task-released', state => {
    const task = taskById(state, input.taskId || input.task_id); const principal = normalizeActor(actor);
    if (!ownedBy(task, principal)) throw new Error('task-release-requires-owning-actor-or-session');
    const activeClaim = state.claims.find(item => item.task_id === task.id && ['active', 'expired'].includes(item.status));
    if (!activeClaim || activeClaim.actor.actor_id !== principal.actor_id || activeClaim.actor.session_id !== principal.session_id) throw new Error('task-release-requires-owning-claim');
    exactClaimProof(state, activeClaim, input);
    for (const claim of state.claims) if (claim.task_id === task.id && ['active', 'expired'].includes(claim.status)) claim.status = 'released';
    for (const wait of state.waits || []) if (wait.task_id === task.id && wait.status === 'waiting') { wait.status = 'cancelled'; wait.cancelled_utc = now(); }
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
  return withState(workspaceRoot, actor, 'memory-captured', (state, paths, deferredPublications) => {
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
    deferredPublications.push({ file: memoryFile(paths, layer, principal.session_id), record });
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
      const stat = fs.statSync(specification.file);
      if (!stat.isFile()) throw new Error('memory-history-not-regular-file');
      if (stat.size > MAX_MEMORY_FILE_BYTES) throw new Error('memory-history-file-byte-budget-exceeded');
      if (bytes + stat.size > MAX_MEMORY_TOTAL_BYTES) throw new Error('memory-history-total-byte-budget-exceeded');
      bytes += stat.size;
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
  const state = readAuthoritativeState(paths, { persistCorruptionEvidence: false });
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
  const paths = coordinationPaths(workspaceRoot);
  if (!fs.existsSync(paths.state)) {
    const state = defaultState(paths.workspace); state.state_hash = stateHash(state);
    return {
      state: publicState(state), events: [],
      event_log_health: { status: 'missing', valid_records: 0, failed_line: null, ignored_suffix_lines: 0 },
      paths: publicPaths(paths), memory: memoryRecords(paths, state, { limit: options.memoryLimit || 12, includeContent: false }),
      instrumented: false, persistence: 'not-initialized-read-only'
    };
  }
  const state = readAuthoritativeState(paths, { persistCorruptionEvidence: false }); expireClaims(state); expireSessions(state); expireWaits(state);
  const eventTail = tailJsonlDetailed(paths.events, MAX_EVENTS);
  if (eventTail.health.status === 'healthy') {
    try {
      if (!eventTail.records.length && state.revision > 0) throw new Error('coordination-event-history-missing');
      assertEventAncestry(eventTail.records, state.state_hash, state.project.id);
      eventTail.health.integrity_verified = true;
      eventTail.health.integrity_scope = 'retained-event-suffix-and-current-state-head';
      eventTail.health.verified_records = eventTail.records.length;
    } catch (error) {
      eventTail.health = { ...eventTail.health, status: 'degraded', integrity_verified: false,
        reason: 'event-integrity-failure', detail: cleanText(error.message, 500) };
    }
  } else {
    eventTail.health.integrity_verified = false;
  }
  const eventLimit = Math.max(0, Math.min(Number(options.eventLimit ?? 40) || 0, 200));
  const privateMessageIds = new Set(Object.values(state.mailboxes || {}).flatMap(rows => rows.filter(item => item.privacy_class === 'private').map(item => item.message_id)));
  const visibleEvents = eventLimit ? eventTail.records.filter(event => event.result?.privacy_class !== 'private' && !containsPrivateMessageId(event.result, privateMessageIds)).slice(-eventLimit) : [];
  return { state: publicState(state), events: visibleEvents, event_log_health: eventTail.health, paths: publicPaths(paths), memory: memoryRecords(paths, state, { limit: options.memoryLimit || 12, includeContent: false }), instrumented: true };
}

function tailJsonl(file, limit) {
  return tailJsonlDetailed(file, limit).records;
}

function tailJsonlDetailed(file, limit) {
  let raw; let truncatedBeforeBytes = 0;
  try {
    const stat = fs.statSync(file);
    if (!stat.isFile()) throw new Error('event-history-not-regular-file');
    const retainedBytes = Math.min(stat.size, MAX_EVENT_BYTES);
    truncatedBeforeBytes = stat.size - retainedBytes;
    const handle = fs.openSync(file, 'r');
    try {
      const buffer = Buffer.alloc(retainedBytes);
      let offset = 0;
      while (offset < retainedBytes) {
        const count = fs.readSync(handle, buffer, offset, retainedBytes - offset, truncatedBeforeBytes + offset);
        if (!count) break;
        offset += count;
      }
      raw = buffer.subarray(0, offset).toString('utf8');
    } finally { fs.closeSync(handle); }
    if (truncatedBeforeBytes > 0) {
      const newline = raw.indexOf('\n');
      raw = newline < 0 ? '' : raw.slice(newline + 1);
    }
  }
  catch (error) {
    if (error.code === 'ENOENT') return { records: [], health: { status: 'missing', valid_records: 0, failed_line: null, ignored_suffix_lines: 0 } };
    return { records: [], health: { status: 'degraded', valid_records: 0, failed_line: 0, ignored_suffix_lines: 0, reason: `unreadable:${error.code || error.message}` } };
  }
  const lines = raw.split(/\r?\n/); const records = []; let failure = null;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]; if (!line.trim()) continue;
    try { records.push(JSON.parse(line)); }
    catch (error) { failure = { line: index + 1, reason: index === lines.length - 1 && !/\r?\n$/.test(raw) ? 'truncated-final-line' : 'malformed-line', error: cleanText(error.message, 500) }; break; }
  }
  const boundedLimit = Math.max(0, Math.min(MAX_EVENTS, Number(limit) || 0));
  return {
    records: boundedLimit ? records.slice(-boundedLimit) : [],
    health: failure ? { status: 'degraded', valid_records: records.length, failed_line: failure.line, ignored_suffix_lines: lines.slice(failure.line).filter(line => line.trim()).length, reason: failure.reason, detail: failure.error, truncated_before_bytes: truncatedBeforeBytes, verification_scope: 'bounded-retained-suffix' }
      : { status: 'healthy', valid_records: records.length, failed_line: null, ignored_suffix_lines: 0, truncated_before_bytes: truncatedBeforeBytes, verification_scope: 'bounded-retained-suffix' }
  };
}

function publicPaths(paths) {
  return { root: paths.root, state: paths.state, events: paths.events, handoff_json: paths.handoffJson, handoff_markdown: paths.handoffMarkdown, memory_root: paths.memory.root, quarantine: paths.quarantine };
}

function containsPrivateMessageId(value, privateIds, depth = 0) {
  if (!privateIds.size || depth > 8 || value == null) return false;
  if (typeof value === 'string') return privateIds.has(value);
  if (Array.isArray(value)) return value.some(item => containsPrivateMessageId(item, privateIds, depth + 1));
  if (typeof value === 'object') return Object.values(value).some(item => containsPrivateMessageId(item, privateIds, depth + 1));
  return false;
}

function publicState(state) {
  const copy = JSON.parse(JSON.stringify(state));
  expireClaims(copy); expireWaits(copy);
  copy.claims = copy.claims.filter(claim => claim.status === 'active');
  const privateIds = new Set(Object.values(state.mailboxes || {}).flatMap(rows => rows.filter(item => item.privacy_class === 'private').map(item => item.message_id)));
  copy.waits = copy.waits.map(wait => {
    if (wait.condition_type !== 'message' || ![...(wait.dependency_ids || []), ...(wait.satisfied_ids || [])].some(id => privateIds.has(id))) return wait;
    return { ...wait, dependency_ids: wait.dependency_ids.filter(id => !privateIds.has(id)),
      satisfied_ids: wait.satisfied_ids.filter(id => !privateIds.has(id)), exact_next_action: null, private_trigger_redacted: true };
  });
  copy.wakes = copy.wakes.map(wake => {
    if (wake.trigger_type !== 'message' || !(wake.trigger_ids || []).some(id => privateIds.has(id))) return wake;
    return { ...wake, trigger_ids: wake.trigger_ids.filter(id => !privateIds.has(id)), trigger_evidence: [],
      exact_next_action: null, private_trigger_redacted: true };
  });
  copy.mailboxes = Object.fromEntries(Object.entries(copy.mailboxes || {}).flatMap(([recipient, rows]) => {
    const visible = rows.filter(item => item.privacy_class !== 'private').map(item => ({ message_id: item.message_id, recipient_id: item.recipient_id, privacy_class: item.privacy_class, created_utc: item.created_utc, status: item.status, payload_sha256: item.payload_sha256 }));
    return visible.length ? [[recipient, visible]] : [];
  }));
  return copy;
}

function writeReceipt(paths, event) {
  atomicWrite(path.join(paths.receipts, `${event.event_id}.json`), event);
  const files = fs.readdirSync(paths.receipts).filter(name => name.endsWith('.json')).sort();
  if (files.length > MAX_EVENTS) {
    // Receipts are evidence. Retention is reported, never auto-purged.
  }
}

function handoffArtifacts(paths, state, event) {
  const tasks = state.tasks.filter(task => state.plans.find(plan => plan.id === state.active_plan)?.task_ids.includes(task.id));
  const next = tasks.find(task => ['planned', 'ready', 'released'].includes(task.status) && task.depends_on.every(dep => ['completed', 'reconciled'].includes(taskById(state, dep).status)));
  const privateIds = new Set(Object.values(state.mailboxes || {}).flatMap(rows => rows.filter(item => item.privacy_class === 'private').map(item => item.message_id)));
  const privateEvent = event.result?.privacy_class === 'private' || containsPrivateMessageId(event.result, privateIds);
  const publicLastEvent = privateEvent
    ? { event_id: event.event_id, timestamp: event.timestamp, operation: event.operation,
        event_sha256: event.event_sha256, private_message_redacted: true }
    : event;
  const packet = {
    schema_version: SCHEMA_VERSION, generated_utc: now(), project: state.project, objective: state.plans.find(plan => plan.id === state.active_plan)?.objective || null,
    phase: state.active_plan ? 'parallel-execution' : 'idle-or-complete', verified_state_hash: state.state_hash,
    tasks, active_claims: state.claims.filter(claim => claim.status === 'active'), last_event: publicLastEvent,
    team_fabric: { mode: state.team_fabric.mode, hub: state.team_fabric.hub, work_rooms: state.team_fabric.work_rooms.length },
    exact_next_action: next ? `Claim task ${next.id}: ${next.title}` : 'Review completed work or create a new parallel plan.',
    memory_refs: [path.relative(paths.workspace, paths.memory.project).replaceAll('\\', '/'), path.relative(paths.workspace, paths.memory.state).replaceAll('\\', '/')],
    event_log: path.relative(paths.workspace, paths.events).replaceAll('\\', '/'), hazards: ['Respect active claims before writing files.', 'System-memory candidates are not canonical until separately reviewed and promoted.']
  };
  packet.sha256 = hash(packet);
  const lines = [
    '# Pacify-X Cross-IDE Handoff', '', `Generated: ${packet.generated_utc}`, `State hash: ${packet.verified_state_hash}`, '',
    '## Objective', '', packet.objective || 'No active plan.', '', '## Exact next action', '', packet.exact_next_action, '',
    '## Tasks', '', ...tasks.map(task => `- [${task.status === 'reconciled' ? 'x' : ' '}] ${task.id} — ${task.title} (${task.status})`), '',
    '## Active claims', '', ...(packet.active_claims.length ? packet.active_claims.map(claim => `- ${claim.task_id}: ${claim.targets.join(', ')} — ${claim.actor.actor_id} / ${claim.actor.harness}`) : ['- None']), '',
    '## Resume contract', '', '- Read `handoff.json` and verify its SHA-256 field.', '- Read active claims before editing.', '- Claim one dependency-ready task before workspace writes.', '- Append progress and reconciliation receipts.', '- Never treat system-memory candidates as canonical facts.', ''
  ];
  return [
    { file: paths.handoffJson, afterText: `${JSON.stringify(packet, null, 2)}\n` },
    { file: paths.handoffMarkdown, afterText: `${lines.join('\n')}\n` }
  ];
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
  registerWait, waitStatus, acknowledgeWake, sendMessage, readMessages, consumeMessage, satisfyWaits,
  readCoordination, readMemoryTelemetry, taskHandoff, diagnoseWorkStop, workRoom, hash,
  readAuthoritativeState, tailJsonl, tailJsonlDetailed, acquireLock, localProcessAlive, retireProvablyStaleLock
};
