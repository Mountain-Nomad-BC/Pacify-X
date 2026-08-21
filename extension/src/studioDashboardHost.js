'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const SHA256 = /^[a-f0-9]{64}$/;
const IDENTITY = /^[a-z0-9][a-z0-9._:-]{1,127}$/;
const VERSION = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-.]([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*))?$/;
const MAX_VERSION_COMPONENT = 2147483647n;
const MAX_TREE_ENTRIES = 512;
const MAX_TREE_FILE_BYTES = 4 * 1024 * 1024;
const MAX_TREE_BYTES = 16 * 1024 * 1024;
const MAX_TREE_DEPTH = 12;

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
}

function validVersion(value) {
  if (typeof value !== 'string' || value !== value.trim().toLowerCase() || value.length > 96) return false;
  const match = VERSION.exec(value);
  if (!match || match[4]?.length > 64 || match[4]?.split('.').some(item => /^0[0-9]+$/.test(item))) return false;
  try { return [match[1], match[2], match[3]].every(item => BigInt(item) <= MAX_VERSION_COMPONENT); } catch { return false; }
}

function boundedEntries(directory) {
  const handle = fs.opendirSync(directory); const entries = [];
  try {
    for (;;) {
      const entry = handle.readSync(); if (!entry) break;
      if (entries.length >= MAX_TREE_ENTRIES) throw new Error('studio-catalog-tree-bound-exceeded');
      entries.push(entry);
    }
  } finally { handle.closeSync(); }
  return entries.sort((left, right) => Buffer.compare(Buffer.from(left.name, 'utf8'), Buffer.from(right.name, 'utf8')));
}

function readBoundedFile(file, expectedStat) {
  const descriptor = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try {
    const stat = fs.fstatSync(descriptor);
    if (!stat.isFile() || stat.size > MAX_TREE_FILE_BYTES || (expectedStat && (stat.dev !== expectedStat.dev || stat.ino !== expectedStat.ino))) throw new Error('studio-catalog-tree-file-invalid');
    const buffer = Buffer.alloc(stat.size + 1); let offset = 0;
    while (offset < buffer.length) { const count = fs.readSync(descriptor, buffer, offset, buffer.length - offset, null); if (!count) break; offset += count; }
    if (offset !== stat.size) throw new Error('studio-catalog-tree-file-changed');
    return buffer.subarray(0, offset);
  } finally { fs.closeSync(descriptor); }
}

function revisionTreeSha256(revision, projectRoot) {
  const project = fs.realpathSync.native(path.resolve(projectRoot)); const supplied = path.resolve(revision);
  const relative = path.relative(project, supplied);
  if (!relative || path.isAbsolute(relative) || relative === '..' || relative.startsWith(`..${path.sep}`)) throw new Error('studio-catalog-revision-outside-project');
  let current = project;
  for (const segment of relative.split(path.sep)) {
    current = path.join(current, segment); const component = fs.lstatSync(current);
    if (component.isSymbolicLink()) throw new Error('studio-catalog-revision-link-refused');
  }
  const physical = fs.realpathSync.native(supplied);
  const physicalRelative = path.relative(project, physical);
  if (!physicalRelative || path.isAbsolute(physicalRelative) || physicalRelative === '..' || physicalRelative.startsWith(`..${path.sep}`)) throw new Error('studio-catalog-revision-outside-project');
  const rootStat = fs.lstatSync(physical);
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) throw new Error('studio-catalog-revision-invalid');
  const rows = []; const pending = [{ directory: physical, depth: 0 }]; let totalBytes = 0; let observedEntries = 0;
  while (pending.length) {
    const current = pending.pop();
    for (const entry of boundedEntries(current.directory)) {
      observedEntries += 1;
      if (observedEntries > MAX_TREE_ENTRIES) throw new Error('studio-catalog-tree-bound-exceeded');
      const absolute = path.join(current.directory, entry.name); const stat = fs.lstatSync(absolute);
      if (entry.isSymbolicLink() || stat.isSymbolicLink()) throw new Error('studio-catalog-tree-link-refused');
      const relative = path.relative(physical, absolute).replaceAll('\\', '/');
      if (!relative || relative.startsWith('../') || path.isAbsolute(relative)) throw new Error('studio-catalog-tree-path-invalid');
      if (relative.split('/').length > MAX_TREE_DEPTH) throw new Error('studio-catalog-tree-bound-exceeded');
      if (entry.isDirectory()) {
        if (current.depth + 1 > MAX_TREE_DEPTH) throw new Error('studio-catalog-tree-bound-exceeded');
        rows.push({ kind: 'directory', path: relative }); pending.push({ directory: absolute, depth: current.depth + 1 });
      } else if (entry.isFile()) {
        const data = readBoundedFile(absolute, stat); totalBytes += data.length;
        if (totalBytes > MAX_TREE_BYTES) throw new Error('studio-catalog-tree-bound-exceeded');
        rows.push({ kind: 'file', path: relative, size: data.length, sha256: crypto.createHash('sha256').update(data).digest('hex') });
      } else throw new Error('studio-catalog-tree-entry-invalid');
    }
  }
  rows.sort((left, right) => Buffer.compare(Buffer.from(left.path, 'utf8'), Buffer.from(right.path, 'utf8')) || left.kind.localeCompare(right.kind));
  return crypto.createHash('sha256').update(Buffer.from(canonicalJson(rows), 'utf8')).digest('hex');
}

function exactCatalogRevision(page, { kind, catalogKind, recordId }) {
  if (!['agent', 'workflow'].includes(kind) || catalogKind !== `${kind}s` || typeof recordId !== 'string' || !recordId) throw new Error('studio-catalog-selection-contract-invalid');
  const matches = (page?.items || []).filter(item => item?.id === recordId);
  if (matches.length !== 1) throw new Error('studio-catalog-selection-stale-or-ambiguous');
  const item = matches[0]; const details = item.details;
  if (!details || typeof details !== 'object' || Array.isArray(details) || item.kind !== `studio-${kind}-revision`) throw new Error('studio-catalog-selection-kind-invalid');
  const identityKey = kind === 'agent' ? 'agent_id' : 'workflow_id';
  const rawIdentity = details[identityKey]; const rawVersion = details.version;
  const identity = String(rawIdentity || '').trim().toLowerCase(); const sourceVersion = String(rawVersion || '').trim().toLowerCase();
  const rawRevisionSha256 = details.revision_sha256; const rawContentSha256 = details.source_content_sha256;
  const revisionSha256 = String(rawRevisionSha256 || '').trim().toLowerCase(); const contentSha256 = String(rawContentSha256 || '').trim().toLowerCase();
  if (rawIdentity !== identity || rawVersion !== sourceVersion || rawRevisionSha256 !== revisionSha256 || rawContentSha256 !== contentSha256 || !IDENTITY.test(identity) || !validVersion(sourceVersion) || !SHA256.test(revisionSha256) || !SHA256.test(contentSha256) || details.studio_revision !== true) throw new Error('studio-catalog-selection-authentication-invalid');
  return Object.freeze({
    kind, catalog_kind: catalogKind, record_id: recordId, identity, source_version: sourceVersion,
    source_revision_sha256: revisionSha256, source_content_sha256: contentSha256,
    record: JSON.parse(JSON.stringify({ ...details, identity: item.identity, summary: item.summary, effects: item.effects, tags: item.tags }))
  });
}

function createPanelOrigin(webview) {
  if (!webview || typeof webview.postMessage !== 'function') throw new TypeError('dashboard-origin-webview-invalid');
  let active = true;
  return Object.freeze({
    webview,
    postMessage: message => active ? webview.postMessage(message) : Promise.resolve(false),
    dispose: () => { active = false; },
    isActive: () => active
  });
}

module.exports = { createPanelOrigin, exactCatalogRevision, revisionTreeSha256, validVersion };
