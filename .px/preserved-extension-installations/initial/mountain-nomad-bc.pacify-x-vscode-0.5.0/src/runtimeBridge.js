'use strict';

const cp = require('child_process');
const path = require('path');
const { findEngineRoot, isEngineRoot } = require('./pxBridge');
const { nonBillableEnvironment } = require('./contextBridge');

function runValidation({ pythonPath = 'python', engineRoot, timeoutMs = 180000 }) {
  return new Promise(resolve => {
    if (!isEngineRoot(engineRoot)) {
      resolve({ status: 'blocked', exitCode: null, detail: 'Pacify-X engine root unavailable.', output: '' });
      return;
    }
    const child = cp.spawn(pythonPath, ['-m', 'runtime.cli', 'validate'], {
      cwd: engineRoot, windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...nonBillableEnvironment(), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' }
    });
    let stdout = ''; let stderr = ''; let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; child.kill(); }, timeoutMs);
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => { stdout = (stdout + chunk).slice(-240000); });
    child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-120000); });
    child.on('error', error => { clearTimeout(timer); resolve({ status: 'failed', exitCode: null, detail: error.message, output: stderr, timedOut }); });
    child.on('close', code => {
      clearTimeout(timer);
      resolve({
        status: code === 0 && !timedOut ? 'passed' : 'failed', exitCode: code,
        detail: timedOut ? 'Pacify-X validation timed out.' : code === 0 ? 'Pacify-X validation passed.' : 'Pacify-X validation reported failures.',
        output: [stdout, stderr].filter(Boolean).join('\n').trim(), timedOut,
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

module.exports = { findEngineRoot, isEngineRoot, runValidation, isPathWithin };
