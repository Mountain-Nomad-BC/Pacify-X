'use strict';

const cp = require('child_process');
const path = require('path');
const { nonBillableEnvironment } = require('./contextBridge');
const { processTreeSpawnOptions, terminateProcessTreeAsync } = require('./processTree');

const MAX_QUEUE = 1000;
const MAX_BATCH = 250;
const MAX_OUTPUT = 2 * 1024 * 1024;
const MAX_EVENT_BYTES = 64 * 1024;

class CanonicalEventPublisher {
  constructor(options = {}) {
    this.pythonPath = options.pythonPath || 'python';
    this.engineRoot = options.engineRoot || null;
    this.workspaceRoot = options.workspaceRoot || null;
    this.onHealth = options.onHealth || (() => {});
    this.delayMs = Number(options.delayMs ?? 1000);
    this.timeoutMs = Number(options.timeoutMs ?? 15_000);
    this.spawn = options.spawn || cp.spawn;
    this.schedule = options.schedule || setTimeout;
    this.cancelSchedule = options.cancelSchedule || clearTimeout;
    this.queue = [];
    this.timer = null;
    this.running = null;
    this.activeChild = null;
    this.closed = false;
  }

  update(options = {}) {
    this.pythonPath = options.pythonPath || this.pythonPath;
    this.engineRoot = options.engineRoot || null;
    this.workspaceRoot = options.workspaceRoot || null;
  }

  publish(event) {
    if (this.closed || !event || !this.engineRoot || !this.workspaceRoot) {
      this.onHealth({ connected: false, status: 'unconfigured', dropped: event ? 1 : 0, error_code: 'canonical-bus-unconfigured' });
      return false;
    }
    if (this.queue.length >= MAX_QUEUE) {
      this.onHealth({ connected: false, status: 'degraded', dropped: 1, error_code: 'canonical-bus-queue-full' });
      return false;
    }
    let eventBytes;
    try { eventBytes = Buffer.byteLength(JSON.stringify(event), 'utf8'); }
    catch {
      this.onHealth({ connected: false, status: 'degraded', dropped: 1, error_code: 'canonical-bus-event-not-serializable' });
      return false;
    }
    if (eventBytes > MAX_EVENT_BYTES) {
      this.onHealth({ connected: false, status: 'degraded', dropped: 1, error_code: 'canonical-bus-event-too-large' });
      return false;
    }
    this.queue.push(event);
    // Leading-edge scheduling guarantees continuous event streams are drained
    // at a bounded cadence instead of continually resetting the debounce.
    if (!this.timer && !this.running) this.timer = this.schedule(() => { void this.flush(); }, this.delayMs);
    return true;
  }

  async flush() {
    if (this.running) return this.running;
    this.cancelSchedule(this.timer); this.timer = null;
    if (!this.queue.length || this.closed) return null;
    const events = this.queue.splice(0, MAX_BATCH);
    this.running = this._send(events).finally(() => {
      this.running = null;
      if (this.queue.length && !this.closed && !this.timer) this.timer = this.schedule(() => { void this.flush(); }, this.delayMs);
    });
    return this.running;
  }

  _send(events) {
    return new Promise(resolve => {
      const busRoot = path.join(this.workspaceRoot, '.engineering-bootstrap', 'operation-bus');
      const args = ['-m', 'runtime.cli', '--root', this.engineRoot, 'visibility', 'publish', '--bus-root', busRoot];
      let child;
      try {
        child = this.spawn(this.pythonPath, args, {
          cwd: this.engineRoot, shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
          ...processTreeSpawnOptions(),
          env: { ...nonBillableEnvironment(), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1', NO_COLOR: '1' }
        });
      } catch (error) {
        this.onHealth({ connected: false, status: 'degraded', dropped: events.length, error_code: error.code || 'canonical-bus-spawn-failed' }); resolve(null); return;
      }
      this.activeChild = child;
      let stdout = ''; let stderr = ''; let settled = false;
      const finish = (result, errorCode = null) => {
        if (settled) return; settled = true; clearTimeout(timer);
        if (this.activeChild === child) this.activeChild = null;
        if (result) this.onHealth({ connected: true, published: Number(result.published || events.length) });
        else this.onHealth({ connected: false, status: 'degraded', dropped: events.length, error_code: errorCode || 'canonical-bus-publish-failed' });
        resolve(result);
      };
      const capture = (current, chunk) => {
        const next = current + chunk.toString('utf8');
        if (Buffer.byteLength(next, 'utf8') > MAX_OUTPUT) { void terminateProcessTreeAsync(child); finish(null, 'canonical-bus-output-limit'); return next.slice(0, MAX_OUTPUT); }
        return next;
      };
      child.stdout?.on('data', chunk => { stdout = capture(stdout, chunk); });
      child.stderr?.on('data', chunk => { stderr = capture(stderr, chunk); });
      child.on('error', error => finish(null, error.code || 'canonical-bus-process-error'));
      child.on('close', code => {
        if (code !== 0) { finish(null, `canonical-bus-exit-${code}`); return; }
        try { const result = JSON.parse(stdout); finish(result?.valid ? result : null, result?.valid ? null : 'canonical-bus-invalid-result'); }
        catch { finish(null, 'canonical-bus-invalid-json'); }
      });
      const timer = setTimeout(() => {
        void terminateProcessTreeAsync(child).then(verified => finish(null, verified ? 'canonical-bus-timeout' : 'canonical-bus-termination-unverified'));
      }, this.timeoutMs);
      child.stdin.on('error', () => finish(null, 'canonical-bus-stdin-error'));
      child.stdin.end(JSON.stringify({ schema_version: 'px.operation-batch/1.0', events }));
    });
  }

  dispose() {
    this.closed = true; this.cancelSchedule(this.timer); this.timer = null;
    const child = this.activeChild; this.activeChild = null;
    if (child) {
      // Canonical publication owns a single Python child with no expected
      // descendants. Request direct termination synchronously without running
      // a blocking process-tree command in the extension host event loop.
      void terminateProcessTreeAsync(child);
      this.onHealth({ connected: false, status: 'closed', dropped: 0, error_code: 'canonical-bus-disposed-active-child' });
    }
    if (this.queue.length) this.onHealth({ connected: false, status: 'degraded', dropped: this.queue.length, error_code: 'canonical-bus-disposed-with-pending-events' });
    this.queue = [];
  }
}

module.exports = { CanonicalEventPublisher, MAX_QUEUE, MAX_BATCH, MAX_OUTPUT, MAX_EVENT_BYTES };
