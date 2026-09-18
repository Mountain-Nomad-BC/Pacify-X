'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const CACHE_SCHEMA = 'px.owned-vscode-test-cache/1.0';
const MARKER_NAME = '.pacify-x-owned-cache.json';
const VERSION_PATTERN = /^\d+\.\d+\.\d+$/;

function defaultOwnedCacheRoot({ platform = process.platform, homeDirectory = os.homedir(), temporaryRoot = os.tmpdir() } = {}) {
  const parent = platform === 'linux'
    ? path.join(path.resolve(homeDirectory), '.cache')
    : path.resolve(temporaryRoot);
  return path.join(parent, 'pacify-x-vscode-test-cache');
}

const CACHE_ROOT = defaultOwnedCacheRoot();

function normalizedVersion(version) {
  if (typeof version !== 'string' || !VERSION_PATTERN.test(version)) {
    throw new Error('vscode-test-cache-version-invalid');
  }
  return version;
}

function ownedCacheRoot(options = {}) {
  const root = path.resolve(options.cacheRoot || CACHE_ROOT);
  if (root !== path.resolve(CACHE_ROOT)) {
    throw new Error(`vscode-test-cache-outside-admitted-root:${root}`);
  }
  return root;
}

function readOwnedVscodeTestCache(version, options = {}) {
  const retainedVersion = normalizedVersion(version);
  const root = ownedCacheRoot(options);
  const markerPath = path.join(root, MARKER_NAME);
  for (const [target, kind] of [[root, 'directory'], [markerPath, 'file']]) {
    if (!fs.existsSync(target)) throw new Error(`vscode-test-cache-${kind}-missing:${path.basename(target)}`);
    const status = fs.lstatSync(target);
    if (status.isSymbolicLink() || (kind === 'directory' ? !status.isDirectory() : !status.isFile())) {
      throw new Error(`vscode-test-cache-${kind}-invalid:${path.basename(target)}`);
    }
  }
  const marker = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
  if (marker.schema_version !== CACHE_SCHEMA || marker.owner !== 'PACIFY-X') {
    throw new Error(`vscode-test-cache-ownership-mismatch:${root}`);
  }
  return Object.freeze({ root, markerPath, retainedVersion, pruned: Object.freeze([]) });
}

function ensureOwnedVscodeTestCache(version, options = {}) {
  const retainedVersion = normalizedVersion(version);
  const root = ownedCacheRoot(options);
  fs.mkdirSync(root, { recursive: true });
  const markerPath = path.join(root, MARKER_NAME);
  let existingMarker = null;
  if (fs.existsSync(markerPath)) {
    const status = fs.lstatSync(markerPath);
    if (status.isSymbolicLink() || !status.isFile()) throw new Error(`vscode-test-cache-file-invalid:${MARKER_NAME}`);
    existingMarker = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
    if (existingMarker.schema_version !== CACHE_SCHEMA || existingMarker.owner !== 'PACIFY-X') {
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
    retained_versions: [...new Set([
      ...(Array.isArray(existingMarker?.retained_versions)
        ? existingMarker.retained_versions.filter(item => typeof item === 'string' && VERSION_PATTERN.test(item))
        : []),
      retainedVersion
    ])].sort(),
    updated_utc: new Date().toISOString()
  };
  fs.writeFileSync(markerPath, `${JSON.stringify(marker, null, 2)}\n`, 'utf8');
  return Object.freeze({ root, markerPath, retainedVersion, pruned: Object.freeze([]) });
}

function adoptOwnedVscodeTestCache(version, options = {}) {
  const retainedVersion = normalizedVersion(version);
  const root = ownedCacheRoot(options);
  if (!fs.existsSync(root)) throw new Error(`vscode-test-cache-directory-missing:${path.basename(root)}`);
  const rootStatus = fs.lstatSync(root);
  if (rootStatus.isSymbolicLink() || !rootStatus.isDirectory()) {
    throw new Error(`vscode-test-cache-directory-invalid:${path.basename(root)}`);
  }
  const layout = cachedVSCodeLayout(root, retainedVersion, options);
  const entries = fs.readdirSync(root).sort();
  if (entries.length !== 1 || path.join(root, entries[0]) !== layout.directory) {
    throw new Error(`unclassified-vscode-test-cache:${root}`);
  }
  const markerPath = path.join(root, MARKER_NAME);
  const prepared = `${markerPath}.${process.pid}.new`;
  fs.writeFileSync(prepared, `${JSON.stringify({
    schema_version: CACHE_SCHEMA,
    owner: 'PACIFY-X',
    classification: 'reusable_test_cache',
    retained_versions: [retainedVersion],
    adopted_existing_complete_layout: true,
    updated_utc: new Date().toISOString()
  }, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  fs.renameSync(prepared, markerPath);
  return resolveOwnedCachedVSCode(retainedVersion, options);
}

function cachedVSCodeLayout(cacheRoot, version, options = {}) {
  const root = path.resolve(cacheRoot);
  const platform = options.platform || process.platform;
  const arch = options.arch || process.arch;
  const retainedVersion = normalizedVersion(version);
  const platformName = platform === 'win32' && ['x64', 'arm64'].includes(arch)
    ? `win32-${arch}-archive`
    : platform === 'linux' && ['x64', 'arm64', 'arm'].includes(arch)
      ? `linux-${arch === 'arm' ? 'armhf' : arch}`
      : null;
  if (!platformName) throw new Error(`vscode-test-cache-platform-unsupported:${platform}-${arch}`);
  const directory = path.join(root, `vscode-${platformName}-${retainedVersion}`);
  const complete = path.join(directory, 'is-complete');
  const executable = path.join(directory, platform === 'win32' ? 'Code.exe' : 'code');
  for (const [target, kind] of [[root, 'directory'], [directory, 'directory'], [complete, 'file'], [executable, 'file']]) {
    if (!fs.existsSync(target)) throw new Error(`vscode-test-cache-${kind}-missing:${path.basename(target)}`);
    const status = fs.lstatSync(target);
    if (status.isSymbolicLink() || (kind === 'directory' ? !status.isDirectory() : !status.isFile())) {
      throw new Error(`vscode-test-cache-${kind}-invalid:${path.basename(target)}`);
    }
  }
  return Object.freeze({ root, directory, complete, executable, version: retainedVersion, platform, arch });
}

function resolveOwnedCachedVSCode(version, options = {}) {
  const cache = readOwnedVscodeTestCache(version, options);
  return Object.freeze({ ...cache, ...cachedVSCodeLayout(cache.root, version, options) });
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
  adoptOwnedVscodeTestCache,
  cachedVSCodeLayout,
  defaultOwnedCacheRoot,
  ensureOwnedVscodeTestCache,
  markOwnedHostWorkspace,
  readOwnedVscodeTestCache,
  resolveOwnedCachedVSCode
};
