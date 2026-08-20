'use strict';

const assert = require('assert');
const childProcess = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { runTests } = require('@vscode/test-electron');
const { nonBillableEnvironment } = require('../src/contextBridge');
const { runOwnedHostWorker } = require('./owned-host-runner');
const { ensureOwnedVscodeTestCache, markOwnedHostWorkspace } = require('./owned-vscode-test-cache');

const CHILD_FLAG = '--owned-host-child';
const extensionRoot = path.resolve(__dirname, '..');
const retainedReceipt = path.join(extensionRoot, 'evidence', 'vscode-host-listener-smoke.json');
const retainedLifecycleReceipt = path.join(extensionRoot, 'evidence', 'vscode-host-process-lifecycle.json');
const vscodeVersion = '1.132.1';

async function childMain(configPath) {
  const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  const cache = ensureOwnedVscodeTestCache(vscodeVersion);
  delete process.env.ELECTRON_RUN_AS_NODE;
  return runTests({
    extensionDevelopmentPath: extensionRoot,
    extensionTestsPath: path.join(extensionRoot, 'tests', 'vscode-host', 'index.js'),
    extensionTestsEnv: { PX_VSCODE_SMOKE_RECEIPT: config.receipt, PX_EXPECT_CANONICAL_BUS: config.engineRoot ? '1' : '0' },
    version: vscodeVersion,
    cachePath: cache.root,
    launchArgs: [config.workspace, `--user-data-dir=${config.userData}`, `--extensions-dir=${config.extensions}`, '--disable-updates', '--disable-workspace-trust', '--skip-welcome', '--skip-release-notes']
  });
}

function prepare(temporaryRoot, engineRoot) {
  const config = {
    workspace: path.join(temporaryRoot, 'workspace'), userData: path.join(temporaryRoot, 'user-data'),
    extensions: path.join(temporaryRoot, 'extensions'), receipt: path.join(temporaryRoot, 'receipt.json'), engineRoot
  };
  for (const directory of [config.workspace, config.userData, config.extensions]) fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(path.join(config.workspace, 'listener-matrix.txt'), 'initial\n', 'utf8');
  if (engineRoot) {
    assert.ok(fs.existsSync(path.join(engineRoot, 'runtime', 'cli.py')), 'PX_ENGINE_ROOT must contain runtime/cli.py');
    fs.mkdirSync(path.join(config.workspace, '.vscode'), { recursive: true });
    fs.writeFileSync(path.join(config.workspace, '.vscode', 'settings.json'), `${JSON.stringify({ 'pacifyX.engineRoot': engineRoot }, null, 2)}\n`, 'utf8');
  }
  childProcess.spawnSync('git.exe', ['init', '--quiet'], { cwd: config.workspace, encoding: 'utf8' });
  childProcess.spawnSync('git.exe', ['config', 'user.email', 'px-o04@example.invalid'], { cwd: config.workspace, encoding: 'utf8' });
  childProcess.spawnSync('git.exe', ['config', 'user.name', 'PX O04 Smoke'], { cwd: config.workspace, encoding: 'utf8' });
  childProcess.spawnSync('git.exe', ['add', 'listener-matrix.txt'], { cwd: config.workspace, encoding: 'utf8' });
  childProcess.spawnSync('git.exe', ['commit', '--quiet', '-m', 'fixture'], { cwd: config.workspace, encoding: 'utf8' });
  return config;
}

async function main() {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'pacify-x-o04-vscode-'));
  markOwnedHostWorkspace(temporaryRoot, 'development-host-smoke');
  const engineRoot = process.env.PX_ENGINE_ROOT ? path.resolve(process.env.PX_ENGINE_ROOT) : null;
  const config = prepare(temporaryRoot, engineRoot);
  const configPath = path.join(temporaryRoot, 'host-config.json');
  fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`, 'utf8');
  let lifecycle;
  try {
    const run = await runOwnedHostWorker({
      scriptPath: __filename, childFlag: CHILD_FLAG, configPath, cwd: extensionRoot, timeoutMs: 180_000,
      ownershipToken: config.userData,
      env: { ...nonBillableEnvironment(), PX_OWNED_VSCODE_HOST: '1' }, stdout: process.stdout, stderr: process.stderr,
      onReceipt: value => { lifecycle = value; }
    });
    assert.equal(run.receipt.worker_exit_verified, true, 'VS Code worker process exit was not verified');
    assert.ok(fs.existsSync(config.receipt), 'VS Code host did not write its listener receipt.');
    const parsed = JSON.parse(fs.readFileSync(config.receipt, 'utf8'));
    parsed.process_lifecycle = run.receipt;
    fs.mkdirSync(path.dirname(retainedReceipt), { recursive: true });
    fs.writeFileSync(retainedReceipt, `${JSON.stringify(parsed, null, 2)}\n`, 'utf8');
    process.stdout.write(`${JSON.stringify(parsed, null, 2)}\n`);
  } finally {
    if (lifecycle) {
      fs.mkdirSync(path.dirname(retainedLifecycleReceipt), { recursive: true });
      fs.writeFileSync(retainedLifecycleReceipt, `${JSON.stringify(lifecycle, null, 2)}\n`, 'utf8');
    }
    if (lifecycle?.process_tree_closed_verified) fs.rmSync(temporaryRoot, { recursive: true, force: true });
    else process.stderr.write(`Retained recoverable host workspace because process-tree closure was not verified: ${temporaryRoot}\n`);
  }
}

if (process.argv[2] === CHILD_FLAG) childMain(process.argv[3]).then(code => { process.exitCode = code; }).catch(error => { process.stderr.write(`${error.stack || error.message}\n`); process.exitCode = 1; });
else main().catch(error => { process.stderr.write(`${error.stack || error.message}\n`); process.exitCode = 1; });
