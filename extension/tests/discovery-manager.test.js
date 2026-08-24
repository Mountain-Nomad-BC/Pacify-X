'use strict';

const assert = require('node:assert/strict');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const test = require('node:test');
const { discoverEnvironment, readEnvironmentInventory, readEnvironmentSubject, readEnvironmentExtension, applyEnvironmentFreshness, rootIdentity, inspectRoots, boundedTree, scanEnvironmentAsync, virtualEnvironmentInventory, environmentFileInventory, pathsFor, optionalCurrentPathFor } = require('../src/discoveryManager');

function fixture() { return fs.mkdtempSync(path.join(os.tmpdir(), 'px-environment-')); }

test('workspace-less optional environment projection never calls the strict path resolver', () => {
  assert.equal(optionalCurrentPathFor(undefined), '');
  assert.equal(optionalCurrentPathFor(null), '');
  const root = fixture();
  try { assert.equal(optionalCurrentPathFor(root), pathsFor(root).current); }
  finally { fs.rmSync(root, { recursive: true, force: true }); }
});
const extensions = [{
  id: 'sample.publisher', isActive: true,
  packageJSON: { displayName: 'Sample', version: '1.2.3', publisher: 'sample', contributes: { commands: [{ command: 'sample.run' }], languages: [{ id: 'sample' }] }, extensionDependencies: ['dependency.publisher'] }
}];
async function fakeRun(command, args) {
  if (args.includes('--format=json')) return { status: 0, stdout: '[{"name":"pytest","version":"9.0.2"}]', stderr: '' };
  if (args.includes('ls')) return { status: 0, stdout: '{"dependencies":{"typescript":{"version":"6.0.0"}}}', stderr: '' };
  if (/^python(?:\.exe)?$/i.test(path.basename(command)) && args.includes('--version')) return { status: 0, stdout: 'Python 3.13.7', stderr: '' };
  return { status: ['python', 'node', 'npm', 'git'].includes(command) ? 0 : 1, stdout: `${command} 1.0`, stderr: '' };
}

test('startup discovery builds a separate hashed ontology and semantic graph', async t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const result = await discoverEnvironment({ extensions, projectRoot: root, pythonPath: 'python', run: fakeRun, reason: 'startup' });
  assert.equal(result.inventory.schema_version, 'px.environment-capability-map/2.0');
  assert.equal(result.inventory.boundaries.arbitrary_extension_activation, false);
  assert.equal(result.inventory.boundaries.network_installs, false);
  assert.equal(result.inventory.summary.extensions, 1);
  assert.equal(result.inventory.summary.python_packages, 1);
  assert.equal(result.inventory.storage.mode, 'compact-index-with-hash-verified-lazy-shards');
  assert.equal(result.inventory.discovery.generation, 1);
  assert.equal(result.inventory.discovery.completeness, 'complete');
  assert.equal(result.inventory.freshness.state, 'fresh');
  assert.equal(Object.hasOwn(result.inventory, 'graph'), false);
  assert.equal(Object.hasOwn(result.inventory, 'subjects'), false);
  const graph = readEnvironmentSubject(root, 'graph');
  assert.ok(graph.nodes.some(item => item.id === 'vscode-command:sample.run'));
  assert.ok(graph.edges.some(item => item.predicate === 'contributes-command'));
  assert.ok(graph.edges.some(item => item.predicate === 'installed-by'));
  assert.ok(graph.edges.some(item => item.predicate === 'governed-by'));
  const detail = readEnvironmentExtension(root, 'sample.publisher').extension;
  assert.equal(detail.api_contract.activation_attempted, false);
  assert.equal(detail.commands[0].expected_outputs.includes('not declared'), true);
  assert.deepEqual(detail.resource_contract.resource, 'sample.publisher');
  assert.equal(readEnvironmentInventory(root).inventory.snapshot_hash, result.inventory.snapshot_hash);
});

test('bounded discovery inventories actual virtual environments and secret-safe environment schemas', async t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const environmentRoot = path.join(root, '.venv');
  const interpreter = process.platform === 'win32' ? path.join(environmentRoot, 'Scripts', 'python.exe') : path.join(environmentRoot, 'bin', 'python');
  fs.mkdirSync(path.dirname(interpreter), { recursive: true });
  fs.writeFileSync(path.join(environmentRoot, 'pyvenv.cfg'), 'home = safe\nversion = 3.13.7\n', 'utf8');
  fs.writeFileSync(interpreter, '', 'utf8');
  fs.mkdirSync(path.join(environmentRoot, 'Lib', 'site-packages', 'example_pkg-1.2.3.dist-info'), { recursive: true });
  fs.writeFileSync(path.join(root, 'poetry.lock'), '');
  fs.writeFileSync(path.join(root, '.env.example'), 'OPENAI_API_KEY=\nREQUIRED_DATABASE_URL=\n', 'utf8');
  fs.writeFileSync(path.join(root, '.env'), 'OPENAI_API_KEY=sk-ultra-secret-do-not-persist\n', 'utf8');
  fs.writeFileSync(path.join(root, '.gitignore'), '.env\n', 'utf8');
  fs.writeFileSync(path.join(root, 'consumer.js'), 'const configured = process.env.OPENAI_API_KEY;\n', 'utf8');

  const tree = boundedTree([root, path.parse(root).root]);
  assert.deepEqual(tree.roots, [fs.realpathSync.native(root)]);
  const environments = virtualEnvironmentInventory(tree, { pythonPath: interpreter });
  assert.equal(environments.length, 1);
  assert.equal(environments[0].state, 'active');
  assert.equal(environments[0].python_version, '3.13.7');
  assert.ok(environments[0].evidence.active_signals.includes('configured-python-path'));
  assert.ok(environments[0].managers.includes('poetry'));
  assert.equal(environments[0].package_summary.count, 1);

  const environmentFiles = environmentFileInventory(tree);
  const serialized = JSON.stringify(environmentFiles);
  assert.doesNotMatch(serialized, /sk-ultra-secret-do-not-persist/);
  assert.equal(environmentFiles.every(item => item.variables.every(variable => variable.value === undefined && variable.value_fingerprint === null)), true);
  const local = environmentFiles.find(item => item.relative_path === '.env');
  assert.equal(local.exposure.status, 'ignore-pattern-observed');
  assert.equal(local.variables[0].provider, 'openai');
  assert.deepEqual(local.variables[0].consumers.map(item => item.path), ['consumer.js']);
  assert.deepEqual(local.validation.missing_required, ['REQUIRED_DATABASE_URL']);

  const result = await discoverEnvironment({ extensions, projectRoot: root, engineRoot: root, pythonPath: interpreter, run: fakeRun, reason: 'environment-test' });
  assert.equal(result.inventory.summary.virtual_environments, 1);
  assert.equal(result.inventory.summary.environment_files, 2);
  assert.equal(readEnvironmentSubject(root, 'environments').records[0].state, 'active');
  assert.doesNotMatch(JSON.stringify(readEnvironmentSubject(root, 'environment-files')), /sk-ultra-secret-do-not-persist/);
});

test('refresh event records newly detected semantic identities', async t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  await discoverEnvironment({ extensions: [], projectRoot: root, pythonPath: 'python', run: fakeRun, reason: 'startup' });
  const result = await discoverEnvironment({ extensions, projectRoot: root, pythonPath: 'python', run: fakeRun, reason: 'vscode-extension-change' });
  assert.equal(result.event.changed, true);
  assert.ok(result.event.added_node_ids.includes('vscode-extension:sample.publisher'));
  assert.ok(result.event.added_node_ids.includes('vscode-command:sample.run'));
  assert.equal(result.event.removed_node_ids.length, 0);
  assert.equal(result.event.generation, 2);
  assert.equal(result.inventory.discovery.previous_snapshot_hash === null, false);
});

test('read-only discovery is memory-only and does not create project state', async t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.writeFileSync(path.join(root, 'sentinel.txt'), 'unchanged', 'utf8');
  const before = fs.readdirSync(root).sort();
  const result = await discoverEnvironment({ extensions, projectRoot: root, pythonPath: 'python', run: fakeRun, reason: 'read-only', persist: false });
  assert.equal(result.persistence, 'memory-only-read-discovery');
  assert.equal(result.event, null);
  assert.deepEqual(fs.readdirSync(root).sort(), before);
  assert.equal(fs.existsSync(path.join(root, '.engineering-bootstrap')), false);
});

test('root inspection reports missing, alias, nested, and symlink ambiguity without escaping admitted roots', t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const nested = path.join(root, 'nested'); fs.mkdirSync(nested);
  const missing = path.join(root, 'missing');
  const aliases = [root, nested, missing];
  const link = path.join(root, 'alias-link');
  try { fs.symlinkSync(nested, link, process.platform === 'win32' ? 'junction' : 'dir'); aliases.push(link); } catch { /* symlink creation can be privilege-gated */ }
  const inspected = inspectRoots(aliases);
  assert.ok(inspected.failures.some(item => item.code === 'missing-or-unreadable'));
  assert.ok(inspected.ambiguities.some(item => item.code === 'nested-root-overlap'));
  if (aliases.includes(link)) assert.ok(inspected.ambiguities.some(item => item.code === 'duplicate-physical-root'));
  const tree = boundedTree([root]);
  if (aliases.includes(link)) assert.ok(tree.symbolic_links_skipped >= 1);
});

test('Windows case and UNC spellings share one deterministic physical-root identity', () => {
  assert.equal(rootIdentity('C:\\Work\\Pacify-X', 'win32'), rootIdentity('c:/work/pacify-x/', 'win32'));
  assert.equal(rootIdentity('\\\\Server\\Share\\Project', 'win32'), rootIdentity('//server/share/project/', 'win32'));
  assert.equal(rootIdentity('//server/share/project/', 'win32'), '\\\\server\\share\\project');
});

test('active environment with the wrong configured Python series is explicit, never healthy by inference', t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const environmentRoot = path.join(root, '.venv');
  const interpreter = process.platform === 'win32' ? path.join(environmentRoot, 'Scripts', 'python.exe') : path.join(environmentRoot, 'bin', 'python');
  fs.mkdirSync(path.dirname(interpreter), { recursive: true });
  fs.writeFileSync(path.join(environmentRoot, 'pyvenv.cfg'), 'version = 3.10.14\n'); fs.writeFileSync(interpreter, '');
  const environments = virtualEnvironmentInventory(boundedTree([root]), { pythonPath: interpreter, currentPythonVersion: 'Python 3.13.7' });
  assert.equal(environments[0].state, 'wrong-version');
  assert.equal(environments[0].active, false);
  assert.equal(environments[0].evidence.version_compatibility, 'mismatched');
});

test('expired discovery evidence degrades active environment claims to unknown', () => {
  const records = applyEnvironmentFreshness([{ id: 'env', active: true, state: 'active', evidence: { active_signals: ['configured-python-path'] } }], { state: 'stale' });
  assert.equal(records[0].active, false); assert.equal(records[0].state, 'unknown'); assert.equal(records[0].evidence.active_evidence_stale, true);
});

test('refresh generations expose moved and deleted environment identities without inventing continuity', async t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const first = path.join(root, '.venv'); fs.mkdirSync(first);
  fs.writeFileSync(path.join(first, 'pyvenv.cfg'), 'version = 3.12.0\n');
  await discoverEnvironment({ extensions: [], projectRoot: root, pythonPath: 'python', run: fakeRun, reason: 'initial' });
  const moved = path.join(root, 'moved-venv'); fs.renameSync(first, moved);
  const second = await discoverEnvironment({ extensions: [], projectRoot: root, pythonPath: 'python', run: fakeRun, reason: 'moved' });
  assert.equal(second.event.generation, 2);
  assert.ok(second.event.added_node_ids.some(id => id.startsWith('python-env:')));
  assert.ok(second.event.removed_node_ids.some(id => id.startsWith('python-env:')));
  fs.rmSync(moved, { recursive: true, force: true });
  const third = await discoverEnvironment({ extensions: [], projectRoot: root, pythonPath: 'python', run: fakeRun, reason: 'deleted' });
  assert.equal(third.event.generation, 3);
  assert.ok(third.event.removed_node_ids.some(id => id.startsWith('python-env:')));
});

test('legacy compact inventory is integrity-checked then migrated in memory to schema 2', t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const environmentRoot = path.join(root, '.engineering-bootstrap', 'environment'); fs.mkdirSync(environmentRoot, { recursive: true });
  const stable = {
    schema_version: 'px.environment-capability-map/1.0', authority: 'legacy-test', boundaries: {}, ontology: {}, summary: {},
    storage: { mode: 'compact-index-with-hash-verified-lazy-shards' }, datasets: {}, content_hash: 'legacy-content'
  };
  const snapshot_hash = crypto.createHash('sha256').update(JSON.stringify(stable)).digest('hex');
  fs.writeFileSync(path.join(environmentRoot, 'current.json'), JSON.stringify({ ...stable, generated_utc: '2026-01-01T00:00:00Z', snapshot_hash }), 'utf8');
  const loaded = readEnvironmentInventory(root).inventory;
  assert.equal(loaded.schema_version, 'px.environment-capability-map/2.0');
  assert.equal(loaded.migration.from, 'px.environment-capability-map/1.0');
  assert.equal(loaded.summary.virtual_environments, 0);
  assert.equal(loaded.source_snapshot_hash, snapshot_hash);
});

test('filesystem discovery runs in a worker without blocking the extension-host event loop', async t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (let index = 0; index < 80; index += 1) {
    const directory = path.join(root, `package-${index}`, 'src');
    fs.mkdirSync(directory, { recursive: true });
    fs.writeFileSync(path.join(directory, `module-${index}.js`), `process.env.PX_TEST_${index};\n`);
  }
  let eventLoopAdvanced = false;
  setImmediate(() => { eventLoopAdvanced = true; });
  const result = await scanEnvironmentAsync([root], { pythonPath: 'python', currentPythonVersion: 'Python 3.13.7' });
  assert.equal(eventLoopAdvanced, true);
  assert.ok(result.tree.entries.length >= 160);
  assert.equal(Array.isArray(result.virtualEnvironments), true);
  assert.equal(Array.isArray(result.environmentFiles), true);
});

test('filesystem discovery worker is owned and abortable', async t => {
  const root = fixture(); t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const controller = new AbortController();
  controller.abort('test-cancel');
  await assert.rejects(scanEnvironmentAsync([root], { signal: controller.signal }), error => error.name === 'AbortError');
});
