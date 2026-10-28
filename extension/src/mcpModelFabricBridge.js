'use strict';

const cp = require('child_process');
const fs = require('fs');
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

function nativeFailure(value) {
  if (!value || value.schema_version !== 'px.provider-client-failure/1.0' || typeof value.failure_type !== 'string' ||
      typeof value.retryable !== 'boolean' || !['unknown','quota','http_5xx','timeout','transport','invalid_request','policy_denied','cancelled','deadline'].includes(value.failure_class) ||
      (value.upstream_status !== null && (!Number.isInteger(value.upstream_status) || value.upstream_status < 100 || value.upstream_status > 599))) {
    throw new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X returned an invalid failure contract.');
  }
  const error = new ModelFabricBridgeError(value.upstream_status === 429 ? 'rate_limit_exceeded' : 'PX_MODEL_PROVIDER_FAILED',
    `Pacify-X provider failed (${String(value.failure_type).slice(0, 128)}).`);
  error.status = value.upstream_status; error.retryable = value.retryable; error.failureClass = value.failure_class;
  error.retryAfterSeconds = Number.isFinite(value.retry_after_seconds) && value.retry_after_seconds >= 0 && value.retry_after_seconds <= 3600 ? value.retry_after_seconds : null;
  return error;
}

function defaultRunner({ operation, payload, pythonPath, engineRoot, projectRoot, token, onEvent, timeoutMs = 300000 }) {
  if (token && typeof token.addEventListener === 'function' && typeof token.aborted === 'boolean') {
    const signal = token;
    token = { get isCancellationRequested() { return signal.aborted; }, onCancellationRequested(listener) {
      signal.addEventListener('abort', listener, { once: true });
      return { dispose: () => signal.removeEventListener('abort', listener) };
    } };
  }
  if (token?.isCancellationRequested) return Promise.reject(new ModelFabricBridgeError('PX_MODEL_CLIENT_CANCELLED', 'Pacify-X model client was cancelled before launch.'));
  return new Promise((resolve, reject) => {
    const child = cp.spawn(pythonPath, ['-m', 'runtime.vscode_model_bridge', operation, '--engine-root', engineRoot, '--project-root', projectRoot], {
      cwd: engineRoot, shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
      ...processTreeSpawnOptions(), env: { ...nonBillableEnvironment(), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' }
    });
    let stdout = ''; let stderr = ''; let total = 0; let receiptSeen = false; let providerFailure = null; let deliveries = Promise.resolve(); let settled = false; let cancelled = Boolean(token?.isCancellationRequested);
    const finish = (error, value) => {
      if (settled) return; settled = true; clearTimeout(timer); cancellation?.dispose?.();
      if (error) reject(error); else resolve(value);
    };
    const consumerFailure = () => {
      terminateProcessTree(child);
      finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_CONSUMER', 'Pacify-X model client consumer rejected output.'));
    };
    const deliver = event => {
      deliveries = deliveries.then(() => { if (!settled) return onEvent?.(event); });
      void deliveries.catch(consumerFailure);
    };
    const consumeLine = line => {
      if (!line.trim()) return;
      if (Buffer.byteLength(line, 'utf8') > MAX_LINE_BYTES) throw new ModelFabricBridgeError('PX_MODEL_CLIENT_LIMIT', 'Pacify-X model event exceeded its line bound.');
      const parsed = JSON.parse(line);
      if (receiptSeen || providerFailure) throw new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X model client produced output after its terminal receipt.');
      if (parsed?.type === 'event' && Object.keys(parsed).sort().join(',') === 'event,type' && parsed.event && typeof parsed.event === 'object') deliver(parsed.event);
      else if (parsed?.type === 'receipt' && Object.keys(parsed).sort().join(',') === 'receipt,type' && parsed.receipt && typeof parsed.receipt === 'object') {
        receiptSeen = true; deliver({ kind: 'px_receipt', payload: parsed.receipt });
      } else if (parsed?.type === 'failure' && Object.keys(parsed).sort().join(',') === 'failure,type') {
        providerFailure = nativeFailure(parsed.failure);
      } else throw new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X model client returned an unsupported event envelope.');
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
        try { for (const line of lines) consumeLine(line); }
        catch (error) {
          terminateProcessTree(child);
          finish(error instanceof ModelFabricBridgeError ? error : new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X model client returned invalid JSONL protocol.'));
        }
      }
    });
    child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-MAX_STDERR_BYTES); });
    child.on('error', () => finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_SPAWN', 'Pacify-X model client could not start.')));
    child.on('close', code => {
      if (settled) return;
      if (cancelled) { finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_CANCELLED', 'Pacify-X model client was cancelled.')); return; }
      if (operation === 'chat' && stdout.trim()) {
        try { consumeLine(stdout); stdout = ''; }
        catch (error) { finish(error instanceof ModelFabricBridgeError ? error : new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X model client ended with invalid JSONL protocol.')); return; }
      }
      if (providerFailure) { finish(providerFailure); return; }
      if (code !== 0 && operation !== 'chat') {
        try { const parsed = JSON.parse(stdout); if (parsed.type === 'failure') { finish(nativeFailure(parsed.failure)); return; } } catch {}
      }
      if (code !== 0) { finish(new ModelFabricBridgeError('PX_MODEL_CLIENT_FAILED', 'Pacify-X model client rejected or failed the request.')); return; }
      if (operation === 'chat') {
        try {
          if (stdout.trim()) consumeLine(stdout);
          if (!receiptSeen) throw new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X model client omitted its terminal receipt.');
        } catch (error) {
          finish(error instanceof ModelFabricBridgeError ? error : new ModelFabricBridgeError('PX_MODEL_CLIENT_PROTOCOL', 'Pacify-X model client ended with invalid JSONL protocol.')); return;
        }
        void deliveries.then(() => finish(null, { completed: true }), consumerFailure); return;
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
  inspectPreparedGroup(reference, token) {
    return this.runner({ ...this.context(), operation: 'prepared-group', payload: reference, token, timeoutMs: 30000 });
  }
  retrieveContext(payload, token) { return this.runner({ ...this.context(), operation: 'context', payload, token, timeoutMs: 30000 }); }
  countTokens(payload, token) { return this.runner({ ...this.context(), operation: 'count', payload, token, timeoutMs: 30000 }); }
  setSandboxMode(payload, token) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload) ||
        payload.schema_version !== 'px.isolated-agent-sandbox-request/1.0' ||
        !['ON', 'OFF'].includes(payload.mode) ||
        !Array.isArray(payload.allowed_endpoints) ||
        payload.allowed_endpoints.length > 256 ||
        (payload.mode === 'OFF' && payload.allowed_endpoints.length !== 0) ||
        payload.allowed_endpoints.some(endpoint =>
          typeof endpoint !== 'string' || !endpoint.trim() ||
          endpoint.length > 253 || !/^[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?$/.test(endpoint))) {
      throw new ModelFabricBridgeError('PX_SANDBOX_REQUEST_INVALID', 'Sandbox request is invalid.');
    }
    if ((payload.scope_key !== undefined &&
         (typeof payload.scope_key !== 'string' || !payload.scope_key.trim() || payload.scope_key.length > 512)) ||
        (payload.policy_revision !== undefined &&
         (typeof payload.policy_revision !== 'string' || !payload.policy_revision.trim() || payload.policy_revision.length > 128))) {
      throw new ModelFabricBridgeError('PX_SANDBOX_REQUEST_INVALID', 'Sandbox scope or policy revision is invalid.');
    }
    const context = this.context();
    const expectedScope = fs.realpathSync(context.projectRoot).replaceAll('\\', '/');
    if (payload.scope_key !== undefined &&
        String(payload.scope_key).replaceAll('\\', '/') !== expectedScope) {
      throw new ModelFabricBridgeError('PX_SANDBOX_REQUEST_INVALID', 'Sandbox scope does not match the project root.');
    }
    const expectedRevision = payload.policy_revision || 'sandbox-r1';
    return Promise.resolve(this.runner({ ...context, operation: 'sandbox', payload, token, timeoutMs: 30000 })).then(result => {
      const policy = result?.policy;
      const endpoints = [...new Set(payload.allowed_endpoints)].sort();
      if (result?.schema_version !== 'px.isolated-agent-sandbox-result/1.0' ||
          result.authority_granted !== false || result.mode !== payload.mode ||
          !policy || policy.schema_version !== 'px.isolated-agent-sandbox/1.0' ||
          policy.mode !== payload.mode || policy.scope_key !== expectedScope ||
          policy.policy_revision !== expectedRevision ||
          !/^[a-f0-9]{64}$/.test(String(policy.policy_sha256 || '')) ||
          policy.authority_granted !== false ||
          policy.network_policy?.default !== 'deny' ||
          JSON.stringify(policy.network_policy?.allowed_endpoints) !== JSON.stringify(endpoints)) {
        throw new ModelFabricBridgeError('PX_SANDBOX_RESPONSE_INVALID', 'Pacify-X returned an invalid sandbox policy.');
      }
      return result;
    });
  }
  streamChat(payload, token, onEvent) { return this.runner({ ...this.context(), operation: 'chat', payload, token, onEvent, timeoutMs: Math.min(600000, Number(payload?.deadline_ms || 300000) + 5000) }); }
}

module.exports = { ModelFabricBridgeError, defaultRunner, McpModelFabricBridge };
