'use strict';

const { ExecutionAdapter } = require('./base');

class MockAdapter extends ExecutionAdapter {
  async health() { return { status: 'healthy', detail: 'deterministic-test-adapter' }; }
  async runTurn(input) {
    const text = this.options.response || 'PX mock worker completed the test turn.';
    for (const part of text.match(/.{1,18}/g) || []) { input.onEvent({ type: 'worker.stream.delta', status: 'progress', summary: part, payload: { delta: part } }); }
    return { text, usage: { inputTokens: 10, outputTokens: Math.ceil(text.length / 4), totalTokens: 10 + Math.ceil(text.length / 4) } };
  }
}

module.exports = { MockAdapter };
