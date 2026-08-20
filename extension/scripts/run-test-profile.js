'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { requiredBrowserLanes } = require('../tests/browser-lane');

const root = path.resolve(__dirname, '..');
const testsRoot = path.join(root, 'tests');
const isolated = Object.freeze({
  'ui-e2e': Object.freeze(['dashboard-e2e.test.js', 'sidebar-e2e.test.js']),
  performance: Object.freeze(['runtime-efficiency-load.test.js'])
});

function testFiles() {
  return fs.readdirSync(testsRoot).filter(name => name.endsWith('.test.js')).sort();
}

function profile(name) {
  const all = testFiles();
  const isolatedNames = new Set(Object.values(isolated).flat());
  if (name === 'unit') return { name, concurrency: 4, files: all.filter(file => !isolatedNames.has(file)) };
  if (Object.hasOwn(isolated, name)) return { name, concurrency: 1, files: isolated[name].filter(file => all.includes(file)) };
  throw new Error(`unknown-test-profile:${name}`);
}

function run(name) {
  const selected = profile(name);
  if (!selected.files.length) throw new Error(`empty-test-profile:${name}`);
  const args = ['--test', `--test-concurrency=${selected.concurrency}`, ...selected.files.map(file => path.join('tests', file))];
  const lanes = name === 'ui-e2e' ? requiredBrowserLanes() : [null];
  const results = [];
  for (const lane of lanes) {
    const result = spawnSync(process.execPath, args, {
      cwd: root, stdio: 'inherit', windowsHide: true,
      env: { ...process.env, ...(lane ? { PX_UI_BROWSER: lane } : {}) }
    });
    if (result.error) throw result.error;
    results.push({ lane, exit_code: Number.isInteger(result.status) ? result.status : 1 });
  }
  if (name === 'ui-e2e') {
    const evidenceRoot = path.join(root, 'evidence');
    fs.mkdirSync(evidenceRoot, { recursive: true });
    fs.writeFileSync(path.join(evidenceRoot, 'browser-matrix.json'), `${JSON.stringify({
      schema_version: 'px.ui-browser-matrix/1.0', generated_utc: new Date().toISOString(),
      platform: process.platform, lanes: results, passed: results.every(item => item.exit_code === 0)
    }, null, 2)}\n`, 'utf8');
  }
  return results.every(item => item.exit_code === 0) ? 0 : 1;
}

if (require.main === module) process.exitCode = run(process.argv[2] || 'unit');

module.exports = { profile, run, testFiles };
