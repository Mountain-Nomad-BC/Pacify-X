'use strict';

const cp = require('child_process');

function processTreeSpawnOptions(platform = process.platform) {
  return platform === 'win32' ? {} : { detached: true };
}

function terminateProcessTree(child, options = {}) {
  const pid = Number(child?.pid);
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  const platform = options.platform || process.platform;
  const signal = options.signal || 'SIGTERM';
  try {
    if (platform === 'win32') {
      const result = (options.spawnSync || cp.spawnSync)('taskkill', ['/pid', String(pid), '/t', '/f'], {
        windowsHide: true, shell: false, stdio: 'ignore', timeout: options.timeoutMs || 5000
      });
      if (!result.error && (result.status === 0 || result.status === 128)) return true;
    } else {
      (options.kill || process.kill)(-pid, signal);
      return true;
    }
  } catch {
    // Fall back to the direct child when the OS tree primitive is unavailable.
  }
  try { return child.kill(signal); } catch { return false; }
}

function terminateProcessTreeAsync(child, options = {}) {
  const pid = Number(child?.pid);
  if (!Number.isSafeInteger(pid) || pid <= 0) {
    try { return Promise.resolve(Boolean(child?.kill?.(options.signal || 'SIGTERM'))); } catch { return Promise.resolve(false); }
  }
  const platform = options.platform || process.platform;
  const signal = options.signal || 'SIGTERM';
  const graceMs = Math.max(0, Number(options.graceMs ?? 750));
  const verifyMs = Math.max(graceMs + 1, Number(options.verifyMs ?? 5000));
  const spawn = options.spawn || cp.spawn;
  const kill = options.kill || process.kill;
  return new Promise(resolve => {
    let settled = false; let escalationTimer; let verifyTimer;
    const finish = value => {
      if (settled) return; settled = true;
      clearTimeout(escalationTimer); clearTimeout(verifyTimer); resolve(value);
    };
    child?.once?.('close', () => finish(true));
    child?.once?.('exit', () => finish(true));
    try { child?.kill?.(signal); } catch {}
    escalationTimer = setTimeout(() => {
      try {
        if (platform === 'win32') {
          const killer = spawn('taskkill', ['/pid', String(pid), '/t', '/f'], { windowsHide: true, shell: false, stdio: 'ignore' });
          killer.once?.('error', () => {});
        } else kill(-pid, 'SIGKILL');
      } catch {}
    }, graceMs);
    verifyTimer = setTimeout(() => finish(false), verifyMs);
    escalationTimer.unref?.(); verifyTimer.unref?.();
  });
}

module.exports = { processTreeSpawnOptions, terminateProcessTree, terminateProcessTreeAsync };
