'use strict';

const fs = require('node:fs');
const path = require('node:path');

const EXTENSION_ID = /^[a-z0-9][a-z0-9-]{0,63}\.[a-z0-9][a-z0-9-]{0,127}$/;
const DEFAULT_MAX_ENTRIES = 4096;
const DEFAULT_MAX_MANIFEST_BYTES = 1024 * 1024;

function boundedPositiveInteger(value, fallback, label) {
  const number = value == null ? fallback : Number(value);
  if (!Number.isSafeInteger(number) || number < 1) throw new TypeError(`extension-physical-catalog-${label}-invalid`);
  return number;
}

function within(candidate, root) {
  const normalizedCandidate = process.platform === 'win32' ? path.resolve(candidate).toLowerCase() : path.resolve(candidate);
  const normalizedRoot = process.platform === 'win32' ? path.resolve(root).toLowerCase() : path.resolve(root);
  return normalizedCandidate === normalizedRoot || normalizedCandidate.startsWith(`${normalizedRoot}${path.sep}`);
}

function readBoundedJson(file, maxBytes, label) {
  const stat = fs.lstatSync(file);
  if (stat.isSymbolicLink()) throw new Error(`extension-physical-catalog-${label}-link-refused`);
  if (!stat.isFile()) throw new Error(`extension-physical-catalog-${label}-not-file`);
  if (stat.size > maxBytes) throw new Error(`extension-physical-catalog-${label}-oversized`);
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch { throw new Error(`extension-physical-catalog-${label}-invalid-json`); }
}

function readObsolete(root, maxBytes) {
  const file = path.join(root, '.obsolete');
  if (!fs.existsSync(file)) return new Set();
  const value = readBoundedJson(file, maxBytes, 'obsolete');
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('extension-physical-catalog-obsolete-invalid-shape');
  const obsolete = new Set();
  for (const [name, state] of Object.entries(value)) {
    if (path.basename(name) !== name || name === '.' || name === '..' || typeof state !== 'boolean') throw new Error('extension-physical-catalog-obsolete-entry-invalid');
    if (state) obsolete.add(name);
  }
  return obsolete;
}

function loadedRecords(loadedExtensions) {
  const records = loadedExtensions && Array.isArray(loadedExtensions.all) ? loadedExtensions.all : [];
  return records.filter(record => record && typeof record === 'object');
}

function extensionId(manifest) {
  const publisher = String(manifest?.publisher || '').trim().toLowerCase();
  const name = String(manifest?.name || '').trim().toLowerCase();
  const id = `${publisher}.${name}`;
  if (!EXTENSION_ID.test(id)) throw new Error('extension-physical-catalog-manifest-id-invalid');
  if (!String(manifest?.version || '').trim()) throw new Error('extension-physical-catalog-manifest-version-invalid');
  return id;
}

function readPhysicalExtensionCatalog({ currentExtensionPath, loadedExtensions, maxEntries, maxManifestBytes } = {}) {
  if (!currentExtensionPath || !String(currentExtensionPath).trim()) throw new TypeError('extension-physical-catalog-current-path-required');
  const entryLimit = boundedPositiveInteger(maxEntries, DEFAULT_MAX_ENTRIES, 'max-entries');
  const byteLimit = boundedPositiveInteger(maxManifestBytes, DEFAULT_MAX_MANIFEST_BYTES, 'max-manifest-bytes');
  const current = fs.realpathSync(path.resolve(String(currentExtensionPath)));
  const root = fs.realpathSync(path.dirname(current));
  if (!within(current, root) || path.dirname(current) !== root) throw new Error('extension-physical-catalog-current-path-outside-root');

  const entries = fs.readdirSync(root, { withFileTypes: true });
  if (entries.length > entryLimit) throw new Error('extension-physical-catalog-entry-limit-exceeded');
  const obsolete = readObsolete(root, byteLimit);
  const physical = new Map();
  for (const entry of entries) {
    if (entry.name.startsWith('.') || obsolete.has(entry.name)) continue;
    const candidate = path.join(root, entry.name);
    const candidateStat = fs.lstatSync(candidate);
    if (candidateStat.isSymbolicLink()) throw new Error('extension-physical-catalog-entry-link-refused');
    if (!candidateStat.isDirectory()) continue;
    const manifestPath = path.join(candidate, 'package.json');
    if (!fs.existsSync(manifestPath)) continue;
    const manifest = readBoundedJson(manifestPath, byteLimit, 'manifest');
    if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) throw new Error('extension-physical-catalog-manifest-invalid-shape');
    const id = extensionId(manifest);
    if (physical.has(id)) throw new Error(`extension-physical-catalog-identity-ambiguous:${id}`);
    physical.set(id, { id, extensionPath: candidate, packageJSON: manifest, isActive: false });
  }

  const loaded = loadedRecords(loadedExtensions);
  const loadedById = new Map();
  for (const record of loaded) {
    const id = String(record.id || '').trim().toLowerCase();
    if (EXTENSION_ID.test(id) && !loadedById.has(id)) loadedById.set(id, record);
  }
  for (const [id, record] of physical) {
    const loadedRecord = loadedById.get(id);
    const loadedVersion = String(loadedRecord?.packageJSON?.version || '').trim();
    const physicalVersion = String(record.packageJSON.version).trim();
    record.isActive = loadedVersion === physicalVersion && Boolean(loadedRecord?.isActive);
  }

  const records = [...physical.values()];
  for (const record of loaded) {
    const id = String(record.id || '').trim().toLowerCase();
    if (!EXTENSION_ID.test(id) || physical.has(id)) continue;
    const loadedPath = record.extensionPath ? path.resolve(String(record.extensionPath)) : null;
    if (loadedPath && within(loadedPath, root)) continue;
    records.push(record);
  }
  records.sort((left, right) => String(left.id).toLowerCase().localeCompare(String(right.id).toLowerCase()));
  return records;
}

function createPhysicalExtensionCatalog(options = {}) {
  const read = () => readPhysicalExtensionCatalog(options);
  return {
    get all() { return read(); },
    getExtension(id) {
      const exact = String(id || '').trim().toLowerCase();
      if (!EXTENSION_ID.test(exact)) return undefined;
      return read().find(record => String(record.id).toLowerCase() === exact);
    }
  };
}

module.exports = { createPhysicalExtensionCatalog, readPhysicalExtensionCatalog };
