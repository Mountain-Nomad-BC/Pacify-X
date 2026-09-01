'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { acquireWalkOwnership, appendHostProgress, boundedDelay, excludedEnginePath, ownedExternalNetworkDeniedEnvironment, reconcileOwnedPrelaunchFailure, reconcilePrelaunchFailure, reserveLoopbackPort, retainedHostProgress, retainedProfileProgress, stageDisposableEngine, stageOwnedGitAuthority, stageOwnedHostBoundaryFixture, stageOwnedKnowledgeFixture, stageOwnedProviderPaginationFixture, waitForIsolatedStorageBoundary } = require('../scripts/run-isolated-current-source-walk');
const { acquireHostLease } = require('../scripts/owned-host-runner');
const { cachedVSCodeLayout, markOwnedHostWorkspace } = require('../scripts/owned-vscode-test-cache');
const { gitSnapshot } = require('../src/contextBridge');

const digest = target => crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex');

test('owned external-network denial sentinel requires both exact dead-loopback proxies', () => {
  assert.equal(ownedExternalNetworkDeniedEnvironment({ HTTP_PROXY: 'http://127.0.0.1:9', HTTPS_PROXY: 'http://127.0.0.1:9' }), true);
  assert.equal(ownedExternalNetworkDeniedEnvironment({ HTTP_PROXY: 'http://127.0.0.1:9', HTTPS_PROXY: 'http://127.0.0.1:10' }), false);
  assert.equal(ownedExternalNetworkDeniedEnvironment({ HTTP_PROXY: 'http://proxy.example', HTTPS_PROXY: 'http://proxy.example' }), false);
});

test('owned cached VS Code layout requires the exact complete nonlink Windows archive', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-cache-layout-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const directory = path.join(root, 'vscode-win32-x64-archive-1.132.1');
  fs.mkdirSync(directory);
  fs.writeFileSync(path.join(directory, 'is-complete'), '');
  fs.writeFileSync(path.join(directory, 'Code.exe'), 'fixture');
  const layout = cachedVSCodeLayout(root, '1.132.1', { platform: 'win32', arch: 'x64' });
  assert.equal(layout.executable, path.join(directory, 'Code.exe'));
  fs.rmSync(path.join(directory, 'is-complete'));
  assert.throws(() => cachedVSCodeLayout(root, '1.132.1', { platform: 'win32', arch: 'x64' }), /file-missing:is-complete/);
  assert.throws(() => cachedVSCodeLayout(root, 'latest', { platform: 'win32', arch: 'x64' }), /version-invalid/);
  assert.throws(() => cachedVSCodeLayout(root, '1.132.1', { platform: 'linux', arch: 'x64' }), /platform-unsupported/);
});

function runIsolatedCacheOwner(t, body) {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-cache-owner-env-'));
  t.after(() => fs.rmSync(temporaryRoot, { recursive: true, force: true }));
  const modulePath = path.join(__dirname, '..', 'scripts', 'owned-vscode-test-cache.js');
  const child = childProcess.spawnSync(process.execPath, ['-e', `
    const fs = require('node:fs');
    const path = require('node:path');
    const crypto = require('node:crypto');
    const api = require(${JSON.stringify(modulePath)});
    const digest = target => crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex');
    ${body}
  `], {
    encoding: 'utf8',
    env: { ...process.env, TEMP: temporaryRoot, TMP: temporaryRoot },
    windowsHide: true
  });
  assert.equal(child.status, 0, child.stderr || child.stdout);
  return JSON.parse(child.stdout);
}

test('owned cache validation fails before effects for malformed versions', t => {
  const result = runIsolatedCacheOwner(t, `
    fs.mkdirSync(api.CACHE_ROOT, { recursive: true });
    const marker = path.join(api.CACHE_ROOT, '.pacify-x-owned-cache.json');
    const sentinel = path.join(api.CACHE_ROOT, 'retained-sentinel');
    fs.writeFileSync(marker, JSON.stringify({ schema_version: 'px.owned-vscode-test-cache/1.0', owner: 'PACIFY-X', retained_versions: ['[object Object]', '1.132.1'] }));
    fs.mkdirSync(sentinel);
    fs.writeFileSync(path.join(sentinel, 'evidence.txt'), 'retain');
    const before = digest(marker);
    const errors = [];
    for (const operation of [api.ensureOwnedVscodeTestCache, api.resolveOwnedCachedVSCode]) {
      try { operation({ version: '1.132.1' }); } catch (error) { errors.push(error.message); }
    }
    process.stdout.write(JSON.stringify({ errors, markerUnchanged: digest(marker) === before, sentinelPresent: fs.existsSync(path.join(sentinel, 'evidence.txt')) }));
  `);
  assert.deepEqual(result.errors, ['vscode-test-cache-version-invalid', 'vscode-test-cache-version-invalid']);
  assert.equal(result.markerUnchanged, true);
  assert.equal(result.sentinelPresent, true);
});

test('owned cache resolution is read-only and ensure never prunes retained evidence', t => {
  const result = runIsolatedCacheOwner(t, `
    fs.mkdirSync(api.CACHE_ROOT, { recursive: true });
    const marker = path.join(api.CACHE_ROOT, '.pacify-x-owned-cache.json');
    const directory = path.join(api.CACHE_ROOT, 'vscode-win32-x64-archive-1.132.1');
    const archive = path.join(api.CACHE_ROOT, 'vscode-win32-x64-archive-1.132.1.zip');
    const quarantine = path.join(api.CACHE_ROOT, 'vscode-win32-x64-archive-1.132.1-quarantine-r1');
    fs.writeFileSync(marker, JSON.stringify({ schema_version: 'px.owned-vscode-test-cache/1.0', owner: 'PACIFY-X', retained_versions: ['[object Object]', '1.132.1'] }));
    fs.mkdirSync(directory);
    fs.writeFileSync(path.join(directory, 'is-complete'), '');
    fs.writeFileSync(path.join(directory, 'Code.exe'), 'fixture');
    fs.writeFileSync(archive, 'retained-archive');
    fs.mkdirSync(quarantine);
    fs.writeFileSync(path.join(quarantine, 'evidence.txt'), 'retained-quarantine');
    const markerBeforeResolve = digest(marker);
    const layout = api.resolveOwnedCachedVSCode('1.132.1');
    const markerUnchangedByResolve = digest(marker) === markerBeforeResolve;
    const ensured = api.ensureOwnedVscodeTestCache('1.132.1');
    process.stdout.write(JSON.stringify({
      executable: layout.executable,
      markerUnchangedByResolve,
      pruned: ensured.pruned,
      archivePresent: fs.existsSync(archive),
      quarantinePresent: fs.existsSync(path.join(quarantine, 'evidence.txt')),
      retainedVersions: JSON.parse(fs.readFileSync(marker, 'utf8')).retained_versions
    }));
  `);
  assert.match(result.executable, /Code\.exe$/);
  assert.equal(result.markerUnchangedByResolve, true);
  assert.deepEqual(result.pruned, []);
  assert.equal(result.archivePresent, true);
  assert.equal(result.quarantinePresent, true);
  assert.deepEqual(result.retainedVersions, ['1.132.1']);
});

test('sanitized host progress survives a missing child result and rejects unknown stages', t => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'px-host-progress-'));
  t.after(() => fs.rmSync(output, { recursive: true, force: true }));
  appendHostProgress(output, 'child-started', { pid: 123, secret: 'must-not-persist' });
  appendHostProgress(output, 'cache-ready');
  const retained = retainedHostProgress(output);
  assert.equal(retained.valid, true);
  assert.equal(retained.record_count, 2);
  assert.equal(retained.last_record.stage, 'cache-ready');
  assert.doesNotMatch(fs.readFileSync(path.join(output, 'host-progress.ndjson'), 'utf8'), /must-not-persist|secret/);
  assert.throws(() => appendHostProgress(output, 'unknown-stage'), /stage-invalid/);
  for (const stage of ['walker-closed', 'native-helper-stop-requested', 'native-helper-closed', 'vscode-termination-started', 'vscode-closed', 'child-result-written']) {
    appendHostProgress(output, stage);
  }
  assert.equal(retainedHostProgress(output).last_record.stage, 'child-result-written');
});

test('loopback port reservation is bounded and returns only a valid released port', async () => {
  const port = await reserveLoopbackPort(1_000);
  assert.ok(Number.isSafeInteger(port) && port >= 1024 && port <= 65535);
  const stalled = { once() {}, listen() {}, close(callback) { callback?.(); }, address() { return null; } };
  await assert.rejects(() => reserveLoopbackPort(10, () => stalled), /loopback-port-listen-timeout/);
});

test('native helper finalizer uses a defined bounded delay', async () => {
  await boundedDelay(1);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /Promise\.race\(\[helperExit, boundedDelay\(5_000\)\.then\(\(\) => null\)\]\)/);
  assert.doesNotMatch(source, /\bwait\(5_000\)/);
});

test('owned VS Code host launches at a deterministic width above every dashboard visibility breakpoint', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /'--new-window',\s*'--window-size=1600,1000',\s*'--no-sandbox'/);
});

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

test('timeout evidence retains bounded hash-bound physical profile progress', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-profile-progress-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const records = [
    { schema_version: 'px.operational-profile-progress/1.0', observed_utc: '2026-08-27T00:00:00Z', profile: 'host-boundary', state: 'started' },
    { schema_version: 'px.operational-profile-progress/1.0', observed_utc: '2026-08-27T00:00:30Z', profile: 'host-boundary-control', control_id: 'one', state: 'returned', error_count: 0, errors: [] },
    { schema_version: 'px.operational-profile-progress/1.0', observed_utc: '2026-08-27T00:01:00Z', profile: 'host-boundary', state: 'returned', error_count: 1, errors: ['exact-failure'] },
    { schema_version: 'px.operational-profile-progress/1.0', observed_utc: '2026-08-27T00:01:01Z', profile: 'dependent', state: 'skipped', error_count: 1, errors: ['dependency-failed'] },
    { schema_version: 'px.operational-profile-progress/1.0', observed_utc: '2026-08-27T00:01:02Z', profile: 'thrown', state: 'threw', error_count: 1, errors: ['bounded-failure'] }
  ];
  const target = path.join(root, 'profile-progress.ndjson');
  fs.writeFileSync(target, `${records.map(record => JSON.stringify(record)).join('\n')}\n`, 'utf8');
  const retained = retainedProfileProgress(root);
  assert.equal(retained.valid, true);
  assert.equal(retained.sha256, digest(target));
  assert.equal(retained.record_count, 5);
  assert.equal(retained.started_count, 1);
  assert.equal(retained.returned_count, 2);
  assert.equal(retained.terminal_count, 4);
  assert.equal(retained.terminal_with_errors, 3);
  assert.equal(retained.returned_with_errors, 1);
  assert.deepEqual(retained.last_record, records[4]);
  fs.writeFileSync(target, '{"schema_version":"wrong"}\n', 'utf8');
  assert.equal(retainedProfileProgress(root).valid, false);
});

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
  assert.equal(excludedEnginePath('.engineering-bootstrap/diagnostics/retained-workspaces/source/runtime.py'), true);
  assert.equal(excludedEnginePath('.engineering-bootstrap/test-evidence/adversarial-repair-gates/run/linked-fixture'), true);
  assert.equal(excludedEnginePath('.engineering-bootstrap/test-evidence/sections/dashboard-extension.json'), true);
  assert.equal(excludedEnginePath('.engineering-bootstrap/operation-bus/wal/.wal.lock'), true);
  assert.equal(excludedEnginePath('registry/.operational-gap-ledger.lock'), true);
  assert.equal(excludedEnginePath('registry/lock-policy.json'), false);
  assert.equal(excludedEnginePath('.engineering-bootstrap/operation-bus/wal/segment-1.jsonl'), true);
  assert.equal(excludedEnginePath('.engineering-bootstrap/project-map/architecture-graph.json'), false);
  assert.equal(excludedEnginePath('.engineering-bootstrap/diagnostics-live/runtime.py'), false);
  assert.equal(excludedEnginePath('runtime/legitimate.py'), false);
  assert.equal(excludedEnginePath('docs/.git-notes.md'), false);
});

test('disposable engine skips linked retained diagnostics but still copies canonical source', t => {
  const { source, owned } = fixture(t);
  const retained = path.join(source, '.engineering-bootstrap', 'diagnostics', 'retained-workspaces');
  fs.mkdirSync(retained, { recursive: true });
  const linked = path.join(retained, 'linked-source');
  try { fs.symlinkSync(source, linked, process.platform === 'win32' ? 'junction' : 'dir'); }
  catch (error) {
    if (['EPERM', 'EACCES', 'UNKNOWN'].includes(error?.code)) return t.skip(`directory links unavailable: ${error.code}`);
    throw error;
  }
  fs.mkdirSync(path.join(source, 'runtime', 'canonical'), { recursive: true });
  fs.writeFileSync(path.join(source, 'runtime', 'canonical', 'live.py'), 'LIVE = True\n');

  const result = stageDisposableEngine(source, owned);

  assert.equal(fs.existsSync(path.join(result.root, '.engineering-bootstrap', 'diagnostics')), false);
  assert.equal(fs.readFileSync(path.join(result.root, 'runtime', 'canonical', 'live.py'), 'utf8'), 'LIVE = True\n');
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

test('rejected duplicate acquires no temporary or evidence namespace', t => {
  const container = fs.mkdtempSync(path.join(os.tmpdir(), 'px-walk-owner-custody-'));
  const lockPath = path.join(container, 'host.lock.json');
  const reportPath = path.join(container, 'owner-report.json');
  const outputPath = path.join(container, 'owner-output');
  t.after(() => fs.rmSync(container, { recursive: true, force: true }));
  const owner = acquireHostLease({ lockPath });
  t.after(() => owner.release());
  let temporaryAllocationAttempted = false;

  assert.throws(() => acquireWalkOwnership({
    lockPath,
    makeTemporaryRoot: () => {
      temporaryAllocationAttempted = true;
      return fs.mkdtempSync(path.join(container, 'duplicate-root-'));
    }
  }), /owned-host-already-running/);

  assert.equal(temporaryAllocationAttempted, false);
  assert.equal(fs.existsSync(reportPath), false);
  assert.equal(fs.existsSync(outputPath), false);
  assert.deepEqual(fs.readdirSync(container), ['host.lock.json']);
});

test('prelaunch evidence collision still releases the acquired owner lease', t => {
  const container = fs.mkdtempSync(path.join(os.tmpdir(), 'px-walk-prelaunch-collision-'));
  const lockPath = path.join(container, 'host.lock.json');
  const reportPath = path.join(container, 'existing-report.json');
  const walkOutput = path.join(container, 'owner-output');
  t.after(() => fs.rmSync(container, { recursive: true, force: true }));
  fs.writeFileSync(reportPath, '{}\n', { encoding: 'utf8', flag: 'wx' });
  const ownership = acquireWalkOwnership({
    lockPath,
    makeTemporaryRoot: () => fs.mkdtempSync(path.join(os.tmpdir(), 'pacify-x-current-source-walk-')),
    ownershipLabel: 'test-prelaunch-evidence-collision'
  });

  assert.throws(
    () => reconcileOwnedPrelaunchFailure(ownership, reportPath, walkOutput, new Error('staging-failed')),
    error => error?.code === 'EEXIST'
  );
  assert.equal(fs.existsSync(ownership.temporaryRoot), false);
  const replacement = acquireHostLease({ lockPath });
  replacement.release();
  assert.equal(fs.existsSync(lockPath), false);
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

test('launcher exposes an exact host-boundary-only mode without Studio setup or a full completion claim', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--host-boundary-only'\)/);
  assert.match(source, /PX_OPERATIONAL_HOST_BOUNDARY_ONLY: '1'/);
  assert.match(source, /hostBoundaryOnly \? 'host-boundary' : nativeDialogOnly \? 'native-dialog-boundary' : codexHandoffOnly \? 'codex-handoff' : errorIndicatorsOnly \? 'error-indicators' : lateCardRepairOnly \? 'late-card-repair' : null/);
  assert.match(source, /!config\.knowledgeLifecycleOnly && !config\.hostBoundaryOnly && !config\.nativeDialogOnly[\s\S]*PX_OPERATIONAL_EXERCISE_STUDIO_APPROVAL/);
  assert.match(source, /full_operational_completion_claimed: focusedProfile \? false/);
  assert.match(source, /--host-boundary-only/);
});

test('launcher exposes an exact native-dialog-only mode without unrelated fixtures or a full completion claim', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--native-dialog-only'\)/);
  assert.match(source, /PX_OPERATIONAL_NATIVE_DIALOG_ONLY: '1'/);
  assert.match(source, /owned_windows_native_input\.py/);
  assert.match(source, /native_input_helper_pid/);
  assert.match(source, /PX_OWNED_NATIVE_INPUT_SECRET: config\.nativeInputSecret/);
  assert.match(source, /native_input_helper_termination_verified/);
  assert.match(source, /nativeDialogOnly \? 'native-dialog-boundary' : codexHandoffOnly \? 'codex-handoff' : errorIndicatorsOnly \? 'error-indicators' : lateCardRepairOnly \? 'late-card-repair' : null/);
  assert.match(source, /focused-launcher-modes-are-mutually-exclusive/);
  assert.match(source, /postAuditLongRunning && \(bootstrapOnly \|\| configurationOnly \|\| studioLifecycleOnly \|\| knowledgeLifecycleOnly \|\| hostBoundaryOnly \|\| nativeDialogOnly \|\| codexHandoffOnly \|\| errorIndicatorsOnly \|\| lateCardRepairOnly\)/);
  assert.match(source, /!config\.hostBoundaryOnly && !config\.nativeDialogOnly[\s\S]*PX_OPERATIONAL_EXERCISE_STUDIO_APPROVAL/);
  assert.match(source, /studioLifecycleOnly \|\| nativeDialogOnly \|\| codexHandoffOnly \? null : stageOwnedKnowledgeFixture/);
  assert.match(source, /prepare\(temporaryRoot, walkOutput, vsixPath, bootstrapOnly, configurationOnly, studioLifecycleOnly, knowledgeLifecycleOnly, hostBoundaryOnly, nativeDialogOnly, codexHandoffOnly, errorIndicatorsOnly, lateCardRepairOnly, postAuditLongRunning\)/);
  assert.match(source, /full_operational_completion_claimed: focusedProfile \? false/);
  assert.match(source, /timeoutMs: postAuditLongRunning \? 3_600_000 : 1_800_000/);
});

test('launcher exposes an exact Codex-handoff-only mode without unrelated fixtures or a full completion claim', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--codex-handoff-only'\)/);
  assert.match(source, /PX_OPERATIONAL_CODEX_HANDOFF_ONLY: '1'/);
  assert.match(source, /codexHandoffOnly \? 'codex-handoff' : errorIndicatorsOnly \? 'error-indicators' : lateCardRepairOnly \? 'late-card-repair' : null/);
  assert.match(source, /focused-launcher-modes-are-mutually-exclusive/);
  assert.match(source, /postAuditLongRunning && \(bootstrapOnly \|\| configurationOnly \|\| studioLifecycleOnly \|\| knowledgeLifecycleOnly \|\| hostBoundaryOnly \|\| nativeDialogOnly \|\| codexHandoffOnly \|\| errorIndicatorsOnly \|\| lateCardRepairOnly\)/);
  assert.match(source, /!config\.nativeDialogOnly && !config\.codexHandoffOnly[\s\S]*PX_OPERATIONAL_EXERCISE_STUDIO_APPROVAL/);
  assert.match(source, /studioLifecycleOnly \|\| nativeDialogOnly \|\| codexHandoffOnly \? null : stageOwnedKnowledgeFixture/);
  assert.match(source, /prepare\(temporaryRoot, walkOutput, vsixPath, bootstrapOnly, configurationOnly, studioLifecycleOnly, knowledgeLifecycleOnly, hostBoundaryOnly, nativeDialogOnly, codexHandoffOnly, errorIndicatorsOnly, lateCardRepairOnly, postAuditLongRunning\)/);
  assert.match(source, /--codex-handoff-only/);
  assert.match(source, /full_operational_completion_claimed: focusedProfile \? false/);
});

test('launcher exposes an exact error-indicators-only mode without unrelated stateful fixtures or a full completion claim', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--error-indicators-only'\)/);
  assert.match(source, /PX_OPERATIONAL_ERROR_INDICATORS_ONLY: '1'/);
  assert.match(source, /errorIndicatorsOnly \? 'error-indicators' : lateCardRepairOnly \? 'late-card-repair' : null/);
  assert.match(source, /\[bootstrapOnly, configurationOnly, studioLifecycleOnly, knowledgeLifecycleOnly, hostBoundaryOnly, nativeDialogOnly, codexHandoffOnly, errorIndicatorsOnly, lateCardRepairOnly\]/);
  assert.match(source, /postAuditLongRunning && \(bootstrapOnly \|\| configurationOnly \|\| studioLifecycleOnly \|\| knowledgeLifecycleOnly \|\| hostBoundaryOnly \|\| nativeDialogOnly \|\| codexHandoffOnly \|\| errorIndicatorsOnly \|\| lateCardRepairOnly\)/);
  assert.match(source, /!config\.codexHandoffOnly && !config\.errorIndicatorsOnly[\s\S]*PX_OPERATIONAL_EXERCISE_STUDIO_APPROVAL/);
  assert.match(source, /prepare\(temporaryRoot, walkOutput, vsixPath, bootstrapOnly, configurationOnly, studioLifecycleOnly, knowledgeLifecycleOnly, hostBoundaryOnly, nativeDialogOnly, codexHandoffOnly, errorIndicatorsOnly, lateCardRepairOnly, postAuditLongRunning\)/);
  assert.match(source, /--error-indicators-only/);
  assert.match(source, /full_operational_completion_claimed: focusedProfile \? false/);
});

test('host-boundary fixture owns one real handoff task and one certified canonical source lifecycle', t => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'px-host-boundary-workspace-'));
  const engine = fs.mkdtempSync(path.join(os.tmpdir(), 'px-host-boundary-engine-'));
  t.after(() => fs.rmSync(workspace, { recursive: true, force: true }));
  t.after(() => fs.rmSync(engine, { recursive: true, force: true }));
  const calls = [];
  fs.mkdirSync(path.join(engine, 'registry'), { recursive: true });
  fs.writeFileSync(path.join(engine, 'registry', 'provider_budget_policy.json'), `${JSON.stringify({ schema_version: 'px.provider-budget-policy/1.0', budgets: [{ budget_id: 'local-development', actor_id: 'pacify-x-local', provider_id: 'ollama', enabled: true, hard_limit_microunits: 0, max_charge_per_request_microunits: 0, unknown_billing: 'deny', fallback_adapter_ids: [] }] }, null, 2)}\n`);
  const projectRoot = path.join(workspace, 'projects', 'px-owned-memory-profile');
  const runtimeCommand = (_engine, args) => {
    calls.push(args);
    const operation = args.slice(0, 2).join(':');
    if (operation === 'workspace:init') return { valid: true, applied: true };
    if (operation === 'workspace:create-project') { fs.mkdirSync(projectRoot, { recursive: true }); return { valid: true, applied: true, project: { project_id: 'prj_px-owned-memory-profile', path: projectRoot } }; }
    if (operation === 'project:activate') return { activated: true };
    if (operation === 'memory:ingest') return { valid: true, outputs: { memory_ids: ['mem_px_owned_host_boundary_b', 'mem_px_owned_host_boundary_a'] } };
    if (operation === 'memory:transition') return { valid: true, applied: true };
    throw new Error(`unexpected runtime operation: ${operation}`);
  };
  const fixture = stageOwnedHostBoundaryFixture(workspace, engine, { runtimeCommand });
  assert.equal(fixture.schema_version, 'px.owned-host-boundary-fixture/1.0');
  assert.equal(fixture.task_id, 'host-boundary-fixture-task');
  assert.equal(fixture.project_id, 'prj_px-owned-memory-profile');
  assert.equal(fixture.memory_id, 'mem_px_owned_host_boundary_a');
  assert.deepEqual(fixture.memory_ids, ['mem_px_owned_host_boundary_a', 'mem_px_owned_host_boundary_b']);
  assert.equal(fixture.memory_record_count, 2);
  assert.equal(fixture.provider_pagination.schema_version, 'px.owned-provider-pagination-fixture/1.0');
  assert.equal(fixture.provider_pagination.provider_count, 2);
  assert.equal(fixture.provider_pagination.owned_provider_id, 'ollama:px-owned-pagination:px-owned-pagination');
  assert.equal(fixture.provider_pagination.local_non_billable, true);
  assert.match(fixture.provider_pagination.policy_before_sha256, /^[a-f0-9]{64}$/);
  assert.match(fixture.provider_pagination.policy_after_sha256, /^[a-f0-9]{64}$/);
  assert.notEqual(fixture.provider_pagination.policy_before_sha256, fixture.provider_pagination.policy_after_sha256);
  assert.match(fixture.coordination_handoff_relative, /^\.engineering-bootstrap\/coordination\/HANDOFF\.md$/);
  assert.match(fixture.memory_source_relative, /^projects\/px-owned-memory-profile\/host-boundary-memory\.md$/);
  assert.match(fixture.coordination_handoff_sha256, /^[a-f0-9]{64}$/);
  assert.match(fixture.memory_source_sha256, /^[a-f0-9]{64}$/);
  assert.deepEqual(calls.map(args => args.slice(0, 2).join(':')), ['workspace:init', 'workspace:create-project', 'project:activate', 'memory:ingest', 'memory:transition', 'memory:transition', 'memory:transition', 'memory:transition']);
  const transitions = calls.filter(args => args[0] === 'memory' && args[1] === 'transition').map(args => ({ memoryId: args[args.indexOf('--memory-id') + 1], target: args[args.indexOf('--target') + 1] }));
  assert.deepEqual(transitions, [
    { memoryId: 'mem_px_owned_host_boundary_a', target: 'validated' },
    { memoryId: 'mem_px_owned_host_boundary_a', target: 'certified' },
    { memoryId: 'mem_px_owned_host_boundary_b', target: 'validated' },
    { memoryId: 'mem_px_owned_host_boundary_b', target: 'certified' }
  ]);
  assert.equal(fs.readFileSync(path.join(workspace, fixture.coordination_handoff_relative), 'utf8').includes('host-boundary-fixture-task'), true);
  assert.equal(digest(path.join(workspace, fixture.memory_source_relative)), fixture.memory_source_sha256);
});

test('owned provider pagination fixture fails closed and changes only a disposable local non-billable policy copy', t => {
  const engine = fs.mkdtempSync(path.join(os.tmpdir(), 'px-provider-pagination-engine-'));
  t.after(() => fs.rmSync(engine, { recursive: true, force: true }));
  fs.mkdirSync(path.join(engine, 'registry'), { recursive: true });
  const policyPath = path.join(engine, 'registry', 'provider_budget_policy.json');
  fs.writeFileSync(policyPath, `${JSON.stringify({ schema_version: 'px.provider-budget-policy/1.0', budgets: [{ budget_id: 'local-development', actor_id: 'pacify-x-local', provider_id: 'ollama', enabled: true, hard_limit_microunits: 0, max_charge_per_request_microunits: 0, unknown_billing: 'deny', fallback_adapter_ids: [] }] }, null, 2)}\n`);
  const fixture = stageOwnedProviderPaginationFixture(engine);
  const projected = JSON.parse(fs.readFileSync(policyPath, 'utf8'));
  assert.equal(fixture.provider_count, 2);
  assert.equal(projected.budgets.length, 2);
  assert.equal(projected.budgets[1].provider_id, 'ollama');
  assert.equal(projected.budgets[1].hard_limit_microunits, 0);
  assert.equal(projected.budgets[1].max_charge_per_request_microunits, 0);
  assert.equal(projected.budgets[1].unknown_billing, 'deny');
  assert.throws(() => stageOwnedProviderPaginationFixture(engine), /fixture-already-present/);
});

test('full current-source walks stage the certified disposable host-boundary fixture before launch', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  const prepare = source.slice(source.indexOf('function prepare('), source.indexOf('function reconcilePrelaunchFailure'));
  assert.match(prepare, /hostBoundaryFixtureRequired = hostBoundaryOnly \|\| \(!bootstrapOnly && !configurationOnly && !studioLifecycleOnly && !knowledgeLifecycleOnly && !nativeDialogOnly\)/);
  assert.match(prepare, /'pacifyX\.workspaceRoot': hostBoundaryFixtureRequired \? config\.workspace : ''/);
  assert.match(prepare, /config\.hostBoundaryFixture = hostBoundaryFixtureRequired \? stageOwnedHostBoundaryFixture/);
  assert.match(prepare, /config\.gitAuthority = fullOperationalWalk \? stageOwnedGitAuthority\(config\.workspace\) : null/);
});

test('owned full-walk Git authority is a bounded real repository without user or network custody', async t => {
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'px-owned-git-authority-'));
  t.after(() => fs.rmSync(workspace, { recursive: true, force: true }));
  const authority = stageOwnedGitAuthority(workspace);
  assert.equal(authority.schema_version, 'px.owned-disposable-git-authority/1.0');
  assert.equal(authority.network_used, false);
  assert.equal(authority.user_git_configuration_read_or_written, false);
  assert.equal(fs.readFileSync(path.join(workspace, '.git', 'HEAD'), 'utf8'), 'ref: refs/heads/main\n');
  assert.match(fs.readFileSync(path.join(workspace, '.git', 'config'), 'utf8'), /bare = false/);
  assert.equal(fs.existsSync(path.join(workspace, '.git', 'objects', 'info')), true);
  const snapshot = await gitSnapshot(workspace);
  assert.equal(snapshot.available, true);
  assert.equal(snapshot.repositoryRoot, fs.realpathSync.native(workspace));
  assert.equal(snapshot.operation, 'none');
  assert.throws(() => stageOwnedGitAuthority(workspace), /target-unavailable/);
});

test('launcher exposes an exact Studio-only mode without claiming full completion', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--studio-lifecycle-only'\)/);
  assert.match(source, /PX_OPERATIONAL_STUDIO_LIFECYCLE_ONLY: '1'/);
  assert.match(source, /PX_OPERATIONAL_EXERCISE_STUDIO_APPROVAL: '1'/);
  assert.match(source, /focusedProfile = configurationOnly \? 'reversible-configuration' : studioLifecycleOnly \? 'studio-lifecycle'/);
  assert.match(source, /focused-\$\{focusedProfile\}-walk/);
  assert.match(source, /full_operational_completion_claimed: focusedProfile \? false/);
  assert.match(source, /regularOperationalHost: !bootstrapOnly/);
  assert.match(source, /!regularOperationalHost \? \[`--extensionTestsPath=\$\{bootstrapPath\}`\] : \[\]/);
  assert.match(source, /status: 'deferred-to-operational-walker'/);
  assert.match(source, /test_mode: false/);
});

test('only bootstrap-only retains extension test bootstrap mode', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /regularOperationalHost: !bootstrapOnly/);
  assert.match(source, /if \(regularOperationalHost\)[\s\S]*deferred-to-operational-walker[\s\S]*else \{[\s\S]*waitForJsonFile\(config\.bootstrapReceipt, vscode\)/);
  assert.match(source, /assert\.equal\(lifecycle\.bootstrap\.command_executed, true/);
});

test('regular host waits boundedly for isolated storage observation before the walker starts', async () => {
  const storageBoundary = { result: { user_scoped_shared_data_observed: false, owned_shared_data_observed: false, in_memory_observed: false } };
  const host = { exitCode: null, signalCode: null };
  setTimeout(() => { storageBoundary.result.in_memory_observed = true; }, 20);
  const observed = await waitForIsolatedStorageBoundary(storageBoundary, host, 500);
  assert.equal(observed.in_memory_observed, true);
});

test('storage observation gate fails immediately on user scope or host exit', async () => {
  await assert.rejects(() => waitForIsolatedStorageBoundary({ result: { user_scoped_shared_data_observed: true } }, { exitCode: null, signalCode: null }, 500), /user-scoped-shared-storage-observed/);
  await assert.rejects(() => waitForIsolatedStorageBoundary({ result: { user_scoped_shared_data_observed: false } }, { exitCode: 7, signalCode: null }, 500), /vscode-host-exited-before-storage-boundary:7/);
});

test('launcher exposes an exact reversible-configuration-only mode with bounded evidence', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--configuration-only'\)/);
  assert.match(source, /PX_OPERATIONAL_CONFIGURATION_ONLY: '1'/);
  assert.match(source, /focusedProfile = configurationOnly \? 'reversible-configuration'/);
  assert.match(source, /full_operational_completion_claimed: focusedProfile \? false/);
});

test('launcher exposes a bounded late-card repair mode without full-walk or native-input authority', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--late-card-repair-only'\)/);
  assert.match(source, /PX_OPERATIONAL_LATE_CARD_REPAIR_ONLY: '1'/);
  assert.match(source, /lateCardRepairOnly \? 'late-card-repair'/);
  assert.match(source, /fullOperationalWalk =[\s\S]*!lateCardRepairOnly/);
  assert.match(source, /nativeInputRequired = studioLifecycleOnly \|\| nativeDialogOnly \|\| postAuditLongRunning \|\| fullOperationalWalk/);
  assert.match(source, /full_operational_completion_claimed: focusedProfile \? false/);
});

test('launcher requires explicit full-profile authority for post-audit long-running owners', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(source, /process\.argv\.includes\('--post-audit-long-running'\)/);
  assert.match(source, /PX_OPERATIONAL_POST_AUDIT_LONG_RUNNING: '1'/);
  assert.match(source, /post-audit-long-running-requires-full-profile/);
  assert.match(source, /post_audit_long_running_authority: postAuditLongRunning/);
  assert.match(source, /prepare\(temporaryRoot, walkOutput, vsixPath, bootstrapOnly, configurationOnly, studioLifecycleOnly, knowledgeLifecycleOnly, hostBoundaryOnly, nativeDialogOnly, codexHandoffOnly, errorIndicatorsOnly, lateCardRepairOnly, postAuditLongRunning\)/);
  assert.match(source, /timeoutMs: postAuditLongRunning \? 3_600_000 : 1_800_000/);
  assert.match(source, /workerExitVerified: run\?\.receipt\?\.worker_exit_verified \?\? lifecycle\?\.worker_exit_verified/);
  assert.match(source, /partial_profile_progress: child\?\.walk_receipt \? null : retainedProfileProgress\(walkOutput\)/);
  assert.match(source, /partial_host_progress: child\?\.walk_receipt \? null : retainedHostProgress\(walkOutput\)/);
  assert.match(source, /const nativeInputRequired = config\.nativeInputRequired === true/);
  assert.match(source, /const nativeInputRequired = studioLifecycleOnly \|\| nativeDialogOnly \|\| postAuditLongRunning \|\| fullOperationalWalk/);
  assert.match(source, /nativeInputRequired,/);
  assert.match(source, /nativeInputRequired \? \{[\s\S]*PX_OWNED_NATIVE_INPUT_SECRET: config\.nativeInputSecret/);
  assert.match(source, /nativeInputRequired \? resolveOwnedCachedVSCode/);
  assert.match(source, /config\.nativeDialogOnly \? \{ PX_OPERATIONAL_NATIVE_DIALOG_ONLY: '1' \} : \{\}/);
});

test('ordinary full operational walks start the owned native input helper used by their native profiles', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  const prepareSource = source.slice(source.indexOf('function prepare('), source.indexOf('function stageOwnedGitAuthority'));
  assert.match(prepareSource, /fullOperationalWalk/);
  assert.match(prepareSource, /nativeDialogOnly \|\| postAuditLongRunning \|\| fullOperationalWalk/);
  assert.match(prepareSource, /nativeInputSecret: nativeInputRequired \? crypto\.randomBytes\(32\)\.toString\('hex'\) : null/);
});
