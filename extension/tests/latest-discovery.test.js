'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createLatestDiscoveryCoordinator } = require('../src/latestDiscovery');
const { WorkGovernor } = require('../src/workGovernor');

function deferred() {
  let resolve; let reject;
  const promise = new Promise((accept, decline) => { resolve = accept; reject = decline; });
  return { promise, resolve, reject };
}

test('ordinary observation coalesces with the current discovery', async () => {
  const coordinator = createLatestDiscoveryCoordinator();
  const first = deferred(); let starts = 0;
  const one = coordinator.run(() => { starts += 1; return first.promise; });
  const two = coordinator.run(() => { starts += 1; return Promise.resolve('wrong'); });
  assert.strictEqual(two, one);
  assert.equal(starts, 1);
  first.resolve('current');
  assert.equal(await two, 'current');
});

test('fresh discovery supersedes a stale observation and late stale settlement cannot clear its slot', async () => {
  const coordinator = createLatestDiscoveryCoordinator();
  const stale = deferred(); const current = deferred(); let starts = 0;
  const staleRun = coordinator.run(() => { starts += 1; return stale.promise; });
  const staleObserved = assert.rejects(staleRun, /work-superseded/);
  const currentRun = coordinator.run(() => { starts += 1; return current.promise; }, { requireFresh: true });
  assert.notStrictEqual(currentRun, staleRun);
  assert.equal(starts, 2);

  stale.reject(Object.assign(new Error('work-superseded'), { name: 'AbortError' }));
  await staleObserved;
  const joinedAfterStaleSettlement = coordinator.run(() => { starts += 1; return Promise.resolve('wrong'); });
  assert.strictEqual(joinedAfterStaleSettlement, currentRun);
  assert.equal(starts, 2);

  current.resolve('physical-v2');
  assert.equal(await joinedAfterStaleSettlement, 'physical-v2');
  const next = coordinator.run(() => { starts += 1; return Promise.resolve('next'); });
  assert.equal(await next, 'next');
  assert.equal(starts, 3);
});

test('synchronous start failure releases ownership for a later discovery', async () => {
  const coordinator = createLatestDiscoveryCoordinator();
  await assert.rejects(coordinator.run(() => { throw new Error('capture-failed'); }), /capture-failed/);
  assert.equal(await coordinator.run(() => Promise.resolve('recovered')), 'recovered');
});

test('monotonic coordinator generations reach real WorkGovernor supersession instead of its same-key join', async t => {
  const governor = new WorkGovernor({ pools: { cpuWorkers: { concurrency: 1, queueLimit: 4, timeoutMs: 5_000 } } });
  t.after(() => governor.dispose());
  const coordinator = createLatestDiscoveryCoordinator();
  const keys = [];
  const start = (generation, value, hold = false) => {
    const key = `environment-discovery:${generation}`; keys.push(key);
    return governor.run(key, async signal => {
      if (hold) await new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(Object.assign(new Error(String(signal.reason)), { name: 'AbortError' })), { once: true }));
      return value;
    }, { pool: 'cpuWorkers', supersessionKey: 'environment-discovery' });
  };

  const stale = coordinator.run(generation => start(generation, 'loaded-v1', true));
  const staleObserved = assert.rejects(stale, /work-superseded/);
  const fresh = coordinator.run(generation => start(generation, 'physical-v2'), { requireFresh: true });
  await staleObserved;
  assert.equal(await fresh, 'physical-v2');
  assert.deepEqual(keys, ['environment-discovery:1', 'environment-discovery:2']);
  const metrics = governor.snapshot().metrics;
  assert.equal(metrics.superseded, 1);
  assert.equal(metrics.joins, 0);
});
