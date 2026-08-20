'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { TextDecoder } = require('node:util');

const MAX_FILES = 128;
const MAX_BYTES = 2 * 1024 * 1024;
const MAX_FILE_BYTES = 512 * 1024;
const MAX_DIRECTORIES = 256;
const MAX_ENTRIES = MAX_FILES + MAX_DIRECTORIES;
const MAX_DEPTH = 12;
const MAX_PATH_BYTES = 4096;
const UTF8_BOM_POLICY = 'preserve';
const WINDOWS_DEVICE = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$/i;
const WINDOWS_ALIAS_CHARACTER = /[<>:"|?*\u0000-\u001f]/;

function isWellFormedUnicode(value) {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false;
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) return false;
  }
  return true;
}

function safeSegment(value, label) {
  const raw = String(value || '');
  if (!isWellFormedUnicode(raw)) throw new Error(`studio-package-${label}-invalid`);
  const normalized = raw.trim().replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '');
  if (!normalized || normalized === '.' || normalized === '..') throw new Error(`studio-package-${label}-invalid`);
  return normalized.slice(0, 96);
}

function collisionSafeSkillSegment(value) {
  const identity = String(value ?? '');
  const readable = safeSegment(identity.toLowerCase(), 'skill-id');
  const identityHash = crypto.createHash('sha256').update(identity, 'utf8').digest('hex').slice(0, 16);
  return `${readable}-${identityHash}`;
}

function portablePathParts(suppliedPath) {
  const canonical = String(suppliedPath ?? '').replaceAll('\\', '/');
  const parts = canonical.split('/');
  if (
    !canonical || !isWellFormedUnicode(canonical) || canonical.startsWith('/') || /^[A-Za-z]:/.test(canonical)
    || Buffer.byteLength(canonical, 'utf8') > MAX_PATH_BYTES
    || parts.length > MAX_DEPTH
    || parts.some(part => (
      !part || part === '.' || part === '..' || part !== part.normalize('NFC')
      || Buffer.byteLength(part, 'utf8') > 255 || WINDOWS_ALIAS_CHARACTER.test(part)
      || /[. ]$/.test(part) || WINDOWS_DEVICE.test(part)
    ))
  ) throw new Error('studio-package-path-invalid');
  return { canonical, parts };
}

function normalizeFiles(files, options = {}) {
  if (!files || typeof files !== 'object' || Array.isArray(files)) throw new Error('studio-package-files-invalid');
  const records = Object.entries(files);
  if (!records.length || records.length > MAX_FILES) throw new Error('studio-package-file-count-invalid');
  let totalBytes = 0;
  const physicalPaths = new Map();
  const normalized = records.map(([suppliedPath, content]) => {
    if (typeof content !== 'string') throw new Error('studio-package-content-invalid');
    if (!isWellFormedUnicode(content)) throw new Error('studio-package-content-unpaired-surrogate');
    if (content.includes('\0')) throw new Error('studio-package-content-nul');
    const { canonical, parts } = portablePathParts(suppliedPath);
    for (let index = 1; index <= parts.length; index += 1) {
      const prefix = parts.slice(0, index).join('/'); const folded = prefix.toLowerCase();
      const kind = index === parts.length ? 'file' : 'directory'; const existing = physicalPaths.get(folded);
      if (existing && existing.path !== prefix) throw new Error('studio-package-path-case-collision');
      if (existing && existing.kind !== kind) throw new Error('studio-package-path-type-collision');
      if (existing && kind === 'file') throw new Error('studio-package-path-duplicate');
      if (!existing) physicalPaths.set(folded, { path: prefix, kind });
    }
    const contentBytes = Buffer.byteLength(content, 'utf8');
    if (contentBytes > MAX_FILE_BYTES) throw new Error('studio-package-file-bytes-exceeded');
    totalBytes += contentBytes;
    return { relativePath: canonical, content };
  }).sort((left, right) => Buffer.compare(Buffer.from(left.relativePath, 'utf8'), Buffer.from(right.relativePath, 'utf8')));
  if (totalBytes > MAX_BYTES) throw new Error('studio-package-bytes-exceeded');
  const directoryCount = [...physicalPaths.values()].filter(item => item.kind === 'directory').length;
  if (directoryCount > MAX_DIRECTORIES || directoryCount + normalized.length > MAX_ENTRIES) throw new Error('studio-package-topology-bound-exceeded');
  if (options.requireNativePackage !== false) {
    for (const required of ['SKILL.md', 'capability.json', 'skill.yaml']) if (!normalized.some(item => item.relativePath === required)) throw new Error(`studio-package-required-file-missing:${required}`);
  }
  return normalized;
}

function digestFiles(files) {
  const ordered = [...files].sort((left, right) => Buffer.compare(Buffer.from(left.relativePath, 'utf8'), Buffer.from(right.relativePath, 'utf8')));
  const hash = crypto.createHash('sha256');
  const frameLength = value => {
    const encoded = Buffer.allocUnsafe(8); encoded.writeBigUInt64BE(BigInt(value)); hash.update(encoded);
  };
  hash.update('px.skill-tree/2\0', 'utf8'); frameLength(ordered.length);
  for (const file of ordered) {
    const relativePath = Buffer.from(file.relativePath, 'utf8'); const content = Buffer.from(file.content, 'utf8');
    frameLength(relativePath.length); hash.update(relativePath); frameLength(content.length); hash.update(content);
  }
  return hash.digest('hex');
}

function fileInventory(files) {
  return [...files]
    .sort((left, right) => Buffer.compare(Buffer.from(left.relativePath, 'utf8'), Buffer.from(right.relativePath, 'utf8')))
    .map(file => {
      const bytes = Buffer.from(file.content, 'utf8');
      return { path: file.relativePath, bytes: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
    });
}

function pathWithin(root, target) {
  const relative = path.relative(root, target);
  return relative === '' || (!path.isAbsolute(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`));
}

function ensureOwnedDirectory(root, target, errorCode) {
  if (!pathWithin(root, target)) throw new Error(errorCode);
  const rootStat = fs.lstatSync(root);
  if (rootStat.isSymbolicLink() || !rootStat.isDirectory()) throw new Error(errorCode);
  const realRoot = fs.realpathSync.native(root);
  if (!pathWithin(root, realRoot) || !pathWithin(realRoot, root)) throw new Error(errorCode);
  const relative = path.relative(root, target); let cursor = root;
  for (const segment of relative.split(path.sep).filter(Boolean)) {
    cursor = path.join(cursor, segment);
    if (pathExistsNoFollow(cursor)) {
      const stat = fs.lstatSync(cursor);
      if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error(errorCode);
    } else fs.mkdirSync(cursor, { mode: 0o700 });
    const real = fs.realpathSync.native(cursor);
    if (!pathWithin(root, real)) throw new Error(errorCode);
  }
  return cursor;
}

function boundedDirectoryNames(directory, remaining, errorCode) {
  const handle = fs.opendirSync(directory); const names = [];
  try {
    while (true) {
      const entry = handle.readSync(); if (!entry) break;
      if (names.length >= remaining) throw new Error(errorCode);
      names.push(entry.name);
    }
  } finally { handle.closeSync(); }
  return names.sort().reverse();
}

function pathExistsNoFollow(target) {
  try { fs.lstatSync(target); return true; } catch (error) {
    if (error?.code === 'ENOENT') return false;
    throw error;
  }
}

function writeLifecycleReceipt(lifecycleRoot, operationId, phase, value) {
  const receipt = {
    schema_version: 'px.studio-package-temp-lifecycle/1.0',
    operation_id: operationId,
    phase,
    ...value
  };
  fs.writeFileSync(
    path.join(lifecycleRoot, `${operationId}.${phase}.json`),
    `${JSON.stringify(receipt)}\n`,
    { encoding: 'utf8', flag: 'wx', mode: 0o600 }
  );
}

function compactErrorCode(error) {
  return String(error?.code || error?.message || 'unknown-error').slice(0, 160);
}

function verifyRetainedDirectory(root, target) {
  if (!pathWithin(root, target)) throw new Error('studio-package-failure-resource-boundary');
  const stat = fs.lstatSync(target);
  if (stat.isSymbolicLink() || !stat.isDirectory()) throw new Error('studio-package-failure-resource-boundary');
  if (!pathWithin(root, fs.realpathSync.native(target))) throw new Error('studio-package-failure-resource-boundary');
}

function readBoundedRegularFile(target, limit, boundError, changedError) {
  const noFollow = fs.constants.O_NOFOLLOW || 0;
  const descriptor = fs.openSync(target, fs.constants.O_RDONLY | noFollow);
  try {
    const stat = fs.fstatSync(descriptor);
    if (!stat.isFile()) throw new Error(changedError);
    if (stat.size > limit) throw new Error(boundError);
    const buffer = Buffer.allocUnsafe(stat.size + 1); let offset = 0;
    while (offset < buffer.length) {
      const count = fs.readSync(descriptor, buffer, offset, buffer.length - offset, null);
      if (!count) break;
      offset += count;
    }
    if (offset !== stat.size) throw new Error(changedError);
    return { bytes: buffer.subarray(0, offset), size: stat.size };
  } finally { fs.closeSync(descriptor); }
}

function verifyExistingTree(target, files) {
  const expectedFiles = new Map(files.map(file => [file.relativePath, Buffer.from(file.content, 'utf8')]));
  const expectedDirectories = new Set();
  for (const file of files) {
    const parts = file.relativePath.split('/');
    for (let index = 1; index < parts.length; index += 1) expectedDirectories.add(parts.slice(0, index).join('/'));
  }
  const observedFiles = new Set(); const observedDirectories = new Set();
  const pending = [{ absolutePath: target, relativePath: '', depth: 0 }];
  let entryCount = 0; let directoryCount = 0; let fileCount = 0; let totalBytes = 0;
  while (pending.length) {
    const current = pending.pop(); const stat = fs.lstatSync(current.absolutePath);
    if (stat.isSymbolicLink()) throw new Error('studio-package-existing-link');
    if (current.depth > MAX_DEPTH) throw new Error('studio-package-existing-bound-exceeded');
    if (stat.isDirectory()) {
      if (current.relativePath) {
        directoryCount += 1;
        if (directoryCount > MAX_DIRECTORIES || !expectedDirectories.has(current.relativePath)) throw new Error('studio-package-existing-content-mismatch');
        observedDirectories.add(current.relativePath);
      }
      const names = boundedDirectoryNames(current.absolutePath, MAX_ENTRIES - entryCount, 'studio-package-existing-bound-exceeded');
      entryCount += names.length;
      for (const name of names) {
        const relativePath = current.relativePath ? `${current.relativePath}/${name}` : name;
        pending.push({ absolutePath: path.join(current.absolutePath, name), relativePath, depth: current.depth + 1 });
      }
      continue;
    }
    if (!stat.isFile()) throw new Error('studio-package-existing-content-mismatch');
    fileCount += 1;
    if (fileCount > MAX_FILES) throw new Error('studio-package-existing-bound-exceeded');
    observedFiles.add(current.relativePath);
    const expected = expectedFiles.get(current.relativePath);
    if (!expected) throw new Error('studio-package-existing-content-mismatch');
    const actual = readBoundedRegularFile(
      current.absolutePath,
      Math.min(MAX_FILE_BYTES, MAX_BYTES - totalBytes),
      'studio-package-existing-bound-exceeded',
      'studio-package-existing-content-mismatch'
    );
    totalBytes += actual.size;
    if (actual.size !== expected.length || !actual.bytes.equals(expected)) throw new Error('studio-package-existing-content-mismatch');
  }
  if (observedFiles.size !== expectedFiles.size || observedDirectories.size !== expectedDirectories.size) throw new Error('studio-package-existing-content-mismatch');
  for (const relativePath of expectedFiles.keys()) if (!observedFiles.has(relativePath)) throw new Error('studio-package-existing-content-mismatch');
  for (const relativePath of expectedDirectories) if (!observedDirectories.has(relativePath)) throw new Error('studio-package-existing-content-mismatch');
}

function materializationReceipt(operationId, root, target, digest, files, reused) {
  return Object.freeze({
    schema_version: 'px.studio-package-materialization/1.0',
    operation_id: operationId,
    source_directory: target,
    resource_relative: path.relative(root, target),
    tree_sha256: digest,
    file_count: files.length,
    files: fileInventory(files),
    reused: Boolean(reused)
  });
}

function sameInventory(left, right) {
  return Array.isArray(left) && Array.isArray(right) && left.length === right.length && left.every((item, index) => {
    const other = right[index];
    return item && other && item.path === other.path && item.bytes === other.bytes && item.sha256 === other.sha256;
  });
}

function attestContainedTree(target) {
  const files = {}; const observedDirectories = new Set(); const pending = [{ absolutePath: target, relativePath: '', depth: 0 }];
  let entryCount = 0; let directoryCount = 0; let fileCount = 0; let totalBytes = 0;
  while (pending.length) {
    const current = pending.pop(); const stat = fs.lstatSync(current.absolutePath);
    if (stat.isSymbolicLink()) throw new Error('studio-package-reclaim-link');
    if (current.depth > MAX_DEPTH) throw new Error('studio-package-reclaim-bound-exceeded');
    if (current.relativePath) {
      try { portablePathParts(current.relativePath); } catch { throw new Error('studio-package-reclaim-path-invalid'); }
    }
    if (stat.isDirectory()) {
      if (current.relativePath) { directoryCount += 1; observedDirectories.add(current.relativePath); }
      if (directoryCount > MAX_DIRECTORIES) throw new Error('studio-package-reclaim-bound-exceeded');
      const names = boundedDirectoryNames(current.absolutePath, MAX_ENTRIES - entryCount, 'studio-package-reclaim-bound-exceeded');
      entryCount += names.length;
      for (const name of names) pending.push({ absolutePath: path.join(current.absolutePath, name), relativePath: current.relativePath ? `${current.relativePath}/${name}` : name, depth: current.depth + 1 });
      continue;
    }
    if (!stat.isFile() || ++fileCount > MAX_FILES) throw new Error('studio-package-reclaim-bound-exceeded');
    const actual = readBoundedRegularFile(current.absolutePath, Math.min(MAX_FILE_BYTES, MAX_BYTES - totalBytes), 'studio-package-reclaim-bound-exceeded', 'studio-package-reclaim-changed');
    totalBytes += actual.size;
    try { files[current.relativePath] = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(actual.bytes); }
    catch { throw new Error('studio-package-reclaim-utf8-invalid'); }
  }
  const expectedDirectories = new Set();
  for (const relativePath of Object.keys(files)) {
    const parts = relativePath.split('/');
    for (let index = 1; index < parts.length; index += 1) expectedDirectories.add(parts.slice(0, index).join('/'));
  }
  if (observedDirectories.size !== expectedDirectories.size || [...observedDirectories].some(item => !expectedDirectories.has(item))) throw new Error('studio-package-reclaim-topology-invalid');
  const normalized = normalizeFiles(files);
  return { treeSha256: digestFiles(normalized), fileCount: normalized.length, files: fileInventory(normalized) };
}

function materializeSkillPackage(projectRoot, payload) {
  if (typeof projectRoot !== 'string' || !projectRoot.trim()) throw new Error('studio-package-project-root-required');
  const root = fs.realpathSync.native(path.resolve(projectRoot)); const files = normalizeFiles(payload?.editor_files);
  const skill = collisionSafeSkillSegment(payload?.skill_id);
  const rawVersion = String(payload?.version ?? '');
  const version = `${safeSegment(rawVersion, 'version')}-${crypto.createHash('sha256').update(rawVersion, 'utf8').digest('hex').slice(0, 16)}`;
  const digest = digestFiles(files);
  const studioRoot = path.join(root, '.px', 'studio-inputs'); const target = path.join(studioRoot, skill, `${version}-${digest.slice(0, 16)}`);
  if (!pathWithin(root, target) || target === root) throw new Error('studio-package-target-outside-project');
  ensureOwnedDirectory(root, path.dirname(target), 'studio-package-link-boundary');
  const operationId = crypto.randomUUID();
  const lifecycleRoot = ensureOwnedDirectory(root, path.join(studioRoot, '.lifecycle'), 'studio-package-lifecycle-boundary');
  let published = false; let registered = false; let reused = false;
  try {
    writeLifecycleReceipt(lifecycleRoot, operationId, 'registered', {
      state: 'registered',
      resource_relative: path.relative(root, target),
      target_relative: path.relative(root, target),
      tree_sha256: digest,
      file_count: files.length,
      registered_at: new Date().toISOString()
    });
    registered = true;
    if (pathExistsNoFollow(target)) {
      verifyExistingTree(target, files); reused = true;
    } else {
      try { fs.mkdirSync(target, { mode: 0o700 }); }
      catch (error) {
        if (error?.code !== 'EEXIST') throw error;
        verifyExistingTree(target, files); reused = true;
      }
      if (!reused) {
        for (const file of files) {
          const destination = path.join(target, ...file.relativePath.split('/'));
          ensureOwnedDirectory(target, path.dirname(destination), 'studio-package-write-boundary');
          fs.writeFileSync(destination, file.content, { encoding: 'utf8', flag: 'wx' });
        }
        verifyExistingTree(target, files);
      }
    }
    published = true;
    writeLifecycleReceipt(lifecycleRoot, operationId, 'closed', {
      state: reused ? 'reused' : 'published',
      resource_relative: path.relative(root, target),
      target_relative: path.relative(root, target),
      tree_sha256: digest,
      file_count: files.length,
      closed_at: new Date().toISOString()
    });
  } catch (error) {
    let state = 'resource-absent'; let retentionError;
    try {
      if (pathExistsNoFollow(target)) {
        verifyRetainedDirectory(root, target);
        state = 'retained-in-place';
      }
    } catch (caught) {
      retentionError = caught; state = 'retention-state-unknown';
    }
    try {
      if (!registered) throw new Error('studio-package-lifecycle-not-registered');
      writeLifecycleReceipt(lifecycleRoot, operationId, 'closed', {
        state,
        resource_relative: pathWithin(root, target) ? path.relative(root, target) : null,
        target_relative: path.relative(root, target),
        tree_sha256: digest,
        file_count: files.length,
        error_code: compactErrorCode(error),
        retention_error_code: retentionError ? compactErrorCode(retentionError) : null,
        published_before_failure: published,
        closed_at: new Date().toISOString()
      });
    } catch {
      // The original failure remains authoritative; a registered receipt still exposes an unclosed operation.
    }
    throw error;
  }
  return { sourceDirectory: target, treeSha256: digest, fileCount: files.length, reused, materialization: materializationReceipt(operationId, root, target, digest, files, reused) };
}

function reclaimMaterializedSkillPackage(projectRoot, materialized, createReceipt) {
  const expectedMaterializationKeys = ['file_count', 'files', 'operation_id', 'resource_relative', 'reused', 'schema_version', 'source_directory', 'tree_sha256'];
  const receipt = materialized?.materialization;
  if (!receipt || typeof receipt !== 'object' || Array.isArray(receipt) || Object.keys(receipt).sort().join('\0') !== expectedMaterializationKeys.sort().join('\0') || receipt.schema_version !== 'px.studio-package-materialization/1.0'
    || materialized.sourceDirectory !== receipt.source_directory || materialized.treeSha256 !== receipt.tree_sha256 || materialized.fileCount !== receipt.file_count || materialized.reused !== receipt.reused
    || typeof receipt.operation_id !== 'string' || !/^[a-f0-9-]{32,64}$/i.test(receipt.operation_id) || typeof receipt.resource_relative !== 'string' || typeof receipt.reused !== 'boolean') throw new Error('studio-package-reclaim-materialization-receipt-invalid');
  const durableSuccess = createReceipt?.created === true || (createReceipt?.created === false && createReceipt?.idempotent_replay === true);
  if (!durableSuccess || createReceipt.schema_version !== 'px.skill-draft/1.1' || typeof createReceipt.source_authority_token !== 'string' || !createReceipt.source_authority_token
    || createReceipt.source_tree_sha256 !== receipt.tree_sha256 || createReceipt.file_count !== receipt.file_count || !sameInventory(createReceipt.files, receipt.files)) throw new Error('studio-package-reclaim-create-receipt-mismatch');
  const root = fs.realpathSync.native(path.resolve(projectRoot));
  const studioRoot = fs.realpathSync.native(path.join(root, '.px', 'studio-inputs'));
  const target = fs.realpathSync.native(path.resolve(receipt.source_directory));
  if (!pathWithin(studioRoot, target) || target === studioRoot || path.basename(target) === '.lifecycle' || path.basename(target) === '.reclaiming' || path.relative(root, target) !== receipt.resource_relative) throw new Error('studio-package-reclaim-boundary');
  const lifecycleRoot = fs.realpathSync.native(path.join(studioRoot, '.lifecycle'));
  const closedPath = path.join(lifecycleRoot, `${receipt.operation_id}.closed.json`);
  const closedStat = fs.lstatSync(closedPath);
  if (closedStat.isSymbolicLink() || !closedStat.isFile()) throw new Error('studio-package-reclaim-lifecycle-receipt-mismatch');
  const closed = JSON.parse(readBoundedRegularFile(closedPath, 16 * 1024, 'studio-package-reclaim-lifecycle-receipt-mismatch', 'studio-package-reclaim-lifecycle-receipt-mismatch').bytes.toString('utf8'));
  const closedKeys = ['closed_at', 'file_count', 'operation_id', 'phase', 'resource_relative', 'schema_version', 'state', 'target_relative', 'tree_sha256'];
  if (!closed || typeof closed !== 'object' || Array.isArray(closed) || Object.keys(closed).sort().join('\0') !== closedKeys.sort().join('\0')
    || closed.schema_version !== 'px.studio-package-temp-lifecycle/1.0' || closed.phase !== 'closed' || !['published', 'reused'].includes(closed.state)
    || closed.operation_id !== receipt.operation_id || closed.resource_relative !== receipt.resource_relative || closed.target_relative !== receipt.resource_relative
    || closed.tree_sha256 !== receipt.tree_sha256 || closed.file_count !== receipt.file_count || typeof closed.closed_at !== 'string') throw new Error('studio-package-reclaim-lifecycle-receipt-mismatch');
  const observed = attestContainedTree(target);
  if (observed.treeSha256 !== receipt.tree_sha256 || observed.fileCount !== receipt.file_count || !sameInventory(observed.files, receipt.files)) throw new Error('studio-package-reclaim-tree-mismatch');
  const reclaimRoot = ensureOwnedDirectory(root, path.join(studioRoot, '.reclaiming'), 'studio-package-reclaim-boundary');
  const container = path.join(reclaimRoot, `${receipt.operation_id}-${crypto.randomUUID()}`);
  fs.mkdirSync(container, { mode: 0o700 });
  const retained = path.join(container, 'resource');
  try {
    writeLifecycleReceipt(lifecycleRoot, receipt.operation_id, 'reclaim-authorized', {
      state: 'reclaim-authorized', resource_relative: receipt.resource_relative,
      retained_relative: path.relative(root, retained), tree_sha256: receipt.tree_sha256,
      file_count: receipt.file_count, authorized_at: new Date().toISOString()
    });
    fs.renameSync(target, retained);
    const moved = attestContainedTree(retained);
    if (moved.treeSha256 !== receipt.tree_sha256 || moved.fileCount !== receipt.file_count || !sameInventory(moved.files, receipt.files)) throw new Error('studio-package-reclaim-tree-changed');
    fs.rmSync(retained, { recursive: true, force: false });
    writeLifecycleReceipt(lifecycleRoot, receipt.operation_id, 'reclaimed', {
      state: 'reclaimed', resource_relative: receipt.resource_relative, tree_sha256: receipt.tree_sha256,
      file_count: receipt.file_count, reclaimed_at: new Date().toISOString()
    });
    const reclaimedPath = path.join(lifecycleRoot, `${receipt.operation_id}.reclaimed.json`);
    const reclaimed = JSON.parse(readBoundedRegularFile(reclaimedPath, 16 * 1024, 'studio-package-reclaim-receipt-invalid', 'studio-package-reclaim-receipt-invalid').bytes.toString('utf8'));
    if (reclaimed.schema_version !== 'px.studio-package-temp-lifecycle/1.0' || reclaimed.operation_id !== receipt.operation_id || reclaimed.phase !== 'reclaimed'
      || reclaimed.state !== 'reclaimed' || reclaimed.resource_relative !== receipt.resource_relative || reclaimed.tree_sha256 !== receipt.tree_sha256 || reclaimed.file_count !== receipt.file_count) throw new Error('studio-package-reclaim-receipt-invalid');
    try { fs.rmdirSync(container); } catch { /* empty reclaim container is a bounded owned ephemeral */ }
    return { schema_version: 'px.studio-package-reclamation/1.0', reclaimed: true, operation_id: receipt.operation_id };
  } catch (error) {
    // Never delete an uncertain resource. The target or uniquely contained moved resource remains for evidence.
    throw error;
  }
}

function rejectLinkBoundary(root, target) {
  const relative = path.relative(root, target);
  if (path.isAbsolute(relative) || relative === '..' || relative.startsWith(`..${path.sep}`)) throw new Error('studio-package-read-boundary');
  let cursor = root;
  for (const segment of relative.split(path.sep).filter(Boolean)) {
    cursor = path.join(cursor, segment);
    const stat = fs.lstatSync(cursor);
    if (stat.isSymbolicLink()) throw new Error('studio-package-read-link');
  }
}

function readSkillPackage(engineRoot, suppliedPath, options = {}) {
  if (typeof engineRoot !== 'string' || !engineRoot.trim()) throw new Error('studio-package-engine-root-required');
  const engine = fs.realpathSync.native(path.resolve(engineRoot)); let relativePath;
  try { relativePath = portablePathParts(suppliedPath).canonical; } catch { throw new Error('studio-package-read-path-invalid'); }
  const scope = String(options.scope || 'engine');
  if (!['engine', 'project-studio'].includes(scope)) throw new Error('studio-package-read-scope-invalid');
  let root = engine; let allowed;
  if (scope === 'project-studio') {
    if (typeof options.projectRoot !== 'string' || !options.projectRoot.trim()) throw new Error('studio-package-project-root-required');
    root = fs.realpathSync.native(path.resolve(options.projectRoot));
    allowed = path.resolve(root, '.engineering-bootstrap', 'studios', 'skills');
  }
  const candidate = path.resolve(root, ...relativePath.split('/')); if (!fs.existsSync(candidate)) throw new Error('studio-package-read-missing');
  rejectLinkBoundary(root, candidate);
  const realCandidate = fs.realpathSync.native(candidate);
  let preservedOriginal = false;
  if (scope === 'engine') {
    const engineRoots = ['.px/skills', '.px/preserved-skills'].map(value => path.resolve(root, ...value.split('/'))).filter(fs.existsSync).map(value => fs.realpathSync.native(value));
    if (!engineRoots.some(parent => realCandidate === parent || realCandidate.startsWith(`${parent}${path.sep}`))) throw new Error('studio-package-read-boundary');
    const preservedRoot = path.resolve(root, '.px', 'preserved-skills');
    if (fs.existsSync(preservedRoot)) {
      const realPreserved = fs.realpathSync.native(preservedRoot);
      preservedOriginal = realCandidate === realPreserved || realCandidate.startsWith(`${realPreserved}${path.sep}`);
    }
  } else {
    if (!fs.existsSync(allowed)) throw new Error('studio-package-read-boundary');
    const realAllowed = fs.realpathSync.native(allowed); const fromStudio = path.relative(realAllowed, realCandidate);
    const parts = fromStudio.split(path.sep);
    if (path.isAbsolute(fromStudio) || fromStudio === '..' || fromStudio.startsWith(`..${path.sep}`) || parts.length !== 4 || parts[1] !== 'revisions' || parts[3] !== 'payload') throw new Error('studio-package-read-boundary');
  }
  const rootStat = fs.lstatSync(realCandidate);
  if (rootStat.isSymbolicLink()) throw new Error('studio-package-read-link');
  if (!rootStat.isDirectory()) throw new Error('studio-package-read-special-file');
  const files = {}; const physicalPaths = new Map(); const observedDirectories = new Set();
  const pending = [{ absolutePath: realCandidate, relativePath: '', depth: 0 }];
  let entryCount = 0; let directoryCount = 0; let fileCount = 0; let totalBytes = 0;
  while (pending.length) {
    const current = pending.pop(); const stat = fs.lstatSync(current.absolutePath);
    if (stat.isSymbolicLink()) throw new Error('studio-package-read-link');
    if (current.depth > MAX_DEPTH) throw new Error('studio-package-read-bound-exceeded');
    if (current.relativePath) {
      try { portablePathParts(current.relativePath); } catch { throw new Error('studio-package-read-path-invalid'); }
      const folded = current.relativePath.toLowerCase(); const kind = stat.isDirectory() ? 'directory' : 'file'; const existing = physicalPaths.get(folded);
      if (existing && (existing.path !== current.relativePath || existing.kind !== kind)) throw new Error('studio-package-read-path-collision');
      physicalPaths.set(folded, { path: current.relativePath, kind });
    }
    if (stat.isDirectory()) {
      if (current.relativePath && ++directoryCount > MAX_DIRECTORIES) throw new Error('studio-package-read-bound-exceeded');
      if (current.relativePath) observedDirectories.add(current.relativePath);
      const names = boundedDirectoryNames(current.absolutePath, MAX_ENTRIES - entryCount, 'studio-package-read-bound-exceeded');
      entryCount += names.length;
      for (const name of names) {
        const childRelative = current.relativePath ? `${current.relativePath}/${name}` : name;
        pending.push({ absolutePath: path.join(current.absolutePath, name), relativePath: childRelative, depth: current.depth + 1 });
      }
      continue;
    }
    if (!stat.isFile()) throw new Error('studio-package-read-special-file');
    if (++fileCount > MAX_FILES) throw new Error('studio-package-read-bound-exceeded');
    const actual = readBoundedRegularFile(
      current.absolutePath,
      Math.min(MAX_FILE_BYTES, MAX_BYTES - totalBytes),
      'studio-package-read-bound-exceeded',
      'studio-package-read-changed'
    );
    totalBytes += actual.size; const bytes = actual.bytes;
    if (bytes.includes(0)) throw new Error(`studio-package-read-binary:${current.relativePath}`);
    try {
      // ignoreBOM=true prevents TextDecoder from consuming the UTF-8 BOM, preserving exact bytes on re-encode.
      files[current.relativePath] = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
    } catch {
      throw new Error(`studio-package-read-utf8-invalid:${current.relativePath}`);
    }
  }
  const expectedDirectories = new Set();
  for (const relativePath of Object.keys(files)) {
    const parts = relativePath.split('/');
    for (let index = 1; index < parts.length; index += 1) expectedDirectories.add(parts.slice(0, index).join('/'));
  }
  if (observedDirectories.size !== expectedDirectories.size || [...observedDirectories].some(item => !expectedDirectories.has(item))) throw new Error('studio-package-read-topology-invalid');
  const normalized = normalizeFiles(files, { requireNativePackage: !preservedOriginal });
  const missingRequiredFiles = ['SKILL.md', 'capability.json', 'skill.yaml'].filter(required => !Object.hasOwn(files, required));
  return { packagePath: relativePath, packageScope: scope, preservedOriginal, nativePackageComplete: missingRequiredFiles.length === 0, missingRequiredFiles, editor_files: files, treeSha256: digestFiles(normalized), fileCount: Object.keys(files).length };
}

module.exports = {
  MAX_BYTES,
  MAX_DEPTH,
  MAX_DIRECTORIES,
  MAX_ENTRIES,
  MAX_FILE_BYTES,
  MAX_FILES,
  UTF8_BOM_POLICY,
  digestFiles,
  fileInventory,
  materializeSkillPackage,
  normalizeFiles,
  reclaimMaterializedSkillPackage,
  readSkillPackage,
  safeSegment
};
