'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { decideAuthority, codexHostHandoffDecision } = require('../src/operationAuthority');

test('observation cannot claim write authority', () => {
  const result = decideAuthority({
    executor: 'codex-host', effects: ['workspace-write'], observedOnly: true,
    userApprovalId: 'approval', pxPolicyDecisionId: 'policy', claimId: 'claim', claimStatus: 'active', idempotencyKey: 'once'
  });
  assert.equal(result.allowed, false);
  assert.match(result.reasons.join(' '), /observation cannot authorize/);
});

test('claim, policy, and approval are independent gates', () => {
  const missingApproval = decideAuthority({ executor: 'codex-host', effects: ['workspace-write'], pxPolicyDecisionId: 'policy', claimId: 'claim', claimStatus: 'active', idempotencyKey: 'once' });
  assert.match(missingApproval.reasons.join(' '), /user approval/);
  const missingPolicy = decideAuthority({ executor: 'codex-host', effects: ['workspace-write'], userApprovalId: 'approval', claimId: 'claim', claimStatus: 'active', idempotencyKey: 'once' });
  assert.match(missingPolicy.reasons.join(' '), /PX policy/);
  const missingClaim = decideAuthority({ executor: 'codex-host', effects: ['workspace-write'], userApprovalId: 'approval', pxPolicyDecisionId: 'policy', idempotencyKey: 'once' });
  assert.match(missingClaim.reasons.join(' '), /repository claim/);
});

test('nested PX executor is forbidden', () => {
  const result = decideAuthority({ executor: 'px-owned-executor', effects: ['read'], explicitDelegation: true, activeExecutors: ['codex-host'] });
  assert.equal(result.allowed, false);
  assert.match(result.reasons.join(' '), /nested executor/);
});

test('extension handoff assigns execution to the existing Codex host', () => {
  const result = codexHostHandoffDecision({ git: { allowed: true, reasons: [] } });
  assert.equal(result.allowed, true);
  assert.equal(result.executorOwner, 'codex-host');
  assert.equal(result.extensionExecutes, false);
});

test('extension source contains no nested codex process owner', () => {
  const root = path.resolve(__dirname, '..');
  const extension = fs.readFileSync(path.join(root, 'src', 'extension.js'), 'utf8');
  const bridge = fs.readFileSync(path.join(root, 'src', 'contextBridge.js'), 'utf8');
  assert.doesNotMatch(extension, /CodexRunManager|codexRuns\.run|codexRuns\.cancel/);
  assert.doesNotMatch(bridge, /class CodexRunManager|cp\.spawn\(['"]codex['"]/);
  assert.match(extension, /executorOwner: 'codex-host'/);
});
