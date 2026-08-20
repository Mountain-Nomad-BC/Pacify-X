'use strict';

const crypto = require('crypto');
const cp = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { terminateProcessTreeAsync } = require('../src/processTree');

const HOST_LOCK = path.join(os.tmpdir(), 'pacify-x-vscode-host-smoke.lock.json');
const MAX_CAPTURE = 4 * 1024 * 1024;

function pidAlive(pid, probe = process.kill) {
  try { probe(pid, 0); return true; } catch (error) { return error?.code === 'EPERM'; }
}

function listProcessesByCommandToken(token, options = {}) {
  if (!token) return [];
  const spawnSync = options.spawnSync || cp.spawnSync;
  if ((options.platform || process.platform) === 'win32') {
    const script = "$needle=$env:PX_PROCESS_TOKEN; @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($needle) } | Select-Object -ExpandProperty ProcessId) | ConvertTo-Json -Compress";
    const result = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
      windowsHide: true, shell: false, encoding: 'utf8', timeout: 10_000,
      env: { ...process.env, PX_PROCESS_TOKEN: String(token) }
    });
    if (result.error || result.status !== 0) throw new Error('owned-host-process-reconciliation-failed');
    const text = String(result.stdout || '').trim(); if (!text) return [];
    const parsed = JSON.parse(text); return (Array.isArray(parsed) ? parsed : [parsed]).map(Number).filter(pid => Number.isSafeInteger(pid) && pid > 0 && pid !== process.pid);
  }
  const result = spawnSync('ps', ['-eo', 'pid=,args='], { shell: false, encoding: 'utf8', timeout: 10_000 });
  if (result.error || result.status !== 0) throw new Error('owned-host-process-reconciliation-failed');
  return String(result.stdout || '').split(/\r?\n/).filter(line => line.includes(String(token))).map(line => Number(line.trim().split(/\s+/, 1)[0])).filter(pid => Number.isSafeInteger(pid) && pid > 0 && pid !== process.pid);
}

async function terminateRegisteredPid(pid, options = {}) {
  if (!Number.isSafeInteger(pid) || pid <= 0 || pid === process.pid) return false;
  if ((options.platform || process.platform) !== 'win32') {
    try { process.kill(pid, 'SIGTERM'); return true; } catch { return false; }
  }
  const spawn = options.spawn || cp.spawn;
  return new Promise(resolve => {
    let settled = false; const finish = value => { if (settled) return; settled = true; resolve(value); };
    try {
      const child = spawn('taskkill', ['/pid', String(pid), '/t', '/f'], { windowsHide: true, shell: false, stdio: 'ignore' });
      child.once('error', () => finish(false)); child.once('close', code => finish(code === 0 || code === 128));
    } catch { finish(false); }
  });
}

function acquireHostLease(options = {}) {
  const lockPath = options.lockPath || HOST_LOCK;
  const token = crypto.randomUUID();
  const document = { schema_version: 'px.owned-host-lease/1.0', token, pid: process.pid, hostname: os.hostname(), acquired_utc: new Date().toISOString() };
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try { fs.writeFileSync(lockPath, `${JSON.stringify(document)}\n`, { encoding: 'utf8', flag: 'wx' }); break; }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      let existing;
      try { existing = JSON.parse(fs.readFileSync(lockPath, 'utf8')); } catch { throw new Error(`owned-host-lock-unreadable:${lockPath}`); }
      if (existing.hostname !== os.hostname() || pidAlive(Number(existing.pid), options.probe)) {
        throw new Error(`owned-host-already-running:pid-${existing.pid}`);
      }
      // Exact PACIFY-X-owned lock, same host, and its registered owner is dead.
      fs.unlinkSync(lockPath);
    }
  }
  let released = false;
  return { token, lockPath, release() {
    if (released) return; released = true;
    try {
      const current = JSON.parse(fs.readFileSync(lockPath, 'utf8'));
      if (current.token === token && current.pid === process.pid) fs.unlinkSync(lockPath);
    } catch {}
  } };
}

async function runOwnedHostWorker(options) {
  const lease = acquireHostLease(options);
  const started = Date.now();
  const receipt = {
    schema_version: 'px.owned-host-run/1.0', run_id: crypto.randomUUID(), owner_pid: process.pid,
    worker_pid: null, status: 'starting', started_utc: new Date(started).toISOString(),
    timeout_ms: Number(options.timeoutMs || 180_000), termination_requested: false,
    worker_exit_verified: false, exit_code: null, signal: null
  };
  const spawn = options.spawn || cp.spawn;
  let child; let timeout; let stdout = ''; let stderr = ''; let settled = false;
  const capture = (current, chunk) => `${current}${chunk.toString('utf8')}`.slice(-MAX_CAPTURE);
  const handlers = new Map();
  const reconcile = async () => {
    if (!options.ownershipToken) {
      receipt.residual_owned_pids_before = []; receipt.residual_owned_pids_after = [];
      receipt.process_tree_closed_verified = receipt.worker_exit_verified; return;
    }
    const find = options.findOwnedProcesses || (token => listProcessesByCommandToken(token));
    const terminatePid = options.terminatePid || terminateRegisteredPid;
    const before = await find(options.ownershipToken);
    receipt.residual_owned_pids_before = [...new Set(before.map(Number))].filter(pid => Number.isSafeInteger(pid) && pid > 0 && pid !== process.pid);
    receipt.reconciled_owned_pids = [];
    for (const pid of receipt.residual_owned_pids_before) if (await terminatePid(pid)) receipt.reconciled_owned_pids.push(pid);
    receipt.residual_owned_pids_after = await find(options.ownershipToken);
    receipt.process_tree_closed_verified = receipt.worker_exit_verified && receipt.residual_owned_pids_after.length === 0;
    if (!receipt.process_tree_closed_verified) throw new Error('owned-host-process-tree-not-closed');
  };
  try {
    child = spawn(process.execPath, [options.scriptPath, options.childFlag, options.configPath], {
      cwd: options.cwd, shell: false, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], env: options.env || process.env
    });
    receipt.worker_pid = Number(child.pid) || null; receipt.status = 'running';
    child.stdout?.on('data', chunk => { stdout = capture(stdout, chunk); options.stdout?.write?.(chunk); });
    child.stderr?.on('data', chunk => { stderr = capture(stderr, chunk); options.stderr?.write?.(chunk); });
    const requestTermination = async reason => {
      if (!child || receipt.worker_exit_verified || receipt.termination_requested) return;
      receipt.termination_requested = true; receipt.termination_reason = reason;
      receipt.termination_verified = await (options.terminate || terminateProcessTreeAsync)(child, { graceMs: 1500, verifyMs: 10_000 });
    };
    for (const signal of ['SIGINT', 'SIGTERM']) {
      const handler = () => { void requestTermination(`parent-${signal.toLowerCase()}`); };
      handlers.set(signal, handler); process.once(signal, handler);
    }
    const result = await new Promise((resolve, reject) => {
      const close = (code, signal) => {
        if (settled) return; settled = true; clearTimeout(timeout);
        receipt.worker_exit_verified = true; receipt.exit_code = code; receipt.signal = signal || null;
        resolve(code);
      };
      child.once('error', error => {
        if (settled) return; settled = true; clearTimeout(timeout);
        receipt.worker_exit_verified = !child.pid; reject(error);
      });
      child.once('close', close);
      timeout = setTimeout(() => {
        void requestTermination('timeout').then(() => {
          if (!settled) { settled = true; reject(new Error('owned-host-timeout-termination-unverified')); }
        });
      }, receipt.timeout_ms);
      timeout.unref?.();
    });
    await reconcile();
    receipt.status = result === 0 ? 'completed' : 'failed';
    if (result !== 0) throw new Error(`owned-host-worker-exit-${result}`);
    return { receipt, stdout, stderr };
  } catch (error) {
    if (receipt.residual_owned_pids_after === undefined) {
      try { await reconcile(); } catch (reconcileError) { receipt.reconciliation_error = String(reconcileError?.message || reconcileError).slice(0, 200); }
    }
    receipt.status = receipt.termination_requested ? 'terminated' : 'failed';
    receipt.error = String(error?.message || error).slice(0, 500);
    error.lifecycleReceipt = receipt; throw error;
  } finally {
    clearTimeout(timeout);
    for (const [signal, handler] of handlers) process.removeListener(signal, handler);
    receipt.finished_utc = new Date().toISOString(); receipt.duration_ms = Date.now() - started;
    lease.release();
    options.onReceipt?.(receipt);
  }
}

module.exports = {
  HOST_LOCK, acquireHostLease, pidAlive, listProcessesByCommandToken,
  terminateRegisteredPid, runOwnedHostWorker
};
