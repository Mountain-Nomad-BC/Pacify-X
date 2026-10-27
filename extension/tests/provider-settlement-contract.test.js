'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { PxProviderGatewayAdapter } = require('../src/agentHarness/adapters/pxProviderGateway');

for (const receipt of [true, {}, { schema_version: 'failure', provider_receipt: {} }, { exact_receipt: false }]) {
  test(`gateway refuses non-native settlement ${JSON.stringify(receipt)}`, async () => {
    const adapter = new PxProviderGatewayAdapter({
      worker: { workerId: 'worker', providerId: 'provider', modelId: 'model', costClass: 'billable-api' },
      invokeProvider: async () => ({ value: 'untrusted', receipt })
    });
    let emitted = false;
    await assert.rejects(adapter.runTurn({ task: { taskId: 'task' }, run: { runId: 'run' },
      onEvent: () => { emitted = true; } }), /receipt|settlement/);
    assert.equal(emitted, false);
  });
}
