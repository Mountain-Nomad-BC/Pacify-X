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
        PX_ENGINE_ROOT: repositoryRoot,
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
    lifecycle.status = 'walking';
    walker = childProcess.spawn(process.execPath, [walkerPath, endpoint, config.walkOutput, `--px-owned-token=${config.userData}`], {
      cwd: extensionRoot,
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...nonBillableEnvironment(), PX_OWNED_VSCODE_HOST: '1' }
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
    lifecycle.operational_status = evaluateOperationalWalk(walkReceipt, { additionalIssues: processIssues });
    if (!childError) lifecycle.status = `walk-${lifecycle.operational_status.terminal_state}`;
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

function prepare(temporaryRoot, walkOutput, vsixPath = null) {
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
    'pacifyX.engineRoot': repositoryRoot,
    'pacifyX.workspaceRoot': '',
    'pacifyX.pythonPath': process.platform === 'win32' ? 'python' : 'python3',
    'pacifyX.activity.enabled': false
  }, null, 2)}\n`, 'utf8');
  fs.mkdirSync(path.join(config.userData, 'User'), { recursive: true });
  fs.writeFileSync(path.join(config.userData, 'User', 'settings.json'), `${JSON.stringify({
    'extensions.autoUpdate': false,
    'extensions.autoCheckUpdates': false,
    'telemetry.telemetryLevel': 'off'
  }, null, 2)}\n`, 'utf8');
  fs.writeFileSync(path.join(config.workspace, 'README.md'), '# PACIFY-X owned operational walk workspace\n', 'utf8');
  return config;
}

async function main() {
  const stamp = utcStamp();
  const requestedVsix = argument('--vsix');
  const vsixPath = requestedVsix ? path.resolve(requestedVsix) : null;
  if (vsixPath && (!fs.existsSync(vsixPath) || path.extname(vsixPath).toLowerCase() !== '.vsix')) throw new Error(`exact-vsix-missing:${vsixPath}`);
  const mode = vsixPath ? 'installed-vsix' : 'current-source';
  const walkOutput = path.resolve(argument('--output') || path.join(repositoryRoot, 'evidence', `operational-ui-walk-${mode}-${stamp}`));
  const reportPath = path.resolve(argument('--report') || path.join(repositoryRoot, 'evidence', 'operational-gap-ledger', `${mode}-host-walk-${stamp}.json`));
  for (const target of [walkOutput, reportPath, ...(vsixPath ? [vsixPath] : [])]) {
    const relative = path.relative(repositoryRoot, target);
    if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error(`walk-input-or-evidence-target-outside-repository:${target}`);
  }
  if (fs.existsSync(reportPath)) throw new Error(`evidence-report-already-exists:${reportPath}`);
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'pacify-x-current-source-walk-'));
  markOwnedHostWorkspace(temporaryRoot, vsixPath ? 'installed-vsix-operational-ui-walk' : 'current-source-operational-ui-walk');
  const config = prepare(temporaryRoot, walkOutput, vsixPath);
  const configPath = path.join(temporaryRoot, 'host-config.json');
  fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
  let run = null;
  let lifecycle = null;
  let error = null;
  try {
    run = await runOwnedHostWorker({
      scriptPath: __filename,
      childFlag: CHILD_FLAG,
      configPath,
      cwd: extensionRoot,
      timeoutMs: 300_000,
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
      created: ['PACIFY-X-owned temporary workspace', 'PACIFY-X-owned user-data profile', 'PACIFY-X-owned empty extensions directory', 'PACIFY-X-owned shared-data directory', 'repository evidence'],
      spawned: ['pinned VS Code development host', 'existing operational UI walker'],
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
      workspace: 'PACIFY-X-owned ephemeral',
      user_data: 'PACIFY-X-owned ephemeral; not the user profile',
      extensions: 'PACIFY-X-owned empty directory',
      shared_data_requested: 'PACIFY-X-owned ephemeral; explicitly supplied through --shared-data-dir',
      shared_data_observed_mode: child?.storage_boundary?.mode || 'unverified',
      cdp: child?.cdp || null,
      extension_loading: vsixPath ? 'exact VSIX installed into owned empty extensions directory' : 'current repository source only'
    },
    walk: child?.walk_receipt || { path: path.relative(repositoryRoot, config.walkReceipt).replace(/\\/g, '/'), present: fs.existsSync(config.walkReceipt) },
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
  } else {
    main().catch(error => {
      process.stderr.write(`${error.stack || error.message}\n`);
      process.exitCode = 1;
    });
  }
}

module.exports = { classifySharedStoragePath };
