'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { downloadAndUnzipVSCode, resolveCliArgsFromVSCodeExecutablePath, runTests } = require('@vscode/test-electron');
const { nonBillableEnvironment } = require('../src/contextBridge');
const { runOwnedHostWorker } = require('./owned-host-runner');
const { ensureOwnedVscodeTestCache, markOwnedHostWorkspace } = require('./owned-vscode-test-cache');

const CHILD_FLAG = '--owned-host-child';
const extensionRoot = path.resolve(__dirname, '..');
const extensionPackage = JSON.parse(fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf8'));
const platformSuffix = process.platform === 'win32' ? '' : `-${process.platform}`;
const retainedReceipt = path.join(extensionRoot, 'evidence', `installed-vsix-smoke${platformSuffix}.json`);
const retainedLifecycleReceipt = path.join(extensionRoot, 'evidence', `installed-vsix-process-lifecycle${platformSuffix}.json`);
const vscodeVersion = '1.132.1';
const digest = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const engineIdentity = engineRoot => {
  if (!engineRoot) return null;
  const manifestPath = path.join(engineRoot, 'registry', 'engine_identity.json');
  assert.ok(fs.existsSync(manifestPath), 'PX engine identity manifest is missing');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  assert.equal(manifest.schema_version, 'px.engine-identity/1.0', 'PX engine identity schema is unsupported');
  assert.match(String(manifest.tree_sha256 || ''), /^[0-9a-f]{64}$/, 'PX engine tree identity is invalid');
  return {
    manifest_path: 'registry/engine_identity.json',
    manifest_sha256: digest(manifestPath),
    tree_sha256: manifest.tree_sha256,
    file_total: manifest.file_total
  };
};
const argument = name => {
  const index = process.argv.indexOf(name);
  return index >= 0 && process.argv[index + 1] ? process.argv[index + 1] : null;
};

function portableHostReceipt(value) {
  const portable = JSON.parse(JSON.stringify(value));
  if (portable?.live_dashboard?.source?.engineRoot) portable.live_dashboard.source.engineRoot = '[connected-engine-root]';
  return portable;
}

async function childMain(configPath) {
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  const before = digest(config.vsixPath);
  const cache = ensureOwnedVscodeTestCache(vscodeVersion);
  const executable = await downloadAndUnzipVSCode({ version: vscodeVersion, cachePath: cache.root });
  const [cli, ...cliPrefix] = resolveCliArgsFromVSCodeExecutablePath(executable, { reuseMachineInstall: true });
  const install = childProcess.spawnSync(
    cli, [...cliPrefix, `--extensions-dir=${config.extensions}`, `--user-data-dir=${config.userData}`, '--install-extension', config.vsixPath, '--force'],
    { encoding: 'utf8', shell: process.platform === 'win32', timeout: 120000, windowsHide: true }
  );
  assert.equal(install.error, undefined, install.error?.message);
  assert.equal(install.status, 0, `VSIX install failed:\n${install.stdout}\n${install.stderr}`);
  assert.match(`${install.stdout}\n${install.stderr}`, /successfully installed/i);
  delete process.env.ELECTRON_RUN_AS_NODE;
  const status = await runTests({
    vscodeExecutablePath: executable,
    extensionDevelopmentPath: path.join(extensionRoot, 'tests', 'installed-harness'),
    extensionTestsPath: path.join(extensionRoot, 'tests', 'vscode-host', 'index.js'),
    extensionTestsEnv: {
      PX_VSCODE_SMOKE_RECEIPT: config.hostReceipt,
      PX_EXPECT_CANONICAL_BUS: config.engineRoot ? '1' : '0',
      PX_ENGINE_ROOT: config.engineRoot || '',
      PX_PYTHON_PATH: process.platform === 'win32' ? 'python' : 'python3'
    },
    launchArgs: [config.workspace, `--user-data-dir=${config.userData}`, `--extensions-dir=${config.extensions}`, '--disable-updates', '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes', ...(process.platform === 'linux' ? ['--no-sandbox', '--disable-gpu'] : [])]
  });
  assert.equal(status, 0, `Installed VSIX host exited ${status}`);
  assert.ok(fs.existsSync(config.hostReceipt), 'Installed VSIX host did not produce a receipt');
  const after = digest(config.vsixPath);
  assert.equal(after, before, 'VSIX bytes changed after installation/test');
  fs.writeFileSync(config.childResult, `${JSON.stringify({ before, after, host: JSON.parse(fs.readFileSync(config.hostReceipt, 'utf8')) }, null, 2)}\n`, 'utf8');
  return 0;
}

function prepare(temporaryRoot, engineRoot, vsixPath) {
  assert.ok(fs.existsSync(vsixPath), `Exact VSIX is missing: ${vsixPath}`);
  if (engineRoot) assert.ok(fs.existsSync(path.join(engineRoot, 'runtime', 'cli.py')), 'PX_ENGINE_ROOT must contain runtime/cli.py');
  const config = {
    workspace: path.join(temporaryRoot, 'workspace'), userData: path.join(temporaryRoot, 'user-data'), extensions: path.join(temporaryRoot, 'extensions'),
    hostReceipt: path.join(temporaryRoot, 'host-receipt.json'), childResult: path.join(temporaryRoot, 'child-result.json'), engineRoot, vsixPath
  };
  for (const directory of [config.workspace, config.userData, config.extensions]) fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(config.workspace, 'listener-matrix.txt'), 'initial\n', 'utf8');
  if (engineRoot) {
    fs.mkdirSync(path.join(config.workspace, '.vscode'), { recursive: true });
    fs.writeFileSync(path.join(config.workspace, '.vscode', 'settings.json'), `${JSON.stringify({
      'pacifyX.engineRoot': engineRoot,
      // Linux distributions commonly expose only python3.  Keep the Windows
      // lane on its native launcher while making the platform receipt explicit.
      'pacifyX.pythonPath': process.platform === 'win32' ? 'python' : 'python3',
      // The headless Linux host has no desktop trash service.  This keeps the
      // WorkspaceEdit delete path (and its will/did file-operation listeners)
      // deterministic inside the disposable owned workspace.
      'files.enableTrash': process.platform === 'win32'
    }, null, 2)}\n`, 'utf8');
  }
  const git = process.platform === 'win32' ? 'git.exe' : 'git';
  childProcess.spawnSync(git, ['init', '--quiet'], { cwd: config.workspace, encoding: 'utf8' });
  childProcess.spawnSync(git, ['config', 'user.email', 'px-installed@example.invalid'], { cwd: config.workspace, encoding: 'utf8' });
  childProcess.spawnSync(git, ['config', 'user.name', 'PX installed certifier'], { cwd: config.workspace, encoding: 'utf8' });
  childProcess.spawnSync(git, ['add', 'listener-matrix.txt'], { cwd: config.workspace, encoding: 'utf8' });
  childProcess.spawnSync(git, ['commit', '--quiet', '-m', 'fixture'], { cwd: config.workspace, encoding: 'utf8' });
  return config;
}

async function main() {
  const configuredEngine = argument('--engine-root') || process.env.PX_ENGINE_ROOT;
  const engineRoot = configuredEngine ? path.resolve(configuredEngine) : null;
  const boundEngineIdentity = engineIdentity(engineRoot);
  const vsixPath = path.resolve(argument('--vsix') || process.env.PX_VSIX_PATH || path.join(extensionRoot, 'dist', `${extensionPackage.name}-${extensionPackage.version}.vsix`));
  const expectedSha256 = String(argument('--expected-sha256') || '').toLowerCase();
  if (expectedSha256) assert.equal(digest(vsixPath), expectedSha256, 'Exact VSIX preflight SHA-256 mismatch');
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'pacify-x-installed-vsix-'));
  markOwnedHostWorkspace(temporaryRoot, 'installed-vsix-smoke');
  const config = prepare(temporaryRoot, engineRoot, vsixPath);
  const configPath = path.join(temporaryRoot, 'host-config.json'); fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
  let lifecycle;
  try {
    const run = await runOwnedHostWorker({
      scriptPath: __filename, childFlag: CHILD_FLAG, configPath, cwd: extensionRoot, timeoutMs: 300_000,
      ownershipToken: config.userData,
      env: {
        ...nonBillableEnvironment(),
        PX_OWNED_VSCODE_HOST: '1',
        // The pinned Linux desktop host is intentionally exercised under WSL
        // with an isolated profile.  Its CLI otherwise prompts interactively
        // before extension installation and makes the governed lane hang.
        ...(process.platform === 'linux' ? { DONT_PROMPT_WSL_INSTALL: '1' } : {})
      }, stdout: process.stdout, stderr: process.stderr,
      onReceipt: value => { lifecycle = value; }
    });
    assert.equal(run.receipt.worker_exit_verified, true, 'Installed VSIX worker process exit was not verified');
    assert.ok(fs.existsSync(config.childResult), 'Installed VSIX worker did not publish its result');
    const child = JSON.parse(fs.readFileSync(config.childResult, 'utf8'));
    const receipt = {
      schema_version: 'px.installed-vsix-certification/1.1',
      platform: process.platform,
      artifact: { name: path.basename(vsixPath), sha256_before: child.before, sha256_after: child.after, unchanged: child.before === child.after },
      vscode_version: vscodeVersion, installation: 'clean-profile-exact-vsix', engine_connected: Boolean(engineRoot),
      engine_identity: boundEngineIdentity,
      process_lifecycle: run.receipt, host: portableHostReceipt(child.host)
    };
    fs.mkdirSync(path.dirname(retainedReceipt), { recursive: true }); fs.writeFileSync(retainedReceipt, `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
    process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
  } finally {
    if (lifecycle) {
      fs.mkdirSync(path.dirname(retainedLifecycleReceipt), { recursive: true });
      fs.writeFileSync(retainedLifecycleReceipt, `${JSON.stringify(lifecycle, null, 2)}\n`, 'utf8');
    }
    if (lifecycle?.process_tree_closed_verified) fs.rmSync(temporaryRoot, { recursive: true, force: true });
    else process.stderr.write(`Retained recoverable installed-host workspace because process-tree closure was not verified: ${temporaryRoot}\n`);
  }
}

if (process.argv[2] === CHILD_FLAG) childMain(process.argv[3]).then(code => { process.exitCode = code; }).catch(error => { process.stderr.write(`${error.stack || error.message}\n`); process.exitCode = 1; });
else if (process.argv.includes('--help')) process.stdout.write('Usage: node scripts/run-installed-vsix-smoke.js --engine-root <path> --vsix <path> [--expected-sha256 <sha256>]\n');
else main().catch(error => { process.stderr.write(`${error.stack || error.message}\n`); process.exitCode = 1; });
