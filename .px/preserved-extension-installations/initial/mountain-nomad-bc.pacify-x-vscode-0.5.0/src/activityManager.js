'use strict';

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SCHEMA_VERSION = 'px.activity/1.0';
const EVENT_LIMIT = 20000;
const activeWriters = new Set();

function now() { return new Date().toISOString(); }
function sha(value) { return crypto.createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex'); }
function text(value, limit = 512) { return String(value ?? '').trim().slice(0, limit); }
function safeId(value, fallback = 'unknown') {
  const normalized = text(value, 200).toLowerCase().replace(/[^a-z0-9._:-]+/g, '-').replace(/^-+|-+$/g, '');
  return normalized || fallback;
}
function activityPaths(workspaceRoot) {
  const workspace = path.resolve(workspaceRoot || '');
  if (!workspaceRoot || workspace === path.parse(workspace).root) throw new Error('activity-workspace-must-be-bounded');
  const coordination = path.join(workspace, '.engineering-bootstrap', 'coordination');
  const root = path.join(coordination, 'activity');
  return { workspace, coordination, root, state: path.join(root, 'current.json'), events: path.join(root, 'events.jsonl'), lock: path.join(root, '.activity.lock') };
}
function normalizeActor(actor = {}) {
  return {
    actor_id: safeId(actor.actorId || actor.actor_id, 'unknown-actor'),
    session_id: safeId(actor.sessionId || actor.session_id, 'unknown-session'),
    harness: text(actor.harness || 'unknown-harness', 120),
    accountable_owner: text(actor.accountableOwner || actor.accountable_owner || 'local-user', 160)
  };
}
function normalizePolicy(input = {}) {
  return {
    enabled: input.enabled !== false,
    paused: Boolean(input.paused),
    metadata_only: true,
    capture_file_events: input.captureFileEvents !== false && input.capture_file_events !== false,
    capture_terminal_lifecycle: input.captureTerminalLifecycle !== false && input.capture_terminal_lifecycle !== false,
    capture_task_lifecycle: input.captureTaskLifecycle !== false && input.capture_task_lifecycle !== false,
    capture_debug_lifecycle: input.captureDebugLifecycle !== false && input.capture_debug_lifecycle !== false,
    capture_test_lifecycle: input.captureTestLifecycle !== false && input.capture_test_lifecycle !== false,
    capture_mcp_calls: input.captureMcpCalls !== false && input.capture_mcp_calls !== false,
    capture_command_text: Boolean(input.captureCommandText || input.capture_command_text),
    retention_days: Math.min(3650, Math.max(1, Number(input.retentionDays || input.retention_days || 30))),
    content_policy: 'hash-or-redacted-reference-only',
    automatic_purge: false
  };
}
function defaultState(paths, policy = {}) {
  return {
    schema_version: SCHEMA_VERSION, authority: 'project-owned observational trace; non-canonical and non-authorizing',
    project_root_hash: sha(paths.workspace), revision: 0, event_count: 0, updated_utc: now(), last_event_sha256: null,
    policy: normalizePolicy(policy), totals: { by_category: {}, by_status: {} }, agents: {}, active_operations: {}
  };
}
function readJson(file, fallback) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return fallback; } }
function atomicWrite(file, value) {
  const temporary = `${file}.${process.pid}.${crypto.randomUUID()}.tmp`;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  fs.renameSync(temporary, file);
}
function acquireLock(paths, timeoutMs = 4000) {
  fs.mkdirSync(paths.root, { recursive: true }); const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const descriptor = fs.openSync(paths.lock, 'wx'); fs.writeFileSync(descriptor, JSON.stringify({ pid: process.pid, host: os.hostname(), acquired_utc: now() }));
      return () => { try { fs.closeSync(descriptor); } catch {} try { fs.unlinkSync(paths.lock); } catch {} };
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      try { if (Date.now() - fs.statSync(paths.lock).mtimeMs > 30000) { fs.unlinkSync(paths.lock); continue; } } catch { continue; }
    }
  }
  throw new Error('activity-lock-timeout');
}
function sanitizeMetadata(value, depth = 0) {
  if (depth > 4 || value == null) return value == null ? null : '[depth-bounded]';
  if (typeof value === 'string') return text(value, 1000);
  if (typeof value === 'number' || typeof value === 'boolean') return value;
  if (Array.isArray(value)) return value.slice(0, 50).map(item => sanitizeMetadata(item, depth + 1));
  if (typeof value !== 'object') return text(value, 200);
  const result = {};
  for (const [key, item] of Object.entries(value).slice(0, 80)) {
    if (/secret|token|password|credential|authorization|cookie|content|prompt|stdout|stderr|api.?key/i.test(key)) { result[key] = '[redacted]'; continue; }
    result[text(key, 120)] = sanitizeMetadata(item, depth + 1);
  }
  return result;
}
function normalizeScope(workspace, value) {
  const candidate = text(value, 1000); if (!candidate) return null;
  try {
    const resolved = path.resolve(candidate); const relative = path.relative(workspace, resolved);
    if (relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))) return relative.replaceAll('\\', '/') || '.';
  } catch {}
  return candidate.replaceAll('\\', '/').replace(/^[A-Za-z]:\//, '[drive]/').slice(-512);
}
function recordActivity(workspaceRoot, actorInput, input = {}, policyInput = {}) {
  const paths = activityPaths(workspaceRoot); const policy = normalizePolicy(policyInput); const operation = text(input.operation, 200) || 'activity.unknown';
  if ((!policy.enabled || policy.paused) && operation !== 'observability.policy-changed') return { recorded: false, reason: policy.enabled ? 'activity-paused' : 'activity-disabled' };
  if (activeWriters.has(paths.root)) return { recorded: false, reason: 'activity-reentrancy-guard' };
  activeWriters.add(paths.root); let release = null;
  try {
    release = acquireLock(paths);
    const state = readJson(paths.state, defaultState(paths, policy)); state.policy = policy;
    const actor = normalizeActor(actorInput); const timestamp = now(); const status = ['started', 'running', 'succeeded', 'failed', 'cancelled', 'observed', 'blocked', 'idle'].includes(input.status) ? input.status : 'observed';
    const correlationId = safeId(input.correlationId || input.correlation_id || `trace-${crypto.randomUUID()}`, 'trace');
    const event = {
      schema_version: SCHEMA_VERSION, event_id: `act-${crypto.randomUUID()}`, timestamp, correlation_id: correlationId,
      parent_correlation_id: input.parentCorrelationId || input.parent_correlation_id ? safeId(input.parentCorrelationId || input.parent_correlation_id, null) : null,
      task_id: input.taskId || input.task_id ? safeId(input.taskId || input.task_id, null) : null,
      claim_id: input.claimId || input.claim_id ? safeId(input.claimId || input.claim_id, null) : null,
      actor, source: text(input.source || 'pacify-x', 120), category: safeId(input.category || 'system', 'system'), operation,
      status, effect: safeId(input.effect || 'observe', 'observe'), duration_ms: input.durationMs == null && input.duration_ms == null ? null : Math.max(0, Number(input.durationMs ?? input.duration_ms)),
      scope_refs: [...new Set((input.scopeRefs || input.scope_refs || []).map(value => normalizeScope(paths.workspace, value)).filter(Boolean))].slice(0, 50),
      input_sha256: text(input.inputSha256 || input.input_sha256, 64) || null, output_sha256: text(input.outputSha256 || input.output_sha256, 64) || null,
      metadata: sanitizeMetadata(input.metadata || {}), content_captured: false, previous_event_sha256: state.last_event_sha256 || null
    };
    event.event_sha256 = sha(event);
    fs.appendFileSync(paths.events, `${JSON.stringify(event)}\n`, 'utf8');
    state.revision = Number(state.revision || 0) + 1; state.event_count = Number(state.event_count || 0) + 1; state.updated_utc = timestamp; state.last_event_sha256 = event.event_sha256;
    state.totals ||= { by_category: {}, by_status: {} }; state.totals.by_category[event.category] = Number(state.totals.by_category[event.category] || 0) + 1; state.totals.by_status[event.status] = Number(state.totals.by_status[event.status] || 0) + 1;
    const operationKey = `${actor.actor_id}:${actor.session_id}:${correlationId}`;
    if (status === 'started' || status === 'running') state.active_operations[operationKey] = { correlation_id: correlationId, task_id: event.task_id, actor, category: event.category, operation, source: event.source, started_utc: timestamp, scope_refs: event.scope_refs };
    else if (['succeeded', 'failed', 'cancelled', 'blocked', 'idle'].includes(status)) delete state.active_operations[operationKey];
    const priorAgent = state.agents[`${actor.actor_id}:${actor.session_id}`] || {};
    state.agents[`${actor.actor_id}:${actor.session_id}`] = status === 'observed'
      ? { ...priorAgent, ...actor, last_seen_utc: timestamp, task_id: event.task_id || priorAgent.task_id || null }
      : { ...actor, last_seen_utc: timestamp, status: status === 'started' || status === 'running' ? 'working' : status === 'failed' || status === 'blocked' ? 'attention' : 'idle', current_operation: status === 'started' || status === 'running' ? operation : null, correlation_id: status === 'started' || status === 'running' ? correlationId : null, task_id: event.task_id };
    atomicWrite(paths.state, state);
    return { recorded: true, event, state_revision: state.revision, paths: { root: paths.root, state: paths.state, events: paths.events } };
  } finally { try { release?.(); } finally { activeWriters.delete(paths.root); } }
}
function tailEvents(file, limit) {
  try { return fs.readFileSync(file, 'utf8').split(/\r?\n/).filter(Boolean).slice(-Math.min(EVENT_LIMIT, Math.max(limit * 4, limit))).map(line => JSON.parse(line)); } catch { return []; }
}
function eventIntegrity(events, state) {
  const invalidEventIds = []; const chainBreaks = [];
  events.forEach((event, index) => {
    const { event_sha256: sealed, ...unsealed } = event;
    if (!sealed || sha(unsealed) !== sealed) invalidEventIds.push(event.event_id || `index-${index}`);
    if (index > 0 && event.previous_event_sha256 !== events[index - 1].event_sha256) chainBreaks.push(event.event_id || `index-${index}`);
  });
  const counterDrift = Number(state.event_count || 0) < events.length || (events.length && state.last_event_sha256 !== events.at(-1).event_sha256);
  return { valid: invalidEventIds.length === 0 && chainBreaks.length === 0 && !counterDrift, checked_events: events.length, invalid_event_ids: invalidEventIds.slice(0, 50), chain_breaks: chainBreaks.slice(0, 50), counter_drift: counterDrift, truncated: Number(state.event_count || 0) > events.length };
}
function readActivity(workspaceRoot, options = {}) {
  const paths = activityPaths(workspaceRoot); const exists = fs.existsSync(paths.state); const state = readJson(paths.state, defaultState(paths, options.policy));
  const limit = Math.min(500, Math.max(1, Number(options.limit || 100))); const query = text(options.query, 300).toLowerCase();
  const ledgerEvents = tailEvents(paths.events, EVENT_LIMIT); const integrity = eventIntegrity(ledgerEvents, state);
  const events = ledgerEvents.filter(event => {
    if (options.category && event.category !== options.category) return false;
    if (options.status && event.status !== options.status) return false;
    if (!query) return true;
    return `${event.operation} ${event.category} ${event.status} ${event.source} ${event.actor?.actor_id} ${(event.scope_refs || []).join(' ')} ${event.task_id || ''}`.toLowerCase().includes(query);
  }).slice(-limit).reverse();
  const activeOperations = Object.values(state.active_operations || {}).map(item => ({ ...item, stale: Date.now() - Date.parse(item.started_utc) > 30 * 60 * 1000 }));
  return {
    schema_version: SCHEMA_VERSION, generated_utc: now(), instrumented: exists, authority: state.authority,
    policy: state.policy, revision: state.revision, event_count: state.event_count, last_event_sha256: state.last_event_sha256, integrity,
    totals: state.totals, agents: Object.values(state.agents || {}).sort((a, b) => String(b.last_seen_utc).localeCompare(String(a.last_seen_utc))),
    active_operations: activeOperations, matched_count: events.length, events,
    paths: { root: paths.root, state: paths.state, events: paths.events },
    limitations: ['Metadata and hashes only; prompts, file contents, terminal output, secrets, and private reasoning are not captured.', 'Unmediated external activity is unattributed unless an agent supplies a correlation identity.', 'Retention is declared but automatic destructive purge is disabled.']
  };
}

module.exports = { SCHEMA_VERSION, activityPaths, normalizePolicy, normalizeActor, sanitizeMetadata, recordActivity, readActivity, sha };
