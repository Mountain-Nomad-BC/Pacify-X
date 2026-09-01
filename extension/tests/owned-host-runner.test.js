'use strict';

const assert = require('node:assert/strict');
const cp = require('node:child_process');
const { EventEmitter } = require('node:events');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { PassThrough } = require('node:stream');
const test = require('node:test');
const { acquireHostLease, listProcessesByCommandToken, runOwnedHostWorker } = require('../scripts/owned-host-runner');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-owned-host-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function fakeChild(pid = 43210) {
  const child = new EventEmitter(); child.pid = pid; child.stdout = new PassThrough(); child.stderr = new PassThrough();
  child.kill = signal => { child.killSignal = signal; setImmediate(() => child.emit('close', null, signal)); return true; };
  return child;
}

test('owned host lease prevents a second concurrent runner and releases by token', t => {
  const lockPath = path.join(fixture(t), 'host.lock.json');
  const lease = acquireHostLease({ lockPath });
  assert.throws(() => acquireHostLease({ lockPath }), /owned-host-already-running/);
  lease.release();
  const replacement = acquireHostLease({ lockPath }); replacement.release();
  assert.equal(fs.existsSync(lockPath), false);
});

test('rejected duplicate process allocates no temporary or evidence namespace', async t => {
  const root = fixture(t);
  const lockPath = path.join(root, 'host.lock.json');
  const reportPath = path.join(root, 'duplicate-report.json');
  const outputPath = path.join(root, 'duplicate-output');
  const duplicateRoot = path.join(root, 'duplicate-root');
  const runnerPath = path.resolve(__dirname, '../scripts/owned-host-runner.js');
  const walkPath = path.resolve(__dirname, '../scripts/run-isolated-current-source-walk.js');
  const ownerSource = [
    "const { acquireHostLease } = require(process.argv[1]);",
    "const lease = acquireHostLease({ lockPath: process.argv[2] });",
    "process.stdout.write('READY\\n');",
    "process.stdin.resume();",
    "process.stdin.once('end', () => { lease.release(); });"
  ].join('');
  const owner = cp.spawn(process.execPath, ['-e', ownerSource, runnerPath, lockPath], {
    shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']
  });
  t.after(() => { if (owner.exitCode === null) owner.kill(); });

  let ownerStdout = '';
  let ownerStderr = '';
  owner.stdout.on('data', chunk => { ownerStdout += chunk.toString('utf8'); });
  owner.stderr.on('data', chunk => { ownerStderr += chunk.toString('utf8'); });
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`owner-ready-timeout:${ownerStderr}`)), 5000);
    const observe = () => {
      if (!ownerStdout.includes('READY\n')) return;
      clearTimeout(timeout);
      owner.stdout.off('data', observe);
      resolve();
    };
    owner.stdout.on('data', observe);
    owner.once('exit', code => {
      if (!ownerStdout.includes('READY\n')) {
        clearTimeout(timeout);
        reject(new Error(`owner-exited-before-ready:${code}:${ownerStderr}`));
      }
    });
  });

  const duplicateSource = [
    "const fs = require('node:fs');",
    "const { acquireWalkOwnership } = require(process.argv[1]);",
    "const [lockPath, reportPath, outputPath, duplicateRoot] = process.argv.slice(2);",
    "let rejection = '';",
    "try { acquireWalkOwnership({ lockPath, makeTemporaryRoot: () => { fs.mkdirSync(duplicateRoot); return duplicateRoot; } }); }",
    "catch (error) { rejection = String(error && error.message || error); }",
    "const result = { rejection, lock_present: fs.existsSync(lockPath), report_present: fs.existsSync(reportPath), output_present: fs.existsSync(outputPath), duplicate_root_present: fs.existsSync(duplicateRoot) };",
    "process.stdout.write(JSON.stringify(result));",
    "process.exit(rejection.startsWith('owned-host-already-running:') ? 0 : 3);"
  ].join('');
  const duplicate = cp.spawnSync(process.execPath, [
    '-e', duplicateSource, walkPath, lockPath, reportPath, outputPath, duplicateRoot
  ], { shell: false, windowsHide: true, encoding: 'utf8', timeout: 5000 });

  assert.equal(duplicate.status, 0, duplicate.stderr);
  const result = JSON.parse(duplicate.stdout);
  assert.match(result.rejection, /^owned-host-already-running:pid-/);
  assert.equal(result.lock_present, true);
  assert.equal(result.report_present, false);
  assert.equal(result.output_present, false);
  assert.equal(result.duplicate_root_present, false);

  owner.stdin.end();
  const ownerExit = await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`owner-release-timeout:${ownerStderr}`)), 5000);
    owner.once('exit', code => { clearTimeout(timeout); resolve(code); });
  });
  assert.equal(ownerExit, 0, ownerStderr);
  assert.equal(fs.existsSync(lockPath), false);
  const replacement = acquireHostLease({ lockPath });
  replacement.release();
});

test('owned host worker records one PID and verifies normal closure', async t => {
  const root = fixture(t); const child = fakeChild();
  const spawn = () => { setImmediate(() => child.emit('close', 0, null)); return child; };
  let retained;
  const result = await runOwnedHostWorker({
    scriptPath: 'worker.js', childFlag: '--child', configPath: 'config.json', cwd: root,
    lockPath: path.join(root, 'host.lock.json'), spawn, timeoutMs: 1000, onReceipt: value => { retained = { ...value }; }
  });
  assert.equal(result.receipt.worker_pid, child.pid);
  assert.equal(result.receipt.worker_exit_verified, true);
  assert.equal(result.receipt.status, 'completed');
  assert.equal(retained.worker_exit_verified, true);
  assert.equal(process.listenerCount('SIGINT') >= 0, true);
});

test('owned host worker consumes and releases a pre-acquired owner lease', async t => {
  const root = fixture(t); const child = fakeChild();
  const lockPath = path.join(root, 'host.lock.json');
  const lease = acquireHostLease({ lockPath });
  const spawn = () => { setImmediate(() => child.emit('close', 0, null)); return child; };

  const result = await runOwnedHostWorker({
    lease, scriptPath: 'worker.js', childFlag: '--child', configPath: 'config.json', cwd: root,
    spawn, timeoutMs: 1000
  });

  assert.equal(result.receipt.status, 'completed');
  assert.equal(fs.existsSync(lockPath), false);
});

test('owned host timeout terminates only the registered child and verifies its exit', async t => {
  const root = fixture(t); const child = fakeChild(45678); const terminated = []; let retained;
  await assert.rejects(runOwnedHostWorker({
    scriptPath: 'worker.js', childFlag: '--child', configPath: 'config.json', cwd: root,
    lockPath: path.join(root, 'host.lock.json'), spawn: () => child, timeoutMs: 5,
    terminate: async target => { terminated.push(target.pid); target.emit('close', null, 'SIGTERM'); return true; },
    onReceipt: value => { retained = { ...value }; }
  }), /owned-host-timeout/);
  assert.deepEqual(terminated, [child.pid]);
  assert.equal(retained.status, 'timed_out');
  assert.equal(retained.worker_exit_verified, true);
  assert.equal(retained.termination_reason, 'timeout');
  assert.equal(retained.termination_verified, true);
  assert.equal(retained.process_tree_closed_verified, true);
  assert.equal(fs.existsSync(path.join(root, 'host.lock.json')), false);
});

test('dead same-host lease is the only stale lease reclaimed', t => {
  const lockPath = path.join(fixture(t), 'host.lock.json');
  fs.writeFileSync(lockPath, `${JSON.stringify({ schema_version: 'px.owned-host-lease/1.0', token: 'stale', pid: 99999, hostname: os.hostname() })}\n`, 'utf8');
  const lease = acquireHostLease({ lockPath, probe: () => { const error = new Error('dead'); error.code = 'ESRCH'; throw error; } });
  lease.release(); assert.equal(fs.existsSync(lockPath), false);
});

test('unique profile reconciliation terminates and verifies only exact owned residual PIDs', async t => {
  const root = fixture(t); const child = fakeChild(47000); let scans = 0; const terminated = [];
  const result = await runOwnedHostWorker({
    scriptPath: 'worker.js', childFlag: '--child', configPath: 'config.json', cwd: root,
    lockPath: path.join(root, 'host.lock.json'), spawn: () => { setImmediate(() => child.emit('close', 0)); return child; }, timeoutMs: 1000,
    ownershipToken: path.join(root, 'unique-user-data'),
    findOwnedProcesses: async () => (++scans === 1 ? [48111, 48112] : []),
    terminatePid: async pid => { terminated.push(pid); return true; }
  });
  assert.deepEqual(terminated, [48111, 48112]);
  assert.deepEqual(result.receipt.residual_owned_pids_before, [48111, 48112]);
  assert.deepEqual(result.receipt.residual_owned_pids_after, []);
  assert.equal(result.receipt.process_tree_closed_verified, true);
});

test('Windows process reconciliation parses only bounded numeric matches', () => {
  const pids = listProcessesByCommandToken('C:/unique/profile', {
    platform: 'win32', spawnSync: (_command, _args, options) => {
      assert.equal(options.shell, false); assert.equal(options.env.PX_PROCESS_TOKEN, 'C:/unique/profile');
      return { status: 0, stdout: '[48111,48112]' };
    }
  });
  assert.deepEqual(pids, [48111, 48112]);
});
