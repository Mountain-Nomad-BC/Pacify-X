'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));

test('all package commands are registered in the extension host', () => {
  const extension = fs.readFileSync(path.join(root, 'src', 'extension.js'), 'utf8');
  for (const item of pkg.contributes.commands) assert.match(extension, new RegExp(item.command.replaceAll('.', '\\.')));
});

test('MCP build dependencies are pinned and the shipped server is bundled', () => {
  assert.equal(pkg.dependencies['@modelcontextprotocol/server'], '2.0.0');
  assert.equal(pkg.dependencies.zod, '4.4.3');
  assert.equal(pkg.devDependencies.esbuild, '0.28.2');
  assert.equal(fs.existsSync(path.join(root, 'server', 'index.js')), true);
  assert.match(pkg.scripts.package, /scripts\/package-vsix\.js/);
  const packager = fs.readFileSync(path.join(root, 'scripts', 'package-vsix.js'), 'utf8');
  assert.match(packager, /main: '\.\/src\/extension\.bundle\.js'/);
  assert.match(packager, /bundle: true/);
  assert.match(packager, /external: \['vscode'\]/);
  assert.match(packager, /Refusing to overwrite issued extension version/);
  assert.match(packager, /release-artifacts.*vscode/);
  const installedRunner = fs.readFileSync(path.join(root, 'scripts', 'run-installed-vsix-smoke.js'), 'utf8');
  assert.match(installedRunner, /--expected-sha256/);
  assert.match(installedRunner, /Exact VSIX preflight SHA-256 mismatch/);
  assert.match(installedRunner, /ensureOwnedVscodeTestCache/);
  assert.match(installedRunner, /cachePath: cache\.root/);
  const hostRunner = fs.readFileSync(path.join(root, 'scripts', 'run-vscode-host-smoke.js'), 'utf8');
  assert.match(hostRunner, /ensureOwnedVscodeTestCache/);
  assert.match(hostRunner, /version: vscodeVersion/);
  assert.match(hostRunner, /process\.platform === 'win32' \? 'git\.exe' : 'git'/);
  const cacheOwner = fs.readFileSync(path.join(root, 'scripts', 'owned-vscode-test-cache.js'), 'utf8');
  assert.match(cacheOwner, /px\.owned-vscode-test-cache\/1\.0/);
  assert.match(cacheOwner, /retained_versions/);
});

test('owned operational host isolates unrelated AI and GitHub services', () => {
  const runner = fs.readFileSync(path.join(root, 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(runner, /'chat\.disableAIFeatures': true/);
  for (const extensionId of ['github.copilot', 'github.copilot-chat', 'github.vscode-pull-request-github', 'vscode.github-authentication', 'vscode.microsoft-authentication']) {
    assert.ok(runner.includes(`'--disable-extension', '${extensionId}'`), extensionId);
  }
  assert.match(runner, /`--extensions-dir=\$\{config\.extensions\}`/);
  assert.match(runner, /'--install-extension', config\.vsixPath, '--force'/);
  assert.match(runner, /exact-vsix-preinstall-sha256-mismatch/);
  assert.match(runner, /exact-vsix-bytes-changed-during-install/);
  assert.match(runner, /unchanged_after_install: true/);
  assert.match(runner, /PX_OWNED_VSCODE_HOST_CONFIRM_REVERSIBLE_WRITES: '1'/);
});

test('control center contribution and implementation agree on a demand-activated webview', () => {
  const view = pkg.contributes.views.pacifyX.find(item => item.id === 'pacifyX.controlCenter');
  const extension = fs.readFileSync(path.join(root, 'src', 'extension.js'), 'utf8');
  assert.ok(view, 'pacifyX.controlCenter must be contributed');
  assert.equal(view.type, 'webview');
  assert.ok(pkg.activationEvents.includes('onView:pacifyX.controlCenter'));
  assert.equal(pkg.activationEvents.includes('onStartupFinished'), false);
  assert.match(extension, /registerWebviewViewProvider\('pacifyX\.controlCenter', sidebar/);
});

test('all referenced local media assets exist', () => {
  for (const file of ['dashboard.css', 'px-activity.svg', 'px-shield-32.png', 'px-shield-128.png', 'px-shield-256.png', 'px-shield-mark-tight.png']) assert.equal(fs.existsSync(path.join(root, 'media', file)), true, file);
  assert.equal(fs.existsSync(path.join(root, 'media', 'dashboard', '90-controller.js')), true, 'dashboard/90-controller.js');
  for (const file of ['00-foundation.js', '10-state.js', '20-bridge.js', '30-components.js', '40-surfaces.js', '45-system-surfaces.js']) assert.equal(fs.existsSync(path.join(root, 'media', 'dashboard', file)), true, file);
  for (const file of ['00-layer-order.css', '01-tokens.css', '10-primitives.css', '20-layout.css', '30-components.css', '40-surfaces.css', '50-responsive.css', '60-accessibility.css']) assert.equal(fs.existsSync(path.join(root, 'media', 'styles', file)), true, file);
});

test('parallel coordination skill and orchestration are packaged sources', () => {
  assert.equal(fs.existsSync(path.join(root, 'resources', 'skills', 'parallel-planning-coordination', 'SKILL.md')), true);
  const orchestration = JSON.parse(fs.readFileSync(path.join(root, 'resources', 'orchestrations', 'parallel-planning.json'), 'utf8'));
  assert.equal(orchestration.id, 'parallel-planning-coordination');
  assert.equal(orchestration.billable_services, false);
  assert.equal(orchestration.steps.at(-1).action, 'update_layered_memory_and_resume_state');
});

test('sort picker and Team Fabric integration resources are packaged', () => {
  for (const skill of ['data-sort-dry-run-picker', 'px-lean-engineering', 'px-work-stop-diagnostics']) {
    assert.equal(fs.existsSync(path.join(root, 'resources', 'skills', skill, 'SKILL.md')), true, skill);
  }
  assert.equal(JSON.parse(fs.readFileSync(path.join(root, 'resources', 'orchestrations', 'data-sort-dry-run-selection.json'), 'utf8')).writes_sorted_data, false);
  assert.equal(JSON.parse(fs.readFileSync(path.join(root, 'resources', 'team-fabric', 'capability-manifest.json'), 'utf8')).billable_api_required, false);
  assert.equal(fs.existsSync(path.join(root, 'docs', 'TEAM_FABRIC_INTEGRATION.md')), true);
});

test('MS+Enterprise boundary and second-pass evidence are packaged', () => {
  const boundary = JSON.parse(fs.readFileSync(path.join(root, 'resources', 'enterprise', 'boundary-contract.json'), 'utf8'));
  assert.equal(boundary.project_state_schema, 'px.ms-enterprise.state/1.0');
  assert.equal(boundary.defaults.billable_services, 'disabled');
  assert.equal(boundary.cloud_connection_implemented, false);
  assert.equal(fs.existsSync(path.join(root, 'docs', 'MS_ENTERPRISE_SECOND_PASS_PUNCH_CARD.md')), true);
  assert.equal(fs.existsSync(path.join(root, 'docs', 'MS_ENTERPRISE_OPERATOR_GUIDE.md')), true);
  const guardrails = JSON.parse(fs.readFileSync(path.join(root, 'resources', 'enterprise', 'execution-guardrails.json'), 'utf8'));
  assert.equal(guardrails.master_enabled, false);
  assert.equal(guardrails.invariants.master_switch_authorizes_execution, false);
});

test('environment ontology and lazy-shard contract are packaged', () => {
  const ontology = JSON.parse(fs.readFileSync(path.join(root, 'resources', 'environment', 'ontology.json'), 'utf8'));
  assert.deepEqual(ontology.canonical_chain, ['resource', 'capabilities', 'interface', 'requirements', 'effects', 'conflicts', 'policy', 'state']);
  assert.equal(ontology.lazy_storage.per_extension_contracts, true);
  assert.ok(ontology.forbidden_effects.includes('activate arbitrary extensions'));
});

test('installer derives the current version and verifies the generated hash manifest', () => {
  const installer = fs.readFileSync(path.join(root, 'Install-PacifyX.ps1'), 'utf8');
  assert.match(installer, /package\.version/);
  assert.match(installer, /SHA256SUMS\.txt/);
  assert.match(installer, /--list-extensions --show-versions/);
  assert.match(installer, /Refusing same-version replacement/);
  assert.match(installer, /Developer: Reload Window/);
  assert.doesNotMatch(installer, /0\.2\.0|0\.3\.1/);
});
