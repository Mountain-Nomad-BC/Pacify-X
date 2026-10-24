'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { buildPxProviderGatewayInvoker } = require('../src/agentHarness/pxProviderInvoker');

test('provider invoker uses the routed worker output-token allowance', async () => {
  let request;
  const invoke = buildPxProviderGatewayInvoker({
    profileIdForWorker: () => 'profile-local',
    bridge: {
      streamChat: async (payload, _signal, onEvent) => {
        request = payload;
        onEvent({ kind: 'px_receipt', payload: { provider_receipt: {} } });
        return { completed: true };
      }
    }
  });

  await invoke({
    worker: { workerId: 'worker-local' },
    task: { taskId: 'task-local' },
    run: {},
    message: 'hello',
    contextPack: {},
    maxOutputTokens: 2048
  });
  assert.equal(request.max_output_tokens, 2048);
});

test('provider invoker retains its bounded default when no worker allowance is supplied', async () => {
  let request;
  const invoke = buildPxProviderGatewayInvoker({
    profileIdForWorker: () => 'profile-local',
    bridge: {
      streamChat: async (payload, _signal, onEvent) => {
        request = payload;
        onEvent({ kind: 'px_receipt', payload: { provider_receipt: {} } });
        return { completed: true };
      }
    }
  });

  await invoke({
    worker: { workerId: 'worker-local' },
    task: { taskId: 'task-local' },
    run: {},
    message: 'hello',
    contextPack: {}
  });
  assert.equal(request.max_output_tokens, 1024);
});

test('provider invoker rejects an invalid output-token allowance before bridge invocation', async () => {
  const invoke = buildPxProviderGatewayInvoker({
    profileIdForWorker: () => 'profile-local',
    bridge: { streamChat: async () => { throw new Error('must not run'); } }
  });
  await assert.rejects(invoke({
    worker: { workerId: 'worker-local' },
    task: { taskId: 'task-local' },
    run: {},
    message: 'hello',
    contextPack: {},
    maxOutputTokens: 1.5
  }), /px-provider-output-token-budget-invalid/);
});
