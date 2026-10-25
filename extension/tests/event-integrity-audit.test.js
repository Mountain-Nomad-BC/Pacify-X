'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { CanonicalEventBus } = require('../src/agentHarness/eventBus');
const { buildAgentConsoleProjection } = require('../src/agentHarness/agentConsoleProjection');
const { AgentConsoleViewProvider } = require('../src/agentHarness/agentConsoleView');
const { validateOutbound, MESSAGE_VERSION, ASSET_PROTOCOL } = require('../src/agentHarness/agentConsoleMessages');

test('nested snapshot secrets are redacted without mutating canonical events', () => {
  const bus = new CanonicalEventBus();
  const event = bus.emit('audit.completed', { payload: { nested: { authorization: 'private-one' }, items: [{ password: 'private-two', text: 'visible' }] } });
  const view = buildAgentConsoleProjection({ events: [event] });
  assert.equal(view.events[0].payload.nested.authorization, '[redacted]');
  assert.equal(view.events[0].payload.items[0].password, '[redacted]');
  assert.equal(view.events[0].payload.items[0].text, 'visible');
  assert.equal(event.payload.nested.authorization, 'private-one');
});

test('live and snapshot transport both redact nested secrets', async () => {
  const bus = new CanonicalEventBus();
  const frames = [];
  const provider = new AgentConsoleViewProvider({}, {}, { harness: { eventBus: bus, project: () => ({ events: bus.snapshot() }) } });
  provider.view = { webview: { postMessage: async message => frames.push(message) } };
  bus.emit('audit.completed', { payload: { nested: { apiKey: 'private-key' } } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(frames.find(frame => frame.type === 'event').event.payload.nested.apiKey, '[redacted]');
  assert.equal(frames.find(frame => frame.type === 'snapshot').state.events[0].payload.nested.apiKey, '[redacted]');
});

test('observer exceptions and rejected promises cannot change committed result', async () => {
  const faults = [];
  const bus = new CanonicalEventBus({ onDiagnostic: message => faults.push(message) });
  let delivered = 0;
  bus.subscribe(() => { throw new Error('subscriber fault'); });
  bus.subscribe(async () => { throw new Error('async subscriber fault'); });
  bus.subscribe(() => { delivered += 1; });
  const event = bus.emit('worker.completed', { payload: { text: 'completed output' } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(event.type, 'worker.completed');
  assert.equal(delivered, 1);
  assert.equal(faults.length, 2);
  assert.equal(bus.snapshot().length, 1);
});

test('oversize payloads and cumulative event buffers fit transport with omission proof', () => {
  const bus = new CanonicalEventBus();
  const event = bus.emit('audit.completed', { payload: { text: 'x'.repeat(600000) } });
  assert.doesNotThrow(() => validateOutbound({ schemaVersion: MESSAGE_VERSION, type: 'event', event }));
  assert.equal(event.payload.contentOmission.reason, 'event-payload-byte-budget');
  assert.match(event.payload.contentOmission.sha256, /^[a-f0-9]{64}$/);
  for (let i = 0; i < 100; i += 1) bus.emit('audit.completed', { payload: { text: 'x'.repeat(60000) } });
  const state = buildAgentConsoleProjection({ events: bus.snapshot() });
  assert.doesNotThrow(() => validateOutbound({ schemaVersion: MESSAGE_VERSION, type: 'snapshot', assetProtocol: ASSET_PROTOCOL, state }));
  assert.ok(bus.omissionSummary().bufferEvictedEvents > 0);
});

test('observer mutation cannot rewrite committed canonical events', () => {
  const bus = new CanonicalEventBus();
  const input = { nested: { text: 'committed' } };
  bus.subscribe(event => { event.payload.nested.text = 'rewritten'; });
  const event = bus.emit('audit.completed', { payload: input });
  input.nested.text = 'caller mutation';
  assert.equal(event.payload.nested.text, 'committed');
  assert.equal(bus.snapshot()[0].payload.nested.text, 'committed');
});
