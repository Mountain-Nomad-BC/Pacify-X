'use strict';

const { newId, nowIso } = require('./ids');
const { PxTask, PxRun, parse } = require('./contracts');

const EFFECT_ORDER = ['READ_ONLY', 'LOW_RISK', 'MUTATING', 'HIGH_RISK'];

class TaskStore {
  constructor(options = {}) { this.tasks = new Map(); this.runs = new Map(); this.persistence = options.persistence || null; this._load(); }

  createTask(input) {
    const at = nowIso();
    const task = parse(PxTask, {
      schemaVersion: 'px.agent-task/1.0', taskId: input.taskId || newId('task'), createdAt: at, updatedAt: at,
      goal: input.goal, mode: input.mode || 'ASK', stage: 'INTAKE', targets: input.targets || [], activeSkills: [],
      constraints: {
        maxEffectClass: input.maxEffectClass || 'READ_ONLY', contextBudgetTokens: Number(input.contextBudgetTokens || 12000),
        taskCostCeilingUsd: input.taskCostCeilingUsd ?? null, localFirst: input.localFirst !== false,
        requireApprovalBeforeBillable: input.requireApprovalBeforeBillable !== false
      },
      completionContract: input.completionContract || [], confidence: null, status: 'active'
    }, 'task');
    this.tasks.set(task.taskId, task); this._persist(); return task;
  }

  updateTask(taskId, patch) {
    const current = this.requireTask(taskId);
    if (patch.constraints?.maxEffectClass && EFFECT_ORDER.indexOf(patch.constraints.maxEffectClass) < 0) throw new Error('task-effect-class-invalid');
    const next = parse(PxTask, { ...current, ...patch, constraints: { ...current.constraints, ...(patch.constraints || {}) }, updatedAt: nowIso() }, 'task');
    this.tasks.set(taskId, next); this._persist(); return next;
  }

  createRun(taskId) {
    this.requireTask(taskId); const at = nowIso();
    const run = parse(PxRun, { schemaVersion: 'px.agent-run/1.0', runId: newId('run'), taskId, createdAt: at, updatedAt: at,
      status: 'running', activeWorkerId: null, providerSessionRef: null, routeHistory: [], round: 0, lastError: null }, 'run');
    this.runs.set(run.runId, run); this._persist(); return run;
  }

  updateRun(runId, patch) {
    const current = this.requireRun(runId);
    const next = parse(PxRun, { ...current, ...patch, updatedAt: nowIso() }, 'run');
    this.runs.set(runId, next); this._persist(); return next;
  }

  selectWorker(runId, workerId, reason) {
    const run = this.requireRun(runId);
    return this.updateRun(runId, { activeWorkerId: workerId, routeHistory: [...run.routeHistory, { workerId, selectedAt: nowIso(), reason: String(reason || 'selected').slice(0, 500) }].slice(-100) });
  }

  requireTask(id) { const value = this.tasks.get(id); if (!value) throw new Error('task-not-found'); return value; }
  requireRun(id) { const value = this.runs.get(id); if (!value) throw new Error('run-not-found'); return value; }
  listTasks() { return [...this.tasks.values()]; }
  listRuns(taskId = null) { return [...this.runs.values()].filter(r => !taskId || r.taskId === taskId); }
  snapshot() { return { schemaVersion: 'px.agent-task-store/1.0', tasks: this.listTasks(), runs: this.listRuns() }; }

  _load() {
    if (!this.persistence?.load) return;
    try { const snap = this.persistence.load(); for (const row of snap?.tasks || []) { const task=parse(PxTask,row,'persisted-task'); this.tasks.set(task.taskId,task); } for (const row of snap?.runs || []) { const run=parse(PxRun,row,'persisted-run'); this.runs.set(run.runId,run); } } catch { this.tasks.clear(); this.runs.clear(); }
  }

  _persist() { if (this.persistence?.save) void Promise.resolve(this.persistence.save(this.snapshot())).catch(() => {}); }
}

module.exports = { TaskStore, EFFECT_ORDER };
