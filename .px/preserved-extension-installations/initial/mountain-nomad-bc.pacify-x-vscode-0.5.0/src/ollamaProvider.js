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

class OllamaChatProvider {
  constructor(vscode, getBaseUrl) {
    this.vscode = vscode;
    this.getBaseUrl = getBaseUrl;
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeLanguageModelChatInformation = this.emitter.event;
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
    const cancellation = token.onCancellationRequested(() => controller.abort());
    try {
      const response = await fetch(`${baseUrl}/api/chat`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          model: model.id,
          messages: ollamaMessages(this.vscode, messages),
          stream: true,
          options: { num_predict: Math.min(Number(options?.maxOutputTokens || model.maxOutputTokens || 8192), 8192) }
        }),
        signal: controller.signal
      });
      if (!response.ok || !response.body) throw new Error(`Ollama returned HTTP ${response.status}.`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffered = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffered += decoder.decode(value, { stream: true });
        const lines = buffered.split(/\r?\n/); buffered = lines.pop() || '';
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.error) throw new Error(String(event.error));
          if (event.message?.content) progress.report(new this.vscode.LanguageModelTextPart(event.message.content));
        }
      }
      if (buffered.trim()) {
        const event = JSON.parse(buffered);
        if (event.message?.content) progress.report(new this.vscode.LanguageModelTextPart(event.message.content));
      }
    } finally {
      cancellation.dispose();
    }
  }

  async provideTokenCount(_model, value) {
    const text = typeof value === 'string' ? value : messageText(value);
    return Math.max(1, Math.ceil(text.length / 4));
  }
}

module.exports = { admittedBaseUrl, messageText, ollamaMessages, OllamaChatProvider };

