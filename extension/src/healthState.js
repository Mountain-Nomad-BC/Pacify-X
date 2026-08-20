'use strict';

const HEALTH_DIMENSIONS = Object.freeze(['configured', 'detected', 'connected', 'authoritative', 'ready']);

function bool(value) { return value === true; }

function createHealthState(input = {}) {
  const state = {
    configured: bool(input.configured),
    detected: bool(input.detected),
    connected: bool(input.connected),
    authoritative: bool(input.authoritative),
    ready: bool(input.ready),
    reason: typeof input.reason === 'string' && input.reason.trim() ? input.reason.trim() : null,
    observed_at: typeof input.observed_at === 'string' ? input.observed_at : null
  };
  if (state.detected && !state.configured) throw new Error('health-state-detected-requires-configured');
  if (state.connected && !state.detected) throw new Error('health-state-connected-requires-detected');
  if (state.authoritative && !state.connected) throw new Error('health-state-authoritative-requires-connected');
  if (state.ready && !state.authoritative) throw new Error('health-state-ready-requires-authoritative');
  return Object.freeze(state);
}

function healthLabel(state) {
  const normalized = createHealthState(state);
  if (normalized.ready) return 'READY';
  if (normalized.authoritative) return 'AUTHORITATIVE';
  if (normalized.connected) return 'CONNECTED';
  if (normalized.detected) return 'DETECTED';
  if (normalized.configured) return 'CONFIGURED';
  return 'UNCONFIGURED';
}

module.exports = { HEALTH_DIMENSIONS, createHealthState, healthLabel };
