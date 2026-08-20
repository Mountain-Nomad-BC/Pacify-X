'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { WorkGovernor } = require('../src/workGovernor');

const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test('ten equivalent requests execute once and join nine times', async () => {
  const governor = new WorkGovernor({ pools: { background: { concurrency: 1, queueLimit: 4 } } });
  const gate = deferred(); let executions = 0;
  const requests = Array.from({ length: 10 }, () => governor.run('same-refresh', async () => { executions += 1; return gate.promise; }));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(executions, 1); gate.resolve('done');
  assert.deepEqual(await Promise.all(requests), Array(10).fill('done'));
  assert.equal(governor.snapshot().metrics.joins, 9);
  assert.equal(governor.snapshot().metrics.duplicateExecutionsAvoided, 9);
});

test('bounded queue rejects excess background work and preserves concurrency', async () => {
  const governor = new WorkGovernor({ pools: { background: { concurrency: 1, queueLimit: 1 } } });
  const gate = deferred();
  const active = governor.run('active', () => gate.promise);
  await new Promise(resolve => setImmediate(resolve));
  const queued = governor.run('queued', async () => 'queued');
  await assert.rejects(governor.run('overflow', async () => 'overflow'), /queue is full/);
  assert.equal(governor.snapshot().pools[0].active, 1);
  assert.equal(governor.snapshot().pools[0].queued, 1);
  gate.resolve('active');
  assert.equal(await active, 'active');
  assert.equal(await queued, 'queued');
});

test('supersession cancels obsolete queued work without growing the queue', async () => {
  const governor = new WorkGovernor({ pools: { background: { concurrency: 1, queueLimit: 3 } } });
  const gate = deferred();
  const active = governor.run('blocker', () => gate.promise);
  await new Promise(resolve => setImmediate(resolve));
  const obsolete = governor.run('scan-a', async () => 'old', { supersessionKey: 'environment-scan' });
  const replacement = governor.run('scan-b', async () => 'new', { supersessionKey: 'environment-scan' });
  await assert.rejects(obsolete, /superseded/);
  gate.resolve('done'); await active;
  assert.equal(await replacement, 'new');
  assert.equal(governor.snapshot().metrics.superseded, 1);
});

test('repeated dependency failures open a quiet bounded circuit', async () => {
  let now = 1000;
  const governor = new WorkGovernor({ now: () => now, pools: { background: { concurrency: 1, queueLimit: 2 } } });
  const fail = () => governor.run(`probe-${now}`, async () => { throw new Error('offline'); }, { circuitKey: 'ollama', circuitThreshold: 2, circuitCooldownMs: 1000 });
  await assert.rejects(fail(), /offline/); now += 1; await assert.rejects(fail(), /offline/); now += 1;
  await assert.rejects(fail(), /circuit is open/);
  assert.equal(governor.snapshot().circuits[0].state, 'open');
  now += 1001;
  assert.equal(await governor.run('half-open-success', async () => 'ready', { circuitKey: 'ollama', circuitThreshold: 2, circuitCooldownMs: 1000 }), 'ready');
  assert.equal(governor.snapshot().circuits[0].state, 'closed');
});

test('active work is aborted at its pool deadline and resource diagnostics stay bounded', async () => {
  const governor = new WorkGovernor({ pools: { background: { concurrency: 1, queueLimit: 2, timeoutMs: 100 } } });
  await assert.rejects(governor.run('deadline', signal => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })), { once: true });
  })), /deadline|aborted/);
  const report = governor.snapshot();
  assert.equal(report.metrics.timedOut, 1);
  assert.ok(report.latency.operations.p50_ms >= 0);
  assert.ok(report.resources.rss_bytes > 0);
  assert.equal(typeof report.resources.event_loop_utilization, 'number');
  governor.dispose();
});

test('resource telemetry fails soft in proc-less or restricted hosts', () => {
  const governor = new WorkGovernor({ memoryUsage: () => { const error = new Error('uv_resident_set_memory'); error.code = 'ENOENT'; throw error; } });
  const report = governor.snapshot();
  assert.equal(report.resources.status, 'unavailable');
  assert.equal(report.resources.error_class, 'Error');
  assert.equal(report.resources.rss_bytes, null);
  assert.ok(Array.isArray(report.pools));
  governor.dispose();
});
