'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { setupStudio, STARTER_AGENT, STARTER_WORKFLOW } = require('../src/studioBootstrap');

test('Studio setup creates, admits, and runs editable starter agent and workflow revisions', async () => {
  const calls = [];
  const bridge = {
    async issueStudioApproval(kind, operation, payload) {
      calls.push(['approve', kind, operation, payload]);
      return { approval_capability: { exact: `${kind}:${operation}` } };
    },
    async studioOperation(kind, operation, payload) {
      calls.push(['operate', kind, operation, payload]);
      if (kind === 'agent' && operation === 'test') return { passed: true };
      if (operation === 'admit' || (kind === 'workflow' && operation === 'validate')) return { decision: 'admitted' };
      if (kind === 'agent' && operation === 'run') return { run_id: 'run:agent-starter', run_outcome: 'succeeded' };
      if (kind === 'workflow' && operation === 'dry-run') return { effects_executed: false, runnable: true };
      if (kind === 'workflow' && operation === 'run') return { run_id: 'run:workflow-starter', run_state: 'succeeded' };
      return { created: true };
    }
  };
  const progress = [];
  const result = await setupStudio(bridge, { progress: value => progress.push(value) });
  assert.equal(result.ready, true);
  assert.equal(result.agent.decision, 'admitted');
  assert.equal(result.workflow.decision, 'admitted');
  assert.equal(result.completed_steps.length, 10);
  assert.deepEqual(progress, result.completed_steps);
  assert.equal(calls.filter(call => call[0] === 'approve').length, 9, 'dry-run is the sole unsigned read-only operation');
  assert.equal(calls.filter(call => call[0] === 'operate').length, 10);
  assert.equal(STARTER_AGENT.agent_id, 'agent:pacify-x-starter');
  assert.equal(STARTER_WORKFLOW.workflow_id, 'workflow:pacify-x-starter');
});

test('Studio setup stops immediately when agent admission is not admitted', async () => {
  const operations = [];
  const bridge = {
    async issueStudioApproval() { return { approval_capability: { exact: true } }; },
    async studioOperation(kind, operation) {
      operations.push(`${kind}:${operation}`);
      if (operation === 'test') return { passed: true };
      if (operation === 'admit') return { decision: 'blocked' };
      return { created: true };
    }
  };
  await assert.rejects(setupStudio(bridge), /agent-admission-failed/);
  assert.equal(operations.includes('agent:run'), false);
  assert.equal(operations.some(value => value.startsWith('workflow:')), false);
});
