'use strict';

// Launch the current extension source in a PACIFY-X-owned, disposable VS Code
// profile and run the existing operational UI walker over loopback CDP. This
// launcher deliberately does not install into, read from, or write to the
// user's normal VS Code profile.

const assert = require('assert');
const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const net = require('net');
const os = require('os');
const path = require('path');
const { downloadAndUnzipVSCode, resolveCliArgsFromVSCodeExecutablePath } = require('@vscode/test-electron');
const { nonBillableEnvironment } = require('../src/contextBridge');
const { terminateProcessTreeAsync } = require('../src/processTree');
const { runOwnedHostWorker } = require('./owned-host-runner');
const { ensureOwnedVscodeTestCache, markOwnedHostWorkspace } = require('./owned-vscode-test-cache');
const {
  evaluateBootstrapActivation,
  evaluateLauncherTerminal,
  evaluateOperationalWalk,
  exitCodeForTerminalState,
  normalizeProcessOutput
} = require('./operational-walk-status');

const CHILD_FLAG = '--isolated-current-source-child';
const VSCODE_VERSION = '1.132.1';
const extensionRoot = path.resolve(__dirname, '..');
const repositoryRoot = path.resolve(extensionRoot, '..');
const walkerPath = path.join(__dirname, 'run-operational-ui-walk.js');
const bootstrapPath = path.join(extensionRoot, 'tests', 'operational-walk-bootstrap', 'index.js');
const installedHarnessPath = path.join(extensionRoot, 'tests', 'installed-harness');
const MAX_CAPTURE = 2 * 1024 * 1024;
const ENGINE_COPY_EXCLUDED_ROOTS = new Set(['.git', '.vscode', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.venv', 'venv', 'node_modules', 'evidence']);
const ENGINE_COPY_EXCLUDED_PATHS = new Set(['extension/node_modules', 'extension/dist', '.engineering-bootstrap/test-evidence', '.engineering-bootstrap/resource-lifecycle', '.engineering-bootstrap/operation-bus']);
const REQUIRED_ENGINE_FILES = ['runtime/cli.py', 'registry/engine_identity.json'];

const utcStamp = () => new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
const sha256 = target => crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex');
const argument = name => {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : null;
};

function capture(stream, collector) {
  stream?.on('data', chunk => collector(chunk.toString('utf8')));
}

function electronHostEnvironment(extra = {}) {
  const environment = { ...nonBillableEnvironment(), ...extra };
  // Codex and CLI hosts may intentionally run Electron as Node. A VS Code
  // desktop child must not inherit that mode or it interprets the workspace
  // path as a JavaScript entry point.
  delete environment.ELECTRON_RUN_AS_NODE;
  return environment;
}

function waitForExit(child) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = value => { if (!settled) { settled = true; resolve(value); } };
    child.once('error', error => { if (!settled) { settled = true; reject(error); } });
    child.once('close', (code, signal) => finish({ code, signal: signal || null }));
  });
}

async function waitForJsonFile(target, host, timeoutMs = 60_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (fs.existsSync(target)) {
      const parsed = JSON.parse(fs.readFileSync(target, 'utf8'));
      if (!parsed || typeof parsed !== 'object') throw new Error('operational-bootstrap-receipt-invalid');
      return parsed;
    }
    if (host.exitCode !== null || host.signalCode !== null) throw new Error(`vscode-host-exited-before-bootstrap:${host.exitCode ?? host.signalCode}`);
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('operational-bootstrap-receipt-timeout');
}

function inside(root, target) {
  const relative = path.relative(path.resolve(root), path.resolve(target));
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function excludedEnginePath(relativePath) {
  const normalized = String(relativePath || '').replaceAll('\\', '/').replace(/^\.\//, '');
  if (!normalized) return false;
  const parts = normalized.split('/');
  if (ENGINE_COPY_EXCLUDED_ROOTS.has(parts[0]) || parts.includes('__pycache__')) return true;
  if (parts.at(-1)?.endsWith('.lock')) return true;
  if (normalized.endsWith('.pyc') || normalized.endsWith('.pyo')) return true;
  return [...ENGINE_COPY_EXCLUDED_PATHS].some(candidate => normalized === candidate || normalized.startsWith(`${candidate}/`));
}

function stageDisposableEngine(sourceRoot, temporaryRoot) {
  const sourceInput = path.resolve(sourceRoot);
  const ownedInput = path.resolve(temporaryRoot);
  const sourceInputStatus = fs.lstatSync(sourceInput);
  const ownedInputStatus = fs.lstatSync(ownedInput);
  if (sourceInputStatus.isSymbolicLink() || ownedInputStatus.isSymbolicLink()) throw new Error('owned-engine-root-linked');
  if (!sourceInputStatus.isDirectory() || !ownedInputStatus.isDirectory()) throw new Error('owned-engine-root-not-directory');
  const source = fs.realpathSync.native(sourceInput);
  const ownedRoot = fs.realpathSync.native(ownedInput);
  const target = path.join(ownedRoot, 'engine');
  if (source === ownedRoot || inside(source, ownedRoot) || !inside(ownedRoot, target)) throw new Error('owned-engine-root-boundary-invalid');
  if (fs.existsSync(target)) throw new Error('owned-engine-target-already-exists');
  let copiedFiles = 0;
  let copiedBytes = 0;
  try {
    fs.cpSync(source, target, {
      recursive: true,
      force: false,
      errorOnExist: true,
      filter(candidate) {
        const resolved = path.resolve(candidate);
        const relative = path.relative(source, resolved);
        if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error(`owned-engine-source-escape:${relative}`);
        if (excludedEnginePath(relative)) return false;
        const status = fs.lstatSync(resolved);
        if (status.isSymbolicLink()) throw new Error(`owned-engine-source-link:${relative.replaceAll('\\', '/')}`);
        if (status.isFile()) { copiedFiles += 1; copiedBytes += status.size; }
        return true;
      }
    });
    const staged = fs.realpathSync.native(target);
    if (!inside(ownedRoot, staged) || fs.lstatSync(staged).isSymbolicLink()) throw new Error('owned-engine-staged-boundary-invalid');
    const required = Object.fromEntries(REQUIRED_ENGINE_FILES.map(relative => {
      const original = path.join(source, ...relative.split('/'));
      const copy = path.join(staged, ...relative.split('/'));
      if (!fs.existsSync(original) || !fs.existsSync(copy) || !fs.lstatSync(copy).isFile() || fs.lstatSync(copy).isSymbolicLink()) {
        throw new Error(`owned-engine-required-file-missing:${relative}`);
      }
      let stableSha256 = null;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const before = fs.readFileSync(original);
        fs.copyFileSync(original, copy);
        const after = fs.readFileSync(original);
        const copied = fs.readFileSync(copy);
        const beforeSha256 = crypto.createHash('sha256').update(before).digest('hex');
        const afterSha256 = crypto.createHash('sha256').update(after).digest('hex');
        const copiedSha256 = crypto.createHash('sha256').update(copied).digest('hex');
        if (beforeSha256 === afterSha256 && afterSha256 === copiedSha256) {
          stableSha256 = copiedSha256;
          break;
        }
      }
      if (!stableSha256) throw new Error(`owned-engine-required-file-unstable:${relative}`);
      return [relative, stableSha256];
    }));
    return { root: staged, source: '[current-repository-source]', copied_files: copiedFiles, copied_bytes: copiedBytes, required_file_sha256: required };
  } catch (error) {
    if (fs.existsSync(target) && inside(ownedRoot, target) && !fs.lstatSync(target).isSymbolicLink()) {
      fs.rmSync(target, { recursive: true, force: true });
    }
    throw error;
  }
}

function classifySharedStoragePath(sharedData, raw) {
  if (raw === ':memory:') return { mode: 'in-memory', isolated: true, display_path: ':memory:' };
  const observed = path.resolve(raw);
  const owned = inside(sharedData, observed);
  return {
    mode: owned ? 'owned-filesystem' : 'external-filesystem',
    isolated: owned,
    display_path: owned ? '[owned-shared-data]/sharedStorage/state.vscdb' : observed
  };
}

function storageBoundaryObserver(config) {
  const result = {
    expected_shared_data: '[owned-shared-data]',
    in_memory_observed: false,
    owned_shared_data_observed: false,
    user_scoped_shared_data_observed: false,
    observed_database_paths: []
  };
  return {
    result,
    observe(text) {
      for (const match of String(text).matchAll(/shared storage database at '([^']+)'/gi)) {
        const classified = classifySharedStoragePath(config.sharedData, match[1]);
        result.in_memory_observed ||= classified.mode === 'in-memory';
        result.owned_shared_data_observed ||= classified.mode === 'owned-filesystem';
        result.user_scoped_shared_data_observed ||= !classified.isolated;
        result.observed_database_paths.push(classified.display_path);
      }
    }
  };
}

async function reserveLoopbackPort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const address = server.address();
  const port = Number(address?.port);
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  if (!Number.isSafeInteger(port) || port < 1024 || port > 65535) throw new Error('invalid-loopback-cdp-port');
  return port;
}

function probeCdp(port) {
  return new Promise(resolve => {
    const request = http.get({ hostname: '127.0.0.1', port, path: '/json/version', timeout: 1000 }, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { body = `${body}${chunk}`.slice(0, 16 * 1024); });
      response.on('end', () => {
        try {
          const parsed = JSON.parse(body);
          resolve(response.statusCode === 200 && Boolean(parsed.webSocketDebuggerUrl));
        } catch { resolve(false); }
      });
    });
    request.once('timeout', () => { request.destroy(); resolve(false); });
    request.once('error', () => resolve(false));
  });
}

async function waitForCdp(port, host, timeoutMs = 60_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await probeCdp(port)) return Date.now() - started;
    if (host.exitCode !== null || host.signalCode !== null) throw new Error(`vscode-host-exited-before-cdp:${host.exitCode ?? host.signalCode}`);
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(`loopback-cdp-not-ready:${port}`);
}

function safeOwnedEphemeralCleanup(temporaryRoot, processTreeClosedVerified) {
  const resolved = path.resolve(temporaryRoot);
  const allowedParent = path.resolve(os.tmpdir());
  const markerPath = path.join(resolved, '.pacify-x-owned-ephemeral.json');
  if (!processTreeClosedVerified) return { reclaimed: false, reason: 'process-tree-closure-unverified' };
  if (path.dirname(resolved) !== allowedParent || !path.basename(resolved).startsWith('pacify-x-current-source-walk-')) {
    return { reclaimed: false, reason: 'target-outside-owned-ephemeral-root' };
  }
  if (!fs.existsSync(markerPath) || fs.lstatSync(resolved).isSymbolicLink()) {
    return { reclaimed: false, reason: 'ownership-marker-missing-or-linked-root' };
  }
  const marker = JSON.parse(fs.readFileSync(markerPath, 'utf8'));
  if (marker.owner !== 'PACIFY-X' || marker.classification !== 'ephemeral') {
    return { reclaimed: false, reason: 'ownership-marker-invalid' };
  }
  fs.rmSync(resolved, { recursive: true, force: true });
  return { reclaimed: !fs.existsSync(resolved), reason: 'verified-process-tree-closure' };
}

async function childMain(configPath) {
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  const lifecycle = {
    schema_version: 'px.isolated-current-source-host-child/1.0',
    started_utc: new Date().toISOString(),
    source_mode: config.vsixPath ? 'installed-exact-vsix' : 'extensionDevelopmentPath',
    vscode_pid: null,
    walker_pid: null,
    cdp: null,
    vscode_termination_verified: false,
    walker_termination_verified: null,
    status: 'starting'
  };
  let vscode = null;
  let walker = null;
  let stdout = '';
  let stderr = '';
  let childError = null;
  const storageBoundary = storageBoundaryObserver(config);
  const appendStdout = text => { storageBoundary.observe(text); stdout = `${stdout}${text}`.slice(-MAX_CAPTURE); process.stdout.write(text); };
  const appendStderr = text => { stderr = `${stderr}${text}`.slice(-MAX_CAPTURE); process.stderr.write(text); };
  try {
    const cache = ensureOwnedVscodeTestCache(VSCODE_VERSION);
    const executable = await downloadAndUnzipVSCode({ version: VSCODE_VERSION, cachePath: cache.root });
    let developmentPath = extensionRoot;
    if (config.vsixPath) {
      const before = sha256(config.vsixPath);
      if (before !== config.vsixSha256) throw new Error('exact-vsix-preinstall-sha256-mismatch');
      const [cli, ...cliPrefix] = resolveCliArgsFromVSCodeExecutablePath(executable, { reuseMachineInstall: true });
      const install = childProcess.spawnSync(
        cli,
        [...cliPrefix, `--extensions-dir=${config.extensions}`, `--user-data-dir=${config.userData}`, '--install-extension', config.vsixPath, '--force'],
        { encoding: 'utf8', shell: process.platform === 'win32', timeout: 120_000, windowsHide: true }
      );
      if (install.error || install.status !== 0 || !/successfully installed/i.test(`${install.stdout}\n${install.stderr}`)) {
        throw new Error(`exact-vsix-install-failed:${install.error?.message || install.status}:${String(install.stderr || install.stdout).slice(0, 1000)}`);
      }
      if (sha256(config.vsixPath) !== before) throw new Error('exact-vsix-bytes-changed-during-install');
      lifecycle.installed_artifact = { path: path.basename(config.vsixPath), sha256: before, unchanged_after_install: true };
      developmentPath = installedHarnessPath;
    }
    const port = await reserveLoopbackPort();
    const endpoint = `http://127.0.0.1:${port}`;
    const args = [
      config.workspace,
      '--new-window',
      '--no-sandbox',
      '--disable-gpu-sandbox',
      '--disable-updates',
      '--disable-extension', 'github.copilot',
      '--disable-extension', 'github.copilot-chat',
      '--disable-extension', 'github.vscode-pull-request-github',
      '--disable-extension', 'vscode.github-authentication',
      '--disable-extension', 'vscode.microsoft-authentication',
      '--disable-workspace-trust',
      '--skip-welcome',
      '--skip-release-notes',
      '--no-cached-data',
      `--user-data-dir=${config.userData}`,
      `--extensions-dir=${config.extensions}`,
      `--shared-data-dir=${config.sharedData}`,
      `--extensionDevelopmentPath=${developmentPath}`,
      `--extensionTestsPath=${bootstrapPath}`,
      '--remote-debugging-address=127.0.0.1',
      `--remote-debugging-port=${port}`
    ];
    lifecycle.executable = executable;
    lifecycle.launch_arguments = args.map(value => value === config.workspace ? '[owned-workspace]' :
      value === `--user-data-dir=${config.userData}` ? '--user-data-dir=[owned-user-data]' :
      value === `--extensions-dir=${config.extensions}` ? '--extensions-dir=[owned-empty-extensions]' :
      value === `--shared-data-dir=${config.sharedData}` ? '--shared-data-dir=[owned-shared-data]' :
      value === `--extensionDevelopmentPath=${developmentPath}` ? (config.vsixPath ? '--extensionDevelopmentPath=[installed-artifact-harness]' : '--extensionDevelopmentPath=[current-source]') :
      value === `--extensionTestsPath=${bootstrapPath}` ? '--extensionTestsPath=[owned-bootstrap]' : value);
    vscode = childProcess.spawn(executable, args, {
      cwd: extensionRoot,
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: electronHostEnvironment({
        PX_OWNED_VSCODE_HOST: '1',
        PX_OWNED_VSCODE_HOST_CONFIRM_REVERSIBLE_WRITES: '1',
        PX_ENGINE_ROOT: config.engineRoot,
        PX_OPERATIONAL_WALK_BOOTSTRAP_RECEIPT: config.bootstrapReceipt,
        PX_OPERATIONAL_WALK_BOOTSTRAP_SENTINEL: config.bootstrapSentinel
      })
    });
    lifecycle.vscode_pid = Number(vscode.pid) || null;
    capture(vscode.stdout, appendStdout);
    capture(vscode.stderr, appendStderr);
    lifecycle.cdp = { endpoint, address: '127.0.0.1', port, ready_after_ms: await waitForCdp(port, vscode) };
    lifecycle.bootstrap = await waitForJsonFile(config.bootstrapReceipt, vscode);
    assert.equal(lifecycle.bootstrap.status, 'ready', `operational-bootstrap:${lifecycle.bootstrap.status || 'unknown'}`);
    assert.equal(lifecycle.bootstrap.command_registered, true, 'operational-bootstrap-command-unregistered');
    assert.equal(lifecycle.bootstrap.command_executed, true, 'operational-bootstrap-command-not-executed');
    assert.equal(storageBoundary.result.user_scoped_shared_data_observed, false, 'user-scoped-shared-storage-observed');
    assert.equal(storageBoundary.result.owned_shared_data_observed || storageBoundary.result.in_memory_observed, true, 'isolated-shared-storage-not-observed');
    if (config.bootstrapOnly) {
      lifecycle.walker_termination_verified = true;
      lifecycle.status = 'bootstrap-ready';
    } else {
      lifecycle.status = 'walking';
      walker = childProcess.spawn(process.execPath, [walkerPath, endpoint, config.walkOutput, `--px-owned-token=${config.userData}`], {
        cwd: extensionRoot,
        shell: false,
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
        env: {
          ...nonBillableEnvironment(),
          PX_OWNED_VSCODE_HOST: '1',
          PX_OWNED_ENGINE_ROOT: config.engineRoot,
          ...(config.knowledgeFixture ? {
            PX_OWNED_KNOWLEDGE_SOURCE_ID: config.knowledgeFixture.source_id,
            PX_OWNED_KNOWLEDGE_SOURCE_SHA256: config.knowledgeFixture.source_sha256
          } : {}),
          ...(config.configurationOnly ? { PX_OPERATIONAL_CONFIGURATION_ONLY: '1' } : {}),
          ...(config.studioLifecycleOnly ? { PX_OPERATIONAL_STUDIO_LIFECYCLE_ONLY: '1' } : {}),
          ...(config.knowledgeLifecycleOnly ? { PX_OPERATIONAL_KNOWLEDGE_LIFECYCLE_ONLY: '1' } : {})
        }
      });
      lifecycle.walker_pid = Number(walker.pid) || null;
      capture(walker.stdout, appendStdout);
      capture(walker.stderr, appendStderr);
      const walkerExit = await waitForExit(walker);
      lifecycle.walker_exit = walkerExit;
      lifecycle.walker_termination_verified = true;
      assert.equal(walkerExit.signal, null, `operational-walker-signal:${walkerExit.signal}`);
      assert.ok(fs.existsSync(config.walkReceipt), 'operational-walker-receipt-missing');
      lifecycle.status = 'walk-finished';
    }
  } catch (error) {
    childError = error;
    lifecycle.status = 'failed';
    lifecycle.error = String(error?.stack || error?.message || error).slice(0, 4000);
  } finally {
    try {
      fs.writeFileSync(config.bootstrapSentinel, `${JSON.stringify({ released_utc: new Date().toISOString() })}\n`, { encoding: 'utf8', flag: 'wx' });
    } catch (error) {
      if (error?.code !== 'EEXIST') lifecycle.bootstrap_release_error = String(error?.message || error).slice(0, 1000);
    }
    if (walker && walker.exitCode === null && walker.signalCode === null) {
      lifecycle.walker_termination_verified = await terminateProcessTreeAsync(walker, { graceMs: 750, verifyMs: 10_000 });
    }
    if (vscode) lifecycle.vscode_termination_verified = await terminateProcessTreeAsync(vscode, { graceMs: 1000, verifyMs: 15_000 });
    lifecycle.finished_utc = new Date().toISOString();
    lifecycle.storage_boundary = {
      ...storageBoundary.result,
      mode: storageBoundary.result.in_memory_observed ? 'in-memory' : storageBoundary.result.owned_shared_data_observed ? 'owned-filesystem' : 'unverified',
      verified: (storageBoundary.result.in_memory_observed || storageBoundary.result.owned_shared_data_observed) && !storageBoundary.result.user_scoped_shared_data_observed
    };
    if (!lifecycle.bootstrap && fs.existsSync(config.bootstrapReceipt)) {
      try { lifecycle.bootstrap = JSON.parse(fs.readFileSync(config.bootstrapReceipt, 'utf8')); }
      catch (error) { lifecycle.bootstrap = { status: 'invalid', error: String(error?.message || error).slice(0, 1000) }; }
    }
    let walkReceipt = null;
    let walkReceiptError = null;
    if (fs.existsSync(config.walkReceipt)) {
      try { walkReceipt = JSON.parse(fs.readFileSync(config.walkReceipt, 'utf8')); }
      catch (error) { walkReceiptError = error; }
    }
    const processIssues = normalizeProcessOutput({
      stdout,
      stderr,
      walkerExit: lifecycle.walker_exit,
      expectedWalkerExitCode: walkReceipt?.status_truth
        ? exitCodeForTerminalState(walkReceipt.status_truth.terminal_state)
        : 0,
      processError: childError || walkReceiptError,
      processTreeClosedVerified: lifecycle.vscode_termination_verified === true && lifecycle.walker_termination_verified === true
    });
    lifecycle.operational_status = config.bootstrapOnly
      ? evaluateBootstrapActivation({ bootstrap: lifecycle.bootstrap, storageBoundary: lifecycle.storage_boundary, additionalIssues: processIssues })
      : evaluateOperationalWalk(walkReceipt, { additionalIssues: processIssues });
    if (!childError) lifecycle.status = `${config.bootstrapOnly ? 'bootstrap' : 'walk'}-${lifecycle.operational_status.terminal_state}`;
    lifecycle.stdout_tail = stdout;
    lifecycle.stderr_tail = stderr;
    if (walkReceipt) {
      lifecycle.walk_receipt = {
        path: path.relative(repositoryRoot, config.walkReceipt).replace(/\\/g, '/'),
        sha256: sha256(config.walkReceipt),
        terminal_state: lifecycle.operational_status.terminal_state,
        operationally_complete: lifecycle.operational_status.operationally_complete
      };
    }
    fs.writeFileSync(config.childResult, `${JSON.stringify(lifecycle, null, 2)}\n`, 'utf8');
  }
  if (childError) throw childError;
  return 0;
}

function stageOwnedKnowledgeFixture(workspaceRoot, engineRoot = null) {
  const resolved = fs.realpathSync.native(workspaceRoot);
  if (fs.lstatSync(resolved).isSymbolicLink()) throw new Error('owned-knowledge-workspace-linked');
  const sourceDirectory = path.join(resolved, 'knowledge');
  const registryDirectory = path.join(resolved, 'registry');
  const sourceRelative = 'knowledge/px-owned-lifecycle-source.md';
  const sourcePath = path.join(resolved, ...sourceRelative.split('/'));
  const registryPath = path.join(registryDirectory, 'knowledge_sources.json');
  for (const target of [sourceDirectory, registryDirectory, sourcePath, registryPath]) {
    if (!inside(resolved, target)) throw new Error(`owned-knowledge-target-outside-workspace:${target}`);
    if (fs.existsSync(target)) throw new Error(`owned-knowledge-target-already-exists:${path.relative(resolved, target).replace(/\\/g, '/')}`);
  }
  fs.mkdirSync(sourceDirectory);
  fs.mkdirSync(registryDirectory);
  const source = '# PACIFY-X owned Knowledge lifecycle fixture\n\nBounded source evidence for the disposable installed-host operational walk.\n';
  fs.writeFileSync(sourcePath, source, { encoding: 'utf8', flag: 'wx' });
  const sourceSha256 = sha256(sourcePath);
  const sourceRecord = {
    id: 'source:px-owned-knowledge-lifecycle',
    status: 'active',
    kind: 'local_file',
    visibility: ['local'],
    location: sourceRelative,
    uses: []
  };
  const registry = {
    schema_version: '2.0',
    knowledge_sources: [sourceRecord]
  };
  fs.writeFileSync(registryPath, `${JSON.stringify(registry, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  let engineRegistrySha256 = null;
  if (engineRoot) {
    const engine = fs.realpathSync.native(engineRoot);
    if (fs.lstatSync(engine).isSymbolicLink()) throw new Error('owned-knowledge-engine-linked');
    const engineRegistryPath = path.join(engine, 'registry', 'knowledge_sources.json');
    const engineSourcePath = path.join(engine, ...sourceRelative.split('/'));
    for (const target of [engineRegistryPath, engineSourcePath]) if (!inside(engine, target)) throw new Error(`owned-knowledge-engine-target-outside-root:${target}`);
    if (!fs.existsSync(engineRegistryPath) || fs.lstatSync(engineRegistryPath).isSymbolicLink() || !fs.lstatSync(engineRegistryPath).isFile()) throw new Error('owned-knowledge-engine-registry-invalid');
    if (fs.existsSync(engineSourcePath)) throw new Error(`owned-knowledge-engine-source-already-exists:${sourceRelative}`);
    const engineRegistry = JSON.parse(fs.readFileSync(engineRegistryPath, 'utf8'));
    if (engineRegistry?.schema_version !== '2.0' || !Array.isArray(engineRegistry.knowledge_sources)) throw new Error('owned-knowledge-engine-registry-schema-invalid');
    if (engineRegistry.knowledge_sources.some(item => item?.id === sourceRecord.id)) throw new Error('owned-knowledge-engine-source-id-conflict');
    const engineSourceDirectory = path.dirname(engineSourcePath);
    if (fs.existsSync(engineSourceDirectory) && (fs.lstatSync(engineSourceDirectory).isSymbolicLink() || !fs.lstatSync(engineSourceDirectory).isDirectory())) throw new Error('owned-knowledge-engine-source-directory-invalid');
    fs.mkdirSync(engineSourceDirectory, { recursive: true });
    fs.writeFileSync(engineSourcePath, source, { encoding: 'utf8', flag: 'wx' });
    if (sha256(engineSourcePath) !== sourceSha256) throw new Error('owned-knowledge-engine-source-hash-mismatch');
    engineRegistry.knowledge_sources.push(sourceRecord);
    fs.writeFileSync(engineRegistryPath, `${JSON.stringify(engineRegistry, null, 2)}\n`, 'utf8');
    const projected = JSON.parse(fs.readFileSync(engineRegistryPath, 'utf8'));
    if (projected.knowledge_sources.filter(item => item?.id === sourceRecord.id).length !== 1) throw new Error('owned-knowledge-engine-projection-invalid');
    engineRegistrySha256 = sha256(engineRegistryPath);
  }
  return {
    source_id: sourceRecord.id,
    source_relative: sourceRecord.location,
    source_sha256: sourceSha256,
    evidence_ref: `sha256:${sourceSha256}`,
    engine_registry_sha256: engineRegistrySha256
  };
}

function prepare(temporaryRoot, walkOutput, vsixPath = null, bootstrapOnly = false, configurationOnly = false, studioLifecycleOnly = false, knowledgeLifecycleOnly = false) {
  const stagedEngine = stageDisposableEngine(repositoryRoot, temporaryRoot);
  const config = {
    workspace: path.join(temporaryRoot, 'workspace'),
    userData: path.join(temporaryRoot, 'user-data'),
    extensions: path.join(temporaryRoot, 'extensions'),
    sharedData: path.join(temporaryRoot, 'shared-data'),
    bootstrapReceipt: path.join(temporaryRoot, 'bootstrap-receipt.json'),
    bootstrapSentinel: path.join(temporaryRoot, 'bootstrap-release.json'),
    childResult: path.join(temporaryRoot, 'child-result.json'),
    walkOutput,
    walkReceipt: path.join(walkOutput, 'receipt.json'),
    engineRoot: stagedEngine.root,
    stagedEngine,
    bootstrapOnly,
    configurationOnly,
    studioLifecycleOnly,
    knowledgeLifecycleOnly,
    vsixPath,
    vsixSha256: vsixPath ? sha256(vsixPath) : null
  };
  for (const directory of [config.workspace, config.userData, config.extensions, config.sharedData, config.walkOutput]) {
    fs.mkdirSync(directory, { recursive: true });
  }
  for (const directory of [config.workspace, config.userData, config.extensions, config.sharedData]) {
    if (!inside(temporaryRoot, directory) || fs.lstatSync(directory).isSymbolicLink()) throw new Error(`owned-host-directory-invalid:${directory}`);
  }
  fs.mkdirSync(path.join(config.workspace, '.vscode'), { recursive: true });
  fs.writeFileSync(path.join(config.workspace, '.vscode', 'settings.json'), `${JSON.stringify({
    'pacifyX.engineRoot': config.engineRoot,
    'pacifyX.workspaceRoot': '',
    'pacifyX.pythonPath': process.platform === 'win32' ? 'python' : 'python3',
    'pacifyX.activity.enabled': false
  }, null, 2)}\n`, 'utf8');
  fs.mkdirSync(path.join(config.userData, 'User'), { recursive: true });
  fs.writeFileSync(path.join(config.userData, 'User', 'settings.json'), `${JSON.stringify({
    'extensions.autoUpdate': false,
    'extensions.autoCheckUpdates': false,
    'chat.disableAIFeatures': true,
    'telemetry.telemetryLevel': 'off'
  }, null, 2)}\n`, 'utf8');
  fs.writeFileSync(path.join(config.workspace, 'README.md'), '# PACIFY-X owned operational walk workspace\n', 'utf8');
  config.knowledgeFixture = bootstrapOnly || configurationOnly || studioLifecycleOnly ? null : stageOwnedKnowledgeFixture(config.workspace, config.engineRoot);
  return config;
}

function reconcilePrelaunchFailure(temporaryRoot, reportPath, walkOutput, error) {
  const cleanup = safeOwnedEphemeralCleanup(temporaryRoot, true);
  const statusTruth = evaluateLauncherTerminal({ walkStatus: null, processTreeClosedVerified: true, workerExitVerified: false, error });
  const report = {
    schema_version: 'px.isolated-current-source-operational-walk/1.1',
    observed_utc: new Date().toISOString(),
    status: statusTruth.terminal_state,
    status_truth: statusTruth,
    phase: 'prelaunch-staging',
    authority: 'Codex host retained execution authority; PX governed scope, evidence, isolation, and cleanup.',
    effects: { created: ['PACIFY-X-owned temporary root', 'repository failure evidence'], spawned: [], user_main_vscode_profile_touched: false, isolation_boundary_verified: true, product_ui_modified: false, broad_tests_run: false },
    walk: { path: path.relative(repositoryRoot, walkOutput).replace(/\\/g, '/'), present: fs.existsSync(walkOutput) },
    child_lifecycle: null,
    owner_lifecycle: { process_tree_closed_verified: true, host_started: false },
    cleanup,
    error: String(error?.stack || error?.message || error).slice(0, 4000)
  };
  if (!cleanup.reclaimed) report.recovery = { retained_temporary_root: temporaryRoot, reason: cleanup.reason };
  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  return report;
}

async function main() {
  const stamp = utcStamp();
  const requestedVsix = argument('--vsix');
  const vsixPath = requestedVsix ? path.resolve(requestedVsix) : null;
  const bootstrapOnly = process.argv.includes('--bootstrap-only');
  const configurationOnly = process.argv.includes('--configuration-only');
  const studioLifecycleOnly = process.argv.includes('--studio-lifecycle-only');
  const knowledgeLifecycleOnly = process.argv.includes('--knowledge-lifecycle-only');
  if ([bootstrapOnly, configurationOnly, studioLifecycleOnly, knowledgeLifecycleOnly].filter(Boolean).length > 1) throw new Error('focused-launcher-modes-are-mutually-exclusive');
  if (vsixPath && (!fs.existsSync(vsixPath) || path.extname(vsixPath).toLowerCase() !== '.vsix')) throw new Error(`exact-vsix-missing:${vsixPath}`);
  const focusedProfile = configurationOnly ? 'reversible-configuration' : studioLifecycleOnly ? 'studio-lifecycle' : knowledgeLifecycleOnly ? 'knowledge-lifecycle' : null;
  const mode = `${vsixPath ? 'installed-vsix' : 'current-source'}${bootstrapOnly ? '-bootstrap' : focusedProfile ? `-${focusedProfile}` : ''}`;
  const walkOutput = path.resolve(argument('--output') || path.join(repositoryRoot, 'evidence', `operational-ui-walk-${mode}-${stamp}`));
  const reportPath = path.resolve(argument('--report') || path.join(repositoryRoot, 'evidence', 'operational-gap-ledger', `${mode}-host-walk-${stamp}.json`));
  for (const target of [walkOutput, reportPath, ...(vsixPath ? [vsixPath] : [])]) {
    const relative = path.relative(repositoryRoot, target);
    if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error(`walk-input-or-evidence-target-outside-repository:${target}`);
  }
  if (fs.existsSync(reportPath)) throw new Error(`evidence-report-already-exists:${reportPath}`);
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'pacify-x-current-source-walk-'));
  markOwnedHostWorkspace(temporaryRoot, `${vsixPath ? 'installed-vsix' : 'current-source'}-${bootstrapOnly ? 'bootstrap-activation' : focusedProfile || 'operational-ui-walk'}`);
  let config = null;
  let configPath = null;
  try {
    config = prepare(temporaryRoot, walkOutput, vsixPath, bootstrapOnly, configurationOnly, studioLifecycleOnly, knowledgeLifecycleOnly);
    configPath = path.join(temporaryRoot, 'host-config.json');
    fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  } catch (error) {
    reconcilePrelaunchFailure(temporaryRoot, reportPath, walkOutput, error);
    throw error;
  }
  let run = null;
  let lifecycle = null;
  let error = null;
  try {
    run = await runOwnedHostWorker({
      scriptPath: __filename,
      childFlag: CHILD_FLAG,
      configPath,
      cwd: extensionRoot,
      // The exhaustive installed-control campaign is intentionally larger
      // than the old four-minute bootstrap lease. Keep the outer owned-worker
      // boundary longer than the bootstrap release wait so the child can
      // publish its receipt and reconcile cleanup instead of being killed
      // mid-walk by its own harness.
      timeoutMs: 1_200_000,
      ownershipToken: config.userData,
      env: { ...nonBillableEnvironment(), PX_OWNED_VSCODE_HOST: '1' },
      stdout: process.stdout,
      stderr: process.stderr,
      onReceipt: value => { lifecycle = value; }
    });
  } catch (caught) {
    error = caught;
    lifecycle = caught.lifecycleReceipt || lifecycle;
  }
  let child = null;
  if (fs.existsSync(config.childResult)) child = JSON.parse(fs.readFileSync(config.childResult, 'utf8'));
  const statusTruth = evaluateLauncherTerminal({
    walkStatus: child?.operational_status || null,
    processTreeClosedVerified: lifecycle?.process_tree_closed_verified,
    workerExitVerified: run?.receipt?.worker_exit_verified,
    error
  });
  const report = {
    schema_version: 'px.isolated-current-source-operational-walk/1.1',
    observed_utc: new Date().toISOString(),
    status: statusTruth.terminal_state,
    status_truth: statusTruth,
    authority: 'Codex host retained execution authority; PX governed scope, evidence, isolation, and cleanup.',
    effects: {
      created: ['PACIFY-X-owned temporary engine copy', 'PACIFY-X-owned temporary workspace', 'PACIFY-X-owned user-data profile', 'PACIFY-X-owned empty extensions directory', 'PACIFY-X-owned shared-data directory', 'repository evidence'],
      spawned: bootstrapOnly ? ['pinned VS Code development host'] : ['pinned VS Code development host', 'existing operational UI walker'],
      user_main_vscode_profile_touched: child?.storage_boundary?.verified === true ? false : null,
      isolation_boundary_verified: child?.storage_boundary?.verified === true,
      product_ui_modified: false,
      broad_tests_run: false
    },
    source: {
      mode: vsixPath ? 'installed-exact-vsix' : 'extensionDevelopmentPath',
      extension_version: JSON.parse(fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf8')).version,
      extension_entry_sha256: sha256(path.join(extensionRoot, 'src', 'extension.js')),
      artifact: vsixPath ? { name: path.basename(vsixPath), sha256: sha256(vsixPath) } : null,
      walker_sha256: sha256(walkerPath),
      bootstrap_sha256: sha256(bootstrapPath),
      vscode_version: VSCODE_VERSION
    },
    isolation: {
      engine: config.stagedEngine ? {
        root: 'PACIFY-X-owned ephemeral current-source copy',
        copied_files: config.stagedEngine.copied_files,
        copied_bytes: config.stagedEngine.copied_bytes,
        required_file_sha256: config.stagedEngine.required_file_sha256,
        live_repository_used_as_engine: false
      } : null,
      workspace: 'PACIFY-X-owned ephemeral',
      user_data: 'PACIFY-X-owned ephemeral; not the user profile',
      extensions: 'PACIFY-X-owned empty directory',
      shared_data_requested: 'PACIFY-X-owned ephemeral; explicitly supplied through --shared-data-dir',
      shared_data_observed_mode: child?.storage_boundary?.mode || 'unverified',
      cdp: child?.cdp || null,
      extension_loading: vsixPath ? 'exact VSIX installed into owned empty extensions directory' : 'current repository source only'
    },
    operation: bootstrapOnly ? 'installed-extension-bootstrap-activation' : focusedProfile ? `focused-${focusedProfile}-walk` : 'operational-ui-walk',
    focused_profile: focusedProfile,
    full_operational_completion_claimed: focusedProfile ? false : child?.operational_status?.operationally_complete === true,
    bootstrap: bootstrapOnly ? child?.bootstrap || null : null,
    walk: bootstrapOnly ? null : child?.walk_receipt || { path: path.relative(repositoryRoot, config.walkReceipt).replace(/\\/g, '/'), present: fs.existsSync(config.walkReceipt) },
    child_lifecycle: child,
    owner_lifecycle: lifecycle,
    error: error ? String(error?.stack || error?.message || error).slice(0, 4000) : null
  };
  const cleanup = safeOwnedEphemeralCleanup(temporaryRoot, Boolean(lifecycle?.process_tree_closed_verified));
  report.cleanup = cleanup;
  if (!cleanup.reclaimed) report.recovery = { retained_temporary_root: temporaryRoot, reason: cleanup.reason };
  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  process.stdout.write(`${JSON.stringify({ status: report.status, report: reportPath, walk: walkOutput, cleanup }, null, 2)}\n`);
  if (report.status !== 'completed') throw error || new Error(`isolated-current-source-walk-${report.status}`);
  assert.equal(run?.receipt?.worker_exit_verified, true, 'owned worker exit was not verified');
}

if (require.main === module) {
  if (process.argv[2] === CHILD_FLAG) {
    childMain(process.argv[3]).then(code => { process.exitCode = code; }).catch(error => {
      process.stderr.write(`${error.stack || error.message}\n`);
      process.exitCode = 1;
    });
  } else if (process.argv.includes('--help')) {
    process.stdout.write('Usage: node scripts/run-isolated-current-source-walk.js [--bootstrap-only | --configuration-only | --studio-lifecycle-only | --knowledge-lifecycle-only] [--vsix <path>] [--output <path>] [--report <path>]\n');
  } else {
    main().catch(error => {
      process.stderr.write(`${error.stack || error.message}\n`);
      process.exitCode = 1;
    });
  }
}

module.exports = { classifySharedStoragePath, excludedEnginePath, reconcilePrelaunchFailure, stageDisposableEngine, stageOwnedKnowledgeFixture };
