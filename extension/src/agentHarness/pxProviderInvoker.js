'use strict';

// Canonical agent-harness provider invoker.
//
// The PX Agent Console harness must never call a provider directly. This module adapts
// the already-governed `runtime.vscode_model_bridge` client (via McpModelFabricBridge)
// into the `invokeProvider` contract expected by PxProviderGatewayAdapter:
//
//   invokeProvider({ worker, task, run, message, contextPack, signal })
//     -> { value: string, receipt: object }
//
// The receipt is produced by PX's own ProviderInvocationGateway on the Python side; this
// file adds no networking, credentials, pricing, or routing authority of its own.

function buildPxProviderGatewayInvoker({ bridge, profileIdForWorker }) {
  if (!bridge || typeof bridge.streamChat !== 'function') throw new Error('px-model-bridge-required');
  if (typeof profileIdForWorker !== 'function') throw new Error('px-worker-profile-resolver-required');

  return async function invokeProvider({ worker, task, run, message, contextPack, signal } = {}) {
    const profileId = profileIdForWorker(worker);
    if (!profileId) throw new Error('px-provider-gateway-worker-has-no-profile');

    const requestId = `agent-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    let receipt = null;
    let text = '';

    const payload = {
      profile_id: profileId,
      request_id: requestId,
      client_session_id: run?.clientSessionId || `agent-session-${requestId}`,
      correlation_id: task?.taskId ? `corr-${task.taskId}` : `corr-${requestId}`,
      messages: compileMessages({ message, contextPack, task }),
      max_output_tokens: Number(run?.maxOutputTokens || contextPack?.maxOutputTokens || 1024),
      deadline_ms: Number(run?.deadlineMs || task?.deadlineMs || 300000)
    };

    await bridge.streamChat(payload, signal, event => {
      if (!event || typeof event !== 'object') return;
      if (event.kind === 'text_delta' && typeof event.payload?.text === 'string') text += event.payload.text;
      else if (event.kind === 'px_receipt') receipt = event.payload;
    });

    if (!receipt) throw new Error('px-provider-gateway-exact-receipt-missing');
    return { value: text, receipt };
  };
}

function compileMessages({ message, contextPack, task }) {
  const messages = [];
  const context = contextPack && typeof contextPack === 'object'
    ? (typeof contextPack.text === 'string' ? contextPack.text.trim() : '')
    : '';
  if (context) messages.push({ role: 'system', content: `PX context:\n${context}` });
  const userText = typeof message === 'string'
    ? message
    : (message?.text || message?.content || (task?.goal ?? ''));
  messages.push({ role: 'user', content: String(userText || '').slice(0, 200000) });
  return messages;
}

module.exports = { buildPxProviderGatewayInvoker, compileMessages };