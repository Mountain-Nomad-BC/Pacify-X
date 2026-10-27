'use strict';

const { ExecutionAdapter, sanitizeRemoteError } = require('./base');
const { withStreamReader, errorPreview } = require('./streamCustody');
const { compileMessages } = require('../pxProviderInvoker');

class OpenAICompatibleAdapter extends ExecutionAdapter {
  constructor(options = {}) { super(options); this.baseUrl = String(options.baseUrl || '').replace(/\/$/, ''); this.model = options.model; this.getApiKey = options.getApiKey; }

  async health() {
    try { const key = await this.getApiKey?.(); const headers = key ? { authorization: `Bearer ${key}` } : {}; const response = await fetch(`${this.baseUrl}/models`, { headers, signal: AbortSignal.timeout(3000) }); return { status: response.ok ? 'healthy' : 'degraded', detail: `HTTP ${response.status}` }; }
    catch (error) { return { status: 'unavailable', detail: sanitizeRemoteError(error) }; }
  }

  async runTurn(input) {
    const key = await this.getApiKey?.(); if (!key) throw new Error('provider-credential-unavailable');
    const messages = compileMessages(input);
    const response = await fetch(`${this.baseUrl}/chat/completions`, { method: 'POST', signal: input.signal, headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
      body: JSON.stringify({ model: this.model, messages, stream: true, stream_options: { include_usage: true }, ...(this.options.request || {}) }) });
    if (!response.ok || !response.body) throw new Error(`provider-http-${response.status}:${sanitizeRemoteError(await errorPreview(response, input.signal))}`);
    return withStreamReader(response.body, input.signal, async reader => {
    const decoder = new TextDecoder('utf-8', { fatal: true });
    let receivedBytes = 0;
    let pending = ''; let text = ''; let usage = null; let terminal = false;
    const maxPendingChars = 4 * 1024 * 1024;
    const handleFrame = frame => {
      const data = frame.split('\n').filter(line => line.startsWith('data:'))
        .map(line => line.slice(5).trimStart()).join('\n').trim();
      if (!data) return;
      if (data === '[DONE]') { terminal = true; return; }
      const item = JSON.parse(data); const delta = item.choices?.[0]?.delta?.content || '';
      if (delta) { text += delta; input.onEvent({ type: 'worker.stream.delta', status: 'progress', summary: delta.slice(0, 500), payload: { delta } }); }
      if (item.usage) usage = { inputTokens: item.usage.prompt_tokens ?? null, outputTokens: item.usage.completion_tokens ?? null, totalTokens: item.usage.total_tokens ?? null };
    };
    while (true) {
      const { done, value } = await reader.read();
      if (done) { pending += decoder.decode(); break; }
      receivedBytes += value.byteLength;
      if (receivedBytes > 8 * 1024 * 1024) throw new Error('provider-stream-response-byte-budget');
      pending += decoder.decode(value, { stream: true });
      if (pending.endsWith('\r')) {
        const tail = pending.slice(-1);
        pending = pending.slice(0, -1).replace(/\r\n|\r/g, '\n') + tail;
      } else pending = pending.replace(/\r\n|\r/g, '\n');
      let split;
      while ((split = pending.indexOf('\n\n')) >= 0) {
        const frame = pending.slice(0, split); pending = pending.slice(split + 2);
        if (terminal) throw new Error('openai-stream-data-after-terminal');
        handleFrame(frame);
      }
      if (pending.length > maxPendingChars) throw new Error('openai-stream-frame-too-large');
    }
    pending = pending.replace(/\r\n|\r/g, '\n');
    while (pending.includes('\n\n')) {
      const split = pending.indexOf('\n\n');
      const frame = pending.slice(0, split); pending = pending.slice(split + 2);
      if (terminal) throw new Error('openai-stream-data-after-terminal');
      handleFrame(frame);
    }
    if (!terminal || pending.trim()) throw new Error('openai-stream-incomplete');
    return { text, usage };
    });
  }
}

module.exports = { OpenAICompatibleAdapter };
