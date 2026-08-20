'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const { findEngineRoot, isEngineRoot } = require('./pxBridge');
const { nonBillableEnvironment } = require('./contextBridge');
const { processTreeSpawnOptions, terminateProcessTree } = require('./processTree');

function runValidation({ pythonPath = 'python', engineRoot, timeoutMs = 180000, signal }) {
  return new Promise(resolve => {
    if (!isEngineRoot(engineRoot)) {
      resolve({ status: 'blocked', exitCode: null, detail: 'Pacify-X engine root unavailable.', output: '' });
      return;
    }
    const child = cp.spawn(pythonPath, ['-m', 'runtime.cli', 'validate'], {
      cwd: engineRoot, windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe'],
      ...processTreeSpawnOptions(),
      env: { ...nonBillableEnvironment(), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' }
    });
    let stdout = ''; let stderr = ''; let timedOut = false;
    const onAbort = () => { terminateProcessTree(child); };
    const timer = setTimeout(() => { timedOut = true; terminateProcessTree(child); }, timeoutMs);
    signal?.addEventListener?.('abort', onAbort, { once: true });
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => { stdout = (stdout + chunk).slice(-240000); });
    child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-120000); });
    child.on('error', error => { clearTimeout(timer); signal?.removeEventListener?.('abort', onAbort); resolve({ status: 'failed', exitCode: null, detail: error.message, output: stderr, timedOut, cancelled: Boolean(signal?.aborted) }); });
    child.on('close', code => {
      clearTimeout(timer); signal?.removeEventListener?.('abort', onAbort);
      resolve({
        status: code === 0 && !timedOut && !signal?.aborted ? 'passed' : signal?.aborted ? 'cancelled' : 'failed', exitCode: code,
        detail: signal?.aborted ? 'Pacify-X validation was cancelled or superseded.' : timedOut ? 'Pacify-X validation timed out.' : code === 0 ? 'Pacify-X validation passed.' : 'Pacify-X validation reported failures.',
        output: [stdout, stderr].filter(Boolean).join('\n').trim(), timedOut, cancelled: Boolean(signal?.aborted),
        engineRoot, completedAt: new Date().toISOString()
      });
    });
  });
}

function isPathWithin(candidate, roots) {
  if (!candidate) return false;
  const resolved = path.resolve(candidate);
  return roots.filter(Boolean).some(root => {
    const base = path.resolve(root); const relative = path.relative(base, resolved);
    return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
  });
}

function fileIdentity(stat) {
  return `${Number(stat.dev)}:${Number(stat.ino)}:${Number(stat.size)}:${Math.trunc(stat.mtimeMs)}`;
}

function resolveAdmittedFile(candidate, roots) {
  if (!candidate || !Array.isArray(roots)) throw new Error('file-path-missing');
  const requested = path.resolve(candidate);
  for (const rootValue of roots.filter(Boolean)) {
    const root = path.resolve(rootValue);
    const relative = path.relative(root, requested);
    if (relative.startsWith('..') || path.isAbsolute(relative)) continue;
    try {
      const rootReal = fs.realpathSync.native(root);
      let cursor = root;
      for (const component of relative.split(path.sep).filter(Boolean)) {
        cursor = path.join(cursor, component);
        if (fs.lstatSync(cursor).isSymbolicLink()) throw new Error('file-path-alias-rejected');
      }
      const real = fs.realpathSync.native(requested);
      const realRelative = path.relative(rootReal, real);
      if (realRelative.startsWith('..') || path.isAbsolute(realRelative)) throw new Error('file-realpath-escaped-root');
      const stat = fs.statSync(real);
      if (!stat.isFile()) throw new Error('file-path-not-file');
      return { requested, root, rootReal, real, identity: fileIdentity(stat) };
    } catch (error) {
      if (String(error?.message || '').startsWith('file-')) throw error;
    }
  }
  throw new Error('file-path-not-admitted');
}

function revalidateAdmittedFile(guard) {
  const current = resolveAdmittedFile(guard.requested, [guard.root]);
  if (current.real !== guard.real || current.rootReal !== guard.rootReal || current.identity !== guard.identity) {
    throw new Error('file-path-changed-after-validation');
  }
  return current;
}

module.exports = { findEngineRoot, isEngineRoot, runValidation, isPathWithin, resolveAdmittedFile, revalidateAdmittedFile };
