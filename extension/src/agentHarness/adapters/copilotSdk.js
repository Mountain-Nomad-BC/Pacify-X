'use strict';

const { ExecutionAdapter, sanitizeRemoteError } = require('./base');

// Optional adapter starter. The SDK is intentionally dynamically loaded so the
// current PX extension does not gain an undeclared hard dependency.
class CopilotSdkAdapter extends ExecutionAdapter {
  constructor(options = {}) { super(options); this.client = null; this.session = null; }

  _sdk() {
    try { return require('@github/copilot-sdk'); }
    catch (error) { throw new Error(`copilot-sdk-unavailable:${sanitizeRemoteError(error)}`); }
  }

  async health() { try { this._sdk(); return { status: 'healthy', detail: 'SDK module available' }; } catch (error) { return { status: 'unavailable', detail: error.message }; } }

  async createSession(input = {}) {
    const sdk = this._sdk();
    const CopilotClient = sdk.CopilotClient || sdk.Client;
    if (!CopilotClient) throw new Error('copilot-sdk-client-export-unknown');
    this.client ||= new CopilotClient(this.options.clientOptions || {});
    if (typeof this.client.start === 'function') await this.client.start();
    const creator = this.client.createSession || this.client.session?.create;
    if (typeof creator !== 'function') throw new Error('copilot-sdk-createSession-unavailable');
    this.session = await creator.call(this.client, { model: this.options.model, ...(input.sessionOptions || {}) });
    return { sessionRef: String(this.session.id || this.session.sessionId || 'copilot-session') };
  }

  async runTurn(input) {
    if (!this.session) await this.createSession(); let text = ''; let usage = null; const disposables = [];
    const on = (name, fn) => { if (typeof this.session.on === 'function') { const d = this.session.on(name, fn); if (d?.dispose) disposables.push(d); } };
    on('assistant.message_delta', event => { const delta = event?.data?.delta || event?.delta || ''; if (delta) { text += delta; input.onEvent({ type: 'worker.stream.delta', status: 'progress', summary: delta.slice(0, 500), payload: { delta, providerEvent: 'assistant.message_delta' } }); } });
    on('session.usage_info', event => { usage = event?.data || event; input.onEvent({ type: 'budget.updated', status: 'progress', summary: 'Copilot usage updated.', payload: { providerEvent: 'session.usage_info', usage } }); });
    try {
      const prompt = [input.contextPack?.instruction || '', ...(input.contextPack?.refs || []).filter(r => r.content).map(r => `[#${r.refId}]\n${r.content}`), input.message].filter(Boolean).join('\n\n');
      if (typeof this.session.sendAndWait === 'function') { const result = await this.session.sendAndWait({ prompt }); if (!text) text = result?.data?.content || result?.content || ''; }
      else if (typeof this.session.send === 'function') { const result = await this.session.send({ prompt }); if (!text) text = result?.data?.content || result?.content || ''; }
      else throw new Error('copilot-sdk-session-send-unavailable');
      return { text, usage: normalizeUsage(usage) };
    } finally { for (const d of disposables) d.dispose(); }
  }

  async interrupt() { if (typeof this.session?.abort === 'function') { await this.session.abort(); return true; } return false; }
  async dispose() { try { await this.session?.destroy?.(); } catch {} try { await this.client?.stop?.(); } catch {} }
}

function normalizeUsage(value) {
  if (!value) return null;
  return { inputTokens: value.inputTokens ?? value.input_tokens ?? null, outputTokens: value.outputTokens ?? value.output_tokens ?? null, totalTokens: value.totalTokens ?? value.total_tokens ?? null };
}

module.exports = { CopilotSdkAdapter };
