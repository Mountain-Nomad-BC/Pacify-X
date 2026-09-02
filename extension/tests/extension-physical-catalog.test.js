'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createPhysicalExtensionCatalog, readPhysicalExtensionCatalog } = require('../src/extensionPhysicalCatalog');

function manifest(root, directory, publisher, name, version, extra = {}) {
  const target = path.join(root, directory);
  fs.mkdirSync(target, { recursive: true });
  fs.writeFileSync(path.join(target, 'package.json'), JSON.stringify({ publisher, name, version, ...extra }));
  return target;
}

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-physical-catalog-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const current = manifest(root, 'pacify-x.control-plane-0.6.77', 'pacify-x', 'control-plane', '0.6.77');
  return { root, current };
}

test('physical identity supersedes stale loaded identity while preserving only exact activation and out-of-root extensions', t => {
  const { root, current } = fixture(t);
  const v1 = manifest(root, 'publisher.demo-1.0.0', 'Publisher', 'Demo', '1.0.0');
  const v2 = manifest(root, 'publisher.demo-2.0.0', 'Publisher', 'Demo', '2.0.0');
  fs.writeFileSync(path.join(root, '.obsolete'), JSON.stringify({ [path.basename(v1)]: true }));
  const loaded = { all: [
    { id: 'publisher.demo', extensionPath: v1, packageJSON: { publisher: 'Publisher', name: 'Demo', version: '1.0.0' }, isActive: true },
    { id: 'vscode.git', extensionPath: path.join(os.tmpdir(), 'vscode-builtin-git'), packageJSON: { version: '1.0.0', isBuiltin: true }, isActive: true }
  ] };
  const records = readPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: loaded });
  const demo = records.find(record => record.id === 'publisher.demo');
  assert.equal(demo.packageJSON.version, '2.0.0');
  assert.equal(demo.extensionPath, v2);
  assert.equal(demo.isActive, false);
  assert.equal(records.find(record => record.id === 'vscode.git').isActive, true);

  loaded.all[0] = { ...loaded.all[0], extensionPath: v2, packageJSON: { publisher: 'Publisher', name: 'Demo', version: '2.0.0' } };
  assert.equal(readPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: loaded }).find(record => record.id === 'publisher.demo').isActive, true);
});

test('dynamic catalog follows update, uninstall, and rollback disk state without accepting stale loaded records', t => {
  const { root, current } = fixture(t);
  const v1 = manifest(root, 'publisher.demo-1.0.0', 'publisher', 'demo', '1.0.0');
  const loaded = { all: [{ id: 'publisher.demo', extensionPath: v1, packageJSON: { version: '1.0.0' }, isActive: true }] };
  const catalog = createPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: loaded });
  assert.equal(catalog.getExtension('PUBLISHER.DEMO').packageJSON.version, '1.0.0');

  manifest(root, 'publisher.demo-2.0.0', 'publisher', 'demo', '2.0.0');
  fs.writeFileSync(path.join(root, '.obsolete'), JSON.stringify({ 'publisher.demo-1.0.0': true }));
  assert.equal(catalog.getExtension('publisher.demo').packageJSON.version, '2.0.0');

  fs.writeFileSync(path.join(root, '.obsolete'), JSON.stringify({ 'publisher.demo-1.0.0': true, 'publisher.demo-2.0.0': true }));
  assert.equal(catalog.getExtension('publisher.demo'), undefined);

  fs.writeFileSync(path.join(root, '.obsolete'), JSON.stringify({ 'publisher.demo-1.0.0': true, 'publisher.demo-2.0.0': false }));
  assert.equal(catalog.getExtension('publisher.demo').packageJSON.version, '2.0.0');
});

test('catalog bounds transient obsolete JSON retries while VS Code publishes its control file', t => {
  const { root, current } = fixture(t);
  manifest(root, 'publisher.demo-1.0.0', 'publisher', 'demo', '1.0.0');
  fs.writeFileSync(path.join(root, '.obsolete'), '{}');
  const originalRead = fs.readFileSync;
  let obsoleteReads = 0;
  fs.readFileSync = function patchedRead(file, ...args) {
    if (path.basename(String(file)) === '.obsolete' && obsoleteReads++ < 2) return '{';
    return originalRead.call(this, file, ...args);
  };
  t.after(() => { fs.readFileSync = originalRead; });
  const records = readPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: { all: [] } });
  assert.equal(records.some(record => record.id === 'publisher.demo'), true);
  assert.equal(obsoleteReads, 3);
});

test('catalog fails closed on current identity ambiguity, malformed control data, and bounded-entry overflow', t => {
  const { root, current } = fixture(t);
  manifest(root, 'publisher.demo-a', 'publisher', 'demo', '1.0.0');
  manifest(root, 'publisher.demo-b', 'publisher', 'demo', '2.0.0');
  assert.throws(() => readPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: { all: [] } }), /identity-ambiguous:publisher\.demo/);
  fs.writeFileSync(path.join(root, '.obsolete'), '{');
  assert.throws(() => readPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: { all: [] } }), /obsolete-invalid-json/);
  fs.writeFileSync(path.join(root, '.obsolete'), '[]');
  assert.throws(() => readPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: { all: [] } }), /obsolete-invalid-shape/);
  fs.writeFileSync(path.join(root, '.obsolete'), '{}');
  assert.throws(() => readPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: { all: [] }, maxEntries: 1 }), /entry-limit-exceeded/);
});

test('catalog refuses linked extension entries and linked manifests', async t => {
  const { root, current } = fixture(t);
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'px-physical-catalog-link-target-'));
  t.after(() => fs.rmSync(outside, { recursive: true, force: true }));
  fs.writeFileSync(path.join(outside, 'package.json'), JSON.stringify({ publisher: 'publisher', name: 'linked', version: '1.0.0' }));
  try { fs.symlinkSync(outside, path.join(root, 'publisher.linked-1.0.0'), process.platform === 'win32' ? 'junction' : 'dir'); }
  catch (error) { t.skip(`directory links unavailable: ${error.code || error.message}`); return; }
  assert.throws(() => readPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: { all: [] } }), /entry-link-refused/);
});

test('catalog refuses oversized manifests before parsing', t => {
  const { root, current } = fixture(t);
  const target = path.join(root, 'publisher.large-1.0.0');
  fs.mkdirSync(target);
  fs.writeFileSync(path.join(target, 'package.json'), '{"publisher":"publisher","name":"large","version":"1.0.0","padding":"0123456789"}');
  assert.throws(() => readPhysicalExtensionCatalog({ currentExtensionPath: current, loadedExtensions: { all: [] }, maxManifestBytes: 32 }), /manifest-oversized/);
});
