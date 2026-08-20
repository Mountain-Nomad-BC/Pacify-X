'use strict';
const assert = require('node:assert/strict'); const fs = require('fs'); const os = require('os'); const path = require('path'); const test = require('node:test');
const { metadataSnapshot, EnvironmentLifecycleManager } = require('../src/environmentLifecycleManager');
function fixture() { return fs.mkdtempSync(path.join(os.tmpdir(), 'px-env-life-')); }

test('active virtual environments and externally owned tools fail closed', t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true })); const env = path.join(root, '.venv'); fs.mkdirSync(env); fs.writeFileSync(path.join(env, 'pyvenv.cfg'), 'version=3.13');
  const manager = new EnvironmentLifecycleManager(root); assert.equal(manager.preview({ id: 'env', kind: 'python-venv', path: env, active: true }).reason, 'resource-active-or-selected');
  assert.equal(manager.preview({ id: 'python', resource_type: 'system-tool', executable: 'C:/Python/python.exe' }).reason, 'externally-owned-system-tool');
});
test('environment quarantine requires exact target and consumer-impact acknowledgement', t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true })); const target = path.join(root, '.env'); fs.writeFileSync(target, 'OPENAI_API_KEY=secret-never-in-receipt\n');
  const manager = new EnvironmentLifecycleManager(root); const preview = manager.preview({ id: 'env-file:one', kind: 'local-environment', path: target, variables: [{ name: 'OPENAI_API_KEY', consumers: [{ path: 'provider.js' }] }] }, 'archive');
  assert.equal(preview.allowed, true); assert.throws(() => manager.execute(preview.token, { approved: true, exact_target: target }), /consumer-impact/);
  assert.throws(() => manager.execute(preview.token, { approved: true, exact_target: `${target}.wrong`, consumer_impact_acknowledged: true }), /exact-target/);
  const receipt = manager.execute(preview.token, { approved: true, exact_target: target, consumer_impact_acknowledged: true });
  assert.equal(fs.existsSync(target), false); assert.equal(receipt.disposition, 'quarantined-reversible'); assert.doesNotMatch(JSON.stringify(receipt), /secret-never-in-receipt/); assert.equal(fs.existsSync(path.join(root, receipt.destination_relative)), true);
});
test('immediate pre-move snapshot rejects changed targets and retains the source', t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true })); const target = path.join(root, '.venv'); fs.mkdirSync(target); fs.writeFileSync(path.join(target, 'pyvenv.cfg'), 'version=3.13');
  const manager = new EnvironmentLifecycleManager(root); const preview = manager.preview({ id: 'env', kind: 'python-venv', path: target, active: false }); fs.writeFileSync(path.join(target, 'changed.txt'), 'changed');
  assert.throws(() => manager.execute(preview.token, { approved: true, exact_target: target }), /changed after preview/); assert.equal(fs.existsSync(target), true);
});
test('root targets, escapes, and symbolic links are never lifecycle candidates', t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true })); assert.throws(() => metadataSnapshot(root, root), /outside or equal/); assert.throws(() => metadataSnapshot(path.dirname(root), root), /outside or equal/);
  const real = path.join(root, 'real'); const link = path.join(root, 'link'); fs.mkdirSync(real);
  try { fs.symlinkSync(real, link, process.platform === 'win32' ? 'junction' : 'dir'); assert.throws(() => metadataSnapshot(link, root), /symbolic link|junction/); } catch (error) { if (!/privilege|permitted|symbolic link|junction/i.test(error.message)) throw error; }
});
test('a lexical child reached through a parent junction is rejected', t => {
  const fixtureRoot = fixture(); t.after(() => fs.rmSync(fixtureRoot, { recursive: true, force: true }));
  const admitted = path.join(fixtureRoot, 'admitted'); const outside = path.join(fixtureRoot, 'outside'); fs.mkdirSync(admitted); fs.mkdirSync(outside); fs.writeFileSync(path.join(outside, 'data.txt'), 'outside');
  const alias = path.join(admitted, 'alias');
  try { fs.symlinkSync(outside, alias, process.platform === 'win32' ? 'junction' : 'dir'); assert.throws(() => metadataSnapshot(path.join(alias, 'data.txt'), admitted), /symbolic link|junction|escaped/); } catch (error) { if (!/privilege|permitted|symbolic link|junction|escaped/i.test(error.message)) throw error; }
});
