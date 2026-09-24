'use strict';

class ExecutionAdapter {
  constructor(options = {}) { this.options = options; }
  async health() { return { status: 'unknown' }; }
  async createSession() { return { sessionRef: null }; }
  async resumeSession(sessionRef) { return { sessionRef }; }
  async runTurn() { throw new Error('adapter-runTurn-not-implemented'); }
  async interrupt() { return false; }
  async closeSession() {}
  async dispose() {}
}

function sanitizeRemoteError(error) {
  const text = String(error?.message || error || 'unknown-error');
  return text.replace(/(authorization|api[-_ ]?key|token)\s*[:=]\s*[^\s,;]+/ig, '$1=[redacted]').slice(0, 1000);
}

module.exports = { ExecutionAdapter, sanitizeRemoteError };
