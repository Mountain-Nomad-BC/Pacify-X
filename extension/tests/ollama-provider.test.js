'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { OllamaChatProvider } = require('../src/ollamaProvider');

function vscodeHarness() {
  return {
    EventEmitter: class { constructor() { this.event = () => ({ dispose() {} }); } fire() {} dispose() {} },
    LanguageModelTextPart: class { constructor(value) { this.value = value; } },
    LanguageModelChatMessageRole: { Assistant: 2 }
  };
}

function cancellationToken() {
  let handler = () => {};
  return { token: { isCancellationRequested: false, onCancellationRequested(callback) { handler = callback; return { dispose() {} }; } }, cancel() { handler(); } };
}

async function faultServer() {
  const sockets = new Set();
  const server = http.createServer((request, response) => {
    if (request.url !== '/api/chat') { response.writeHead(404).end(); return; }
    let body = '';
    request.on('data', chunk => { body += chunk; });
    request.on('end', () => {
      const model = JSON.parse(body).model;
      response.writeHead(model === 'http-error' ? 503 : 200, { 'content-type': 'application/x-ndjson' });
      if (model === 'http-error') { response.end(); return; }
      if (model === 'success') { response.end('{"message":{"content":"hello"}}\n{"done":true}\n'); return; }
      if (model === 'malformed') { response.end('{bad json}\n'); return; }
      if (model === 'truncated') { response.end('{"message":{"content":"partial"}}\n'); return; }
      if (model === 'huge') { response.end(JSON.stringify({ message: { content: 'x'.repeat(1024) } }) + '\n'); return; }
      if (model === 'remote-error') { response.end('{"error":"sensitive backend details"}\n'); return; }
      if (model === 'disconnect') { response.write('{"message":{"content":"partial"}}\n'); response.socket.destroy(); return; }
      if (model === 'slow' || model === 'cancel') { response.write('{"message":{"content":"started"}}\n'); return; }
      response.end('{"done":true}\n');
    });
  });
  server.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { baseUrl: `http://127.0.0.1:${server.address().port}`, close: async () => { for (const socket of sockets) socket.destroy(); await new Promise(resolve => server.close(resolve)); } };
}

function invoke(baseUrl, model, overrides = {}) {
  const vscode = vscodeHarness(); const cancel = cancellationToken(); const output = [];
  const provider = new OllamaChatProvider(vscode, () => baseUrl, { idleTimeoutMs: 100, totalTimeoutMs: 2500, maxLineBytes: 256, maxStreamBytes: 512, ...overrides });
  const promise = provider.provideLanguageModelChatResponse({ id: model, maxOutputTokens: 128 }, [], {}, { report(part) { output.push(part.value); } }, cancel.token);
  return { promise, output, cancel };
}

test('bounded Ollama loopback stream succeeds only after an explicit completion event', async t => {
  const server = await faultServer(); t.after(server.close);
  const result = invoke(server.baseUrl, 'success'); await result.promise;
  assert.deepEqual(result.output, ['hello']);
});

test('Ollama streaming faults have stable, non-sensitive classifications', async t => {
  const server = await faultServer(); t.after(server.close);
  const cases = [
    ['http-error', 'OLLAMA_HTTP_ERROR'], ['malformed', 'OLLAMA_STREAM_MALFORMED'],
    ['truncated', 'OLLAMA_STREAM_TRUNCATED'], ['huge', 'OLLAMA_STREAM_LIMIT'],
    ['remote-error', 'OLLAMA_REMOTE_ERROR'], ['disconnect', 'OLLAMA_STREAM_DISCONNECTED'],
    ['slow', 'OLLAMA_IDLE_TIMEOUT']
  ];
  for (const [model, code] of cases) {
    await assert.rejects(invoke(server.baseUrl, model).promise, error => {
      assert.equal(error.code, code, model);
      assert.doesNotMatch(error.message, /sensitive backend details/);
      return true;
    });
  }
});

test('Ollama cancellation is distinct from timeout and disconnect', async t => {
  const server = await faultServer(); t.after(server.close);
  const result = invoke(server.baseUrl, 'cancel');
  setTimeout(() => result.cancel.cancel(), 20);
  await assert.rejects(result.promise, error => error.code === 'OLLAMA_CANCELLED');
});

test('Ollama total deadline is independently classified', async t => {
  const server = await faultServer(); t.after(server.close);
  const result = invoke(server.baseUrl, 'slow', { idleTimeoutMs: 500, totalTimeoutMs: 45 });
  await assert.rejects(result.promise, error => error.code === 'OLLAMA_TOTAL_TIMEOUT');
});
