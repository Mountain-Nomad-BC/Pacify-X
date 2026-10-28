'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { buildPxProviderGatewayInvoker } = require('../src/agentHarness/pxProviderInvoker');
const {createExecutionContext} = require('../src/agentHarness/executionContext');
function executionContext() {
  return createExecutionContext({run:{runId:'run-local',revision:1,epoch:1},projectId:'prj-local',sessionId:'run-local',providerId:'llama.cpp',authoritySha256:'a'.repeat(64),effectBudgetSha256:'b'.repeat(64)});
}

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
    executionContext: executionContext(),
    message: 'hello',
    contextPack: {},
    maxOutputTokens: 2048
  });
  assert.equal(request.max_output_tokens, 2048);
  assert.equal(request.request_id, request.execution_context.execution_id);
  assert.equal(request.project_id, "prj-local");
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
    executionContext: executionContext(),
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
    executionContext: executionContext(),
    message: 'hello',
    contextPack: {},
    maxOutputTokens: 1.5
  }), /px-provider-output-token-budget-invalid/);
});


test('provider invoker refuses a missing invocation owner instead of minting one', async () => {
  let invoked=false;
  const invoke=buildPxProviderGatewayInvoker({profileIdForWorker:()=> 'profile-local',bridge:{streamChat:async()=>{invoked=true;}}});
  await assert.rejects(invoke({worker:{workerId:'local'},task:{taskId:'t'},run:{},contextPack:{},message:'hello'}), /px-provider-invocation-owner-required/);
  assert.equal(invoked,false);
});
