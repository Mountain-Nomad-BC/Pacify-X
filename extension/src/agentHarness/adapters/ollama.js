'use strict';

const { ExecutionAdapter, sanitizeRemoteError } = require('./base');

class OllamaAdapter extends ExecutionAdapter {
  constructor(options = {}) { super(options); this.baseUrl = String(options.baseUrl || 'http://127.0.0.1:11434').replace(/\/$/, ''); this.model = options.model; }

  async health() {
    const response = await fetch(`${this.baseUrl}/api/tags`, { signal: AbortSignal.timeout(2500) });
    if (!response.ok) return { status: 'unavailable', detail: `HTTP ${response.status}` };
    const data = await response.json(); const names = (data.models || []).map(m => m.name);
    return { status: this.model && !names.includes(this.model) ? 'degraded' : 'healthy', detail: `${names.length} model(s)` };
  }

  async runTurn(input) {
    const messages = [];
    if (input.contextPack?.instruction) messages.push({ role: 'system', content: input.contextPack.instruction });
    const contextText = (input.contextPack?.refs || []).filter(r => r.content).map(r => `[#${r.refId} ${r.label}]\n${r.content}`).join('\n\n');
    if (contextText) messages.push({ role: 'system', content: `PX context references:\n${contextText}` });
    messages.push({ role: 'user', content: input.message });
    let response;
    try {
      response = await fetch(`${this.baseUrl}/api/chat`, { method: 'POST', headers: { 'content-type': 'application/json' }, signal: input.signal,
        body: JSON.stringify({ model: this.model, stream: true, messages, options: this.options.options || {} }) });
    } catch (error) { throw new Error(`ollama-request-failed:${sanitizeRemoteError(error)}`); }
    if (!response.ok || !response.body) throw new Error(`ollama-http-${response.status}:${(await response.text()).slice(0, 500)}`);
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let pending = ''; let text = ''; let usage = null;
    while (true) {
      const { done, value } = await reader.read(); if (done) break; pending += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, nl).trim(); pending = pending.slice(nl + 1); if (!line) continue;
        const item = JSON.parse(line); const delta = item.message?.content || '';
        if (delta) { text += delta; input.onEvent({ type: 'worker.stream.delta', status: 'progress', summary: delta.slice(0, 500), payload: { delta } }); }
        if (item.done) usage = { inputTokens: item.prompt_eval_count ?? null, outputTokens: item.eval_count ?? null, totalTokens: (item.prompt_eval_count != null && item.eval_count != null) ? item.prompt_eval_count + item.eval_count : null };
      }
    }
    return { text, usage };
  }
}

module.exports = { OllamaAdapter };
