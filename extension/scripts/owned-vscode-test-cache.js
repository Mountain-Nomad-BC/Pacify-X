'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const CACHE_SCHEMA = 'px.owned-vscode-test-cache/1.0';
const CACHE_ROOT = path.join(os.tmpdir(), 'pacify-x-vscode-test-cache');
const MARKER_NAME = '.pacify-x-owned-cache.json';

function ensureOwnedVscodeTestCache(version, options = {}) {
  const root = path.resolve(options.cacheRoot || CACHE_ROOT);
  const temporaryRoot = path.resolve(os.tmpdir());
  if (path.dirname(root) !== temporaryRoot || path.basename(root) !== 'pacify-x-vscode-test-cache') {
    throw new Error(`vscode-test-cache-outside-admitted-root:${root}`);
  }
  fs.mkdirSync(root, { recursive: true });
  const markerPath = path.join(root, MARKER_NAME);
  if (fs.existsSync(markerPath)) {
    const marker = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
    if (marker.schema_version !== CACHE_SCHEMA || marker.owner !== 'PACIFY-X') {
      throw new Error(`vscode-test-cache-ownership-mismatch:${root}`);
    }
  } else {
    const unexpected = fs.readdirSync(root);
    if (unexpected.length) throw new Error(`unclassified-vscode-test-cache:${root}`);
  }
  const marker = {
    schema_version: CACHE_SCHEMA,
    owner: 'PACIFY-X',
    classification: 'reusable_test_cache',
    retained_versions: [String(version)],
    updated_utc: new Date().toISOString()
  };
  fs.writeFileSync(markerPath, `${JSON.stringify(marker, null, 2)}\n`, 'utf8');

  const pruned = [];
  for (const name of fs.readdirSync(root)) {
    if (name === MARKER_NAME || name.endsWith(`-${version}`)) continue;
    const target = path.join(root, name);
    const stat = fs.lstatSync(target);
    if (stat.isSymbolicLink()) throw new Error(`vscode-test-cache-link-blocked:${target}`);
    // The marker classifies this exact root as PACIFY-X-owned. Keeping only the
    // pinned version prevents each host update from accumulating another SDK.
    fs.rmSync(target, { recursive: stat.isDirectory(), force: true });
    pruned.push(name);
  }
  return { root, markerPath, retainedVersion: String(version), pruned };
}

function markOwnedHostWorkspace(root, kind) {
  const resolved = path.resolve(root);
  const temporaryRoot = path.resolve(os.tmpdir());
  if (path.dirname(resolved) !== temporaryRoot || !path.basename(resolved).startsWith('pacify-x-')) {
    throw new Error(`owned-host-workspace-outside-admitted-root:${resolved}`);
  }
  const markerPath = path.join(resolved, '.pacify-x-owned-ephemeral.json');
  fs.writeFileSync(markerPath, `${JSON.stringify({
    schema_version: 'px.owned-host-workspace/1.0', owner: 'PACIFY-X',
    classification: 'ephemeral', kind, owner_pid: process.pid,
    expected_cleanup_event: 'verified_process_tree_closure', created_utc: new Date().toISOString()
  }, null, 2)}\n`, 'utf8');
  return markerPath;
}

module.exports = {
  CACHE_ROOT,
  ensureOwnedVscodeTestCache,
  markOwnedHostWorkspace
};
