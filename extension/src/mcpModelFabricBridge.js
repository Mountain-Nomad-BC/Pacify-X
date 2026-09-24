'use strict';

const cp = require('child_process');
const path = require('path');
const { nonBillableEnvironment } = require('./contextBridge');
const { processTreeSpawnOptions, terminateProcessTree } = require('./processTree');

const MAX_STDOUT_BYTES = 16 * 1024 * 1024;
const MAX_STDERR_BYTES = 256 * 1024;
const MAX_LINE_BYTES = 1024 * 1024;

function boundedRoot(value, name) {
  if (!value || typeof value !== 'string') throw new Error(`${name}-unavailable`);
  return path.resolve(value);
}

class ModelFabricBridgeError extends Error {
  constructor(code, message) { super(message); this.name = 'ModelFabricBridgeError'; this.code = code; }
}

function defaultRunner({ operation, payload, pythonPath, engineRoot, projectRoot, token, onEvent, timeoutMs = 300000 }) {
  return new Promise((resolve, reject) => {
    const child = cp.spawn(pythonPath, ['-m', 'runtime.vscode_model_bridge', operation, '--engine-root', engineRoot, '--project-root', projectRoot], {
      cwd: engineRoot, shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      ...processTreeSpawnOptions(), env: { ...nonBillableEnvironment(), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' }
    });
    let stdout = ''; let stderr = ''; let total = 0; let settled = false; let cancelled = Boolean(token?.isCancellationRequested);
    const finish = (error, value) => {
      if (settled) return; settled = true; clearTimeout(timer); cancellation?.dispose?.();
      if (error) reject(error); else resolve(value);
    };
    const cancellation = token?.onCancellationRequested?.(() => { cancelled = true; terminateProcessTree(child); });
    const timer = setTimeout(() => { terminateProcessTree(child); finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_TIMEOUT', 'Pacify-X model client exceeded its bounded deadline.')); }, timeoutMs);
    if (cancelled) { terminateProcessTree(child); finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_CANCELLED', 'Pacify-X model client was cancelled.')); return; }
    child.stdin.end(JSON.stringify(payload || {}));
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      total += Buffer.byteLength(chunk, 'utf8');
      if (total > MAX_STDOUT_BYTES) { terminateProcessTree(child); finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_LIMIT', 'Pacify-X model client exceeded its output bound.')); return; }
      stdout += chunk;
      if (operation === 'chat') {
        const lines = stdout.split(/\r?\n/); stdout = lines.pop() || '';
        for (const line of lines) {
          if (!line.trim()) continue;
          if (Buffer.byteLength(line, 'utf8') > MAX_LINE_BYTES) { terminateProcessTree(child); finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_LIMIT', 'Pacify-X model event exceeded its line bound.')); return; }
          let parsed; try { parsed = JSON.parse(line); } catch { terminateProcessTree(child); finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X model client returned invalid JSONL.')); return; }
          if (parsed.type === 'event') onEvent?.(parsed.event);
          else if (parsed.type === 'receipt') onEvent?.({ kind: 'px_receipt', payload: parsed.receipt });
          else { terminateProcessTree(child); finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X model client returned an unsupported event envelope.')); return; }
        }
      }
    });
    child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-MAX_STDERR_BYTES); });
    child.on('error', () => finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_SPAWN', 'Pacify-X model client could not start.')));
    child.on('close', code => {
      if (settled) return;
      if (cancelled) { finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_CANCELLED', 'Pacify-X model client was cancelled.')); return; }
      if (code !== 0) { finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_FAILED', 'Pacify-X model client rejected or failed the request.')); return; }
      if (operation === 'chat') {
        if (stdout.trim()) { try { const parsed = JSON.parse(stdout); onEvent?.(parsed.event || parsed); } catch { finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X model client ended with malformed output.')); return; } }
        finish(null, { completed: true }); return;
      }
      try { finish(null, JSON.parse(stdout)); } catch { finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X model client returned malformed JSON.')); }
    });
  });
}

class McpModelFabricBridge {
  constructor({ pythonPath = () => 'python', engineRoot, projectRoot, runner = defaultRunner } = {}) {
    this.pythonPath = typeof pythonPath === 'function' ? pythonPath : () => pythonPath;
    this.engineRoot = engineRoot;
    this.projectRoot = projectRoot;
    this.runner = runner;
  }
  context() {
    return {
      pythonPath: String(this.pythonPath() || 'python'),
      engineRoot: boundedRoot(typeof this.engineRoot === 'function' ? this.engineRoot() : this.engineRoot, 'engine-root'),
      projectRoot: boundedRoot(typeof this.projectRoot === 'function' ? this.projectRoot() : this.projectRoot, 'project-root')
    };
  }
  listModels(token) { return this.runner({ ...this.context(), operation: 'list', payload: {}, token, timeoutMs: 10000 }); }
  countTokens(payload, token) { return this.runner({ ...this.context(), operation: 'count', payload, token, timeoutMs: 30000 }); }
  streamChat(payload, token, onEvent) { return this.runner({ ...this.context(), operation: 'chat', payload, token, onEvent, timeoutMs: Math.min(600000, Number(payload?.deadline_ms || 300000) + 5000) }); }
}

module.exports = { ModelFabricBridgeError, defaultRunner, McpModelFabricBridge };
