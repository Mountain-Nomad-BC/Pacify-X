'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { failureContained, recoveryObserved, stageMap } = require('../scripts/run-operational-fault-recovery-walk');
const { STAGES, currentSourceManifest } = require('../scripts/run-exhaustive-operational-control-walk');

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

test('control source manifest changes when an exercised source changes', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-control-source-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.writeFileSync(path.join(root, 'surface.js'), 'first');
  const matrix = { controls: [{ source_refs: ['surface.js:1-2'] }] };
  const before = currentSourceManifest(matrix, root);
  fs.writeFileSync(path.join(root, 'surface.js'), 'second');
  const after = currentSourceManifest(matrix, root);
  assert.notEqual(before.source_sha256, after.source_sha256);
  assert.equal(after.files[0].path, 'surface.js');
});
