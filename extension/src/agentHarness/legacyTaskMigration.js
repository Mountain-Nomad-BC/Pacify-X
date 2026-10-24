'use strict';

// Explicit, hash-bound migration of legacy VS Code workspaceState task state into
// the native durable file store. The legacy snapshot is never discarded: the exact
// source bytes are retained, bound by digest, and re-import is refused once the
// same snapshot has already been reconciled. Import is additive only; a task/run
// that already exists in the native store is left untouched rather than overwritten.

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const RECEIPT_SCHEMA = 'px.legacy-task-migration/1.0';
const MIGRATION_DIRECTORY = path.join('.agentic_engineering_os_px', 'runtime-core', 'agent-console', 'legacy-migration');

function digest(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value), 'utf8').digest('hex');
}

function rejectLinks(target) {
  let cursor = path.resolve(target);
  while (true) {
    try { if (fs.lstatSync(cursor).isSymbolicLink()) throw new Error('legacy-migration-linked-path'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    const parent = path.dirname(cursor);
    if (parent === cursor) break;
    cursor = parent;
  }
}

function readJsonIfPresent(file) {
  rejectLinks(file);
  if (!fs.existsSync(file)) return null;
  const value = JSON.parse(fs.readFileSync(file, 'utf8'));
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
}

// Accept both the historic store shapes: the bare snapshot, or the
// workspaceState envelope `{ state: snapshot, migratedAt }`.
function legacySnapshot(raw) {
  if (raw == null) return null;
  if (raw.schemaVersion === 'px.agent-task-store/1.0' || raw.schemaVersion === 'px.agent-task-store/2.0') return raw;
  const nested = raw.state;
  if (nested && typeof nested === 'object' && !Array.isArray(nested)) return nested;
  return null;
}

function migrateLegacyTaskState(projectRoot, legacyRaw, taskStore) {
  const snapshot = legacySnapshot(legacyRaw);
  if (snapshot == null) {
    return { schemaVersion: RECEIPT_SCHEMA, status: 'NOTHING_TO_MIGRATE', source_sha256: null, authority_granted: false };
  }
  if (!Array.isArray(snapshot.tasks) || !Array.isArray(snapshot.runs)) {
    throw new Error('legacy-task-state-malformed');
  }
  const sourceSha256 = digest(snapshot);
  const directory = path.join(projectRoot, MIGRATION_DIRECTORY);
  rejectLinks(directory);
  fs.mkdirSync(directory, { recursive: true });
  rejectLinks(directory);

  // Retain the exact source snapshot once, content-addressed, so the original
  // bytes survive independently of the legacy store.
  const retained = path.join(directory, `source-${sourceSha256}.json`);
  if (!fs.existsSync(retained)) {
    const prepared = path.join(directory, `.source-${crypto.randomUUID()}.prepared`);
    const fd = fs.openSync(prepared, 'wx');
    try {
      fs.writeFileSync(fd, Buffer.from(JSON.stringify(snapshot), 'utf8'));
      fs.fsyncSync(fd);
    } finally { fs.closeSync(fd); }
    try { fs.renameSync(prepared, retained); }
    catch (error) {
      if (fs.existsSync(prepared)) fs.unlinkSync(prepared);
      if (!fs.existsSync(retained)) throw error;
    }
  }

  const receiptPath = path.join(directory, `receipt-${sourceSha256}.json`);
  const prior = readJsonIfPresent(receiptPath);
  if (prior && prior.schemaVersion === RECEIPT_SCHEMA && prior.source_sha256 === sourceSha256) {
    // Idempotent: the same exact snapshot was already reconciled.
    return { ...prior, status: 'ALREADY_MIGRATED', authority_granted: false };
  }

  const importedTasks = [];
  const importedRuns = [];
  const existingTasks = new Set(taskStore.listTasks().map(task => task.taskId));
  for (const row of snapshot.tasks) {
    const taskId = row && row.taskId;
    if (typeof taskId !== 'string' || existingTasks.has(taskId)) continue;
    taskStore.tasks.set(taskId, row);
    existingTasks.add(taskId);
    importedTasks.push(taskId);
  }
  for (const row of snapshot.runs) {
    const runId = row && row.runId;
    if (typeof runId !== 'string' || taskStore.runs.has(runId) || !existingTasks.has(row.taskId)) continue;
    taskStore.runs.set(runId, row);
    importedRuns.push(runId);
  }
  taskStore._persist();

  const receipt = {
    schemaVersion: RECEIPT_SCHEMA,
    status: 'MIGRATED',
    source_sha256: sourceSha256,
    retained_source: path.relative(projectRoot, retained).split(path.sep).join('/'),
    legacy_task_count: snapshot.tasks.length,
    legacy_run_count: snapshot.runs.length,
    imported_task_ids: importedTasks,
    imported_run_ids: importedRuns,
    migrated_utc: new Date().toISOString(),
    authority_granted: false
  };
  const prepared = path.join(directory, `.receipt-${crypto.randomUUID()}.prepared`);
  const fd = fs.openSync(prepared, 'wx');
  try {
    fs.writeFileSync(fd, Buffer.from(JSON.stringify(receipt), 'utf8'));
    fs.fsyncSync(fd);
  } finally { fs.closeSync(fd); }
  fs.renameSync(prepared, receiptPath);
  return receipt;
}

module.exports = { migrateLegacyTaskState, legacySnapshot, RECEIPT_SCHEMA };