'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const {
  buildProviderExecutionPolicy,
  providerExecutionPolicyReport
} = require('../src/providerExecutionPolicy');

test('shared provider execution vectors preserve stable outcomes and violation IDs', () => {
  const corpus = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'tests', 'coordination_conformance', 'provider_execution_policy_vectors.json'), 'utf8'));
  for (const vector of corpus.vectors) {
    let policy = buildProviderExecutionPolicy(corpus.base_policy);
    Object.assign(policy, vector.policy_mutations);
    if (vector.reseal) policy = buildProviderExecutionPolicy(policy);
    const request = { ...corpus.base_request, ...vector.request_mutations };
    const report = providerExecutionPolicyReport(policy, request);
    assert.equal(report.valid, vector.expected_valid, vector.id);
    assert.deepEqual(report.violation_ids, vector.expected_violation_ids, vector.id);
  }
});
