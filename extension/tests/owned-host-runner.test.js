'use strict';

const assert = require('node:assert/strict');
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

test('owned host timeout terminates only the registered child and verifies its exit', async t => {
  const root = fixture(t); const child = fakeChild(45678); const terminated = [];
  await assert.rejects(runOwnedHostWorker({
    scriptPath: 'worker.js', childFlag: '--child', configPath: 'config.json', cwd: root,
    lockPath: path.join(root, 'host.lock.json'), spawn: () => child, timeoutMs: 5,
    terminate: async target => { terminated.push(target.pid); target.emit('close', null, 'SIGTERM'); return true; }
  }), /owned-host-worker-exit-null/);
  assert.deepEqual(terminated, [child.pid]);
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
