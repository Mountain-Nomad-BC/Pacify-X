'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { scanCleanupCandidates, executeCleanup } = require('../src/cleanupManager');

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-cleanup-test-'));
  fs.mkdirSync(path.join(root, 'pkg', '__pycache__'), { recursive: true });
  fs.writeFileSync(path.join(root, 'pkg', '__pycache__', 'module.pyc'), 'generated-bytecode');
  fs.mkdirSync(path.join(root, '.pytest_cache'), { recursive: true });
  fs.writeFileSync(path.join(root, '.pytest_cache', 'state'), 'generated-test-state');
  fs.mkdirSync(path.join(root, 'evidence', '__pycache__'), { recursive: true });
  fs.writeFileSync(path.join(root, 'evidence', '__pycache__', 'protected.pyc'), 'protected-evidence');
  return root;
}

test('cleanup manager classifies generated caches but excludes evidence', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const inventory = await scanCleanupCandidates(root);
  assert.deepEqual(inventory.candidates.map(item => item.relativePath).sort(), ['.pytest_cache', 'pkg/__pycache__']);
  assert.equal(inventory.summary.candidateCount, 2);
  assert.equal(inventory.orchestration.intake, 'safe_cleanup');
  assert.equal(inventory.orchestration.reconciliation, 'resource-lifecycle-reconciliation');
});

test('individual permanent cleanup is revalidated, executed, and receipted', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const inventory = await scanCleanupCandidates(root);
  const selected = inventory.candidates.find(item => item.relativePath === 'pkg/__pycache__');
  const calls = [];
  const result = await executeCleanup({
    root, candidates: inventory.candidates, ids: [selected.id], disposition: 'permanent', receiptDir: path.join(root, '.receipts'),
    deletePath: async (target, options) => { calls.push({ target, options }); await fs.promises.rm(target, { recursive: true }); }
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.useTrash, false);
  assert.notEqual(calls[0].target, selected.path);
  assert.match(path.basename(calls[0].target), /^\.px-cleanup-staged-/);
  assert.equal(calls[0].options.originalPath, selected.path);
  assert.equal(fs.existsSync(selected.path), false);
  assert.equal(result.receipt.resources_reclaimed, 1);
  assert.equal(result.receipt.hard_delete, true);
  assert.match(result.receipt.resources[0].scan_tree_sha256, /^[a-f0-9]{64}$/);
  assert.equal(result.receipt.resources[0].scan_tree_sha256, result.receipt.resources[0].preflight_tree_sha256);
  assert.equal(result.receipt.resources[0].preflight_tree_sha256, result.receipt.resources[0].immediate_tree_sha256);
  assert.equal(fs.existsSync(result.receiptPath), true);
});

test('select-all recycle cleanup requests operating-system trash for every candidate', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const inventory = await scanCleanupCandidates(root);
  const calls = [];
  const result = await executeCleanup({
    root, candidates: inventory.candidates, ids: inventory.candidates.map(item => item.id), disposition: 'recycle', receiptDir: path.join(root, '.receipts'),
    deletePath: async (target, options) => { calls.push({ target, options }); await fs.promises.rm(target, { recursive: true }); }
  });
  assert.equal(calls.length, 2);
  assert.equal(calls.every(call => call.options.useTrash === true), true);
  assert.equal(result.receipt.resources_reclaimed, 2);
  assert.equal(result.receipt.hard_delete, false);
});

test('arbitrary directories fail closed even if a webview forges a candidate', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-cleanup-boundary-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const target = path.join(root, 'authoritative-data');
  fs.mkdirSync(target);
  fs.writeFileSync(path.join(target, 'keep.txt'), 'keep');
  const forged = { id: 'forged', path: target, relativePath: 'authoritative-data', classification: 'safe-to-delete' };
  const result = await executeCleanup({ root, candidates: [forged], ids: ['forged'], disposition: 'permanent', receiptDir: path.join(root, '.receipts'), deletePath: () => { throw new Error('must-not-run'); } });
  assert.equal(result.receipt.resources[0].result, 'skipped-fail-closed');
  assert.match(result.receipt.resources[0].error, /outside-admitted-cache-boundary/);
  assert.equal(fs.existsSync(path.join(target, 'keep.txt')), true);
});

test('cleanup fails closed when a candidate tree changes after the scan', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const inventory = await scanCleanupCandidates(root);
  const selected = inventory.candidates.find(item => item.relativePath === 'pkg/__pycache__');
  fs.writeFileSync(path.join(selected.path, 'late.pyc'), 'changed-after-scan');
  const result = await executeCleanup({
    root, candidates: inventory.candidates, ids: [selected.id], disposition: 'permanent',
    receiptDir: path.join(root, '.receipts'), deletePath: () => { throw new Error('must-not-run'); }
  });
  assert.equal(result.receipt.resources[0].result, 'skipped-fail-closed');
  assert.match(result.receipt.resources[0].error, /changed-since-scan/);
  assert.equal(fs.existsSync(selected.path), true);
});

test('a link or junction swapped in after scan is skipped and never followed', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const inventory = await scanCleanupCandidates(root);
  const selected = inventory.candidates.find(item => item.relativePath === 'pkg/__pycache__');
  const authoritative = path.join(root, 'authoritative');
  fs.mkdirSync(authoritative);
  fs.writeFileSync(path.join(authoritative, 'keep.txt'), 'keep');
  fs.rmSync(selected.path, { recursive: true });
  fs.symlinkSync(authoritative, selected.path, process.platform === 'win32' ? 'junction' : 'dir');
  let invoked = false;
  const result = await executeCleanup({
    root, candidates: inventory.candidates, ids: [selected.id], disposition: 'permanent', receiptDir: path.join(root, '.receipts'),
    deletePath: async () => { invoked = true; }
  });
  assert.equal(invoked, false);
  assert.equal(result.receipt.resources[0].result, 'skipped-fail-closed');
  assert.match(result.receipt.resources[0].error, /link-reparse|identity-changed/);
  assert.equal(fs.readFileSync(path.join(authoritative, 'keep.txt'), 'utf8'), 'keep');
});

test('nested links and junctions make a cache non-actionable during scanning', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const authoritative = path.join(root, 'authoritative');
  fs.mkdirSync(authoritative);
  fs.writeFileSync(path.join(authoritative, 'keep.txt'), 'keep');
  fs.symlinkSync(authoritative, path.join(root, 'pkg', '__pycache__', 'escape'), process.platform === 'win32' ? 'junction' : 'dir');
  const inventory = await scanCleanupCandidates(root);
  assert.equal(inventory.candidates.some(item => item.relativePath === 'pkg/__pycache__'), false);
  assert.equal(fs.readFileSync(path.join(authoritative, 'keep.txt'), 'utf8'), 'keep');
});

test('multiply linked files make a cache non-actionable without touching the other name', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const authoritative = path.join(root, 'authoritative.bin');
  fs.writeFileSync(authoritative, 'shared authoritative bytes');
  fs.linkSync(authoritative, path.join(root, 'pkg', '__pycache__', 'shared.pyc'));
  const inventory = await scanCleanupCandidates(root);
  assert.equal(inventory.candidates.some(item => item.relativePath === 'pkg/__pycache__'), false);
  assert.equal(fs.readFileSync(authoritative, 'utf8'), 'shared authoritative bytes');
});

test('per-target adapter failures are isolated, restored when unchanged, and receipted', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const inventory = await scanCleanupCandidates(root);
  const result = await executeCleanup({
    root, candidates: inventory.candidates, ids: inventory.candidates.map(item => item.id), disposition: 'recycle', receiptDir: path.join(root, '.receipts'),
    deletePath: async (target, options) => {
      if (options.originalPath.endsWith(`pkg${path.sep}__pycache__`)) {
        const error = new Error('locked by another process');
        error.code = 'EPERM';
        throw error;
      }
      await fs.promises.rm(target, { recursive: true });
    }
  });
  const failed = result.receipt.resources.find(item => item.relative_path === 'pkg/__pycache__');
  const succeeded = result.receipt.resources.find(item => item.relative_path === '.pytest_cache');
  assert.equal(failed.result, 'failed-restored');
  assert.equal(failed.restored_to_original_path, true);
  assert.match(failed.error, /^EPERM:/);
  assert.equal(succeeded.result, 'moved-to-recycle-bin');
  assert.equal(fs.existsSync(path.join(root, 'pkg', '__pycache__', 'module.pyc')), true);
  assert.equal(fs.existsSync(path.join(root, '.pytest_cache')), false);
  assert.equal(result.receipt.resources_reclaimed, 1);
});

test('partial adapter deletion is retained at the staging path and never overstated', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const inventory = await scanCleanupCandidates(root);
  const selected = inventory.candidates.find(item => item.relativePath === 'pkg/__pycache__');
  const result = await executeCleanup({
    root, candidates: inventory.candidates, ids: [selected.id], disposition: 'recycle', receiptDir: path.join(root, '.receipts'),
    deletePath: async target => {
      await fs.promises.rm(path.join(target, 'module.pyc'));
      const error = new Error('recycle operation stopped after partial mutation');
      error.code = 'EACCES';
      throw error;
    }
  });
  const resource = result.receipt.resources[0];
  assert.equal(resource.result, 'failed-partial-retained');
  assert.equal(result.receipt.resources_reclaimed, 0);
  assert.equal(fs.existsSync(selected.path), false);
  assert.equal(fs.existsSync(path.join(root, resource.staging_relative_path)), true);
});

test('adapter error after disappearance is explicitly uncertain instead of reclaimed', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const inventory = await scanCleanupCandidates(root);
  const selected = inventory.candidates.find(item => item.relativePath === 'pkg/__pycache__');
  const result = await executeCleanup({
    root, candidates: inventory.candidates, ids: [selected.id], disposition: 'recycle', receiptDir: path.join(root, '.receipts'),
    deletePath: async target => {
      await fs.promises.rm(target, { recursive: true });
      const error = new Error('trash API lost acknowledgement');
      error.code = 'EIO';
      throw error;
    }
  });
  assert.equal(result.receipt.resources[0].result, 'disposition-uncertain');
  assert.equal(result.receipt.resources_reclaimed, 0);
  assert.equal(result.receipt.resources_uncertain, 1);
});

test('a concurrently recreated cache at the original path is preserved', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const inventory = await scanCleanupCandidates(root);
  const selected = inventory.candidates.find(item => item.relativePath === 'pkg/__pycache__');
  const result = await executeCleanup({
    root, candidates: inventory.candidates, ids: [selected.id], disposition: 'permanent', receiptDir: path.join(root, '.receipts'),
    deletePath: async (target, options) => {
      fs.mkdirSync(options.originalPath);
      fs.writeFileSync(path.join(options.originalPath, 'new.pyc'), 'new concurrent cache');
      await fs.promises.rm(target, { recursive: true });
    }
  });
  assert.equal(result.receipt.resources[0].result, 'permanently-reclaimed');
  assert.equal(result.receipt.resources[0].replacement_detected_at_original_path, true);
  assert.equal(fs.readFileSync(path.join(selected.path, 'new.pyc'), 'utf8'), 'new concurrent cache');
});

test('cross-device style adapter errors fail one target closed with a durable receipt', async t => {
  const root = fixture();
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const inventory = await scanCleanupCandidates(root);
  const selected = inventory.candidates.find(item => item.relativePath === 'pkg/__pycache__');
  const result = await executeCleanup({
    root, candidates: inventory.candidates, ids: [selected.id], disposition: 'recycle', receiptDir: path.join(root, '.receipts'),
    deletePath: async () => {
      const error = new Error('cross-device recycle move denied');
      error.code = 'EXDEV';
      throw error;
    }
  });
  assert.equal(result.receipt.resources[0].result, 'failed-restored');
  assert.match(result.receipt.resources[0].error, /^EXDEV:/);
  assert.equal(fs.existsSync(path.join(selected.path, 'module.pyc')), true);
  assert.equal(JSON.parse(fs.readFileSync(result.receiptPath, 'utf8')).resources[0].result, 'failed-restored');
});

test('unicode and deep cache paths scan and clean without path truncation', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-cleanup-unicode-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  let parent = root;
  for (let index = 0; index < 12; index += 1) {
    parent = path.join(parent, `层-${index}-${'x'.repeat(12)}`);
  }
  const target = path.join(parent, '__pycache__');
  assert.ok(target.length > 260, `expected a >260 character test path, got ${target.length}`);
  fs.mkdirSync(target, { recursive: true });
  fs.writeFileSync(path.join(target, 'módulo-数据.pyc'), 'generated');
  const inventory = await scanCleanupCandidates(root);
  assert.equal(inventory.candidates.length, 1);
  const result = await executeCleanup({
    root, candidates: inventory.candidates, ids: [inventory.candidates[0].id], disposition: 'permanent', receiptDir: path.join(root, '.receipts'),
    deletePath: targetPath => fs.promises.rm(targetPath, { recursive: true })
  });
  assert.equal(result.receipt.resources[0].result, 'permanently-reclaimed');
  assert.equal(fs.existsSync(target), false);
});
