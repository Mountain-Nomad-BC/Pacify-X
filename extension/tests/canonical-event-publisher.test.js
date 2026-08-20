'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { PassThrough, Writable } = require('node:stream');
const test = require('node:test');
const { CanonicalEventPublisher, MAX_QUEUE, MAX_BATCH, MAX_EVENT_BYTES } = require('../src/canonicalEventPublisher');

function fakeSpawn(records, outcome = { code: 0, result: { valid: true, published: 1 } }) {
  return (command, args, options) => {
    const child = new EventEmitter(); child.stdout = new PassThrough(); child.stderr = new PassThrough();
    let input = '';
    child.stdin = new Writable({ write(chunk, _encoding, callback) { input += chunk.toString('utf8'); callback(); } });
    child.stdin.on('finish', () => {
      records.push({ command, args, options, document: JSON.parse(input) });
      if (outcome.result) child.stdout.end(JSON.stringify(outcome.result));
      setImmediate(() => child.emit('close', outcome.code));
    });
    child.kill = () => child.emit('close', 1);
    return child;
  };
}

test('publisher batches canonical events through fixed non-shell runtime ingress', async () => {
  const records = []; const health = [];
  const publisher = new CanonicalEventPublisher({
    pythonPath: 'python', engineRoot: 'C:/engine', workspaceRoot: 'C:/workspace',
    spawn: fakeSpawn(records, { code: 0, result: { valid: true, published: 2 } }),
    onHealth: value => health.push(value), delayMs: 1
  });
  assert.equal(publisher.publish({ event_id: 'one' }), true);
  assert.equal(publisher.publish({ event_id: 'two' }), true);
  await publisher.flush();
  assert.equal(records.length, 1);
  assert.equal(records[0].options.shell, false);
  assert.deepEqual(records[0].document, { schema_version: 'px.operation-batch/1.0', events: [{ event_id: 'one' }, { event_id: 'two' }] });
  assert.ok(records[0].args.includes('publish'));
  assert.deepEqual(health.at(-1), { connected: true, published: 2 });
});

test('publisher reports unconfigured, queue-full, and process failures without throwing into observed work', async () => {
  const health = [];
  const unavailable = new CanonicalEventPublisher({ onHealth: value => health.push(value) });
  assert.equal(unavailable.publish({ event_id: 'missing-root' }), false);
  assert.equal(health.at(-1).error_code, 'canonical-bus-unconfigured');

  const queuePublisher = new CanonicalEventPublisher({ engineRoot: 'C:/engine', workspaceRoot: 'C:/workspace', spawn: fakeSpawn([]), onHealth: value => health.push(value), delayMs: 60_000 });
  for (let index = 0; index < MAX_QUEUE; index += 1) assert.equal(queuePublisher.publish({ event_id: String(index) }), true);
  assert.equal(queuePublisher.publish({ event_id: 'overflow' }), false);
  assert.equal(health.at(-1).error_code, 'canonical-bus-queue-full');
  queuePublisher.dispose();

  const records = [];
  const publisher = new CanonicalEventPublisher({ engineRoot: 'C:/engine', workspaceRoot: 'C:/workspace', spawn: fakeSpawn(records, { code: 7 }), onHealth: value => health.push(value), delayMs: 60_000 });
  publisher.publish({ event_id: 'process-failure' });
  await publisher.flush();
  assert.equal(health.at(-1).error_code, 'canonical-bus-exit-7');
  publisher.dispose();
});

test('continuous publication uses one leading-edge timer and large bounded batches', async () => {
  const timers = []; const records = [];
  const publisher = new CanonicalEventPublisher({
    engineRoot: 'C:/engine', workspaceRoot: 'C:/workspace', spawn: fakeSpawn(records, { code: 0, result: { valid: true, published: MAX_BATCH } }),
    schedule: callback => { const timer = { callback }; timers.push(timer); return timer; }, cancelSchedule() {}
  });
  for (let index = 0; index < MAX_BATCH; index += 1) assert.equal(publisher.publish({ event_id: String(index) }), true);
  assert.equal(timers.length, 1);
  await publisher.flush();
  assert.equal(records.length, 1);
  assert.equal(records[0].document.events.length, MAX_BATCH);
  assert.equal(publisher.publish({ payload: 'x'.repeat(MAX_EVENT_BYTES) }), false);
  publisher.dispose();
});

test('dispose requests termination of the one active publisher child and drops its bounded remainder', async () => {
  const health = []; let child; let resolveClose;
  const spawn = () => {
    child = new EventEmitter(); child.pid = 4242; child.stdout = new PassThrough(); child.stderr = new PassThrough();
    child.stdin = new Writable({ write(_chunk, _encoding, callback) { callback(); } });
    child.killCalls = []; child.kill = signal => { child.killCalls.push(signal); setImmediate(() => child.emit('close', 143)); return true; };
    resolveClose = () => child.emit('close', 0); return child;
  };
  const publisher = new CanonicalEventPublisher({ engineRoot: 'C:/engine', workspaceRoot: 'C:/workspace', spawn, onHealth: row => health.push(row), delayMs: 60_000 });
  publisher.publish({ event_id: 'active' }); const running = publisher.flush();
  publisher.publish({ event_id: 'queued' });
  publisher.dispose();
  await running;
  assert.deepEqual(child.killCalls, ['SIGTERM']);
  assert.ok(health.some(row => row.error_code === 'canonical-bus-disposed-active-child'));
  assert.ok(health.some(row => row.error_code === 'canonical-bus-disposed-with-pending-events'));
  resolveClose?.();
});
