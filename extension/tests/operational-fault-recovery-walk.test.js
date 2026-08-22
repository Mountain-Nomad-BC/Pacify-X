'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { failureContained, recoveryObserved, stageMap } = require('../scripts/run-operational-fault-recovery-walk');
const { STAGES } = require('../scripts/run-exhaustive-operational-control-walk');

test('fault evidence rejects page errors and unchanged stale success', () => {
  const base = { baselineVisible: true, baselineText: '7 runnable agents', faultVisible: true, faultText: '7 runnable agents', mainVisible: true, alertText: '', newPageErrors: 0 };
  assert.equal(failureContained(base), false);
  assert.equal(failureContained({ ...base, newPageErrors: 1, faultVisible: false }), false);
});

test('fault evidence accepts exact disappearance, changed fallback, or a visible alert', () => {
  const base = { baselineVisible: true, baselineText: 'healthy', faultVisible: true, faultText: 'unavailable', mainVisible: true, alertText: '', newPageErrors: 0 };
  assert.equal(failureContained(base), true);
  assert.equal(failureContained({ ...base, faultVisible: false }), true);
  assert.equal(failureContained({ ...base, faultText: 'healthy', alertText: 'snapshot unavailable' }), true);
});

test('recovery and stage mapping remain exact and fail closed', () => {
  assert.equal(recoveryObserved({ baselineVisible: true, recoveredVisible: true, newPageErrors: 0 }), true);
  assert.equal(recoveryObserved({ baselineVisible: true, recoveredVisible: false, newPageErrors: 0 }), false);
  const control = { stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['failure_handling', 'recovery_rollback'].includes(stage) ? 'required' : 'not_applicable_with_evidence'])) };
  const stages = stageMap(control, true, false, 'receipt:demo');
  assert.equal(stages.failure_handling.state, 'present');
  assert.equal(stages.recovery_rollback.state, 'missing');
  assert.equal(stages.runtime_effect.state, 'not_applicable');
});
