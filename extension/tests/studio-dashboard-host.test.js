'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { createPanelOrigin, exactCatalogRevision, revisionTreeSha256, validVersion } = require('../src/studioDashboardHost');

const HASH = 'a'.repeat(64);

test('panel origins never redirect a completed request to a replacement panel', async () => {
  const firstMessages = []; const secondMessages = [];
  const first = createPanelOrigin({ postMessage: async message => { firstMessages.push(message); return true; } });
  const second = createPanelOrigin({ postMessage: async message => { secondMessages.push(message); return true; } });
  first.dispose();
  assert.equal(await first.postMessage({ type: 'late-first-result' }), false);
  assert.equal(await second.postMessage({ type: 'second-result' }), true);
  assert.deepEqual(firstMessages, []);
  assert.deepEqual(secondMessages, [{ type: 'second-result' }]);
});

test('exact catalog selection reopens a hash-bound physical candidate without granting lifecycle authority', () => {
  const page = { items: [{
    id: 'studio-agent:agent:demo@1.0.0', kind: 'studio-agent-revision', identity: 'agent:demo', summary: 'Exact', effects: ['read'], tags: ['studio'],
    details: { agent_id: 'agent:demo', version: '1.0.0', studio_revision: true, revision_sha256: HASH, source_content_sha256: 'b'.repeat(64), lifecycle_authentication: { authenticated: true } }
  }] };
  const selected = exactCatalogRevision(page, { kind: 'agent', catalogKind: 'agents', recordId: page.items[0].id });
  assert.equal(selected.identity, 'agent:demo');
  assert.equal(selected.source_content_sha256, 'b'.repeat(64));
  assert.throws(() => exactCatalogRevision({ items: [page.items[0], page.items[0]] }, { kind: 'agent', catalogKind: 'agents', recordId: page.items[0].id }), /stale-or-ambiguous/);
  const candidate = { ...page.items[0], details: { ...page.items[0].details, studio_revision: true, lifecycle_authentication: { authenticated: false, status: 'candidate' } } };
  assert.equal(exactCatalogRevision({ items: [candidate] }, { kind: 'agent', catalogKind: 'agents', recordId: candidate.id }).identity, 'agent:demo');
  assert.throws(() => exactCatalogRevision({ items: [{ ...candidate, details: { ...candidate.details, studio_revision: false } }] }, { kind: 'agent', catalogKind: 'agents', recordId: candidate.id }), /authentication-invalid/);
  assert.throws(() => exactCatalogRevision(page, { kind: 'workflow', catalogKind: 'workflows', recordId: page.items[0].id }), /kind-invalid/);
});

test('revision tree commitment is deterministic, content-sensitive, bounded, and link-refusing', t => {
  const project = fs.mkdtempSync(path.join(os.tmpdir(), 'px-studio-dashboard-host-'));
  t.after(() => fs.rmSync(project, { recursive: true, force: true }));
  const revision = path.join(project, '.engineering-bootstrap', 'studios', 'agents', 'demo', 'revisions', '1.0.0');
  fs.mkdirSync(path.join(revision, 'payload'), { recursive: true });
  fs.writeFileSync(path.join(revision, 'record.json'), '{"version":"1.0.0"}\n');
  fs.writeFileSync(path.join(revision, 'payload', 'agent.json'), '{"agent_id":"agent:demo"}\n');
  const first = revisionTreeSha256(revision, project);
  assert.match(first, /^[a-f0-9]{64}$/);
  assert.equal(revisionTreeSha256(revision, project), first);
  fs.writeFileSync(path.join(revision, 'payload', 'agent.json'), '{"agent_id":"agent:changed"}\n');
  assert.notEqual(revisionTreeSha256(revision, project), first);
  assert.throws(() => revisionTreeSha256(project, project), /outside-project/);

  const link = path.join(revision, 'payload', 'link.json');
  try {
    fs.symlinkSync(path.join(revision, 'record.json'), link, 'file');
    assert.throws(() => revisionTreeSha256(revision, project), /link-refused/);
  } catch (error) {
    if (!['EPERM', 'EACCES', 'UNKNOWN'].includes(error?.code)) throw error;
  }

  assert.equal(validVersion('1.0.0-rc.1'), true);
  assert.equal(validVersion('1.0.0-RC.1'), false);
});
