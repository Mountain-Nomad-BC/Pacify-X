'use strict';

const { nowIso, sha256, requireSafeId } = require('./ids');
const { UsageReceipt, parse } = require('./contracts');
const STORE_VERSION = 'px.agent-budget-store/1.0';
const MAX_ROWS = 5000;

function microunits(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || !Number.isSafeInteger(Math.ceil(value * 1e6))) throw new Error('task-cost-number-invalid');
  return Math.ceil(value * 1e6);
}
function immutable(value) { if (value && typeof value === 'object') { for (const item of Object.values(value)) immutable(item); Object.freeze(value); } return value; }
function snapshotHash(value) { const { snapshotSha256, ...body } = value; return sha256(body); }

class BudgetLedger {
  constructor(policyProvider = () => ({}), options = {}) {
    this.policyProvider = policyProvider; this.persistence = options.persistence || null;
    this.entries = []; this.reservations = new Map(); this.revision = 0; this.epoch = 1;
    this.persistenceError = null; this.writes = Promise.resolve();
    this.unreconciledTaskIds = new Set(options.legacyTaskIds || []);
    const loaded = this.persistence?.load?.();
    if (loaded) {
      if (loaded.schemaVersion !== STORE_VERSION || !Number.isSafeInteger(loaded.revision) || loaded.revision < 1 ||
          !Number.isSafeInteger(loaded.epoch) || loaded.epoch < 1 || loaded.snapshotSha256 !== snapshotHash(loaded) ||
          !Array.isArray(loaded.entries) || !Array.isArray(loaded.reservations) || loaded.entries.length + loaded.reservations.length > MAX_ROWS) throw new Error('budget-store-invalid');
      if (!Array.isArray(loaded.unreconciledTaskIds || []) || (loaded.unreconciledTaskIds || []).some(id => typeof id !== 'string')) throw new Error('budget-store-invalid-legacy-owners');
      this.unreconciledTaskIds = new Set(loaded.unreconciledTaskIds || []);
      this.revision = loaded.revision; this.epoch = loaded.epoch + 1;
      const settlements = new Set();
      for (const row of loaded.entries) {
        parse(UsageReceipt, row.receipt, 'persisted-usage');
        for (const field of ['actualChargeUsd', 'projectedChargeUsd']) if (row.receipt[field] !== null) microunits(row.receipt[field]);
        if (row.taskId !== null) requireSafeId(row.taskId, 'usage-task');
        if (row.runId !== null) requireSafeId(row.runId, 'usage-run');
        if (row.executionId !== null) requireSafeId(row.executionId, 'usage-execution');
        if (row.settlementId !== null) {
          requireSafeId(row.settlementId, 'usage-settlement');
          if (settlements.has(row.settlementId)) throw new Error('budget-store-duplicate-settlement');
          settlements.add(row.settlementId);
        }
        const { capturedAt, ...financial } = row.receipt;
        if (row.identity !== sha256({ taskId: row.taskId, runId: row.runId, executionId: row.executionId, financial })) throw new Error('budget-store-identity-invalid');
        this.entries.push(immutable(row));
      }
      for (const row of loaded.reservations) {
        for (const field of ['executionId', 'taskId', 'runId', 'workerId', 'providerId']) requireSafeId(row[field], `reservation-${field}`);
        if (!Number.isSafeInteger(row.microunits) || row.microunits < 0 || this.reservations.has(row.executionId)) throw new Error('budget-store-invalid-reservation');
        this.reservations.set(row.executionId, immutable(row));
      }
    }
    if (this.persistence) this._persist();
  }

  get receipts() { return this.entries.map(row => row.receipt); }
  _healthy() { if (this.persistenceError) throw this.persistenceError; }
  _persist() {
    this._healthy(); this.revision += 1;
    if (!this.persistence?.save) return;
    const snapshot = { schemaVersion: STORE_VERSION, revision: this.revision, epoch: this.epoch,
      entries: this.entries, reservations: [...this.reservations.values()], unreconciledTaskIds: [...this.unreconciledTaskIds] };
    const image = JSON.parse(JSON.stringify({ ...snapshot, snapshotSha256: snapshotHash(snapshot) }));
    if (this.persistence.synchronous === true) {
      try { this.persistence.save(image); } catch (error) { this.persistenceError = error; throw error; }
    } else {
      this.writes = this.writes.then(() => { this._healthy(); return this.persistence.save(image); }).catch(error => { this.persistenceError = error; });
    }
  }
  async flush() { await this.writes; this._healthy(); }

  policy() { return this.policyProvider?.() || {}; }

  canAdmit(worker, task, projectedChargeUsd = null) {
    this._healthy();
    const p = this.policy();
    if (!task || typeof task.taskId !== 'string' || !task.constraints) return { allowed: false, reason: 'billing-task-owner-required' };
    if (this.entries.length + this.reservations.size >= MAX_ROWS) return { allowed: false, reason: 'billing-ledger-capacity' };
    if (worker.costClass === 'unknown') return { allowed: false, reason: 'billing-identity-unknown' };
    if (worker.costClass === 'billable-api') {
      if (p.master_enabled === false) return { allowed: false, reason: 'billable-disabled' };
      if (task.constraints.requireApprovalBeforeBillable && p.require_approval_before_billable_execution !== false) return { allowed: false, reason: 'billable-approval-required' };
      const ceiling = task.constraints.taskCostCeilingUsd;
      if (projectedChargeUsd == null) return { allowed: false, reason: 'task-cost-estimate-missing' };
      let estimate, maximum;
      try { estimate = microunits(projectedChargeUsd); maximum = ceiling === null ? null : (microunits(ceiling), Math.floor(ceiling * 1e6)); }
      catch { return { allowed: false, reason: 'task-cost-number-invalid' }; }
      if (maximum === null && p.allow_unbounded_task_cost !== true) return { allowed: false, reason: 'task-cost-ceiling-required' };
      if (!this.persistence?.save) return { allowed: false, reason: 'billing-persistence-unavailable' };
      if (this.unreconciledTaskIds.has(task.taskId)) return { allowed: false, reason: 'task-historical-spend-unreconciled' };
      let spent = 0;
      for (const row of this.entries) {
        if (row.receipt.costClass !== 'billable-api') continue;
        if (row.taskId === null || (row.taskId === task.taskId && row.receipt.actualChargeUsd === null)) return { allowed: false, reason: 'task-settlement-unknown' };
        if (row.taskId === task.taskId) spent += microunits(row.receipt.actualChargeUsd);
      }
      for (const row of this.reservations.values()) if (row.taskId === task.taskId) spent += row.microunits;
      if (!Number.isSafeInteger(spent + estimate) || (maximum !== null && spent + estimate > maximum)) return { allowed: false, reason: 'task-cost-ceiling' };
      if (this.entries.length + this.reservations.size >= MAX_ROWS) return { allowed: false, reason: 'billing-ledger-capacity' };
    }
    if (Array.isArray(p.provider_allowlist) && p.provider_allowlist.length && !p.provider_allowlist.includes(worker.providerId)) return { allowed: false, reason: 'provider-not-allowlisted' };
    return { allowed: true, reason: 'admitted' };
  }

  reserve({ worker, task, runId, executionId, projectedChargeUsd = null }) {
    this._healthy();
    for (const value of [task.taskId, runId, executionId, worker.workerId, worker.providerId]) requireSafeId(value, 'billing-owner');
    if (this.reservations.has(executionId) || this.entries.some(row => row.executionId === executionId)) throw new Error('billing-execution-already-recorded');
    const admission = this.canAdmit(worker, task, projectedChargeUsd);
    if (!admission.allowed) throw new Error(admission.reason);
    const row = { taskId: task.taskId, runId, executionId, workerId: worker.workerId, providerId: worker.providerId,
      costClass: worker.costClass, microunits: worker.costClass === 'billable-api' ? microunits(projectedChargeUsd) : 0 };
    this.reservations.set(executionId, immutable(row)); this._persist(); return row;
  }

  record(input) {
    this._healthy();
    const { taskId = null, runId = null, executionId = null, settlementId = null, ...usage } = input;
    for (const value of [taskId, runId, executionId]) if (value !== null) requireSafeId(value, 'usage-owner');
    if (settlementId !== null) requireSafeId(settlementId, 'usage-settlement');
    const receipt = parse(UsageReceipt, { schemaVersion: 'px.usage-receipt/1.0', ...usage, capturedAt: input.capturedAt || nowIso() }, 'usage-receipt');
    for (const field of ['actualChargeUsd', 'projectedChargeUsd']) if (receipt[field] !== null) microunits(receipt[field]);
    const { capturedAt, ...financial } = receipt;
    const identity = sha256({ taskId, runId, executionId, financial });
    const prior = settlementId !== null && this.entries.find(row => row.settlementId === settlementId);
    if (prior) { if (prior.identity !== identity) throw new Error('usage-settlement-conflict'); return prior.receipt; }
    if (executionId !== null && this.entries.some(row => row.executionId === executionId)) throw new Error('usage-execution-already-settled');
    const reservation = this.reservations.get(executionId);
    if (reservation && (reservation.taskId !== taskId || reservation.runId !== runId || reservation.workerId !== receipt.workerId || reservation.providerId !== receipt.providerId || reservation.costClass !== receipt.costClass)) throw new Error('usage-reservation-owner-mismatch');
    if (receipt.costClass === 'billable-api' && (!reservation || typeof settlementId !== 'string' || !/^[a-f0-9]{64}$/.test(settlementId))) throw new Error('billable-settlement-identity-required');
    if (this.entries.length >= MAX_ROWS) throw new Error('billing-ledger-capacity');
    this.entries.push(immutable({ taskId, runId, executionId, settlementId, identity, receipt }));
    if (reservation && (receipt.costClass !== 'billable-api' || receipt.actualChargeUsd !== null)) this.reservations.delete(executionId);
    this._persist(); return receipt;
  }

  summary(taskWorkerIds = null) {
    this._healthy();
    const rows = taskWorkerIds ? this.receipts.filter(r => taskWorkerIds.includes(r.workerId)) : this.receipts;
    const byCostClass = {};
    let actualChargeUsd = 0; let knownActualChargeCount = 0; let totalTokens = 0;
    for (const r of rows) {
      byCostClass[r.costClass] = (byCostClass[r.costClass] || 0) + 1;
      if (r.actualChargeUsd != null) { actualChargeUsd += r.actualChargeUsd; knownActualChargeCount += 1; }
      if (r.totalTokens != null) totalTokens += r.totalTokens;
    }
    return { schemaVersion: 'px.budget-summary/1.0', receiptCount: rows.length, byCostClass, totalTokens,
      actualChargeUsd: knownActualChargeCount ? actualChargeUsd : null, billingCoverage: rows.length ? knownActualChargeCount / rows.length : 0 };
  }
}

module.exports = { BudgetLedger };
