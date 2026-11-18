'use strict';

const { newId, nowIso } = require('./ids');
const { PxTask, PxRun, parse } = require('./contracts');

function immutable(value) { if (value && typeof value === 'object') { for (const item of Object.values(value)) immutable(item); Object.freeze(value); } return value; }
function parseImmutable(...args) { return immutable(parse(...args)); }

const EFFECT_ORDER = ['READ_ONLY', 'LOW_RISK', 'MUTATING', 'HIGH_RISK'];

class TaskStore {
  constructor(options = {}) {
    this.tasks = new Map(); this.runs = new Map(); this.persistence = options.persistence || null;
    this.revision = 0; this.epoch = 0; this.loadedSnapshot = false;
    this.persistenceError = null; this.writes = Promise.resolve(); this.pendingWrites = 0; this.recoveryRequired = new Set();
    this._load(); this.committed = this.snapshot(); this.epoch += 1;
    for (const [id, task] of this.tasks) this.tasks.set(id, parseImmutable(PxTask, {...task, epoch:this.epoch, revision:task.revision + 1}, 'recovered-task'));
    for (const [id, run] of this.runs) this.runs.set(id, parseImmutable(PxRun, {...run, epoch:this.epoch, revision:run.revision + 1,
      ...(run.status === 'running' ? {status:'waiting',lastError:'Host restarted; explicit execution resume required.'} : {})}, 'recovered-run'));
    if (this.loadedSnapshot) this._commit(this.tasks, this.runs);
  }

  _healthy() { if (this.persistenceError) throw this.persistenceError; }
  _fence(current, fence) {
    this._healthy();
    if (fence && (fence.epoch !== this.epoch || fence.revision !== current.revision)) throw new Error('task-state-stale-object-writer');
  }
  async flush() { await this.writes; this._healthy(); }
  initializeDurableState() {
    if (this.persistence?.synchronous !== true || this.pendingWrites) throw new Error('task-state-synchronous-owner-required');
    if (this.revision === 0) this._commit(this.tasks, this.runs);
    if (this.pendingWrites) {
      this.persistenceError = new Error('task-state-owner-did-not-acknowledge-synchronously');
      this._restoreCommitted();
    }
    this._healthy();
  }

  createTask(input) {
    this._healthy();
    if (input.taskId && this.tasks.has(input.taskId)) throw new Error('task-already-exists');
    if (this.tasks.size >= 10000) throw new Error('task-store-capacity');
    const at = nowIso();
    const task = parseImmutable(PxTask, {
      schemaVersion: 'px.agent-task/1.0', taskId: input.taskId || newId('task'), createdAt: at, updatedAt: at,
      epoch: this.epoch, revision: 1,
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

  updateTask(taskId, patch, fence = null) {
    const current = this.requireTask(taskId); this._fence(current, fence);
    if (['complete', 'failed', 'cancelled'].includes(current.status)) throw new Error('terminal-task-immutable');
    for (const key of ['taskId', 'createdAt', 'schemaVersion']) if (key in patch && patch[key] !== current[key]) throw new Error('task-identity-immutable');
    if (patch.constraints?.maxEffectClass && EFFECT_ORDER.indexOf(patch.constraints.maxEffectClass) < 0) throw new Error('task-effect-class-invalid');
    const terminalStage = { cancelled: 'CANCELLED', complete: 'COMPLETE', failed: 'FAILED' }[patch.status];
    if (terminalStage && patch.stage && patch.stage !== terminalStage) throw new Error('terminal-task-stage-invalid');
    const next = parseImmutable(PxTask, { ...current, ...patch, epoch:this.epoch, revision:current.revision + 1, ...(terminalStage ? { stage: terminalStage } : {}), constraints: { ...current.constraints, ...(patch.constraints || {}) }, updatedAt: nowIso() }, 'task');
    const tasks = new Map(this.tasks); tasks.set(taskId, next);
    this._commit(tasks, this.runs); return next;
  }

  createRun(taskId, { dispatchMode = 'single' } = {}) {
    const task = this.requireTask(taskId);
    if (['complete', 'failed', 'cancelled'].includes(task.status)) throw new Error('terminal-task-cannot-start-run');
    if (this.requiresTaskRecovery(taskId)) throw new Error('task-recovery-required');
    if (this.listRuns(taskId).some(run => ['running', 'waiting'].includes(run.status))) throw new Error('task-already-has-live-run');
    if (this.runs.size >= 10000) throw new Error('run-store-capacity');
    const at = nowIso();
    const run = parseImmutable(PxRun, { schemaVersion: 'px.agent-run/1.0', runId: newId('run'), taskId, createdAt: at, updatedAt: at, epoch:this.epoch, revision:1,
      status: 'running', dispatchMode, dispatchPending: false, activeWorkerId: null, providerSessionRef: null, routeHistory: [], round: 0, lastError: null }, 'run');
    const runs = new Map(this.runs); runs.set(run.runId, run);
    this._commit(this.tasks, runs); return run;
  }

  updateRun(runId, patch, fence = null) {
    const current = this.requireRun(runId); this._fence(current, fence);
    if (this.requiresRecovery(runId)) throw new Error('run-recovery-required');
    if (['complete', 'failed', 'cancelled'].includes(current.status)) throw new Error('terminal-run-immutable');
    for (const key of ['runId', 'taskId', 'createdAt', 'schemaVersion', 'dispatchMode', 'dispatchPending']) if (key in patch && patch[key] !== current[key]) throw new Error('run-identity-immutable');
    const next = parseImmutable(PxRun, { ...current, ...patch, epoch:this.epoch, revision:current.revision + 1, updatedAt: nowIso() }, 'run');
    const runs = new Map(this.runs); runs.set(runId, next);
    this._commit(this.tasks, runs); return next;
  }

  selectWorker(runId, workerId, reason) {
    const run = this.requireRun(runId);
    return this.updateRun(runId, { activeWorkerId: workerId, routeHistory: [...run.routeHistory, { workerId, selectedAt: nowIso(), reason: String(reason || 'selected').slice(0, 500) }].slice(-100) });
  }

  requiresRecovery(id) { return this.recoveryRequired.has(id); }
  async importLegacySnapshot(snapshot) {
    const previousRecovery = this.recoveryRequired;
    try {
      const result = this._importLegacySnapshot(snapshot);
      await this.flush();
      return result;
    } catch (error) { this.recoveryRequired = previousRecovery; throw error; }
  }
  importLegacySnapshotSync(snapshot) {
    if (this.persistence?.synchronous !== true || this.pendingWrites) throw new Error('task-state-synchronous-owner-required');
    const previousRecovery = this.recoveryRequired;
    const result = this._importLegacySnapshot(snapshot);
    this._healthy();
    if (this.pendingWrites) {
      this.persistenceError = new Error('task-state-owner-did-not-acknowledge-synchronously');
      this.recoveryRequired = previousRecovery;
      this._restoreCommitted();
      throw this.persistenceError;
    }
    return result;
  }
  _importLegacySnapshot(snapshot) {
    this._healthy();
    // Validate the complete image before touching native maps. The disposable
    // parser has no disk writer and applies the same restart quarantine rules.
    const parsed = new TaskStore({ persistence: { load: () => snapshot } });
    const tasks = new Map(this.tasks), runs = new Map(this.runs);
    const importedTasks = [], importedRuns = [], recovered = new Set(this.recoveryRequired);
    for (const task of parsed.listTasks()) {
      if (tasks.has(task.taskId)) continue;
      tasks.set(task.taskId, parseImmutable(PxTask, { ...task, epoch: this.epoch }, 'legacy-task'));
      importedTasks.push(task.taskId);
    }
    const admittedTasks = new Set(importedTasks);
    for (const run of parsed.listRuns()) {
      // A conflicting native task is not authority to attach legacy runs to it.
      if (runs.has(run.runId) || !admittedTasks.has(run.taskId)) continue;
      runs.set(run.runId, parseImmutable(PxRun, { ...run, epoch: this.epoch }, 'legacy-run'));
      importedRuns.push(run.runId);
      if (parsed.requiresRecovery(run.runId)) recovered.add(run.runId);
    }
    const previousRecovery = this.recoveryRequired;
    this.recoveryRequired = recovered;
    try { this._commit(tasks, runs); }
    catch (error) { this.recoveryRequired = previousRecovery; throw error; }
    return { importedTasks, importedRuns };
  }
  requiresTaskRecovery(taskId) { return this.listRuns(taskId).some(run => this.requiresRecovery(run.runId) || run.dispatchPending === true); }

  beginMeshDispatch(runId) { return this._meshDispatchState(runId, true); }
  settleMeshDispatch(runId) { return this._meshDispatchState(runId, false); }
  _meshDispatchState(runId, pending) {
    const current = this.requireRun(runId);
    if (this.requiresRecovery(runId)) throw new Error('run-recovery-required');
    if (current.dispatchMode !== 'mesh') throw new Error('run-dispatch-mode-mismatch');
    if (pending && current.status !== 'running') throw new Error('run-dispatch-not-running');
    if (current.dispatchPending === pending) throw new Error('run-dispatch-state-unchanged');
    // Only the controller's settled branch join may clear this marker, including
    // after cancellation. Ordinary status edits cannot erase provider custody.
    const next = parseImmutable(PxRun, { ...current, dispatchPending: pending, revision: current.revision + 1, updatedAt: nowIso() }, 'run');
    const runs = new Map(this.runs); runs.set(runId, next);
    this._commit(this.tasks, runs); return next;
  }

  requireTask(id) { this._healthy(); const value = this.tasks.get(id); if (!value) throw new Error('task-not-found'); return value; }
  requireRun(id) { this._healthy(); const value = this.runs.get(id); if (!value) throw new Error('run-not-found'); return value; }
  listTasks() { return [...this.tasks.values()]; }
  listRuns(taskId = null) { return [...this.runs.values()].filter(r => !taskId || r.taskId === taskId); }
  snapshot() { return { schemaVersion: 'px.agent-task-store/2.0', epoch: this.epoch, revision: this.revision, tasks: this.listTasks(), runs: this.listRuns() }; }

  _load() {
    if (!this.persistence?.load) return;
    const snap = this.persistence.load();
    if (snap == null) return;
    if (!['px.agent-task-store/1.0','px.agent-task-store/2.0'].includes(snap.schemaVersion) || !Array.isArray(snap.tasks) || !Array.isArray(snap.runs)
        || snap.tasks.length > 10000 || snap.runs.length > 10000) throw new Error('task-state-corrupt-snapshot');
    if (snap.schemaVersion === 'px.agent-task-store/2.0') {
      if (!Number.isSafeInteger(snap.epoch) || snap.epoch < 1 || !Number.isSafeInteger(snap.revision) || snap.revision < 1) throw new Error('task-state-corrupt-generation');
      this.epoch = snap.epoch; this.revision = snap.revision;
    }
    this.loadedSnapshot = true;
    const tasks = new Map(), runs = new Map();
    for (const row of snap.tasks) { const task=parseImmutable(PxTask,row,'persisted-task'); if (tasks.has(task.taskId)) throw new Error('task-state-duplicate-task'); tasks.set(task.taskId,task); }
    for (const row of snap.runs) {
      const run=parseImmutable(PxRun,row,'persisted-run');
      if (runs.has(run.runId) || !tasks.has(run.taskId)) throw new Error('task-state-invalid-run-owner');
      runs.set(run.runId,run);
      const live = ['running','waiting','blocked'].includes(run.status);
      // Legacy images cannot distinguish an undispatched mesh from a lost
      // provider call, including a terminal cancellation before branch return.
      if (run.dispatchPending === true || (run.activeWorkerId && live)
          || (!run.dispatchMode && (live || run.status === 'cancelled'))) this.recoveryRequired.add(run.runId);
    }
    this.tasks = tasks; this.runs = runs;
  }

  _restoreCommitted() {
    this.revision = this.committed.revision; this.epoch = this.committed.epoch;
    this.tasks = new Map(this.committed.tasks.map(row => [row.taskId, immutable(row)]));
    this.runs = new Map(this.committed.runs.map(row => [row.runId, immutable(row)]));
  }

  _commit(tasks, runs) {
    this._healthy();
    const snapshot = JSON.parse(JSON.stringify({ schemaVersion: 'px.agent-task-store/2.0', epoch:this.epoch, revision:this.revision + 1, tasks: [...tasks.values()], runs: [...runs.values()] }));
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
    this.tasks = tasks; this.runs = runs; this.revision = snapshot.revision;
  }
}

module.exports = { TaskStore, EFFECT_ORDER };
