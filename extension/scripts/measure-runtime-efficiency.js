'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { performance } = require('node:perf_hooks');
const { scanEnvironmentAsync } = require('../src/discoveryManager');
const { WorkGovernor } = require('../src/workGovernor');

const profiles = Object.freeze([
  { id: 'current', files: 200, depth: 3 },
  { id: '2x', files: 400, depth: 4 },
  { id: '5x', files: 1000, depth: 5 },
  { id: 'pathological', files: 2500, depth: 7 }
]);

function buildFixture(root, profile) {
  for (let index = 0; index < profile.files; index += 1) {
    const parts = Array.from({ length: index % profile.depth }, (_value, part) => `d${part}`);
    const directory = path.join(root, ...parts); fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, `f-${index}.txt`), `${index}\n`, 'utf8');
  }
  const environment = path.join(root, '.venv');
  fs.mkdirSync(path.join(environment, 'Lib', 'site-packages', 'fixture-1.0.dist-info'), { recursive: true });
  fs.writeFileSync(path.join(environment, 'pyvenv.cfg'), 'version = 3.13.7\n', 'utf8');
}

async function measureScan(root, profile) {
  let last = performance.now(); let maxLag = 0; let ticks = 0;
  const timer = setInterval(() => {
    const current = performance.now(); maxLag = Math.max(maxLag, current - last - 10); last = current; ticks += 1;
  }, 10);
  const started = performance.now();
  const result = await scanEnvironmentAsync([root], { currentPythonVersion: 'Python 3.13.7' });
  const duration = performance.now() - started; clearInterval(timer);
  return {
    profile: profile.id, fixture_files: profile.files,
    observed_entries: result.tree.entries.length, capped: result.tree.capped,
    duration_ms: Number(duration.toFixed(3)), event_loop_max_lag_ms: Number(maxLag.toFixed(3)), heartbeat_ticks: ticks,
    budget: { duration_ms: 5000, event_loop_max_lag_ms: 250 },
    passed: duration < 5000 && maxLag < 250 && !result.tree.capped
  };
}

async function measure() {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'px-efficiency-load-'));
  try {
    const scans = [];
    for (const profile of profiles) {
      const root = path.join(temporary, profile.id); fs.mkdirSync(root); buildFixture(root, profile);
      scans.push(await measureScan(root, profile));
    }
    const governor = new WorkGovernor(); let executions = 0; let release;
    const gate = new Promise(resolve => { release = resolve; });
    const requests = Array.from({ length: 100 }, () => governor.run('load-single-flight', async () => { executions += 1; await gate; return true; }));
    await new Promise(resolve => setImmediate(resolve)); release(); await Promise.all(requests);
    const governorReport = governor.snapshot(); governor.dispose();
    return {
      schema_version: 'px.runtime-efficiency-load/1.0', generated_utc: new Date().toISOString(),
      profiles: scans,
      duplicate_load: { requests: 100, executions, joins: governorReport.metrics.joins, passed: executions === 1 && governorReport.metrics.joins === 99 },
      acceptance: { all_profiles_within_budget: scans.every(item => item.passed), duplicate_load_bounded: executions === 1 && governorReport.metrics.joins === 99 },
      authority: 'CPU-authoritative filesystem measurement in owned worker; no network, provider, credential, or destructive effect'
    };
  } finally { fs.rmSync(temporary, { recursive: true, force: true }); }
}

async function main() {
  const report = await measure();
  const target = path.join(__dirname, '..', 'evidence', 'runtime-efficiency-load.json');
  fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  if (!report.acceptance.all_profiles_within_budget || !report.acceptance.duplicate_load_bounded) process.exitCode = 1;
}

if (require.main === module) main().catch(error => { process.stderr.write(`${error.stack || error.message}\n`); process.exitCode = 1; });
module.exports = { profiles, buildFixture, measureScan, measure };
