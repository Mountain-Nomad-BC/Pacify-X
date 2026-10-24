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

function providerHttpError(status, detail) {
  const error = new Error(`provider-http-${status}:${sanitizeRemoteError(detail)}`);
  error.status = status;
  if (status === 429) error.code = 'rate_limit_exceeded';
  return error;
}

function isCapacityError(error) {
  if (error?.retryable === false) return false;
  return error?.status === 429 || ['rate_limit_exceeded', 'insufficient_quota', 'quota_exceeded',
    'context_length_exceeded', 'model_capacity_exceeded'].includes(error?.code);
}

module.exports = { ExecutionAdapter, sanitizeRemoteError, providerHttpError, isCapacityError };
