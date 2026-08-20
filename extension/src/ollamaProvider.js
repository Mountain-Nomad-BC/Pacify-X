'use strict';

function admittedBaseUrl(value) {
  try {
    const url = new URL(String(value || ''));
    if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '::1', '[::1]'].includes(url.hostname)) return null;
    return url.toString().replace(/\/$/, '');
  } catch {
    return null;
  }
}

function messageText(message) {
  return (message.content || []).map(part => typeof part?.value === 'string' ? part.value : '').filter(Boolean).join('\n');
}

function ollamaMessages(vscode, messages) {
  return messages.map(message => ({
    role: message.role === vscode.LanguageModelChatMessageRole.Assistant ? 'assistant' : 'user',
    content: messageText(message)
  })).filter(message => message.content);
}

class OllamaStreamError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'OllamaStreamError';
    this.code = code;
  }
}

const STREAM_DEFAULTS = Object.freeze({
  idleTimeoutMs: 30000,
  totalTimeoutMs: 300000,
  maxLineBytes: 1024 * 1024,
  maxStreamBytes: 16 * 1024 * 1024
});

function streamFault(code, message) { return new OllamaStreamError(code, message); }

function parseStreamEvent(line) {
  let event;
  try { event = JSON.parse(line); } catch { throw streamFault('OLLAMA_STREAM_MALFORMED', 'Ollama returned a malformed streaming event.'); }
  if (!event || Array.isArray(event) || typeof event !== 'object') throw streamFault('OLLAMA_STREAM_MALFORMED', 'Ollama returned an invalid streaming event.');
  if (event.error) throw streamFault('OLLAMA_REMOTE_ERROR', 'Ollama reported a model execution error.');
  return event;
}

class OllamaChatProvider {
  constructor(vscode, getBaseUrl, streamLimits = {}) {
    this.vscode = vscode;
    this.getBaseUrl = getBaseUrl;
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeLanguageModelChatInformation = this.emitter.event;
    this.streamLimits = { ...STREAM_DEFAULTS, ...streamLimits };
  }

  refresh() { this.emitter.fire(); }
  dispose() { this.emitter.dispose(); }

  async provideLanguageModelChatInformation(_options, token) {
    const baseUrl = admittedBaseUrl(this.getBaseUrl());
    if (!baseUrl || token.isCancellationRequested) return [];
    try {
      const response = await fetch(`${baseUrl}/api/tags`, { signal: AbortSignal.timeout(3000) });
      if (!response.ok) return [];
      const payload = await response.json();
      return (payload.models || []).map(item => ({
        id: item.name,
        name: item.name,
        family: item.details?.family || item.model || item.name.split(':')[0],
        version: item.digest || item.modified_at || item.name,
        tooltip: `Local Ollama model at ${baseUrl}`,
        detail: 'Pacify-X local provider',
        maxInputTokens: 32768,
        maxOutputTokens: 8192,
        capabilities: { toolCalling: false, imageInput: false }
      }));
    } catch {
      return [];
    }
  }

  async provideLanguageModelChatResponse(model, messages, options, progress, token) {
    const baseUrl = admittedBaseUrl(this.getBaseUrl());
    if (!baseUrl) throw new Error('Pacify-X refused the Ollama URL because it is not a loopback HTTP endpoint.');
    const controller = new AbortController();
    let cancelled = Boolean(token.isCancellationRequested); let totalExpired = false;
    const cancellation = token.onCancellationRequested(() => { cancelled = true; controller.abort(); });
    const started = Date.now();
    const totalTimer = setTimeout(() => { totalExpired = true; controller.abort(); }, this.streamLimits.totalTimeoutMs);
    try {
      if (cancelled) throw streamFault('OLLAMA_CANCELLED', 'Ollama generation was cancelled.');
      const response = await fetch(`${baseUrl}/api/chat`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          model: model.id,
          messages: ollamaMessages(this.vscode, messages),
          stream: true,
          options: {
            num_predict: Math.min(Number(options?.modelOptions?.maxOutputTokens || model.maxOutputTokens || 8192), 8192),
            temperature: Math.max(0, Math.min(2, Number(options?.modelOptions?.temperature ?? 0)))
          }
        }),
        signal: controller.signal
      });
      if (!response.ok) throw streamFault('OLLAMA_HTTP_ERROR', `Ollama returned HTTP ${response.status}.`);
      if (!response.body) throw streamFault('OLLAMA_STREAM_MISSING', 'Ollama returned no response stream.');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffered = ''; let totalBytes = 0; let completed = false;
      const consume = line => {
        if (!line.trim()) return;
        if (Buffer.byteLength(line, 'utf8') > this.streamLimits.maxLineBytes) throw streamFault('OLLAMA_STREAM_LIMIT', 'Ollama exceeded the streaming event size limit.');
        const event = parseStreamEvent(line);
        if (event.message?.content) progress.report(new this.vscode.LanguageModelTextPart(event.message.content));
        if (event.done === true) completed = true;
      };
      while (true) {
        if (Date.now() - started >= this.streamLimits.totalTimeoutMs) throw streamFault('OLLAMA_TOTAL_TIMEOUT', 'Ollama exceeded the total generation deadline.');
        let idleTimer;
        const idleFailure = new Promise((_, reject) => { idleTimer = setTimeout(() => { reject(streamFault('OLLAMA_IDLE_TIMEOUT', 'Ollama stopped producing stream data.')); controller.abort(); }, this.streamLimits.idleTimeoutMs); });
        let chunk;
        try { chunk = await Promise.race([reader.read(), idleFailure]); } finally { clearTimeout(idleTimer); }
        const { done, value } = chunk;
        if (done) break;
        totalBytes += value?.byteLength || 0;
        if (totalBytes > this.streamLimits.maxStreamBytes) { controller.abort(); throw streamFault('OLLAMA_STREAM_LIMIT', 'Ollama exceeded the total stream size limit.'); }
        buffered += decoder.decode(value, { stream: true });
        if (Buffer.byteLength(buffered, 'utf8') > this.streamLimits.maxLineBytes) { controller.abort(); throw streamFault('OLLAMA_STREAM_LIMIT', 'Ollama exceeded the streaming event size limit.'); }
        const lines = buffered.split(/\r?\n/); buffered = lines.pop() || '';
        for (const line of lines) consume(line);
        if (completed) { try { await reader.cancel(); } catch {} break; }
      }
      buffered += decoder.decode();
      if (buffered.trim()) consume(buffered);
      if (!completed) throw streamFault('OLLAMA_STREAM_TRUNCATED', 'Ollama closed the stream before a completion event.');
    } catch (error) {
      if (error instanceof OllamaStreamError) throw error;
      if (cancelled) throw streamFault('OLLAMA_CANCELLED', 'Ollama generation was cancelled.');
      if (totalExpired || Date.now() - started >= this.streamLimits.totalTimeoutMs) throw streamFault('OLLAMA_TOTAL_TIMEOUT', 'Ollama exceeded the total generation deadline.');
      throw streamFault('OLLAMA_STREAM_DISCONNECTED', 'The local Ollama stream disconnected unexpectedly.');
    } finally {
      clearTimeout(totalTimer);
      cancellation.dispose();
    }
  }

  async provideTokenCount(_model, value) {
    const text = typeof value === 'string' ? value : messageText(value);
    return Math.max(1, Math.ceil(text.length / 4));
  }
}

module.exports = { admittedBaseUrl, messageText, ollamaMessages, parseStreamEvent, OllamaStreamError, OllamaChatProvider };
