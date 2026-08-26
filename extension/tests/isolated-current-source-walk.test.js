'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { excludedEnginePath, reconcilePrelaunchFailure, stageDisposableEngine, stageOwnedKnowledgeFixture } = require('../scripts/run-isolated-current-source-walk');
const { markOwnedHostWorkspace } = require('../scripts/owned-vscode-test-cache');

const digest = target => crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex');

function fixture(t, { complete = true } = {}) {
  const source = fs.mkdtempSync(path.join(os.tmpdir(), 'px-engine-source-'));
  const owned = fs.mkdtempSync(path.join(os.tmpdir(), 'px-engine-owned-'));
  t.after(() => fs.rmSync(source, { recursive: true, force: true }));
  t.after(() => fs.rmSync(owned, { recursive: true, force: true }));
  fs.mkdirSync(path.join(source, 'runtime'), { recursive: true });
  fs.writeFileSync(path.join(source, 'runtime', 'cli.py'), 'print("fixture")\n');
  if (complete) {
    fs.mkdirSync(path.join(source, 'registry'), { recursive: true });
    fs.writeFileSync(path.join(source, 'registry', 'engine_identity.json'), '{"engine":"fixture"}\n');
  }
  fs.mkdirSync(path.join(source, 'evidence'), { recursive: true });
  fs.writeFileSync(path.join(source, 'evidence', 'retained.json'), '{}\n');
  fs.mkdirSync(path.join(source, '.git'), { recursive: true });
  fs.writeFileSync(path.join(source, '.git', 'config'), 'must-not-copy\n');
  fs.mkdirSync(path.join(source, 'extension', 'node_modules', 'fixture'), { recursive: true });
  fs.writeFileSync(path.join(source, 'extension', 'node_modules', 'fixture', 'index.js'), 'must-not-copy\n');
  return { source, owned };
}

test('disposable engine copies current state beneath the owned root and excludes non-engine caches', t => {
  const { source, owned } = fixture(t);
  const result = stageDisposableEngine(source, owned);
  assert.equal(path.dirname(result.root), fs.realpathSync.native(owned));
  assert.equal(fs.lstatSync(result.root).isSymbolicLink(), false);
  assert.equal(fs.existsSync(path.join(result.root, 'evidence')), false);
  assert.equal(fs.existsSync(path.join(result.root, '.git')), false);
  assert.equal(fs.existsSync(path.join(result.root, 'extension', 'node_modules')), false);
  assert.equal(result.required_file_sha256['runtime/cli.py'], digest(path.join(source, 'runtime', 'cli.py')));
  assert.equal(result.required_file_sha256['registry/engine_identity.json'], digest(path.join(source, 'registry', 'engine_identity.json')));
  assert.ok(result.copied_files >= 2);
});

test('disposable engine fails closed and reclaims its partial copy when required identity is absent', t => {
  const { source, owned } = fixture(t, { complete: false });
  assert.throws(() => stageDisposableEngine(source, owned), /owned-engine-required-file-missing:registry\/engine_identity\.json/);
  assert.equal(fs.existsSync(path.join(owned, 'engine')), false);
});

test('engine copy exclusion is exact and does not hide similarly named source directories', () => {
  assert.equal(excludedEnginePath('.git/objects/one'), true);
  assert.equal(excludedEnginePath('extension/node_modules/pkg/index.js'), true);
  assert.equal(excludedEnginePath('evidence/retained.json'), true);
  assert.equal(excludedEnginePath('runtime/__pycache__/cli.pyc'), true);
  assert.equal(excludedEnginePath('.engineering-bootstrap/test-evidence/adversarial-repair-gates/run/linked-fixture'), true);
  assert.equal(excludedEnginePath('.engineering-bootstrap/test-evidence/sections/dashboard-extension.json'), true);
  assert.equal(excludedEnginePath('.engineering-bootstrap/operation-bus/wal/.wal.lock'), true);
  assert.equal(excludedEnginePath('registry/.operational-gap-ledger.lock'), true);
  assert.equal(excludedEnginePath('registry/lock-policy.json'), false);
  assert.equal(excludedEnginePath('.engineering-bootstrap/operation-bus/wal/segment-1.jsonl'), true);
  assert.equal(excludedEnginePath('.engineering-bootstrap/project-map/architecture-graph.json'), false);
  assert.equal(excludedEnginePath('runtime/legitimate.py'), false);
  assert.equal(excludedEnginePath('docs/.git-notes.md'), false);
});

test('disposable engine rejects a linked source root before copying', t => {
  const { source, owned } = fixture(t);
  const links = fs.mkdtempSync(path.join(os.tmpdir(), 'px-engine-links-'));
  t.after(() => fs.rmSync(links, { recursive: true, force: true }));
  const linkedSource = path.join(links, 'source-link');
  try { fs.symlinkSync(source, linkedSource, process.platform === 'win32' ? 'junction' : 'dir'); }
  catch (error) {
    if (['EPERM', 'EACCES', 'UNKNOWN'].includes(error?.code)) return t.skip(`directory links unavailable: ${error.code}`);
    throw error;
  }
  assert.throws(() => stageDisposableEngine(linkedSource, owned), /owned-engine-root-linked/);
  assert.equal(fs.existsSync(path.join(owned, 'engine')), false);
});

test('owned Knowledge fixture creates one exact source registry without live-project state', t => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'px-knowledge-workspace-'));
  const engine = fs.mkdtempSync(path.join(os.tmpdir(), 'px-knowledge-engine-'));
  t.after(() => fs.rmSync(workspace, { recursive: true, force: true }));
  t.after(() => fs.rmSync(engine, { recursive: true, force: true }));
  fs.mkdirSync(path.join(engine, 'registry'));
  fs.writeFileSync(path.join(engine, 'registry', 'knowledge_sources.json'), `${JSON.stringify({ schema_version: '2.0', knowledge_sources: [{ id: 'existing', status: 'active', kind: 'local_file', visibility: ['local'], location: 'existing.md', uses: [] }] }, null, 2)}\n`);
  const result = stageOwnedKnowledgeFixture(workspace, engine);
  assert.equal(result.source_id, 'source:px-owned-knowledge-lifecycle');
  assert.equal(result.source_relative, 'knowledge/px-owned-lifecycle-source.md');
  assert.match(result.source_sha256, /^[0-9a-f]{64}$/);
  assert.equal(result.evidence_ref, `sha256:${result.source_sha256}`);
  const registry = JSON.parse(fs.readFileSync(path.join(workspace, 'registry', 'knowledge_sources.json'), 'utf8'));
  assert.deepEqual(registry, {
    schema_version: '2.0',
    knowledge_sources: [{ id: result.source_id, status: 'active', kind: 'local_file', visibility: ['local'], location: result.source_relative, uses: [] }]
  });
  assert.equal(digest(path.join(workspace, result.source_relative)), result.source_sha256);
  assert.equal(digest(path.join(engine, result.source_relative)), result.source_sha256);
  const engineRegistry = JSON.parse(fs.readFileSync(path.join(engine, 'registry', 'knowledge_sources.json'), 'utf8'));
  assert.deepEqual(engineRegistry.knowledge_sources.map(item => item.id), ['existing', result.source_id]);
  assert.equal(digest(path.join(engine, 'registry', 'knowledge_sources.json')), result.engine_registry_sha256);
});

test('owned Knowledge fixture refuses to overwrite any pre-existing target', t => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'px-knowledge-workspace-'));
  t.after(() => fs.rmSync(workspace, { recursive: true, force: true }));
  fs.mkdirSync(path.join(workspace, 'knowledge'));
  assert.throws(() => stageOwnedKnowledgeFixture(workspace), /owned-knowledge-target-already-exists:knowledge/);
  assert.equal(fs.existsSync(path.join(workspace, 'registry')), false);
});

test('prelaunch staging failure is evidenced and its exact marked root is reclaimed', t => {
  const container = fs.mkdtempSync(path.join(os.tmpdir(), 'px-prelaunch-reconcile-'));
  const ownedRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'pacify-x-current-source-walk-'));
  t.after(() => fs.rmSync(container, { recursive: true, force: true }));
  t.after(() => { if (fs.existsSync(ownedRoot)) fs.rmSync(ownedRoot, { recursive: true, force: true }); });
  markOwnedHostWorkspace(ownedRoot, 'test-prelaunch-failure');
  const reportPath = path.join(container, 'prelaunch-report.json');
  const walkOutput = path.join(container, 'walk-output');
  const report = reconcilePrelaunchFailure(ownedRoot, reportPath, walkOutput, new Error('bounded-stage-failure'));
  assert.equal(report.phase, 'prelaunch-staging');
  assert.equal(report.owner_lifecycle.host_started, false);
  assert.equal(report.cleanup.reclaimed, true);
  assert.equal(fs.existsSync(ownedRoot), false);
  assert.equal(JSON.parse(fs.readFileSync(reportPath, 'utf8')).error.includes('bounded-stage-failure'), true);
});

test('launcher exposes an exact Knowledge-only mode without claiming full completion', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--knowledge-lifecycle-only'\)/);
  assert.match(source, /PX_OPERATIONAL_KNOWLEDGE_LIFECYCLE_ONLY: '1'/);
  assert.match(source, /PX_OWNED_KNOWLEDGE_SOURCE_ID: config\.knowledgeFixture\.source_id/);
  assert.match(source, /PX_OWNED_KNOWLEDGE_SOURCE_SHA256: config\.knowledgeFixture\.source_sha256/);
  assert.match(source, /focused-\$\{focusedProfile\}-walk/);
  assert.match(source, /full_operational_completion_claimed: focusedProfile \? false/);
  assert.match(source, /focused-launcher-modes-are-mutually-exclusive/);
});

test('launcher exposes an exact Studio-only mode without claiming full completion', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--studio-lifecycle-only'\)/);
  assert.match(source, /PX_OPERATIONAL_STUDIO_LIFECYCLE_ONLY: '1'/);
  assert.match(source, /focusedProfile = configurationOnly \? 'reversible-configuration' : studioLifecycleOnly \? 'studio-lifecycle'/);
  assert.match(source, /focused-\$\{focusedProfile\}-walk/);
  assert.match(source, /full_operational_completion_claimed: focusedProfile \? false/);
});

test('launcher exposes an exact reversible-configuration-only mode with bounded evidence', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--configuration-only'\)/);
  assert.match(source, /PX_OPERATIONAL_CONFIGURATION_ONLY: '1'/);
  assert.match(source, /focusedProfile = configurationOnly \? 'reversible-configuration'/);
  assert.match(source, /full_operational_completion_claimed: focusedProfile \? false/);
});
