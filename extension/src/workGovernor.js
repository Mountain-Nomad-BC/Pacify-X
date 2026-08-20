'use strict';

const { performance } = require('node:perf_hooks');

const DEFAULT_POOLS = Object.freeze({
  interactive: { concurrency: 2, queueLimit: 16, timeoutMs: 30_000 },
  providerIo: { concurrency: 2, queueLimit: 8, timeoutMs: 30_000 },
  filesystem: { concurrency: 1, queueLimit: 6, timeoutMs: 45_000 },
  cpuWorkers: { concurrency: 1, queueLimit: 4, timeoutMs: 60_000 },
  validation: { concurrency: 1, queueLimit: 3, timeoutMs: 180_000 },
  background: { concurrency: 1, queueLimit: 6, timeoutMs: 60_000 }
});

function abortError(reason = 'work-cancelled') {
  const error = new Error(reason);
  error.name = 'AbortError';
  return error;
}

class WorkGovernor {
  constructor(options = {}) {
    this.now = options.now || Date.now;
    this.memoryUsage = options.memoryUsage || (() => process.memoryUsage());
    this.pools = new Map();
    for (const [id, policy] of Object.entries(options.pools || DEFAULT_POOLS)) {
      this.pools.set(id, {
        id,
        concurrency: Math.max(1, Number(policy.concurrency) || 1),
        queueLimit: Math.max(1, Number(policy.queueLimit) || 1),
        timeoutMs: Math.max(100, Number(policy.timeoutMs) || 30_000),
        active: 0,
        queue: []
      });
    }
    this.entries = new Map();
    this.supersession = new Map();
    this.circuits = new Map();
    this.sequence = 0;
    this.disposed = false;
    this.metrics = {
      starts: 0,
      joins: 0,
      completed: 0,
      failed: 0,
      cancelled: 0,
      superseded: 0,
      rejected: 0,
      duplicateExecutionsAvoided: 0,
      maxQueueDepth: 0
    };
    this.durations = [];
    this.queueWaits = [];
    this.eventLoopBaseline = performance.eventLoopUtilization();
  }

  run(key, producer, options = {}) {
    if (this.disposed) return Promise.reject(abortError('work-governor-disposed'));
    if (!key || typeof producer !== 'function') return Promise.reject(new TypeError('bounded work requires a key and producer'));
    const existing = this.entries.get(key);
    if (existing) {
      this.metrics.joins += 1;
      this.metrics.duplicateExecutionsAvoided += 1;
      return existing.promise;
    }
    const pool = this.pools.get(options.pool || 'background');
    if (!pool) return Promise.reject(new Error(`unknown work pool: ${options.pool}`));
    const circuitKey = options.circuitKey || null;
    if (circuitKey && !this._admitCircuit(circuitKey, options)) {
      this.metrics.rejected += 1;
      return Promise.reject(new Error(`work circuit is open: ${circuitKey}`));
    }
    if (options.supersessionKey) {
      const previous = this.supersession.get(options.supersessionKey);
      if (previous && previous !== key) this.cancel(previous, 'work-superseded');
      this.supersession.set(options.supersessionKey, key);
    }
    const controller = new AbortController();
    let resolve;
    let reject;
    const promise = new Promise((accept, decline) => { resolve = accept; reject = decline; });
    const entry = {
      key,
      producer,
      promise,
      resolve,
      reject,
      controller,
      pool,
      priority: Math.max(0, Math.min(5, Number.isFinite(Number(options.priority)) ? Number(options.priority) : 3)),
      reason: String(options.reason || 'unspecified').slice(0, 160),
      circuitKey,
      circuitThreshold: Math.max(1, Number(options.circuitThreshold) || 3),
      circuitCooldownMs: Math.max(1000, Number(options.circuitCooldownMs) || 30_000),
      supersessionKey: options.supersessionKey || null,
      state: 'queued',
      queuedAt: this.now(),
      startedAt: null,
      sequence: this.sequence += 1
    };
    entry.timeoutMs = Math.max(100, Number(options.timeoutMs) || pool.timeoutMs);
    this.entries.set(key, entry);
    if (!this._enqueue(pool, entry)) {
      this.entries.delete(key);
      if (entry.supersessionKey && this.supersession.get(entry.supersessionKey) === entry.key) this.supersession.delete(entry.supersessionKey);
      if (entry.circuitKey) {
        const circuit = this.circuits.get(entry.circuitKey);
        if (circuit?.state === 'half-open') circuit.halfOpenActive = false;
      }
      this.metrics.rejected += 1;
      reject(new Error(`work queue is full: ${pool.id}`));
      return promise;
    }
    this.metrics.maxQueueDepth = Math.max(this.metrics.maxQueueDepth, pool.queue.length);
    this._drain(pool);
    return promise;
  }

  _enqueue(pool, entry) {
    if (pool.queue.length >= pool.queueLimit) {
      const candidates = pool.queue.filter(item => item.priority > entry.priority).sort((left, right) => right.priority - left.priority || right.sequence - left.sequence);
      const displaced = candidates[0];
      if (!displaced) return false;
      pool.queue.splice(pool.queue.indexOf(displaced), 1);
      this.entries.delete(displaced.key);
      if (displaced.supersessionKey && this.supersession.get(displaced.supersessionKey) === displaced.key) this.supersession.delete(displaced.supersessionKey);
      displaced.state = 'rejected';
      displaced.reject(new Error(`work displaced by higher-priority request: ${entry.key}`));
      this.metrics.rejected += 1;
    }
    pool.queue.push(entry);
    pool.queue.sort((left, right) => left.priority - right.priority || left.sequence - right.sequence);
    return true;
  }

  _drain(pool) {
    while (!this.disposed && pool.active < pool.concurrency && pool.queue.length) {
      const entry = pool.queue.shift();
      if (!entry || entry.state !== 'queued') continue;
      pool.active += 1;
      entry.state = 'active';
      entry.startedAt = this.now();
      this.queueWaits.push(Math.max(0, entry.startedAt - entry.queuedAt));
      if (this.queueWaits.length > 256) this.queueWaits.shift();
      this.metrics.starts += 1;
      const timeout = setTimeout(() => {
        if (entry.state === 'active') {
          entry.timedOut = true;
          entry.controller.abort('work-deadline-exceeded');
        }
      }, entry.timeoutMs);
      const aborted = new Promise((_, reject) => entry.controller.signal.addEventListener('abort', () => reject(abortError(String(entry.controller.signal.reason || 'work-cancelled'))), { once: true }));
      Promise.resolve()
        .then(() => Promise.race([entry.producer(entry.controller.signal), aborted]))
        .then(value => {
          if (entry.controller.signal.aborted) throw abortError(String(entry.controller.signal.reason || 'work-cancelled'));
          entry.state = 'completed';
          this.metrics.completed += 1;
          this._recordCircuit(entry, true);
          entry.resolve(value);
        })
        .catch(error => {
          const cancelled = entry.controller.signal.aborted || error?.name === 'AbortError';
          entry.state = cancelled ? 'cancelled' : 'failed';
          this.metrics[cancelled ? 'cancelled' : 'failed'] += 1;
          if (entry.timedOut) this.metrics.timedOut = (this.metrics.timedOut || 0) + 1;
          this._recordCircuit(entry, false, cancelled);
          entry.reject(error);
        })
        .finally(() => {
          clearTimeout(timeout);
          this.durations.push(Math.max(0, this.now() - entry.startedAt));
          if (this.durations.length > 256) this.durations.shift();
          pool.active -= 1;
          if (this.entries.get(entry.key) === entry) this.entries.delete(entry.key);
          if (entry.supersessionKey && this.supersession.get(entry.supersessionKey) === entry.key) this.supersession.delete(entry.supersessionKey);
          this._drain(pool);
        });
    }
  }

  cancel(key, reason = 'work-cancelled') {
    const entry = this.entries.get(key);
    if (!entry) return false;
    if (reason === 'work-superseded') this.metrics.superseded += 1;
    if (entry.state === 'queued') {
      const index = entry.pool.queue.indexOf(entry);
      if (index >= 0) entry.pool.queue.splice(index, 1);
      this.entries.delete(key);
      entry.state = 'cancelled';
      this.metrics.cancelled += 1;
      entry.reject(abortError(reason));
    } else if (entry.state === 'active') {
      entry.controller.abort(reason);
    }
    return true;
  }

  _admitCircuit(key, options) {
    const circuit = this.circuits.get(key);
    if (!circuit || circuit.state === 'closed') return true;
    if (this.now() < circuit.openUntil) return false;
    if (circuit.halfOpenActive) return false;
    circuit.state = 'half-open';
    circuit.halfOpenActive = true;
    circuit.cooldownMs = Math.max(1000, Number(options.circuitCooldownMs) || circuit.cooldownMs);
    return true;
  }

  _recordCircuit(entry, success, cancelled = false) {
    if (!entry.circuitKey || cancelled) return;
    const circuit = this.circuits.get(entry.circuitKey) || { state: 'closed', failures: 0, openUntil: 0, halfOpenActive: false, cooldownMs: entry.circuitCooldownMs };
    if (success) {
      Object.assign(circuit, { state: 'closed', failures: 0, openUntil: 0, halfOpenActive: false });
    } else {
      circuit.failures += 1;
      circuit.halfOpenActive = false;
      if (circuit.failures >= entry.circuitThreshold || circuit.state === 'half-open') {
        circuit.state = 'open';
        circuit.openUntil = this.now() + entry.circuitCooldownMs;
      }
    }
    this.circuits.set(entry.circuitKey, circuit);
  }

  snapshot() {
    const percentile = (values, fraction) => {
      if (!values.length) return 0;
      const sorted = [...values].sort((a, b) => a - b);
      return sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * fraction) - 1)];
    };
    let telemetry;
    try {
      const eventLoop = performance.eventLoopUtilization(this.eventLoopBaseline);
      this.eventLoopBaseline = performance.eventLoopUtilization();
      const memory = this.memoryUsage();
      telemetry = {
        status: 'available', error_class: null,
        rss_bytes: memory.rss, heap_used_bytes: memory.heapUsed,
        event_loop_utilization: Number(eventLoop.utilization.toFixed(6)),
        active_resource_types: typeof process.getActiveResourcesInfo === 'function' ? process.getActiveResourcesInfo().sort() : []
      };
    } catch (error) {
      telemetry = {
        status: 'unavailable', error_class: error?.constructor?.name || 'Error',
        rss_bytes: null, heap_used_bytes: null, event_loop_utilization: null,
        active_resource_types: []
      };
    }
    return {
      schema_version: 'px.work-governor/1.0',
      disposed: this.disposed,
      metrics: { ...this.metrics },
      pools: [...this.pools.values()].map(pool => ({ id: pool.id, concurrency: pool.concurrency, active: pool.active, queued: pool.queue.length, queueLimit: pool.queueLimit, timeoutMs: pool.timeoutMs })),
      work: [...this.entries.values()].map(entry => ({ key: entry.key, state: entry.state, pool: entry.pool.id, priority: entry.priority, reason: entry.reason, timeoutMs: entry.timeoutMs, queuedMs: Math.max(0, this.now() - entry.queuedAt), activeMs: entry.startedAt == null ? 0 : Math.max(0, this.now() - entry.startedAt) })),
      latency: {
        operations: { p50_ms: percentile(this.durations, 0.50), p95_ms: percentile(this.durations, 0.95), p99_ms: percentile(this.durations, 0.99) },
        queue_wait: { p50_ms: percentile(this.queueWaits, 0.50), p95_ms: percentile(this.queueWaits, 0.95), p99_ms: percentile(this.queueWaits, 0.99) }
      },
      resources: telemetry,
      circuits: [...this.circuits.entries()].map(([key, value]) => ({ key, state: value.state, failures: value.failures, openUntil: value.openUntil }))
    };
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    for (const key of [...this.entries.keys()]) this.cancel(key, 'work-governor-disposed');
  }
}

module.exports = { WorkGovernor, DEFAULT_POOLS, abortError };
