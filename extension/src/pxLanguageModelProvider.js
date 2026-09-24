'use strict';

const crypto = require('crypto');

function textFromPart(part) {
  if (typeof part?.value === 'string') return part.value;
  if (Array.isArray(part?.content)) return part.content.map(textFromPart).filter(Boolean).join('\n');
  return '';
}

function stableJson(value) { try { return JSON.stringify(value ?? {}); } catch { return '{}'; } }

function normalizeMessages(vscode, messages) {
  const result = [];
  for (const message of messages || []) {
    const assistant = message.role === vscode.LanguageModelChatMessageRole?.Assistant;
    const fragments = [];
    for (const part of message.content || []) {
      if (typeof part?.name === 'string' && typeof part?.callId === 'string' && part?.input !== undefined) {
        fragments.push(`[PX_TOOL_CALL id=${part.callId} name=${part.name}] ${stableJson(part.input)}`);
        continue;
      }
      if (typeof part?.callId === 'string' && Array.isArray(part?.content)) {
        fragments.push(`[PX_TOOL_RESULT id=${part.callId}] ${part.content.map(textFromPart).filter(Boolean).join('\n')}`);
        continue;
      }
      const text = textFromPart(part);
      if (text) fragments.push(text);
    }
    const content = fragments.join('\n').trim();
    if (content) result.push({ role: assistant ? 'assistant' : 'user', content });
  }
  if (!result.length) result.push({ role: 'user', content: '' });
  return result;
}

function normalizeTools(options) {
  const source = options?.tools || [];
  return source.map(tool => ({
    name: String(tool.name || ''), description: String(tool.description || ''), input_schema: tool.inputSchema || { type: 'object' }
  })).filter(tool => tool.name);
}

class PxLanguageModelProvider {
  constructor(vscode, bridge) {
    this.vscode = vscode; this.bridge = bridge; this.emitter = new vscode.EventEmitter();
    this.onDidChangeLanguageModelChatInformation = this.emitter.event;
  }
  refresh() { this.emitter.fire(); }
  dispose() { this.emitter.dispose(); }
  async provideLanguageModelChatInformation(_options, token) {
    let payload;
    try { payload = await this.bridge.listModels(token); } catch { return []; }
    return (payload?.models || []).map(model => ({
      id: model.profile_id,
      name: `${model.model_id} · ${model.lane}`,
      family: 'Pacify-X governed local',
      version: model.profile_sha256,
      tooltip: `PX ${model.lane} lane · certified loaded profile`,
      detail: 'Pacify-X canonical provider gateway',
      maxInputTokens: model.context_tokens,
      maxOutputTokens: model.max_output_tokens,
      capabilities: { toolCalling: Boolean(model.tool_calling), imageInput: Boolean(model.image_input) }
    }));
  }
  async provideLanguageModelChatResponse(model, messages, options, progress, token) {
    const requestId = `vscode-model-${crypto.randomUUID()}`;
    const toolCalls = new Map();
    const payload = {
      profile_id: model.id,
      request_id: requestId,
      client_session_id: `vscode-${crypto.randomUUID()}`,
      correlation_id: `corr-${requestId}`,
      messages: normalizeMessages(this.vscode, messages),
      tools: normalizeTools(options),
      max_output_tokens: Math.min(Number(options?.modelOptions?.maxOutputTokens || model.maxOutputTokens || 512), Number(model.maxOutputTokens || 512)),
      deadline_ms: 300000
    };
    await this.bridge.streamChat(payload, token, event => {
      if (event?.kind === 'text_delta' && typeof event.payload?.text === 'string') {
        progress.report(new this.vscode.LanguageModelTextPart(event.payload.text));
      } else if (event?.kind === 'tool_call_start') {
        toolCalls.set(event.payload.call_id, { name: event.payload.name, args: '' });
      } else if (event?.kind === 'tool_call_delta') {
        const call = toolCalls.get(event.payload.call_id); if (call) call.args += String(event.payload.arguments_delta || '');
      } else if (event?.kind === 'tool_call_end') {
        const callId = event.payload.call_id; const call = toolCalls.get(callId) || { name: event.payload.name, args: '' };
        const input = event.payload.arguments || (() => { try { return JSON.parse(call.args || '{}'); } catch { return {}; } })();
        progress.report(new this.vscode.LanguageModelToolCallPart(callId, event.payload.name || call.name, input));
        toolCalls.delete(callId);
      } else if (event?.kind === 'error') {
        const error = new Error(`Pacify-X model stream failed: ${String(event.payload?.code || 'provider_stream_failure')}`); error.code = String(event.payload?.code || 'PX_MODEL_STREAM_FAILED'); throw error;
      }
      // reasoning_delta is intentionally not surfaced by this client adapter.
    });
  }
  async provideTokenCount(model, value, token) {
    const text = typeof value === 'string' ? value : (value?.content || []).map(textFromPart).filter(Boolean).join('\n');
    const requestId = `vscode-token-${crypto.randomUUID()}`;
    const result = await this.bridge.countTokens({
      profile_id: model.id, request_id: requestId, client_session_id: `vscode-${crypto.randomUUID()}`,
      messages: [{ role: 'user', content: text }], max_output_tokens: 1, deadline_ms: 30000
    }, token);
    if (result?.exact !== true || !Number.isInteger(result?.input_tokens) || result.input_tokens < 0) throw new Error('Pacify-X exact token counting is unavailable for this model.');
    return result.input_tokens;
  }
}

module.exports = { textFromPart, normalizeMessages, normalizeTools, PxLanguageModelProvider };
