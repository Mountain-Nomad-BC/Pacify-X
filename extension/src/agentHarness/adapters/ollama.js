'use strict';

const { ExecutionAdapter, sanitizeRemoteError } = require('./base');
const { withStreamReader, errorPreview } = require('./streamCustody');
const { compileMessages } = require('../pxProviderInvoker');

class OllamaAdapter extends ExecutionAdapter {
  constructor(options = {}) { super(options); this.baseUrl = String(options.baseUrl || 'http://127.0.0.1:11434').replace(/\/$/, ''); this.model = options.model; }

  async health() {
    const response = await fetch(`${this.baseUrl}/api/tags`, { signal: AbortSignal.timeout(2500) });
    if (!response.ok) return { status: 'unavailable', detail: `HTTP ${response.status}` };
    const data = await response.json(); const names = (data.models || []).map(m => m.name);
    return { status: this.model && !names.includes(this.model) ? 'degraded' : 'healthy', detail: `${names.length} model(s)` };
  }

  async runTurn(input) {
    const messages = compileMessages(input);
    let response;
    try {
      response = await fetch(`${this.baseUrl}/api/chat`, { method: 'POST', headers: { 'content-type': 'application/json' }, signal: input.signal,
        body: JSON.stringify({ model: this.model, stream: true, messages, options: this.options.options || {} }) });
    } catch (error) { throw new Error(`ollama-request-failed:${sanitizeRemoteError(error)}`); }
    if (!response.ok || !response.body) throw new Error(`ollama-http-${response.status}:${sanitizeRemoteError(await errorPreview(response, input.signal))}`);
    return withStreamReader(response.body, input.signal, async reader => {
    const decoder = new TextDecoder('utf-8', { fatal: true });
    let receivedBytes = 0;
    let pending = ''; let text = ''; let usage = null; let terminal = false;
    const consume = line => {
      if (!line.trim()) return;
      if (terminal) throw new Error('ollama-stream-data-after-terminal');
      const item = JSON.parse(line); const delta = item.message?.content || '';
      if (delta) { text += delta; input.onEvent({ type: 'worker.stream.delta', status: 'progress', summary: delta.slice(0, 500), payload: { delta } }); }
      if (item.done === true) {
        terminal = true;
        usage = { inputTokens: item.prompt_eval_count ?? null, outputTokens: item.eval_count ?? null, totalTokens: (item.prompt_eval_count != null && item.eval_count != null) ? item.prompt_eval_count + item.eval_count : null };
      }
    };
    while (true) {
      const { done, value } = await reader.read();
      if (done) { pending += decoder.decode(); break; }
      receivedBytes += value.byteLength;
      if (receivedBytes > 8 * 1024 * 1024) throw new Error('provider-stream-response-byte-budget');
      pending += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = pending.indexOf('\n')) >= 0) {
        consume(pending.slice(0, nl)); pending = pending.slice(nl + 1);
      }
      if (pending.length > 4 * 1024 * 1024) throw new Error('ollama-stream-frame-too-large');
    }
    if (pending.trim()) consume(pending);
    if (!terminal) throw new Error('ollama-stream-incomplete');
    return { text, usage };
    });
  }
}

module.exports = { OllamaAdapter };
