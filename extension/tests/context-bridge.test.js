'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { gitConflictDecision, codexPrompt, GIT_MUTATION_PROHIBITIONS, nonBillableEnvironment, isWithin } = require('../src/contextBridge');
const { admittedBaseUrl } = require('../src/ollamaProvider');

test('Git conflict boundary blocks operations, conflicts, and overlapping Codex runs', () => {
  assert.equal(gitConflictDecision({ available: true, operation: 'none', conflicts: 0, dirty: true }).allowed, true);
  assert.deepEqual(gitConflictDecision({ available: true, operation: 'rebase', conflicts: 0 }, false).reasons, ['git-operation-active:rebase']);
  assert.deepEqual(gitConflictDecision({ available: true, operation: 'none', conflicts: 2 }, true).reasons, ['unmerged-paths:2', 'bridge-codex-run-active']);
});

test('Codex handoff explicitly denies every declared Git mutation', () => {
  const prompt = codexPrompt({ correlation_id: 'test', git_policy: { mutation_allowed: false } });
  for (const operation of GIT_MUTATION_PROHIBITIONS) assert.match(prompt, new RegExp(operation.split(' ')[0], 'i'));
  assert.match(prompt, /preserve every pre-existing working-tree change/i);
});

test('context and Ollama boundaries reject path escapes and remote endpoints', () => {
  assert.equal(isWithin('C:/work/project/a.js', ['C:/work/project']), true);
  assert.equal(isWithin('C:/work/project-evil/a.js', ['C:/work/project']), false);
  assert.equal(admittedBaseUrl('http://127.0.0.1:11434'), 'http://127.0.0.1:11434');
  assert.equal(admittedBaseUrl('https://127.0.0.1:11434'), null);
  assert.equal(admittedBaseUrl('http://example.com:11434'), null);
});

test('bridge-owned processes do not inherit billable provider API credentials', () => {
  const filtered = nonBillableEnvironment({ PATH: 'kept', OPENAI_API_KEY: 'removed', azure_openai_api_key: 'removed', CODEX_API_KEY: 'removed', OPENROUTER_API_KEY: 'removed' });
  assert.deepEqual(filtered, { PATH: 'kept' });
});
