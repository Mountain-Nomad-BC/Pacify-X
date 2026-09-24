'use strict';

const { nowIso } = require('./ids');
const { UsageReceipt, parse } = require('./contracts');

class BudgetLedger {
  constructor(policyProvider = () => ({})) { this.policyProvider = policyProvider; this.receipts = []; }

  policy() { return this.policyProvider?.() || {}; }

  canAdmit(worker, task, projectedChargeUsd = null) {
    const p = this.policy();
    if (worker.costClass === 'billable-api') {
      if (p.master_enabled === false) return { allowed: false, reason: 'billable-disabled' };
      if (task.constraints.requireApprovalBeforeBillable && p.require_approval_before_billable_execution !== false) return { allowed: false, reason: 'billable-approval-required' };
      const ceiling = task.constraints.taskCostCeilingUsd;
      if (ceiling != null && projectedChargeUsd != null && projectedChargeUsd > ceiling) return { allowed: false, reason: 'task-cost-ceiling' };
    }
    if (Array.isArray(p.provider_allowlist) && p.provider_allowlist.length && !p.provider_allowlist.includes(worker.providerId)) return { allowed: false, reason: 'provider-not-allowlisted' };
    return { allowed: true, reason: 'admitted' };
  }

  record(input) {
    const receipt = parse(UsageReceipt, { schemaVersion: 'px.usage-receipt/1.0', ...input, capturedAt: input.capturedAt || nowIso() }, 'usage-receipt');
    this.receipts.push(receipt); if (this.receipts.length > 5000) this.receipts.splice(0, this.receipts.length - 5000); return receipt;
  }

  summary(taskWorkerIds = null) {
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
