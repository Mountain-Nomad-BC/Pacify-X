'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { inventoryTeamPack, inventoryTeamPackAsync, stageTeamPack, workerAdapters } = require('../src/teamFabricManager');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-team-pack-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.writeFileSync(path.join(root, 'LICENSE'), 'Apache-2.0');
  fs.mkdirSync(path.join(root, 'teams', 'builders'), { recursive: true });
  fs.writeFileSync(path.join(root, 'teams', 'builders', 'TEAM.md'), '---\nname: Builders\n---\n# Builders\n');
  fs.mkdirSync(path.join(root, 'skills', 'sorter'), { recursive: true });
  fs.writeFileSync(path.join(root, 'skills', 'sorter', 'SKILL.md'), '---\nname: data-sort-dry-run-picker\ndescription: test\n---\n');
  return root;
}

test('team pack inventory is complete, hashed, dry-run, and collision-aware', t => {
  const source = fixture(t);
  const preview = inventoryTeamPack(source, ['data-sort-dry-run-picker']);
  assert.equal(preview.dry_run, true);
  assert.equal(preview.totals.files, 3);
  assert.equal(preview.totals.entities, 2);
  assert.equal(preview.totals.collisions, 1);
  assert.match(preview.manifest_sha256, /^[a-f0-9]{64}$/);
  assert.equal(JSON.stringify(preview).includes(source), false);
});

test('team pack inventory can run in an owned bounded worker', async t => {
  const source = fixture(t);
  const preview = await inventoryTeamPackAsync(source, ['data-sort-dry-run-picker'], { timeoutMs: 5000 });
  assert.equal(preview.totals.files, 3);
  assert.equal(preview.totals.collisions, 1);
});

test('staging writes candidates only and never mutates the canonical registry', t => {
  const source = fixture(t); const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'px-team-workspace-'));
  t.after(() => fs.rmSync(workspace, { recursive: true, force: true }));
  const preview = inventoryTeamPack(source, ['data-sort-dry-run-picker']);
  const result = stageTeamPack(workspace, preview, { collisionMode: 'rename' });
  assert.equal(result.receipt.canonical_registry_mutated, false);
  assert.equal(result.receipt.staged_count, 2);
  assert.equal(fs.existsSync(result.path), true);
  assert.match(result.receipt.staged.find(item => item.kind === 'skill').staged_slug, /candidate/);
});

test('worker adapter doctor separates executor, authentication and billing identity', () => {
  const rows = workerAdapters({ workspaceRoot: process.cwd(), extensionRoot: path.resolve(__dirname, '..'), appName: 'Antigravity', codexAuthenticated: true, ollamaEnabled: false });
  const codex = rows.find(item => item.id === 'codex-cli');
  assert.equal(codex.status, 'ready');
  assert.equal(codex.authentication_identity, 'ChatGPT verified');
  assert.equal(codex.billing_identity, 'not-inferred');
  assert.equal(codex.billable_api_fallback, false);
});
