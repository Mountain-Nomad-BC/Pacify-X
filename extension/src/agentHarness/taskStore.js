'use strict';

const { newId, nowIso } = require('./ids');
const { PxTask, PxRun, parse } = require('./contracts');

function immutable(value) { if (value && typeof value === 'object') { for (const item of Object.values(value)) immutable(item); Object.freeze(value); } return value; }
function parseImmutable(...args) { return immutable(parse(...args)); }

const EFFECT_ORDER = ['READ_ONLY', 'LOW_RISK', 'MUTATING', 'HIGH_RISK'];

class TaskStore {
  constructor(options = {}) {
    this.tasks = new Map(); this.runs = new Map(); this.persistence = options.persistence || null;
    this.persistenceError = null; this.writes = Promise.resolve(); this.pendingWrites = 0; this.recoveryRequired = new Set();
    this._load(); this.committed = this.snapshot();
  }

  _healthy() { if (this.persistenceError) throw this.persistenceError; }
  async flush() { await this.writes; this._healthy(); }

  createTask(input) {
    this._healthy();
    if (input.taskId && this.tasks.has(input.taskId)) throw new Error('task-already-exists');
    if (this.tasks.size >= 10000) throw new Error('task-store-capacity');
    const at = nowIso();
    const task = parseImmutable(PxTask, {
      schemaVersion: 'px.agent-task/1.0', taskId: input.taskId || newId('task'), createdAt: at, updatedAt: at,
      goal: input.goal, mode: input.mode || 'ASK', stage: 'INTAKE', targets: input.targets || [], activeSkills: [],
      constraints: {
        maxEffectClass: input.maxEffectClass || 'READ_ONLY', contextBudgetTokens: Number(input.contextBudgetTokens || 12000),
        taskCostCeilingUsd: input.taskCostCeilingUsd ?? null, localFirst: input.localFirst !== false,
        requireApprovalBeforeBillable: input.requireApprovalBeforeBillable !== false
      },
      completionContract: input.completionContract || [], confidence: null, status: 'active'
    }, 'task');
    const tasks = new Map(this.tasks); tasks.set(task.taskId, task);
    this._commit(tasks, this.runs); return task;
  }

  updateTask(taskId, patch) {
    const current = this.requireTask(taskId);
    if (['complete', 'failed', 'cancelled'].includes(current.status)) throw new Error('terminal-task-immutable');
    for (const key of ['taskId', 'createdAt', 'schemaVersion']) if (key in patch && patch[key] !== current[key]) throw new Error('task-identity-immutable');
    if (patch.constraints?.maxEffectClass && EFFECT_ORDER.indexOf(patch.constraints.maxEffectClass) < 0) throw new Error('task-effect-class-invalid');
    const terminalStage = { cancelled: 'CANCELLED', complete: 'COMPLETE', failed: 'FAILED' }[patch.status];
    if (terminalStage && patch.stage && patch.stage !== terminalStage) throw new Error('terminal-task-stage-invalid');
    const next = parseImmutable(PxTask, { ...current, ...patch, ...(terminalStage ? { stage: terminalStage } : {}), constraints: { ...current.constraints, ...(patch.constraints || {}) }, updatedAt: nowIso() }, 'task');
    const tasks = new Map(this.tasks); tasks.set(taskId, next);
    this._commit(tasks, this.runs); return next;
  }

  createRun(taskId) {
    const task = this.requireTask(taskId);
    if (['complete', 'failed', 'cancelled'].includes(task.status)) throw new Error('terminal-task-cannot-start-run');
    if (this.listRuns(taskId).some(run => ['running', 'waiting'].includes(run.status))) throw new Error('task-already-has-live-run');
    if (this.runs.size >= 10000) throw new Error('run-store-capacity');
    const at = nowIso();
    const run = parseImmutable(PxRun, { schemaVersion: 'px.agent-run/1.0', runId: newId('run'), taskId, createdAt: at, updatedAt: at,
      status: 'running', activeWorkerId: null, providerSessionRef: null, routeHistory: [], round: 0, lastError: null }, 'run');
    const runs = new Map(this.runs); runs.set(run.runId, run);
    this._commit(this.tasks, runs); return run;
  }

  updateRun(runId, patch) {
    const current = this.requireRun(runId);
    if (this.requiresRecovery(runId)) throw new Error('run-recovery-required');
    if (['complete', 'failed', 'cancelled'].includes(current.status)) throw new Error('terminal-run-immutable');
    for (const key of ['runId', 'taskId', 'createdAt', 'schemaVersion']) if (key in patch && patch[key] !== current[key]) throw new Error('run-identity-immutable');
    const next = parseImmutable(PxRun, { ...current, ...patch, updatedAt: nowIso() }, 'run');
    const runs = new Map(this.runs); runs.set(runId, next);
    this._commit(this.tasks, runs); return next;
  }

  selectWorker(runId, workerId, reason) {
    const run = this.requireRun(runId);
    return this.updateRun(runId, { activeWorkerId: workerId, routeHistory: [...run.routeHistory, { workerId, selectedAt: nowIso(), reason: String(reason || 'selected').slice(0, 500) }].slice(-100) });
  }

  requiresRecovery(id) { return this.recoveryRequired.has(id); }

  requireTask(id) { this._healthy(); const value = this.tasks.get(id); if (!value) throw new Error('task-not-found'); return value; }
  requireRun(id) { this._healthy(); const value = this.runs.get(id); if (!value) throw new Error('run-not-found'); return value; }
  listTasks() { return [...this.tasks.values()]; }
  listRuns(taskId = null) { return [...this.runs.values()].filter(r => !taskId || r.taskId === taskId); }
  snapshot() { return { schemaVersion: 'px.agent-task-store/1.0', tasks: this.listTasks(), runs: this.listRuns() }; }

  _load() {
    if (!this.persistence?.load) return;
    const snap = this.persistence.load();
    if (snap == null) return;
    if (snap.schemaVersion !== 'px.agent-task-store/1.0' || !Array.isArray(snap.tasks) || !Array.isArray(snap.runs)
        || snap.tasks.length > 10000 || snap.runs.length > 10000) throw new Error('task-state-corrupt-snapshot');
    const tasks = new Map(), runs = new Map();
    for (const row of snap.tasks) { const task=parseImmutable(PxTask,row,'persisted-task'); if (tasks.has(task.taskId)) throw new Error('task-state-duplicate-task'); tasks.set(task.taskId,task); }
    for (const row of snap.runs) { const run=parseImmutable(PxRun,row,'persisted-run'); if (runs.has(run.runId) || !tasks.has(run.taskId)) throw new Error('task-state-invalid-run-owner'); runs.set(run.runId,run); if (run.activeWorkerId && ['running','waiting'].includes(run.status)) this.recoveryRequired.add(run.runId); }
    this.tasks = tasks; this.runs = runs;
  }

  _restoreCommitted() {
    this.tasks = new Map(this.committed.tasks.map(row => [row.taskId, immutable(row)]));
    this.runs = new Map(this.committed.runs.map(row => [row.runId, immutable(row)]));
  }

  _commit(tasks, runs) {
    this._healthy();
    const snapshot = JSON.parse(JSON.stringify({ schemaVersion: 'px.agent-task-store/1.0', tasks: [...tasks.values()], runs: [...runs.values()] }));
    if (this.persistence?.save) {
      let saved;
      try {
        saved = this.pendingWrites ? this.writes.then(() => { this._healthy(); return this.persistence.save(snapshot); }) : this.persistence.save(snapshot);
      } catch (error) { this.persistenceError = error; throw error; }
      if (saved && typeof saved.then === 'function') {
        this.pendingWrites += 1;
        this.writes = Promise.resolve(saved).then(() => { this._healthy(); this.committed = snapshot; }).catch(error => {
          this.persistenceError = this.persistenceError || error; this._restoreCommitted();
        }).finally(() => { this.pendingWrites -= 1; });
      } else this.committed = snapshot;
    } else this.committed = snapshot;
    this.tasks = tasks; this.runs = runs;
  }
}

module.exports = { TaskStore, EFFECT_ORDER };
