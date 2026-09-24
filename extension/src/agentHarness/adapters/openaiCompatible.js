'use strict';

const { ExecutionAdapter, sanitizeRemoteError } = require('./base');

class OpenAICompatibleAdapter extends ExecutionAdapter {
  constructor(options = {}) { super(options); this.baseUrl = String(options.baseUrl || '').replace(/\/$/, ''); this.model = options.model; this.getApiKey = options.getApiKey; }

  async health() {
    try { const key = await this.getApiKey?.(); const headers = key ? { authorization: `Bearer ${key}` } : {}; const response = await fetch(`${this.baseUrl}/models`, { headers, signal: AbortSignal.timeout(3000) }); return { status: response.ok ? 'healthy' : 'degraded', detail: `HTTP ${response.status}` }; }
    catch (error) { return { status: 'unavailable', detail: sanitizeRemoteError(error) }; }
  }

  async runTurn(input) {
    const key = await this.getApiKey?.(); if (!key) throw new Error('provider-credential-unavailable');
    const messages = [{ role: 'system', content: input.contextPack?.instruction || 'You are a PX-governed worker.' }];
    const refs = (input.contextPack?.refs || []).filter(r => r.content).map(r => `[#${r.refId}] ${r.label}\n${r.content}`).join('\n\n');
    if (refs) messages.push({ role: 'system', content: `PX context:\n${refs}` }); messages.push({ role: 'user', content: input.message });
    const response = await fetch(`${this.baseUrl}/chat/completions`, { method: 'POST', signal: input.signal, headers: { 'content-type': 'application/json', authorization: `Bearer ${key}` },
      body: JSON.stringify({ model: this.model, messages, stream: true, stream_options: { include_usage: true }, ...(this.options.request || {}) }) });
    if (!response.ok || !response.body) throw new Error(`provider-http-${response.status}:${sanitizeRemoteError(await response.text())}`);
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let pending = ''; let text = ''; let usage = null;
    while (true) {
      const { done, value } = await reader.read(); if (done) break; pending += decoder.decode(value, { stream: true });
      let split;
      while ((split = pending.indexOf('\n\n')) >= 0) {
        const frame = pending.slice(0, split); pending = pending.slice(split + 2);
        for (const raw of frame.split('\n')) {
          if (!raw.startsWith('data:')) continue; const data = raw.slice(5).trim(); if (!data || data === '[DONE]') continue;
          const item = JSON.parse(data); const delta = item.choices?.[0]?.delta?.content || '';
          if (delta) { text += delta; input.onEvent({ type: 'worker.stream.delta', status: 'progress', summary: delta.slice(0, 500), payload: { delta } }); }
          if (item.usage) usage = { inputTokens: item.usage.prompt_tokens ?? null, outputTokens: item.usage.completion_tokens ?? null, totalTokens: item.usage.total_tokens ?? null };
        }
      }
    }
    return { text, usage };
  }
}

module.exports = { OpenAICompatibleAdapter };
