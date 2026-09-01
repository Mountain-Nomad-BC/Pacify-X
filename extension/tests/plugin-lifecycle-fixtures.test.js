'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const test = require('node:test');

const root = path.resolve(__dirname, '..');
const generated = path.join(root, 'tests', 'generated', 'plugin-lifecycle');
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

test('canonical Plugin lifecycle fixture builder emits deterministic inert v1 and v2 VSIX packages', () => {
  const run = () => childProcess.execFileSync(process.execPath, [path.join(root, 'scripts', 'build-plugin-lifecycle-fixtures.js')], { cwd: root, encoding: 'utf8' });
  run();
  const receipt = JSON.parse(fs.readFileSync(path.join(generated, 'receipt.json'), 'utf8'));
  assert.equal(receipt.extension_id, 'px-owned.fixture');
  assert.deepEqual(receipt.artifacts.map(value => value.version), ['1.0.0', '2.0.0']);
  const first = receipt.artifacts.map(value => digest(path.join(root, value.path)));
  run();
  const second = receipt.artifacts.map(value => digest(path.join(root, value.path)));
  assert.deepEqual(second, first);
  for (const artifact of receipt.artifacts) {
    const bytes = fs.readFileSync(path.join(root, artifact.path));
    assert.equal(bytes.readUInt32LE(0), 0x04034b50);
    assert.equal(digest(path.join(root, artifact.path)), artifact.sha256);
    assert.ok(artifact.size > 500 && artifact.size < 10000);
  }
});

test('fixture activation sources are inert and version-bound', () => {
  for (const [directory, version] of [['v1', '1.0.0'], ['v2', '2.0.0']]) {
    const source = require(path.join(root, 'tests', 'fixtures', 'plugin-lifecycle', directory, 'extension.js'));
    assert.deepEqual(source.activate(), { fixture: 'px-owned.fixture', version });
    assert.equal(source.deactivate(), undefined);
  }
});

test('v2 fixture declares one deterministic inert conflict without activation authority', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, 'tests', 'fixtures', 'plugin-lifecycle', 'v2', 'package.json'), 'utf8'));
  assert.deepEqual(manifest.activationEvents, []);
  assert.deepEqual(manifest.contributes.commands, [{ command: 'pacifyX.openDashboard', title: 'PX Inert Conflict Fixture' }]);
});
