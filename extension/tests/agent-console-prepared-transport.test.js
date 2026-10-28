'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { registerAgentConsole } = require('../src/agentHarness/registerAgentConsole');
const { MESSAGE_VERSION } = require('../src/agentHarness/agentConsoleMessages');
const reference = { schema_version: 'px.prepared-group-reference/1.0', plan_id: 'task-plan-' + 'a'.repeat(24), plan_sha256: 'b'.repeat(64) };
function host(t, options) {
  let view; const messages = []; const noop = () => ({ dispose() {} });
  const owner = registerAgentConsole({
    window: { registerWebviewViewProvider: (_id, provider) => { view = provider; return noop(); } },
    commands: { registerCommand: noop }
  }, { workspaceState: { get: (_key, fallback) => fallback, update: async () => {} } }, options);
  t.after(() => owner.dispose());
  view.view = { webview: { postMessage: async message => { messages.push(message); } } };
  return { owner, view, messages };
}
test('registered console forwards only the canonical reference to its actual host callback', async t => {
  let received; const result = { status: 'waiting', receipt: 'controlled-host-response' };
  const { owner, view } = host(t, { executePreparedGroup: async value => { received = value; return result; } });
  await view._handle({ schemaVersion: MESSAGE_VERSION, type: 'executePreparedGroup', reference });
  assert.deepEqual(received, reference);
  const returned = owner.harness.eventBus.events.find(event => event.type === 'group.plan.dispatch.returned');
  assert.deepEqual(returned.payload, result);
  assert.equal(returned.status, 'info');
});
test('registered console preserves a native execution rejection and emits no completion', async t => {
  const { owner, view, messages } = host(t, { executePreparedGroup: async () => { throw new Error('native capability rejected'); } });
  await view._handle({ schemaVersion: MESSAGE_VERSION, type: 'executePreparedGroup', reference });
  assert.ok(messages.some(message => message.type === 'error' && message.code === 'prepared-group-execution-rejected'));
  assert.equal(owner.harness.eventBus.events.length, 0);
});
test('registered console refuses an inspection response that invents authority', async t => {
  const { owner, view, messages } = host(t, { inspectPreparedGroup: async () => ({
    ...reference, schema_version: 'px.prepared-group-inspection/1.0', execution_authorized: false, authority_granted: true
  }) });
  await view._handle({ schemaVersion: MESSAGE_VERSION, type: 'inspectPreparedGroup', reference });
  assert.ok(messages.some(message => message.type === 'error' && /contract-mismatch/.test(message.detail)));
  assert.equal(owner.harness.eventBus.events.length, 0);
});
