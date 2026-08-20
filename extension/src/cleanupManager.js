'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const SAFE_CACHE_DIRECTORY_NAMES = new Set(['__pycache__', '.pytest_cache', '.ruff_cache']);
const SKIP_DIRECTORY_NAMES = new Set(['.git', 'node_modules']);

function normalizedPath(value) {
  const resolved = path.resolve(value);
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved;
}

function samePath(left, right) {
  return normalizedPath(left) === normalizedPath(right);
}

function isInside(candidate, root) {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative !== '' && !relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative);
}

function compareNames(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function statIdentity(stat) {
  return {
    dev: String(stat.dev),
    ino: String(stat.ino),
    mode: stat.mode,
    birthtime_ms: stat.birthtimeMs
  };
}

function sameIdentity(left, right) {
  return Boolean(left && right && left.dev === right.dev && left.ino === right.ino && left.mode === right.mode && left.birthtime_ms === right.birthtime_ms);
}

function candidateId(root, target) {
  return crypto.createHash('sha256').update(`${path.resolve(root)}\0${path.relative(root, target)}`).digest('hex').slice(0, 24);
}

async function captureRoot(root) {
  const resolved = path.resolve(root || '');
  if (!root || resolved === path.parse(resolved).root) throw new Error('engine-root-must-be-bounded');
  const stat = await fs.promises.lstat(resolved);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error('engine-root-is-not-a-plain-directory');
  return { resolved, real: await fs.promises.realpath(resolved), identity: statIdentity(stat) };
}

async function assertRootUnchanged(rootGuard) {
  const stat = await fs.promises.lstat(rootGuard.resolved);
  if (!stat.isDirectory() || stat.isSymbolicLink() || !sameIdentity(rootGuard.identity, statIdentity(stat))) throw new Error('engine-root-identity-changed');
  const real = await fs.promises.realpath(rootGuard.resolved);
  if (!samePath(real, rootGuard.real)) throw new Error('engine-root-resolution-changed');
}

async function assertPlainDirectoryUnderRoot(target, rootGuard) {
  const resolved = path.resolve(target);
  if (!isInside(resolved, rootGuard.resolved)) throw new Error('target-outside-engine-root');
  await assertRootUnchanged(rootGuard);
  const relative = path.relative(rootGuard.resolved, resolved);
  let cursor = rootGuard.resolved;
  for (const component of relative.split(path.sep).filter(Boolean)) {
    cursor = path.join(cursor, component);
    const stat = await fs.promises.lstat(cursor);
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error('link-reparse-or-nondirectory-in-target-path');
  }
  const real = await fs.promises.realpath(resolved);
  const expectedReal = path.join(rootGuard.real, relative);
  if (!samePath(real, expectedReal)) throw new Error('target-resolves-through-link-or-reparse-point');
  return fs.promises.lstat(resolved);
}

async function hashFileStable(file) {
  const before = await fs.promises.lstat(file);
  if (!before.isFile() || before.isSymbolicLink()) throw new Error('unsupported-or-linked-file');
  if (before.nlink > 1) throw new Error('multiply-linked-file-is-not-actionable');
  const noFollow = process.platform === 'win32' ? 0 : (fs.constants.O_NOFOLLOW || 0);
  const handle = await fs.promises.open(file, fs.constants.O_RDONLY | noFollow);
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || !sameIdentity(statIdentity(before), statIdentity(opened))) throw new Error('file-identity-changed-during-open');
    const digest = crypto.createHash('sha256');
    const buffer = Buffer.allocUnsafe(64 * 1024);
    let position = 0;
    while (true) {
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, position);
      if (!bytesRead) break;
      digest.update(buffer.subarray(0, bytesRead));
      position += bytesRead;
    }
    const afterHandle = await handle.stat();
    const afterPath = await fs.promises.lstat(file);
    if (!sameIdentity(statIdentity(opened), statIdentity(afterHandle)) || !sameIdentity(statIdentity(opened), statIdentity(afterPath)) || opened.size !== afterHandle.size || opened.mtimeMs !== afterHandle.mtimeMs || opened.size !== afterPath.size || opened.mtimeMs !== afterPath.mtimeMs) {
      throw new Error('file-changed-during-inventory');
    }
    return digest.digest('hex');
  } finally {
    await handle.close();
  }
}

async function inventoryDirectory(target, maxEntries = 50000) {
  const rootStat = await fs.promises.lstat(target);
  if (rootStat.isSymbolicLink()) throw new Error('link-or-reparse-target');
  if (!rootStat.isDirectory()) throw new Error('candidate-is-not-a-directory');
  const stack = [target];
  let files = 0;
  let directories = 0;
  let bytes = 0;
  let entries = 0;
  const manifest = [];
  while (stack.length) {
    const current = stack.pop();
    const before = await fs.promises.lstat(current);
    if (before.isSymbolicLink()) throw new Error('link-or-reparse-target');
    if (!before.isDirectory()) throw new Error('candidate-is-not-a-directory');
    directories += 1;
    const children = (await fs.promises.readdir(current, { withFileTypes: true })).sort((left, right) => compareNames(left.name, right.name));
    for (const child of children) {
      entries += 1;
      if (entries > maxEntries) throw new Error('candidate-inventory-limit-exceeded');
      const childPath = path.join(current, child.name);
      const childStat = await fs.promises.lstat(childPath);
      if (childStat.isSymbolicLink()) throw new Error('nested-link-or-reparse-point');
      const relative = path.relative(target, childPath).split(path.sep).join('/');
      if (childStat.isDirectory()) {
        const real = await fs.promises.realpath(childPath);
        const currentReal = await fs.promises.realpath(current);
        if (!samePath(real, path.join(currentReal, child.name))) throw new Error('nested-link-or-reparse-point');
        manifest.push({ path: `${relative}/`, type: 'directory' });
        stack.push(childPath);
      } else if (childStat.isFile()) {
        const sha256 = await hashFileStable(childPath);
        const stableStat = await fs.promises.lstat(childPath);
        files += 1;
        bytes += stableStat.size;
        manifest.push({ path: relative, type: 'file', bytes: stableStat.size, sha256 });
      } else {
        throw new Error('unsupported-filesystem-entry');
      }
    }
    const after = await fs.promises.lstat(current);
    if (!sameIdentity(statIdentity(before), statIdentity(after)) || before.mtimeMs !== after.mtimeMs) throw new Error('directory-changed-during-inventory');
  }
  manifest.sort((left, right) => compareNames(left.path, right.path));
  return {
    files,
    directories,
    bytes,
    links: 0,
    directoryIdentity: statIdentity(rootStat),
    treeHash: crypto.createHash('sha256').update(JSON.stringify(manifest)).digest('hex')
  };
}

function sameInventory(left, right) {
  return Boolean(left && right && left.files === right.files && left.directories === right.directories && left.bytes === right.bytes && left.links === right.links && left.treeHash === right.treeHash && (!left.directoryIdentity || sameIdentity(left.directoryIdentity, right.directoryIdentity)));
}

async function scanCleanupCandidates(root, options = {}) {
  const rootGuard = await captureRoot(root);
  const resolvedRoot = rootGuard.resolved;
  const maxDirectories = Number(options.maxDirectories || 25000);
  const maxCandidates = Number(options.maxCandidates || 500);
  const stack = [resolvedRoot];
  const candidates = [];
  let visitedDirectories = 0;
  while (stack.length) {
    if (options.signal?.aborted) throw Object.assign(new Error('Cleanup candidate scan cancelled.'), { name: 'AbortError' });
    const current = stack.pop();
    await assertRootUnchanged(rootGuard);
    if (!samePath(current, resolvedRoot)) await assertPlainDirectoryUnderRoot(current, rootGuard);
    visitedDirectories += 1;
    if (visitedDirectories > maxDirectories) throw new Error('cleanup-scan-directory-limit-exceeded');
    const children = await fs.promises.readdir(current, { withFileTypes: true });
    for (const child of children) {
      if (options.signal?.aborted) throw Object.assign(new Error('Cleanup candidate scan cancelled.'), { name: 'AbortError' });
      if (!child.isDirectory() || child.isSymbolicLink()) continue;
      const target = path.join(current, child.name);
      const relative = path.relative(resolvedRoot, target);
      const evidenceRoot = 'evidence';
      const quarantineRoot = path.join('.engineering-bootstrap', 'quarantine');
      if (relative === evidenceRoot || relative.startsWith(`${evidenceRoot}${path.sep}`) || relative === quarantineRoot || relative.startsWith(`${quarantineRoot}${path.sep}`)) continue;
      if (SAFE_CACHE_DIRECTORY_NAMES.has(child.name)) {
        if (candidates.length >= maxCandidates) throw new Error('cleanup-candidate-limit-exceeded');
        try {
          await assertPlainDirectoryUnderRoot(target, rootGuard);
          const inventory = await inventoryDirectory(target);
          const candidate = {
            id: candidateId(resolvedRoot, target),
            path: target,
            relativePath: relative.split(path.sep).join('/'),
            name: child.name,
            classification: 'safe-to-delete',
            category: 'Python / generated cache',
            explanation: 'Generated Python or test cache; tooling recreates it when needed.',
            retentionRequired: false,
            files: inventory.files,
            directories: inventory.directories,
            bytes: inventory.bytes,
            links: inventory.links,
            treeHash: inventory.treeHash
          };
          // The filesystem identity is execution-only guard state, not webview data.
          Object.defineProperty(candidate, 'directoryIdentity', { value: inventory.directoryIdentity, enumerable: false });
          candidates.push(candidate);
        } catch {
          // Ambiguous, inaccessible, linked, reparse-backed, or concurrently changing candidates fail closed.
        }
        continue;
      }
      if (!SKIP_DIRECTORY_NAMES.has(child.name)) stack.push(target);
    }
  }
  candidates.sort((left, right) => right.bytes - left.bytes || compareNames(left.relativePath, right.relativePath));
  return {
    root: resolvedRoot,
    rootIdentity: rootGuard.identity,
    candidates,
    summary: {
      candidateCount: candidates.length,
      bytes: candidates.reduce((total, item) => total + item.bytes, 0),
      files: candidates.reduce((total, item) => total + item.files, 0),
      visitedDirectories
    },
    orchestration: {
      audit: 'disk-auditor-safe-recommendations',
      intake: 'safe_cleanup',
      reconciliation: 'resource-lifecycle-reconciliation',
      sequence: ['classify', 'select', 'revalidate', 'atomically-stage', 'revalidate-staged-object', 'dispose', 'receipt']
    }
  };
}

function errorText(error) {
  const code = error && typeof error === 'object' && 'code' in error ? `${error.code}:` : '';
  return `${code}${error instanceof Error ? error.message : String(error)}`;
}

async function pathState(target) {
  try {
    return { exists: true, stat: await fs.promises.lstat(target) };
  } catch (error) {
    if (error && error.code === 'ENOENT') return { exists: false };
    throw error;
  }
}

async function assertReceiptDirectoryUnchanged(receiptGuard) {
  const stat = await fs.promises.lstat(receiptGuard.resolved);
  if (!stat.isDirectory() || stat.isSymbolicLink() || !sameIdentity(receiptGuard.identity, statIdentity(stat))) throw new Error('cleanup-receipt-directory-identity-changed');
  if (!samePath(await fs.promises.realpath(receiptGuard.resolved), receiptGuard.real)) throw new Error('cleanup-receipt-directory-resolution-changed');
}

async function writeReceiptAtomic(receiptPath, receipt, receiptGuard) {
  await assertReceiptDirectoryUnchanged(receiptGuard);
  const temporaryPath = `${receiptPath}.${process.pid}.${crypto.randomUUID()}.tmp`;
  let handle;
  try {
    handle = await fs.promises.open(temporaryPath, 'wx', 0o600);
    await handle.writeFile(`${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
    await handle.sync();
    await handle.close();
    handle = undefined;
    await assertReceiptDirectoryUnchanged(receiptGuard);
    await fs.promises.rename(temporaryPath, receiptPath);
    // Directory fsync is unsupported on some Windows filesystems; the file itself
    // is still flushed before its atomic replacement.
    if (process.platform !== 'win32') {
      const directoryHandle = await fs.promises.open(receiptGuard.resolved, 'r');
      try { await directoryHandle.sync(); } finally { await directoryHandle.close(); }
    }
  } finally {
    if (handle) await handle.close().catch(() => {});
    await fs.promises.rm(temporaryPath, { force: true }).catch(() => {});
  }
}

async function restoreUnchangedStage(stagePath, originalPath, expectedInventory, resource) {
  const stageState = await pathState(stagePath);
  const originalState = await pathState(originalPath);
  if (!stageState.exists || originalState.exists || !stageState.stat.isDirectory() || stageState.stat.isSymbolicLink()) return false;
  const retained = await inventoryDirectory(stagePath);
  if (!sameInventory(expectedInventory, retained)) return false;
  await fs.promises.rename(stagePath, originalPath);
  resource.restored_to_original_path = true;
  return true;
}

async function executeCleanup({ root, candidates, ids, disposition, deletePath, receiptDir }) {
  if (!['recycle', 'permanent'].includes(disposition)) throw new Error('unsupported-cleanup-disposition');
  if (typeof deletePath !== 'function') throw new Error('delete-path-adapter-required');
  const rootGuard = await captureRoot(root);
  const resolvedRoot = rootGuard.resolved;
  const selectedIds = [...new Set(Array.isArray(ids) ? ids.map(String) : [])];
  if (!selectedIds.length) throw new Error('cleanup-selection-required');
  const byId = new Map((Array.isArray(candidates) ? candidates : []).map(item => [item.id, item]));
  const selected = selectedIds.map(id => {
    const candidate = byId.get(id);
    if (!candidate) throw new Error('unknown-cleanup-candidate');
    return candidate;
  });
  const resolvedReceiptDir = path.resolve(receiptDir || '');
  if (!receiptDir || resolvedReceiptDir === path.parse(resolvedReceiptDir).root) throw new Error('cleanup-receipt-directory-must-be-bounded');
  for (const candidate of selected) {
    const target = path.resolve(candidate.path || '');
    if (samePath(resolvedReceiptDir, target) || isInside(resolvedReceiptDir, target)) throw new Error('receipt-path-inside-cleanup-target');
  }
  await fs.promises.mkdir(resolvedReceiptDir, { recursive: true });
  const receiptStat = await fs.promises.lstat(resolvedReceiptDir);
  if (!receiptStat.isDirectory() || receiptStat.isSymbolicLink()) throw new Error('cleanup-receipt-directory-is-not-plain');
  const receiptGuard = { resolved: resolvedReceiptDir, real: await fs.promises.realpath(resolvedReceiptDir), identity: statIdentity(receiptStat) };

  const cleanupId = `px-cleanup-${new Date().toISOString().replace(/[:.]/g, '')}-${crypto.randomUUID()}`;
  const receiptPath = path.join(resolvedReceiptDir, `${cleanupId}.json`);
  const receipt = {
    schema_version: '2.0', cleanup_id: cleanupId, operation: 'governed_cache_cleanup',
    audit_source: 'disk-auditor-safe-recommendations',
    orchestrations: ['safe_cleanup', 'resource-lifecycle-reconciliation'],
    disposition, root: resolvedRoot, started_utc: new Date().toISOString(), completed_utc: null,
    state: 'started', sequential: true, hard_delete: disposition === 'permanent', atomic_staging: true,
    resources: selected.map(item => ({ id: item.id, relative_path: item.relativePath, classification: item.classification, scan_tree_sha256: item.treeHash, result: 'pending', phase: 'selected' })),
    errors: []
  };
  await writeReceiptAtomic(receiptPath, receipt, receiptGuard);

  for (let index = 0; index < selected.length; index += 1) {
    const candidate = selected[index];
    const resource = receipt.resources[index];
    let target;
    let before;
    let stagePath;
    try {
      target = path.resolve(candidate.path || '');
      resource.phase = 'preflight';
      const actualRelativePath = path.relative(resolvedRoot, target).split(path.sep).join('/');
      if (!isInside(target, resolvedRoot) || !SAFE_CACHE_DIRECTORY_NAMES.has(path.basename(target)) || candidate.relativePath !== actualRelativePath || candidate.name !== path.basename(target) || candidate.classification !== 'safe-to-delete' || candidate.retentionRequired !== false || candidate.id !== candidateId(resolvedRoot, target)) {
        throw new Error('cleanup-target-outside-admitted-cache-boundary');
      }
      const stat = await assertPlainDirectoryUnderRoot(target, rootGuard);
      if (candidate.directoryIdentity && !sameIdentity(candidate.directoryIdentity, statIdentity(stat))) throw new Error('cleanup-target-identity-changed');
      before = await inventoryDirectory(target);
      if (!sameInventory(candidate, before)) throw new Error('cleanup-candidate-changed-since-scan');
      resource.preflight_tree_sha256 = before.treeHash;
      resource.before = before;
      resource.phase = 'preflight-valid';
      await writeReceiptAtomic(receiptPath, receipt, receiptGuard);

      await assertRootUnchanged(rootGuard);
      const immediateStat = await assertPlainDirectoryUnderRoot(target, rootGuard);
      if (!sameIdentity(before.directoryIdentity, statIdentity(immediateStat))) throw new Error('immediate-target-identity-gate-failed');
      const immediateInventory = await inventoryDirectory(target);
      if (!sameInventory(before, immediateInventory)) throw new Error('immediate-tree-equality-gate-failed');
      resource.immediate_tree_sha256 = immediateInventory.treeHash;

      stagePath = path.join(path.dirname(target), `.px-cleanup-staged-${cleanupId}-${index}`);
      if (!isInside(stagePath, resolvedRoot) || (await pathState(stagePath)).exists) throw new Error('cleanup-stage-path-unavailable');
      resource.phase = 'staging';
      resource.staging_relative_path = path.relative(resolvedRoot, stagePath).split(path.sep).join('/');
      await writeReceiptAtomic(receiptPath, receipt, receiptGuard);
      await fs.promises.rename(target, stagePath);

      const stagedStat = await assertPlainDirectoryUnderRoot(stagePath, rootGuard);
      if (!sameIdentity(immediateInventory.directoryIdentity, statIdentity(stagedStat))) throw new Error('staged-object-identity-mismatch');
      if ((await pathState(target)).exists) resource.replacement_detected_at_original_path = true;
      const stagedInventory = await inventoryDirectory(stagePath);
      if (!sameInventory(immediateInventory, stagedInventory)) throw new Error('staged-tree-equality-gate-failed');
      resource.staged_tree_sha256 = stagedInventory.treeHash;
      resource.phase = 'staged-valid';
      await writeReceiptAtomic(receiptPath, receipt, receiptGuard);

      // This is the last userspace gate before the adapter call. The random sibling
      // staging name makes the remaining OS-level pathname race narrow and ensures
      // a source-path replacement can never become the disposal target.
      await assertRootUnchanged(rootGuard);
      const finalStat = await assertPlainDirectoryUnderRoot(stagePath, rootGuard);
      if (!sameIdentity(stagedInventory.directoryIdentity, statIdentity(finalStat))) throw new Error('final-staged-object-identity-gate-failed');
      const finalInventory = await inventoryDirectory(stagePath);
      if (!sameInventory(stagedInventory, finalInventory)) throw new Error('final-staged-tree-equality-gate-failed');
      resource.pre_disposition_tree_sha256 = finalInventory.treeHash;

      let adapterError;
      try {
        await deletePath(stagePath, {
          recursive: true,
          useTrash: disposition === 'recycle',
          originalPath: target,
          expectedTreeSha256: stagedInventory.treeHash
        });
      } catch (error) {
        adapterError = error;
      }
      const after = await pathState(stagePath);
      if ((await pathState(target)).exists) resource.replacement_detected_at_original_path = true;
      if (!after.exists && !adapterError) {
        resource.result = disposition === 'recycle' ? 'moved-to-recycle-bin' : 'permanently-reclaimed';
        resource.phase = 'disposed';
      } else if (!after.exists) {
        resource.result = 'disposition-uncertain';
        resource.phase = 'absent-after-adapter-error';
        resource.error = errorText(adapterError);
        receipt.errors.push(`${candidate.relativePath}: adapter reported failure after target disappeared (${resource.error})`);
      } else {
        let retainedInventory;
        try { retainedInventory = await inventoryDirectory(stagePath); } catch (error) { resource.retained_inventory_error = errorText(error); }
        resource.retained_tree_sha256 = retainedInventory?.treeHash;
        resource.result = retainedInventory && sameInventory(stagedInventory, retainedInventory) ? 'failed-retained-unchanged' : 'failed-partial-retained';
        resource.phase = 'retained-after-disposition-failure';
        resource.error = adapterError ? errorText(adapterError) : 'target-remains-after-cleanup';
        if (resource.result === 'failed-retained-unchanged') {
          try {
            if (await restoreUnchangedStage(stagePath, target, stagedInventory, resource)) resource.result = 'failed-restored';
          } catch (error) {
            resource.restore_error = errorText(error);
          }
        }
        receipt.errors.push(`${candidate.relativePath}: ${resource.error}`);
      }
    } catch (error) {
      resource.error = errorText(error);
      resource.phase = stagePath ? 'staging-or-validation-failed' : 'preflight-failed';
      resource.result = stagePath ? 'failed-original-preserved' : 'skipped-fail-closed';
      if (stagePath) {
        try {
          const stageState = await pathState(stagePath);
          const originalState = await pathState(target);
          if (stageState.exists) {
            resource.retained_staging_relative_path = path.relative(resolvedRoot, stagePath).split(path.sep).join('/');
            resource.result = 'failed-retained';
            if (before && await restoreUnchangedStage(stagePath, target, before, resource)) resource.result = 'failed-restored';
            else if (originalState.exists) resource.stage_collision_or_replacement_detected = true;
          } else if (!originalState.exists) {
            resource.result = 'disposition-uncertain';
          }
        } catch (restoreError) {
          resource.restore_error = errorText(restoreError);
        }
      }
      receipt.errors.push(`${candidate.relativePath}: ${resource.error}`);
    }
    await writeReceiptAtomic(receiptPath, receipt, receiptGuard);
  }
  receipt.completed_utc = new Date().toISOString();
  receipt.state = receipt.errors.length ? 'completed-with-errors' : 'completed';
  const confirmedResults = new Set(['moved-to-recycle-bin', 'permanently-reclaimed']);
  receipt.resources_reclaimed = receipt.resources.filter(item => confirmedResults.has(item.result)).length;
  receipt.bytes_reclaimed = selected.filter((_, index) => confirmedResults.has(receipt.resources[index].result)).reduce((total, item) => total + Number(item.bytes || 0), 0);
  receipt.resources_uncertain = receipt.resources.filter(item => item.result === 'disposition-uncertain').length;
  await writeReceiptAtomic(receiptPath, receipt, receiptGuard);
  return { receipt, receiptPath };
}

module.exports = { SAFE_CACHE_DIRECTORY_NAMES, isInside, inventoryDirectory, sameInventory, scanCleanupCandidates, executeCleanup };
