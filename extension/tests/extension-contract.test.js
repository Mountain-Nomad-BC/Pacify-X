'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const bridge = require('../src/runtimeBridge');
const { normalizeSnapshot } = require('../src/pxBridge');
const { buildContextEnvelope } = require('../src/contextBridge');

const root = path.resolve(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const dashboard = fs.readFileSync(path.join(root, 'media', 'dashboard', '90-controller.js'), 'utf8');
const coreSurfaces = fs.readFileSync(path.join(root, 'media', 'dashboard', '42-core-surfaces.js'), 'utf8');
const catalogSurfaces = fs.readFileSync(path.join(root, 'media', 'dashboard', '43-catalog-surfaces.js'), 'utf8');
const operationalSurfaces = fs.readFileSync(path.join(root, 'media', 'dashboard', '44-operational-surfaces.js'), 'utf8');
const systemSurfaces = fs.readFileSync(path.join(root, 'media', 'dashboard', '45-system-surfaces.js'), 'utf8');
const observabilitySurfaces = fs.readFileSync(path.join(root, 'media', 'dashboard', '46-observability-surfaces.js'), 'utf8');
const graphSurface = fs.readFileSync(path.join(root, 'media', 'dashboard', '48-graph-surface.js'), 'utf8');
const css = fs.readFileSync(path.join(root, 'media', 'dashboard.css'), 'utf8');
const extension = fs.readFileSync(path.join(root, 'src', 'extension.js'), 'utf8');
const sidebarView = fs.readFileSync(path.join(root, 'src', 'sidebarView.js'), 'utf8');
const activityObservability = fs.readFileSync(path.join(root, 'src', 'activityObservability.js'), 'utf8');
const runtimeBridge = fs.readFileSync(path.join(root, 'src', 'runtimeBridge.js'), 'utf8');
const pxBridge = fs.readFileSync(path.join(root, 'src', 'pxBridge.js'), 'utf8');
const extensionLifecycleHost = fs.readFileSync(path.join(root, 'src', 'extensionLifecycleHost.js'), 'utf8');
const extensionConflictAnalyzer = fs.readFileSync(path.join(root, 'src', 'extensionConflictAnalyzer.js'), 'utf8');

test('admitted host tools reach the live interface, policy, target, budget, and receipt gates', () => {
  assert.doesNotMatch(extension, /Direct VS Code host tools are refused until/);
  assert.match(extension, /attestHostToolInterface/);
  assert.match(extension, /host_tool_interface_sha256/);
  assert.match(extension, /enforceAdmittedHostToolPolicy\(admitted, call\.input\)/);
  assert.match(extension, /toolCalls \+ calls\.length > 8/);
  assert.match(extension, /vscode\.lm\.invokeTool/);
});

test('dashboard restart restoration and predecessor-bound draft recovery have live owners', () => {
  assert.match(extension, /registerWebviewPanelSerializer\('pacifyX\.dashboard'/);
  assert.match(extension, /openDashboard\('\/control-plane', null, restoredPanel\)/);
  assert.match(dashboard, /function workingStudioOverlayDisposition\(/);
  assert.match(dashboard, /function openReauthenticatedStudioDraft\(/);
  assert.match(dashboard, /RETAINED OVERLAY RESTORED/);
  assert.match(dashboard, /RETAINED OVERLAY NOT APPLIED/);
  assert.doesNotMatch(dashboard, /studioPendingSkillPackage = null; closeModal\(true\); openStudioDraftModal\(kind, seed\)/);
});

test('preserved-original skill provenance is host-attested and allocation-bound', () => {
  assert.match(extension, /const declaredBackup = String\(details\.backup/);
  assert.match(extension, /readSkillPackage\(bridge\(\)\.engineRoot, declaredBackup, \{ scope: 'engine' \}\)/);
  assert.match(extension, /backup_provenance: backupProvenance/);
  assert.match(extension, /registerVersionAllocation\(message\.kind, result,[\s\S]*allocationSourceSelection\)/);
  assert.match(extension, /resolveVersionAllocationSourceSelection/);
  assert.match(extension, /reauthenticatePreservedOriginalSelection/);
  assert.match(extension, /studio-skill-preserved-original-changed/);
  assert.doesNotMatch(extension, /backup_provenance: null/);
});

test('declares exactly sixteen primary and two governed advanced dashboard surfaces', () => {
  const visible = dashboard.match(/const visibleSurfaces = \[([\s\S]*?)\];/)?.[1].match(/\['/g) || [];
  const advanced = dashboard.match(/const advancedSurfaces = \[([\s\S]*?)\];/)?.[1].match(/\['/g) || [];
  assert.equal(visible.length, 16);
  assert.equal(advanced.length, 2);
  assert.equal(pkg.contributes.configuration.properties['pacifyX.showAdvancedSurfaces'].default, true);
  assert.match(dashboard, /advancedVisible && state\.advancedOpen/);
});

test('0.6.25 surfaces operational Studio setup, interactive graphs, JSON inspectors, telemetry, plugins, memory and activity observability, readiness, agent models, and the complete logo', () => {
  const surfaceStyles = fs.readFileSync(path.join(root, 'media', 'styles', '40-surfaces.css'), 'utf8');
  assert.equal(pkg.version, '0.6.25');
  assert.ok(pkg.activationEvents.includes('onCommand:pacifyX.setupStudio'));
  assert.ok(pkg.activationEvents.includes('onUri'));
  assert.ok(pkg.contributes.commands.some(item => item.command === 'pacifyX.setupStudio'));
  assert.match(extension, /setupStudio\(bridge\(\)/);
  assert.match(dashboard, /studioSetupResult/);
  assert.match(operationalSurfaces, /agents_runnable_revisions/);
  assert.match(extension, /px-shield-128\.png/);
  assert.doesNotMatch(extension, /px-shield-mark-tight\.png/);
  assert.match(dashboard, /Human readable[\s\S]*Machine readable/);
  assert.match(dashboard, /exportRecordJson/);
  assert.match(dashboard, /graphQuery/);
  assert.match(dashboard, /graphRendered/);
  assert.match(dashboard, /parts\.indexOf\('control-plane'\)/);
  assert.match(dashboard, /exceeded its 12-second bound/);
  assert.match(graphSurface, /relationship-inspector/);
  assert.match(graphSurface, /Selected record and readable relationships/);
  for (const token of ['graphZoomIn', 'graphZoomOut', 'graphFit', 'graphReset', 'graphToggleInspector', 'graphLayout', 'pointerdown', 'pointermove']) assert.match(dashboard, new RegExp(token));
  assert.match(graphSurface, /Ctrl\+wheel or/);
  assert.match(`${coreSurfaces}\n${fs.readFileSync(path.join(root, 'media', 'dashboard', '47-advanced-surfaces.js'), 'utf8')}`, /Thermals & sensors/);
  assert.match(operationalSurfaces, /Governed plugin lifecycle/);
  assert.match(systemSurfaces, /Agent readiness matrix/);
  assert.match(dashboard, /agentModelHuman/);
  assert.match(operationalSurfaces, /Capability catalog contract/);
  assert.match(css, /\.control-rail \.brand-mark/);
  assert.match(css, /\.graph-workspace/);
  assert.match(surfaceStyles, /touch-action: none/);
  assert.match(css, /\.graph-minimap/);
  assert.match(surfaceStyles, /\.sensor-row/);
  assert.match(surfaceStyles, /\.plugin-row/);
  assert.match(surfaceStyles, /\.readiness-row/);
  assert.match(css, /\.agent-model/);
  assert.match(observabilitySurfaces, /Canonical memory vault/);
  assert.match(observabilitySurfaces, /Canonical record browser/);
  assert.match(observabilitySurfaces, /configureCanonicalMemory/);
  assert.match(css, /\.memory-record/);
  assert.match(observabilitySurfaces, /METADATA-ONLY OBSERVABILITY/);
  assert.match(observabilitySurfaces, /inspectActivityEvent/);
  assert.match(css, /\.activity-event/);
  const observabilityWiring = `${extension}\n${activityObservability}`;
  for (const token of ['onDidChangeTextDocument', 'createFileSystemWatcher', 'onDidOpenTerminal', 'onDidStartTask', 'onDidStartDebugSession', 'recordActivity']) assert.match(observabilityWiring, new RegExp(token));
});

test('webview uses local CSP, vertical navigation, focus containment, and reduced motion', () => {
  assert.match(extension, /default-src 'none'/);
  assert.match(sidebarView, /default-src 'none'/);
  assert.doesNotMatch(`${extension}\n${sidebarView}`, /'unsafe-inline'|'unsafe-eval'/);
  assert.match(extension, /style-src \$\{webview\.cspSource\}; script-src 'nonce-\$\{nonce\}'/);
  assert.match(sidebarView, /style-src \$\{webview\.cspSource\}; script-src 'nonce-\$\{nonce\}'/);
  assert.match(extension, /switch \(message\?\.type\)/);
  assert.match(dashboard, /class="control-rail"/);
  assert.match(dashboard, /event\.key === 'Tab'/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(extension, /retainContextWhenHidden: false/);
});

test('dynamic dashboard geometry uses one bounded CSSOM applicator without inline style attributes', () => {
  const layoutSources = `${dashboard}\n${graphSurface}\n${systemSurfaces}`;
  assert.doesNotMatch(layoutSources, /\sstyle\s*=/i);
  assert.doesNotMatch(dashboard, /\b(?:app|canvas|scene)\.style\b/);
  assert.match(dashboard, /BOUNDED_LAYOUT_LIMIT = 2048/);
  assert.match(dashboard, /new CSSStyleSheet\(\)/);
  assert.match(dashboard, /document\.adoptedStyleSheets/);
  assert.match(dashboard, /globalThis\.PXDashboard\.define\('boundedLayout', boundedLayout\)/);
  assert.match(dashboard, /boundedLayout\.apply\(document\)/);
  for (const attribute of ['data-workflow-x', 'data-workflow-scale', 'data-graph-x', 'data-graph-scene', 'data-readiness-score', 'data-glass-opacity']) assert.match(layoutSources, new RegExp(attribute));
  for (const bound of ['Number.isFinite', '-20000, 20000', '320, 20000', '.08, 2.8', '0, 5']) assert.match(layoutSources, new RegExp(bound.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
});

test('startup and visible refresh remain bounded and hidden views suspend polling', () => {
  const refresh = pkg.contributes.configuration.properties['pacifyX.refreshIntervalSeconds'];
  assert.equal(refresh.default, 300);
  assert.equal(refresh.minimum, 60);
  assert.match(extension, /registration-only-until-visible-or-commanded/);
  assert.match(extension, /subprocesses_started: 0, discovery_started: false, project_writes: 0/);
  assert.match(extension, /if \(!panel\?\.visible && !sidebar\.hasVisibleView\(\)\) return/);
  assert.match(extension, /persist: false/);
  assert.match(extension, /pool: 'cpuWorkers'/);
  assert.match(extension, /pool: 'validation'/);
  assert.match(extension, /pool: 'providerIo'/);
});

test('canonical Pacify-X API owns normalization and detailed catalogs are lazy and paged', () => {
  assert.match(pxBridge, /runtime\.dashboard_api/);
  assert.match(pxBridge, /async catalog\(input\)/);
  assert.match(dashboard, /data-catalog-search/);
  assert.match(dashboard, /catalogPrevious/);
  assert.match(dashboard, /catalogNext/);
  assert.match(dashboard, /inspectCatalogItem/);
  assert.doesNotMatch(runtimeBridge, /readFileSync|safeJson|extractNamed|registryRecord/);
  assert.doesNotMatch(dashboard, /DISCOVERED SAMPLE/);
});

test('MS+Enterprise skills, agents, workflows, connectors, models, and state remain separated', () => {
  for (const kind of ['enterprise-skills', 'enterprise-agents', 'enterprise-workflows', 'enterprise-integrations', 'enterprise-models']) {
    assert.match(pxBridge, new RegExp(kind));
  }
  assert.match(catalogSurfaces, /PX Native[\s\S]*Preserved Originals[\s\S]*Microsoft \/ Vendor[\s\S]*Enterprise Restricted/);
  assert.match(catalogSurfaces, /REGISTERED RECORDS[\s\S]*MS\+Enterprise/);
  assert.match(operationalSurfaces, /Local \+ Team Fabric[\s\S]*MS\+Enterprise/);
  assert.match(dashboard, /SEPARATE PROJECT STATE · CONNECTORS STAY OFF/);
  assert.match(extension, /enterprisePackToggle/);
  assert.match(extension, /does not connect to Microsoft/);
  assert.match(extension, /billable services/);
});

test('billable policy defaults deny and exposes every configurable guardrail', () => {
  const properties = pkg.contributes.configuration.properties;
  assert.equal(properties['pacifyX.billable.enabled'].default, false);
  assert.equal(properties['pacifyX.guardrails.maxCostPerTaskUsd'].default, 0);
  assert.equal(properties['pacifyX.guardrails.maxCostPerSessionUsd'].default, 0);
  assert.equal(properties['pacifyX.guardrails.maxCostPerDayUsd'].default, 0);
  assert.equal(properties['pacifyX.guardrails.localFirst'].default, true);
  assert.deepEqual(properties['pacifyX.guardrails.providerAllowlist'].default, []);
  assert.equal(properties['pacifyX.guardrails.requireApprovalBeforeBillableExecution'].default, true);
  for (const token of ['gpuMemoryCeilingMb', 'cpuCoreCeiling', 'ramCeilingMb', 'escalationConfidenceThreshold', 'cacheReuseAggressiveness']) assert.ok(Object.keys(properties).some(key => key.endsWith(token)), token);
  assert.match(systemSurfaces, /role="switch"/);
  assert.match(extension, /Enable guarded policy/);
});

test('U02 system surfaces have one renderer owner outside the legacy compatibility renderer', () => {
  for (const name of ['diagnostics', 'assurance', 'settings']) {
    assert.doesNotMatch(dashboard, new RegExp(`function ${name}\\(`));
    assert.match(systemSurfaces, new RegExp(`function ${name}\\(`));
  }
  for (const helper of ['card', 'section', 'empty']) assert.doesNotMatch(dashboard, new RegExp(`function ${helper}\\(`));
  assert.match(dashboard, /systemSurfaces\.render\(id/);
});

test('environment map is compact, lazy, semantic, and never activates arbitrary extensions', () => {
  const discovery = fs.readFileSync(path.join(root, 'src', 'discoveryManager.js'), 'utf8');
  assert.match(operationalSurfaces, /Environment Map/);
  assert.match(dashboard, /environmentQuery/);
  assert.match(dashboard, /RESOURCE → CAPABILITIES → INTERFACE → REQUIREMENTS → EFFECTS → CONFLICTS → POLICY → STATE/);
  assert.match(discovery, /compact-index-with-hash-verified-lazy-shards/);
  assert.match(discovery, /per_extension_contracts/);
  assert.match(discovery, /activation_attempted: false/);
  assert.match(discovery, /expected_inputs/);
  assert.match(discovery, /known_conflicts/);
  assert.doesNotMatch(discovery, /extensions\.getExtension\([^)]*\)\.activate/);
});

test('extension installation has an exact governed request, native approval, dispatch, and reconciliation path', () => {
  assert.match(operationalSurfaces, /Install exact extension/);
  assert.match(operationalSurfaces, /data-action="previewExtensionInstall"/);
  assert.match(dashboard, /extensionLifecyclePreview/);
  assert.match(dashboard, /extensionLifecycleExecute/);
  assert.match(dashboard, /message\.requestId !== request\.requestId/);
  assert.match(extension, /case 'extensionLifecyclePreview'/);
  assert.match(extension, /case 'extensionLifecycleExecute'/);
  assert.match(extension, /showWarningMessage[\s\S]*modal: true[\s\S]*Authorize native install/);
  assert.match(extensionLifecycleHost, /workbench\.extensions\.installExtension/);
  assert.match(extensionLifecycleHost, /extension-lifecycle-install-denominator-changed/);
  assert.match(extensionLifecycleHost, /pending-host-reload-or-refresh/);
  assert.doesNotMatch(operationalSurfaces, /<b>Install \+ update<\/b>[\s\S]*data-action="openExtensionsView"/);
});

test('extension update is distinct, rollback-identified, compatibility-honest, and persistently reconciled', () => {
  assert.match(operationalSurfaces, /Update installed extension/);
  assert.match(operationalSurfaces, /data-action="previewExtensionUpdate"/);
  assert.match(dashboard, /extensionUpdatePreview/);
  assert.match(dashboard, /extensionUpdateExecute/);
  assert.match(extension, /case 'extensionUpdatePreview'/);
  assert.match(extension, /case 'extensionUpdateExecute'/);
  assert.match(extension, /extension-lifecycle-update[\s\S]*'approved'/);
  assert.match(extension, /persistence-escalation/);
  assert.match(extensionLifecycleHost, /rollback_target/);
  assert.match(extensionLifecycleHost, /VS Code enforces target engine compatibility/);
  assert.match(extensionLifecycleHost, /extension-lifecycle-update-denominator-changed/);
});

test('extension enablement uses exact scoped native handoff and never conflates activation with enablement', () => {
  assert.match(operationalSurfaces, /NATIVE MANAGER BOUNDARY/);
  assert.match(operationalSurfaces, /data-action="previewExtensionEnablement"/);
  assert.match(dashboard, /extensionEnablementPreview/);
  assert.match(dashboard, /extensionEnablementObserved/);
  assert.match(extension, /case 'extensionEnablementExecute'/);
  assert.match(extension, /temporal-pending-handoff-only/);
  assert.match(extensionLifecycleHost, /workbench\.extensions\.search/);
  assert.match(extensionLifecycleHost, /enablement_observed: null/);
  assert.match(extensionLifecycleHost, /mutation_dispatched: false/);
});

test('extension uninstall discloses consumers, retains rollback identity before dispatch, and reconciles absence', () => {
  assert.match(operationalSurfaces, /Uninstall exact extension/);
  assert.match(operationalSurfaces, /data-action="previewExtensionUninstall"/);
  assert.match(dashboard, /extensionUninstallPreview/);
  assert.match(dashboard, /extension-uninstall-consumers/);
  assert.match(extension, /case 'extensionUninstallExecute'/);
  assert.match(extension, /extension-lifecycle-uninstall[\s\S]*'approved'/);
  assert.match(extensionLifecycleHost, /retained-before-uninstall/);
  assert.match(extensionLifecycleHost, /workbench\.extensions\.uninstallExtension/);
  assert.match(extensionLifecycleHost, /installed directory is not treated as a signed package artifact/);
});

test('extension rollback consumes retained identity only after exact-version host observation', () => {
  assert.match(operationalSurfaces, /Rollback retained uninstall/);
  assert.match(operationalSurfaces, /data-action="previewExtensionRollback"/);
  assert.match(dashboard, /extensionRollbackPreview/);
  assert.match(dashboard, /extensionRollbackResult/);
  assert.match(extension, /case 'extensionRollbackExecute'/);
  assert.match(extension, /extension-lifecycle-rollback[\s\S]*'approved'/);
  assert.match(extensionLifecycleHost, /rollback-consumed/);
  assert.match(extensionLifecycleHost, /verified-by-host-exact-version-observation/);
  assert.match(extensionLifecycleHost, /rollback-custody-stale/);
});

test('extension conflicts have live typed drilldown and route mutations through proven lifecycle previews', () => {
  assert.match(operationalSurfaces, /Conflict analysis \+ governed resolution/);
  assert.match(operationalSurfaces, /data-action="queryExtensionConflicts"/);
  assert.match(dashboard, /extensionConflictResolutionPreview/);
  assert.match(dashboard, /routed-to-governed-install/);
  assert.match(dashboard, /routed-to-governed-uninstall/);
  assert.match(dashboard, /routed-to-governed-enablement/);
  assert.match(extension, /case 'extensionConflictResolutionExecute'/);
  assert.match(extensionLifecycleHost, /extension-conflict-signal-missing-or-stale/);
  for (const token of ['duplicate-command-provider', 'overlapping-keybinding', 'missing-extension-dependency', 'language-provider-overlap', 'reverse-extension-dependency']) assert.match(extensionConflictAnalyzer, new RegExp(token));
});

test('coordination and memory actions use typed host messages and project-owned state', () => {
  for (const message of ['createParallelPlan', 'claimCoordinationTask', 'recordTaskProgress', 'reconcileCoordinationTask', 'releaseCoordinationTask', 'captureCoordinationMemory']) {
    assert.match(extension, new RegExp(`case '${message}'`));
  }
  assert.match(observabilitySurfaces, /Portable project coordination memory; not canonical|Portable project records below are not substituted for canonical memory/);
  assert.match(extension, /case 'memoryQuery'/);
  assert.match(catalogSurfaces, /Task graph[\s\S]*Claims[\s\S]*Dispatch[\s\S]*Receipts[\s\S]*Memory/);
  assert.match(extension, /hasWorkspaceClaim: Boolean\(ownedTask\)/);
  assert.match(extension, /current Codex host remains the only executor/);
});

test('destructive cleanup remains confirm-gated, hash-revalidated, and receipted', () => {
  assert.match(dashboard, /Hash gate ×2/);
  assert.match(extension, /showWarningMessage[\s\S]*modal: true/);
  assert.match(extension, /case 'executeCleanup'/);
  assert.doesNotMatch(dashboard, /postMessage\(\{ type: ['"]delete/);
});

test('provider context and billing identities remain separate and unguessed', async () => {
  const envelope = await buildContextEnvelope({
    objective: 'test', workspaceRoot: undefined, openFiles: [], contextCapTokens: 12000,
    authenticationIdentity: 'test-auth', sourceSurface: 'test-host', sourceSessionId: 'test-session'
  });
  assert.equal(envelope.source.surface, 'test-host');
  assert.equal(envelope.target.authentication_identity, 'test-auth');
  assert.equal(envelope.target.billing_identity, null);
  assert.equal(envelope.target.billable_api_credentials_allowed, false);
  assert.equal(envelope.context.credentials_included, false);
});

test('canonical snapshot normalization preserves complete catalog cardinalities', () => {
  const normalized = normalizeSnapshot({
    schema_version: '2.0.0', generated_at: '2026-01-01T00:00:00Z', connected: true, mode: 'canonical-dashboard-api',
    source: { root: 'C:/px', version: '1', commit: 'abc' }, project: { name: 'px', branch: 'main' },
    counts: { skills: 169, tools: 11, agents: 270, project_orchestrations: 17, skill_orchestrations: 31, execution_bindings: 21, orchestrations_total: 69, workflow_definitions: 48 },
    attention: [], runtime: {}, memory: {}, coordination: {}, readiness: { assessment: 'structural-agent-readiness', dimensions: [] }
  });
  assert.equal(normalized.counts.skills, 169);
  assert.equal(normalized.counts.agents, 270);
  assert.equal(normalized.counts.workflows, 48);
  assert.equal(normalized.counts.workflowArtifacts, 69);
  assert.equal(normalized.readiness.assessment, 'structural-agent-readiness');
  assert.equal(normalized.catalogSource, 'runtime.dashboard_api');
});

test('path boundary rejects sibling-prefix and traversal escapes', () => {
  const base = path.resolve('C:/admitted/root');
  assert.equal(bridge.isPathWithin(path.join(base, 'docs', 'a.md'), [base]), true);
  assert.equal(bridge.isPathWithin(path.resolve(base, '..', 'root-evil', 'a.md'), [base]), false);
  assert.equal(bridge.isPathWithin(path.resolve(base, '..', 'secret.txt'), [base]), false);
});

test('real-path admission rejects a parent alias that escapes an admitted root', t => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'px-open-file-'));
  t.after(() => fs.rmSync(fixture, { recursive: true, force: true }));
  const admitted = path.join(fixture, 'admitted');
  const outside = path.join(fixture, 'outside');
  fs.mkdirSync(admitted); fs.mkdirSync(outside);
  fs.writeFileSync(path.join(admitted, 'good.txt'), 'good');
  fs.writeFileSync(path.join(outside, 'secret.txt'), 'secret');
  const guard = bridge.resolveAdmittedFile(path.join(admitted, 'good.txt'), [admitted]);
  assert.equal(bridge.revalidateAdmittedFile(guard).real, fs.realpathSync.native(path.join(admitted, 'good.txt')));
  const alias = path.join(admitted, 'alias');
  try {
    fs.symlinkSync(outside, alias, process.platform === 'win32' ? 'junction' : 'dir');
    assert.throws(() => bridge.resolveAdmittedFile(path.join(alias, 'secret.txt'), [admitted]), /alias-rejected|escaped-root/);
  } catch (error) {
    if (!/privilege|permitted|alias-rejected|escaped-root/i.test(error.message)) throw error;
  }
});
