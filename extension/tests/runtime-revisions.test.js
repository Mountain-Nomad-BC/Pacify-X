'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { RevisionStore, MetadataCache } = require('../src/runtimeRevisions');

test('targeted invalidation changes only the dependency closure', () => {
  const revisions = new RevisionStore();
  const providerBefore = revisions.fingerprint(['providers', 'models', 'routes', 'costs']);
  const hardwareBefore = revisions.fingerprint(['hardware']);
  const affected = revisions.invalidate('skills', 'skill-file-change');
  assert.deepEqual(affected, ['skills', 'capabilities', 'workflows', 'agents']);
  assert.equal(revisions.fingerprint(['providers', 'models', 'routes', 'costs']), providerBefore);
  assert.equal(revisions.fingerprint(['hardware']), hardwareBefore);
  assert.notEqual(revisions.fingerprint(['skills']), new RevisionStore().fingerprint(['skills']));
});

test('persistent metadata restores only with matching fingerprint and rejects corruption', async () => {
  const values = new Map();
  const store = { get: key => values.get(key), update: (key, value) => { values.set(key, value); } };
  const first = new MetadataCache({ store, now: () => 1000 });
  await first.set('snapshot', { ready: true }, { fingerprint: 'a' });
  const restored = new MetadataCache({ store, now: () => 1100 });
  assert.equal((await restored.get('snapshot', { fingerprint: 'a' })).value.ready, true);
  assert.equal(await restored.get('snapshot', { fingerprint: 'b' }), null);
  const key = [...values.keys()][0]; values.set(key, { unexpected: true });
  const corrupt = new MetadataCache({ store });
  assert.equal(await corrupt.get('snapshot', { fingerprint: 'a' }), null);
  assert.equal(corrupt.snapshot().metrics.corruptions, 1);
});
