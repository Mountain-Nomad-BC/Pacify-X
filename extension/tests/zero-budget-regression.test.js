'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

function defaults(hostSettings) {
  const s = hostSettings?.() || {};
  return {
    contextBudgetTokens: s.contextInjectionCapTokens || 12000,
    taskCostCeilingUsd: s.executionPolicy?.max_cost_per_task_usd ?? null,
    localFirst: s.executionPolicy?.local_first !== false,
    requireApprovalBeforeBillable: s.executionPolicy?.require_approval_before_billable_execution !== false,
  };
}

test('PX-AUD-050 zero-dollar ceiling preserved with ?? null (not coerced to null by ||)', () => {
  const result = defaults(() => ({ executionPolicy: { max_cost_per_task_usd: 0 } }));
  assert.equal(result.taskCostCeilingUsd, 0, 'zero cost ceiling must be preserved as 0, not coerced to null');
});

test('PX-AUD-050 null ceiling stays null', () => {
  const result = defaults(() => ({ executionPolicy: {} }));
  assert.equal(result.taskCostCeilingUsd, null);
});

test('PX-AUD-050 positive ceiling preserved', () => {
  const result = defaults(() => ({ executionPolicy: { max_cost_per_task_usd: 5.0 } }));
  assert.equal(result.taskCostCeilingUsd, 5.0);
});
