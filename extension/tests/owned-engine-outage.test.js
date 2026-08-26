'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { beginOwnedEngineOutage, validateOwnedEngine } = require('../scripts/owned-engine-outage');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pacify-x-outage-test-'));
  const engine = path.join(root, 'engine');
  const token = path.join(root, 'user-data');
  fs.mkdirSync(path.join(engine, 'runtime'), { recursive: true });
  fs.mkdirSync(token, { recursive: true });
  fs.writeFileSync(path.join(engine, 'runtime', 'cli.py'), 'print("cli")\n');
  fs.writeFileSync(path.join(engine, 'runtime', 'dashboard_api.py'), 'print("dashboard")\n');
  fs.writeFileSync(path.join(root, '.pacify-x-owned-ephemeral.json'), `${JSON.stringify({ schema_version: 'px.owned-host-workspace/1.0', owner: 'PACIFY-X', classification: 'ephemeral' })}\n`);
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { root, engine, token };
}

test('owned engine outage displaces only the disposable runtime and restores exact bytes idempotently', t => {
  const { engine, token } = fixture(t);
  const before = fs.readFileSync(path.join(engine, 'runtime', 'dashboard_api.py'), 'utf8');
  const outage = beginOwnedEngineOutage(engine, token);
  assert.equal(fs.existsSync(path.join(engine, 'runtime')), false);
  assert.equal(fs.existsSync(path.join(engine, '.px-operational-fault-runtime')), true);
  const restored = outage.restore();
  assert.equal(restored.restored, true);
  assert.equal(fs.readFileSync(path.join(engine, 'runtime', 'dashboard_api.py'), 'utf8'), before);
  assert.equal(outage.restore(), restored);
});

test('owned engine outage rejects an engine outside the token-owned root', t => {
  const left = fixture(t); const right = fixture(t);
  assert.throws(() => validateOwnedEngine(left.engine, right.token), /owned-engine-outage-boundary-mismatch/);
  assert.equal(fs.existsSync(path.join(left.engine, 'runtime')), true);
});

test('owned engine outage rejects a linked runtime before mutation', t => {
  const { root, engine, token } = fixture(t);
  const realRuntime = path.join(root, 'real-runtime');
  fs.renameSync(path.join(engine, 'runtime'), realRuntime);
  try { fs.symlinkSync(realRuntime, path.join(engine, 'runtime'), process.platform === 'win32' ? 'junction' : 'dir'); }
  catch (error) {
    fs.renameSync(realRuntime, path.join(engine, 'runtime'));
    if (['EPERM', 'EACCES', 'UNKNOWN'].includes(error?.code)) return t.skip(`directory links unavailable: ${error.code}`);
    throw error;
  }
  assert.throws(() => beginOwnedEngineOutage(engine, token), /owned-engine-outage-runtime-invalid/);
  assert.equal(fs.existsSync(path.join(engine, '.px-operational-fault-runtime')), false);
});
