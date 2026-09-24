'use strict';

const cp = require('node:child_process');
const readline = require('node:readline');
const { ExecutionAdapter, sanitizeRemoteError } = require('./base');
const { newId } = require('../ids');

// Protocol-accurate starter against the supplied Codex app-server JSON-RPC shape.
// Production integration still needs PX ToolBroker-backed handling for server requests
// (command/file approvals and user input) before mutating execution is enabled.
class CodexAppServerAdapter extends ExecutionAdapter {
  constructor(options = {}) {
    super(options); this.command = options.command || 'codex'; this.args = options.args || ['app-server'];
    this.cwd = options.cwd || process.cwd(); this.child = null; this.rl = null; this.pending = new Map(); this.listeners = new Set(); this.threadId = null; this.activeTurnId = null;
  }

  async health() {
    const result = cp.spawnSync(this.command, ['--version'], { windowsHide: true, shell: false, encoding: 'utf8', timeout: 3000 });
    return result.status === 0 ? { status: 'healthy', detail: String(result.stdout || '').trim().slice(0, 240) } : { status: 'unavailable', detail: sanitizeRemoteError(result.stderr || result.error) };
  }

  async _ensureStarted() {
    if (this.child && !this.child.killed) return;
    this.child = cp.spawn(this.command, this.args, { cwd: this.cwd, windowsHide: true, shell: false, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, ...(this.options.environment || {}) } });
    this.child.stderr.on('data', chunk => this.options.onDiagnostic?.(`codex-app-server:${String(chunk).trim().slice(0, 800)}`));
    this.child.on('exit', (code, signal) => { const err = new Error(`codex-app-server-exited:${code ?? 'null'}:${signal ?? 'none'}`); for (const item of this.pending.values()) item.reject(err); this.pending.clear(); this.child = null; });
    this.rl = readline.createInterface({ input: this.child.stdout }); this.rl.on('line', line => this._onLine(line));
    await this._request('initialize', { clientInfo: { name: 'pacify-x', title: 'Pacify-X Agent Console', version: String(this.options.clientVersion || '0.7.0') }, capabilities: { experimentalApi: true, requestAttestation: false, explicitGatewayOauth: false, mcpServerOpenaiFormElicitation: false, optOutNotificationMethods: [], extensions: null } });
    this._notify('initialized', null);
  }

  _write(message) { if (!this.child?.stdin?.writable) throw new Error('codex-app-server-stdin-unavailable'); this.child.stdin.write(`${JSON.stringify(message)}\n`); }
  _request(method, params) {
    const id = newId('rpc'); return new Promise((resolve, reject) => { const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`codex-rpc-timeout:${method}`)); }, Number(this.options.rpcTimeoutMs || 30000)); this.pending.set(id, { resolve: v => { clearTimeout(timer); resolve(v); }, reject: e => { clearTimeout(timer); reject(e); }, method }); this._write({ method, id, params }); });
  }
  _notify(method, params) { const message = { method }; if (params != null) message.params = params; this._write(message); }

  _onLine(line) {
    let msg; try { msg = JSON.parse(line); } catch { this.options.onDiagnostic?.('codex-app-server-invalid-json'); return; }
    if (msg.id != null && (Object.hasOwn(msg, 'result') || Object.hasOwn(msg, 'error'))) {
      const key = String(msg.id); const pending = this.pending.get(key); if (!pending) return; this.pending.delete(key);
      if (msg.error) pending.reject(new Error(`codex-rpc-${pending.method}:${String(msg.error.message || msg.error.code || 'error').slice(0, 500)}`)); else pending.resolve(msg.result); return;
    }
    if (msg.method && msg.id != null) { for (const listener of this.listeners) listener({ kind: 'server-request', message: msg }); return; }
    if (msg.method) for (const listener of this.listeners) listener({ kind: 'notification', message: msg });
  }

  async createSession(input = {}) {
    await this._ensureStarted();
    const result = await this._request('thread/start', { model: input.model || this.options.model || null, modelProvider: input.modelProvider || this.options.modelProvider || null, cwd: input.cwd || this.cwd,
      approvalPolicy: input.approvalPolicy || 'on-request', sandbox: input.sandbox || 'read-only', baseInstructions: input.baseInstructions || null, developerInstructions: input.developerInstructions || null, ephemeral: false });
    this.threadId = result?.thread?.id || null; if (!this.threadId) throw new Error('codex-thread-id-missing'); return { sessionRef: this.threadId, raw: result };
  }

  async resumeSession(sessionRef) { await this._ensureStarted(); const result = await this._request('thread/resume', { threadId: sessionRef }); this.threadId = sessionRef; return { sessionRef, raw: result }; }

  async runTurn(input) {
    await this._ensureStarted(); if (!this.threadId) await this.createSession({ model: this.options.model, cwd: this.cwd });
    let text = ''; let usage = null; let finished = false; let turnStatus = null;
    const listener = event => {
      const msg = event.message;
      if (event.kind === 'server-request') {
        input.onEvent({ type: 'tool.approval.required', status: 'blocked', summary: `Codex server request ${msg.method} requires PX handling.`, payload: { codexMethod: msg.method, requestId: String(msg.id) } });
        // Fail closed. Production code should translate the request through ToolBroker and reply.
        this._write({ id: msg.id, error: { code: -32001, message: 'PX approval/tool bridge not enabled for this starter.' } }); return;
      }
      const method = msg.method; const params = msg.params || {};
      if (method === 'item/agentMessage/delta' && (!this.activeTurnId || params.turnId === this.activeTurnId)) { const delta = params.delta || ''; text += delta; input.onEvent({ type: 'worker.stream.delta', status: 'progress', summary: delta.slice(0, 500), payload: { delta, providerEvent: method } }); }
      else if (method === 'thread/tokenUsage/updated') { const u = params.tokenUsage || {}; usage = { inputTokens: u.last?.inputTokens ?? u.total?.inputTokens ?? null, outputTokens: u.last?.outputTokens ?? u.total?.outputTokens ?? null, totalTokens: u.last?.totalTokens ?? u.total?.totalTokens ?? null }; input.onEvent({ type: 'budget.updated', status: 'progress', summary: 'Codex token usage updated.', payload: { providerEvent: method, tokenUsage: u } }); }
      else if (method === 'account/rateLimits/updated') input.onEvent({ type: 'budget.updated', status: 'progress', summary: 'Codex rate limits updated.', payload: { providerEvent: method, rateLimits: params } });
      else if (method === 'turn/completed' && (!this.activeTurnId || params.turn?.id === this.activeTurnId)) { finished = true; turnStatus = params.turn?.status || 'completed'; }
      else if (method === 'turn/started') { this.activeTurnId = params.turn?.id || this.activeTurnId; input.onEvent({ type: 'worker.started', status: 'started', summary: 'Codex turn started.', payload: { providerEvent: method, turnId: this.activeTurnId } }); }
      else if (method === 'model/rerouted') input.onEvent({ type: 'route.changed', status: 'info', summary: 'Codex internally rerouted model.', payload: { providerEvent: method, details: params } });
    };
    this.listeners.add(listener);
    try {
      const prompt = [input.contextPack?.instruction || '', ...(input.contextPack?.refs || []).filter(r => r.content).map(r => `[#${r.refId} ${r.label}]\n${r.content}`), input.message].filter(Boolean).join('\n\n');
      const start = await this._request('turn/start', { threadId: this.threadId, input: [{ type: 'text', text: prompt, text_elements: [] }], model: this.options.model || null });
      this.activeTurnId = start?.turn?.id || this.activeTurnId;
      const timeoutAt = Date.now() + Number(this.options.turnTimeoutMs || 30 * 60 * 1000);
      while (!finished) { if (input.signal?.aborted) { await this.interrupt(); throw Object.assign(new Error('codex-turn-aborted'), { name: 'AbortError' }); } if (Date.now() > timeoutAt) { await this.interrupt(); throw new Error('codex-turn-timeout'); } await new Promise(resolve => setTimeout(resolve, 40)); }
      return { text, usage, providerStatus: turnStatus, sessionRef: this.threadId };
    } finally { this.listeners.delete(listener); this.activeTurnId = null; }
  }

  async interrupt() { if (!this.threadId || !this.activeTurnId) return false; try { await this._request('turn/interrupt', { threadId: this.threadId, turnId: this.activeTurnId }); return true; } catch { return false; } }
  async closeSession() { this.threadId = null; }
  async dispose() { try { this.rl?.close(); } catch {} try { this.child?.kill(); } catch {} this.child = null; for (const item of this.pending.values()) item.reject(new Error('codex-adapter-disposed')); this.pending.clear(); }
}

module.exports = { CodexAppServerAdapter };
