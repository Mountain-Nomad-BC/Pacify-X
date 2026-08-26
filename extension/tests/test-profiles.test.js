'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { profile, testFiles } = require('../scripts/run-test-profile');
const { requiredBrowserLanes, resolveBrowserLane } = require('./browser-lane');

test('R02 extension test profiles isolate browser and performance campaigns', () => {
  const all = testFiles();
  const unit = profile('unit');
  const browser = profile('ui-e2e');
  const performance = profile('performance');
  const assigned = [...unit.files, ...browser.files, ...performance.files];
  assert.deepEqual([...assigned].sort(), all);
  assert.equal(new Set(assigned).size, all.length);
  assert.equal(unit.concurrency, 4);
  assert.equal(browser.concurrency, 1);
  assert.equal(performance.concurrency, 1);
  assert.deepEqual(browser.files, ['dashboard-e2e.test.js', 'sidebar-e2e.test.js']);
  for (const file of browser.files) {
    const source = fs.readFileSync(path.join(__dirname, file), 'utf8');
    assert.doesNotMatch(source, /\bskip\s*:/, `${file} must not skip a required browser/platform lane`);
    assert.match(source, /resolveBrowserLane/, `${file} must use the governed platform browser resolver`);
  }
  assert.deepEqual(requiredBrowserLanes(), process.platform === 'win32' ? ['edge', 'chrome'] : process.platform === 'darwin' ? ['chrome'] : ['chromium']);
  assert.ok(resolveBrowserLane().executablePath);
  assert.deepEqual(performance.files, ['runtime-efficiency-load.test.js']);
  assert.throws(() => profile('unknown'), /unknown-test-profile/);
});

test('governed dashboard section owns isolated host and physical outage regressions', () => {
  const registry = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'registry', 'test_profiles.json'), 'utf8'));
  const command = registry.sections['dashboard-extension'].command;
  for (const owner of [
    'tests/operational-ui-walk-installed-probe.test.js',
    'tests/isolated-current-source-walk.test.js',
    'tests/owned-engine-outage.test.js'
  ]) assert.ok(command.includes(owner), `dashboard-extension omits ${owner}`);
});
