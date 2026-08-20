'use strict';

const MIN_INTERVAL_MS = 60_000;
const MAX_INTERVAL_MS = 15 * 60_000;

class CanonicalMemoryLeaseController {
  constructor({ bridgeProvider, workspaceRootProvider, projectRootProvider, onState = () => {}, intervalMs = 5 * 60_000 } = {}) {
    if (typeof bridgeProvider !== 'function' || typeof workspaceRootProvider !== 'function') throw new TypeError('Canonical memory lease providers are required.');
    this.bridgeProvider = bridgeProvider;
    this.workspaceRootProvider = workspaceRootProvider;
    this.projectRootProvider = typeof projectRootProvider === 'function' ? projectRootProvider : () => undefined;
    this.onState = onState;
    this.intervalMs = Math.max(MIN_INTERVAL_MS, Math.min(MAX_INTERVAL_MS, Number(intervalMs) || 5 * 60_000));
    this.timer = null;
    this.pending = null;
    this.lastAttemptAt = 0;
    this.state = { state: 'detached', changed: false, reason: 'not-started', observed_at: null };
  }

  async ensure(reason = 'refresh', { force = false } = {}) {
    if (this.pending) return this.pending;
    if (!force && Date.now() - this.lastAttemptAt < MIN_INTERVAL_MS) return this.state;
    this.lastAttemptAt = Date.now();
    this.pending = (async () => {
      const workspaceRoot = this.workspaceRootProvider();
      if (!workspaceRoot) return { state: 'detached', changed: false, reason: 'canonical-workspace-not-configured' };
      try {
        return await this.bridgeProvider().ensureWorkspaceProjectLease(workspaceRoot, { projectRoot: this.projectRootProvider() });
      } catch (error) {
        return { state: 'degraded', changed: false, reason: `lease-controller-error:${error instanceof Error ? error.message : String(error)}` };
      }
    })().then(result => {
      this.state = { ...result, trigger: reason, observed_at: new Date().toISOString() };
      this.onState(this.state);
      return this.state;
    }).finally(() => { this.pending = null; });
    return this.pending;
  }

  start() {
    if (this.timer) return;
    void this.ensure('startup', { force: true });
    this.timer = setInterval(() => void this.ensure('bounded-renewal-timer'), this.intervalMs);
    this.timer.unref?.();
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  snapshot() { return { ...this.state, interval_ms: this.intervalMs, pending: Boolean(this.pending) }; }
  dispose() { this.stop(); }
}

module.exports = { MIN_INTERVAL_MS, MAX_INTERVAL_MS, CanonicalMemoryLeaseController };
