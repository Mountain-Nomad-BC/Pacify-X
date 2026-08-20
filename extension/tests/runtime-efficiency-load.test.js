'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { measure } = require('../scripts/measure-runtime-efficiency');

test('current, 2x, 5x, and pathological filesystem profiles stay worker-owned and bounded', { timeout: 30000 }, async () => {
  const report = await measure();
  assert.deepEqual(report.profiles.map(item => item.profile), ['current', '2x', '5x', 'pathological']);
  assert.equal(report.acceptance.all_profiles_within_budget, true);
  assert.equal(report.acceptance.duplicate_load_bounded, true);
});
