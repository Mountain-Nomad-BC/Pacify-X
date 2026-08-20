'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const SAFE_CACHE_DIRECTORY_NAMES = new Set(['__pycache__', '.pytest_cache', '.ruff_cache']);
const SKIP_DIRECTORY_NAMES = new Set(['.git', 'node_modules']);

function isInside(candidate, root) {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative !== '' && !relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative);
}

function candidateId(root, target) {
  return crypto.createHash('sha256').update(`${path.resolve(root)}\0${path.relative(root, target)}`).digest('hex').slice(0, 24);
}

async function inventoryDirectory(target, maxEntries = 50000) {
  const stack = [target];
  let files = 0;
  let directories = 0;
  let bytes = 0;
  let entries = 0;
  const manifest = [];
  while (stack.length) {
    const current = stack.pop();
    const currentStat = await fs.promises.lstat(current);
    if (currentStat.isSymbolicLink()) throw new Error('link-or-reparse-target');
    if (!currentStat.isDirectory()) throw new Error('candidate-is-not-a-directory');
    directories += 1;
    const children = (await fs.promises.readdir(current, { withFileTypes: true })).sort((left, right) => left.name.localeCompare(right.name));
    for (const child of children) {
      entries += 1;
      if (entries > maxEntries) throw new Error('candidate-inventory-limit-exceeded');
      const childPath = path.join(current, child.name);
      const childStat = await fs.promises.lstat(childPath);
      if (childStat.isSymbolicLink()) throw new Error('nested-link-or-reparse-point');
      const relative = path.relative(target, childPath).split(path.sep).join('/');
      if (childStat.isDirectory()) { manifest.push({ path: `${relative}/`, type: 'directory' }); stack.push(childPath); }
      else if (childStat.isFile()) {
        files += 1; bytes += childStat.size;
        manifest.push({ path: relative, type: 'file', bytes: childStat.size, sha256: await hashFile(childPath) });
      }
      else throw new Error('unsupported-filesystem-entry');
    }
  }
  manifest.sort((left, right) => left.path.localeCompare(right.path));
  return { files, directories, bytes, links: 0, treeHash: crypto.createHash('sha256').update(JSON.stringify(manifest)).digest('hex') };
}

function hashFile(file) {
  return new Promise((resolve, reject) => {
    const digest = crypto.createHash('sha256');
    const stream = fs.createReadStream(file);
    stream.on('data', chunk => digest.update(chunk));
    stream.on('error', reject);
    stream.on('end', () => resolve(digest.digest('hex')));
  });
}

function sameInventory(left, right) {
  return Boolean(left && right && left.files === right.files && left.directories === right.directories && left.bytes === right.bytes && left.links === right.links && left.treeHash === right.treeHash);
}

async function scanCleanupCandidates(root, options = {}) {
  const resolvedRoot = path.resolve(root || '');
  if (!root || resolvedRoot === path.parse(resolvedRoot).root) throw new Error('engine-root-must-be-bounded');
  const rootStat = await fs.promises.lstat(resolvedRoot);
  if (!rootStat.isDirectory() || rootStat.isSymbolicLink()) throw new Error('engine-root-is-not-a-plain-directory');
  const maxDirectories = Number(options.maxDirectories || 25000);
  const maxCandidates = Number(options.maxCandidates || 500);
  const stack = [resolvedRoot];
  const candidates = [];
  let visitedDirectories = 0;
  while (stack.length) {
    const current = stack.pop();
    visitedDirectories += 1;
    if (visitedDirectories > maxDirectories) throw new Error('cleanup-scan-directory-limit-exceeded');
    const children = await fs.promises.readdir(current, { withFileTypes: true });
    for (const child of children) {
      if (!child.isDirectory() || child.isSymbolicLink()) continue;
      const target = path.join(current, child.name);
      const relative = path.relative(resolvedRoot, target);
      const evidenceRoot = 'evidence';
      const quarantineRoot = path.join('.engineering-bootstrap', 'quarantine');
      if (relative === evidenceRoot || relative.startsWith(`${evidenceRoot}${path.sep}`) || relative === quarantineRoot || relative.startsWith(`${quarantineRoot}${path.sep}`)) continue;
      if (SAFE_CACHE_DIRECTORY_NAMES.has(child.name)) {
        if (candidates.length >= maxCandidates) throw new Error('cleanup-candidate-limit-exceeded');
        try {
          const inventory = await inventoryDirectory(target);
          candidates.push({
            id: candidateId(resolvedRoot, target),
            path: target,
            relativePath: relative.split(path.sep).join('/'),
            name: child.name,
            classification: 'safe-to-delete',
            category: 'Python / generated cache',
            explanation: 'Generated Python or test cache; tooling recreates it when needed.',
            retentionRequired: false,
            ...inventory
          });
        } catch {
          // Ambiguous candidates fail closed and are omitted from actionable results.
        }
        continue;
      }
      if (!SKIP_DIRECTORY_NAMES.has(child.name)) stack.push(target);
    }
  }
  candidates.sort((left, right) => right.bytes - left.bytes || left.relativePath.localeCompare(right.relativePath));
  return {
    root: resolvedRoot,
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
      sequence: ['classify', 'select', 'revalidate', 'dispose', 'receipt']
    }
  };
}

async function executeCleanup({ root, candidates, ids, disposition, deletePath, receiptDir }) {
  if (!['recycle', 'permanent'].includes(disposition)) throw new Error('unsupported-cleanup-disposition');
  if (typeof deletePath !== 'function') throw new Error('delete-path-adapter-required');
  const resolvedRoot = path.resolve(root);
  const selectedIds = [...new Set(Array.isArray(ids) ? ids.map(String) : [])];
  if (!selectedIds.length) throw new Error('cleanup-selection-required');
  const byId = new Map(candidates.map(item => [item.id, item]));
  const preflight = [];
  for (const id of selectedIds) {
    const candidate = byId.get(id);
    if (!candidate) throw new Error('unknown-cleanup-candidate');
    const target = path.resolve(candidate.path);
    if (!isInside(target, resolvedRoot) || !SAFE_CACHE_DIRECTORY_NAMES.has(path.basename(target))) throw new Error('cleanup-target-outside-admitted-cache-boundary');
    const stat = await fs.promises.lstat(target);
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error('cleanup-target-type-changed');
    const inventory = await inventoryDirectory(target);
    if (!sameInventory(candidate, inventory)) throw new Error('cleanup-candidate-changed-since-scan');
    preflight.push({ ...candidate, path: target, before: inventory });
  }

  const cleanupId = `px-cleanup-${new Date().toISOString().replace(/[:.]/g, '')}-${crypto.randomUUID()}`;
  const resolvedReceiptDir = path.resolve(receiptDir);
  if (preflight.some(item => isInside(resolvedReceiptDir, item.path) || resolvedReceiptDir === item.path)) throw new Error('receipt-path-inside-cleanup-target');
  await fs.promises.mkdir(resolvedReceiptDir, { recursive: true });
  const receiptPath = path.join(resolvedReceiptDir, `${cleanupId}.json`);
  const receipt = {
    schema_version: '1.0', cleanup_id: cleanupId, operation: 'governed_cache_cleanup',
    audit_source: 'disk-auditor-safe-recommendations',
    orchestrations: ['safe_cleanup', 'resource-lifecycle-reconciliation'],
    disposition, root: resolvedRoot, started_utc: new Date().toISOString(), completed_utc: null,
    state: 'started', sequential: true, hard_delete: disposition === 'permanent',
    resources: preflight.map(item => ({ id: item.id, relative_path: item.relativePath, classification: item.classification, scan_tree_sha256: item.treeHash, preflight_tree_sha256: item.before.treeHash, before: item.before, result: 'pending' })),
    errors: []
  };
  await fs.promises.writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
  for (let index = 0; index < preflight.length; index += 1) {
    const item = preflight[index];
    try {
      const immediateStat = await fs.promises.lstat(item.path);
      if (!immediateStat.isDirectory() || immediateStat.isSymbolicLink() || !isInside(item.path, resolvedRoot)) throw new Error('immediate-pre-delete-gate-failed');
      const immediateInventory = await inventoryDirectory(item.path);
      if (!sameInventory(item.before, immediateInventory)) throw new Error('immediate-tree-equality-gate-failed');
      receipt.resources[index].immediate_tree_sha256 = immediateInventory.treeHash;
      await deletePath(item.path, { recursive: true, useTrash: disposition === 'recycle' });
      if (fs.existsSync(item.path)) throw new Error('target-remains-after-cleanup');
      receipt.resources[index].result = disposition === 'recycle' ? 'moved-to-recycle-bin' : 'permanently-reclaimed';
    } catch (error) {
      receipt.resources[index].result = 'failed';
      receipt.errors.push(`${item.relativePath}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  receipt.completed_utc = new Date().toISOString();
  receipt.state = receipt.errors.length ? 'completed-with-errors' : 'completed';
  receipt.resources_reclaimed = receipt.resources.filter(item => item.result !== 'failed').length;
  receipt.bytes_reclaimed = preflight.filter((_, index) => receipt.resources[index].result !== 'failed').reduce((total, item) => total + item.before.bytes, 0);
  await fs.promises.writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
  return { receipt, receiptPath };
}

module.exports = { SAFE_CACHE_DIRECTORY_NAMES, isInside, inventoryDirectory, sameInventory, scanCleanupCandidates, executeCleanup };
