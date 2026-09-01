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
const { createParallelPlan, readCoordination } = require('../src/coordinationManager');
const { terminateProcessTreeAsync } = require('../src/processTree');
const { acquireHostLease, runOwnedHostWorker } = require('./owned-host-runner');
const { ensureOwnedVscodeTestCache, markOwnedHostWorkspace, resolveOwnedCachedVSCode } = require('./owned-vscode-test-cache');
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
const nativeInputHelperPath = path.join(__dirname, 'owned_windows_native_input.py');
const bootstrapPath = path.join(extensionRoot, 'tests', 'operational-walk-bootstrap', 'index.js');
const installedHarnessPath = path.join(extensionRoot, 'tests', 'installed-harness');
const MAX_CAPTURE = 2 * 1024 * 1024;
const MAX_PROFILE_PROGRESS = 2 * 1024 * 1024;
const HOST_PROGRESS_STAGES = new Set(['child-started', 'cache-ready', 'executable-ready', 'port-reserved', 'vscode-spawned', 'cdp-ready', 'storage-ready', 'native-helper-spawned', 'native-helper-ready', 'walker-spawned', 'walker-closed', 'native-helper-stop-requested', 'native-helper-closed', 'vscode-termination-started', 'vscode-closed', 'child-result-written']);
const ENGINE_COPY_EXCLUDED_ROOTS = new Set(['.git', '.vscode', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.venv', 'venv', 'node_modules', 'evidence']);
const ENGINE_COPY_EXCLUDED_PATHS = new Set(['extension/node_modules', 'extension/dist', '.engineering-bootstrap/diagnostics', '.engineering-bootstrap/test-evidence', '.engineering-bootstrap/resource-lifecycle', '.engineering-bootstrap/operation-bus']);
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

function boundedDelay(milliseconds) {
  const duration = Math.max(0, Number(milliseconds) || 0);
  return new Promise(resolve => setTimeout(resolve, duration));
}

function retainedProfileProgress(outputRoot) {
  const target = path.resolve(outputRoot, 'profile-progress.ndjson');
  try {
    if (!inside(outputRoot, target) || !fs.existsSync(target)) return null;
    const status = fs.lstatSync(target);
    if (!status.isFile() || status.isSymbolicLink() || status.size > MAX_PROFILE_PROGRESS) {
      return { schema_version: 'px.retained-profile-progress/1.0', valid: false, error: 'profile-progress-boundary-invalid' };
    }
    const records = fs.readFileSync(target, 'utf8').split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line));
    if (records.some(record => record?.schema_version !== 'px.operational-profile-progress/1.0'
      || typeof record.profile !== 'string' || !['started', 'returned'].includes(record.state))) {
      throw new Error('profile-progress-record-invalid');
    }
    const started = records.filter(record => record.state === 'started');
    const returned = records.filter(record => record.state === 'returned');
    return {
      schema_version: 'px.retained-profile-progress/1.0', valid: true,
      sha256: sha256(target), record_count: records.length,
      started_count: started.length, returned_count: returned.length,
      returned_with_errors: returned.filter(record => Number(record.error_count || 0) > 0).length,
      last_record: records.at(-1) || null
    };
  } catch (error) {
    return { schema_version: 'px.retained-profile-progress/1.0', valid: false, error: String(error?.message || error).slice(0, 200) };
  }
}

function appendHostProgress(outputRoot, stage, details = {}) {
  if (!HOST_PROGRESS_STAGES.has(stage)) throw new Error(`owned-host-progress-stage-invalid:${stage}`);
  const target = path.resolve(outputRoot, 'host-progress.ndjson');
  if (!inside(outputRoot, target)) throw new Error('owned-host-progress-path-invalid');
  const safe = {};
  for (const key of ['pid', 'ready_after_ms']) {
    if (Number.isSafeInteger(details[key]) && details[key] >= 0) safe[key] = details[key];
  }
  fs.appendFileSync(target, `${JSON.stringify({ schema_version: 'px.owned-host-progress/1.0', observed_utc: new Date().toISOString(), stage, ...safe })}\n`, { encoding: 'utf8' });
}

function retainedHostProgress(outputRoot) {
  const target = path.resolve(outputRoot, 'host-progress.ndjson');
  try {
    if (!inside(outputRoot, target) || !fs.existsSync(target)) return null;
    const status = fs.lstatSync(target);
    if (!status.isFile() || status.isSymbolicLink() || status.size > MAX_PROFILE_PROGRESS) throw new Error('host-progress-boundary-invalid');
    const records = fs.readFileSync(target, 'utf8').split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line));
    if (!records.length || records.some(record => record?.schema_version !== 'px.owned-host-progress/1.0' || !HOST_PROGRESS_STAGES.has(record.stage))) throw new Error('host-progress-record-invalid');
    return { schema_version: 'px.retained-host-progress/1.0', valid: true, sha256: sha256(target), record_count: records.length, last_record: records.at(-1) };
  } catch (error) {
    return { schema_version: 'px.retained-host-progress/1.0', valid: false, error: String(error?.message || error).slice(0, 200) };
  }
}

function electronHostEnvironment(extra = {}) {
  const environment = { ...nonBillableEnvironment(), ...extra };
  // Codex and CLI hosts may intentionally run Electron as Node. A VS Code
  // desktop child must not inherit that mode or it interprets the workspace
  // path as a JavaScript entry point.
  delete environment.ELECTRON_RUN_AS_NODE;
  return environment;
}

function ownedExternalNetworkDeniedEnvironment(environment = process.env) {
  const denied = 'http://127.0.0.1:9';
  return String(environment.HTTP_PROXY || '').toLowerCase() === denied
    && String(environment.HTTPS_PROXY || '').toLowerCase() === denied;
}

function waitForExit(child) {
  return new Promise((resolve, reject) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve({ code: child.exitCode, signal: child.signalCode || null });
      return;
    }
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

async function reserveLoopbackPort(timeoutMs = 5_000, createServer = () => net.createServer()) {
  const server = createServer();
  await new Promise((resolve, reject) => {
    let settled = false;
    const finish = error => { if (!settled) { settled = true; clearTimeout(timer); error ? reject(error) : resolve(); } };
    const timer = setTimeout(() => {
      try { server.close(() => {}); } catch {}
      finish(new Error('loopback-port-listen-timeout'));
    }, timeoutMs);
    server.once('error', finish);
    server.listen(0, '127.0.0.1', () => finish());
  });
  const address = server.address();
  const port = Number(address?.port);
  await new Promise((resolve, reject) => {
    let settled = false;
    const finish = error => { if (!settled) { settled = true; clearTimeout(timer); error ? reject(error) : resolve(); } };
    const timer = setTimeout(() => finish(new Error('loopback-port-close-timeout')), timeoutMs);
    server.close(finish);
  });
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

async function waitForIsolatedStorageBoundary(storageBoundary, host, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const observed = storageBoundary.result;
    if (observed.user_scoped_shared_data_observed) throw new Error('user-scoped-shared-storage-observed');
    if (observed.owned_shared_data_observed || observed.in_memory_observed) return observed;
    if (host.exitCode !== null || host.signalCode !== null) throw new Error(`vscode-host-exited-before-storage-boundary:${host.exitCode ?? host.signalCode}`);
    await new Promise(resolve => setTimeout(resolve, 50));
  } while (Date.now() < deadline);
  throw new Error('isolated-shared-storage-not-observed');
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
  const regularOperationalHost = config.regularOperationalHost === true;
  const lifecycle = {
    schema_version: 'px.isolated-current-source-host-child/1.0',
    started_utc: new Date().toISOString(),
    source_mode: config.vsixPath ? 'installed-exact-vsix' : 'extensionDevelopmentPath',
    vscode_pid: null,
    walker_pid: null,
    native_input_helper_pid: null,
    native_input_helper_exit: null,
    native_input_helper_termination_verified: null,
    cdp: null,
    vscode_termination_verified: false,
    walker_termination_verified: null,
    status: 'starting'
  };
  let vscode = null;
  let walker = null;
  let nativeInputHelper = null;
  let stdout = '';
  let stderr = '';
  let childError = null;
  const storageBoundary = storageBoundaryObserver(config);
  const nativeInputRequired = config.nativeInputRequired === true;
  const appendStdout = text => { storageBoundary.observe(text); stdout = `${stdout}${text}`.slice(-MAX_CAPTURE); process.stdout.write(text); };
  const appendStderr = text => { stderr = `${stderr}${text}`.slice(-MAX_CAPTURE); process.stderr.write(text); };
  appendHostProgress(config.walkOutput, 'child-started', { pid: process.pid });
  try {
    const cache = nativeInputRequired ? resolveOwnedCachedVSCode(VSCODE_VERSION) : ensureOwnedVscodeTestCache(VSCODE_VERSION);
    appendHostProgress(config.walkOutput, 'cache-ready');
    const executable = nativeInputRequired ? cache.executable : await downloadAndUnzipVSCode({ version: VSCODE_VERSION, cachePath: cache.root });
    appendHostProgress(config.walkOutput, 'executable-ready');
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
    appendHostProgress(config.walkOutput, 'port-reserved');
    const endpoint = `http://127.0.0.1:${port}`;
    const args = [
      config.workspace,
      '--new-window',
      '--window-size=1600,1000',
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
      ...(!regularOperationalHost ? [`--extensionTestsPath=${bootstrapPath}`] : []),
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
        PX_OPERATIONAL_WALK_BOOTSTRAP_SENTINEL: config.bootstrapSentinel,
        ...(!config.bootstrapOnly && !config.configurationOnly && !config.knowledgeLifecycleOnly && !config.hostBoundaryOnly && !config.nativeDialogOnly && !config.codexHandoffOnly && !config.errorIndicatorsOnly
          ? { PX_OPERATIONAL_EXERCISE_STUDIO_APPROVAL: '1' }
          : {})
      })
    });
    lifecycle.vscode_pid = Number(vscode.pid) || null;
    appendHostProgress(config.walkOutput, 'vscode-spawned', { pid: lifecycle.vscode_pid });
    capture(vscode.stdout, appendStdout);
    capture(vscode.stderr, appendStderr);
    lifecycle.cdp = { endpoint, address: '127.0.0.1', port, ready_after_ms: await waitForCdp(port, vscode) };
    appendHostProgress(config.walkOutput, 'cdp-ready', { ready_after_ms: lifecycle.cdp.ready_after_ms });
    if (regularOperationalHost) {
      lifecycle.bootstrap = {
        schema_version: 'px.operational-walk-bootstrap/1.0',
        status: 'deferred-to-operational-walker',
        test_mode: false,
        command_id: 'pacifyX.openDashboard',
        command_registered: null,
        command_executed: false,
        ready_utc: new Date().toISOString()
      };
    } else {
      lifecycle.bootstrap = await waitForJsonFile(config.bootstrapReceipt, vscode);
      assert.equal(lifecycle.bootstrap.status, 'ready', `operational-bootstrap:${lifecycle.bootstrap.status || 'unknown'}`);
      assert.equal(lifecycle.bootstrap.command_registered, true, 'operational-bootstrap-command-unregistered');
      assert.equal(lifecycle.bootstrap.command_executed, true, 'operational-bootstrap-command-not-executed');
    }
    await waitForIsolatedStorageBoundary(storageBoundary, vscode);
    appendHostProgress(config.walkOutput, 'storage-ready');
    assert.equal(storageBoundary.result.user_scoped_shared_data_observed, false, 'user-scoped-shared-storage-observed');
    if (nativeInputRequired) {
      assert.equal(process.platform, 'win32', 'owned-native-input-requires-windows');
      const helperConfig = path.join(config.nativeInputRoot, 'helper-config.json');
      fs.writeFileSync(helperConfig, `${JSON.stringify({
        schema_version: 'px.owned-native-input-config/1.0',
        root: config.nativeInputRoot,
        secret: config.nativeInputSecret,
        vscode_pid: lifecycle.vscode_pid,
        ownership_token: config.userData
      }, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
      nativeInputHelper = childProcess.spawn('python', [nativeInputHelperPath, '--serve', helperConfig, `--px-owned-token=${config.userData}`], {
        cwd: extensionRoot, shell: false, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], env: nonBillableEnvironment()
      });
      lifecycle.native_input_helper_pid = Number(nativeInputHelper.pid) || null;
      appendHostProgress(config.walkOutput, 'native-helper-spawned', { pid: lifecycle.native_input_helper_pid });
      capture(nativeInputHelper.stdout, appendStdout);
      capture(nativeInputHelper.stderr, appendStderr);
      const ready = await waitForJsonFile(path.join(config.nativeInputRoot, 'ready.json'), nativeInputHelper, 15_000);
      assert.equal(ready.schema_version, 'px.owned-native-input-ready/1.0', 'owned-native-input-ready-schema-invalid');
      assert.equal(ready.pid, lifecycle.native_input_helper_pid, 'owned-native-input-ready-pid-mismatch');
      assert.equal(ready.vscode_pid, lifecycle.vscode_pid, 'owned-native-input-ready-vscode-pid-mismatch');
      lifecycle.native_input_helper_ready = true;
      appendHostProgress(config.walkOutput, 'native-helper-ready');
    }
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
          PX_OWNED_VSCODE_WORKSPACE_ROOT: config.workspace,
          PX_OWNED_VSCODE_EXTENSIONS_ROOT: config.extensions,
          ...(ownedExternalNetworkDeniedEnvironment() ? { PX_OWNED_EXTERNAL_NETWORK_DENIED: '1' } : {}),
          ...(config.knowledgeFixture ? {
            PX_OWNED_KNOWLEDGE_SOURCE_ID: config.knowledgeFixture.source_id,
            PX_OWNED_KNOWLEDGE_SOURCE_SHA256: config.knowledgeFixture.source_sha256
          } : {}),
          ...(config.configurationOnly ? { PX_OPERATIONAL_CONFIGURATION_ONLY: '1' } : {}),
          ...(config.studioLifecycleOnly ? { PX_OPERATIONAL_STUDIO_LIFECYCLE_ONLY: '1' } : {}),
          ...(config.knowledgeLifecycleOnly ? { PX_OPERATIONAL_KNOWLEDGE_LIFECYCLE_ONLY: '1' } : {}),
          ...(config.hostBoundaryOnly ? { PX_OPERATIONAL_HOST_BOUNDARY_ONLY: '1' } : {}),
          ...(config.nativeDialogOnly ? { PX_OPERATIONAL_NATIVE_DIALOG_ONLY: '1' } : {}),
          ...(config.codexHandoffOnly ? { PX_OPERATIONAL_CODEX_HANDOFF_ONLY: '1' } : {}),
          ...(config.errorIndicatorsOnly ? { PX_OPERATIONAL_ERROR_INDICATORS_ONLY: '1' } : {}),
          ...(nativeInputRequired ? {
            PX_OWNED_NATIVE_INPUT_ROOT: config.nativeInputRoot,
            PX_OWNED_NATIVE_INPUT_TOKEN: config.userData,
            PX_OWNED_NATIVE_INPUT_SECRET: config.nativeInputSecret,
            PX_OWNED_NATIVE_INPUT_VSCODE_PID: String(lifecycle.vscode_pid)
          } : {}),
          ...(config.postAuditLongRunning ? { PX_OPERATIONAL_POST_AUDIT_LONG_RUNNING: '1' } : {})
        }
      });
      lifecycle.walker_pid = Number(walker.pid) || null;
      appendHostProgress(config.walkOutput, 'walker-spawned', { pid: lifecycle.walker_pid });
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
    if (walker) appendHostProgress(config.walkOutput, 'walker-closed');
    if (nativeInputHelper) {
      const helperExit = waitForExit(nativeInputHelper);
      try {
        fs.writeFileSync(path.join(config.nativeInputRoot, 'stop.json'), `${JSON.stringify({ requested_utc: new Date().toISOString() })}\n`, { encoding: 'utf8', flag: 'wx' });
      } catch (error) {
        if (error?.code !== 'EEXIST') lifecycle.native_input_helper_stop_error = String(error?.message || error).slice(0, 500);
      }
      appendHostProgress(config.walkOutput, 'native-helper-stop-requested');
      const boundedExit = await Promise.race([helperExit, boundedDelay(5_000).then(() => null)]);
      if (boundedExit) {
        lifecycle.native_input_helper_exit = boundedExit;
        lifecycle.native_input_helper_termination_verified = boundedExit.signal === null;
        if (boundedExit.code !== 0 || boundedExit.signal !== null) lifecycle.native_input_helper_exit_error = `exit-${boundedExit.code}:signal-${boundedExit.signal || 'none'}`;
      } else {
        lifecycle.native_input_helper_termination_verified = await terminateProcessTreeAsync(nativeInputHelper, { graceMs: 750, verifyMs: 10_000 });
      }
      appendHostProgress(config.walkOutput, 'native-helper-closed');
    }
    if (vscode) {
      appendHostProgress(config.walkOutput, 'vscode-termination-started');
      lifecycle.vscode_termination_verified = await terminateProcessTreeAsync(vscode, { graceMs: 1000, verifyMs: 15_000 });
      appendHostProgress(config.walkOutput, 'vscode-closed');
    }
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
    if (nativeInputRequired && lifecycle.native_input_helper_termination_verified !== true) processIssues.push('owned-native-input-helper-termination-unverified');
    if (nativeInputRequired && lifecycle.native_input_helper_exit_error) processIssues.push(`owned-native-input-helper-${lifecycle.native_input_helper_exit_error}`);
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
    appendHostProgress(config.walkOutput, 'child-result-written');
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

function runOwnedRuntimeJson(engineRoot, args) {
  const runtime = childProcess.spawnSync(process.platform === 'win32' ? 'python' : 'python3', ['-m', 'runtime.cli', '--root', engineRoot, ...args], {
    cwd: engineRoot,
    shell: false,
    windowsHide: true,
    encoding: 'utf8',
    timeout: 120_000,
    maxBuffer: 4 * 1024 * 1024,
    env: { ...nonBillableEnvironment(), PYTHONDONTWRITEBYTECODE: '1' }
  });
  if (runtime.error || runtime.status !== 0) throw new Error(`owned-host-boundary-runtime-command-failed:${args.slice(0, 2).join(':')}:${String(runtime.error?.message || runtime.stderr || runtime.stdout || `exit-${runtime.status}`).slice(0, 2000)}`);
  try { return JSON.parse(String(runtime.stdout || '')); }
  catch (error) { throw new Error(`owned-host-boundary-runtime-json-invalid:${args.slice(0, 2).join(':')}:${String(error?.message || error)}`); }
}

function stageOwnedProviderPaginationFixture(engineRoot) {
  const engine = fs.realpathSync.native(engineRoot);
  const policyPath = path.join(engine, 'registry', 'provider_budget_policy.json');
  if (!inside(engine, policyPath) || !fs.existsSync(policyPath) || fs.lstatSync(policyPath).isSymbolicLink() || !fs.lstatSync(policyPath).isFile()) throw new Error('owned-provider-pagination-policy-invalid');
  const policyBeforeSha256 = sha256(policyPath);
  const policy = JSON.parse(fs.readFileSync(policyPath, 'utf8'));
  if (!Array.isArray(policy?.budgets)) throw new Error('owned-provider-pagination-budgets-invalid');
  const baseline = policy.budgets.find(row => row?.enabled === true && row?.provider_id === 'ollama');
  if (!baseline) throw new Error('owned-provider-pagination-local-baseline-missing');
  const owned = {
    ...baseline,
    budget_id: 'px-owned-pagination',
    actor_id: 'px-owned-pagination',
    enabled: true,
    hard_limit_microunits: 0,
    warning_threshold_microunits: 0,
    max_charge_per_request_microunits: 0,
    unknown_billing: 'deny',
    unknown_charge_microunits: 0,
    fallback_adapter_ids: []
  };
  const ownedKey = `${owned.provider_id}:${owned.budget_id}:${owned.actor_id}`;
  if (policy.budgets.some(row => `${row?.provider_id}:${row?.budget_id}:${row?.actor_id}` === ownedKey)) throw new Error('owned-provider-pagination-fixture-already-present');
  policy.budgets.push(owned);
  fs.writeFileSync(policyPath, `${JSON.stringify(policy, null, 2)}\n`, 'utf8');
  const projected = JSON.parse(fs.readFileSync(policyPath, 'utf8'));
  const enabled = projected.budgets.filter(row => row?.enabled === true);
  if (enabled.filter(row => `${row?.provider_id}:${row?.budget_id}:${row?.actor_id}` === ownedKey).length !== 1 || enabled.length < 2) throw new Error('owned-provider-pagination-projection-invalid');
  return {
    schema_version: 'px.owned-provider-pagination-fixture/1.0',
    provider_count: enabled.length,
    owned_provider_id: ownedKey,
    policy_before_sha256: policyBeforeSha256,
    policy_after_sha256: sha256(policyPath),
    local_non_billable: true
  };
}

function stageOwnedHostBoundaryFixture(workspaceRoot, engineRoot, { runtimeCommand = runOwnedRuntimeJson } = {}) {
  const workspace = fs.realpathSync.native(workspaceRoot);
  const engine = fs.realpathSync.native(engineRoot);
  if (fs.lstatSync(workspace).isSymbolicLink() || fs.lstatSync(engine).isSymbolicLink()) throw new Error('owned-host-boundary-fixture-root-linked');
  const taskId = 'host-boundary-fixture-task';
  const actor = { actorId: 'px-host-boundary-fixture', sessionId: 'px-host-boundary-fixture', harness: 'VS Code', accountableOwner: 'PACIFY-X owned operational walker' };
  createParallelPlan(workspace, actor, {
    id: 'host-boundary-fixture-plan',
    objective: 'Provide exact disposable state for typed host-boundary controls.',
    tasks: [{ id: taskId, title: 'Inspect exact disposable task handoff', claims: ['.px-owned/host-boundary-fixture'], acceptance: ['Exact task handoff is copyable through the installed host.'] }]
  });
  const coordination = readCoordination(workspace);
  if (!coordination.instrumented || coordination.state?.tasks?.filter(item => item.id === taskId).length !== 1) throw new Error('owned-host-boundary-coordination-fixture-invalid');
  const handoffPath = coordination.paths?.handoff_markdown;
  if (!handoffPath || !inside(workspace, handoffPath) || !fs.existsSync(handoffPath) || fs.lstatSync(handoffPath).isSymbolicLink()) throw new Error('owned-host-boundary-handoff-fixture-invalid');

  const initialized = runtimeCommand(engine, ['workspace', 'init', '--workspace', workspace, '--apply']);
  if (initialized?.valid !== true) throw new Error('owned-host-boundary-workspace-initialization-invalid');
  const projectName = 'px-owned-memory-profile';
  const projectId = 'prj_px-owned-memory-profile';
  const created = runtimeCommand(engine, ['workspace', 'create-project', '--workspace', workspace, '--name', projectName, '--apply']);
  if (created?.valid !== true || created?.project?.project_id !== projectId) throw new Error('owned-host-boundary-project-fixture-invalid');
  const projectRoot = path.join(workspace, 'projects', projectName);
  const sourcePath = path.join(projectRoot, 'host-boundary-memory.md');
  if (!inside(workspace, projectRoot) || !inside(projectRoot, sourcePath) || !fs.existsSync(projectRoot) || fs.lstatSync(projectRoot).isSymbolicLink() || fs.existsSync(sourcePath)) throw new Error('owned-host-boundary-memory-source-target-invalid');
  const source = '# PACIFY-X owned host-boundary memory\n\nCertified disposable source for the exact open-memory-source host action.\n';
  fs.writeFileSync(sourcePath, source, { encoding: 'utf8', flag: 'wx' });
  const activated = runtimeCommand(engine, ['project', 'activate', '--workspace', workspace, '--project-id', projectId, '--agent-id', 'human-local-user', '--session-id', 'vscode-dashboard', '--context-reset-confirmed']);
  if (activated?.activated !== true && activated?.already_active !== true) throw new Error('owned-host-boundary-project-activation-invalid');
  const ingested = runtimeCommand(engine, ['memory', 'ingest', '--workspace', workspace, '--project-id', projectId, '--source', sourcePath, '--session-id', 'vscode-dashboard', '--actor-id', 'human-local-user', '--apply']);
  const rawMemoryIds = Array.isArray(ingested?.outputs?.memory_ids) ? ingested.outputs.memory_ids : [];
  const memoryIds = [...new Set(rawMemoryIds)].sort();
  if (ingested?.valid !== true || memoryIds.length < 1 || memoryIds.length > 64 || memoryIds.length !== rawMemoryIds.length || memoryIds.some(value => typeof value !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/.test(value))) throw new Error(`owned-host-boundary-memory-ingest-invalid:${JSON.stringify({ valid: ingested?.valid === true, memory_id_count: memoryIds.length, duplicate_count: rawMemoryIds.length - memoryIds.length })}`);
  for (const memoryId of memoryIds) for (const [target, evidence] of [['validated', 'owned-host-boundary-validation'], ['certified', 'owned-host-boundary-certification']]) {
    const transitioned = runtimeCommand(engine, ['memory', 'transition', '--workspace', workspace, '--project-id', projectId, '--memory-id', memoryId, '--target', target, '--evidence', evidence, '--session-id', 'vscode-dashboard', '--actor-id', 'human-local-user', '--apply']);
    if (transitioned?.valid !== true || transitioned?.applied !== true) throw new Error(`owned-host-boundary-memory-${target}-invalid:${memoryId}`);
  }
  const memoryId = memoryIds[0];
  const providerPagination = stageOwnedProviderPaginationFixture(engine);
  return {
    schema_version: 'px.owned-host-boundary-fixture/1.0',
    task_id: taskId,
    coordination_handoff_relative: path.relative(workspace, handoffPath).replace(/\\/g, '/'),
    coordination_handoff_sha256: sha256(handoffPath),
    project_id: projectId,
    memory_id: memoryId,
    memory_ids: memoryIds,
    memory_record_count: memoryIds.length,
    memory_source_relative: path.relative(workspace, sourcePath).replace(/\\/g, '/'),
    memory_source_sha256: sha256(sourcePath),
    provider_pagination: providerPagination,
    lifecycle: ['workspace-initialized', 'project-created', 'project-activated', 'memory-ingested', 'memory-validated', 'memory-certified']
  };
}

function prepare(temporaryRoot, walkOutput, vsixPath = null, bootstrapOnly = false, configurationOnly = false, studioLifecycleOnly = false, knowledgeLifecycleOnly = false, hostBoundaryOnly = false, nativeDialogOnly = false, codexHandoffOnly = false, errorIndicatorsOnly = false, postAuditLongRunning = false) {
  const stagedEngine = stageDisposableEngine(repositoryRoot, temporaryRoot);
  const hostBoundaryFixtureRequired = hostBoundaryOnly || (!bootstrapOnly && !configurationOnly && !studioLifecycleOnly && !knowledgeLifecycleOnly && !nativeDialogOnly);
  const fullOperationalWalk = !bootstrapOnly && !configurationOnly && !studioLifecycleOnly && !knowledgeLifecycleOnly && !hostBoundaryOnly && !nativeDialogOnly && !codexHandoffOnly && !errorIndicatorsOnly;
  const nativeInputRequired = nativeDialogOnly || postAuditLongRunning || fullOperationalWalk;
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
    hostBoundaryOnly,
    nativeDialogOnly,
    codexHandoffOnly,
    errorIndicatorsOnly,
    nativeInputRequired,
    nativeInputRoot: path.join(temporaryRoot, 'native-input'),
    nativeInputSecret: nativeInputRequired ? crypto.randomBytes(32).toString('hex') : null,
    postAuditLongRunning,
    // Operational walks must own a normal isolated host even when the product
    // came from an exact VSIX. An extension-test host cannot survive the
    // extension-host restart required to reconcile install/uninstall receipts.
    // Bootstrap-only remains the sole extension-test-host campaign.
    regularOperationalHost: !bootstrapOnly,
    vsixPath,
    vsixSha256: vsixPath ? sha256(vsixPath) : null
  };
  for (const directory of [config.workspace, config.userData, config.extensions, config.sharedData, config.walkOutput]) {
    fs.mkdirSync(directory, { recursive: true });
  }
  if (nativeInputRequired) {
    for (const directory of [config.nativeInputRoot, path.join(config.nativeInputRoot, 'requests'), path.join(config.nativeInputRoot, 'results')]) {
      fs.mkdirSync(directory, { recursive: true });
      if (!inside(temporaryRoot, directory) || fs.lstatSync(directory).isSymbolicLink()) throw new Error(`owned-native-input-directory-invalid:${directory}`);
    }
  }
  for (const directory of [config.workspace, config.userData, config.extensions, config.sharedData]) {
    if (!inside(temporaryRoot, directory) || fs.lstatSync(directory).isSymbolicLink()) throw new Error(`owned-host-directory-invalid:${directory}`);
  }
  fs.mkdirSync(path.join(config.workspace, '.vscode'), { recursive: true });
  fs.writeFileSync(path.join(config.workspace, '.vscode', 'settings.json'), `${JSON.stringify({
    'pacifyX.engineRoot': config.engineRoot,
    'pacifyX.workspaceRoot': hostBoundaryFixtureRequired ? config.workspace : '',
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
  config.gitAuthority = fullOperationalWalk ? stageOwnedGitAuthority(config.workspace) : null;
  config.hostBoundaryFixture = hostBoundaryFixtureRequired ? stageOwnedHostBoundaryFixture(config.workspace, config.engineRoot) : null;
  if (!bootstrapOnly && !configurationOnly && !knowledgeLifecycleOnly && !hostBoundaryOnly && !nativeDialogOnly && !codexHandoffOnly && !errorIndicatorsOnly) {
    const promptRoot = path.join(config.engineRoot, '.px', 'owned-operational-prompts');
    const setupPrompt = path.join(promptRoot, 'setup-studio.marker');
    if (!inside(config.engineRoot, promptRoot) || !inside(config.engineRoot, setupPrompt)) throw new Error('owned-setup-prompt-marker-outside-engine');
    fs.mkdirSync(promptRoot, { recursive: true });
    if (fs.lstatSync(promptRoot).isSymbolicLink()) throw new Error('owned-setup-prompt-root-linked');
    fs.writeFileSync(setupPrompt, 'exercise-native-setup-approval\n', { encoding: 'utf8', flag: 'wx' });
  }
  config.knowledgeFixture = bootstrapOnly || configurationOnly || studioLifecycleOnly || nativeDialogOnly || codexHandoffOnly ? null : stageOwnedKnowledgeFixture(config.workspace, config.engineRoot);
  return config;
}

function stageOwnedGitAuthority(workspaceRoot) {
  const workspace = fs.realpathSync.native(workspaceRoot);
  const gitRoot = path.join(workspace, '.git');
  if (!inside(workspace, gitRoot) || fs.existsSync(gitRoot)) throw new Error('owned-git-authority-target-unavailable');
  const directories = [
    gitRoot, path.join(gitRoot, 'objects'), path.join(gitRoot, 'objects', 'info'), path.join(gitRoot, 'objects', 'pack'),
    path.join(gitRoot, 'refs'), path.join(gitRoot, 'refs', 'heads'), path.join(gitRoot, 'refs', 'tags')
  ];
  for (const directory of directories) {
    fs.mkdirSync(directory);
    if (!inside(workspace, directory) || fs.lstatSync(directory).isSymbolicLink()) throw new Error('owned-git-authority-directory-invalid');
  }
  const config = '[core]\n\trepositoryformatversion = 0\n\tfilemode = false\n\tbare = false\n\tlogallrefupdates = true\n\tsymlinks = false\n\tignorecase = true\n';
  fs.writeFileSync(path.join(gitRoot, 'HEAD'), 'ref: refs/heads/main\n', { encoding: 'utf8', flag: 'wx' });
  fs.writeFileSync(path.join(gitRoot, 'config'), config, { encoding: 'utf8', flag: 'wx' });
  fs.writeFileSync(path.join(gitRoot, 'description'), 'PACIFY-X owned disposable operational authority\n', { encoding: 'utf8', flag: 'wx' });
  return {
    schema_version: 'px.owned-disposable-git-authority/1.0',
    repository_relative: '.',
    git_directory_relative: '.git',
    head: 'refs/heads/main',
    config_sha256: crypto.createHash('sha256').update(config).digest('hex'),
    network_used: false,
    user_git_configuration_read_or_written: false
  };
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

function acquireWalkOwnership(options = {}) {
  const lease = acquireHostLease(options);
  let temporaryRoot = null;
  try {
    const makeTemporaryRoot = options.makeTemporaryRoot
      || (() => fs.mkdtempSync(path.join(os.tmpdir(), 'pacify-x-current-source-walk-')));
    temporaryRoot = makeTemporaryRoot();
    markOwnedHostWorkspace(temporaryRoot, options.ownershipLabel || 'current-source-operational-ui-walk');
    return { lease, temporaryRoot };
  } catch (error) {
    if (temporaryRoot) {
      try { fs.rmSync(temporaryRoot, { recursive: true, force: true }); } catch {}
    }
    lease.release();
    throw error;
  }
}

function reconcileOwnedPrelaunchFailure(ownership, reportPath, walkOutput, error) {
  try {
    return reconcilePrelaunchFailure(ownership.temporaryRoot, reportPath, walkOutput, error);
  } finally {
    // The evidence write is deliberately fail-closed (`wx`). Even if that
    // write itself loses a race, the pre-acquired owner lease must never be
    // stranded and block every later owned-host run.
    ownership.lease.release();
  }
}

async function main() {
  const stamp = utcStamp();
  const requestedVsix = argument('--vsix');
  const vsixPath = requestedVsix ? path.resolve(requestedVsix) : null;
  const bootstrapOnly = process.argv.includes('--bootstrap-only');
  const configurationOnly = process.argv.includes('--configuration-only');
  const studioLifecycleOnly = process.argv.includes('--studio-lifecycle-only');
  const knowledgeLifecycleOnly = process.argv.includes('--knowledge-lifecycle-only');
  const hostBoundaryOnly = process.argv.includes('--host-boundary-only');
  const nativeDialogOnly = process.argv.includes('--native-dialog-only');
  const codexHandoffOnly = process.argv.includes('--codex-handoff-only');
  const errorIndicatorsOnly = process.argv.includes('--error-indicators-only');
  const postAuditLongRunning = process.argv.includes('--post-audit-long-running');
  if ([bootstrapOnly, configurationOnly, studioLifecycleOnly, knowledgeLifecycleOnly, hostBoundaryOnly, nativeDialogOnly, codexHandoffOnly, errorIndicatorsOnly].filter(Boolean).length > 1) throw new Error('focused-launcher-modes-are-mutually-exclusive');
  if (postAuditLongRunning && (bootstrapOnly || configurationOnly || studioLifecycleOnly || knowledgeLifecycleOnly || hostBoundaryOnly || nativeDialogOnly || codexHandoffOnly || errorIndicatorsOnly)) throw new Error('post-audit-long-running-requires-full-profile');
  if (vsixPath && (!fs.existsSync(vsixPath) || path.extname(vsixPath).toLowerCase() !== '.vsix')) throw new Error(`exact-vsix-missing:${vsixPath}`);
  const focusedProfile = configurationOnly ? 'reversible-configuration' : studioLifecycleOnly ? 'studio-lifecycle' : knowledgeLifecycleOnly ? 'knowledge-lifecycle' : hostBoundaryOnly ? 'host-boundary' : nativeDialogOnly ? 'native-dialog-boundary' : codexHandoffOnly ? 'codex-handoff' : errorIndicatorsOnly ? 'error-indicators' : null;
  const mode = `${vsixPath ? 'installed-vsix' : 'current-source'}${bootstrapOnly ? '-bootstrap' : focusedProfile ? `-${focusedProfile}` : ''}`;
  const walkOutput = path.resolve(argument('--output') || path.join(repositoryRoot, 'evidence', `operational-ui-walk-${mode}-${stamp}`));
  const reportPath = path.resolve(argument('--report') || path.join(repositoryRoot, 'evidence', 'operational-gap-ledger', `${mode}-host-walk-${stamp}.json`));
  for (const target of [walkOutput, reportPath, ...(vsixPath ? [vsixPath] : [])]) {
    const relative = path.relative(repositoryRoot, target);
    if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error(`walk-input-or-evidence-target-outside-repository:${target}`);
  }
  if (fs.existsSync(reportPath)) throw new Error(`evidence-report-already-exists:${reportPath}`);
  // Acquire the single-host lease before allocating any output namespace or
  // owned ephemeral. A rejected duplicate therefore has no report, output,
  // or cleanup authority belonging to the legitimate in-flight owner.
  const ownership = acquireWalkOwnership({
    ownershipLabel: `${vsixPath ? 'installed-vsix' : 'current-source'}-${bootstrapOnly ? 'bootstrap-activation' : focusedProfile || 'operational-ui-walk'}`
  });
  const { lease: hostLease, temporaryRoot } = ownership;
  let config = null;
  let configPath = null;
  try {
    config = prepare(temporaryRoot, walkOutput, vsixPath, bootstrapOnly, configurationOnly, studioLifecycleOnly, knowledgeLifecycleOnly, hostBoundaryOnly, nativeDialogOnly, codexHandoffOnly, errorIndicatorsOnly, postAuditLongRunning);
    configPath = path.join(temporaryRoot, 'host-config.json');
    fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  } catch (error) {
    reconcileOwnedPrelaunchFailure(ownership, reportPath, walkOutput, error);
    throw error;
  }
  let run = null;
  let lifecycle = null;
  let error = null;
  try {
    run = await runOwnedHostWorker({
      lease: hostLease,
      scriptPath: __filename,
      childFlag: CHILD_FLAG,
      configPath,
      cwd: extensionRoot,
      // The exhaustive installed-control campaign is intentionally larger
      // than the old four-minute bootstrap lease. Keep the outer owned-worker
      // boundary longer than the bootstrap release wait so the child can
      // publish its receipt and reconcile cleanup instead of being killed
      // mid-walk by its own harness.
      // A full post-audit campaign exercises every admitted stateful profile
      // and can legitimately exceed the ordinary twenty-minute walk bound.
      // Keep it bounded, but do not let the owner terminate a healthy campaign
      // before the child can publish its receipt and reconcile its resources.
      timeoutMs: postAuditLongRunning ? 3_600_000 : 1_800_000,
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
    workerExitVerified: run?.receipt?.worker_exit_verified ?? lifecycle?.worker_exit_verified,
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
    owned_host_boundary_fixture: config.hostBoundaryFixture,
    owned_git_authority: config.gitAuthority,
    operation: bootstrapOnly ? 'installed-extension-bootstrap-activation' : focusedProfile ? `focused-${focusedProfile}-walk` : 'operational-ui-walk',
    focused_profile: focusedProfile,
    post_audit_long_running_authority: postAuditLongRunning,
    full_operational_completion_claimed: focusedProfile ? false : child?.operational_status?.operationally_complete === true,
    partial_profile_progress: child?.walk_receipt ? null : retainedProfileProgress(walkOutput),
    partial_host_progress: child?.walk_receipt ? null : retainedHostProgress(walkOutput),
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
    process.stdout.write('Usage: node scripts/run-isolated-current-source-walk.js [--post-audit-long-running | --bootstrap-only | --configuration-only | --studio-lifecycle-only | --knowledge-lifecycle-only | --host-boundary-only | --native-dialog-only | --codex-handoff-only | --error-indicators-only] [--vsix <path>] [--output <path>] [--report <path>]\n');
  } else {
    main().catch(error => {
      process.stderr.write(`${error.stack || error.message}\n`);
      process.exitCode = 1;
    });
  }
}

module.exports = { acquireWalkOwnership, appendHostProgress, boundedDelay, classifySharedStoragePath, excludedEnginePath, ownedExternalNetworkDeniedEnvironment, reconcileOwnedPrelaunchFailure, reconcilePrelaunchFailure, reserveLoopbackPort, retainedHostProgress, retainedProfileProgress, stageDisposableEngine, stageOwnedGitAuthority, stageOwnedHostBoundaryFixture, stageOwnedKnowledgeFixture, stageOwnedProviderPaginationFixture, waitForIsolatedStorageBoundary };
