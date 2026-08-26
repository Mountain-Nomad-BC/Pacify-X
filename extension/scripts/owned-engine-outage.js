'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const MARKER = '.pacify-x-owned-ephemeral.json';
const DISPLACED_RUNTIME = '.px-operational-fault-runtime';

const sha256 = target => crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex');

function samePath(left, right) {
  return process.platform === 'win32'
    ? path.resolve(left).toLowerCase() === path.resolve(right).toLowerCase()
    : path.resolve(left) === path.resolve(right);
}

function validateOwnedEngine(engineRoot, ownershipToken) {
  const engineInput = path.resolve(engineRoot || '');
  const tokenInput = path.resolve(ownershipToken || '');
  if (!engineRoot || !ownershipToken || !fs.existsSync(engineInput) || !fs.existsSync(tokenInput)) throw new Error('owned-engine-outage-boundary-missing');
  const engineInputStatus = fs.lstatSync(engineInput);
  const tokenStatus = fs.lstatSync(tokenInput);
  if (engineInputStatus.isSymbolicLink() || tokenStatus.isSymbolicLink()) throw new Error('owned-engine-outage-linked-root');
  if (!engineInputStatus.isDirectory() || !tokenStatus.isDirectory()) throw new Error('owned-engine-outage-root-not-directory');
  const token = fs.realpathSync.native(tokenInput);
  const ownedRoot = fs.realpathSync.native(path.dirname(token));
  const engine = fs.realpathSync.native(engineInput);
  if (!samePath(engine, path.join(ownedRoot, 'engine')) || path.basename(token).toLowerCase() !== 'user-data') {
    throw new Error('owned-engine-outage-boundary-mismatch');
  }
  const markerPath = path.join(ownedRoot, MARKER);
  if (!fs.existsSync(markerPath) || fs.lstatSync(markerPath).isSymbolicLink()) throw new Error('owned-engine-outage-marker-missing');
  const marker = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
  if (marker.schema_version !== 'px.owned-host-workspace/1.0' || marker.owner !== 'PACIFY-X' || marker.classification !== 'ephemeral') {
    throw new Error('owned-engine-outage-marker-invalid');
  }
  const runtime = path.join(engine, 'runtime');
  const displaced = path.join(engine, DISPLACED_RUNTIME);
  if (!fs.existsSync(runtime) || fs.lstatSync(runtime).isSymbolicLink() || !fs.lstatSync(runtime).isDirectory()) throw new Error('owned-engine-outage-runtime-invalid');
  if (fs.existsSync(displaced)) throw new Error('owned-engine-outage-target-exists');
  const required = ['cli.py', 'dashboard_api.py'];
  const hashes = Object.fromEntries(required.map(name => {
    const target = path.join(runtime, name);
    if (!fs.existsSync(target) || fs.lstatSync(target).isSymbolicLink() || !fs.lstatSync(target).isFile()) throw new Error(`owned-engine-outage-required-file-invalid:${name}`);
    return [name, sha256(target)];
  }));
  return { engine, ownedRoot, runtime, displaced, hashes };
}

function beginOwnedEngineOutage(engineRoot, ownershipToken) {
  const boundary = validateOwnedEngine(engineRoot, ownershipToken);
  fs.renameSync(boundary.runtime, boundary.displaced);
  let restored = false;
  const receipt = {
    schema_version: 'px.owned-engine-outage/1.0',
    engine_root: '[owned-temporary-engine]',
    displaced_relative: DISPLACED_RUNTIME,
    required_file_sha256: boundary.hashes,
    outage_active: true,
    restored: false
  };
  return {
    receipt,
    restore() {
      if (restored) return receipt;
      if (fs.existsSync(boundary.runtime) || !fs.existsSync(boundary.displaced) || fs.lstatSync(boundary.displaced).isSymbolicLink() || !fs.lstatSync(boundary.displaced).isDirectory()) {
        throw new Error('owned-engine-outage-restore-boundary-invalid');
      }
      fs.renameSync(boundary.displaced, boundary.runtime);
      for (const [name, expected] of Object.entries(boundary.hashes)) {
        const target = path.join(boundary.runtime, name);
        if (!fs.existsSync(target) || fs.lstatSync(target).isSymbolicLink() || sha256(target) !== expected) throw new Error(`owned-engine-outage-restoration-mismatch:${name}`);
      }
      restored = true;
      receipt.outage_active = false;
      receipt.restored = true;
      return receipt;
    }
  };
}

module.exports = { beginOwnedEngineOutage, validateOwnedEngine };
