'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { advanceInstalledSurfaceControlSettlement, applyInstalledProbeObservations, catalogPaginationControlProbe, cleanupControlProbe, clickWhenKnowledgeControlReady, commandPaletteAttemptDecision, coordinationMemoryControlProbe, eligibleInstalledControl, eligibleInstalledSidebarControl, engineOutageRecord, enterpriseControlProbe, environmentLifecycleControlProbe, exactPluginConflictSignal, graphProjectionIdentity, requestBoundGraphResultIdentity, hostBoundaryControlProbe, inlineCommandOwnerControlProbe, installedActionIdentity, installedConditionalRecoverySpec, installedConditionalScenario, installedFilesystemPathIdentity, installedFilesystemPathsMatch, installedFilesystemPathWithin, installedHostActionReceiptMatches, installedHostActionRequestIdentity, installedHostBoundaryRevealSelector, installedPluginControlPreservesModal, installedPreparationIdentity, installedSidebarHandoffRequestMatches, installedSidebarHandoffSpec, installedSidebarSelector, installedStudioControlScenario, installedStudioPrerequisites, installedSurfaceState, installedSurfaceAcknowledged, installedSurfaceControlAcknowledged, installedWorkbenchCommandSpec, installedWorkbenchAuthorityBoundarySpec, knowledgeBrowseHasHead, knowledgeGraphControlProbe, knowledgeLifecycleControlProbe, learningLifecycleControlProbe, nativeWorkbenchKeyboardActionAdmitted, nativeWorkbenchKeyboardFallbackAdmitted, nativeWorkbenchRequestFallbackAdmitted, ownedCleanupCandidate, ownedWorkbenchReloadIdentity, partitionExpectedFaultDiagnostics, pluginMutationControlProbe, pluginReadControlProbe, probeInstalledSidebarControls, projectMapIdentity, projectsControlProbe, reacquirableOwnedFrameError, restartInstalledSidebarWebview, revealInstalledHostBoundaryControl, selectLatestMatchingInstalledSnapshot, sidebarPreferenceRoundTripIdentity, sidebarReconstructionIdentity, sidebarStateControlProbe, sidebarStateControlVerified, skillQueryControlProbe, systemProjectionControlProbe, systemProjectionIdentity, requestBoundSystemSnapshotIdentity, validCleanupResult, validCoordinationResult, validKnowledgeLifecycleResult, validLearningLifecycleResult, validPermanentCleanupResult, validPendingPluginMutationReceipt, validPluginLifecycleObservation, validPluginMutationReceipt, validStudioDraftReceipt, validStudioLifecycleResult, validStudioRevisionEditObservation, validStudioSetupResult, validationControlProbe, workbenchCommandRowIdentity } = require('../scripts/run-operational-ui-walk');
const { codexHandoffControlProbe } = require('../scripts/run-operational-ui-walk');
const { installedSnapshotTimeoutIdentity } = require('../scripts/run-operational-ui-walk');
const { currentSourceExtensionAssetIdentity, installedRuntimeSourceIdentityState } = require('../scripts/run-operational-ui-walk');
const { installedSourceIdentityNeedsLateRefresh } = require('../scripts/run-operational-ui-walk');
const { mergeStudioLifecycleObservations } = require('../scripts/run-operational-ui-walk');
const { correlateCatalogExchange } = require('../scripts/run-operational-ui-walk');
const { buildInstalledLateCardAdversarialProfile, buildInstalledLateCardScenarioProfile, runInstalledStudioBridgeConflictProfile } = require('../scripts/run-operational-ui-walk');
const { exactStudioSetupTerminalResponse } = require('../scripts/run-operational-ui-walk');
const { installedDashboardRestartIdentity } = require('../scripts/run-operational-ui-walk');
const { dispatchInstalledPluginConfirmation, dispatchInstalledPluginFormAction, installedPluginPreviewConfirmationMatches } = require('../scripts/run-operational-ui-walk');
const { installedAdvancedFixtureStateAcknowledged } = require('../scripts/run-operational-ui-walk');

const { boundedOwnedUiAction, waitForOwnedWebview } = require('../scripts/run-operational-ui-walk');
const { clickWhenBuilderControlReady, clickWhenInstalledGraphControlReady, installedGraphExchangeOffset, invokeBuilderControl, waitForBuilderJsonControls, waitForInstalledGraphExchange, waitForInstalledGraphIdle } = require('../scripts/run-operational-ui-walk');

const STAGES = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];

test('dashboard restart identity follows canonical ownership instead of the restored visible surface title', () => {
  const canonicalRestart = { document_ready: true, canonical_dashboard_dom: true, connected: true, restarted: true };
  assert.equal(installedDashboardRestartIdentity(canonicalRestart), true);
  for (const field of Object.keys(canonicalRestart)) {
    assert.equal(installedDashboardRestartIdentity({ ...canonicalRestart, [field]: false }), false, `${field} must remain mandatory`);
  }
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const restart = source.slice(source.indexOf('async function restartInstalledDashboardWebview'), source.indexOf('async function reloadInstalledDashboardWebview'));
  const reload = source.slice(source.indexOf('async function reloadInstalledDashboardWebview'), source.indexOf('async function waitForInstalledStudioState'));
  assert.match(restart, /canonical_dashboard_dom:[\s\S]*data-surface="dashboard"[\s\S]*data-surface="agents"/);
  assert.match(restart, /canonicalRestartDisconnected[\s\S]*disconnectedRecoveryDelayMs[\s\S]*restartOwnedWorkbenchWindow\(workbench, frameHost, remaining, \{ conflictSafeReconstruction: true \}\)/);
  assert.match(reload, /canonical_dashboard_dom:[\s\S]*data-surface="dashboard"[\s\S]*data-surface="agents"/);
  assert.doesNotMatch(restart, /PACIFY-X\\s\*\\\/\\s\*DASHBOARD/);
  assert.doesNotMatch(reload, /PACIFY-X\\s\*\\\/\\s\*DASHBOARD/);
});

test('Studio lifecycle projection preserves eligible and blocked Agent roles while replacing the primary Skill revision', () => {
  const eligibleAgent = { kind: 'agent', identity: 'agent:eligible', fixture_only: false, operations: [{ operation: 'start', valid: true }] };
  const blockedAgent = { kind: 'agent', identity: 'agent:blocked', fixture_only: true, blocked_preview_verified: true };
  const workflow = { kind: 'workflow', identity: 'workflow:eligible' };
  const originalSkill = { kind: 'skill', identity: 'skill:eligible', operations: [{ operation: 'promote', valid: true }] };
  const rollbackSkill = { kind: 'skill', identity: 'skill:eligible', operations: [{ operation: 'rollback', valid: true }] };
  const current = [eligibleAgent, blockedAgent, workflow, originalSkill];
  const replacements = [rollbackSkill];
  const before = JSON.stringify({ current, replacements });
  const merged = mergeStudioLifecycleObservations(
    current,
    replacements
  );

  assert.deepEqual(merged, [eligibleAgent, blockedAgent, workflow, rollbackSkill]);
  assert.equal(JSON.stringify({ current, replacements }), before, 'projection must not mutate source observations');
  assert.equal(merged.filter(observation => observation.kind === 'agent').length, 2);
  assert.equal(merged.find(observation => observation.kind === 'agent' && observation.fixture_only !== true), eligibleAgent);
  assert.equal(merged.find(observation => observation.kind === 'agent' && observation.fixture_only === true), blockedAgent);

  const blockedReplay = { ...blockedAgent, blocked_preview_verified: false };
  const replayed = mergeStudioLifecycleObservations(merged, [blockedReplay]);
  assert.equal(replayed.filter(observation => observation.kind === 'agent').length, 2, 'a repeated fixture may replace only its exact fixture identity');
  assert.equal(replayed.find(observation => observation.fixture_only === true), blockedReplay);
  assert.equal(replayed.find(observation => observation.fixture_only !== true && observation.kind === 'agent'), eligibleAgent);
});

test('Catalog exchange correlation rejects stale same-kind responses and binds lifecycle status to the exact request', () => {
  const requests = [
    { type: 'catalogQuery', requestId: 'agents-stale', kind: 'agents', status: '', offset: 0, limit: 50 },
    { type: 'catalogQuery', requestId: 'agents-active', kind: 'agents', status: 'active', offset: 0, limit: 50 }
  ];
  const responses = [
    { type: 'catalogResult', requestId: 'agents-stale', result: { kind: 'agents', filtered: 0, items: [] } },
    { type: 'catalogResult', requestId: 'agents-active', result: { kind: 'agents', filtered: 9, items: [{ status: 'active' }] } }
  ];
  const exchange = correlateCatalogExchange(requests, responses, { kind: 'agents', status: 'active', offset: 0, limit: 50 });
  assert.equal(exchange.request.requestId, 'agents-active');
  assert.equal(exchange.request.status, 'active');
  assert.equal(exchange.response.requestId, 'agents-active');
  assert.equal(exchange.response.result.filtered, 9);

  const missingExactResponse = correlateCatalogExchange(requests, responses.slice(0, 1), { kind: 'agents', status: 'active', offset: 0, limit: 50 });
  assert.equal(missingExactResponse.request.requestId, 'agents-active');
  assert.equal(missingExactResponse.response, null, 'a stale same-kind response cannot satisfy a newer lifecycle request');
});

test('expected owned fault diagnostics are retained until exact reversible recovery is proven', () => {
  const diagnostics = [
    { source: 'console', message: 'Pacify-X setActivityPaused failed closed: owned-injected-configuration-fault:setActivityPaused' },
    { source: 'console', message: 'unrelated console failure' }
  ];
  const incomplete = { eligible_control_count: 1, records: [{ attempted: true, errors: ['restart failed'], interaction_chain: {} }] };
  assert.deepEqual(partitionExpectedFaultDiagnostics(diagnostics, incomplete), { retained: diagnostics, recovered: [] });

  const interactionChain = Object.fromEntries(STAGES.map(stage => [stage, { state: 'present' }]));
  const complete = { eligible_control_count: 1, records: [{ attempted: true, errors: [], interaction_chain: interactionChain }] };
  const partitioned = partitionExpectedFaultDiagnostics(diagnostics, complete);
  assert.deepEqual(partitioned.retained, [diagnostics[1]]);
  assert.equal(partitioned.recovered.length, 1);
  assert.equal(partitioned.recovered[0].disposition, 'expected_owned_fault_recovered');
  const hostFault = { source: 'console', message: 'Pacify-X openFile failed closed: owned-injected-host-action-fault:openFile' };
  const completeHost = { eligible_control_count: 1, records: [{ ...complete.records[0], control_id: 'pxui.diagnostics.action.openPunchSource.row' }] };
  assert.deepEqual(partitionExpectedFaultDiagnostics([hostFault], incomplete, completeHost), { retained: [], recovered: [{ ...hostFault, disposition: 'expected_owned_fault_recovered' }] });
  assert.deepEqual(partitionExpectedFaultDiagnostics([hostFault], incomplete, incomplete), { retained: [hostFault], recovered: [] });
});

test('owned host fault diagnostics recover only exact operations with individual rollback proof', () => {
  const chain = Object.fromEntries(STAGES.map(stage => [stage, { state: 'present' }]));
  const partialHost = {
    eligible_control_count: 3,
    records: [
      { control_id: 'pxui.dashboard-control-plane.action.openSettings.header', attempted: true, errors: [], interaction_chain: { ...chain, recovery_rollback: { state: 'not_applicable', evidence: ['matrix:openSettings'] } } },
      { control_id: 'pxui.memory.action.contextSnapshot', attempted: true, errors: [], interaction_chain: { ...chain, recovery_rollback: { state: 'missing' } } },
      { control_id: 'pxui.memory.action.openMemorySource', attempted: false, errors: ['not rendered'], interaction_chain: {} }
    ]
  };
  const diagnostics = [
    { source: 'console', message: 'owned-injected-host-action-fault:openSettings' },
    { source: 'console', message: 'owned-injected-host-action-fault:createContextSnapshot' },
    { source: 'console', message: 'owned-injected-host-action-fault:unknownOperation' },
    { source: 'console', message: 'owned-injected-host-action-fault:openSettings:extra' },
    { source: 'page', message: 'owned-injected-host-action-fault:openSettings' }
  ];
  const partitioned = partitionExpectedFaultDiagnostics(diagnostics, null, partialHost);
  assert.deepEqual(partitioned.recovered, [{ ...diagnostics[0], disposition: 'expected_owned_fault_recovered' }]);
  assert.deepEqual(partitioned.retained, diagnostics.slice(1));
});

test('owned dead-proxy diagnostics are nonblocking only with the exact sentinel and external VS Code context', () => {
  const proxy = { source: 'console', context: 'vscode-file://vscode-app/out/vs/workbench/workbench.desktop.main.js', message: 'Failed to load resource: net::ERR_PROXY_CONNECTION_FAILED' };
  const marketplace = { source: 'console', context: 'https://marketplace.visualstudio.com/_apis/public/gallery', message: 'Failed to fetch' };
  const fallback = { source: 'console', context: 'console:vscode-file://vscode-app/out/vs/workbench/workbench.desktop.main.js', message: '%c ERR color: #f33 Error while getting the latest version for the extension mountain-nomad-bc.pacify-x-vscode from https://marketplace.visualstudio.com/_apis/public/gallery/vscode/{publisher}/{name}/latest. Trying the fallback https://www.vscode-unpkg.net/_gallery/{publisher}/{name}/latest Failed' };
  const product = { source: 'console', context: 'vscode-webview://pacify-x/dashboard.js', message: 'Failed to fetch' };
  assert.deepEqual(partitionExpectedFaultDiagnostics([proxy, marketplace, fallback, product], null, null, true), {
    retained: [product],
    recovered: [
      { ...proxy, disposition: 'expected_owned_external_network_denial' },
      { ...marketplace, disposition: 'expected_owned_external_network_denial' },
      { ...fallback, disposition: 'expected_owned_external_network_denial' }
    ]
  });
  assert.deepEqual(partitionExpectedFaultDiagnostics([proxy], null, null, false), { retained: [proxy], recovered: [] });
});

test('late-card diagnostics exclude only exact external host warnings', () => {
  const mermaid = {
    source: 'console',
    context: 'console:vscode-file://vscode-app/C:/Program Files/Microsoft VS Code/resources/app/out/vs/workbench/workbench.desktop.main.js',
    message: '%c ERR color: #f33 Tool "renderMermaidDiagram" was not contributed.'
  };
  const marketplace = {
    source: 'console',
    context: 'console:https://marketplace.visualstudio.com/_apis/public/gallery/vscode/px-owned/fixture/latest',
    message: 'Failed to load resource: the server responded with a status of 404 ()'
  };
  const lookalike = { ...marketplace, context: 'console:https://marketplace.visualstudio.com/_apis/public/gallery/vscode/other/fixture/latest' };
  assert.deepEqual(partitionExpectedFaultDiagnostics([mermaid, marketplace, lookalike], null, null, false), {
    retained: [lookalike],
    recovered: [
      { ...mermaid, disposition: 'expected_external_host_warning' },
      { ...marketplace, disposition: 'expected_external_host_warning' }
    ]
  });
});

test('graph cancellation settles on exact installed idle state without requiring a graph response', async () => {
  const samples = [false, false, true];
  const frameHost = { evaluateContent: async () => samples.shift() ?? true };
  assert.equal(await waitForInstalledGraphIdle(frameHost, 1_000), true);
  assert.equal(samples.length, 0);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const cancellation = source.slice(source.indexOf('async function runInstalledLateCardRepairObservationProfile'), source.indexOf('async function runInstalledObservationStateProfile'));
  assert.match(cancellation, /const cancelled = await waitForInstalledGraphIdle\(frameHost, timeoutMs\)/);
  assert.doesNotMatch(source, /await waitForInstalledResponse\(frameHost, before, \{ types: \['graphResult'\] \}, timeoutMs\);\s*const cancelled/);
});

test('graph pagination waits for the exact request-bound terminal response', async () => {
  const requests = [{ type: 'graphQuery', requestId: 'graph-exact', offset: 0, edgeOffset: 0 }];
  const responses = [
    { type: 'graphResult', requestId: 'graph-stale', result: { page: {} } },
    { type: 'graphResult', requestId: 'graph-exact', result: { page: { node_has_more: true } } }
  ];
  const frame = { contentWindow: { __PX_INSTALLED_REQUESTS__: requests, __PX_INSTALLED_RESPONSES__: responses } };
  const frameHost = { evaluate: async (operation, argument) => operation(frame, argument) };
  assert.deepEqual(await installedGraphExchangeOffset(frameHost), { requests: 1, responses: 2 });
  const exact = await waitForInstalledGraphExchange(frameHost, { requests: 0, responses: 0 }, 1_000);
  assert.equal(exact.requestId, 'graph-exact');
  assert.equal(exact.result.page.node_has_more, true);

  frame.contentWindow.__PX_INSTALLED_RESPONSES__ = [
    { type: 'operationError', operation: 'graphQuery', requestId: 'graph-exact', error: 'work-superseded' }
  ];
  await assert.rejects(
    waitForInstalledGraphExchange(frameHost, { requests: 0, responses: 0 }, 1_000),
    /installed-graph-query-failed:graph-exact:work-superseded/
  );
});

test('builder JSON controls are reacquired from the current modal render', async () => {
  let samples = 0;
  let selected = false;
  const tab = { disabled: false, getAttribute: name => name === 'aria-selected' && selected ? 'true' : 'false', click: () => { selected = true; } };
  const input = {};
  const apply = {};
  const modal = { querySelector: selector => {
    if (selector.includes('studioEditorTab')) return tab;
    if (selector === '#studio-draft-json') return selected ? input : null;
    if (selector.includes('studioApplyJson')) return selected ? apply : null;
    if (selector === 'h2') return { textContent: 'Agent Studio' };
    return null;
  } };
  const frameHost = { evaluate: async (operation, argument) => {
    samples += 1;
    const document = { querySelector: selector => selector === '.studio-modal' && samples > 1 ? modal : null };
    return operation({ contentDocument: document }, argument);
  } };
  const ready = await waitForBuilderJsonControls(frameHost, 'agent', 1_000);
  assert.equal(ready.ready, true);
  assert.equal(ready.json_tab_selected, true);
  assert.ok(samples >= 2, 'the helper must tolerate a transiently replaced modal render');
});

test('builder action controls are atomically reacquired from the current installed render', async () => {
  let samples = 0;
  let clicks = 0;
  const control = {
    dataset: { action: 'agentZoom', delta: '0.1' },
    disabled: false,
    innerText: '+',
    getAttribute: () => 'Zoom in',
    click: () => { clicks += 1; }
  };
  const frameHost = { evaluate: async (operation, argument) => {
    samples += 1;
    const modal = {
      querySelector: () => null,
      querySelectorAll: selector => selector === '[data-action]' && samples >= 3 ? [control] : []
    };
    const document = { querySelector: selector => selector === '.studio-modal' ? modal : null };
    return operation({ contentDocument: document }, argument);
  } };
  const result = await clickWhenBuilderControlReady(frameHost, {
    controlId: 'pxui.agent-studio.action.agentZoom.in',
    action: 'agentZoom', dataset: { delta: '0.1' }, pick: 'only'
  }, 1_000);
  assert.deepEqual(result, { match_count: 1, label: '+' });
  assert.equal(clicks, 1);
  assert.ok(samples >= 3, 'the control must be reacquired after transient render replacement');
});

test('builder action continuity attributes a displaced Studio modal to the causing control', async () => {
  let displaced = false;
  const classes = (...items) => Object.assign(items, { contains: value => items.includes(value) });
  const control = {
    dataset: { action: 'agentRemoveBinding', index: '1' }, disabled: false, innerText: 'Remove',
    classList: classes(), getAttribute: () => 'Remove binding', click: () => { displaced = true; }
  };
  const studioModal = {
    classList: classes('control-modal', 'studio-modal'),
    querySelector: selector => selector === 'h2' ? { textContent: 'Agent Studio' }
      : selector === '[data-agent-editor-canvas]' ? { dataset: { agentScale: '1' } }
        : selector === '.studio-editor-root' ? {} : null,
    querySelectorAll: selector => selector === '[data-action]' ? [control] : []
  };
  const lateModal = {
    classList: classes('control-modal'),
    querySelector: selector => selector === 'h2' ? { textContent: 'Eligible skill candidates' } : null,
    querySelectorAll: selector => selector === '[data-action]' ? [{ dataset: { action: 'closeModal' } }] : []
  };
  const frameHost = { evaluate: async (operation, argument) => operation({ contentDocument: {
    querySelector: selector => selector === '.studio-modal' ? (displaced ? null : studioModal)
      : selector === '.control-modal' ? (displaced ? lateModal : studioModal) : null
  } }, argument) };
  await assert.rejects(
    invokeBuilderControl(frameHost, 'agent', 'pxui.agent-studio.action.agentRemoveBinding.row', 'agentRemoveBinding', {}, 'last'),
    error => {
      assert.match(error.message, /builder modal continuity lost after agentRemoveBinding/);
      assert.equal(error.builderObservation.control_id, 'pxui.agent-studio.action.agentRemoveBinding.row');
      assert.equal(error.builderObservation.after.active_modal_title, 'Eligible skill candidates');
      assert.deepEqual(error.builderObservation.after.active_modal_classes, ['control-modal']);
      assert.deepEqual(error.builderObservation.after.active_modal_actions, ['closeModal']);
      return true;
    }
  );
});

test('graph action readiness requires the current enabled label before one atomic click', async () => {
  let samples = 0;
  let clicks = 0;
  const control = {
    dataset: { action: 'graphLoadAll' },
    get disabled() { return samples < 3; },
    textContent: 'Load all remaining pages',
    click: () => { clicks += 1; }
  };
  const frameHost = { evaluate: async (operation, argument) => {
    samples += 1;
    return operation({ contentDocument: { querySelectorAll: () => [control] } }, argument);
  } };
  const result = await clickWhenInstalledGraphControlReady(frameHost, 'graphLoadAll', 'Load all remaining pages', 1_000);
  assert.equal(result.clicked, true);
  assert.equal(result.match_count, 1);
  assert.equal(clicks, 1);
  assert.ok(samples >= 3);
});

test('graph cancellation reseeds a bounded incomplete page before recovery and proves terminal completion', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const start = source.indexOf('async function runInstalledObservationStateProfile');
  const profile = source.slice(start, source.indexOf("await navigateInstalledSurface(frameHost, 'memory'", start));
  assert.match(profile, /const cancelled = await waitForInstalledGraphIdle[\s\S]*const recoverySeed = await requestGraphPage\(\)[\s\S]*graph-recovery-denominator-too-small[\s\S]*clickWhenInstalledGraphControlReady\(frameHost, 'graphLoadAll', 'Load all remaining pages'/);
  assert.match(profile, /const allDone = completion\.idle && !completion\.node_has_more && !completion\.edge_has_more[\s\S]*completion\.control_disabled[\s\S]*Complete graph loaded/);
  assert.doesNotMatch(profile, /querySelector\('\[data-action="graphLoadAll"\]'\)\?\.click/);
});

test('timed profile failures retain partial builder evidence and the exact failed control state', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const collector = source.slice(source.indexOf('const failedProfileResult'), source.indexOf('const skippedProfileResult'));
  assert.match(collector, /failure\?\.builderEvidence/);
  assert.match(collector, /observations: builderEvidence\?\.observations \|\| \[\]/);
  assert.match(collector, /failed_control_id: builderEvidence\?\.failed_control_id \|\| null/);
  assert.match(collector, /failure_state: builderEvidence\?\.failure_state \|\| null/);
});

test('graph cancellation diagnostic is nonblocking only after exact cancellation recovery', () => {
  const diagnostic = {
    source: 'console',
    context: 'console:vscode-file://vscode-app/resources/app/out/vs/workbench/workbench.desktop.main.js',
    message: 'Pacify-X graphQuery failed closed: work-superseded'
  };
  const complete = { observations: { 'pxui.knowledge-graph.action.graphLoadAll': { attempted: true, cancelled: true, recovered: true, completed: true } } };
  assert.deepEqual(partitionExpectedFaultDiagnostics([diagnostic], null, null, false, complete), {
    retained: [],
    recovered: [{ ...diagnostic, disposition: 'expected_graph_cancellation_recovered' }]
  });
  const transportDiagnostic = { ...diagnostic, message: 'Pacify-X graphQuery failed closed: Pacify-X dashboard API request was superseded.' };
  assert.deepEqual(partitionExpectedFaultDiagnostics([transportDiagnostic], null, null, false, complete), {
    retained: [],
    recovered: [{ ...transportDiagnostic, disposition: 'expected_graph_cancellation_recovered' }]
  });
  const incomplete = { observations: { 'pxui.knowledge-graph.action.graphLoadAll': { attempted: true, cancelled: true, recovered: false, completed: false } } };
  assert.deepEqual(partitionExpectedFaultDiagnostics([diagnostic], null, null, false, incomplete), { retained: [diagnostic], recovered: [] });
  assert.equal(partitionExpectedFaultDiagnostics([{ ...diagnostic, message: `${diagnostic.message}:lookalike` }], null, null, false, complete).retained.length, 1);

  const focused = {
    projects: { observation: { completed: true, exact_reconstruction: true, cancelled_controls: { a: true, b: true, c: true } } },
    knowledgeGraph: { observation: { completed: true, exact_reconstruction: true, restored: true } }
  };
  assert.equal(partitionExpectedFaultDiagnostics([diagnostic], null, null, false, null, focused).recovered[0]?.disposition, 'expected_graph_cancellation_recovered');
  assert.deepEqual(partitionExpectedFaultDiagnostics([diagnostic], null, null, false, null, {
    ...focused,
    knowledgeGraph: { observation: { ...focused.knowledgeGraph.observation, restored: false } }
  }), { retained: [diagnostic], recovered: [] });
});

test('late-card repair focus runs only observation state and controller adversarial profiles', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /PX_OPERATIONAL_LATE_CARD_REPAIR_ONLY === '1'/);
  assert.match(source, /lateCardRepairOnly \? 'late-card-repair'/);
  assert.match(source, /lateCardRepairOnly[\s\S]*runInstalledLateCardRepairObservationProfile\(dashboard, proofMatrix\)[\s\S]*runInstalledObservationStateProfile\(dashboard, sidebar, proofMatrix\)/);
  assert.match(source, /INSTALLED_GRAPH_PAGINATION_OBSERVATION_IDS[\s\S]*observationStateControlProbe\(matrix, observations, INSTALLED_GRAPH_PAGINATION_OBSERVATION_IDS\)/);
  assert.match(source, /lateCardControllerProfile = \(!focusedProfileOnly \|\| lateCardRepairOnly\)/);
  assert.match(source, /studioChainAdmitted =[\s\S]*!lateCardRepairOnly/);
  assert.match(source, /knowledgeLifecycleProfile =[\s\S]*!lateCardRepairOnly/);
  assert.match(source, /learningLifecycleProfile =[\s\S]*!lateCardRepairOnly/);
  assert.match(source, /lateCardWorkerProfile = !focusedProfileOnly/);
  assert.match(source, /lateCardAdversarialProfile = !focusedProfileOnly/);
});

test('builder focus runs only the two unsaved builder durability profiles', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /PX_OPERATIONAL_BUILDER_ONLY === '1'/);
  assert.match(source, /builderOnly \? 'builder' : null/);
  assert.match(source, /for \(const kind of focusedProfileOnly && !builderOnly \? \[\] : \['agent', 'workflow'\]\)/);
  assert.match(source, /if \(focusedProfileOnly && !builderOnly\)/);
  assert.match(source, /studioChainAdmitted =[^\n]*!builderOnly/);
  assert.match(source, /knowledgeLifecycleProfile =[^\n]*!builderOnly/);
  assert.match(source, /learningLifecycleProfile =[^\n]*!builderOnly/);
});

test('physical host mechanics reopen the owned editor, preserve command mode, and defer command probes', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /dashboardTab\.click\(\)[\s\S]*Control\+W[\s\S]*reopenPacifyDashboardFromOwnedUi\(workbench, frameHost\)/);
  assert.match(source, /async function reopenPacifyDashboardFromOwnedUi\(workbench, frameHost = null[\s\S]*\[role="tab"\][\s\S]*dashboardTab\.isVisible\(\)[\s\S]*lastOwner = 'existing-dashboard-tab'[\s\S]*lastOwner = 'pacify-statusbar'[\s\S]*keyboard\.press\('Escape'\)[\s\S]*owner\.click\([\s\S]*owner\.evaluate\(element => element\.click\([\s\S]*frameHost\.reacquire[\s\S]*instrumentInstalledBridge\(frameHost, reconstructionBudget\)[\s\S]*installed-dashboard-owner-reopen-timeout/);
  assert.match(source, /for \(let sample = 0; sample < 2; sample \+= 1\)[\s\S]*frameHost\.reacquire[\s\S]*stability_samples: 2/);
  assert.match(source, /after_time_origin: state\.time_origin, restarted: true, reconstructed: true/);
  assert.match(source, /async function closeOwnedDashboardTabs[\s\S]*PX\.\*Control Plane[\s\S]*Control\+W[\s\S]*restored-tab-close-unobserved/);
  assert.match(source, /restartOwnedWorkbenchWindow[\s\S]*closeOwnedDashboardTabs[\s\S]*Pacify-X: Open Control Plane|restartOwnedWorkbenchWindow[\s\S]*closeOwnedDashboardTabs[\s\S]*openDashboard[\s\S]*reopenPacifyDashboardFromOwnedUi/);
  assert.doesNotMatch(source, /frame\.setAttribute\('src', source\)/);
  assert.doesNotMatch(source, /inner\.location\.reload\(\)/);
  assert.match(source, /async function openWorkbenchCommandPalette[\s\S]*quick-input-widget:visible[\s\S]*keyboard\.press\('Escape'\)[\s\S]*state: 'hidden'[\s\S]*shortcuts = \['F1'[\s\S]*Control\+Shift\+P/);
  assert.match(source, /keyboard\.press\(process\.platform === 'darwin' \? 'Meta\+A' : 'Control\+A'\)[\s\S]*keyboard\.type\(`>\$\{title\}`\)/);
  assert.match(source, /quick-input-list \.monaco-list-row[\s\S]*\.label-name[\s\S]*workbenchCommandRowIdentity[\s\S]*keyboard\.press\('Enter'\)[\s\S]*widget\.waitFor\(\{ state: 'hidden'/);
  assert.doesNotMatch(source, /getByText\(title, \{ exact: true \}\)\.first\(\)/);
  assert.doesNotMatch(source, /await exact\.click\(\)/);
  const hostBoundary = source.slice(source.indexOf('async function runInstalledHostBoundaryProfile'), source.indexOf('const INSTALLED_ENTERPRISE_CONTROLS'));
  assert.match(hostBoundary, /reopenPacifyDashboardFromOwnedUi\(workbench,/);
  assert.doesNotMatch(hostBoundary, /executeWorkbenchCommand\(/);
  assert.doesNotMatch(hostBoundary, /profileDeadline = Date\.now\(\) \+ 180_000/);
  assert.match(hostBoundary, /controlBudgetMs = spec\.scenario === 'canonical-memory'[\s\S]*controlDeadline = Date\.now\(\) \+ controlBudgetMs/);
  assert.match(hostBoundary, /exerciseOwnedHostActionFailure[\s\S]*failure_handling[\s\S]*failure_dashboard_recovered[\s\S]*refused_without_effect/);
  assert.ok(hostBoundary.indexOf('reopenPacifyDashboardFromOwnedUi(workbench,') < hostBoundary.indexOf('typed-acknowledgement-missing'), 'a displaced webview must reconstruct before reading the durable request-bound receipt');
  assert.match(hostBoundary, /DISPLACING_HOST_OPERATIONS\.has\(spec\.operation\)/);
  assert.match(source, /openPunchSource'[\s\S]*operation: 'openFile', editorDisplacement: true/);
  assert.match(hostBoundary, /if \(displacing\) \{[\s\S]*waitForOwnedWorkbenchDisplacementOrReceipt\(workbench, frameHost,[\s\S]*terminal === 'native-displacement'[\s\S]*reopenPacifyDashboardFromOwnedUi\(workbench, frameHost/);
  assert.doesNotMatch(hostBoundary, /refreshSnapshot: false/);
  assert.match(hostBoundary, /outboundRequest = \(frame\.contentWindow\?\.__PX_INSTALLED_REQUESTS__[\s\S]*reopenPacifyDashboardFromOwnedUi\(workbench, frameHost[\s\S]*refreshSnapshot: true/);
  assert.ok(hostBoundary.indexOf('outboundRequest = (frame.contentWindow?.__PX_INSTALLED_REQUESTS__') < hostBoundary.indexOf('reopenPacifyDashboardFromOwnedUi(workbench,'), 'the request must be captured in the dispatch evaluation before native displacement');
  assert.ok(hostBoundary.indexOf('reopenPacifyDashboardFromOwnedUi(workbench,') < hostBoundary.indexOf('refreshSnapshot: true'), 'durable receipt refresh must wait for owned UI reconstruction');
  assert.match(hostBoundary, /response \|\|= await waitForDurableHostActionResult/);
  assert.match(hostBoundary, /typed-acknowledgement-unaccepted/);
  assert.match(hostBoundary, /navigateInstalledSurface\(frameHost, spec\.route/);
  assert.match(hostBoundary, /finally[\s\S]*resetInstalledDashboardBaseline\(workbench, frameHost/);
  assert.match(hostBoundary, /actionStartedAt = Date\.now\(\)[\s\S]*waitForDurableHostActionResult/);
  const durableReceipt = source.slice(source.indexOf('async function waitForDurableHostActionResult'), source.indexOf('const INSTALLED_HOST_BOUNDARY_SPECS'));
  assert.match(durableReceipt, /Date\.parse\(value\.observedAt/);
  assert.match(durableReceipt, /const readAcknowledgement = \(\) => frameHost\.evaluate[\s\S]*return readAcknowledgement\(\)/);
  assert.ok(source.indexOf("timedProfile('sidebar-state-restart'") < source.indexOf("timedProfile('workbench-commands'"));
});

test('owned workbench reload identity requires a new ready renderer document', () => {
  assert.equal(ownedWorkbenchReloadIdentity(100, 200, true), true);
  assert.equal(ownedWorkbenchReloadIdentity(100, 100, true), false);
  assert.equal(ownedWorkbenchReloadIdentity(100, 200, false), false);
  assert.equal(ownedWorkbenchReloadIdentity(0, 200, true), false);
});

test('command palette identity requires one visible full-label selected row', () => {
  const title = 'Pacify-X: Open Control Plane';
  const similar = { id: 'row-similar', label: 'View: Toggle Control Characters', visible: true, selected: false };
  const exact = { id: 'row-exact', label: 'Pacify-X:   Open Control Plane', visible: true, selected: true };
  assert.deepEqual(workbenchCommandRowIdentity([similar, exact], title, ''), { valid: true, reason: 'exact-visible-selected-command-row', match_count: 1, row: exact });
  const active = { ...exact, selected: false };
  assert.equal(workbenchCommandRowIdentity([similar, active], title, 'row-exact').valid, true);
  assert.equal(workbenchCommandRowIdentity([{ ...exact, visible: false }, similar], title, '').reason, 'exact-visible-command-row-missing');
  assert.equal(workbenchCommandRowIdentity([exact, { ...exact, id: 'row-duplicate' }], title, '').reason, 'duplicate-exact-visible-command-rows');
  assert.equal(workbenchCommandRowIdentity([active, similar], title, '').reason, 'exact-command-row-not-selected');
});

test('command palette attempts retry only after widget loss and dispatch only exact identity', () => {
  const missing = { valid: false, reason: 'exact-visible-command-row-missing', match_count: 0, row: null };
  assert.equal(commandPaletteAttemptDecision(missing, true), 'continue-current-widget');
  assert.equal(commandPaletteAttemptDecision(missing, false), 'retry-fresh-widget');
  assert.equal(commandPaletteAttemptDecision({ ...missing, valid: true }, true), 'dispatch');
  assert.equal(commandPaletteAttemptDecision({ ...missing, valid: true }, false), 'dispatch');
});

test('profile control settlement requires the exact rendered surface, scope, and visible control', () => {
  const exact = { nav_current: true, rendered_surface: true, scope_current: true, control_visible: true };
  assert.equal(installedSurfaceControlAcknowledged(exact), true);
  for (const key of Object.keys(exact)) assert.equal(installedSurfaceControlAcknowledged({ ...exact, [key]: false }), false, key);
  let settlement = advanceInstalledSurfaceControlSettlement(exact, 0, 4);
  assert.deepEqual(settlement, { consecutive_samples: 1, complete: false });
  settlement = advanceInstalledSurfaceControlSettlement(exact, settlement.consecutive_samples, 4);
  assert.deepEqual(settlement, { consecutive_samples: 2, complete: false });
  settlement = advanceInstalledSurfaceControlSettlement({ ...exact, nav_current: false }, settlement.consecutive_samples, 4);
  assert.deepEqual(settlement, { consecutive_samples: 0, complete: false }, 'a late route invalidation must reset settlement');
  for (let sample = 1; sample <= 4; sample += 1) {
    settlement = advanceInstalledSurfaceControlSettlement(exact, settlement.consecutive_samples, 4);
    assert.equal(settlement.complete, sample === 4);
  }
  assert.equal(installedSurfaceAcknowledged({ nav_current: true, rendered_surface: false }), false);
  assert.equal(installedSurfaceAcknowledged({ nav_current: false, rendered_surface: true }), false);
  assert.equal(installedSurfaceAcknowledged({ nav_current: true, rendered_surface: true }), true);
});

test('plugin settlement preserves only exact request-bound execute confirmation modals', () => {
  for (const action of [
    'executeExtensionEnablement',
    'executeExtensionInstall',
    'executeExtensionUpdate',
    'executeExtensionUninstall',
    'executeExtensionRollback',
    'executeExtensionConflictResolution'
  ]) assert.equal(installedPluginControlPreservesModal(`[data-action="${action}"]`), true, action);
  for (const selector of [
    '#extension-install-id',
    '[data-action="previewExtensionInstall"]',
    '[data-action="queryExtensionConflicts"]',
    '[data-action="openExtensionsView"]',
    '[data-action="executeExtensionInstall"][data-token]'
  ]) assert.equal(installedPluginControlPreservesModal(selector), false, selector);
});

test('plugin conflict route dispatches the authenticated confirmation without a second modal settlement window', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledPluginMutationProfile'), source.indexOf('function knowledgeLifecycleControlProbe'));
  const conflictRoute = profile.slice(profile.indexOf('const exerciseConflictRoute'), profile.indexOf('observation.conflict_route_completed'));
  assert.match(conflictRoute, /waitForResponse\(previewBefore, 'extensionConflictResolutionPreview'[^]*dispatchInstalledPluginConfirmation\(frameHost, \{[^]*executeAction: 'executeExtensionConflictResolution'[^]*token: preview\.token[^]*exactTarget: preview\.exact_target/);
  assert.match(conflictRoute, /const executeBefore = dispatch\.responseOffset;[^]*const requestBeforeExecute = dispatch\.requestOffset;/);
  assert.doesNotMatch(conflictRoute, /settleInstalledPluginControl\(frameHost, '\[data-action="executeExtensionConflictResolution"\]'/);
  assert.doesNotMatch(conflictRoute, /querySelector\('\[data-action="executeExtensionConflictResolution"\]'\)\.click\(\)/);
});

test('host-boundary failure coverage is request-bound, pre-effect, one-shot, and recovered before success', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const outbound = source.slice(source.indexOf('async function waitForInstalledOutboundHostAction'), source.indexOf('async function exerciseOwnedHostActionFailure'));
  assert.match(outbound, /__PX_INSTALLED_REQUESTS__/);
  assert.match(outbound, /value\?\.type === item\.expected\.operation/);
  assert.match(outbound, /value\?\.requestId === item\.expected\.requestId/);
  const failure = source.slice(source.indexOf('async function exerciseOwnedHostActionFailure'), source.indexOf('async function invokeInstalledHostAction'));
  assert.match(failure, /owned-host-action-faults[\s\S]*px\.owned-host-action-fault\/1\.0[\s\S]*fail-after-validation-before-host-effect/);
  assert.match(failure, /previousRequestId[\s\S]*operation\.requestId !== previousRequestId[\s\S]*waitForDurableHostActionResult[\s\S]*disposition !== 'failed'[\s\S]*marker-not-consumed/);
  const profile = source.slice(source.indexOf('async function runInstalledHostBoundaryProfile'), source.indexOf('const INSTALLED_ENTERPRISE_CONTROLS'));
  assert.match(profile, /const requestBeforeDispatch = await installedOutboundRequestOffset\(frameHost\)/);
  assert.match(profile, /outboundRequest = \(frame\.contentWindow\?\.__PX_INSTALLED_REQUESTS__ \|\| \[\]\)[\s\S]*slice\(item\.requestOffset\)[\s\S]*value\?\.type === item\.operation[\s\S]*value\?\.requestId === requestId/);
  assert.match(profile, /result\.attempted = true;[\s\S]*result\.outbound_request = dispatch\.outboundRequest/);
  assert.match(profile, /if \(!result\.outbound_request && !displacing\) result\.outbound_request = await waitForInstalledOutboundHostAction/);
  assert.match(profile, /if \(displacing\) \{[\s\S]*reopenPacifyDashboardFromOwnedUi\(workbench, frameHost/);
  assert.doesNotMatch(profile, /if \(displacing\)[\s\S]*refreshSnapshot: false/);
  assert.match(profile, /reconstructedResponseOffset = await frameHost\.evaluate/);
  assert.ok(profile.indexOf('exerciseOwnedHostActionFailure') < profile.indexOf('const before = await frameHost.evaluate'));
  assert.ok(profile.indexOf('failure_dashboard_recovered = true') < profile.indexOf('const before = await frameHost.evaluate'));
  const controls = [{ control_id: 'pxui.activity.action.reconcileStaleActivity', surface_id: 'activity', kind: 'action', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, 'required'])) }];
  const complete = hostBoundaryControlProbe({ controls }, { operations: { [controls[0].control_id]: { rendered: true, attempted: true, acknowledged: true, dashboard_reopened: true, failure_handling: true, failure_dashboard_recovered: true, errors: [] } } });
  assert.ok(STAGES.every(stage => complete.records[0].interaction_chain[stage].state === 'present'));
  const missingRecovery = hostBoundaryControlProbe({ controls }, { operations: { [controls[0].control_id]: { rendered: true, attempted: true, acknowledged: true, dashboard_reopened: true, failure_handling: true, failure_dashboard_recovered: false, errors: [] } } });
  assert.equal(missingRecovery.records[0].interaction_chain.failure_handling.state, 'missing');
  assert.equal(missingRecovery.records[0].interaction_chain.recovery_rollback.state, 'missing');
});

test('host-boundary progress identifies every exact control within its bounded budget', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledHostBoundaryProfile'), source.indexOf('const INSTALLED_ENTERPRISE_CONTROLS'));
  assert.match(profile, /onProgress\(\{ control_id: spec\.controlId, state: 'started', budget_ms: controlBudgetMs \}\)/);
  assert.match(profile, /const recoveryReserveMs = 10_000;[\s\S]*const activeControlDeadline = controlDeadline - recoveryReserveMs/);
  assert.match(profile, /boundedOwnedUiAction\(async \(\) => \{[\s\S]*Math\.max\(1, activeControlDeadline - controlStarted\), `\$\{spec\.controlId\}-host-boundary-control`/);
  assert.match(profile, /host-boundary-control-timeout:[\s\S]*terminalControlTimeout = error/);
  assert.match(profile, /host-boundary-restoration[\s\S]*host-boundary-baseline-recovery/);
  assert.match(profile, /if \(terminalControlTimeout\) throw terminalControlTimeout/);
  assert.match(profile, /state: 'returned',[\s\S]*duration_ms: Date\.now\(\) - controlStarted,[\s\S]*acknowledged: result\.acknowledged === true,[\s\S]*error_count: result\.errors\.length/);
  assert.match(source, /profile: 'host-boundary-control', \.\.\.event/);
});

test('every native-displacing host boundary waits for exact displacement or durable retained-dashboard acknowledgement', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledHostBoundaryProfile'), source.indexOf('const INSTALLED_ENTERPRISE_CONTROLS'));
  assert.match(profile, /const displacingOperation = DISPLACING_HOST_OPERATIONS\.has\(spec\.operation\)/);
  const owner = source.slice(source.indexOf('async function waitForOwnedWorkbenchDisplacementOrReceipt'), source.indexOf('async function resetInstalledDashboardBaseline'));
  assert.match(profile, /if \(displacing\) \{[\s\S]*result\.displacement = await waitForOwnedWorkbenchDisplacementOrReceipt\(workbench, frameHost,[\s\S]*result\.displacement\.response[\s\S]*terminal === 'native-displacement'[\s\S]*reopenPacifyDashboardFromOwnedUi\(workbench, frameHost/);
  assert.doesNotMatch(profile, /if \(spec\.editorDisplacement === true\)/);
  assert.match(owner, /stableSamples >= 3[\s\S]*terminal: 'native-displacement'/);
  assert.match(owner, /lastState\.dashboard[\s\S]*type === 'hostActionResult'[\s\S]*terminal: 'durable-dashboard-retained'/);
  assert.match(owner, /requestId === item\.requestId[\s\S]*operation === item\.operation[\s\S]*Date\.parse\(value\.observedAt/);
  assert.match(profile, /const activeDisplacementBudgetMs = Math\.max\(1_000, activeControlDeadline - Date\.now\(\)\);[\s\S]*waitForOwnedWorkbenchDisplacementOrReceipt\(workbench, frameHost,[\s\S]*activeDisplacementBudgetMs/);
  assert.doesNotMatch(profile, /waitForOwnedWorkbenchDisplacementOrReceipt\(workbench, frameHost,[\s\S]*Math\.min\(10_000, activeControlDeadline - Date\.now\(\)\)/);
  assert.match(profile, /const baselineRecoveryBudgetMs = Math\.max\(1_000, Math\.min\(recoveryReserveMs, controlDeadline - Date\.now\(\)\)\);[\s\S]*resetInstalledDashboardBaseline\(workbench, frameHost, baselineRecoveryBudgetMs\)[\s\S]*baselineRecoveryBudgetMs/);
  assert.ok(profile.indexOf('waitForOwnedWorkbenchDisplacementOrReceipt(workbench,') < profile.indexOf('reopenPacifyDashboardFromOwnedUi(workbench,'));
});

test('mixed portable and canonical memory reveals only an exact canonical record', async () => {
  const spec = {
    revealAction: 'inspectMemoryRecord',
    revealSelector: '[data-action="inspectMemoryRecord"][data-memory-id]'
  };
  assert.equal(installedHostBoundaryRevealSelector(spec), spec.revealSelector);
  assert.equal(installedHostBoundaryRevealSelector({ revealAction: 'inspectMetric' }), '[data-action="inspectMetric"]');
  let portableClicked = false;
  let canonicalClicked = false;
  const portable = { disabled: false, offsetWidth: 10, offsetHeight: 10, getClientRects: () => [1], click: () => { portableClicked = true; } };
  const canonical = { disabled: false, offsetWidth: 10, offsetHeight: 10, getClientRects: () => [1], click: () => { canonicalClicked = true; } };
  const frameHost = {
    async evaluate(operation, selector) {
      assert.equal(selector, spec.revealSelector);
      const frame = { contentDocument: { querySelectorAll: exact => {
        assert.equal(exact, spec.revealSelector);
        return exact.includes('[data-memory-id]') ? [canonical] : [portable, canonical];
      } } };
      return operation(frame, selector);
    }
  };
  assert.equal(await revealInstalledHostBoundaryControl(frameHost, spec), true);
  assert.equal(canonicalClicked, true);
  assert.equal(portableClicked, false);
});

test('conditional host scenarios settle exact owned rows instead of assuming route readiness', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const scenarios = source.slice(source.indexOf('async function prepareInstalledHostBoundaryScenario'), source.indexOf('async function restoreInstalledHostBoundaryScenario'));
  assert.match(scenarios, /canonical-memory[\s\S]*settleInstalledCanonicalMemoryRecord/);
  assert.match(scenarios, /owned-task-row[\s\S]*settleInstalledOwnedTaskRow/);
  assert.match(source, /pxui\.workflows\.action\.copyTaskHandoff\.row'[\s\S]*scenario: 'owned-task-row'/);
  const memorySettlement = source.slice(source.indexOf('async function settleInstalledCanonicalMemoryRecord'), source.indexOf('function installedFilesystemPathIdentity'));
  assert.match(memorySettlement, /data-memory-search[\s\S]*data-memory-project[\s\S]*data-memory-source[\s\S]*data-memory-status/);
  assert.match(memorySettlement, /data-action="memoryRefresh"/);
  assert.match(memorySettlement, /data-action="inspectMemoryRecord"\]\[data-memory-id\]/);
  const taskSettlement = source.slice(source.indexOf('async function settleInstalledOwnedTaskRow'), source.indexOf('async function prepareInstalledHostBoundaryScenario'));
  assert.match(taskSettlement, /scope: 'core'/);
  assert.match(taskSettlement, /data-action="copyTaskHandoff"\]\[data-task-id\]/);
});

test('environment and Codex conditional profiles wait for their exact authoritative state', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const environment = source.slice(source.indexOf('async function runInstalledEnvironmentLifecycleProfile'), source.indexOf('const INSTALLED_SKILL_QUERY_IDS'));
  assert.equal((environment.match(/waitForInstalledResponse\(frameHost, before, \{ types: \['environmentInventory'\] \}/g) || []).length, 2);
  assert.match(environment, /settleInstalledEnvironmentRecord\(frameHost, '\.venv-px-owned-lifecycle'/);
  assert.match(environment, /owned-environment-preview-invalid/);
  assert.match(environment, /waitForInstalledControlState\(frameHost, '\[data-action="executeEnvironmentLifecycle"\]'[\s\S]*executeVisible\.disabled !== true/);
  assert.match(environment, /\.wrong`[\s\S]*dispatchEvent\(new frame\.contentWindow\.Event\('input'[\s\S]*execute\.disabled === true/);
  assert.match(environment, /input\.value = input\.dataset\.exactTarget; input\.dispatchEvent\(new frame\.contentWindow\.Event\('input'[\s\S]*execute\.disabled === false[\s\S]*execute\.click\(\)/);
  assert.doesNotMatch(environment, /await wait\(180\)/);
  const codex = source.slice(source.indexOf('async function runInstalledCodexHandoffProfile'), source.indexOf('function validStudioSetupResult'));
  assert.match(codex, /refreshInstalledDashboardSnapshot/);
  assert.match(codex, /dispatchContextHandoff[\s\S]*installedOutboundRequestOffset[\s\S]*hostActionIdentity[\s\S]*__PX_INSTALLED_REQUESTS__[\s\S]*editorDisplacement[\s\S]*waitForOwnedWorkbenchDisplacementSettled[\s\S]*reopenPacifyDashboardFromOwnedUi\(workbench, frameHost, 22_000\)[\s\S]*waitForDurableHostActionResult/);
  assert.match(codex, /const cancelled = await dispatchContextHandoff[\s\S]*const prepared = await dispatchContextHandoff[\s\S]*cancelCodex/);
  assert.ok(codex.indexOf('claimCoordinationTask') < codex.indexOf('refreshInstalledDashboardSnapshot'));
  assert.ok(codex.indexOf('refreshInstalledDashboardSnapshot') < codex.indexOf("selector: '[data-action=\"continueCodex\"]'"));
});

test('focused host-boundary scheduling runs only its exact typed-host profile', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /PX_OPERATIONAL_HOST_BOUNDARY_ONLY === '1'/);
  assert.match(source, /hostBoundaryOnly \? 'host-boundary' : nativeDialogOnly \? 'native-dialog-boundary' : codexHandoffOnly \? 'codex-handoff' : errorIndicatorsOnly \? 'error-indicators' : lateCardRepairOnly \? 'late-card-repair' : builderOnly \? 'builder' : null/);
  assert.match(source, /hostBoundaryProfile = ownedReversibleConfigurationAuthority && \(!focusedProfileOnly \|\| hostBoundaryOnly\)/);
  assert.match(source, /studioChainAdmitted = ownedReversibleConfigurationAuthority && !configurationOnly && !knowledgeLifecycleOnly && !hostBoundaryOnly/);
  assert.match(source, /studioSetupProfile = studioChainAdmitted/);
  assert.match(source, /knowledgeLifecycleProfile = ownedReversibleConfigurationAuthority && !configurationOnly && !studioLifecycleOnly && !hostBoundaryOnly/);
  assert.match(source, /coordinationMemoryProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly/);
  assert.match(source, /enterpriseProfile = ownedReversibleConfigurationAuthority && \(!focusedProfileOnly \|\| nativeDialogOnly\)/);
});

test('focused native-dialog scheduling runs the exact confirmation profiles and dependent recovery checks', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /PX_OPERATIONAL_NATIVE_DIALOG_ONLY === '1'/);
  assert.match(source, /nativeDialogOnly \? 'native-dialog-boundary' : codexHandoffOnly \? 'codex-handoff' : errorIndicatorsOnly \? 'error-indicators' : lateCardRepairOnly \? 'late-card-repair' : builderOnly \? 'builder' : null/);
  assert.match(source, /reversibleConfigurationProfile = ownedReversibleConfigurationAuthority && \(!focusedProfileOnly \|\| configurationOnly\)/);
  assert.match(source, /enterpriseProfile = ownedReversibleConfigurationAuthority && \(!focusedProfileOnly \|\| nativeDialogOnly\)/);
  assert.match(source, /projectsProfile = ownedReversibleConfigurationAuthority && \(!focusedProfileOnly \|\| nativeDialogOnly\)/);
  assert.match(source, /knowledgeGraphProfile = ownedReversibleConfigurationAuthority && \(!focusedProfileOnly \|\| nativeDialogOnly\)/);
  assert.match(source, /cleanupProfile = ownedReversibleConfigurationAuthority && \(!focusedProfileOnly \|\| nativeDialogOnly\)/);
  assert.match(source, /pluginMutationProfile = ownedReversibleConfigurationAuthority && \(!focusedProfileOnly \|\| nativeDialogOnly\)/);
  const studioChainClause = source.slice(source.indexOf('const studioChainAdmitted ='), source.indexOf('\n', source.indexOf('const studioChainAdmitted =')));
  assert.match(studioChainClause, /!nativeDialogOnly/);
  for (const profile of ['studioSetupProfile', 'studioCandidateSaveProfile', 'studioLifecycleProfile', 'studioRevisionEditProfile', 'knowledgeLifecycleProfile', 'learningLifecycleProfile']) {
    const start = source.indexOf(`const ${profile} =`) >= 0 ? source.indexOf(`const ${profile} =`) : source.indexOf(`let ${profile} =`);
    const clause = source.slice(start, source.indexOf('\n', start));
    if (profile.startsWith('studio')) assert.match(clause, /studioChainAdmitted/, `${profile} must use the excluded Studio chain`);
    else assert.match(clause, /!nativeDialogOnly/, `${profile} must be excluded`);
  }
  for (const profile of ['coordinationMemoryProfile', 'hostBoundaryProfile', 'environmentLifecycleProfile', 'codexHandoffProfile', 'systemProjectionProfile', 'pluginReadProfile']) {
    const start = source.indexOf(`const ${profile} =`);
    const clause = source.slice(start, source.indexOf('\n', start));
    assert.match(clause, /focusedProfileOnly|hostBoundaryOnly/, `${profile} remains outside the native-dialog focus`);
  }
  assert.match(source, /installedControlProbe = dashboardProfileBlocker[\s\S]*: errorIndicatorsOnly/);
  assert.match(source, /for \(const kind of focusedProfileOnly && !builderOnly \? \[\] : \['agent', 'workflow'\]\)/);
});

test('portable memory stays non-canonical while exposing bounded metadata rows after restart', () => {
  const surface = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '46-observability-surfaces.js'), 'utf8');
  const controller = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '90-controller.js'), 'utf8');
  const profile = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(surface, /portable\.records/);
  assert.match(surface, /data-action="inspectMemoryRecord" data-portable-memory-id/);
  assert.match(controller, /portableMemoryId/);
  assert.match(controller, /PORTABLE · NON-CANONICAL/);
  assert.match(profile, /portable_memory_id/);
  assert.match(profile, /data-portable-memory-id/);
});

test('clipboard and export receipts precede non-authoritative notification UI', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'extension.js'), 'utf8');
  const copy = source.slice(source.indexOf("case 'copyText':"), source.indexOf("case 'exportRecordJson':"));
  const exported = source.slice(source.indexOf("case 'exportRecordJson':"), source.indexOf("case 'openExtensionsView':"));
  assert.ok(copy.indexOf("acknowledgeHostAction('completed'") < copy.indexOf('showInformationMessage('));
  assert.ok(exported.indexOf("acknowledgeHostAction('completed'") < exported.indexOf('showInformationMessage('));
});

test('host-boundary conditional controls use real bounded scenarios and reversible restoration', () => {
  const profile = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const surface = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '46-observability-surfaces.js'), 'utf8');
  const host = fs.readFileSync(path.join(__dirname, '..', 'src', 'extension.js'), 'utf8');
  assert.match(profile, /prepareInstalledHostBoundaryScenario/);
  assert.match(profile, /require\('hostQueries'\)\.operationalCard/);
  assert.match(profile, /canonical-memory/);
  assert.match(profile, /activity-enabled/);
  assert.match(profile, /restoreInstalledHostBoundaryScenario/);
  assert.doesNotMatch(surface, /const staleSection = staleOperations\.length \?/);
  const components = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '30-components.js'), 'utf8');
  assert.doesNotMatch(components, /\['Stale operation queue', 'Historical actor sessions'\]\.includes\(title\)/);
  assert.match(components, /title === 'Historical actor sessions'/);
  const reconcile = host.slice(host.indexOf("case 'reconcileStaleActivity':"), host.indexOf("case 'memoryQuery':"));
  assert.ok(reconcile.indexOf("acknowledgeHostAction('no-op'") < reconcile.indexOf('showInformationMessage('));
});

test('native host receipts survive exact webview reconstruction without disk persistence', () => {
  const walker = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const host = fs.readFileSync(path.join(__dirname, '..', 'src', 'extension.js'), 'utf8');
  const controller = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '90-controller.js'), 'utf8');
  assert.match(host, /activeRuntime\.lastHostActionResult = receipt/);
  assert.match(host, /activeRuntime\.lastHostActionRequest = \{/);
  assert.match(host, /currentSnapshot\.lastHostActionRequest = activeRuntime\.lastHostActionRequest \|\| null/);
  assert.match(host, /currentSnapshot\.lastHostActionResult = activeRuntime\.lastHostActionResult \|\| null/);
  assert.match(host, /durableHostActionTypes = new Set/);
  assert.match(host, /retainHostActionResult\('failed', \{ error: detail \}\)/);
  const failedRetention = host.slice(host.indexOf("const failedHostAction = hostActionTerminalRetained"), host.indexOf('const studioError = exactStudioVersionConflictError'));
  assert.ok(failedRetention.indexOf("retainHostActionResult('failed', { error: detail })") < failedRetention.indexOf('dashboardDisposed && isDisposedWebviewError(error)'), 'a failed displacing action must retain its current request before disposed-webview recovery returns');
  assert.match(host, /hostActionTerminalRetained \? null : retainHostActionResult/);
  assert.match(controller, /__PX_DURABLE_HOST_ACTION_RESULT__/);
  assert.match(controller, /__PX_DURABLE_HOST_ACTION_REQUEST__/);
  assert.match(walker, /lastHostActionResult/);
  assert.match(walker, /lastHostActionRequest/);
  assert.match(walker, /requestId/);
  assert.match(walker, /observedAt/);
  assert.doesNotMatch(host, /globalState\.update\([^\n]*lastHostActionResult/);
});

test('Codex handoff informational notifications cannot delay request-bound terminal receipts', () => {
  const host = fs.readFileSync(path.join(__dirname, '..', 'src', 'extension.js'), 'utf8');
  const handoff = host.slice(host.indexOf('async function continueWithCodex()'), host.indexOf('async function cancelCodexHandoff()'));
  const cancellation = host.slice(host.indexOf('async function cancelCodexHandoff()'), host.indexOf('async function pacifyChatHandler('));
  assert.match(handoff, /void vscode\.window\.showInformationMessage\('Governed context is ready\./);
  assert.doesNotMatch(handoff, /await vscode\.window\.showInformationMessage\('Governed context is ready\./);
  assert.match(cancellation, /void vscode\.window\.showInformationMessage\('No local Pacify-X Codex continuation/);
  assert.match(cancellation, /void vscode\.window\.showInformationMessage\('Cleared queued Codex continuation context/);
  assert.doesNotMatch(cancellation, /await vscode\.window\.showInformationMessage/);
});

test('plugin inventory refresh dispatch is atomic with exact route restoration', () => {
  const walker = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = walker.slice(walker.indexOf('async function runInstalledPluginMutationProfile('), walker.indexOf('function knowledgeLifecycleControlProbe('));
  const currentVersion = profile.slice(profile.indexOf('const currentVersion = async ('), profile.indexOf('const mutate = async spec =>'));
  assert.match(currentVersion, /controlDeadline = Date\.now\(\) \+ Math\.min\(timeoutMs, 20_000\)/);
  assert.match(currentVersion, /if \(\(!rendered \|\| !current\) && route\) route\.click\(\)/);
  assert.match(currentVersion, /refreshedRendered && refreshedRoute\?\.getAttribute\('aria-current'\) === 'page' && control/);
  assert.ok(currentVersion.indexOf('const responseOffset =') < currentVersion.indexOf('control.click()'));
  assert.match(currentVersion, /plugin-inventory-control-unavailable/);
});

test('host action correlation is exact-request-bound across reconstruction', () => {
  const requestId = 'request-current';
  assert.equal(installedHostActionRequestIdentity({ status: 'pending', action: 'openKnowledgeSource', requestId }, { action: 'openKnowledgeSource', previousRequestId: 'request-predecessor' }), requestId);
  assert.equal(installedHostActionRequestIdentity({ status: 'completed', action: 'openKnowledgeSource', requestId }, { action: 'openKnowledgeSource', previousRequestId: 'request-predecessor' }), requestId);
  assert.equal(installedHostActionRequestIdentity({ status: 'completed', action: 'openKnowledgeSource', requestId }, { action: 'openKnowledgeSource', previousRequestId: requestId }), '');
  assert.equal(installedHostActionRequestIdentity({ status: 'pending', action: 'openPunchSource', requestId }, { action: 'openKnowledgeSource', previousRequestId: 'request-predecessor' }), '');
  const expected = { requestId, operation: 'openFile', startedAt: Date.parse('2026-08-27T10:36:52.000Z') };
  assert.equal(installedHostActionReceiptMatches({ type: 'hostActionResult', requestId, operation: 'openFile', observedAt: '2026-08-27T10:36:52.001Z' }, expected), true);
  assert.equal(installedHostActionReceiptMatches({ type: 'hostActionResult', requestId: 'request-predecessor', operation: 'openFile', observedAt: '2026-08-27T10:36:53.000Z' }, expected), false);
  assert.equal(installedHostActionReceiptMatches({ type: 'hostActionResult', requestId, operation: 'openFile', observedAt: '2026-08-27T10:36:51.999Z' }, expected), false);
  const walker = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const durable = walker.slice(walker.indexOf('async function waitForDurableHostActionResult'), walker.indexOf('async function inspectHostActionReceiptFailure'));
  assert.match(durable, /value\.requestId === expected\.requestId/);
  assert.match(durable, /durableCandidates[\s\S]*\.filter\(value => value\?\.type === 'snapshot'\)[\s\S]*durableCandidates\.find\(matches\)/);
  assert.match(durable, /require\('hostQueries'\)\?\.refresh/);
  const controller = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '90-controller.js'), 'utf8');
  assert.match(controller, /define\('hostQueries'[\s\S]*refresh\(\)[\s\S]*type: 'refresh'/);
  assert.match(controller, /hostActionIdentity\(\)[\s\S]*state\.operation[\s\S]*requestId/);
  assert.match(walker, /require\('hostQueries'\)[\s\S]*hostActionIdentity\(\)/);
  const host = fs.readFileSync(path.join(__dirname, '..', 'src', 'extension.js'), 'utf8');
  const openPath = host.slice(host.indexOf("case 'openFile':"), host.indexOf("default: throw new Error('webview-message-type-unsupported')"));
  assert.match(openPath, /resolveAdmittedPath/);
  assert.match(openPath, /guard\.kind === 'directory'[\s\S]*revealInExplorer/);
  assert.ok(openPath.indexOf("acknowledgeHostAction('refused'") < openPath.indexOf("showWarningMessage('Pacify-X refused"));
  assert.doesNotMatch(walker, /PXDashboard\?\.require\('state'\)/);
});

test('Activity host-boundary admission waits for a coherent reversible generation', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const controller = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '90-controller.js'), 'utf8');
  const coherence = source.slice(source.indexOf('async function waitForInstalledActivityScenarioState'), source.indexOf('const INSTALLED_HOST_BOUNDARY_SPECS'));
  assert.match(coherence, /require\('hostQueries'\)\?\.activityScenario\(\)/);
  assert.match(coherence, /!current\.pending/);
  assert.match(coherence, /reconcile\.scrollIntoView\(\{ block: 'center', inline: 'nearest' \}\)/);
  assert.match(coherence, /reconcile_present: Boolean\(reconcile\)/);
  assert.match(coherence, /policyCoherent && \(!current\.policy_enabled \|\| current\.current_paused\)/);
  assert.match(coherence, /current\.reconcile_enabled === current\.expected_reconcile_enabled/);
  assert.match(coherence, /if \(!current\.pending && Date\.now\(\) >= nextRefreshAt\)/);
  assert.match(coherence, /data-action="activityRefresh"/);
  assert.match(coherence, /host-boundary-activity-state-not-coherent/);
  assert.match(controller, /function activityScenarioIdentity\(\)[\s\S]*state\.activityData \|\| state\.coordination\?\.activity/);
  assert.match(controller, /activityScenario\(\)[\s\S]*activityScenarioIdentity\(\)/);
  const scenario = source.slice(source.indexOf('async function prepareInstalledHostBoundaryScenario'), source.indexOf('function hostBoundaryControlProbe'));
  assert.match(scenario, /await waitForInstalledActivityScenarioState\(frameHost, timeoutMs\)/);
  assert.match(scenario, /restoreOwnedActivitySettings/);
});

test('installed surface navigation owns advanced expansion behavior', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const expansion = source.slice(source.indexOf('async function waitForAdvancedNavigationExpanded'), source.indexOf('async function navigateInstalledSurface'));
  const navigation = source.slice(source.indexOf('async function navigateInstalledSurface'), source.indexOf('async function runInstalledStudioSetupProfile'));
  assert.match(navigation, /\['knowledgeCore', 'runtimeCore'\]\.includes\(surface\)/);
  assert.match(navigation, /waitForAdvancedNavigationExpanded/);
  assert.match(expansion, /data-action="toggleAdvanced"/);
  assert.match(expansion, /aria-expanded/);
});

test('surface screenshots retain stable first-fold and proof-matrix deep-panel identities', () => {
  const { surfaceCaptureCandidates, surfaceCaptureFileStem } = require('../scripts/run-operational-ui-walk');
  const matrix = { controls: [
    { control_id: 'pxui.dashboard.action.refresh.hero', surface_id: 'dashboard', kind: 'action' },
    { control_id: 'pxui.dashboard.indicator.heroConnection', surface_id: 'dashboard', kind: 'indicator' },
    { control_id: 'pxui.projects.action.openProjectModuleMap', surface_id: 'projects', kind: 'action' },
    { control_id: 'pxui.agents.action.openStudioDraft.agent', surface_id: 'agents', kind: 'action' },
    { control_id: 'pxui.workflows.action.openStudioDraft.workflow', surface_id: 'workflows', kind: 'action' },
    { control_id: 'pxui.skills-tools.action.openStudioDraft.skill', surface_id: 'skills-tools', kind: 'action' }
  ] };
  const candidates = surfaceCaptureCandidates(matrix, 'dashboard');
  assert.deepEqual(candidates.map(candidate => candidate.control_id), [
    'pxui.dashboard.action.refresh.hero',
    'pxui.dashboard.indicator.heroConnection'
  ]);
  assert.equal(candidates[0].selector, '.hero-actions [data-action="refresh"]');
  assert.deepEqual(surfaceCaptureCandidates(matrix, 'agent-studio'), [{ control_id: 'pxui.agents.action.openStudioDraft.agent', selector: '[data-action="openStudioDraft"][data-kind="agent"]' }]);
  assert.deepEqual(surfaceCaptureCandidates(matrix, 'workflow-studio'), [{ control_id: 'pxui.workflows.action.openStudioDraft.workflow', selector: '[data-action="openStudioDraft"][data-kind="workflow"]' }]);
  assert.deepEqual(surfaceCaptureCandidates(matrix, 'skill-studio'), [{ control_id: 'pxui.skills-tools.action.openStudioDraft.skill', selector: '[data-action="openStudioDraft"][data-kind="skill"]' }]);
  assert.equal(surfaceCaptureFileStem('knowledgeGraph', 'first-fold'), 'knowledgeGraph--first-fold');
  assert.equal(surfaceCaptureFileStem('runtimeCore', 'deep-panel', 'pxui.runtime-core.action.refresh'), 'runtimeCore--deep-panel--pxui.runtime-core.action.refresh');

  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const capture = source.slice(source.indexOf('async function captureSurfaceViews'), source.indexOf('async function allPages'));
  assert.match(capture, /surface:\$\{surface\}:first-fold/);
  assert.match(source, /const installedRoute = INSTALLED_ROUTES\[surface\] \|\| surface/);
  assert.match(capture, /control:\$\{deepTarget\.control_id\}:deep-panel/);
  assert.match(capture, /document\.scrollingElement\.scrollTop = 0/);
  assert.match(capture, /scrollIntoView\(\{ block: 'center', inline: 'nearest' \}\)/);
  assert.match(source, /result\.captures = await captureSurfaceViews\(dashboard, proofMatrix, surface/);
  assert.match(source, /result\.screenshot = result\.captures\.first_fold\.screenshot/);
});

test('physical owner dynamically reacquires reconstructed webviews and causally skips dependent profiles', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /async function waitForOwnedWebview[\s\S]*let current = null[\s\S]*requireCurrent[\s\S]*evaluate: async[\s\S]*evaluateContent: async[\s\S]*elementHandle\(\)[\s\S]*handle\.contentFrame\(\)[\s\S]*handle\?\.dispose\(\)[\s\S]*reacquire: async[\s\S]*current = null[\s\S]*resolve[\s\S]*screenshot: async/);
  assert.match(source, /dashboardProfileBlocker = 'reversible-configuration'/);
  assert.match(source, /if \(!dashboardProfileBlocker && profileFailures\.length\) dashboardProfileBlocker = profileFailures\[0\]\.profile/);
  assert.match(source, /!dashboardProfileBlocker && profileDashboardBaseline/);
  assert.match(source, /terminal_disposition: 'blocked_profile_failure'/);
  assert.match(source, /skippedProfileResult\(profile, dashboardProfileBlocker\)/);
  assert.doesNotMatch(source, /throw new Error\(`profile-prerequisite-failed:/);
  assert.match(source, /innerText\(\{ timeout: 1_000 \}\)\.catch/);
  assert.match(source, /resolve\(Math\.min\(10_000, timeoutMs\)\)/);
  assert.match(source, /invokeCurrent[\s\S]*reacquirableOwnedFrameError[\s\S]*current = null/);
});

test('physical owner retries only exact pre-evaluation frame locator loss', () => {
  assert.equal(reacquirableOwnedFrameError(new Error('owned-webview-current-frame-unavailable')), true);
  assert.equal(reacquirableOwnedFrameError(new Error("locator.evaluate: Timeout 30000ms exceeded. waiting for locator('iframe.webview[src*=extensionId]').first().contentFrame().locator('iframe#active-frame')")), true);
  assert.equal(reacquirableOwnedFrameError(new Error('Execution context was destroyed after the callback started')), false);
  assert.equal(reacquirableOwnedFrameError(new Error('ordinary assertion failure')), false);
});

test('dynamic physical owner uses stable dashboard DOM identity after route navigation', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /let identityMode = null[\s\S]*hasDashboardOwnership[\s\S]*data-surface="dashboard"[\s\S]*data-surface="agents"/);
  assert.match(source, /identityMode = dashboardOwned \? 'dashboard-dom' : 'predicate'/);
  assert.match(source, /identityMode === 'dashboard-dom' \? dashboardOwned : await predicate\(text\)/);
});

test('installed control probe admits only local UI and read-only host effects', () => {
  assert.equal(eligibleInstalledControl({ surface_id: 'agents', evidence_mode: 'contained_ui_interaction', effect: 'local-view' }), true);
  assert.equal(eligibleInstalledControl({ surface_id: 'activity', evidence_mode: 'contained_host_interaction', effect: 'read' }), true);
  assert.equal(eligibleInstalledControl({ surface_id: 'activity', evidence_mode: 'contained_host_interaction', effect: 'configuration-write' }), false);
  assert.equal(eligibleInstalledControl({ surface_id: 'dashboard-control-plane', evidence_mode: 'isolated_host_command', effect: 'read' }), false);
  assert.equal(eligibleInstalledControl({ surface_id: 'sidebar', evidence_mode: 'contained_ui_interaction', effect: 'local-view' }), false);
});

test('installed action identity uses the exact action label and variants', () => {
  assert.deepEqual(installedActionIdentity({ control_id: 'pxui.activity.action.filterActivityCorrelation.row', label: 'filterActivityCorrelation.row' }), {
    action: 'filterActivityCorrelation', variants: ['row']
  });
  assert.deepEqual(installedActionIdentity({ control_id: 'pxui.diagnostics.action.dynamicRepair.refreshEnvironment', label: 'dynamicRepair.refreshEnvironment' }), {
    action: 'refreshEnvironment', variants: []
  });
});

test('R105 exact route and graph selectors do not depend on camel-case semantic guessing', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /'pxui\.dashboard-control-plane\.action\.navigate\.knowledgeCore': '\[data-surface="knowledgeCore"\]\.nav-item'/);
  assert.match(source, /'pxui\.dashboard-control-plane\.action\.navigate\.runtimeCore': '\[data-surface="runtimeCore"\]\.nav-item'/);
  assert.match(source, /'pxui\.knowledge-graph\.action\.graphDepth\.decrease': '\[data-action="graphDepth"\]\[data-delta="-1"\]'/);
  assert.match(source, /'pxui\.knowledge-graph\.action\.graphCommunity\.row': '\[data-action="graphCommunity"\]\[data-community-id\]'/);
});

test('installed Studio probe declares exact disposable prerequisites for state-dependent controls', () => {
  assert.deepEqual(installedStudioPrerequisites({ control_id: 'pxui.agent-studio.field.model.family' }), [
    { action: 'agentSelectNode', dataset: { agentKind: 'model' }, pick: 'first' }
  ]);
  assert.deepEqual(installedStudioPrerequisites({ control_id: 'pxui.agent-studio.action.agentRemoveBinding.row' }), [
    { action: 'agentAddBinding', dataset: {}, pick: 'first' }
  ]);
  assert.deepEqual(installedStudioPrerequisites({ control_id: 'pxui.workflow-studio.action.workflowMoveNode.later' }), [
    { action: 'workflowAddNode', dataset: { nodeTemplate: 'task' }, pick: 'first' },
    { action: 'workflowSelectNode', dataset: {}, pick: 'first' }
  ]);
  assert.deepEqual(installedStudioPrerequisites({ control_id: 'pxui.workflow-studio.action.workflowCancelConnection' }), [
    { action: 'workflowPortConnect', dataset: { direction: 'output' }, pick: 'first' }
  ]);
  assert.deepEqual(installedStudioPrerequisites({ control_id: 'pxui.skill-studio.field.packageFileText' }), [
    { action: 'skillAddFile', dataset: { fileKind: 'resource' }, pick: 'first' }
  ]);
  assert.deepEqual(installedStudioPrerequisites({ control_id: 'pxui.agent-studio.action.refreshHostModels' }), [
    { action: 'agentSelectNode', dataset: { agentKind: 'model' }, pick: 'first' }
  ]);
  assert.deepEqual(installedStudioPrerequisites({ control_id: 'pxui.agent-studio.indicator.workingGraphRequiresPythonCompile' }), [
    { action: 'agentAddTopologyNode', dataset: { agentKind: 'tools' }, pick: 'first' }
  ]);
  assert.deepEqual(installedStudioPrerequisites({ control_id: 'pxui.workflow-studio.indicator.pendingPortConnection' }), [
    { action: 'workflowPortConnect', dataset: { direction: 'output' }, pick: 'first' }
  ]);
  assert.deepEqual(installedStudioPrerequisites({ control_id: 'pxui.projects.field.identity' }), []);
});

test('installed Studio control scenarios preserve conditional owners instead of consuming them', () => {
  assert.equal(installedStudioControlScenario({ control_id: 'pxui.agent-studio.action.resumeWorkingStudioDraft' }), 'retained-working-draft');
  assert.equal(installedStudioControlScenario({ control_id: 'pxui.workflow-studio.action.discardWorkingStudioDraft' }), 'retained-working-draft');
  assert.equal(installedStudioControlScenario({ control_id: 'pxui.skill-studio.action.loadSkillPackageEditor' }), 'catalog-record');
  assert.equal(installedStudioControlScenario({ control_id: 'pxui.agent-studio.action.forkStudioCandidate' }), 'predecessor-editor');
  assert.equal(installedStudioControlScenario({ control_id: 'pxui.workflow-studio.action.acceptStudioVersionSuggestion' }), 'version-conflict');
  assert.equal(installedStudioControlScenario({ control_id: 'pxui.agent-studio.action.agentFit.minimap' }), null);
});

test('installed dynamic surfaces restore the exact persisted scope before each probe', () => {
  assert.deepEqual(installedSurfaceState({ surface_id: 'agents', control_id: 'pxui.agents.field.catalogSearch' }), { target: 'agents', scope: 'core' });
  assert.deepEqual(installedSurfaceState({ surface_id: 'agents', control_id: 'pxui.agents.action.enterpriseDoctor' }), { target: 'agents', scope: 'enterprise' });
  assert.deepEqual(installedSurfaceState({ surface_id: 'workflows', control_id: 'pxui.workflows.form.environmentLifecycle' }), { target: 'workflows', scope: 'environment' });
  assert.deepEqual(installedSurfaceState({ surface_id: 'workflows', control_id: 'pxui.workflows.field.catalogSearch' }), { target: 'workflows', scope: 'core' });
  assert.deepEqual(installedSurfaceState({ surface_id: 'skills-tools', control_id: 'pxui.skills-tools.action.compareSkillOriginal' }), { kind: 'preserved-skills' });
  assert.deepEqual(installedSurfaceState({ surface_id: 'skill-studio', control_id: 'pxui.skill-studio.field.identity' }), { kind: 'skills' });
  assert.equal(installedSurfaceState({ surface_id: 'dashboard', control_id: 'pxui.dashboard.indicator.counts' }), null);
});

test('R104 residual preparation uses settled routes, real graph readiness, and exact structural variants', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const direct = source.slice(source.indexOf('function installedDirectSelector'), source.indexOf('function installedStudioPrerequisites'));
  for (const selector of [
    '.hero-actions [data-action="refresh"]', '.cockpit-actions [data-action="refresh"]',
    '.graph-zoom-controls [data-action="graphFit"]', '.graph-minimap[data-action="graphFit"]',
    '[data-graph-direction]', '[data-graph-target]', '.relationship-counts'
  ]) assert.ok(direct.includes(selector));
  const prepare = source.slice(source.indexOf('async function prepareInstalledControl'), source.indexOf('async function revealInstalledControl'));
  assert.match(prepare, /navigateInstalledSurface\(frameHost, route, 20_000\)/);
  assert.match(prepare, /action\\\.navigate\\\.\(knowledgeCore\|runtimeCore\)[\s\S]*waitForAdvancedNavigationExpanded/);
  assert.match(prepare, /route === 'knowledgeGraph'[\s\S]*data-graph-canvas[\s\S]*graph-inline-error/);
  assert.match(prepare, /prepareInstalledCatalogModalAction\(frameHost, 'importCatalogDefinition'/);
  assert.match(prepare, /prepareInstalledCatalogModalAction\(frameHost, 'compareSkillOriginal', 'preserved-skills'\)/);
  assert.match(prepare, /environmentScope[^\n]+extensions[\s\S]*environmentExtensionDetail/);
  assert.match(prepare, /installed-graph-record-option-unavailable/);
  const conditional = source.slice(source.indexOf('async function seedInstalledConditionalScenario'), source.indexOf('async function recoverInstalledConditionalIndicator'));
  assert.match(conditional, /!spec\.controlId\.endsWith\('\.action\.catalogRetry'\)/);
  const exercise = source.slice(source.indexOf('async function exerciseInstalledControl'), source.indexOf('async function probeInstalledControls'));
  assert.match(exercise, /entrypoint: \['entrypoint', 'entrypoints'\]/);
  assert.match(exercise, /'test-link': \['test-link', 'test_links'\]/);
  assert.match(exercise, /variant === 'increase'[\s\S]*variant === 'decrease'/);
});

test('installed Studio preparation identity replays field-specific prerequisites', () => {
  assert.equal(installedPreparationIdentity({
    surface_id: 'agent-studio', control_id: 'pxui.agent-studio.field.model.family'
  }), 'agent-studio:pxui.agent-studio.field.model.family');
  assert.equal(installedPreparationIdentity({
    surface_id: 'workflow-studio', control_id: 'pxui.workflow-studio.field.edge.source_endpoint'
  }), 'workflow-studio:pxui.workflow-studio.field.edge.source_endpoint');
  assert.equal(installedPreparationIdentity({
    surface_id: 'skill-studio', control_id: 'pxui.skill-studio.field.packageFileText'
  }), 'skill-studio:pxui.skill-studio.field.packageFileText');
  assert.equal(installedPreparationIdentity({
    surface_id: 'projects', control_id: 'pxui.projects.field.identity'
  }), 'projects');
});

test('installed conditional scenarios isolate exact request-bound errors and pending states', () => {
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.agents.indicator.catalogError' }), { type: 'catalog-error', kind: 'agents' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.skills-tools.indicator.catalogPending' }), { type: 'catalog-pending', kind: 'skills' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.activity.indicator.queryError' }), { type: 'query-error', kind: 'activity' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.knowledge-graph.indicator.queryPending' }), { type: 'query-pending', kind: 'knowledge-graph' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.knowledge-core.indicator.controllerError' }), { type: 'knowledge-controller-error', kind: 'knowledge' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.activity.action.activityRefresh' }), { type: 'read-action-failure', controlId: 'pxui.activity.action.activityRefresh', operation: 'activityQuery', resultType: 'activityResult' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.agents.action.catalogNext' }), { type: 'read-action-failure', controlId: 'pxui.agents.action.catalogNext', operation: 'catalogQuery', resultType: 'catalogResult', kind: 'agents' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.knowledge-graph.action.graphOverview' }), { type: 'read-action-failure', controlId: 'pxui.knowledge-graph.action.graphOverview', operation: 'graphQuery', resultType: 'graphResult' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.knowledge-graph.action.graphFilterEdgeBundle' }), { type: 'read-action-failure', controlId: 'pxui.knowledge-graph.action.graphFilterEdgeBundle', operation: 'graphQuery', resultType: 'graphResult' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.knowledge-graph.action.graphClearEdgeBundle' }), { type: 'read-action-failure', controlId: 'pxui.knowledge-graph.action.graphClearEdgeBundle', operation: 'graphQuery', resultType: 'graphResult' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.dashboard.action.refresh.hero' }), { type: 'read-action-failure', controlId: 'pxui.dashboard.action.refresh.hero', operation: 'refresh', resultType: 'snapshot' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.knowledge-graph.action.graphCommunity.row' }), { type: 'read-action-failure', controlId: 'pxui.knowledge-graph.action.graphCommunity.row', operation: 'graphQuery', resultType: 'graphResult' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.workflows.action.environmentExtensionDetail.row' }), { type: 'read-action-failure', controlId: 'pxui.workflows.action.environmentExtensionDetail.row', operation: 'environmentExtensionDetail', resultType: 'environmentExtensionDetail' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.agents.action.catalogRetry' }), { type: 'read-action-failure', controlId: 'pxui.agents.action.catalogRetry', operation: 'catalogQuery', resultType: 'catalogResult', kind: 'agents' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.workflows.action.enterpriseDoctor' }), { type: 'read-action-failure', controlId: 'pxui.workflows.action.enterpriseDoctor', operation: 'enterpriseDoctor', resultType: 'enterpriseResult' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.agent-studio.action.refreshHostModels' }), { type: 'read-action-failure', controlId: 'pxui.agent-studio.action.refreshHostModels', operation: 'listHostModels', resultType: 'hostModelCatalog', kind: 'agent', modalScenario: 'studio-draft' });
  assert.deepEqual(installedConditionalScenario({ control_id: 'pxui.skill-studio.action.loadSkillPackageEditor' }), { type: 'read-action-failure', controlId: 'pxui.skill-studio.action.loadSkillPackageEditor', operation: 'loadSkillPackageEditor', resultType: 'skillPackageEditorResult', kind: 'skill', modalScenario: 'catalog-record' });
  assert.equal(installedConditionalScenario({ control_id: 'pxui.dashboard.indicator.counts' }), null);
  assert.equal(installedPreparationIdentity({ surface_id: 'activity', control_id: 'pxui.activity.indicator.queryError' }), 'activity:pxui.activity.indicator.queryError');
  assert.notEqual(
    installedPreparationIdentity({ surface_id: 'agents', control_id: 'pxui.agents.indicator.catalogError' }),
    installedPreparationIdentity({ surface_id: 'agents', control_id: 'pxui.agents.indicator.catalogPending' })
  );
});

test('installed exact action selectors and editor gestures retain reversible failure evidence', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const start = source.indexOf('async function exerciseInstalledControl');
  const exercise = source.slice(start, source.indexOf('async function probeInstalledControls', start));
  assert.match(exercise, /const direct = item\.directSelector \? document\.querySelector\(item\.directSelector\) : null/);
  assert.match(exercise, /target\.addEventListener\('keydown', rejectOwnedInput, \{ capture: true, once: true \}\)/);
  assert.match(exercise, /event\.stopImmediatePropagation\(\)/);
  assert.match(exercise, /state\.failureObserved = rejected && fingerprint\(\) === beforeFailure/);
  assert.match(exercise, /state\.recoveryObserved = state\.failureObserved && state\.restored/);
});

test('conditional error indicators bind exact normal recovery actions and result types', () => {
  assert.deepEqual(installedConditionalRecoverySpec({ kind: 'indicator', control_id: 'pxui.agents.indicator.catalogError' }), { action: 'catalogRetry', actionKind: 'agents', responseType: 'catalogResult' });
  assert.deepEqual(installedConditionalRecoverySpec({ kind: 'indicator', control_id: 'pxui.activity.indicator.queryError' }), { action: 'activityRefresh', responseType: 'activityResult' });
  assert.deepEqual(installedConditionalRecoverySpec({ kind: 'indicator', control_id: 'pxui.memory.indicator.queryError' }), { action: 'memoryRefresh', responseType: 'memoryResult' });
  assert.deepEqual(installedConditionalRecoverySpec({ kind: 'indicator', control_id: 'pxui.knowledge-graph.indicator.queryError' }), { action: 'runGraphSearch', responseType: 'graphResult' });
  assert.deepEqual(installedConditionalRecoverySpec({ kind: 'indicator', control_id: 'pxui.knowledge-core.indicator.controllerError' }), { action: 'knowledgeRefresh', responseType: 'studioOperationResult', responseKind: 'knowledge', operation: 'browse' });
  assert.equal(installedConditionalRecoverySpec({ kind: 'action', control_id: 'pxui.agents.action.catalogRetry' }), null);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /pxui\.memory\.indicator\.queryError': '\.surface-memory \.memory-errors\[role="alert"\]:has\(\[data-action="memoryRefresh"\]\)'/);
  assert.match(source, /pxui\.activity\.indicator\.queryError': '\.surface-activity \.memory-errors\[role="alert"\]:has\(\[data-action="activityRefresh"\]\)'/);
  assert.match(source, /pxui\.knowledge-core\.indicator\.controllerError': '\.surface-knowledgeCore \.memory-errors\[role="alert"\]:has\(\[data-action="knowledgeRefresh"\]\)'/);
  const seed = source.slice(source.indexOf('async function seedInstalledConditionalScenario'), source.indexOf('async function recoverInstalledConditionalIndicator'));
  assert.match(seed, /control\.kind === 'indicator'[\s\S]*installedDirectSelector\(control\)[\s\S]*installed-conditional-control-settlement-timeout/);
  assert.match(seed, /state\.graphRequestId = requestId[\s\S]*state\.memoryRequestId = requestId[\s\S]*state\.activityRequestId = requestId[\s\S]*state\.catalogRequests\[kind\]\.requestId = requestId/);
  assert.match(seed, /operationError', operation, kind, requestId, error/);
  assert.match(seed, /spec\.kind === 'activity'[\s\S]*state\.activityRequestId = requestId[\s\S]*state\.activityData = [\s\S]*error[\s\S]*render\(\)/);
  const probe = source.slice(source.indexOf('async function probeInstalledControls'), source.indexOf('function installedSidebarSelector'));
  assert.match(probe, /conditionalScenario = installedConditionalScenario\(control\)[\s\S]*probe\.failureObserved = true[\s\S]*recoverInstalledConditionalIndicator/);
});

test('installed conditional recovery requires an exact result and disappearance before attribution', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const start = source.indexOf('async function recoverInstalledConditionalIndicator');
  const recovery = source.slice(start, source.indexOf('async function seedInstalledStudioPrerequisites', start));
  assert.ok(start >= 0);
  assert.match(recovery, /value\?\.type === spec\.responseType/);
  assert.match(recovery, /!spec\.actionKind \|\| element\.dataset\.kind === spec\.actionKind/);
  assert.match(recovery, /!spec\.responseKind \|\| value\?\.kind === spec\.responseKind/);
  assert.match(recovery, /lastState\.responseMatched && !lastState\.errorVisible/);
  assert.match(recovery, /exact-error-recovery-timeout/);
  assert.match(source, /spec\.local \? 80 : 15_000/);
});

test('the seventeen R54 read-only failure gaps consume isolated typed failures before recovered actions', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const scenarios = source.slice(source.indexOf('function installedConditionalScenario'), source.indexOf('async function seedInstalledConditionalScenario'));
  const expected = [
    'pxui.activity.action.activityRefresh', 'pxui.agents.action.catalogNext', 'pxui.agents.action.catalogPrevious',
    'pxui.assurance.action.enterpriseDoctor', 'pxui.diagnostics.action.inspectOperationalInventory', 'pxui.diagnostics.action.inspectPunchCard.row',
    'pxui.diagnostics.action.operationalCardsNext', 'pxui.diagnostics.action.operationalCardsPrevious', 'pxui.diagnostics.action.queryOperationalCards',
    'pxui.knowledge-graph.action.focusGraphNode.row', 'pxui.knowledge-graph.action.graphOpenNeighborhood', 'pxui.knowledge-graph.action.graphOverview',
    'pxui.knowledge-graph.action.graphView.capabilities', 'pxui.knowledge-graph.action.graphView.repository', 'pxui.projects.action.openRepositoryGraph',
    'pxui.workflows.action.catalogNext', 'pxui.workflows.action.catalogPrevious'
  ];
  assert.equal(expected.filter(id => scenarios.includes(`'${id}'`)).length, 17);
  const seed = source.slice(source.indexOf('async function seedInstalledConditionalScenario'), source.indexOf('async function seedInstalledStudioPrerequisites'));
  assert.match(seed, /__PX_INSTALLED_FAILURE_SCENARIOS__/);
  assert.match(seed, /sendError\(spec\.operation, spec\.kind \|\| null/);
  const exercise = source.slice(source.indexOf('async function exerciseInstalledControl'), source.indexOf('async function probeInstalledControls'));
  assert.match(exercise, /delete inner\.__PX_INSTALLED_FAILURE_SCENARIOS__\[item\.controlId\]/);
  assert.match(exercise, /before\.recoveryObserved = before\.failureObserved && before\.acknowledged/);
  assert.match(exercise, /matchingResponseObserved/);
});

test('R100 read-only residuals bind failure scenarios to their exact host response contracts', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const scenarios = source.slice(source.indexOf('function installedConditionalScenario'), source.indexOf('function installedConditionalRecoverySpec'));
  for (const [id, operation, resultType] of [
    ['pxui.agents.action.openStudioRuns.agent', 'studioOperation', 'studioOperationResult'],
    ['pxui.workflows.action.openStudioRuns.workflow', 'studioOperation', 'studioOperationResult'],
    ['pxui.knowledge-graph.action.runGraphSearch', 'graphQuery', 'graphResult'],
    ['pxui.memory.action.memoryRefresh', 'memoryQuery', 'memoryResult'],
    ['pxui.plugins.action.environmentExtensionDetail.row', 'environmentExtensionDetail', 'environmentExtensionDetail'],
    ['pxui.plugins.action.refreshEnvironment', 'refreshEnvironment', 'environmentInventory']
  ]) {
    const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    assert.match(scenarios, new RegExp(`'${escaped}': \\{ operation: '${operation}', resultType: '${resultType}'`));
  }
  assert.match(scenarios, /openStudioRuns\.agent'[\s\S]*kind: 'agent'/);
  assert.match(scenarios, /openStudioRuns\.workflow'[\s\S]*kind: 'workflow'/);
});

test('R100 modal-contained read failures reconstruct the exact owner before recovery', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const restoreStart = source.indexOf('async function restoreInstalledModalAfterConditionalFailure');
  const restore = source.slice(restoreStart, source.indexOf('async function prepareInstalledControl', restoreStart));
  const prepareStart = source.indexOf('async function prepareInstalledControl');
  const prepare = source.slice(prepareStart, source.indexOf('async function revealInstalledControl', prepareStart));
  assert.ok(restoreStart >= 0);
  assert.match(restore, /scenario\.modalScenario === 'catalog-record'[\s\S]*prepareInstalledStudioCatalogRecord\(frameHost, kind, false\)/);
  assert.match(restore, /scenario\.modalScenario === 'studio-draft'[\s\S]*prepareInstalledStudioDraftModal\(frameHost, kind, control\)/);
  assert.match(prepare, /await seedInstalledConditionalScenario\(frameHost, control\);[\s\S]*await restoreInstalledModalAfterConditionalFailure\(frameHost, control, kind, installedConditionalScenario\(control\)\)/);
  assert.match(prepare, /const conditionalScenario = installedConditionalScenario\(control\);[\s\S]*await seedInstalledConditionalScenario\(frameHost, control\);[\s\S]*await restoreInstalledModalAfterConditionalFailure\(frameHost, control, kind, conditionalScenario\)/);
  assert.match(source, /delete inner\.__PX_INSTALLED_FAILURE_SCENARIOS__\[item\.controlId\]/);
  assert.match(source, /after\.matchingResponseObserved/);
});

test('graph edge-bundle controls receive exact failure mappings and clear-state preparation', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /graphFilterEdgeBundle': \{ operation: 'graphQuery', resultType: 'graphResult' \}/);
  assert.match(source, /graphClearEdgeBundle': \{ operation: 'graphQuery', resultType: 'graphResult' \}/);
  assert.match(source, /control\.control_id === 'pxui\.knowledge-graph\.action\.graphClearEdgeBundle'[\s\S]*graphFilterEdgeBundle[\s\S]*waitForInstalledResponse[\s\S]*graphClearEdgeBundle/);
  assert.match(source, /installed-conditional-recovery-failed:/);
});

test('installed sidebar probe resolves and exercises exact physical controls', async () => {
  assert.equal(eligibleInstalledSidebarControl({ surface_id: 'sidebar', evidence_mode: 'contained_sidebar_interaction' }), true);
  assert.equal(eligibleInstalledSidebarControl({ surface_id: 'sidebar', evidence_mode: 'live_state_observation' }), true);
  assert.equal(eligibleInstalledSidebarControl({ surface_id: 'sidebar', evidence_mode: 'contained_restart' }), false);
  assert.equal(eligibleInstalledSidebarControl({ surface_id: 'dashboard', evidence_mode: 'contained_sidebar_interaction' }), false);
  assert.equal(installedSidebarSelector({ kind: 'action', control_id: 'pxui.sidebar.action.openEntity.agent' }), '[data-entity-type="agent"]');
  assert.equal(installedSidebarSelector({ kind: 'indicator', control_id: 'pxui.sidebar.indicator.providerBudget' }), '#providers');
  const policy = Object.fromEntries(STAGES.map(stage => [stage,
    ['open_load', 'display', 'user_edit_action', 'input_validation', 'result_acknowledgement'].includes(stage) ? 'required' : 'not_applicable_with_evidence']));
  const frameHost = {
    evaluate: async (_fn, spec) => ({
      loaded: true, visible: true, attempted: spec.kind === 'action',
      validationObserved: spec.kind === 'action', acknowledged: true, details: {}, errors: []
    })
  };
  const result = await probeInstalledSidebarControls(frameHost, { controls: [
    { control_id: 'pxui.sidebar.action.open-control-plane', surface_id: 'sidebar', kind: 'action', evidence_mode: 'contained_sidebar_interaction', effect: 'host-ui-or-read', stage_policy: policy },
    { control_id: 'pxui.sidebar.indicator.providerBudget', surface_id: 'sidebar', kind: 'indicator', evidence_mode: 'live_state_observation', effect: 'read', stage_policy: { ...policy, user_edit_action: 'not_applicable_with_evidence', input_validation: 'not_applicable_with_evidence' } }
  ] }, []);
  assert.equal(result.eligible_control_count, 2);
  assert.equal(result.records[0].attempted, true);
  assert.equal(result.records[0].interaction_chain.result_acknowledgement.state, 'present');
  assert.equal(result.records[1].rendered, true);
  assert.equal(result.records[1].attempted, false);
});

test('R100 sidebar native handoffs bind exact requests, rejection, dashboard identity, and replay', () => {
  assert.deepEqual(installedSidebarHandoffSpec({ control_id: 'pxui.sidebar.action.open-control-plane' }), { requestType: 'openControlPlane' });
  assert.deepEqual(installedSidebarHandoffSpec({ control_id: 'pxui.sidebar.action.openEntity.plan' }), { requestType: 'openEntity', entityType: 'plan' });
  assert.deepEqual(installedSidebarHandoffSpec({ control_id: 'pxui.sidebar.action.openEntity.provider' }), { requestType: 'openEntity', entityType: 'provider' });
  assert.deepEqual(installedSidebarHandoffSpec({ control_id: 'pxui.sidebar.action.openEntity.task' }), { requestType: 'openEntity', entityType: 'task' });
  assert.deepEqual(installedSidebarHandoffSpec({ control_id: 'pxui.sidebar.action.openPlanFromPunch' }), { requestType: 'openPlanFromPunch' });
  assert.equal(installedSidebarHandoffSpec({ control_id: 'pxui.sidebar.action.toggleWave.row' }), null);
  assert.equal(installedSidebarHandoffRequestMatches({ type: 'openEntity', entityType: 'task', entityId: 'task-1' }, { type: 'openEntity', entityType: 'task', entityId: 'task-1' }), true);
  assert.equal(installedSidebarHandoffRequestMatches({ type: 'openEntity', entityType: 'plan', entityId: 'task-1' }, { type: 'openEntity', entityType: 'task', entityId: 'task-1' }), false);
  assert.equal(installedSidebarHandoffRequestMatches({ type: 'openPlanFromPunch', planId: 'plan-1' }, { type: 'openPlanFromPunch', planId: 'plan-1' }), true);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const start = source.indexOf('async function probeInstalledSidebarHandoff');
  const profile = source.slice(start, source.indexOf('async function probeInstalledSidebarControls', start));
  assert.match(profile, /event\.preventDefault\(\); event\.stopImmediatePropagation\(\)/);
  assert.match(profile, /const rejected = inner\.__PX_INSTALLED_SIDEBAR_REQUESTS__\.length === offset/);
  assert.match(profile, /waitForInstalledSidebarHandoffRequest\(frameHost, attempt\.offset, attempt\.expected/);
  assert.match(profile, /waitForInstalledSidebarDashboardIdentity\(dashboard, attempt\.expected/);
  assert.match(profile, /restartInstalledDashboardWebview\(dashboard, timeoutMs\)/);
  assert.match(profile, /waitForInstalledSidebarHandoffRequest\(frameHost, replayOffset, attempt\.expected/);
  assert.match(source, /prepareInstalledSidebarHandoffTarget[\s\S]*fixture\.dataset\.pxOwnedHandoffFixture[\s\S]*px-owned-\$\{spec\.handoff\.entityType\}-handoff/);
  assert.match(profile, /finally[\s\S]*removeInstalledSidebarHandoffTarget/);
  assert.match(source, /const dashboardVisible = Boolean\(document\?\.querySelector\('\[data-surface="dashboard"\]'\)/);
  const records = source.slice(source.indexOf('async function probeInstalledSidebarControls'), source.indexOf('async function safeScreenshot'));
  assert.match(records, /frameHost\.reacquire\(10_000\)/);
  assert.match(records, /\['authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting'\]/);
  assert.match(records, /\['persistence', 'reload_reopen'\]/);
});

test('R100 toggleWave action receives its physical durable sidebar-state evidence', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const start = source.indexOf('function sidebarStateControlProbe');
  const profile = source.slice(start, source.indexOf('function sidebarReconstructionIdentity', start));
  assert.match(profile, /'pxui\.sidebar\.action\.toggleWave\.row', 'pxui\.sidebar\.action\.retry', 'pxui\.sidebar\.indicator\.connection'/);
  assert.match(profile, /observation\.webview_restarted === true && observation\.exact_reconstruction === true/);
  assert.match(profile, /fault && observation\.preference_restored/);
});

test('sidebar instrumentation journals only structurally valid authoritative snapshots', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const start = source.indexOf('async function instrumentInstalledSidebarState');
  const profile = source.slice(start, source.indexOf('async function runInstalledSidebarConditionalStateScenario', start));
  assert.match(profile, /const projection = event\.data\?\.projection/);
  assert.match(profile, /!projection \|\| typeof projection !== 'object' \|\| !Array\.isArray\(projection\.waves\)/);
  assert.match(profile, /!projection\.ui \|\| typeof projection\.ui !== 'object'/);
  assert.match(profile, /__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__\.push\(structuredClone\(event\.data\)\)/);
});

test('installed workbench command coverage admits bounded read-only and reversible UI commands', () => {
  assert.deepEqual(installedWorkbenchCommandSpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.openDashboard' }), {
    title: 'Pacify-X: Open Control Plane', outcome: 'dashboard'
  });
  assert.equal(installedWorkbenchCommandSpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.refreshDashboard' }).outcome, 'dashboard-refresh');
  assert.equal(installedWorkbenchCommandSpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.openSettings' }).outcome, 'settings');
  assert.equal(installedWorkbenchCommandSpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.openCleanupManager' }).outcome, 'cleanup-manager');
  assert.equal(installedWorkbenchCommandSpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.createContextSnapshot' }).outcome, 'context-snapshot');
  assert.equal(installedWorkbenchCommandSpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.rotateStudioApprovalIdentity' }), null);
  assert.equal(installedWorkbenchCommandSpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.refreshProviderStatus' }).outcome, 'dashboard-refresh');
  assert.equal(installedWorkbenchCommandSpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.cancelCodex' }).outcome, 'codex-cancel');
  assert.equal(installedWorkbenchAuthorityBoundarySpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.validateControlPlane' }).policy, 'reject-before-dispatch');
  assert.equal(installedWorkbenchAuthorityBoundarySpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.refreshEnvironment' }).policy, 'reject-before-dispatch');
  assert.equal(installedWorkbenchAuthorityBoundarySpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.rotateStudioApprovalIdentity' }).policy, 'reject-before-dispatch');
  assert.equal(installedWorkbenchAuthorityBoundarySpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.refreshOllama' }).policy, 'reject-before-dispatch');
  assert.equal(installedWorkbenchAuthorityBoundarySpec({ control_id: 'pxui.dashboard-control-plane.command.pacifyX.continueWithCodex' }), null);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function probeInstalledWorkbenchCommands'), source.indexOf('async function inspectSurface'));
  assert.match(profile, /spec\.outcome === 'settings'[\s\S]*waitForOwnedSettingsEditor\(workbench, 10_000\)[\s\S]*reopenPacifyDashboardFromOwnedUi\(workbench, frameHost\)/);
  assert.match(profile, /spec\.outcome === 'dashboard-refresh'[\s\S]*waitForInstalledSidebarDashboardIdentity\(frameHost, \{\}, 10_000\)[\s\S]*waitForInstalledSourceIdentity\(frameHost, 10_000\)[\s\S]*identity\.state === 'verified'/);
  assert.match(profile, /spec\.outcome === 'context-snapshot'[\s\S]*schema_version[\s\S]*reopenPacifyDashboardFromOwnedUi/);
  assert.match(profile, /spec\.outcome === 'cleanup-manager'[\s\S]*cleanupSelectAll/);
  assert.match(profile, /spec\.outcome === 'codex-cancel'[\s\S]*No local Pacify-X Codex continuation was queued/);
  assert.doesNotMatch(profile, /refreshEnvironment[^\n]*policy: 'cancel-modal'|rotateStudioApprovalIdentity[^\n]*policy: 'cancel-modal'/);
  assert.match(source, /const NATIVE_WORKBENCH_DIALOG_SELECTOR = '[^']*\.dialog-container:visible/);
  assert.match(source, /cancelOwnedWorkbenchModal[\s\S]*workbench\.locator\(NATIVE_WORKBENCH_DIALOG_SELECTOR\)/);
  assert.match(profile, /authority_skipped: Boolean\(boundary && probe\.failureObserved && probe\.recoveryObserved\)/);
  assert.match(profile, /\['authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting'\]/);
  assert.doesNotMatch(profile, /spec\.outcome === 'settings'[\s\S]*executeWorkbenchCommand\(workbench, INSTALLED_SAFE_WORKBENCH_COMMANDS\['pxui\.dashboard-control-plane\.command\.pacifyX\.openDashboard'\]/);
});

test('Codex handoff profile owns the exact contributed command without contradictory authority rejection', () => {
  const commandId = 'pxui.dashboard-control-plane.command.pacifyX.continueWithCodex';
  const controls = [
    { control_id: commandId, surface_id: 'dashboard-control-plane', kind: 'command', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['progress_reporting', 'persistence', 'reload_reopen', 'recovery_rollback'].includes(stage) ? 'not_applicable' : 'required'])) },
    { control_id: 'pxui.runtime-core.action.continueCodex', surface_id: 'runtime-core', kind: 'action', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['progress_reporting', 'persistence', 'reload_reopen', 'recovery_rollback'].includes(stage) ? 'not_applicable' : 'required'])) },
    { control_id: 'pxui.runtime-core.action.cancelCodex', surface_id: 'runtime-core', kind: 'action', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['progress_reporting', 'persistence', 'reload_reopen', 'recovery_rollback'].includes(stage) ? 'not_applicable' : 'required'])) }
  ];
  const probe = codexHandoffControlProbe({ controls }, {
    rendered: true,
    attempted: true,
    command_cancelled_without_context: true,
    command_prepared: true,
    command_cleared: true,
    cancelled_without_context: true,
    prepared: true,
    cleared: true,
    claim_released: true,
    webview_restarted: true,
    errors: []
  });

  assert.equal(installedWorkbenchAuthorityBoundarySpec({ control_id: commandId }), null);
  assert.equal(probe.eligible_control_count, 3);
  const command = probe.records.find(record => record.control_id === commandId);
  assert.ok(command);
  assert.equal(command.evidence_mode, 'owned_codex_context_handoff');
  assert.equal(command.attempted, true);
  for (const stage of STAGES) {
    assert.ok(['present', 'not_applicable'].includes(command.interaction_chain[stage].state), `${stage} must be complete`);
    assert.ok(command.interaction_chain[stage].evidence.length > 0, `${stage} must be evidence-bound`);
  }
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledCodexHandoffProfile'), source.indexOf('function validStudioSetupResult'));
  assert.match(profile, /executeWorkbenchCommand\(workbench, commandTitle, \{ acceptedPrompt: 'Prepare governed context for the current Codex host' \}\)[\s\S]*command_cancelled_without_context = true/);
  assert.match(profile, /executeWorkbenchCommand\(workbench, commandTitle, \{ acceptedPrompt: 'Prepare governed context for the current Codex host' \}\)[\s\S]*Owned contributed-command Codex context handoff verification\.[\s\S]*command_prepared/);
  assert.match(profile, /command_prepared[\s\S]*reopenPacifyDashboardFromOwnedUi\(workbench, frameHost\)[\s\S]*command_cleared/);
  assert.match(profile, /executeWorkbenchCommand\(workbench, commandTitle, \{ acceptedPrompt: 'Prepare governed context for the current Codex host' \}\)/);
  const commandHelper = source.slice(source.indexOf('async function executeWorkbenchCommand'), source.indexOf('function ownedWorkbenchReloadIdentity'));
  assert.match(commandHelper, /options\.acceptedPrompt[\s\S]*quick-input-transition[\s\S]*executed: true/);
});

test('focused Codex handoff scheduling excludes every unrelated stateful profile', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /PX_OPERATIONAL_CODEX_HANDOFF_ONLY === '1'/);
  assert.match(source, /codexHandoffOnly \? 'codex-handoff' : errorIndicatorsOnly \? 'error-indicators' : lateCardRepairOnly \? 'late-card-repair' : builderOnly \? 'builder' : null/);
  assert.match(source, /const codexHandoffProfile = ownedReversibleConfigurationAuthority && \(!focusedProfileOnly \|\| codexHandoffOnly\)/);
  const schedulingStart = source.indexOf('const reversibleConfigurationProfile');
  const scheduling = source.slice(schedulingStart, source.indexOf('const engineOutageProfile', schedulingStart));
  assert.match(scheduling, /const studioSetupProfile =[\s\S]*!codexHandoffOnly/);
  assert.match(scheduling, /const knowledgeLifecycleProfile =[\s\S]*!codexHandoffOnly/);
  assert.match(scheduling, /const hostBoundaryProfile =[\s\S]*\(!focusedProfileOnly \|\| hostBoundaryOnly\)/);
  assert.match(scheduling, /const enterpriseProfile =[\s\S]*\(!focusedProfileOnly \|\| nativeDialogOnly\)/);
  assert.match(scheduling, /const environmentLifecycleProfile =[\s\S]*!focusedProfileOnly/);
});

test('focused error-indicator scheduling probes exactly two identities and excludes unrelated stateful profiles', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /PX_OPERATIONAL_ERROR_INDICATORS_ONLY === '1'/);
  assert.match(source, /errorIndicatorsOnly \? 'error-indicators' : lateCardRepairOnly \? 'late-card-repair' : builderOnly \? 'builder' : null/);
  const identityBlock = source.slice(source.indexOf('const ERROR_INDICATOR_CONTROL_IDS'), source.indexOf('const focusedProfile'));
  assert.match(identityBlock, /pxui\.memory\.indicator\.queryError/);
  assert.match(identityBlock, /pxui\.knowledge-core\.indicator\.controllerError/);
  assert.equal((identityBlock.match(/pxui\./g) || []).length, 2);
  const probe = source.slice(source.indexOf('async function probeInstalledControls'), source.indexOf('function installedSidebarSelector'));
  assert.match(probe, /controlIds = null/);
  assert.match(probe, /!controlIds \|\| controlIds\.has\(control\.control_id\)/);
  const schedulingStart = source.indexOf('const reversibleConfigurationProfile');
  const scheduling = source.slice(schedulingStart, source.indexOf('const engineOutageProfile', schedulingStart));
  assert.match(scheduling, /installedControlProbe = dashboardProfileBlocker[\s\S]*: errorIndicatorsOnly[\s\S]*timedProfile\('error-indicators'[\s\S]*ERROR_INDICATOR_CONTROL_IDS/);
  const studioChainClause = scheduling.slice(scheduling.indexOf('const studioChainAdmitted ='), scheduling.indexOf('\n', scheduling.indexOf('const studioChainAdmitted =')));
  assert.match(studioChainClause, /!errorIndicatorsOnly/);
  for (const profile of ['studioSetupProfile', 'studioCandidateSaveProfile', 'studioLifecycleProfile', 'studioRevisionEditProfile', 'knowledgeLifecycleProfile', 'learningLifecycleProfile']) {
    const start = scheduling.indexOf(`const ${profile} =`) >= 0 ? scheduling.indexOf(`const ${profile} =`) : scheduling.indexOf(`let ${profile} =`);
    const clause = scheduling.slice(start, scheduling.indexOf('\n', start));
    if (profile.startsWith('studio')) assert.match(clause, /studioChainAdmitted/, `${profile} must use the excluded Studio chain`);
    else assert.match(clause, /!errorIndicatorsOnly/, `${profile} must be excluded`);
  }
  assert.match(scheduling, /const hostBoundaryProfile =[\s\S]*\(!focusedProfileOnly \|\| hostBoundaryOnly\)/);
  assert.match(scheduling, /const codexHandoffProfile =[\s\S]*\(!focusedProfileOnly \|\| codexHandoffOnly\)/);
  assert.match(source, /full_operational_completion_claimed: focusedProfileOnly \? false/);
});

test('focused Codex handoff opens its disposable plan from one settled visible control identity', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const helper = source.slice(source.indexOf('async function openInstalledSettledControlForm'), source.indexOf('async function runInstalledCodexHandoffProfile'));
  const profile = source.slice(source.indexOf('async function runInstalledCodexHandoffProfile'), source.indexOf('function validStudioSetupResult'));
  assert.match(helper, /control\.isConnected[\s\S]*control\.click\(\)[\s\S]*submit_visible/);
  assert.match(helper, /installed-settled-control-form-timeout/);
  assert.match(profile, /openInstalledSettledControlForm\(frameHost, \{[\s\S]*selector: '\[data-action="newParallelPlan"\]'[\s\S]*submitAction: 'submitParallelPlan'/);
  assert.doesNotMatch(profile, /document\.querySelector\('\[data-action="newParallelPlan"\]'\)\.click\(\)/);
});

test('current-source host identity requires the typed runtime contract and exact local asset binding', () => {
  const fixtureRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'px-source-identity-'));
  try {
    fs.mkdirSync(path.join(fixtureRoot, 'src'), { recursive: true });
    fs.writeFileSync(path.join(fixtureRoot, 'package.json'), JSON.stringify({ version: '1.2.3' }));
    fs.writeFileSync(path.join(fixtureRoot, 'src', 'extension.js'), 'host-v1');
    fs.writeFileSync(path.join(fixtureRoot, 'src', 'extension.bundle.js'), 'bundle-v1');
    const beforeBundleChange = currentSourceExtensionAssetIdentity(fixtureRoot);
    fs.writeFileSync(path.join(fixtureRoot, 'src', 'extension.bundle.js'), 'bundle-v2');
    const afterBundleChange = currentSourceExtensionAssetIdentity(fixtureRoot);
    assert.deepEqual(afterBundleChange, beforeBundleChange, 'the generated installed-only bundle is outside the raw-source identity');
    assert.equal(beforeBundleChange.asset_file_count, 1);
  } finally {
    fs.rmSync(fixtureRoot, { recursive: true, force: true });
  }
  const current = currentSourceExtensionAssetIdentity(path.join(__dirname, '..'));
  assert.match(current.asset_sha256, /^[a-f0-9]{64}$/);
  assert.match(current.package_sha256, /^[a-f0-9]{64}$/);
  assert.ok(current.asset_file_count > 0);
  const repositoryRoot = path.resolve(__dirname, '..', '..');
  const python = String(process.env.PYTHON || process.env.PYTHON_EXECUTABLE || 'python');
  const pythonIdentity = spawnSync(python, ['-c', 'import json; from pathlib import Path; from runtime.dashboard_api import _extension_source_identity; print(json.dumps(_extension_source_identity(Path.cwd())))'], {
    cwd: repositoryRoot, encoding: 'utf8', windowsHide: true, timeout: 30_000
  });
  assert.equal(pythonIdentity.status, 0, pythonIdentity.stderr);
  const dashboardIdentity = JSON.parse(String(pythonIdentity.stdout).trim().split(/\r?\n/).filter(Boolean).at(-1));
  assert.deepEqual(
    { asset_sha256: dashboardIdentity.asset_sha256, asset_file_count: dashboardIdentity.asset_file_count, package_sha256: dashboardIdentity.package_sha256 },
    { asset_sha256: current.asset_sha256, asset_file_count: current.asset_file_count, package_sha256: current.package_sha256 }
  );
  const identitySource = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const identityOwner = identitySource.slice(identitySource.indexOf('function currentSourceExtensionAssetIdentity'), identitySource.indexOf('function installedRuntimeSourceIdentityState'));
  assert.match(identityOwner, /hostSourceRoot[\s\S]*src/);
  assert.match(identityOwner, /name !== 'extension\.bundle\.js'/);
  assert.match(identityOwner, /action-inventory\.json/);
  const host = { ...current, schema_version: 'px.extension-host-identity/1.0', asset_protocol: 'px.sidebar.assets/1.0', message_schema: 'px.sidebar.messages/1.0' };
  const runtime = { schema_version: 'px.extension-runtime-identity/1.0', matches: true, host, source: { ...host }, mismatch_reasons: [] };
  assert.equal(installedRuntimeSourceIdentityState(runtime, current), 'verified');
  const packagedHost = { ...host, package_sha256: 'a'.repeat(64) };
  assert.equal(installedRuntimeSourceIdentityState({ ...runtime, host: packagedHost }, current), 'verified', 'the installed manifest intentionally points main at the generated bundle');
  assert.equal(installedRuntimeSourceIdentityState({ ...runtime, host: packagedHost, source: { ...host, package_sha256: 'b'.repeat(64) } }, current), 'mismatch', 'the runtime source manifest must still bind the current raw source exactly');
  assert.equal(installedRuntimeSourceIdentityState({ ...runtime, matches: false, mismatch_reasons: ['host-assets-differ-from-source'] }, current), 'mismatch');
  assert.equal(installedRuntimeSourceIdentityState({ ...runtime, schema_version: 'substitute' }, current), 'unknown');
  assert.equal(installedRuntimeSourceIdentityState(runtime, { ...current, asset_sha256: 'f'.repeat(64) }), 'mismatch');
  assert.equal(installedSourceIdentityNeedsLateRefresh({ state: 'unknown' }), true);
  assert.equal(installedSourceIdentityNeedsLateRefresh({ state: 'verified' }), false);
  assert.equal(installedSourceIdentityNeedsLateRefresh({ state: 'mismatch' }), false, 'a mismatch must fail closed rather than being refreshed away');
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const main = source.slice(source.indexOf('async function main()'));
  assert.match(main, /refreshInstalledSourceIdentity\(dashboard, installedIdentity, 45_000, 'request-bound'\)/);
  assert.match(source, /state: installedRuntimeSourceIdentityState\(runtimeIdentity, currentSourceIdentity\)/);
  assert.match(source, /refresh: `\$\{refresh\}-failed`[\s\S]*diagnostic: String\(error\?\.message \|\| error\)\.slice\(0, 1600\)/);
  assert.match(main, /installedSourceIdentityNeedsLateRefresh\(installedIdentity\)[\s\S]*refreshInstalledSourceIdentity\(dashboard, installedIdentity, 45_000, 'request-bound-late'\)[\s\S]*const observedAt/);
  assert.match(main, /runtime_identity: installedIdentity\.runtime_identity \|\| null/);
  assert.match(main, /current_source_identity: installedIdentity\.current_source_identity \|\| null/);
});

test('owned walker settles the canonical Dashboard route before typed identity and focused profiles', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const main = source.slice(source.indexOf('async function main()'));
  const route = main.indexOf("navigateInstalledSurface(dashboard, 'dashboard'");
  const identity = main.indexOf('waitForInstalledSourceIdentity(dashboard');
  const profile = main.indexOf('runInstalledCodexHandoffProfile(workbench, dashboard');
  assert.ok(route >= 0 && identity > route && profile > identity);
  assert.match(main.slice(route, identity), /installed-initial-dashboard-route-unavailable/);
  assert.match(source, /__PX_INSTALLED_RESPONSES__[\s\S]*px\.extension-runtime-identity\/1\.0/);
});

test('R107 residual repair keeps environment, sidebar, graph, navigation, and permanent cleanup boundaries exact', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /environmentExtensionDetail\.row[\s\S]*rowAvailable[\s\S]*seedInstalledConditionalScenario\(frameHost, control\)/);
  assert.match(source, /projection\.ui\.expandedTaskIds = item\.expanded/);
  assert.doesNotMatch(source, /projection\.ui\.expandedTaskIds = expanded/);
  assert.match(source, /data-action="graphCommunity"\]\[data-community-id\][\s\S]*dataset\.communityId/);
  assert.doesNotMatch(source, /state\.graphData\.communities/);
  assert.match(source, /!state\.graphData \|\| !Array\.isArray\(state\.graphData\.nodes\)/);
  assert.doesNotMatch(source, /state\.graphData\?\.available/);
  assert.match(source, /data-surface="runtimeCore"\]\[aria-current="page"[\s\S]*Runtime Core/);
  assert.match(source, /stage === 'recovery_rollback' && permanent[\s\S]*native confirmation was cancelled[\s\S]*no cleanup result was emitted/);
  assert.match(source, /frameHost\.evaluateContent\(item => \{[\s\S]*structuredClone\(state\.snapshot\)[\s\S]*state\.snapshot = original; render\(\)/);
});

test('R108 residual repair restores canonical graph state, advanced routes, and the exact stale-environment refusal', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /needsCanonicalCommunities[\s\S]*graphView"\]\[data-view="capabilities"[\s\S]*types: \['graphResult'\][\s\S]*installed-graph-canonical-community-timeout/);
  assert.match(source, /state\.graphInspectorOpen = true;[\s\S]*data-graph-record-list/);
  assert.match(source, /\['knowledgeCore', 'runtimeCore'\]\.includes\(surface\)[\s\S]*state\.active = target;[\s\S]*surface-\$\{target\}/);
  const boundary = source.slice(source.indexOf('async function runInstalledValidationBoundaryProfile'), source.indexOf('async function runInstalledValidationProfile'));
  assert.match(boundary, /state\.active = item\.route;[\s\S]*state: 'stale'[\s\S]*installed-validation-boundary-control-timeout/);
  assert.match(boundary, /__PX_VALIDATION_BOUNDARY_ORIGINAL_SNAPSHOT__[\s\S]*delete inner\.__PX_VALIDATION_BOUNDARY_ORIGINAL_SNAPSHOT__[\s\S]*state\.snapshot = original/);
});

test('R110 residual repair owns the physical viewport, exact graph predecessors, runtime refresh, and restored authority boundary', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /async function enforceOwnedWorkbenchViewport[\s\S]*Emulation\.setDeviceMetricsOverride[\s\S]*inner_width >= 1400[\s\S]*return \{ session, observed \}/);
  assert.doesNotMatch(source, /Browser\.getWindowForTarget|Browser\.setWindowBounds/);
  assert.match(source, /ownedWorkbenchViewport = await enforceOwnedWorkbenchViewport\(workbench\)/);
  assert.match(source, /ownedWorkbenchViewport\?\.session\?\.detach/);
  assert.match(source, /'pxui\.runtime-core\.action\.refresh': '\.surface-runtimeCore \[data-action="refresh"\]'/);
  for (const [control, mode] of [
    ['graphDepth.increase', 'depth-increase'], ['graphLayout.flow', 'layout-flow'], ['graphLayout.orbit', 'layout-orbit']
  ]) assert.match(source, new RegExp(`'pxui\\.knowledge-graph\\.action\\.${control.replace('.', '\\.')}'[^\\n]+ '${mode}'`));
  assert.match(source, /state\.graphPending !== true[\s\S]*installed-graph-state-settlement-timeout/);
  assert.match(source, /installed-graph-exact-control-timeout/);
  const validation = source.slice(source.indexOf('function validationControlProbe'), source.indexOf('async function runInstalledValidationBoundaryProfile'));
  assert.ok(validation.indexOf("if (stage === 'recovery_rollback')") < validation.indexOf("if (requirement.stage_policy[stage] !== 'required')"));
});

test('R112 residual repair uses physical graph modes and restores each advanced-route predecessor', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const prepare = source.slice(source.indexOf('async function prepareInstalledControl'), source.indexOf('async function revealInstalledControl'));
  assert.match(prepare, /physicalMode[\s\S]*data-graph-analysis[\s\S]*dispatchEvent\(new Event\('change'/);
  assert.match(prepare, /depth-decrease[\s\S]*graphDepth[\s\S]*depth-increase[\s\S]*layout-flow[\s\S]*graphLayout[\s\S]*layout-orbit/);
  assert.match(source, /function installedAdvancedControlTarget[\s\S]*prepareInstalledAdvancedControl[\s\S]*showAdvancedSurfaces: true/);
  assert.match(source, /async function restoreInstalledAdvancedControl[\s\S]*state\.settings = original\.settings[\s\S]*state\.active = original\.active[\s\S]*state\.advancedOpen = original\.advancedOpen/);
  const probe = source.slice(source.indexOf('async function probeInstalledControls'), source.indexOf('function installedSidebarSelector'));
  assert.match(probe, /advancedPredecessor = await prepareInstalledAdvancedControl[\s\S]*finally[\s\S]*restoreInstalledAdvancedControl/);
});

test('R113 advanced-route fixture settles prior control modals before rendering predecessor state', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const fixture = source.slice(source.indexOf('async function prepareInstalledAdvancedControl'), source.indexOf('async function restoreInstalledAdvancedControl'));
  assert.match(fixture, /await settleInstalledModalBoundary\(frameHost, 5_000\);[\s\S]*frameHost\.evaluateContent/);
  assert.match(fixture, /state\.settings = [\s\S]*state\.active = route;[\s\S]*state\.advancedOpen = true;[\s\S]*render\(\)/);
  assert.match(fixture, /rendered_surface:[\s\S]*surface-\$\{route\}[\s\S]*installedAdvancedFixtureStateAcknowledged\(observed, target\)/);
  const modalSettlement = fixture.indexOf('settleInstalledModalBoundary');
  const predecessorCapture = fixture.indexOf('structuredClone(state.settings');
  assert.ok(modalSettlement >= 0 && modalSettlement < predecessorCapture);
});

test('advanced-route fixture tolerates deferred modal renders and restores every unsuccessful exit', () => {
  const route = 'runtimeCore';
  const ready = { settings_visible: true, active: route, advanced_open: true, rendered_surface: true, modal_count: 0 };
  assert.equal(installedAdvancedFixtureStateAcknowledged(ready, route), true);
  for (const observation of [
    { ...ready, settings_visible: false },
    { ...ready, active: 'dashboard' },
    { ...ready, advanced_open: false },
    { ...ready, rendered_surface: false },
    null
  ]) assert.equal(installedAdvancedFixtureStateAcknowledged(observation, route), false);

  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const fixture = source.slice(source.indexOf('async function prepareInstalledAdvancedControl'), source.indexOf('async function restoreInstalledAdvancedControl'));
  assert.match(fixture, /const deadline = Date\.now\(\) \+ 5_000;[\s\S]*do \{[\s\S]*settleInstalledModalBoundary[\s\S]*state\.settings = [\s\S]*render\(\)[\s\S]*installedAdvancedFixtureStateAcknowledged/);
  assert.match(fixture, /catch \(error\)[\s\S]*restoreInstalledAdvancedControl\(frameHost, predecessor\)[\s\S]*installed-advanced-route-fixture-error/);
  assert.match(fixture, /restoreInstalledAdvancedControl\(frameHost, predecessor\)[\s\S]*installed-advanced-route-fixture-state-unavailable/);
});

test('R114 residual repair applies authoritative graph modes, owns exact navigation, and reconstructs uninstall inventory', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const prepare = source.slice(source.indexOf('async function prepareInstalledControl'), source.indexOf('async function revealInstalledControl'));
  assert.match(prepare, /analysis\.dispatchEvent\(new Event\('change'[\s\S]*data-action="runGraphSearch"[\s\S]*apply\.click\(\)/);
  assert.match(prepare, /state\.graphPending !== true[\s\S]*state\.graphData[\s\S]*installed-graph-physical-mode-settlement-timeout/);
  assert.match(source, /INSTALLED_EXACT_NAVIGATION_TRANSITIONS[\s\S]*navigate\.knowledgeCore[\s\S]*navigate\.runtimeCore[\s\S]*runtime-core\.action\.navigate\.workflows/);
  assert.match(source, /async function exerciseInstalledExactNavigation[\s\S]*installed-exact-navigation-control-unavailable[\s\S]*installed-exact-navigation-transition-timeout/);
  assert.match(source, /target\.click\(\)[\s\S]*acknowledged: state\.active === spec\.target[\s\S]*if \(clicked\.acknowledged\) return completed\(\)/);
  const probe = source.slice(source.indexOf('async function probeInstalledControls'), source.indexOf('function installedSidebarSelector'));
  assert.match(probe, /installedExactNavigationTransition\(control\)[\s\S]*exerciseInstalledExactNavigation/);
  const plugin = source.slice(source.indexOf('async function runInstalledPluginMutationProfile'), source.indexOf('function knowledgeLifecycleControlProbe'));
  assert.match(plugin, /requiresWorkbenchReconstruction = \['install', 'update', 'uninstall', 'rollback'\]\.includes\(spec\.receiptAction\)/);
  assert.match(plugin, /requiresWorkbenchReconstruction[\s\S]*restartOwnedWorkbenchWindow\(workbench, frameHost, 75_000, \{[\s\S]*physicalExtensionId: extensionId[\s\S]*expectedPhysicalVersion: spec\.expectedVersion/);
  assert.doesNotMatch(plugin, /restartOwnedExtensionHostCatalog\(/);
});

test('final51 residual controls have exact scoped selectors and deterministic restoration', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /pxui\.dashboard\.action\.inspectSensor\.row': '\.surface-dashboard \[data-action="inspectSensor"\]\[data-sensor-id\]'/);
  assert.match(source, /pxui\.runtime-core\.action\.inspectSensor\.row': '\.surface-runtimeCore \[data-action="inspectSensor"\]\[data-sensor-id\]'/);
  assert.match(source, /installed-sensor-row-settlement-timeout/);
  assert.match(source, /pxui\.knowledge-graph\.field\.graphStatus': '\[data-graph-status-filter\]'/);
  const graphField = source.slice(source.indexOf('async function exerciseInstalledExactGraphField'), source.indexOf('async function probeInstalledControls'));
  assert.match(graphField, /endsWith\('\.graphStatus'\) \? 'full'/);
  assert.match(graphField, /const current = document\.querySelector\(spec\.selector\)[\s\S]*current\.add\(new Option\(original, original\)\)[\s\S]*state\.graphStatus === original[\s\S]*restored\.value === original/);
});

test('Plugin lifecycle reconstruction reloads the complete owned workbench catalog before inventory assertion', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const helper = source.slice(source.indexOf('async function restartOwnedExtensionHostCatalog'), source.indexOf('function installedWorkbenchCommandSpec'));
  assert.match(helper, /waitForOwnedPhysicalExtensionVersion[\s\S]*Developer: Restart Extension Host/);
  assert.match(helper, /closeOwnedDashboardTabs[\s\S]*Pacify-X: Open Storage & Cleanup Manager[\s\S]*reopenPacifyDashboardFromOwnedUi/);
  assert.match(helper, /requestInstalledRefreshBound[\s\S]*waitForInstalledSnapshot[\s\S]*snapshot\?\.connected === true/);
  const plugin = source.slice(source.indexOf('async function runInstalledPluginMutationProfile'), source.indexOf('function knowledgeLifecycleControlProbe'));
  assert.match(plugin, /restartOwnedWorkbenchWindow[\s\S]*currentVersion\(spec\.expectedVersion\)/);
  assert.ok(plugin.indexOf('restartOwnedWorkbenchWindow') < plugin.indexOf('currentVersion(spec.expectedVersion)'));
});

test('native focused profiles require request-bound hydrated state and exact route settlement', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const reopen = source.slice(source.indexOf('async function reopenPacifyDashboardFromOwnedUi'), source.indexOf('async function waitForOwnedWorkbenchDisplacementSettled'));
  assert.match(reopen, /canonical:[\s\S]*data-surface="dashboard"[\s\S]*connected:[\s\S]*classList\.contains\('disconnected'\)[\s\S]*state\.canonical === true && state\.connected === true/);
  const enterprise = source.slice(source.indexOf('async function runInstalledEnterpriseProfile'), source.indexOf('const INSTALLED_VALIDATION_CONTROL_IDS'));
  assert.match(enterprise, /requestInstalledRefreshBound[\s\S]*snapshot\?\.enterprise\?\.packs[\s\S]*enterprisePackToggle/);
  const projects = source.slice(source.indexOf('async function runInstalledProjectsProfile'), source.indexOf('function graphProjectionIdentity'));
  assert.match(projects, /observation\.build_result[\s\S]*requestInstalledRefreshBound[\s\S]*waitForInstalledSnapshot[\s\S]*projectMapIdentity/);
  const cleanup = source.slice(source.indexOf('async function runInstalledCleanupProfile'), source.indexOf('function pluginReadControlProbe'));
  assert.match(cleanup, /navigateInstalledSurface\(frameHost, 'runtimeCore'/);
});

test('initial installed dashboard activation allows the full bounded snapshot process window', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /dashboardTab\.waitFor\(\{ state: 'visible', timeout: 90_000 \}\)/);
});

test('generic native cancellation is recovered only after the complete exact native denominator', () => {
  const diagnostic = { source: 'console', context: 'console:vscode-file://vscode-app/workbench/workbench.desktop.main.js', message: 'Canceled' };
  const enterprise = { observation: { controls: Object.fromEntries(Array.from({ length: 5 }, (_, index) => [`control-${index}`, { completed: true, cancelled_without_effect: true, errors: [] }])) } };
  const projects = { observation: { completed: true, cancelled_controls: { a: true, b: true, c: true } } };
  const cleanup = { observation: { completed: true, permanent_refused_without_authorization: true } };
  assert.equal(partitionExpectedFaultDiagnostics([diagnostic], null, null, false, null, { enterprise, projects, cleanup }).recovered[0]?.disposition, 'expected_native_dialog_cancellation_recovered');
  assert.deepEqual(partitionExpectedFaultDiagnostics([diagnostic], null, null, false, null, { enterprise, projects: { observation: { ...projects.observation, completed: false } }, cleanup }), { retained: [diagnostic], recovered: [] });
});

test('R115 final mechanics stay in the content realm and settle physical graph predecessors', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const prepare = source.slice(source.indexOf('async function prepareInstalledControl'), source.indexOf('async function revealInstalledControl'));
  assert.match(prepare, /requestDispatched = true[\s\S]*installed-graph-physical-predecessor-settlement-timeout/);
  const navigation = source.slice(source.indexOf('async function exerciseInstalledExactNavigation'), source.indexOf('async function exerciseInstalledExactGraphField'));
  assert.match(navigation, /frameHost\.evaluateContent[\s\S]*state\.advancedOpen = true[\s\S]*state\.active === target/);
  const graphField = source.slice(source.indexOf('async function exerciseInstalledExactGraphField'), source.indexOf('async function probeInstalledControls'));
  assert.match(source, /INSTALLED_EXACT_GRAPH_FIELDS[\s\S]*graphDirection[\s\S]*graphTarget/);
  assert.match(graphField, /frameHost\.evaluateContent[\s\S]*target\.dispatchEvent[\s\S]*const restored = document\.querySelector\(spec\.selector\)[\s\S]*restored: Boolean\(restored && restored\.value === original && stateRestored\)/);
  const probe = source.slice(source.indexOf('async function probeInstalledControls'), source.indexOf('function installedSidebarSelector'));
  assert.match(probe, /installedExactGraphField\(control\)[\s\S]*exerciseInstalledExactGraphField/);
});

test('R116 final graph fields atomically enter their real analysis mode before reversible input', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const graphField = source.slice(source.indexOf('async function exerciseInstalledExactGraphField'), source.indexOf('async function probeInstalledControls'));
  assert.match(graphField, /endsWith\('\.graphTarget'\) \? 'path'[\s\S]*endsWith\('\.graphStatus'\) \? 'full' : 'dependencies'/);
  assert.match(graphField, /data-graph-analysis[\s\S]*analysis\.dispatchEvent\(new Event\('change'[\s\S]*document\.querySelector\(spec\.selector\)/);
  assert.ok(graphField.indexOf('analysis.dispatchEvent') < graphField.indexOf('document.querySelector(spec.selector)'));
});

test('R117 depth menu owns focused predecessor and advanced fixture verifies state instead of transient submenu DOM', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const direct = source.slice(source.indexOf('function installedDirectSelector'), source.indexOf('function installedStudioPrerequisites'));
  assert.match(direct, /'pxui\.knowledge-graph\.menu\.depth': '\[role="group"\]\[aria-label="Relationship depth"\]'/);
  const prepare = source.slice(source.indexOf('async function prepareInstalledControl'), source.indexOf('async function revealInstalledControl'));
  assert.match(prepare, /'pxui\.knowledge-graph\.menu\.depth': 'depth-menu'[\s\S]*'depth-menu': 'neighborhood'/);
  const acknowledgement = source.slice(source.indexOf('function installedAdvancedFixtureStateAcknowledged'), source.indexOf('async function prepareInstalledAdvancedControl'));
  const fixture = source.slice(source.indexOf('async function prepareInstalledAdvancedControl'), source.indexOf('async function restoreInstalledAdvancedControl'));
  assert.match(acknowledgement, /settings_visible === true[\s\S]*active === route[\s\S]*advanced_open === true[\s\S]*rendered_surface === true/);
  assert.match(fixture, /installedAdvancedFixtureStateAcknowledged\(observed, target\)/);
  assert.doesNotMatch(fixture, /document\.querySelector\(`\[data-surface=/);
});

test('R127 graph conditionals restore a physical graph baseline after preceding failure fixtures', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const prepare = source.slice(source.indexOf('async function prepareInstalledControl'), source.indexOf('async function revealInstalledControl'));
  assert.match(prepare, /graphStatePresent[\s\S]*graphView\"\]\[data-view=\"repository\"\][\s\S]*runGraphSearch/);
  assert.match(prepare, /installed-graph-baseline-request-unavailable[\s\S]*waitForInstalledResponse\(frameHost, before, \{ types: \['graphResult'\] \}, 20_000\)/);
  assert.ok(prepare.indexOf('graphStatePresent') < prepare.indexOf('const graphStateDeadline'));
});

test('R118 catalog pagination waits for kind-specific controls after the exact correlated host response', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const settlement = source.slice(source.indexOf('async function waitForInstalledCatalogControls'), source.indexOf('async function runInstalledCatalogPaginationProfile'));
  assert.match(settlement, /catalogPrevious[\s\S]*catalogNext[\s\S]*previous_rendered[\s\S]*next_rendered[\s\S]*previous_disabled[\s\S]*next_ready/);
  assert.match(settlement, /do \{[\s\S]*await wait\(100\);[\s\S]*Date\.now\(\) < deadline/);
  const profile = source.slice(source.indexOf('async function runInstalledCatalogPaginationProfile'), source.indexOf('const INSTALLED_OBSERVATION_STATE_IDS'));
  assert.match(profile, /waitForInstalledCatalogExchange[\s\S]*waitForInstalledCatalogControls\(frameHost, spec\.kind, timeoutMs\)/);
  assert.ok(profile.indexOf('waitForInstalledCatalogExchange') < profile.indexOf('waitForInstalledCatalogControls'));
});

test('inline command denominator is owned only by the exact completed production action', () => {
  const pairs = [
    ['cleanupManager', 'pxui.runtime-core.action.cleanupManager'],
    ['contextSnapshot', 'pxui.runtime-core.action.contextSnapshot'],
    ['enterpriseDoctor', 'pxui.agents.action.enterpriseDoctor'],
    ['newParallelPlan', 'pxui.workflows.action.newParallelPlan'],
    ['openCoordinationHandoff', 'pxui.runtime-core.action.openCoordinationHandoff'],
    ['openSettings', 'pxui.dashboard-control-plane.action.openSettings.header'],
    ['refresh', 'pxui.dashboard.action.refresh.hero'],
    ['teamPackPreview', 'pxui.agents.action.teamPackPreview'],
    ['validate', 'pxui.diagnostics.action.validate']
  ];
  const controls = pairs.map(([command]) => ({
    control_id: `pxui.dashboard-control-plane.command.${command}`, surface_id: 'dashboard-control-plane', kind: 'command',
    stage_policy: Object.fromEntries(STAGES.map(stage => [stage, 'required']))
  }));
  const completeChain = Object.fromEntries(STAGES.map(stage => [stage, { state: 'present', detail: stage, evidence: ['source'] }]));
  const records = pairs.map(([, control_id]) => ({ control_id, rendered: true, observed: true, attempted: true, interaction_chain: completeChain, errors: [] }));
  const probe = inlineCommandOwnerControlProbe({ controls }, [{ records }]);
  assert.equal(probe.eligible_control_count, 9);
  assert.ok(probe.records.every(record => record.interaction_chain.open_load.state === 'present'));
  const withoutValidation = inlineCommandOwnerControlProbe({ controls }, [{ records: records.filter(record => record.control_id !== 'pxui.diagnostics.action.validate') }]);
  assert.equal(withoutValidation.records.find(record => record.control_id.endsWith('.validate')).interaction_chain.open_load.state, 'missing');
});

test('installed workbench commands reject one exact pre-dispatch event before fresh recovery', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const executeStart = source.indexOf('async function executeWorkbenchCommand');
  const execute = source.slice(executeStart, source.indexOf('function ownedWorkbenchReloadIdentity', executeStart));
  const probeStart = source.indexOf('async function probeInstalledWorkbenchCommands');
  const probe = source.slice(probeStart, source.indexOf('async function inspectSurface', probeStart));
  assert.match(execute, /options\.rejectBeforeDispatch === true/);
  assert.match(execute, /event\.preventDefault\(\);[\s\S]*event\.stopImmediatePropagation\(\)/);
  assert.match(execute, /const retained = await widget\.isVisible/);
  assert.match(execute, /executed: false, rejected: true, restored: true/);
  assert.match(probe, /executeWorkbenchCommand\(workbench, spec\.title, \{ rejectBeforeDispatch: true \}\)/);
  assert.match(probe, /probe\.failureObserved = rejected\.listed === true[\s\S]*rejected\.restored === true/);
  assert.match(probe, /const command = await executeWorkbenchCommand\(workbench, spec\.title\)/);
  assert.match(probe, /probe\.recoveryObserved = probe\.failureObserved/);
});

test('owned installed Studio setup accepts only the exact ready and succeeded result contract', () => {
  const result = {
    schema_version: 'px.studio-setup-result/1.0', ready: true,
    agent: { identity: 'agent:px-studio-local', version: '1.0.0', decision: 'admitted', run_id: 'run:agent:1', run_outcome: 'succeeded' },
    workflow: { identity: 'workflow:px-studio-local', version: '1.0.0', decision: 'admitted', run_id: 'run:workflow:1', run_state: 'succeeded' }
  };
  assert.equal(validStudioSetupResult(result), true);
  assert.equal(validStudioSetupResult({ ...result, ready: false }), false);
  assert.equal(validStudioSetupResult({ ...result, workflow: { ...result.workflow, run_state: 'failed' } }), false);
  assert.equal(validStudioSetupResult({ ...result, agent: { ...result.agent, decision: 'candidate' } }), false);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledStudioSetupProfile'), source.indexOf('function validStudioDraftReceipt'));
  assert.match(profile, /setupStudio-native-cancellation-not-observed/);
  assert.match(profile, /clickNativeStudioSetupAction\(workbench, cancellationDialog, 'Cancel'\)/);
  assert.match(profile, /clickNativeStudioSetupAction\(workbench, approvalDialog, 'Set up and run'\)/);
  assert.match(profile, /cancellationDialog\.request_type = 'setupStudio'[\s\S]*cancellationDialog\.frame_host = frameHost/);
  assert.match(profile, /approvalDialog\.request_type = 'setupStudio'[\s\S]*approvalDialog\.frame_host = frameHost/);
  assert.match(profile, /waitForInstalledOutboundRequest\(frameHost, requestBefore, 'setupStudio'\)/);
  assert.match(profile, /exactStudioSetupTerminalResponse\(responses, 0, request\.requestId\)/);
  assert.match(profile, /setupStudio-operation-error:/);
  assert.match(profile, /const controlIds = \[[\s\S]*pxui\.agent-studio\.indicator\.approvalCancelled[\s\S]*pxui\.agent-studio\.indicator\.hostOperationFailed/);
  const nativeAction = source.slice(source.indexOf('async function clickNativeWorkbenchDialogAction'), source.indexOf('async function clickNativeStudioSetupAction'));
  assert.match(nativeAction, /owned-native-workbench-action-not-admitted/);
  assert.match(source, /NATIVE_WORKBENCH_ACTION_SELECTOR = '[^']*\.monaco-text-button/);
  assert.doesNotMatch(source, /NATIVE_WORKBENCH_ACTION_SELECTOR = '[^']*tabindex/);
  assert.match(nativeAction, /label === 'Cancel'[\s\S]*keyboard\.press\('Escape'\)/);
  assert.match(nativeAction, /exactActionDeadline = Date\.now\(\) \+ 2_000[\s\S]*const candidates = scope\.locator\(actionSelector\)\.filter\(\{ hasText: exact \}\)[\s\S]*candidate\.isVisible[\s\S]*candidate\.click\(\{ timeout: 3_000 \}\)[\s\S]*wait\(50\)[\s\S]*Date\.now\(\) < exactActionDeadline[\s\S]*label === 'Cancel'[\s\S]*nativeWorkbenchRequestFallbackAdmitted\(request, label[\s\S]*requestOwnedNativeInput\(label, request\)[\s\S]*OWNED_NATIVE_WORKBENCH_ACTIONS\.has\(label\)[\s\S]*focusTraversal: true[\s\S]*owned-native-workbench-exact-action-not-visible/);
  assert.doesNotMatch(nativeAction, /candidate\.evaluate\(element => element\.click\(\)|owned-native-workbench-exact-action-focus-unproven/);
  assert.doesNotMatch(nativeAction, /OWNED_NATIVE_WORKBENCH_ACTIONS\.has\(label\)[\s\S]*keyboard\.press\('Enter'\)/);
  assert.match(source, /'Set up and run'[\s\S]*'Authorize native install'[\s\S]*'Authorize conflict route'/);
  assert.match(source, /\['Cancel', new Set\(\['setupStudio'[\s\S]*\['Set up and run', new Set\(\['setupStudio'\]\)\]/);
  const setupWait = source.slice(source.indexOf('async function waitForStudioSetupAction'), source.indexOf('async function runInstalledStudioSetupProfile'));
  assert.match(setupWait, /Date\.now\(\) \+ timeoutMs/);
  assert.match(setupWait, /setupStudio-landing-action-unavailable/);
  assert.match(setupWait, /__PX_INSTALLED_RESPONSES__/);
  assert.match(profile, /observation\.available = await waitForStudioSetupAction\(frameHost\)/);
  assert.ok(profile.indexOf('requestInstalledRefresh(frameHost)') < profile.indexOf("navigateInstalledSurface(frameHost, 'agents')"));
  assert.ok(profile.indexOf("navigateInstalledSurface(frameHost, 'agents')") < profile.indexOf('waitForStudioSetupAction(frameHost)'));
  const navigation = source.slice(source.indexOf('async function navigateInstalledSurface'), source.indexOf('async function runInstalledStudioSetupProfile'));
  assert.match(navigation, /aria-current/);
  assert.match(navigation, /installed-surface-navigation-timeout/);
  const refresh = source.slice(source.indexOf('async function requestInstalledRefresh'), source.indexOf('async function installedSurfaceConnection'));
  assert.match(refresh, /navigateInstalledSurface\(frameHost, 'dashboard', timeoutMs\)/);
  assert.match(refresh, /installed-refresh-control-timeout/);
  assert.match(refresh, /refresh_controls/);
  assert.match(refresh, /data-action="commandCenter"/);
  assert.match(refresh, /opened-control-center/);
  assert.match(refresh, /\.find\(value => value\?\.type === 'refresh'\)/);
  assert.doesNotMatch(refresh, /value\?\.type === 'refresh' && typeof value\.requestId/);
  assert.match(refresh, /control\.closest\('\.control-modal'\)/);
  assert.match(refresh, /closeModal\?\.click\(\)/);
  assert.match(refresh, /modal_open/);
  assert.doesNotMatch(refresh, /installed-refresh-control-unavailable/);
  const nativeDialog = source.slice(source.indexOf('async function waitForNativeStudioSetupDialog'), source.indexOf('async function runInstalledStudioSetupProfile'));
  assert.match(nativeDialog, /\.dialog-container:visible/);
  assert.match(nativeDialog, /\[role="dialog"\]:visible/);
  assert.match(nativeDialog, /getByText\(expected\)/);
  assert.match(nativeDialog, /workbench\.context\(\)\.pages\(\)/);
  assert.match(nativeDialog, /ancestor::\*\[\.\/\/button or \.\/\/\*\[@role="button"\][\s\S]*monaco-text-button[\s\S]*\]\[1\]/);
  assert.match(nativeDialog, /ancestor::body\[1\]/);
  assert.match(nativeDialog, /message_matches/);
  assert.match(nativeDialog, /visible_actions/);
  assert.match(nativeDialog, /pageInventory/);
  assert.match(nativeDialog, /setupStudio-native-dialog-not-observed/);
  assert.match(nativeDialog, /dashboard_responses/);
  assert.match(profile, /waitForNativeStudioSetupDialog\(workbench, frameHost, cancelledBefore\)/);
  assert.match(profile, /waitForNativeStudioSetupDialog\(workbench, frameHost, before\)/);
  const identityProbe = source.slice(source.indexOf('function currentSourceExtensionAssetIdentity'), source.indexOf('async function main()'));
  assert.match(identityProbe, /waitForInstalledSourceIdentity/);
  assert.match(identityProbe, /px\.extension-runtime-identity\/1\.0/);
  assert.match(identityProbe, /__PX_INSTALLED_RESPONSES__/);
  assert.match(source.slice(source.indexOf('async function main()')), /refreshInstalledSourceIdentity\(dashboard, installedIdentity, 45_000, 'request-bound'\)/);
  assert.match(source.slice(source.indexOf('async function main()')), /installedIdentity\.state === 'verified'/);
  assert.match(identityProbe, /vscode\\\.mermaid-markdown-features[\s\S]*legacyToolReferenceFullNames[\s\S]*chatParticipantPrivate/);
  assert.match(identityProbe, /message\?\.location\?\.\(\)/);
  assert.match(identityProbe, /console:\$\{sourceUrl\}/);
  assert.match(identityProbe, /ownedUnpublishedMarketplaceLookup[\s\S]*mountain-nomad-bc\/pacify-x-vscode\/latest[\s\S]*pacify-x-certification\/pacify-x-installed-certifier\/latest[\s\S]*includes\(sourceUrl\)/);
  assert.match(identityProbe, /Cancelled:[\s\S]*Canceled:[\s\S]*getLatestRawGalleryExtension[\s\S]*getLatestGalleryExtension[\s\S]*workbench\\\/workbench\\\.desktop\\\.main\\\.js/);
  const launcher = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-isolated-current-source-walk.js'), 'utf8');
  assert.match(launcher, /path\.join\(config\.engineRoot, '\.px', 'owned-operational-prompts'\)[\s\S]*setup-studio\.marker[\s\S]*flag: 'wx'/);
  assert.match(source.slice(source.indexOf('async function main()')), /runInstalledStudioSetupProfile\(workbench, dashboard, proofMatrix\)/);
});

test('Studio setup terminal correlation rejects stale and cross-request responses', () => {
  const responses = [
    { type: 'studioSetupResult', requestId: 'stale', result: { ready: true } },
    { type: 'operationError', operation: 'setupStudio', requestId: 'active', error: 'exact failure' },
    { type: 'studioSetupResult', requestId: 'active', result: { ready: true } }
  ];
  assert.deepEqual(exactStudioSetupTerminalResponse(responses, 0, 'active'), responses[1]);
  assert.equal(exactStudioSetupTerminalResponse(responses, 2, 'missing'), null);
  assert.equal(exactStudioSetupTerminalResponse(responses, 0, ''), null);
});

test('owned installed Studio candidate save accepts only kind-exact durable receipts', () => {
  const agent = { schema_version: 'px.agent-creation-receipt/1.1', agent_id: 'agent:px-owned', version: '1.0.0', created: true, record_sha256: 'a'.repeat(64) };
  const workflow = { schema_version: 'px.workflow-revision-receipt/1.2', workflow_id: 'workflow:px-owned', version: '1.0.0', created: true, revision_sha256: 'b'.repeat(64) };
  const skill = { schema_version: 'px.skill-draft/1.1', manifest: { skill_id: 'px-owned', version: '1.0.0' }, manifest_sha256: 'c'.repeat(64), source_tree_sha256: 'd'.repeat(64) };
  assert.equal(validStudioDraftReceipt('agent', agent, agent.agent_id), true);
  assert.equal(validStudioDraftReceipt('workflow', workflow, workflow.workflow_id), true);
  assert.equal(validStudioDraftReceipt('skill', skill, skill.manifest.skill_id), true);
  assert.equal(validStudioDraftReceipt('agent', { ...agent, version: '1.0.1' }, agent.agent_id, '1.0.1'), true);
  assert.equal(validStudioDraftReceipt('workflow', { ...workflow, version: '1.0.1' }, workflow.workflow_id, '1.0.1'), true);
  assert.equal(validStudioDraftReceipt('agent', agent, agent.agent_id, '1.0.1'), false);
  assert.equal(validStudioDraftReceipt('agent', { ...agent, created: false }, agent.agent_id), false);
  assert.equal(validStudioDraftReceipt('workflow', workflow, 'workflow:other'), false);
  assert.equal(validStudioDraftReceipt('skill', { ...skill, source_tree_sha256: 'bad' }, skill.manifest.skill_id), false);
  const walker = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = walker.slice(walker.indexOf('async function runInstalledStudioCandidateSaveProfile'), walker.indexOf('function studioRevisionEditRecord'));
  assert.match(profile, /const available = Boolean\(save && !save\.disabled\);[\s\S]*if \(available\) save\.click\(\);[\s\S]*dispatched: available/);
  assert.match(profile, /save_dispatched_atomically/);
  assert.doesNotMatch(profile, /querySelector\('\[data-action="submitStudioDraft"\]'\)\.click\(\)/);
  assert.match(profile, /navigateInstalledSurface\(frameHost, spec\.route, 20_000\)/);
  assert.match(profile, /studio-\$\{spec\.kind\}-catalog-search-readiness-timeout/);
  assert.match(profile, /input\.offsetWidth \|\| input\.offsetHeight \|\| input\.getClientRects\(\)\.length/);
  assert.match(profile, /requests: frame\.contentWindow\?\.__PX_INSTALLED_REQUESTS__/);
  assert.match(profile, /responses: frame\.contentWindow\?\.__PX_INSTALLED_RESPONSES__/);
  assert.match(profile, /\[data-catalog-search="\$\{CSS\.escape\(item\.catalogKind\)\}"\]/);
  assert.match(profile, /input\.value = item\.identity;[\s\S]*dispatchEvent\(new Event\('input', \{ bubbles: true \}\)\)/);
  assert.match(profile, /value\?\.type === 'catalogQuery' && value\?\.kind === item\.catalogKind/);
  assert.match(profile, /value\?\.requestId === request\.requestId && \(value\?\.type === 'catalogResult'/);
  assert.match(profile, /observation\.catalog_request_id = query\.request\.requestId/);
  assert.match(profile, /catalog_query_dispatched/);
  assert.match(profile, /reopened_catalog_row_rendered/);
  assert.match(profile, /includeBlockedAgentFixture[\s\S]*memory:px-owned-unresolved/);
  assert.match(profile, /draft\.memory_binding_ids = \[item\.memoryBindingId\]/);
  assert.match(profile, /if \(!spec\.fixture_only\) records\.push/);
  assert.match(profile, /element\.dataset\.kind === catalogKind && element\.dataset\.id === item\.recordId/);
});

test('owned installed revision edit requires changed content, preserved predecessor, and physical reopen', () => {
  const observation = {
    kind: 'agent',
    editor_bound: true,
    stale_result_rejected: true,
    unchanged_save_rejected: true,
    typed_creation_receipt: true,
    reopened_catalog_match: true,
    predecessor_preserved: true,
    content_changed: true,
    reopened_editor_content_match: true,
    original_owner: 'PX',
    changed_owner: 'PX:edited-one',
    predecessor_revision_sha256: 'a'.repeat(64),
    predecessor_content_sha256: 'b'.repeat(64),
    saved_revision_sha256: 'c'.repeat(64),
    saved_content_sha256: 'd'.repeat(64)
  };
  assert.equal(validStudioRevisionEditObservation(observation), true);
  assert.equal(validStudioRevisionEditObservation({ ...observation, changed_owner: observation.original_owner }), false);
  assert.equal(validStudioRevisionEditObservation({ ...observation, predecessor_preserved: false }), false);
  assert.equal(validStudioRevisionEditObservation({ ...observation, saved_content_sha256: observation.predecessor_content_sha256 }), false);
  assert.equal(validStudioRevisionEditObservation({ ...observation, reopened_editor_content_match: false }), false);
  assert.equal(validStudioRevisionEditObservation({ ...observation, unchanged_save_rejected: false }), false);
  assert.equal(validStudioRevisionEditObservation({ ...observation, saved_revision_sha256: 'invalid' }), false);
  assert.equal(validStudioRevisionEditObservation({ ...observation, stale_result_rejected: false }), false);
});

test('owned installed Studio lifecycle accepts only operation-exact typed receipts', () => {
  assert.equal(validStudioLifecycleResult('agent', 'test', { schema_version: 'px.agent-preflight-receipt/1.2', passed: true }), true);
  assert.equal(validStudioLifecycleResult('agent', 'register-authority', { schema_version: 'px.studio-authority-transaction/1.0', status: 'registered', authenticated: true }), true);
  assert.equal(validStudioLifecycleResult('agent', 'admit', { schema_version: 'px.agent-admission-receipt/1.1', decision: 'admitted' }), true);
  assert.equal(validStudioLifecycleResult('agent', 'start', { schema_version: 'px.agent-session-start/1.1', accepted: true, run_id: 'run:one' }), true);
  assert.equal(validStudioLifecycleResult('workflow', 'validate', { schema_version: 'px.workflow-admission-receipt/1.1', decision: 'admitted' }), true);
  assert.equal(validStudioLifecycleResult('workflow', 'dry-run', { schema_version: 'px.workflow-dry-run/1.1', effects_executed: false }), true);
  assert.equal(validStudioLifecycleResult('workflow', 'start', { schema_version: 'px.workflow-session-start/1.1', accepted: true, run_id: 'run:two' }), true);
  assert.equal(validStudioLifecycleResult('skill', 'validate', { schema_version: 'px.skill-validation-receipt/1.1', passed: true }), true);
  assert.equal(validStudioLifecycleResult('skill', 'admit', { schema_version: 'px.skill-admission-receipt/1.1', decision: 'admitted' }), true);
  assert.equal(validStudioLifecycleResult('skill', 'promote', { schema_version: 'px.skill-promotion-receipt/1.3', state: 'promoted', promotion_receipt_relative: '.engineering-bootstrap/studios/skills/demo/promotion-receipt.json' }), true);
  assert.equal(validStudioLifecycleResult('agent', 'status', { schema_version: 'px.studio-durable-run/1.0', run_id: 'run:one' }), true);
  assert.equal(validStudioLifecycleResult('agent', 'pause', { schema_version: 'px.studio-durable-run/1.0', run_id: 'run:one', state: 'pause_requested' }), true);
  assert.equal(validStudioLifecycleResult('workflow', 'cancel', { schema_version: 'px.studio-durable-run/1.0', run_id: 'run:two', state: 'cancel_requested' }), true);
  assert.equal(validStudioLifecycleResult('agent', 'resume', { schema_version: 'px.agent-session-start/1.1', accepted: true, run_id: 'run:one' }), true);
  assert.equal(validStudioLifecycleResult('agent', 'resume', { schema_version: 'px.agent-runtime-receipt/1.2', run_outcome: 'succeeded', run_id: 'run:one' }), false);
  assert.equal(validStudioLifecycleResult('workflow', 'reconcile', { schema_version: 'px.studio-run-reconciliation/1.0', valid: true }), true);
  assert.equal(validStudioLifecycleResult('workflow', 'approve', { schema_version: 'px.workflow-approval-result/1.0', approval_id: 'approval:one' }), true);
  assert.equal(validStudioLifecycleResult('skill', 'rollback', { state: 'rolled-back' }), true);
  assert.equal(validStudioLifecycleResult('workflow', 'runs', { schema_version: 'px.studio-run-list/1.0', kind: 'workflow', runs: [] }), true);
  assert.equal(validStudioLifecycleResult('skill', 'promote', { schema_version: 'px.skill-promotion-receipt/1.3', state: 'promoted' }), false);
  assert.equal(validStudioLifecycleResult('agent', 'admit', { schema_version: 'px.agent-admission-receipt/1.1', decision: 'rejected' }), false);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledStudioLifecycleProfile'), source.indexOf('function validKnowledgeLifecycleResult'));
  const catalogOpen = source.slice(source.indexOf('async function openExactStudioCatalogRow'), source.indexOf('async function runInstalledStudioLifecycleProfile'));
  assert.match(profile, /openExactStudioCatalogRow\(frameHost, candidate\)/);
  assert.match(catalogOpen, /navigateInstalledSurface\(frameHost, candidate\.route, timeoutMs\)/);
  assert.match(catalogOpen, /data-catalog-search[^\n]+catalogKind[\s\S]*search\.value !== item\.identity[\s\S]*search\.dispatchEvent\(new Event\('input', \{ bubbles: true \}\)\)[\s\S]*data-action="inspectCatalogItem"/);
  assert.match(catalogOpen, /exact-catalog-row-timeout/);
  assert.match(catalogOpen, /search_value:/);
  assert.match(catalogOpen, /expected: \{ kind: `\$\{item\.kind\}s`, id: item\.catalog_record_id \}/);
  assert.match(profile, /invalid_transition_rejected/);
  assert.match(profile, /if \(!action\) return true;[\s\S]*if \(!action\.disabled\) return false/);
  assert.match(profile, /out-of-order-transition-not-rejected/);
  assert.match(source, /draft\.executor_adapters = \{ \[binding\.binding_id\]: 'sleep' \}/);
  assert.match(source, /node\.inputs = \[\{ name: 'seconds', data_type: 'number', required: true \}\]/);
  assert.match(source, /draft\.run_inputs = \{ \[`\$\{node\.node_id\}\.seconds`\]: 8 \}/);
  assert.match(profile, /await waitForState\(\['running'\]\);[\s\S]*await invokeRunControl\('cancel'\)/);
  assert.match(profile, /navigateInstalledSurface\(frameHost, 'studio-lifecycle', 20_000\)/);
  assert.match(profile, /observation\.lifecycle_hub_run_browser/);
  assert.match(profile, /exerciseStudioLifecycleFailureStates\(frameHost, candidate\)/);
  assert.match(source, /function validStudioBlockedPreviewResult[\s\S]*memory_bindings_not_runtime_resolved/);
  assert.match(profile, /candidate\.fixture_only[\s\S]*blocked_preview_verified/);
  assert.match(profile, /RESOLVED EXECUTION BLOCKED[\s\S]*start_suppressed/);
  assert.match(source, /frameHost\.evaluateContent\(item =>/);
  assert.doesNotMatch(profile, /frameHost\.contentFrame\(/);
  assert.match(source, /pxui\.studio-lifecycle\.field\.agentObjective/);
  assert.match(source, /pxui\.studio-lifecycle\.field\.workflowRunInputsJson/);
  const failureProfile = source.slice(source.indexOf('async function exerciseStudioLifecycleFailureStates'), source.indexOf('async function runInstalledStudioLifecycleProfile'));
  assert.match(failureProfile, /pendingSkillLifecycle = Object\.freeze/);
  assert.match(failureProfile, /passed: false, status: 'rejected'/);
  assert.match(failureProfile, /operationError[\s\S]*Owned request-bound lifecycle failure reproduction/);
  assert.match(failureProfile, /openExactStudioCatalogRow\(frameHost, candidate\)[\s\S]*await wait\(120\)/);
  assert.match(failureProfile, /#modal-root \.control-modal[\s\S]*!modal\.querySelector\('\[role="alert"\]'\)[\s\S]*text\.includes\(item\.identity\)[\s\S]*text\.includes\(item\.version\)/);
  assert.doesNotMatch(failureProfile, /operateStudioRevision/);
});

test('owned Studio lifecycle maps all four abstract lifecycle paths to physical exact-kind evidence', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const probe = source.slice(source.indexOf('function studioLifecycleControlProbe'), source.indexOf('async function runInstalledStudioLifecycleProfile'));
  for (const [pathId, kind] of [['path.1', 'agent'], ['path.2', 'workflow'], ['path.3', 'skill'], ['path.4', 'agent']]) {
    assert.match(probe, new RegExp(`pxui\\.studio-lifecycle\\.lifecycle\\.${pathId.replace('.', '\\.')}[^\\n]+${kind}`));
  }
});

test('predecessor-bound Studio revisions require a real content edit before save', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '90-controller.js'), 'utf8');
  assert.match(source, /const unchangedPredecessor = Boolean\(studioVersionAllocation\) && !studioDraftDirty/);
  assert.match(source, /save\.disabled = !validation\.valid \|\| unchangedPredecessor/);
  assert.match(source, /predecessorBound \? 'disabled title="Change this predecessor-bound revision/);
  assert.match(source, /else updateStudioSaveAvailability\(\)/);
  assert.match(source, /studioEditor\.kind === 'skill'[\s\S]*synchronizeSkillIdentityFiles\(studioEditor\.draft\)[\s\S]*updateStudioSaveAvailability\(\)/);
  const walker = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const revisionProfile = walker.slice(walker.indexOf('async function runInstalledStudioRevisionEditProfile'), walker.indexOf('function validStudioLifecycleResult'));
  assert.match(revisionProfile, /editorBefore[\s\S]*__PX_INSTALLED_REQUESTS__[\s\S]*__PX_INSTALLED_RESPONSES__/);
  assert.match(revisionProfile, /value\?\.type === 'loadStudioRevisionEditor'/);
  assert.match(revisionProfile, /value\?\.type === 'studioOperation'[\s\S]*value\?\.operation === 'next-version'/);
  assert.match(revisionProfile, /value\?\.requestId === request\.requestId[\s\S]*studioRevisionEditorResult/);
  assert.match(revisionProfile, /observation\.candidate_version = allocation\.candidate_version/);
  assert.match(revisionProfile, /__PX_STUDIO_EDITOR_TRANSITIONS__/);
  assert.match(revisionProfile, /response_selection/);
  assert.match(revisionProfile, /revision-editor-transition-terminal/);
  assert.match(revisionProfile, /const unchangedDeadline = Date\.now\(\) \+ 2_000/);
  assert.match(revisionProfile, /unchanged_save_state = await frameHost\.evaluateContent/);
  assert.match(revisionProfile, /save_present: Boolean\(save\), save_disabled: Boolean\(save\?\.disabled\)/);
  assert.match(revisionProfile, /request_count:[\s\S]*response_count:[\s\S]*create_request_count:[\s\S]*draft_dirty:[\s\S]*allocation_present:/);
  assert.match(revisionProfile, /value\?\.type === 'createStudioDraft' && value\?\.kind === studioEditor\?\.kind[\s\S]*before\.create_request_count/);
  assert.doesNotMatch(revisionProfile, /before\.request_count[\s\S]*before\.response_count/);
  assert.match(revisionProfile, /unchanged-save-not-rejected:\$\{JSON\.stringify\(observation\.unchanged_save_state\)\}/);
  assert.match(revisionProfile, /unchanged-save-dispatched:\$\{JSON\.stringify\(observation\.unchanged_save_state\)\}/);
  assert.match(revisionProfile, /const available = Boolean\(save && !save\.disabled\);[\s\S]*if \(available\) save\.click\(\);[\s\S]*dispatched: available/);
  assert.match(revisionProfile, /save_dispatched_atomically/);
  assert.doesNotMatch(revisionProfile, /querySelector\('\[data-action="submitStudioDraft"\]'\)\.click\(\)/);
  assert.match(revisionProfile, /version_conflict_host_dispatch_suppressed/);
  assert.match(revisionProfile, /owned-stale-revision-[\s\S]*response-unmatched[\s\S]*trust_released[\s\S]*active_request_preserved[\s\S]*editor_preserved/);
  assert.match(revisionProfile, /clearWorkingStudioDraft\(kind\)[\s\S]*openExactStudioCatalogRow\(frameHost, candidate\)/);
  assert.match(revisionProfile, /value\?\.type === 'releaseStudioTrust'[\s\S]*value\?\.requestId === staleRequestId/);
  assert.doesNotMatch(revisionProfile, /value\?\.proof === staleProof/);
  assert.match(source, /message\.type === 'studioRevisionEditorResult'[\s\S]*response-unmatched[\s\S]*trustKind: 'version-allocation', proof: message\.allocationProof[\s\S]*return;/);
  assert.match(revisionProfile, /clearWorkingStudioDraft\(kind\)/);
  assert.match(revisionProfile, /studioSaveRequest = \{ requestId, kind: item\.kind \}/);
  assert.match(revisionProfile, /value\?\.allocation\?\.kind === item\.kind[\s\S]*studioOperationResult[\s\S]*value\?\.operation === 'next-version'[\s\S]*value\?\.result\?\.kind === item\.kind/);
  assert.match(revisionProfile, /boundAllocation = allocationResponse\?\.allocation \|\| allocationResponse\?\.result/);
  assert.match(revisionProfile, /createDispatchesBefore[\s\S]*type === 'createStudioDraft'[\s\S]*createDispatchesAfter[\s\S]*hostDispatchSuppressed/);
  assert.match(revisionProfile, /studioVersionConflict/);
  assert.match(revisionProfile, /acceptStudioVersionSuggestion/);
  assert.match(revisionProfile, /studioVersionAllocationProof = null;[\s\S]*studioVersionProofRequestId = null;[\s\S]*forkStudioCandidate/);
  assert.match(revisionProfile, /forkStudioCandidate/);
  assert.match(revisionProfile, /releaseStudioTrust/);
  assert.match(revisionProfile, /finally[\s\S]*studioSaveRequest = null[\s\S]*vscode\.postMessage\(\{ type: 'releaseStudioTrust'/);
});

test('owned installed Knowledge lifecycle accepts only exact typed states and canonical heads', () => {
  const hashA = 'a'.repeat(64); const hashB = 'b'.repeat(64);
  const proposal = { schema_version: 'px.knowledge-proposal/1.0', proposal_id: 'proposal:one', candidate_sha256: hashA, state: 'candidate' };
  assert.equal(validKnowledgeLifecycleResult('propose', proposal), true);
  assert.equal(validKnowledgeLifecycleResult('verify', { ...proposal, state: 'verified' }, { proposal_id: proposal.proposal_id, candidate_sha256: hashA }), true);
  assert.equal(validKnowledgeLifecycleResult('approve', { ...proposal, state: 'approved' }), true);
  assert.equal(validKnowledgeLifecycleResult('promote', { ...proposal, state: 'promoted' }), true);
  assert.equal(validKnowledgeLifecycleResult('reject', { ...proposal, state: 'rejected' }), true);
  assert.equal(validKnowledgeLifecycleResult('verify', { ...proposal, state: 'approved' }), false);
  assert.equal(validKnowledgeLifecycleResult('promote', { ...proposal, candidate_sha256: 'bad', state: 'promoted' }), false);
  const rollback = { schema_version: 'px.knowledge-rollback/1.0', from_sha256: hashB, to_sha256: hashA, hard_delete: false };
  assert.equal(validKnowledgeLifecycleResult('rollback', rollback, { from_sha256: hashB, to_sha256: hashA }), true);
  assert.equal(validKnowledgeLifecycleResult('rollback', { ...rollback, hard_delete: true }), false);
  assert.equal(validKnowledgeLifecycleResult('recover', { schema_version: 'px.knowledge-recovery/1.0', valid: true }), true);
  const browse = { schema_version: 'px.knowledge-core-control/1.0', proposals: [], canonical: [{ record_id: 'knowledge:one', candidate_sha256: hashA }] };
  assert.equal(validKnowledgeLifecycleResult('browse', browse), true);
  assert.equal(knowledgeBrowseHasHead(browse, 'knowledge:one', hashA), true);
  assert.equal(knowledgeBrowseHasHead(browse, 'knowledge:one', hashB), false);
});

test('Knowledge lifecycle evidence excludes learning controls and requires a real webview restart for reload evidence', () => {
  const controls = [
    'pxui.knowledge-core.form.proposal',
    'pxui.knowledge-core.form.learningObservation',
    'pxui.knowledge-core.lifecycle.path.2',
    'pxui.knowledge-core.lifecycle.path.1',
    'pxui.knowledge-core.persistence.authoritativeState',
    'pxui.knowledge-core.reload_reopen.authoritativeState'
  ].map(control_id => ({
    control_id, surface_id: 'knowledge-core', kind: control_id.includes('.form.') ? 'form' : control_id.includes('.lifecycle.') ? 'lifecycle' : control_id.includes('.persistence.') ? 'persistence' : 'reload_reopen',
    stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['open_load', 'failure_handling'].includes(stage) ? 'required' : 'not_applicable_with_evidence']))
  }));
  const probe = knowledgeLifecycleControlProbe({ controls }, { rendered: true, attempted: true, completed: true, webview_restarted: true, invalid_proposal_rejected: true, errors: [] });
  const admitted = new Set(probe.records.map(record => record.control_id));
  assert.equal(admitted.has('pxui.knowledge-core.form.proposal'), true);
  assert.equal(admitted.has('pxui.knowledge-core.lifecycle.path.2'), true);
  assert.equal(admitted.has('pxui.knowledge-core.persistence.authoritativeState'), true);
  assert.equal(admitted.has('pxui.knowledge-core.form.learningObservation'), false);
  assert.equal(admitted.has('pxui.knowledge-core.lifecycle.path.1'), false);
  assert.equal(admitted.has('pxui.knowledge-core.reload_reopen.authoritativeState'), true);
  assert.ok(probe.records.every(record => record.interaction_chain.failure_handling.state === 'present'));
  const withoutRestart = knowledgeLifecycleControlProbe({ controls }, { rendered: true, attempted: true, completed: true, webview_restarted: false, invalid_proposal_rejected: true, errors: [] });
  assert.equal(withoutRestart.records.find(record => record.control_id === 'pxui.knowledge-core.reload_reopen.authoritativeState').interaction_chain.open_load.state, 'missing');
});

test('owned Learning lifecycle accepts only exact pipeline states and scopes its controls', () => {
  const base = { schema_version: 'px.learning-pipeline/1.0', pipeline_id: 'learning:one' };
  assert.equal(validLearningLifecycleResult('observe-experience', { ...base, state: 'evidence' }), true);
  assert.equal(validLearningLifecycleResult('record-trial', { ...base, state: 'trialing' }, { pipeline_id: 'learning:one' }), true);
  assert.equal(validLearningLifecycleResult('record-trial', { ...base, state: 'confidence-passed' }), true);
  assert.equal(validLearningLifecycleResult('admit-learning', { ...base, state: 'admitted', knowledge_proposal_id: 'proposal:one' }), true);
  assert.equal(validLearningLifecycleResult('measure-reuse', { ...base, state: 'canonical', reuse_measurements: [] }), true);
  assert.equal(validLearningLifecycleResult('final-validate', { ...base, state: 'validation-blocked' }), false);
  assert.equal(validLearningLifecycleResult('admit-learning', { ...base, state: 'admitted' }), false);
  const controls = [
    ['pxui.knowledge-core.action.learningObserve', 'action'],
    ['pxui.knowledge-core.form.learningObservation', 'form'],
    ['pxui.knowledge-core.lifecycle.path.1', 'lifecycle'],
    ['pxui.knowledge-core.form.proposal', 'form'],
    ['pxui.knowledge-core.reload_reopen.authoritativeState', 'reload_reopen']
  ].map(([control_id, kind]) => ({ control_id, surface_id: 'knowledge-core', kind, label: control_id.split('.').at(-1), stage_policy: Object.fromEntries(STAGES.map(stage => [stage, stage === 'failure_handling' ? 'required' : 'not_applicable_with_evidence'])) }));
  const probe = learningLifecycleControlProbe({ controls }, { rendered: true, attempted: true, completed: true, invalid_form_rejected: true, errors: [] });
  assert.deepEqual(probe.records.map(record => record.control_id), controls.slice(0, 3).map(control => control.control_id));
  assert.ok(probe.records.every(record => record.interaction_chain.failure_handling.state === 'present'));
});

test('owned Knowledge and Learning profiles attribute the exact fields they physically exercise', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const learning = source.slice(source.indexOf('function learningLifecycleControlProbe'), source.indexOf('async function runInstalledLearningLifecycleProfile'));
  const knowledge = source.slice(source.indexOf('function knowledgeLifecycleControlProbe'), source.indexOf('async function waitForKnowledgeProposalRejection'));
  for (const field of ['applicability', 'challengerJson', 'trialEvidence', 'researchReferencesJson', 'finalValidationEvidence', 'partialUnits']) {
    assert.match(learning, new RegExp(`'${field}'`));
  }
  for (const id of ['pxui.knowledge-core.field.knowledgeId', 'pxui.knowledge-core.field.rollbackEvidenceRefs', 'pxui.knowledge-core.field.knowledgeRejectReason']) {
    assert.match(knowledge, new RegExp(id.replaceAll('.', '\\.')));
  }
});

test('owned coordination and memory profile requires operation-exact typed receipts', () => {
  const response = (event, receipt, authorization = undefined) => ({ result: { state: { schema_version: 'px.coordination-state/1.0' }, event: { operation: event }, result: { receipt } }, authorization });
  assert.equal(validCoordinationResult('createParallelPlan', response('parallel-plan-created', { plan_id: 'plan:one', tasks: 2 }), { event: 'parallel-plan-created' }), true);
  assert.equal(validCoordinationResult('claimCoordinationTask', response('task-claimed', { task_id: 'task-one', claim_id: 'claim:one', authority: 'local' }), { event: 'task-claimed', task_id: 'task-one' }), true);
  assert.equal(validCoordinationResult('recordTaskProgress', response('task-progress-recorded', { id: 'progress:one', status: 'completed' }), { event: 'task-progress-recorded' }), true);
  assert.equal(validCoordinationResult('reconcileCoordinationTask', response('task-reconciled', { task_id: 'task-one', conflicts_resolved: true }), { event: 'task-reconciled', task_id: 'task-one' }), true);
  assert.equal(validCoordinationResult('releaseCoordinationTask', response('task-released', { task_id: 'task-two', released: true }, { confirmed: true }), { event: 'task-released', task_id: 'task-two' }), true);
  assert.equal(validCoordinationResult('captureCoordinationMemory', response('memory-captured', { memory_id: 'memory:one', layer: 'project', lifecycle: 'proposed' }), { event: 'memory-captured' }), true);
  assert.equal(validCoordinationResult('releaseCoordinationTask', response('task-released', { task_id: 'task-two', released: true }, { confirmed: false }), { event: 'task-released', task_id: 'task-two' }), false);
  const controls = [
    ['pxui.workflows.action.submitParallelPlan', 'workflows', 'action'],
    ['pxui.workflows.form.parallelPlan', 'workflows', 'form'],
    ['pxui.workflows.field.planObjective', 'workflows', 'field'],
    ['pxui.workflows.indicator.activePlan', 'workflows', 'indicator'],
    ['pxui.workflows.reload_reopen.authoritativeState', 'workflows', 'reload_reopen'],
    ['pxui.memory.action.submitMemory', 'memory', 'action'],
    ['pxui.memory.form.captureMemory', 'memory', 'form'],
    ['pxui.memory.form.queryFilter', 'memory', 'form']
  ].map(([control_id, surface_id, kind]) => ({ control_id, surface_id, kind, stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['open_load', 'failure_handling'].includes(stage) ? 'required' : 'not_applicable_with_evidence'])) }));
  const probe = coordinationMemoryControlProbe({ controls }, { rendered: true, attempted: true, completed: true, webview_restarted: true, invalid_release_rejected: true, invalid_memory_rejected: true, errors: [] });
  assert.deepEqual(probe.records.map(record => record.control_id), controls.slice(0, 7).map(control => control.control_id));
  assert.ok(probe.records.every(record => record.interaction_chain.failure_handling.state === 'present'));
  const missingRestart = coordinationMemoryControlProbe({ controls }, { rendered: true, attempted: true, completed: true, webview_restarted: false, invalid_release_rejected: true, invalid_memory_rejected: true, errors: [] });
  assert.equal(missingRestart.records[0].interaction_chain.open_load.state, 'missing');
});

test('owned environment lifecycle attributes the exact rendered record, fields, restoration, and reconstruction', () => {
  const ids = [
    ['pxui.workflows.action.inspectEnvironmentRecord.row', 'action'],
    ['pxui.workflows.action.previewEnvironmentLifecycle', 'action'],
    ['pxui.workflows.field.environmentExactTarget', 'field'],
    ['pxui.workflows.form.environmentLifecycle', 'form'],
    ['pxui.workflows.reload_reopen.authoritativeState', 'reload_reopen'],
    ['pxui.workflows.action.copyTaskHandoff.row', 'action']
  ];
  const controls = ids.map(([control_id, kind]) => ({ control_id, surface_id: 'workflows', kind, stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['open_load', 'failure_handling'].includes(stage) ? 'required' : 'not_applicable_with_evidence'])) }));
  const probe = environmentLifecycleControlProbe({ controls }, { rendered: true, attempted: true, invalid_confirmation_rejected: true, quarantined: true, restored: true, restart_verified: true, temporary_reconciled: true, errors: [] });
  assert.deepEqual(probe.records.map(record => record.control_id), controls.slice(0, 5).map(control => control.control_id));
  assert.ok(probe.records.every(record => record.interaction_chain.failure_handling.state === 'present'));
});

test('read-only skill query profile separates invalid, pending, empty, result, and hydration evidence', () => {
  const ids = [
    ['pxui.skills-tools.action.submitSkillQuery', 'action'],
    ['pxui.skills-tools.action.hydrateSkillCandidate.row', 'action'],
    ['pxui.skills-tools.form.semanticQuery', 'form'],
    ['pxui.skills-tools.indicator.queryPending', 'indicator'],
    ['pxui.skills-tools.indicator.queryNoMatch', 'indicator'],
    ['pxui.skills-tools.indicator.queryResults', 'indicator'],
    ['pxui.skills-tools.action.compareSkillOriginal', 'action']
  ];
  const controls = ids.map(([control_id, kind]) => ({ control_id, surface_id: 'skills-tools', kind, stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['open_load', 'progress_reporting', 'failure_handling'].includes(stage) ? 'required' : 'not_applicable_with_evidence'])) }));
  const observation = { rendered: true, attempted: true, invalid_rejected: true, pending_observed: true, no_match_observed: true, results_observed: true, hydrated: true, completed: true, errors: [] };
  const probe = skillQueryControlProbe({ controls }, observation);
  assert.deepEqual(probe.records.map(record => record.control_id), controls.slice(0, 6).map(control => control.control_id));
  assert.ok(probe.records.every(record => record.interaction_chain.open_load.state === 'present'));
  assert.ok(probe.records.every(record => record.interaction_chain.progress_reporting.state === 'present'));
  assert.ok(probe.records.every(record => record.interaction_chain.failure_handling.state === 'present'));
});

test('read-only catalog pagination binds real offsets and restores the normal query denominator', () => {
  const surfaces = [
    ['agents', 'pxui.agents.action.catalogNext', 'action'],
    ['agents', 'pxui.agents.action.catalogPrevious', 'action'],
    ['agents', 'pxui.agents.indicator.catalogPage', 'indicator'],
    ['workflows', 'pxui.workflows.action.catalogNext', 'action'],
    ['workflows', 'pxui.workflows.action.catalogPrevious', 'action'],
    ['workflows', 'pxui.workflows.indicator.catalogPage', 'indicator'],
    ['skills-tools', 'pxui.skills-tools.action.catalogNext', 'action'],
    ['skills-tools', 'pxui.skills-tools.action.catalogPrevious', 'action'],
    ['skills-tools', 'pxui.skills-tools.indicator.catalogPage', 'indicator'],
    ['diagnostics', 'pxui.diagnostics.action.catalogNext', 'action'],
    ['diagnostics', 'pxui.diagnostics.action.catalogPrevious', 'action'],
    ['diagnostics', 'pxui.diagnostics.indicator.catalogPage', 'indicator']
  ];
  const controls = surfaces.map(([surface_id, control_id, kind]) => ({ control_id, surface_id, kind, stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['open_load', 'failure_handling', 'recovery_rollback'].includes(stage) ? 'required' : 'not_applicable_with_evidence'])) }));
  const observations = ['agents', 'workflows', 'skills-tools', 'diagnostics'].map(surface => ({ surface, rendered: true, attempted: true, first_page_previous_disabled: true, forward: true, backward: true, restored: true, errors: [] }));
  const probe = catalogPaginationControlProbe({ controls }, observations);
  assert.equal(probe.records.length, 12);
  assert.ok(probe.records.every(record => record.interaction_chain.open_load.state === 'present'));
  assert.ok(probe.records.every(record => record.interaction_chain.failure_handling.state === 'present'));
  assert.ok(probe.records.every(record => record.interaction_chain.recovery_rollback.state === 'present'));
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledCatalogPaginationProfile'), source.indexOf('const INSTALLED_CODEX_HANDOFF_IDS'));
  assert.match(profile, /evaluateContent\(kind => requestCatalog\(kind, \{ offset: 0, limit: 1 \}\)/);
  assert.match(profile, /evaluateContent\(kind => requestCatalog\(kind, \{ query: '', status: '', offset: 0, limit: 50 \}\)/);
  assert.match(profile, /surface: 'diagnostics', route: 'diagnostics', kind: 'enterprise-integrations'/);
  assert.doesNotMatch(profile, /\.eval\(/);
  const agentControls = controls.filter(control => control.surface_id === 'agents');
  const focused = catalogPaginationControlProbe({ controls: agentControls }, [{ surface: 'agents', rendered: true, attempted: true, first_page_previous_disabled: true, forward: true, backward: true, restored: true, lifecycle_filter_required: true, lifecycle_filter_verified: true, empty_state_verified: true, filter_restored: true, errors: [] }], new Set(['agents']));
  assert.equal(focused.records.length, 3);
  assert.ok(focused.records.every(record => record.interaction_chain.open_load.state === 'present'));
  assert.match(profile, /data-catalog-status[\s\S]*lifecycle_filter_verified[\s\S]*No records match this lifecycle and search filter[\s\S]*filter_restored/);
  assert.match(source, /\(!focusedProfileOnly \|\| studioLifecycleOnly\)[\s\S]*new Set\(\['agents'\]\)/);
});

test('owned observation-state profile covers the fourteen bounded reversible state controls', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('const INSTALLED_OBSERVATION_STATE_IDS'), source.indexOf('const INSTALLED_CODEX_HANDOFF_IDS'));
  for (const id of [
    'pxui.activity.action.filterActivityCorrelation.row', 'pxui.activity.indicator.captureActive',
    'pxui.activity.indicator.staleOperations', 'pxui.agent-studio.field.model.host_model',
    'pxui.agent-studio.indicator.workingGraphRequiresPythonCompile', 'pxui.knowledge-graph.action.graphLoadAll',
    'pxui.knowledge-graph.action.graphLoadMore', 'pxui.knowledge-graph.field.graphRelation',
    'pxui.memory.action.memoryNext', 'pxui.memory.action.memoryPrevious',
    'pxui.plugins.indicator.inlineInventoryError', 'pxui.projects.indicator.mapErrors',
    'pxui.sidebar.action.provider-next', 'pxui.sidebar.action.provider-previous'
  ]) assert.match(profile, new RegExp(id.replaceAll('.', '\\.')));
  assert.match(profile, /requestGraph\(\{ view: 'repository',[\s\S]*maxNodes: 1, maxEdges: 1/);
  assert.match(profile, /type: 'memoryQuery'[\s\S]*offset: 0, limit: 1/);
  assert.match(profile, /state\.memoryOffset = -59[\s\S]*Number\(next\.result\?\.offset\) === 1[\s\S]*Number\(previous\.result\?\.offset\) === 0/);
  assert.match(profile, /clearWorkingStudioDraft\('agent'\)/);
  assert.match(profile, /installedLocalSelectFailureRoundTrip\(frameHost, '\[data-agent-host-model\]'/);
  assert.match(profile, /installedLocalSelectFailureRoundTrip\(frameHost, '\[data-graph-relation\]'/);
  assert.match(profile, /invalidRejected && fieldState\.changed && fieldState\.restored && fieldState\.fixtureRemoved/);
  assert.match(profile, /invalidRejected && relation\.changed && relation\.restored && relation\.fixtureRemoved/);
  assert.match(source, /option\.dataset\.pxOwnedSelectFixture = fixtureToken[\s\S]*finally[\s\S]*data-px-owned-select-fixture[\s\S]*fixtureRemoved/);
  const selectRoundTrip = source.slice(source.indexOf('async function installedLocalSelectFailureRoundTrip'), source.indexOf('function observationStateControlProbe'));
  assert.match(selectRoundTrip, /const accepted = control\.value === item\.value;[\s\S]*dispatchEvent\(new frame\.contentWindow\.Event\('input'/);
  assert.match(selectRoundTrip, /dispatchSelectValue\(baseline\.alternate\)[\s\S]*dispatchSelectValue\(baseline\.value\)[\s\S]*waitForBaseline\(\)/);
  assert.doesNotMatch(selectRoundTrip, /installedLocalInputRoundTrip/);
  assert.match(profile, /frame\.contentDocument\.querySelector\(item\.selector\)\?\.value === item\.value/);
  assert.match(profile, /provider-next[\s\S]*provider-previous[\s\S]*restored/);
  assert.match(profile, /px-owned-active-observation[\s\S]*filterActivityCorrelation[\s\S]*activityResult/);
  assert.match(profile, /PX owned reversible extension-inventory failure[\s\S]*environmentInventory/);
  assert.match(profile, /PX owned reversible project-map failure[\s\S]*requestInstalledRefreshBound/);
  assert.match(source, /timedProfile\('observation-state-scenarios'/);
  assert.match(source, /observation_state_observations/);
  assert.ok(source.indexOf('let sidebar = focusedProfileOnly') < source.indexOf("timedProfile('observation-state-scenarios'"), 'the sidebar frame owner must exist before the observation-state profile is invoked');
});

test('coordination release waits and clicks atomically across a stale disabled render', async () => {
  const control = {
    disabled: true, offsetWidth: 20, offsetHeight: 10, dataset: { action: 'releaseTask', taskId: 'task-release' }, clicks: 0,
    getClientRects: () => [{ width: 20, height: 10 }], click() { this.clicks += 1; }
  };
  let evaluations = 0;
  const frameHost = { evaluate: async (operation, argument) => {
    evaluations += 1;
    const result = operation({ contentDocument: { querySelector: selector => selector === argument ? control : null } }, argument);
    if (evaluations === 1) control.disabled = false;
    return result;
  } };
  assert.equal(await clickWhenKnowledgeControlReady(frameHost, '[data-action="releaseTask"][data-task-id="task-release"]', 1_000), true);
  assert.equal(control.clicks, 1);
  assert.ok(evaluations >= 2, 'the stale disabled render must not be clicked');
});

test('coordination profile renews the exact claim and host-boundary controls have typed owners', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /renewCoordinationClaim[\s\S]*task-lease-renewed[\s\S]*coordination-renew-receipt-invalid/);
  assert.match(source, /const releaseSelector = `[\s\S]*clickWhenKnowledgeControlReady\(frameHost, releaseSelector, timeoutMs\)/);
  assert.match(source, /navigateInstalledSurface\(frameHost, 'memory', timeoutMs\)[\s\S]*waitForKnowledgeControl\(frameHost, '\[data-action="captureMemory"\]'\)[\s\S]*memory-capture-control-unavailable/);
  assert.match(source, /data-action="closeModal"[\s\S]*navigateInstalledSurface\(frameHost, 'memory', timeoutMs\)[\s\S]*data-action="captureMemory"/);
  const matrix = { controls: [{ control_id: 'pxui.projects.action.openEngineRoot', surface_id: 'projects', kind: 'action', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, stage === 'open_load' ? 'required' : 'not_applicable_with_evidence'])) }] };
  const probe = hostBoundaryControlProbe(matrix, { operations: { 'pxui.projects.action.openEngineRoot': { rendered: true, attempted: true, acknowledged: true, dashboard_reopened: true, errors: [] } } });
  assert.equal(probe.records.length, 1);
  assert.equal(probe.records[0].interaction_chain.open_load.state, 'present');
  assert.match(source, /host_boundary_profile: hostBoundaryProfile/);
});

test('native workbench keyboard fallback requires an exact newly captured outbound request and admitted action', () => {
  const admitted = [
    'Cancel', 'Set up and run', 'Build graph', 'Enable offline metadata', 'Disable pack metadata', 'Stage candidates',
    'Authorize native install', 'Authorize native update', 'Authorize native uninstall', 'Authorize exact rollback',
    'Authorize conflict route'
  ];
  for (const label of admitted) {
    assert.equal(nativeWorkbenchKeyboardActionAdmitted(label), true, label);
    assert.equal(nativeWorkbenchKeyboardFallbackAdmitted(1, label), true, label);
    assert.equal(nativeWorkbenchKeyboardFallbackAdmitted(0, label), false, label);
  }
  assert.equal(nativeWorkbenchKeyboardActionAdmitted('Authorize whatever is focused'), false);
  assert.equal(nativeWorkbenchKeyboardFallbackAdmitted(1, 'Authorize whatever is focused'), false);
  assert.equal(nativeWorkbenchKeyboardFallbackAdmitted(-1, 'Cancel'), false);
  assert.equal(nativeWorkbenchKeyboardFallbackAdmitted(1.5, 'Cancel'), false);
  const admittedRequests = [
    ['Cancel', 'enterprisePackToggle'], ['Cancel', 'buildRepositoryGraph'], ['Build graph', 'buildRepositoryGraph'],
    ['Enable offline metadata', 'enterprisePackToggle'], ['Disable pack metadata', 'enterprisePackToggle'],
    ['Stage candidates', 'teamPackPreview'], ['Authorize native install', 'extensionLifecycleExecute'],
    ['Authorize native update', 'extensionUpdateExecute'], ['Authorize native uninstall', 'extensionUninstallExecute'],
    ['Authorize exact rollback', 'extensionRollbackExecute'], ['Authorize conflict route', 'extensionConflictResolutionExecute']
  ];
  for (const [label, type] of admittedRequests) assert.equal(nativeWorkbenchRequestFallbackAdmitted({ type }, label, type), true, `${label}:${type}`);
  assert.equal(nativeWorkbenchRequestFallbackAdmitted({ type: 'buildRepositoryGraph' }, 'Stage candidates', 'buildRepositoryGraph'), false);
  assert.equal(nativeWorkbenchRequestFallbackAdmitted({ type: 'enterprisePackToggle' }, 'Cancel', 'buildRepositoryGraph'), false);
  assert.equal(nativeWorkbenchRequestFallbackAdmitted(null, 'Cancel', 'enterprisePackToggle'), false);

  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const controller = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '90-controller.js'), 'utf8');
  const controllerBoundary = controller.slice(0, controller.indexOf('const app ='));
  assert.match(controllerBoundary, /const vscodeApi = acquireVsCodeApi\(\)/);
  assert.match(controllerBoundary, /px-dashboard-outbound-request/);
  assert.match(controllerBoundary, /\['requestId', 'operation', 'kind', 'status', 'sort', 'exactTarget', 'packId', 'trustKind', 'proof'\]/);
  assert.match(controllerBoundary, /\['offset', 'limit'\][\s\S]*Number\.isSafeInteger/);
  assert.match(controllerBoundary, /typeof value\.enabled === 'boolean'/);
  assert.doesNotMatch(controllerBoundary, /token|payload|content|path/);
  assert.match(controllerBoundary, /vscodeApi\.postMessage\(message\)/);
  const instrumentation = source.slice(source.indexOf('async function instrumentInstalledBridge'), source.indexOf('async function reopenPacifyDashboardFromOwnedUi'));
  assert.match(instrumentation, /inner\.__PX_INSTALLED_REQUESTS__ \|\|= \[\]/);
  assert.match(instrumentation, /px-dashboard-outbound-request[\s\S]*JSON\.parse\(JSON\.stringify\(event\.detail\)\)/);
  const helper = source.slice(source.indexOf('const NATIVE_WORKBENCH_DIALOG_SELECTOR'), source.indexOf('async function clickNativeStudioSetupAction'));
  assert.match(helper, /NATIVE_WORKBENCH_MODAL_BLOCKER_SELECTOR = '\.monaco-modal-editor-block:visible'/);
  assert.match(helper, /native_modal_blocker_count: pageNativeModalBlockerCount/);
  assert.match(helper, /return \{ pages, native_modal_blocker_count: nativeModalBlockerCount, dashboard \}/);
  assert.match(helper, /const dialog = await findNativeWorkbenchDialog[\s\S]*const blockerCount = await visibleNativeWorkbenchModalBlockerCount/);
  assert.match(helper, /findInstalledOutboundRequest\(diagnostics\.frameHost, diagnostics\.requestOffset, diagnostics\.requestType\)/);
  assert.match(helper, /let requestObservedAt = null/);
  assert.match(helper, /requestObservedAt \?\?= Date\.now\(\)[\s\S]*Date\.now\(\) - requestObservedAt >= 750[\s\S]*__px_owned_native_keyboard_only: true/);
  assert.match(helper, /else requestObservedAt = null/);
  assert.match(helper, /dialog\?\.__px_owned_native_keyboard_only === true[\s\S]*findInstalledOutboundRequest\(dialog\.frame_host, dialog\.request_offset, dialog\.request_type\)[\s\S]*owned-native-workbench-keyboard-fallback-not-admitted/);
  assert.match(helper, /requestOwnedNativeInput\(label, request, \{ focusTraversal: label !== 'Cancel' \}\)/);
  assert.match(helper, /workbench\.bringToFront\(\)[\s\S]*wait\(100\)[\s\S]*requestOwnedNativeInput\(label, request, \{ focusTraversal: label !== 'Cancel' \}\)/);
  assert.doesNotMatch(helper, /keyboard\.press\(label === 'Cancel'/);
  assert.match(helper, /visibleAdmittedNativeWorkbenchAction\(dialog\)[\s\S]*blockerCount === 0 && !admittedAction[\s\S]*visibleAdmittedNativeWorkbenchAction\(remaining\)[\s\S]*remainingBlockers === 0 && !remainingAction/);
  assert.match(helper, /candidate\.isVisible[\s\S]*candidate\.click\(\{ timeout: 3_000 \}\)[\s\S]*return true[\s\S]*label === 'Cancel'[\s\S]*nativeWorkbenchRequestFallbackAdmitted\(request, label[\s\S]*exact-action-not-visible/);

  const enterprise = source.slice(source.indexOf('async function runInstalledEnterpriseProfile'), source.indexOf('const INSTALLED_VALIDATION_CONTROL_IDS'));
  assert.match(enterprise, /responseOffset: beforeCancel, requestOffset: requestBeforeCancel, requestType: 'enterprisePackToggle', keyboardAction: 'Cancel'/);
  assert.match(enterprise, /responseOffset: beforeCancel, requestOffset: requestBeforeApproval, requestType: 'enterprisePackToggle', keyboardAction: label/);
  assert.match(enterprise, /toggle\.completed = after\?\.result != null;[\s\S]*closeModal[\s\S]*data-surface[\s\S]*enterprisePackToggle[\s\S]*const restoreBefore/);
  assert.match(enterprise, /responseOffset: restoreBefore, requestOffset: requestBeforeRestore, requestType: 'enterprisePackToggle', keyboardAction: restoreLabel/);
  assert.match(enterprise, /responseOffset: stageBefore, requestOffset: requestBeforeStage, requestType: 'teamPackPreview', keyboardAction: 'Stage candidates'/);
  const projects = source.slice(source.indexOf('async function runInstalledProjectsProfile'), source.indexOf('function graphProjectionIdentity'));
  assert.match(projects, /responseOffset: cancelBefore, requestOffset: requestBeforeCancel, requestType: 'buildRepositoryGraph', keyboardAction: 'Cancel'/);
  assert.match(projects, /responseOffset: before, requestOffset: requestBeforeBuild, requestType: 'buildRepositoryGraph', keyboardAction: 'Build graph'/);
  const plugins = source.slice(source.indexOf('async function runInstalledPluginMutationProfile'), source.indexOf('function knowledgeLifecycleControlProbe'));
  assert.match(plugins, /responseOffset: executeBefore, requestOffset: requestBeforeExecute, requestType: spec\.executeOperation, keyboardAction: spec\.nativeApproval/);
  assert.match(plugins, /responseOffset: executeBefore, requestOffset: requestBeforeExecute, requestType: 'extensionConflictResolutionExecute', keyboardAction: 'Authorize conflict route'/);
});

test('project map profile requires an exact physical attempt for all three build entry points', () => {
  const matrix = { controls: ['pxui.projects.action.buildRepositoryGraph', 'pxui.knowledge-graph.action.buildRepositoryGraph', 'pxui.diagnostics.action.dynamicRepair.buildRepositoryGraph'].map(control_id => ({ control_id, surface_id: control_id.split('.')[1], kind: 'action', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, 'not_applicable_with_evidence'])) })) };
  const empty = projectsControlProbe(matrix, { errors: [] });
  assert.equal(empty.records.length, 3);
  assert.ok(empty.records.every(record => record.rendered === false && record.attempted === false));
  const exact = Object.fromEntries(matrix.controls.map(control => [control.control_id, true]));
  const observed = projectsControlProbe(matrix, { rendered: true, attempted: true, rendered_controls: exact, attempted_controls: exact, errors: [] });
  assert.ok(observed.records.every(record => record.rendered === true && record.attempted === true));
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledProjectsProfile'), source.indexOf('function graphProjectionIdentity'));
  assert.equal((profile.match(/clickNativeWorkbenchDialogAction\(workbench, cancelledDialog, 'Cancel'\)/g) || []).length, 1);
  assert.equal((profile.match(/clickNativeWorkbenchDialogAction\(workbench, projectsCancelledDialog, 'Cancel'\)/g) || []).length, 1);
  assert.match(profile, /cancelled_controls\[controlId\][\s\S]*!cancelResponses\.some\(value => value\?\.type === 'graphBuildResult'\)/);
  assert.match(profile, /cancelled_controls\['pxui\.projects\.action\.buildRepositoryGraph'\][\s\S]*!projectsCancelResponses\.some\(value => value\?\.type === 'graphBuildResult'\)/);
  assert.equal((profile.match(/clickNativeWorkbenchDialogAction\(workbench, dialog, 'Build graph'\)/g) || []).length, 1);
  const dynamicId = 'pxui.diagnostics.action.dynamicRepair.buildRepositoryGraph';
  const dynamicMatrix = { controls: [{ control_id: dynamicId, surface_id: 'diagnostics', kind: 'action', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['failure_handling', 'recovery_rollback'].includes(stage) ? 'required' : 'not_applicable_with_evidence'])) }] };
  const dynamic = projectsControlProbe(dynamicMatrix, { cancelled_controls: { [dynamicId]: true }, errors: [] }).records[0];
  assert.equal(dynamic.interaction_chain.failure_handling.state, 'present');
  assert.equal(dynamic.interaction_chain.recovery_rollback.state, 'present');
});

test('Projects profile owns the current native workbench dialog and cannot strand it', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const helper = source.slice(source.indexOf('async function findNativeWorkbenchDialog'), source.indexOf('async function clickNativeWorkbenchDialogAction'));
  assert.match(helper, /workbench\.context\(\)\.pages\(\)/);
  assert.match(source, /NATIVE_WORKBENCH_DIALOG_SELECTOR = '[^']*\.dialog-container:visible[^']*\[role="dialog"\]:visible'/);
  assert.match(helper, /getByText\(expected\)/);
  assert.match(helper, /nativeWorkbenchDialogInventory[\s\S]*visible_dialogs[\s\S]*message_matches[\s\S]*visible_actions[\s\S]*responses[\s\S]*active_surface/);
  assert.match(helper, /owned-native-workbench-dialog-timeout:[\s\S]*JSON\.stringify\(inventory\)/);
  assert.match(helper, /owned-native-workbench-dialog-recovery-timeout/);
  const profile = source.slice(source.indexOf('async function runInstalledProjectsProfile'), source.indexOf('function graphProjectionIdentity'));
  assert.match(profile, /waitForNativeWorkbenchDialog\(workbench, \/Build or refresh the bounded repository architecture graph\/i, 15_000, \{ frameHost, responseOffset:/);
  assert.match(profile, /dismissOwnedNativeWorkbenchDialog/);
  assert.doesNotMatch(profile, /workbench\.locator\('\.monaco-dialog-box:visible'/);
});

test('owned cleanup profile accepts only successful non-permanent Recycle Bin receipts', () => {
  const valid = { receipt: { schema_version: '2.0', disposition: 'recycle', hard_delete: false, state: 'completed', resources_reclaimed: 1, resources_uncertain: 0, errors: [], resources: [{ result: 'moved-to-recycle-bin' }] } };
  assert.equal(validCleanupResult(valid), true);
  assert.equal(validCleanupResult({ receipt: { ...valid.receipt, disposition: 'permanent', hard_delete: true } }), false);
  assert.equal(validCleanupResult({ receipt: { ...valid.receipt, resources_uncertain: 1 } }), false);
  assert.equal(validCleanupResult({ receipt: { ...valid.receipt, resources: [{ result: 'failed-restored' }] } }), false);
  const permanent = { receipt: { ...valid.receipt, disposition: 'permanent', hard_delete: true, resources: [{ result: 'permanently-reclaimed' }] } };
  assert.equal(validPermanentCleanupResult(permanent), true);
  assert.equal(validPermanentCleanupResult({ receipt: { ...permanent.receipt, hard_delete: false } }), false);
  const controls = [
    ['pxui.runtime-core.action.cleanupManager', 'action'], ['pxui.runtime-core.action.cleanupRecycle', 'action'],
    ['pxui.runtime-core.action.cleanupSelectAll', 'action'],
    ['pxui.runtime-core.form.cleanupSelection', 'form'], ['pxui.runtime-core.indicator.cleanupReceipt', 'indicator'],
    ['pxui.runtime-core.action.cleanupPermanent', 'action'], ['pxui.runtime-core.persistence.authoritativeState', 'persistence']
  ].map(([control_id, kind]) => ({ control_id, surface_id: 'runtime-core', kind, stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['open_load', 'failure_handling'].includes(stage) ? 'required' : 'not_applicable_with_evidence'])) }));
  const probe = cleanupControlProbe({ controls }, { rendered: true, attempted: true, completed: true, webview_restarted: true, invalid_selection_rejected: true, select_all_round_trip: true, permanent_refused_without_authorization: true, permanent_completed: false, reclaimed_absent_after_restart: true, result: valid, errors: [] });
  assert.deepEqual(probe.records.map(record => record.control_id), controls.map(control => control.control_id));
  assert.ok(probe.records.every(record => record.interaction_chain.failure_handling.state === 'present'));
  assert.equal(probe.records.find(record => record.control_id.endsWith('cleanupPermanent')).interaction_chain.open_load.state, 'missing');
  assert.equal(probe.records.find(record => record.control_id.endsWith('cleanupPermanent')).authority_skipped, true);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledCleanupProfile'), source.indexOf('function validPluginLifecycleObservation'));
  assert.match(profile, /PX_OPERATIONAL_IRREVERSIBLE_CLEANUP_AUTHORIZED/);
  assert.match(profile, /cleanup-permanent-refusal-not-proven/);
  assert.match(profile, /cleanup-select-all-round-trip-failed/);
  assert.match(profile, /selectAll\.click\(\);[\s\S]*candidates = \[\.\.\.document\.querySelectorAll\('\[data-cleanup-id\]'\)\][\s\S]*const clearAll = document\.querySelector\('\[data-action="cleanupSelectAll"\]'\)[\s\S]*clearAll\.click\(\);[\s\S]*candidates = \[\.\.\.document\.querySelectorAll\('\[data-cleanup-id\]'\)\]/);
  assert.match(profile, /validPermanentCleanupResult/);
  assert.match(profile, /requestBeforeExecute = await installedOutboundRequestOffset/);
  assert.match(profile, /waitForNativeWorkbenchDialog\(workbench, \/Move to Recycle Bin\/i, 15_000, \{ frameHost, responseOffset: beforeExecute, requestOffset: requestBeforeExecute, requestType: 'executeCleanup', keyboardAction: 'Move to Recycle Bin' \}\)/);
  assert.match(profile, /clickNativeWorkbenchDialogAction\(workbench, dialog, 'Move to Recycle Bin'\)/);
  assert.match(profile, /clickNativeWorkbenchDialogAction\(workbench, permanentDialog, 'Cancel'\)/);
  assert.match(profile, /dismissOwnedNativeWorkbenchDialog\(workbench, \/Move to Recycle Bin\|Permanently Delete\/i\)/);
  assert.doesNotMatch(profile, /workbench\.locator\('\.monaco-dialog-box:visible'/);
  assert.match(source, /'Move to Recycle Bin', new Set\(\['executeCleanup'\]\)/);
  assert.match(source, /'Permanently Delete', new Set\(\['executeCleanup'\]\)/);
  const withoutRestart = cleanupControlProbe({ controls }, { rendered: true, attempted: true, completed: true, webview_restarted: false, invalid_selection_rejected: true, reclaimed_absent_after_restart: true, result: valid, errors: [] });
  assert.equal(withoutRestart.records[0].interaction_chain.open_load.state, 'missing');
});

test('owned cleanup scenario selects only its exact safe disposable cache identity', () => {
  const root = path.resolve('owned-engine');
  const fixture = path.join(root, '.px-operational-recycle', '__pycache__');
  const exact = { id: 'owned', relativePath: '.px-operational-recycle/__pycache__', name: '__pycache__', classification: 'safe-to-delete', retentionRequired: false };
  const unrelated = { ...exact, id: 'other', relativePath: 'pkg/__pycache__' };
  assert.equal(ownedCleanupCandidate({ candidates: [unrelated, exact] }, root, fixture), exact);
  assert.equal(ownedCleanupCandidate({ candidates: [{ ...exact, classification: 'review-required' }] }, root, fixture), null);
  assert.equal(ownedCleanupCandidate({ candidates: [exact] }, root, path.resolve('outside', '__pycache__')), null);
});

test('owned Projects profile binds an exact authoritative map identity across restart', () => {
  const project = { path: 'C:/owned/workspace', map: { map_revision: 'map:one', source_inventory_sha256: 'a'.repeat(64), validation_scope: 'repository', counts: { files: 12, architecture_nodes: 7 } } };
  assert.deepEqual(projectMapIdentity({ project }), { project_path: 'C:/owned/workspace', map_revision: 'map:one', source_inventory_sha256: 'a'.repeat(64), validation_scope: 'repository', files: 12, architecture_nodes: 7 });
  assert.equal(projectMapIdentity({ project: { ...project, map: { ...project.map, source_inventory_sha256: 'invalid' } } }), null);
  const controls = ['persistence', 'reload_reopen'].map(kind => ({ control_id: `pxui.projects.${kind}.authoritativeState`, surface_id: 'projects', kind, stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['user_edit_action', 'input_validation', 'progress_reporting'].includes(stage) ? 'not_applicable_with_evidence' : 'required'])) }));
  const observation = {
    rendered: true, attempted: true, completed: true, webview_restarted: true, exact_reconstruction: true, before_restart: project, after_restart: project, errors: [],
    cancelled_controls: {
      'pxui.projects.action.buildRepositoryGraph': true,
      'pxui.knowledge-graph.action.buildRepositoryGraph': true,
      'pxui.diagnostics.action.dynamicRepair.buildRepositoryGraph': true
    }
  };
  const probe = projectsControlProbe({ controls }, observation);
  assert.equal(probe.eligible_control_count, 2);
  assert.equal(probe.records[0].interaction_chain.persistence.state, 'present');
  assert.equal(probe.records[1].interaction_chain.reload_reopen.state, 'present');
  assert.ok(probe.records.every(record => record.interaction_chain.failure_handling.state === 'present'));
  assert.ok(probe.records.every(record => record.interaction_chain.recovery_rollback.state === 'present'));
  const missingCancellation = projectsControlProbe({ controls }, { ...observation, cancelled_controls: { ...observation.cancelled_controls, 'pxui.projects.action.buildRepositoryGraph': false } });
  assert.equal(missingCancellation.records[0].interaction_chain.failure_handling.state, 'missing');
  assert.equal(projectsControlProbe({ controls }, { ...observation, exact_reconstruction: false }).records[0].interaction_chain.persistence.state, 'missing');
});

test('owned Knowledge Graph profile binds saved-view actions and authoritative graph identity across restart', () => {
  const graph = { available: true, view: 'repository', mode: 'full', source: 'C:/owned/.engineering-bootstrap/project-map/architecture-graph.json', cluster: null, requested_query: '', requested_relation: '', direction: 'both', depth: 1, total_nodes: 2, total_edges: 1, nodes: [{ key: 'file:a' }, { key: 'file:b' }], edges: [{ source: 'file:a', relation: 'imports', target: 'file:b' }] };
  const identity = graphProjectionIdentity(graph);
  assert.match(identity.content_sha256, /^[0-9a-f]{64}$/);
  assert.equal(graphProjectionIdentity({ ...graph, available: false }), null);
  const controls = [
    ...['persistence', 'reload_reopen'].map(kind => ({ control_id: `pxui.knowledge-graph.${kind}.authoritativeState`, surface_id: 'knowledge-graph', kind })),
    { control_id: 'pxui.knowledge-graph.action.graphApplySavedView.row', surface_id: 'knowledge-graph', kind: 'action' },
    { control_id: 'pxui.knowledge-graph.action.graphDeleteSavedView.row', surface_id: 'knowledge-graph', kind: 'action' }
  ].map(control => ({ ...control, stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['user_edit_action', 'input_validation', 'progress_reporting'].includes(stage) ? 'not_applicable_with_evidence' : 'required'])) }));
  const observation = { rendered: true, attempted: true, invalid_rejected: true, saved_view_created: true, saved_view_applied: true, saved_view_deleted: true, completed: true, webview_restarted: true, exact_reconstruction: true, restored: true, before_restart: identity, after_restart: identity, errors: [] };
  const probe = knowledgeGraphControlProbe({ controls }, observation);
  assert.equal(probe.eligible_control_count, 4);
  assert.equal(probe.records[0].interaction_chain.persistence.state, 'present');
  assert.equal(probe.records[0].interaction_chain.failure_handling.state, 'present');
  assert.equal(probe.records[0].interaction_chain.recovery_rollback.state, 'present');
  assert.equal(knowledgeGraphControlProbe({ controls }, { ...observation, exact_reconstruction: false }).records[0].interaction_chain.persistence.state, 'missing');
  assert.equal(knowledgeGraphControlProbe({ controls }, { ...observation, saved_view_applied: false }).records.find(record => record.control_id.includes('graphApplySavedView')).interaction_chain.open_load.state, 'missing');
  const request = { type: 'graphQuery', requestId: 'graph:one' };
  assert.equal(requestBoundGraphResultIdentity(request, { type: 'graphResult', requestId: 'graph:one', result: graph }).terminal, 'result');
  assert.equal(requestBoundGraphResultIdentity(request, { type: 'graphResult', requestId: 'graph:other', result: graph }), null);
  assert.equal(requestBoundGraphResultIdentity(request, { type: 'operationError', operation: 'memoryQuery', requestId: 'graph:one', error: 'wrong operation' }), null);
  assert.equal(requestBoundGraphResultIdentity(request, { type: 'operationError', operation: 'graphQuery', requestId: 'graph:one', error: 'bounded failure' }).terminal, 'error');
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledKnowledgeGraphProfile'), source.indexOf('function systemProjectionIdentity'));
  assert.match(profile, /restartInstalledDashboardWebview/);
  assert.doesNotMatch(profile, /reloadInstalledDashboardWebview/);
});

test('owned Knowledge Graph request waits retry once through the exact physical control', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledKnowledgeGraphProfile'), source.indexOf('function systemProjectionControlProbe'));
  assert.match(profile, /const waitForGraph = async \(offsets, retry\)/);
  assert.match(profile, /\.filter\(value => value\?\.type === 'graphQuery'[\s\S]*\.at\(-1\)/);
  assert.match(profile, /!identity && !retried && Date\.now\(\) >= retryAt/);
  assert.match(profile, /knowledge-graph-retry-control-unavailable/);
  assert.match(profile, /knowledge-graph-retry-saved-view-unavailable/);
});

test('system projection profile binds stable canonical snapshot identity across dashboard restart', () => {
  const snapshot = { schemaVersion: 'px.dashboard/1.0', connected: true, source: { engineRoot: 'C:/owned/engine', version: '1.0.0' }, project: { path: 'C:/owned/workspace', map: { map_revision: 'map:one', source_inventory_sha256: 'a'.repeat(64) } }, extensionIdentity: { source: { tree_sha256: 'b'.repeat(64) } }, repairCampaign: { campaign_id: 'campaign:one', phase: 'repair' }, counts: { tools: 2, agents: 3 } };
  const identity = systemProjectionIdentity(snapshot);
  assert.match(identity.counts_sha256, /^[0-9a-f]{64}$/);
  assert.equal(systemProjectionIdentity({ ...snapshot, connected: false }), null);
  const surfaces = ['dashboard', 'dashboard-control-plane', 'diagnostics', 'assurance'];
  const controls = surfaces.flatMap(surface_id => ['persistence', 'reload_reopen'].map(kind => ({ control_id: `pxui.${surface_id}.${kind}.authoritativeState`, surface_id, kind, stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['user_edit_action', 'input_validation', 'progress_reporting'].includes(stage) ? 'not_applicable_with_evidence' : 'required'])) })));
  const rendered = Object.fromEntries(surfaces.map(surface => [surface, true]));
  const probe = systemProjectionControlProbe({ controls }, { attempted: true, completed: true, webview_restarted: true, exact_reconstruction: true, rendered, errors: [] });
  assert.equal(probe.eligible_control_count, 8);
  assert.equal(probe.records[0].interaction_chain.persistence.state, 'present');
  assert.equal(probe.records[0].interaction_chain.failure_handling.state, 'missing');
  const request = { type: 'refresh' };
  const bound = requestBoundSystemSnapshotIdentity(request, { type: 'snapshot', snapshot });
  assert.equal(bound.request_type, 'refresh');
  assert.equal(bound.snapshot, snapshot);
  assert.deepEqual(bound.identity, identity);
  assert.equal(requestBoundSystemSnapshotIdentity({ type: 'ready' }, { type: 'snapshot', snapshot }), null);
  assert.equal(requestBoundSystemSnapshotIdentity(request, { type: 'snapshot', requestId: 'refresh:one', snapshot: { ...snapshot, connected: false } }), null);
});

test('installed snapshot selection does not starve a later predicate-satisfying refresh snapshot', () => {
  const stale = { connected: true, bridge: { decision: { allowed: false } } };
  const allowed = { connected: true, bridge: { decision: { allowed: true } } };
  const selection = selectLatestMatchingInstalledSnapshot([
    { type: 'coordination', coordination: {} },
    { type: 'snapshot', snapshot: stale },
    { type: 'snapshot', snapshot: allowed }
  ], 0, snapshot => snapshot?.bridge?.decision?.allowed === true);
  assert.equal(selection.matched, allowed);
  assert.equal(selection.observed, allowed);
});

test('installed snapshot timeout diagnostics retain only bounded bridge and claim identity', () => {
  const diagnostic = installedSnapshotTimeoutIdentity({
    connected: true,
    reason: 'bounded reason',
    bridge: { decision: { allowed: false, requestedEffect: 'workspace-write', reasons: ['workspace-write requires an active repository claim'] } },
    coordinationData: { state: { revision: 12, tasks: [
      { id: 'px-codex-owned', status: 'claimed', owner: { actor_id: 'ide-safe', session_id: 'session-safe' } },
      { id: 'unrelated', status: 'claimed', owner: { actor_id: 'do-not-retain' } }
    ] } }
  });
  assert.deepEqual(diagnostic, {
    connected: true,
    reason: 'bounded reason',
    bridge_allowed: false,
    requested_effect: 'workspace-write',
    bridge_reasons: ['workspace-write requires an active repository claim'],
    coordination_revision: 12,
    codex_tasks: [{ status: 'claimed', owner_actor_present: true, owner_session_present: true }]
  });
});

test('sidebar state profile composes restart durability with explicit outage and exact recovery', () => {
  const controls = [
    ...['failure_recovery', 'persistence', 'reload_reopen'].map(kind => ({ control_id: `pxui.sidebar.${kind}.surface`, kind })),
    { control_id: 'pxui.sidebar.action.retry', kind: 'action' },
    { control_id: 'pxui.sidebar.indicator.connection', kind: 'indicator' }
  ].map(control => ({ ...control, surface_id: 'sidebar', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['user_edit_action', 'input_validation', 'progress_reporting', ...(control.kind === 'failure_recovery' ? ['persistence', 'reload_reopen'] : [])].includes(stage) ? 'not_applicable_with_evidence' : 'required'])) }));
  const observation = { rendered: true, attempted: true, completed: true, webview_restarted: true, exact_reconstruction: true, disconnected_visible: true, recovered_connected: true, preference_restored: true, errors: [] };
  const probe = sidebarStateControlProbe({ controls }, observation);
  assert.equal(probe.eligible_control_count, 5);
  assert.equal(probe.records[0].interaction_chain.failure_handling.state, 'present');
  assert.equal(probe.records[1].interaction_chain.persistence.state, 'present');
  assert.equal(probe.records[2].interaction_chain.reload_reopen.state, 'present');
  assert.equal(sidebarStateControlProbe({ controls }, { ...observation, recovered_connected: false }).records[0].interaction_chain.recovery_rollback.state, 'missing');
});

test('sidebar state profile binds every remaining production-renderer conditional to exact restoration', () => {
  const observation = {
    completed: true, webview_restarted: true, exact_reconstruction: true,
    disconnected_visible: true, recovered_connected: true, preference_restored: true,
    render_acknowledgement: true, task_preference_round_trip: true, attention_visible: true,
    contract_error_visible: true, contract_error_recovered: true, stale_agent_visible: true,
    orchestration_visible: true, conditional_projection_recovered: true
  };
  for (const id of [
    'pxui.sidebar.acknowledgement.surface', 'pxui.sidebar.action.toggleTask.row',
    'pxui.sidebar.indicator.attention', 'pxui.sidebar.indicator.contractError',
    'pxui.sidebar.indicator.liveStaleAgents', 'pxui.sidebar.indicator.orchestrations'
  ]) assert.equal(sidebarStateControlVerified(id, id.includes('.action.') ? 'action' : 'indicator', observation), true, id);
  assert.equal(sidebarStateControlVerified('pxui.sidebar.indicator.attention', 'indicator', { ...observation, conditional_projection_recovered: false }), false);
  assert.equal(sidebarStateControlVerified('pxui.sidebar.indicator.contractError', 'indicator', { ...observation, contract_error_recovered: false }), false);
  assert.equal(sidebarStateControlVerified('pxui.sidebar.action.toggleTask.row', 'action', { ...observation, task_preference_round_trip: false }), false);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const scenario = source.slice(source.indexOf('async function runInstalledSidebarConditionalStateScenario'), source.indexOf('async function primarySidebarVisible'));
  assert.match(scenario, /px-owned-sidebar-task[\s\S]*MessageEvent\('message'[\s\S]*data-toggle-task[\s\S]*type === 'rendered'/);
  assert.match(scenario, /type === 'toggleTask'[\s\S]*fixtureAbsent[\s\S]*roundTrip\(false\)[\s\S]*conditional_projection_recovered/);
  assert.doesNotMatch(scenario, /innerHTML\s*=/);
});

test('sidebar preference persistence uses a host-owned reconstruction and requires an exact request-bound snapshot', async () => {
  const expected = { wave_id: 'wave:one', expanded: true };
  const exact = { request: { type: 'toggleWave', waveId: 'wave:one', expanded: true }, snapshot: { revision: 4, expanded_wave_ids: ['wave:one'] }, button_expanded: true };
  assert.deepEqual(sidebarPreferenceRoundTripIdentity(exact, expected), { wave_id: 'wave:one', expanded: true, snapshot_revision: 4 });
  assert.equal(sidebarPreferenceRoundTripIdentity({ ...exact, request: { ...exact.request, waveId: 'wave:other' } }, expected), null);
  assert.equal(sidebarPreferenceRoundTripIdentity({ ...exact, snapshot: { revision: 5, expanded_wave_ids: [] } }, expected), null);
  assert.equal(sidebarPreferenceRoundTripIdentity({ ...exact, button_expanded: false }, expected), null);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const waiter = source.slice(source.indexOf('async function waitForInstalledSidebarPreferenceRoundTrip'), source.indexOf('async function runInstalledSidebarStateProfile'));
  assert.match(waiter, /value\?\.type === 'toggleWave'[\s\S]*value\?\.waveId === expected\.wave_id[\s\S]*value\?\.expanded === expected\.expanded/);
  assert.match(waiter, /value\.expanded_wave_ids\.includes\(expected\.wave_id\) === expected\.expanded/);
  const profile = source.slice(source.indexOf('async function runInstalledSidebarStateProfile'), source.indexOf('async function runInstalledCleanupProfile'));
  assert.equal((profile.match(/waitForInstalledSidebarPreferenceRoundTrip/g) || []).length, 2);
  assert.match(profile, /await instrumentInstalledSidebarState\(sidebar\)[\s\S]*restartInstalledSidebarWebview\(workbench, sidebar[\s\S]*await instrumentInstalledSidebarState\(sidebar\)/);
  assert.doesNotMatch(profile, /location\.reload\(\)/);
  assert.match(profile, /observation\.preference_restored = Boolean\(restoredPreference\)/);

  let visible = true;
  let toggles = 0;
  let reacquired = 0;
  const workbench = {
    locator: selector => ({ isVisible: async () => selector === '.part.sidebar' ? visible : false }),
    keyboard: { press: async key => { assert.equal(key, 'Control+B'); visible = !visible; toggles += 1; } }
  };
  const sidebar = { reacquire: async () => { reacquired += 1; return visible; } };
  assert.deepEqual(await restartInstalledSidebarWebview(workbench, sidebar, 1_000), { hidden: true, reopened: true, reacquired: true });
  assert.equal(toggles, 2);
  assert.equal(reacquired, 1);
});

test('sidebar render preserves an explicitly empty durable expansion set', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'media', 'sidebar.js'), 'utf8');
  assert.match(source, /Array\.isArray\(p\.ui\.expandedWaveIds\) \? p\.ui\.expandedWaveIds/);
  assert.doesNotMatch(source, /p\.ui\.expandedWaveIds\.length \? p\.ui\.expandedWaveIds/);
});

test('plugin lifecycle reconstructs the pre-update version without an in-process downgrade', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledPluginMutationProfile'), source.indexOf('function knowledgeLifecycleControlProbe'));
  assert.match(profile, /rollback-stage-uninstall-v2[\s\S]*await rollback\(\)[\s\S]*restore-update-uninstall-v2[\s\S]*await install\(v1\)[\s\S]*plugin-update-predecessor-reconstruction-failed[\s\S]*final-cleanup-uninstall-v1/);
  assert.doesNotMatch(profile, /restore-update-v2-to-v1/);
});

test('expected plugin preview refusals stay request-bound instead of opening host error UI', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'extension.js'), 'utf8');
  assert.match(source, /\['extensionLifecyclePreview', 'extensionUpdatePreview', 'extensionConflictResolutionPreview'\]\.includes\(message\?\.type\)/);
});

test('sidebar reconstruction ignores volatile projection text but rejects semantic substitution', () => {
  const before = { status_state: 'connected', status_version: '1.2.3', execution_plan_id: 'plan:one', wave_ids: ['wave:one', 'wave:two'], targeted_wave_id: 'wave:one', targeted_expanded: true, revision: 7, status_text: 'CONNECTED v1.2.3 REV 7', execution_text: '3 / 10 tasks' };
  const after = { ...before, revision: 8, status_text: 'CONNECTED v1.2.3 REV 8', execution_text: '4 / 10 tasks' };
  assert.deepEqual(sidebarReconstructionIdentity(after), sidebarReconstructionIdentity(before));
  assert.notDeepEqual(sidebarReconstructionIdentity({ ...after, execution_plan_id: 'plan:two' }), sidebarReconstructionIdentity(before));
  assert.notDeepEqual(sidebarReconstructionIdentity({ ...after, wave_ids: ['wave:one', 'wave:three'] }), sidebarReconstructionIdentity(before));
  assert.notDeepEqual(sidebarReconstructionIdentity({ ...after, targeted_expanded: false }), sidebarReconstructionIdentity(before));
});

test('owned plugin profile separates read previews and native handoff from mutation authority', () => {
  const id = 'mountain-nomad-bc.pacify-x-vscode';
  const preview = { schema_version: 'px.extension-lifecycle-preview/1.0', allowed: true, extension_id: id, token: 'token-one', exact_target: `${id}@1.0.0` };
  assert.equal(validPluginLifecycleObservation('enablement-preview', preview, id), true);
  assert.equal(validPluginLifecycleObservation('uninstall-preview', preview, id), true);
  assert.equal(validPluginLifecycleObservation('enablement-execute', { schema_version: 'px.extension-lifecycle-receipt/1.0', action: 'enablement-handoff', extension_id: id, mutation_dispatched: false }, id), true);
  assert.equal(validPluginLifecycleObservation('enablement-execute', { schema_version: 'px.extension-lifecycle-receipt/1.0', action: 'enablement-handoff', extension_id: id, mutation_dispatched: true }, id), false);
  assert.equal(validPluginLifecycleObservation('conflict-query', { schema_version: 'px.extension-conflict-analysis/1.0', available: true, extension_id: id, signals: [] }, id), true);
  assert.equal(validPluginLifecycleObservation('install-blocked', { schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false, extension_id: id, reason: 'extension-already-installed' }, id), true);
  assert.equal(validPluginLifecycleObservation('rollback-blocked', { schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false, extension_id: id, reason: 'rollback-target-occupied' }, id), true);
  const absent = 'px-owned.absent';
  assert.equal(validPluginLifecycleObservation('enablement-blocked', { schema_version: 'px.extension-lifecycle-preview/1.0', allowed: false, extension_id: absent, reason: 'extension-not-installed' }, absent), true);
  assert.equal(validPluginLifecycleObservation('conflict-blocked', { schema_version: 'px.extension-conflict-analysis/1.0', available: false, extension_id: absent, reason: 'extension-not-installed' }, absent), true);
  const controls = [
    'previewExtensionInstall', 'previewExtensionUpdate', 'previewExtensionEnablement', 'executeExtensionEnablement',
    'previewExtensionUninstall', 'previewExtensionRollback', 'queryExtensionConflicts', 'executeExtensionInstall'
  ].map(action => ({ control_id: `pxui.plugins.action.${action}`, surface_id: 'plugins', kind: 'action', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, 'required'])) }));
  const operations = Object.fromEntries(['install-blocked', 'update-preview', 'update-blocked', 'enablement-preview', 'enablement-execute', 'enablement-blocked', 'uninstall-preview', 'uninstall-blocked', 'rollback-blocked', 'conflict-query', 'conflict-blocked'].map(operation => [operation, true]));
  const probe = pluginReadControlProbe({ controls }, { rendered: true, attempted: true, operations, errors: [] });
  assert.deepEqual(probe.records.map(record => record.control_id), controls.slice(0, 7).map(control => control.control_id));
  assert.ok(probe.records.every(record => record.interaction_chain.failure_handling.state === 'present' && record.interaction_chain.recovery_rollback.state === 'present'));
});

test('owned Plugin mutation profile requires exact reconciled receipts and complete physical recovery', () => {
  const id = 'px-owned.fixture';
  assert.equal(validPluginMutationReceipt('install', { schema_version: 'px.extension-lifecycle-receipt/1.0', action: 'install', extension_id: id, before_version: null, after_version: '1.0.0', status: 'installed', reconciled: true }, id, '1.0.0'), true);
  assert.equal(validPluginMutationReceipt('update', { schema_version: 'px.extension-lifecycle-receipt/1.0', action: 'update', extension_id: id, before_version: '1.0.0', after_version: '2.0.0', status: 'updated', reconciled: true }, id, '2.0.0'), true);
  assert.equal(validPluginMutationReceipt('uninstall', { schema_version: 'px.extension-lifecycle-receipt/1.0', action: 'uninstall', extension_id: id, before_version: '2.0.0', after_version: null, status: 'uninstalled', reconciled: true, rollback_identity: { exact_target: `${id}@2.0.0` } }, id), true);
  assert.equal(validPluginMutationReceipt('rollback', { schema_version: 'px.extension-lifecycle-receipt/1.0', action: 'rollback', extension_id: id, before_version: null, after_version: '2.0.0', status: 'restored', reconciled: true, custody_state: 'rollback-consumed' }, id, '2.0.0'), true);
  assert.equal(validPluginMutationReceipt('update', { schema_version: 'px.extension-lifecycle-receipt/1.0', action: 'update', extension_id: id, before_version: '1.0.0', after_version: '1.0.0', status: 'pending-host-reload-or-refresh', reconciled: false }, id, '2.0.0'), false);
  const source = { path: 'C:/owned/fixture.vsix', sha256: 'a'.repeat(64), size: 1446, extension_id: id, version: '1.0.0' };
  const pending = { schema_version: 'px.extension-lifecycle-receipt/1.0', action: 'install', extension_id: id, exact_target: `${id}@1.0.0`, before_version: null, after_version: null, status: 'pending-host-reload-or-refresh', reconciled: false, local_source: source };
  assert.equal(validPendingPluginMutationReceipt('install', pending, id, `${id}@1.0.0`), true);
  assert.equal(validPendingPluginMutationReceipt('install', pending, id, `${id}@2.0.0`), false);

  const uninstall = { schema_version: 'px.extension-lifecycle-receipt/1.0', action: 'uninstall', extension_id: id, exact_target: id, before_version: '1.0.0', after_version: '1.0.0', status: 'pending-host-reload-or-refresh', reconciled: false, rollback_identity: { schema_version: 'px.extension-rollback-identity/1.0', extension_id: id, version: '1.0.0', exact_target: `${id}@1.0.0`, custody_state: 'retained-before-uninstall', source_availability: 'hash-bound-local-vsix', local_source: source } };
  assert.equal(validPendingPluginMutationReceipt('uninstall', uninstall, id, id), true);
  assert.equal(validPendingPluginMutationReceipt('uninstall', { ...uninstall, rollback_identity: { ...uninstall.rollback_identity, custody_state: 'rollback-consumed' } }, id, id), false);
  assert.equal(validPendingPluginMutationReceipt('uninstall', { ...uninstall, rollback_identity: { ...uninstall.rollback_identity, local_source: null }, local_source: source }, id, id), false);

  const rollback = { schema_version: 'px.extension-lifecycle-receipt/1.0', action: 'rollback', extension_id: id, exact_target: `${id}@1.0.0`, before_version: null, after_version: null, status: 'pending-host-reload-or-refresh', reconciled: false, custody_state: 'retained-before-uninstall', source_availability: 'hash-bound-local-vsix', local_source: source };
  assert.equal(validPendingPluginMutationReceipt('rollback', rollback, id, `${id}@1.0.0`), true);
  assert.equal(validPendingPluginMutationReceipt('rollback', { ...rollback, local_source: null }, id, `${id}@1.0.0`), false);

  const walkerSource = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const projects = walkerSource.slice(walkerSource.indexOf('async function runInstalledProjectsProfile'), walkerSource.indexOf('function graphProjectionIdentity'));
  assert.match(projects, /const refreshBefore[\s\S]*data-action="refresh"[\s\S]*\.slice\(after\)/);
  const plugin = walkerSource.slice(walkerSource.indexOf('async function runInstalledPluginMutationProfile'), walkerSource.indexOf('function knowledgeLifecycleControlProbe'));
  assert.match(plugin, /receiptPending[\s\S]*requiresWorkbenchReconstruction = \['install', 'update', 'uninstall', 'rollback'\]\.includes\(spec\.receiptAction\)[\s\S]*restartOwnedWorkbenchWindow\(workbench, frameHost, 75_000, \{[\s\S]*physicalExtensionId: extensionId[\s\S]*expectedPhysicalVersion: spec\.expectedVersion[\s\S]*currentVersion[\s\S]*physicallyReconciled/);
  assert.doesNotMatch(plugin, /restartOwnedExtensionHostCatalog\(/);
  assert.match(walkerSource, /conflictSafeReconstruction === true[\s\S]*Pacify-X: Open Storage & Cleanup Manager/);
  const conflictRoute = plugin.slice(plugin.indexOf('const exerciseConflictRoute'), plugin.indexOf('observation.conflict_route_completed'));
  assert.match(conflictRoute, /restartOwnedWorkbenchWindow\(workbench, frameHost, 75_000, \{[\s\S]*conflictSafeReconstruction: true[\s\S]*physicalExtensionId: extensionId[\s\S]*expectedPhysicalVersion: v2\.version[\s\S]*currentVersion\(v2\.version\)/);
  assert.doesNotMatch(conflictRoute, /restartInstalledDashboardWebview/);
  assert.doesNotMatch(conflictRoute, /pxui\.dashboard-control-plane\.command\.pacifyX\.openDashboard/);
  assert.match(walkerSource, /waitForOwnedPhysicalExtensionVersion\(options\.physicalExtensionId, options\.expectedPhysicalVersion/);
  assert.match(walkerSource, /const obsoletePath = path\.join\(ownedExtensionsRoot, '\.obsolete'\)[\s\S]*obsolete\[entry\.name\] === true/);
  const currentVersion = plugin.slice(plugin.indexOf('const currentVersion'), plugin.indexOf('const mutate'));
  assert.match(currentVersion, /pluginRoutes[\s\S]*classList\.contains\('nav-item'\)[\s\S]*route\.click\(\)/);
  assert.match(currentVersion, /refreshedRendered[\s\S]*aria-current[\s\S]*control\.click\(\)/);
  assert.doesNotMatch(currentVersion, /navigateInstalledSurface\(frameHost, 'plugins', timeoutMs\)[\s\S]*waitForKnowledgeControl\(frameHost, '\[data-action="refreshEnvironment"\]'\)/);
  assert.match(plugin, /pending_rollback_retried = true;[\s\S]*await rollback\(\)/);
  const environment = walkerSource.slice(walkerSource.indexOf('async function runInstalledEnvironmentLifecycleProfile'), walkerSource.indexOf('const INSTALLED_CODEX_HANDOFF_IDS'));
  assert.match(environment, /environmentInventory[\s\S]*settleInstalledSurfaceControl[\s\S]*data-action="environmentScope"[\s\S]*settleInstalledEnvironmentRecord/);
  const ids = ['executeExtensionInstall', 'executeExtensionUpdate', 'executeExtensionUninstall', 'executeExtensionRollback', 'previewExtensionConflictResolution', 'executeExtensionConflictResolution'];
  const controls = [
    ...ids.map(action => ({ control_id: `pxui.plugins.action.${action}`, surface_id: 'plugins', kind: 'action' })),
    ...['activation', 'footer', 'install', 'uninstall'].map(variant => ({ control_id: `pxui.plugins.action.openExtensionsView.${variant}`, surface_id: 'plugins', kind: 'action' })),
    { control_id: 'pxui.plugins.persistence.authoritativeState', surface_id: 'plugins', kind: 'persistence' },
    { control_id: 'pxui.plugins.reload_reopen.authoritativeState', surface_id: 'plugins', kind: 'reload_reopen' },
    { control_id: 'pxui.plugins.failure_recovery.surface', surface_id: 'plugins', kind: 'failure_recovery' }
  ].map(control => ({ ...control, stage_policy: Object.fromEntries(STAGES.map(stage => [stage, 'required'])) }));
  const observation = { rendered: true, attempted: true, completed: true, invalid_source_rejected: true, invalid_conflict_target_rejected: true, conflict_route_completed: true, native_manager_reopened: true, update_rollback_reconciled: true, uninstall_rollback_reconciled: true, cleanup_restored: true, exact_reconstruction: true, errors: [] };
  const probe = pluginMutationControlProbe({ controls }, observation);
  assert.equal(probe.eligible_control_count, controls.length);
  assert.ok(probe.records.every(record => STAGES.every(stage => record.interaction_chain[stage].state === 'present')));
  const incomplete = pluginMutationControlProbe({ controls }, { ...observation, update_rollback_reconciled: false });
  assert.ok(incomplete.records.every(record => record.interaction_chain.recovery_rollback.state === 'missing'));
});

test('plugin conflict identity accepts normalized exact participants and rejects substitutions', () => {
  const px = 'mountain-nomad-bc.pacify-x-vscode';
  const fixture = 'px-owned.fixture';
  const signal = {
    signal_id: 'extension-conflict:123456789012345678901234', kind: 'duplicate-command-provider', resource: 'pacifyx.opendashboard',
    providers: [{ extension_id: fixture }, { extension_id: px.toUpperCase() }],
    extension_ids: [px, fixture], resolution_targets: [fixture, px]
  };
  const result = { schema_version: 'px.extension-conflict-analysis/1.0', available: true, signals: [signal] };
  assert.equal(exactPluginConflictSignal(result, px), signal);
  assert.equal(exactPluginConflictSignal(result, fixture), null);
  assert.equal(exactPluginConflictSignal({ ...result, signals: [{ ...signal, resource: 'pacifyx.other' }] }, px), null);
  assert.equal(exactPluginConflictSignal({ ...result, signals: [{ ...signal, extension_ids: [...signal.extension_ids, 'third.party'] }] }, px), null);
  assert.equal(exactPluginConflictSignal({ ...result, signals: [{ ...signal, providers: [{ extension_id: px }, { extension_id: 'substitute.fixture' }] }] }, px), null);
});

test('installed Plugin mutation source uses deterministic local fixtures and restores the absent denominator', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledPluginMutationProfile'), source.indexOf('function knowledgeLifecycleControlProbe'));
  assert.match(profile, /tests', 'generated', 'plugin-lifecycle/);
  assert.match(profile, /plugin-fixture-receipt-mismatch/);
  assert.match(profile, /\.missing/);
  assert.match(profile, /exactPluginConflictSignal/);
  assert.match(profile, /exactPluginConflictSignal\(result, pxExtensionId, extensionId\)/);
  const conflictIdentity = source.slice(source.indexOf('function exactPluginConflictSignal'), source.indexOf('function pluginReadControlProbe'));
  assert.match(conflictIdentity, /duplicate-command-provider/);
  assert.match(profile, /Authorize conflict route/);
  assert.match(profile, /target-not-admitted/);
  assert.match(profile, /exerciseNativeManagerEntrypoints/);
  assert.match(profile, /hostActionResult/);
  assert.match(profile, /waitForNativeWorkbenchDialog\(workbench, spec\.nativeApproval, 15_000, \{ frameHost, responseOffset: executeBefore, requestOffset: requestBeforeExecute, requestType: spec\.executeOperation, keyboardAction: spec\.nativeApproval \}\)/);
  assert.match(profile, /clickNativeWorkbenchDialogAction\(workbench, dialog, spec\.nativeApproval\)/);
  assert.match(profile, /waitForNativeWorkbenchDialog\(workbench, 'Authorize conflict route'/);
  assert.match(profile, /dismissOwnedNativeWorkbenchDialog\(workbench, \/Authorize native install\|Authorize native update\|Authorize native uninstall\|Authorize exact rollback\|Authorize conflict route\/i\)/);
  assert.doesNotMatch(profile, /workbench\.locator\('\.monaco-dialog-box:visible'/);
  assert.ok(profile.indexOf("await install(v1)") < profile.indexOf("await update('update-v1-to-v2', v2)"));
  assert.ok(profile.indexOf("await update('update-v1-to-v2', v2)") < profile.indexOf('await exerciseConflictRoute()'));
  assert.ok(profile.indexOf("await update('update-v1-to-v2', v2)") < profile.indexOf("await uninstall('rollback-stage-uninstall-v2')"));
  assert.ok(profile.indexOf("await uninstall('rollback-stage-uninstall-v2')") < profile.indexOf('await rollback()'));
  assert.ok(profile.indexOf('await rollback()') < profile.indexOf("await uninstall('restore-update-uninstall-v2')"));
  assert.ok(profile.indexOf("await uninstall('restore-update-uninstall-v2')") < profile.indexOf('observation.update_rollback_reconciled = await currentVersion(v1.version)'));
  assert.ok(profile.indexOf('observation.update_rollback_reconciled = await currentVersion(v1.version)') < profile.indexOf("await uninstall('final-cleanup-uninstall-v1', v1)"));
  assert.match(profile, /restartInstalledDashboardWebview/);
  assert.match(profile, /environmentResult/);
  assert.match(profile, /network_expected/);
});

test('installed Plugin read handoff is request-bound and completes native authority before accepting its typed receipt', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledPluginReadProfile'), source.indexOf('function validPluginMutationReceipt'));
  assert.match(profile, /const requestBeforeExecute = await installedOutboundRequestOffset\(frameHost\)/);
  assert.match(profile, /waitForNativeWorkbenchDialog\(workbench, 'Open exact native record', 15_000, \{ frameHost, responseOffset: executeBefore, requestOffset: requestBeforeExecute, requestType: 'extensionEnablementExecute', keyboardAction: 'Open exact native record' \}\)/);
  assert.match(profile, /clickNativeWorkbenchDialogAction\(workbench, dialog, 'Open exact native record'\)/);
  assert.match(profile, /value\?\.type === 'extensionEnablementResult' && value\?\.requestId === item\.expectedRequestId && value\?\.result/);
  assert.match(source, /'Open exact native record', new Set\(\['extensionEnablementExecute'\]\)/);
});

test('r15 pre-cascade scenarios wait for observable state and preserve exact fail-closed contracts', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const knowledge = source.slice(source.indexOf('async function runInstalledKnowledgeLifecycleProfile'), source.indexOf('async function waitForInstalledMemoryText'));
  const knowledgeRefusal = source.slice(source.indexOf('async function waitForKnowledgeProposalRejection'), source.indexOf('async function runInstalledKnowledgeLifecycleProfile'));
  assert.match(knowledge, /waitForKnowledgeProposalRejection/);
  assert.match(knowledgeRefusal, /responses\.slice\(before\)\.some/);
  assert.match(knowledgeRefusal, /value\?\.kind === 'knowledge' && value\?\.operation === 'propose'/);
  assert.match(knowledgeRefusal, /undispatched: !dispatched/);
  const navigation = source.slice(source.indexOf('async function waitForAdvancedNavigationExpanded'), source.indexOf('async function runInstalledStudioSetupProfile'));
  assert.match(navigation, /aria-expanded/);
  assert.match(navigation, /advanced-navigation-expansion-timeout/);
  assert.match(navigation, /await waitForAdvancedNavigationExpanded\(frameHost, surface/);
  const hostAction = source.slice(source.indexOf('async function waitForDurableHostActionResult'), source.indexOf('const INSTALLED_HOST_BOUNDARY_SPECS'));
  assert.match(hostAction, /__PX_DURABLE_HOST_ACTION_RESULT__/);
  assert.match(hostAction, /value\.requestId === expected\.requestId/);
  assert.match(hostAction, /Date\.parse\(value\.observedAt/);
  const plugin = source.slice(source.indexOf('async function runInstalledPluginMutationProfile'), source.indexOf('function knowledgeLifecycleControlProbe'));
  assert.match(plugin, /\.missing\.vsix/);
  assert.doesNotMatch(plugin, /`\$\{v1\.path\}\.missing`/);
  const enterprise = source.slice(source.indexOf('async function runInstalledEnterpriseProfile'), source.indexOf('const INSTALLED_VALIDATION_CONTROL_IDS'));
  assert.match(enterprise, /resetInstalledDashboardBaseline\(workbench, frameHost/);
});

test('zero-stale Activity no-op remains actionable and request-bound notifications follow acknowledgement', () => {
  const activity = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '46-observability-surfaces.js'), 'utf8');
  assert.match(activity, /staleOperations\.length > 0 && \(policy\.paused \|\| policy\.enabled === false\)/);
  const extension = fs.readFileSync(path.join(__dirname, '..', 'src', 'extension.js'), 'utf8');
  const copy = extension.slice(extension.indexOf("case 'copyTaskHandoff'"), extension.indexOf("case 'openCoordinationHandoff'"));
  assert.ok(copy.indexOf("await acknowledgeHostAction('completed'") < copy.indexOf('showInformationMessage'));
  assert.match(extension, /request-bound-refusal/);
  assert.match(extension, /extensionLifecyclePreview/);
});

test('r16 prerequisites are geometry-independent, owned, reversible, and diagnostically terminal', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const expansion = source.slice(source.indexOf('async function waitForAdvancedNavigationExpanded'), source.indexOf('async function navigateInstalledSurface'));
  assert.doesNotMatch(expansion, /offsetWidth|offsetHeight|getClientRects/);
  assert.match(expansion, /!element\.disabled/);
  assert.match(expansion, /targetNavigation/);
  const navigation = source.slice(source.indexOf('async function navigateInstalledSurface'), source.indexOf('async function runInstalledStudioSetupProfile'));
  assert.doesNotMatch(navigation, /offsetWidth|offsetHeight|getClientRects/);
  const scenario = source.slice(source.indexOf('async function prepareInstalledHostBoundaryScenario'), source.indexOf('function hostBoundaryControlProbe'));
  assert.match(source, /stageOwnedActivityEnabled/);
  assert.match(source, /restoreOwnedActivitySettings/);
  assert.match(scenario, /previous_enabled/);
  assert.match(scenario, /activity_policy_restored/);
  const profile = source.slice(source.indexOf('async function runInstalledHostBoundaryProfile'), source.indexOf('const INSTALLED_ENTERPRISE_CONTROLS'));
  assert.match(profile, /for \(const spec of INSTALLED_HOST_BOUNDARY_SPECS\)[\s\S]*resetInstalledDashboardBaseline\(workbench, frameHost[\s\S]*navigateInstalledSurface\(frameHost, spec\.route/);
  assert.match(profile, /canonicalScenarioTimeoutMs/);
  assert.match(profile, /canonicalScenarioTimeoutMs = 75_000/);
  assert.match(profile, /Math\.max\(35_000, Math\.min\(50_000, timeoutMs \+ 20_000\)\)/);
  assert.match(source, /inspectHostActionReceiptFailure/);
  assert.match(profile, /response_diagnostics/);

  const messages = fs.readFileSync(path.join(__dirname, '..', 'src', 'webviewMessages.js'), 'utf8');
  assert.match(messages, /setActivityPaused: \['requestId', 'paused'\]/);
  assert.doesNotMatch(messages, /setActivityPaused: \['requestId', 'paused', 'enabled'\]/);
});

test('r17 navigation settles retained modals and blank-memory refusal uses the native required contract', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const settlement = source.slice(source.indexOf('async function settleInstalledModalBoundary'), source.indexOf('async function navigateInstalledSurface'));
  assert.match(settlement, /querySelectorAll\('\.control-modal'\)/);
  assert.match(settlement, /data-action="closeModal"/);
  assert.match(settlement, /installed-modal-settlement-timeout/);
  const navigation = source.slice(source.indexOf('async function navigateInstalledSurface'), source.indexOf('async function runInstalledStudioSetupProfile'));
  assert.match(navigation, /await settleInstalledModalBoundary\(frameHost/);
  assert.ok(navigation.indexOf('settleInstalledModalBoundary') < navigation.indexOf('waitForAdvancedNavigationExpanded'));
  const coordination = source.slice(source.indexOf('async function runInstalledCoordinationMemoryProfile'), source.indexOf('function validCleanupResult'));
  const invalidRelease = coordination.slice(coordination.indexOf('const invalidReleaseBefore'), coordination.indexOf("if (!observation.invalid_release_rejected)"));
  assert.match(coordination, /releaseCoordinationTask'[\s\S]*data-release-validation[\s\S]*at least 10 characters/);
  assert.doesNotMatch(invalidRelease, /__PX_INSTALLED_RESPONSES__\?\.length/);
  assert.match(coordination, /content\.required === true/);
  assert.match(coordination, /content\.validity\?\.valueMissing === true/);
  assert.match(coordination, /__PX_INSTALLED_REQUESTS__/);
});

test('r19 navigation acknowledges the exact advanced route after its submenu collapses', () => {
  assert.equal(installedSurfaceAcknowledged({ nav_current: true, rendered_surface: false }), false);
  assert.equal(installedSurfaceAcknowledged({ nav_current: false, rendered_surface: true }), false);
  assert.equal(installedSurfaceAcknowledged({ nav_current: true, rendered_surface: true }), true);
  assert.equal(installedSurfaceAcknowledged({ nav_current: false, rendered_surface: false }), false);
  assert.equal(installedSurfaceAcknowledged(null), false);
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const navigation = source.slice(source.indexOf('async function navigateInstalledSurface'), source.indexOf('async function runInstalledStudioSetupProfile'));
  assert.match(navigation, /classList\.contains\(`surface-\$\{target\}`\)/);
  assert.match(navigation, /data-action="toggleAdvanced"\]\.active/);
  assert.match(navigation, /knowledgeCore: 'Knowledge Core', runtimeCore: 'Runtime Core'/);
  assert.match(navigation, /advancedRouteCurrent/);
  assert.match(navigation, /advancedCurrentAfterClick/);
  assert.match(navigation, /installedSurfaceAcknowledged\(routeState\)/);
  assert.match(navigation, /rendered_surface_classes/);
});

test('r20 dashboard baseline recovery is absolutely bounded and retains both causal errors', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const bounded = source.slice(source.indexOf('async function boundedOwnedUiAction'), source.indexOf('const ownedReversibleConfigurationAuthority'));
  const reopen = source.slice(source.indexOf('async function reopenPacifyDashboardFromOwnedUi'), source.indexOf('async function waitForOwnedWorkbenchDisplacementSettled'));
  const baseline = source.slice(source.indexOf('async function resetInstalledDashboardBaseline'), source.indexOf('async function restartInstalledDashboardWebview'));
  assert.match(bounded, /Promise\.race/);
  assert.match(bounded, /setTimeout\(\(\) => reject/);
  assert.match(reopen, /const deadline = Date\.now\(\) \+ timeoutMs;[\s\S]*boundedOwnedUiAction\(\(\) => workbench\.bringToFront\(\)/);
  assert.match(reopen, /owned-workbench-closed-before-dashboard-reopen/);
  assert.match(reopen, /installed-dashboard-reopen-instrument/);
  assert.match(reopen, /installed-dashboard-reopen-stability-instrument/);
  assert.match(baseline, /const deadline = Date\.now\(\) \+ timeoutMs/);
  assert.match(baseline, /const initialProbeBudget = Math\.max\(250, Math\.min\(2_500, Math\.floor\(timeoutMs \/ 4\)\)\)/);
  assert.match(baseline, /frameHost\.reacquire\(initialProbeBudget\)/);
  assert.match(baseline, /instrumentInstalledBridge\(frameHost, initialProbeBudget\)/);
  assert.match(baseline, /\}, initialProbeBudget, 'installed-dashboard-baseline-instrument'\)/);
  assert.match(baseline, /initial_error: initialError/);
  assert.match(baseline, /recovery_error/);
  assert.match(baseline, /baseline-budget-exhausted/);
});

test('r21 dynamic dashboard resolution bounds a non-responsive frame shell enumeration', async () => {
  const never = new Promise(() => {});
  const workbench = { locator: () => ({ count: () => never }) };
  const started = Date.now();
  const result = await waitForOwnedWebview(workbench, () => true, 30);
  const duration = Date.now() - started;
  assert.equal(result, null);
  assert.ok(duration < 750, `non-responsive shell enumeration exceeded its bound: ${duration} ms`);
  await assert.rejects(
    boundedOwnedUiAction(() => new Promise(() => {}), 20, 'owned-test-action'),
    /owned-test-action-timeout:20/
  );

  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const resolver = source.slice(source.indexOf('async function waitForOwnedWebview'), source.indexOf('async function openWorkbenchCommandPalette'));
  const baseline = source.slice(source.indexOf('async function resetInstalledDashboardBaseline'), source.indexOf('async function restartInstalledDashboardWebview'));
  assert.match(resolver, /boundedResolveAction\(\(\) => shells\.count\(\), 'owned-webview-shell-count'\)/);
  assert.match(resolver, /boundedResolveAction\(\(\) => shell\.isVisible\(\), 'owned-webview-shell-visibility'\)/);
  assert.match(resolver, /timeout: Math\.max\(1, Math\.min\(Number\(options\.timeout\) \|\| 10_000, 10_000\)\)/);
  assert.match(baseline, /instrumentInstalledBridge\(frameHost, initialProbeBudget\)/);
  assert.match(baseline, /\{ timeout: locatorBudget\(\) \}/);
});

test('installed control probe retains exact denominator, bridge, and receipt contracts', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /operational_control_proof_matrix\.json/);
  assert.match(source, /'agent-studio': 'agents', 'workflow-studio': 'workflows', 'skill-studio': 'skillsTools'/);
  assert.match(source, /resumeWorkingStudioDraft/);
  assert.match(source, /querySelectorAll\('\.studio-modal'\)/);
  assert.match(source, /\(open \|\| resume\)\?\.click\(\)/);
  assert.match(source, /element\.dataset\.kind === expectedKind && visible\(element\)/);
  assert.match(source, /if \(\[\.\.\.\(document\?\.querySelectorAll\('\.studio-modal'\)/);
  assert.match(source, /resumeInstalledWorkingDraftIfOffered\(frameHost, kind\)/);
  assert.match(source, /visible_modal_title/);
  assert.match(source, /visible_modal_actions/);
  assert.match(source, /not-ready:\$\{JSON\.stringify\(lastState\)\}/);
  assert.match(source, /waitForInstalledStudioState\(frameHost, kind, 'opener'\)/);
  assert.match(source, /waitForInstalledStudioState\(frameHost, kind, 'modal'\)/);
  assert.match(source, /studio-\$\{expected\}-not-ready/);
  assert.match(source, /const blockedSurfaces = new Map\(\)/);
  assert.match(source, /seedInstalledStudioPrerequisites\(frameHost, control\)/);
  assert.match(source, /preparationIdentity !== control\.surface_id/);
  assert.match(source, /id\|index\|row\|key\|path/);
  assert.match(source, /blockedSurfaces\.set\(control\.surface_id, message\)/);
  assert.match(source, /proofMatrix\.controls\.length !== inventory\.control_count/);
  assert.match(source, /const document = frame\.contentDocument/);
  assert.match(source, /inner\.__PX_INSTALLED_RESPONSES__/);
  assert.doesNotMatch(source, /elementHandle\(\).*contentFrame/);
  assert.match(source, /settleInstalledModalBoundary\(frameHost/);
  assert.match(source, /navigateInstalledSurface\(frameHost, route, 20_000\)/);
  assert.match(source, /__PX_INSTALLED_BRIDGE_INSTRUMENTED__/);
  assert.match(source, /inner\.__PX_INSTALLED_RESPONSES__\.push/);
  assert.match(source, /acknowledgementDeadline = Date\.now\(\) \+ \(spec\.local \? 80 : 15_000\)/);
  assert.match(source, /\['authorization', 'backend_dispatch', 'runtime_effect'\]/);
  assert.match(source, /probe\.attempted && probe\.acknowledged/);
  assert.match(source, /installed_control_probe: installedControlProbe/);
  assert.match(source, /reversible_configuration_profile: reversibleConfigurationProfile/);
  assert.match(source, /studio_setup_profile: studioSetupProfile/);
  assert.match(source, /studio_candidate_save_profile: studioCandidateSaveProfile/);
  assert.match(source, /controlIds: \['pxui\.agent-studio\.action\.submitStudioDraft\.agent', 'pxui\.agent-studio\.form\.candidateMetadata', 'pxui\.agent-studio\.failure_recovery\.surface'/);
  assert.match(source, /controlIds: \['pxui\.workflow-studio\.action\.submitStudioDraft\.workflow', 'pxui\.workflow-studio\.form\.candidateMetadata', 'pxui\.workflow-studio\.failure_recovery\.surface'/);
  assert.match(source, /controlIds: \['pxui\.skill-studio\.action\.submitStudioDraft\.skill', 'pxui\.skill-studio\.form\.candidateMetadata', 'pxui\.skill-studio\.failure_recovery\.surface'/);
  assert.match(source, /identityInput\.value = 'invalid identity with spaces';[\s\S]*invalidRejected[\s\S]*setCustomValidity\('px-owned-invalid-studio-identity'\)[\s\S]*setCustomValidity\(''\)[\s\S]*recovered_before_save/);
  assert.match(source, /studio_revision_edit_profile: studioRevisionEditProfile/);
  assert.match(source, /engine_outage_profile: engineOutageProfile/);
  assert.match(source, /beginOwnedEngineOutage\(process\.env\.PX_OWNED_ENGINE_ROOT, ownedHostToken\)/);
  assert.match(source, /navigateInstalledSurface\(frameHost, 'dashboard', timeoutMs\)[\s\S]*querySelectorAll\('\[data-action="refresh"\]'\)/);
  assert.match(source, /runInstalledStudioRevisionEditProfile/);
  assert.match(source, /kind: 'skill', submitControlId: 'pxui\.skill-studio\.action\.submitStudioDraft\.skill'/);
  assert.match(source, /kind === 'skill' \? 'loadSkillPackageEditor' : 'openStudioFromCatalog'/);
  assert.match(source, /revision-editor-binding-timeout/);
  assert.match(source, /controller_state[\s\S]*active_request_id[\s\S]*transition_trace[\s\S]*requestTrace\.map/);
  assert.match(source, /revision-editor-presentation-invariant-missing/);
  assert.match(source, /modal_title[\s\S]*modal_kicker/);
  assert.match(source, /response-unmatched', 'response-rejected', 'presentation-error'/);
  assert.match(source, /revision-save-unavailable-after-edit/);
  assert.match(source, /last_editor_state/);
  assert.match(source, /revision-catalog-reopen-match-missing/);
  assert.match(source, /runInstalledStudioSetupProfile/);
  assert.match(source, /setupStudio-positive-counts-not-observed/);
  assert.match(source, /data-action="surfaceScope"\]\[data-target="agents"\]\[data-scope="core"/);
  assert.match(source, /PX_OWNED_VSCODE_HOST/);
  assert.match(source, /--px-owned-token=/);
  assert.match(source, /installed-reversible-configuration/);
  assert.match(source, /restoration-mismatch/);
  assert.match(source, /waitForInstalledConfigurationTarget/);
  assert.match(source, /restartInstalledDashboardWebview/);
  assert.match(source, /performance\?\.timeOrigin/);
  assert.match(source, /state-did-not-survive-webview-restart/);
  assert.match(source, /knowledge-webview-restart-reconstruction-invalid/);
  assert.match(source, /pxui\.agents\.reload_reopen\.authoritativeState/);
  assert.match(source, /pxui\.skills-tools\.reload_reopen\.authoritativeState/);
  assert.match(source, /pxui\.studio-lifecycle\.reload_reopen\.authoritativeState/);
  assert.match(source, /cleanup-reclaimed-candidate-reappeared-after-restart/);
  assert.match(source, /did not prove a matched pre-write failure with unchanged state/);
  const configurationInvocation = source.slice(source.indexOf('async function invokeInstalledConfigurationAction'), source.indexOf('async function exerciseOwnedConfigurationFailure'));
  assert.match(configurationInvocation, /const readAcknowledgement[\s\S]*approvalDeadline = Date\.now\(\) \+ 15_000[\s\S]*acknowledgement = await readAcknowledgement\(\)[\s\S]*approval\.isVisible\(\)[\s\S]*approval\.click\(\)/);
  assert.doesNotMatch(configurationInvocation, /timeout: 750/);
  assert.match(source, /invokeInstalledHostAction/);
  assert.match(source, /waitForInstalledCanonicalMemoryState/);
  assert.match(source, /memory-authority/);
  assert.match(source, /data-action="memoryRefresh"/);
  assert.match(source, /disconnectCanonicalMemory/);
  assert.match(source, /canonical-memory-restoration-mismatch/);
  assert.match(source, /px\.installed-operational-control-probe\/1\.0/);
});

test('owned engine outage evidence requires both the visible non-authoritative alert and exact restoration', () => {
  const requirement = {
    control_id: 'pxui.dashboard.failure_recovery.surface', surface_id: 'dashboard', kind: 'failure_recovery',
    stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['open_load', 'display', 'authorization', 'backend_dispatch', 'runtime_effect', 'result_acknowledgement', 'failure_handling', 'recovery_rollback'].includes(stage) ? 'required' : 'not_applicable_with_evidence']))
  };
  const observation = {
    outage_started: true, restoration: { restored: true }, errors: [],
    baseline: { [requirement.control_id]: { heading: 'Dashboard', disconnected: false } },
    fault: { [requirement.control_id]: { disconnected: true, alert_visible: true, alert_text: 'Current operational metrics are unavailable. Any displayed zero is not an observed system value.' } },
    recovered: { [requirement.control_id]: { disconnected: false, alert_visible: false, footer: 'CONTROL PLANE CONNECTED' } }
  };
  const record = engineOutageRecord(requirement, observation);
  assert.equal(record.interaction_chain.failure_handling.state, 'present');
  assert.equal(record.interaction_chain.recovery_rollback.state, 'present');
  assert.equal(record.interaction_chain.runtime_effect.state, 'present');
  const missingAlert = engineOutageRecord(requirement, { ...observation, fault: { [requirement.control_id]: { disconnected: true, alert_visible: false, alert_text: '' } } });
  assert.equal(missingAlert.interaction_chain.failure_handling.state, 'missing');
  assert.equal(missingAlert.interaction_chain.runtime_effect.state, 'missing');
  const persistence = { ...requirement, control_id: 'pxui.dashboard.persistence.authoritativeState', kind: 'persistence', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, ['user_edit_action', 'input_validation', 'progress_reporting'].includes(stage) ? 'not_applicable_with_evidence' : 'required'])) };
  const persistenceObservation = {
    ...observation,
    baseline: { [persistence.control_id]: observation.baseline[requirement.control_id] },
    fault: { [persistence.control_id]: observation.fault[requirement.control_id] },
    recovered: { [persistence.control_id]: observation.recovered[requirement.control_id] }
  };
  const persistenceRecord = engineOutageRecord(persistence, persistenceObservation);
  assert.equal(persistenceRecord.interaction_chain.failure_handling.state, 'present');
  assert.equal(persistenceRecord.interaction_chain.recovery_rollback.state, 'present');
  assert.equal(persistenceRecord.interaction_chain.persistence.state, 'missing');
  assert.equal(persistenceRecord.interaction_chain.reload_reopen.state, 'missing');
});

test('installed form state scenario fails closed around temporary custom validity and exact restoration', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const start = source.indexOf("} else if (item.kind === 'form') {");
  const scenario = source.slice(start, source.indexOf('state.validationObserved = state.attempted', start));
  assert.ok(start >= 0);
  assert.match(scenario, /const validityBefore = field\.checkValidity\(\)/);
  assert.match(scenario, /const customErrorBefore = field\.validity\?\.customError === true/);
  assert.match(scenario, /field\.setCustomValidity\('px-owned-form-probe-invalid'\)/);
  assert.match(scenario, /finally \{[\s\S]*field\.setCustomValidity\(''\)/);
  assert.match(scenario, /state\.recoveryObserved = state\.failureObserved && state\.restored/);
  assert.doesNotMatch(scenario, /\.submit\(|requestSubmit/);
});

test('installed editor and gesture rejection runs before application handlers and restores normal input', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const start = source.indexOf("} else if (['editor', 'gesture'].includes(item.kind)) {");
  const scenario = source.slice(start, source.indexOf("} else if (item.kind === 'form') {", start));
  assert.ok(start >= 0);
  assert.match(scenario, /event\.preventDefault\(\); event\.stopImmediatePropagation\(\)/);
  assert.match(scenario, /addEventListener\('keydown', rejectOwnedInput, \{ capture: true, once: true \}\)/);
  assert.match(scenario, /removeEventListener\('keydown', rejectOwnedInput, \{ capture: true \}\)/);
  assert.match(scenario, /state\.failureObserved = rejected && fingerprint\(\) === beforeFailure/);
  assert.match(scenario, /state\.recoveryObserved = state\.failureObserved && state\.restored/);
});

test('reversible configuration profile injects exact owned faults before writes and requires unchanged state', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /function exerciseOwnedConfigurationFailure[\s\S]*owned-operational-faults[\s\S]*operationError[\s\S]*owned-injected-configuration-fault[\s\S]*verifyUnchanged/);
  assert.match(source, /setActivityPaused[\s\S]*exerciseOwnedConfigurationFailure[\s\S]*readInstalledConfigurationAction[\s\S]*failure_handling = true/);
  assert.match(source, /exerciseOwnedConfigurationFailure\(frameHost, \{ route: 'memory', action: 'configureCanonicalMemory', operation: 'configureCanonicalMemory' \}/);
  assert.match(source, /exerciseOwnedConfigurationFailure\(frameHost, \{ route: 'memory', action: 'disconnectCanonicalMemory', operation: 'disconnectCanonicalMemory' \}[\s\S]*setup\.failure_handling = true/);
  assert.match(source, /stage === 'failure_handling'[\s\S]*observation\.failure_handling[\s\S]*matched pre-write failure/);
});

test('canonical memory reversible profile accepts an attached fixture and restores its exact authority state', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const start = source.indexOf("const memoryRequirements = ['pxui.memory.action.configureCanonicalMemory'");
  const profile = source.slice(start, source.indexOf("return {\n    schema_version: 'px.installed-operational-control-probe/1.0'", start));
  assert.ok(start >= 0);
  assert.match(profile, /const initial = await readInstalledCanonicalMemoryState/);
  assert.match(profile, /if \(initial\.attached\)[\s\S]*disconnectCanonicalMemory[\s\S]*profile_initial_target[\s\S]*waitForInstalledCanonicalMemoryState\(frameHost, false\)/);
  assert.match(profile, /exerciseOwnedConfigurationFailure\(frameHost, \{ route: 'memory', action: 'configureCanonicalMemory'/);
  assert.match(profile, /exerciseOwnedConfigurationFailure\(frameHost, \{ route: 'memory', action: 'disconnectCanonicalMemory'/);
  assert.match(profile, /if \(setup\.profile_initial_attached\)[\s\S]*configureCanonicalMemory[\s\S]*installedFilesystemPathsMatch\(setup\.restored_target, setup\.profile_initial_target\)[\s\S]*waitForInstalledCanonicalMemoryState\(frameHost, true\)/);
  assert.match(profile, /else if \(!setup\.profile_initial_attached && !current\.detached\)[\s\S]*disconnectCanonicalMemory[\s\S]*waitForInstalledCanonicalMemoryState\(frameHost, false/);
  assert.match(profile, /canonical-memory-restoration-mismatch:[\s\S]*initial_target[\s\S]*initial_identity[\s\S]*restored_target[\s\S]*restored_identity/);
});

test('installed filesystem identity compares Windows paths semantically and keeps substitutions distinct', () => {
  const base = path.resolve(__dirname);
  const equivalent = path.join(base, '.');
  assert.equal(installedFilesystemPathsMatch(base, equivalent), true);
  assert.equal(installedFilesystemPathsMatch('', ''), true);
  assert.equal(installedFilesystemPathsMatch(base, path.dirname(base)), false);
  assert.equal(installedFilesystemPathIdentity('', { platform: 'win32' }), '');
  const fakeRealpath = value => value;
  assert.equal(installedFilesystemPathsMatch('C:/PX/Workspace', 'c:\\px\\workspace', { platform: 'win32', realpath: fakeRealpath }), true);
  assert.equal(installedFilesystemPathsMatch('C:/PX/Workspace', 'C:/PX/Substitute', { platform: 'win32', realpath: fakeRealpath }), false);
  assert.equal(installedFilesystemPathWithin('C:/PX/Workspace', 'c:\\px\\workspace\\.engineering-bootstrap\\receipt.json', { platform: 'win32', realpath: fakeRealpath }), true);
  assert.equal(installedFilesystemPathWithin('C:/PX/Workspace', 'C:/PX/Workspace', { platform: 'win32', realpath: fakeRealpath }), false);
  assert.equal(installedFilesystemPathWithin('C:/PX/Workspace', 'C:/PX/Substitute/receipt.json', { platform: 'win32', realpath: fakeRealpath }), false);
});

test('owned enterprise profile stages Team Fabric only as a disposable non-canonical candidate and restores its denominator', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledEnterpriseProfile'), source.indexOf('const INSTALLED_VALIDATION_CONTROL_IDS'));
  assert.match(profile, /owned-team-pack-fixture/);
  assert.match(profile, /item\.route === 'agents'[\s\S]*data-action="surfaceScope"[\s\S]*data-action="capabilityTab"\]\[data-kind="enterprise-skills"/);
  assert.match(profile, /enterprise-scope-control-unavailable/);
  assert.match(profile, /TEAM\.md/);
  assert.match(profile, /phase: 'preview'/);
  assert.match(profile, /cancelled_without_effect/);
  assert.match(profile, /Stage candidates/);
  assert.match(profile, /canonical_registry_mutated === false/);
  assert.match(profile, /installedFilesystemPathWithin\(ownedWorkspaceRoot, stagedPath\)/);
  assert.match(profile, /team\.staged_count = Number/);
  assert.match(profile, /fs\.rmSync\(stagedPath/);
  assert.match(profile, /waitForNativeWorkbenchDialog\(workbench/);
  assert.match(profile, /responseOffset: beforeCancel/);
  assert.match(profile, /responseOffset: restoreBefore/);
  assert.match(profile, /responseOffset: stageBefore/);
  assert.match(profile, /clickNativeWorkbenchDialogAction\(workbench, approval, 'Stage candidates'\)/);
  assert.match(profile, /dismissOwnedNativeWorkbenchDialog/);
  assert.doesNotMatch(profile, /workbench\.locator\('\.monaco-dialog-box:visible'/);
  const control = { control_id: 'pxui.agents.action.teamPackPreview', surface_id: 'agents', kind: 'action', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, 'required'])) };
  const complete = enterpriseControlProbe({ controls: [control] }, { controls: { [control.control_id]: { rendered: true, attempted: true, completed: true, cancelled_without_effect: true, restored: true, errors: [] } } });
  assert.ok(STAGES.every(stage => complete.records[0].interaction_chain[stage].state === 'present'));
  const notRestored = enterpriseControlProbe({ controls: [control] }, { controls: { [control.control_id]: { rendered: true, attempted: true, completed: true, cancelled_without_effect: true, restored: false, errors: [] } } });
  assert.equal(notRestored.records[0].interaction_chain.recovery_rollback.state, 'missing');
});

test('post-audit shared validation fails before execution once, then executes the canonical validator exactly once', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledValidationProfile'), source.indexOf('const INSTALLED_ENVIRONMENT_LIFECYCLE_IDS'));
  assert.match(profile, /exerciseOwnedConfigurationFailure/);
  assert.match(profile, /currentCount === validationCount/);
  assert.match(profile, /observation\.cancelled_probe = true/);
  assert.equal((profile.match(/querySelector\('\[data-action="validate"\]'\)\.click\(\)/g) || []).length, 1);
  const controls = ['diagnostics', 'runtime-core'].map(surface => ({ control_id: `pxui.${surface}.action.validate`, surface_id: surface, kind: 'action', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, 'required'])) }));
  const probe = validationControlProbe({ controls }, { rendered: Object.fromEntries(controls.map(control => [control.control_id, true])), executed_once: true, cancelled_probe: true, result: { status: 'passed' }, webview_restarted: true, errors: [] });
  assert.ok(probe.records.every(record => STAGES.every(stage => record.interaction_chain[stage].state === 'present')));
});

test('open-intake validation boundary clicks both exact controls without dispatch and restores them', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledValidationBoundaryProfile'), source.indexOf('async function runInstalledValidationProfile'));
  assert.match(profile, /document\.addEventListener\('click', refuse, true\)/);
  assert.match(profile, /event\.stopImmediatePropagation\(\)/);
  assert.match(profile, /requests\(\) === before/);
  assert.match(profile, /document\.removeEventListener\('click', refuse, true\)/);
  assert.match(source, /timedProfile\('validation-authority-boundary'/);
  const controls = ['diagnostics', 'runtime-core'].map(surface => ({ control_id: `pxui.${surface}.action.validate`, surface_id: surface, kind: 'action', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, 'required'])) }));
  const values = Object.fromEntries(controls.map(control => [control.control_id, true]));
  const probe = validationControlProbe({ controls }, { authority_deferred: true, rendered: values, refused: values, recovered: values, errors: [] });
  assert.ok(probe.records.every(record => record.authority_skipped === true && record.interaction_chain.failure_handling.state === 'present' && record.interaction_chain.recovery_rollback.state === 'present'));
  assert.ok(probe.records.every(record => record.interaction_chain.backend_dispatch.state === 'missing'));
});

test('long-running operational coverage remains on the validation refusal boundary without independent validation authority', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /PX_OPERATIONAL_VALIDATION_EXECUTION_AUTHORITY/);
  assert.match(source, /validationExecutionAuthority && postAuditLongRunningAuthority && !focusedProfileOnly/);
  assert.doesNotMatch(source, /const validationProfile = postAuditLongRunningAuthority && !focusedProfileOnly/);
});

test('advanced navigation selects only a visible route control before acknowledging its surface', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const expansion = source.slice(source.indexOf('async function waitForAdvancedNavigationExpanded'), source.indexOf('async function settleInstalledModalBoundary'));
  const navigation = source.slice(source.indexOf('async function navigateInstalledSurface'), source.indexOf('function installedSurfaceControlAcknowledged'));
  assert.match(expansion, /getComputedStyle\(element\)[\s\S]*style\.display !== 'none'[\s\S]*visible\(element\)/);
  assert.match(navigation, /filter\(element => !element\.disabled && visible\(element\)\)[\s\S]*aria-current/);
});

test('installed plugin profiles require acknowledged Plugins navigation before lifecycle controls', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const readProfile = source.slice(source.indexOf('async function runInstalledPluginReadProfile'), source.indexOf('function validPluginMutationReceipt'));
  const mutationProfile = source.slice(source.indexOf('async function runInstalledPluginMutationProfile'), source.indexOf('\nfunction ', source.indexOf('async function runInstalledPluginMutationProfile')));
  assert.match(readProfile, /await settleInstalledPluginControl\(frameHost, '\[data-action="previewExtensionEnablement"\]', timeoutMs\)/);
  assert.ok((mutationProfile.match(/await settleInstalledPluginControl\(frameHost,/g) || []).length >= 8);
  const settlement = source.slice(source.indexOf('async function settleInstalledSurfaceControl'), source.indexOf('async function runInstalledStudioSetupProfile'));
  assert.match(settlement, /stableSamplesRequired = 1/);
  assert.match(settlement, /if \(!preserveModal\) await navigateInstalledSurface/);
  assert.match(settlement, /route && !expected\.preserveModal\) route\.click\(\)/);
  assert.match(settlement, /!expected\.preserveModal \|\| control\.closest\('\.control-modal'\)/);
  assert.match(settlement, /nav_current: navCurrent/);
  assert.match(settlement, /advanceInstalledSurfaceControlSettlement\(state, consecutiveSamples, stableSamplesRequired\)/);
  assert.match(settlement, /surface: 'plugins', selector, stableSamplesRequired: 4/);
  assert.match(settlement, /preserveModal: installedPluginControlPreservesModal\(selector\)/);
  assert.doesNotMatch(readProfile, /querySelector\('\[data-surface="plugins"\]'\)\?*\.click\(\)/);
  assert.doesNotMatch(mutationProfile, /querySelector\('\[data-surface="plugins"\]'\)\?*\.click\(\)/);
  const mutate = mutationProfile.slice(mutationProfile.indexOf('const mutate = async spec'), mutationProfile.indexOf('const exerciseNativeManagerEntrypoints'));
  assert.ok(mutate.indexOf('for (const selector of Object.keys(spec.fields))') < mutate.indexOf('dispatchInstalledPluginFormAction(frameHost, spec.fields, spec.previewAction)'));
  assert.match(mutate, /previewRequestBefore = await installedOutboundRequestOffset[\s\S]*waitForInstalledOutboundRequest\(frameHost, previewRequestBefore, spec\.previewOperation\)/);
  assert.match(mutate, /requestId: previewRequest\.requestId[\s\S]*dispatchInstalledPluginConfirmation[\s\S]*responseOffset[\s\S]*requestOffset/);
  assert.doesNotMatch(mutate, /settleInstalledPluginControl\(frameHost, `\[data-action="\$\{spec\.executeAction\}"\]`/);
  assert.doesNotMatch(mutate, /dispatchEvent\(new Event\('input'[\s\S]*settleInstalledPluginControl/);
  const conflicts = mutationProfile.slice(mutationProfile.indexOf('const queryConflicts = async'), mutationProfile.indexOf('const exerciseConflictRoute'));
  assert.ok(conflicts.indexOf('[data-action="queryExtensionConflicts"]') < conflicts.indexOf('dispatchInstalledPluginFormAction'));
  assert.match(mutationProfile, /physicalVersion = await currentVersion\(null, \{ acceptAny: true \}\)[\s\S]*failure-cleanup-uninstall-[\s\S]*observation\.failure_cleanup_restored = physicalVersion === null/);
});

test('installed plugin preview confirmation requires one exact request, token, target, and modal control', () => {
  const expected = {
    responseType: 'extensionUpdatePreview', requestId: 'request-2',
    exactTarget: 'px-owned.fixture@2.0.0', executeAction: 'executeExtensionUpdate'
  };
  const observation = {
    response: { type: expected.responseType, requestId: expected.requestId, result: { token: 'token-2', exact_target: expected.exactTarget } },
    control: { action: expected.executeAction, token: 'token-2', exact_target: expected.exactTarget, visible: true, disabled: false, inside_modal: true }
  };
  assert.equal(installedPluginPreviewConfirmationMatches(observation, expected), true);
  for (const [branch, value] of [
    ['response.requestId', 'request-1'], ['response.result.token', 'token-1'],
    ['response.result.exact_target', 'px-owned.fixture@1.0.0'], ['control.token', 'token-1'],
    ['control.exact_target', 'px-owned.fixture@1.0.0'], ['control.visible', false],
    ['control.disabled', true], ['control.inside_modal', false]
  ]) {
    const changed = structuredClone(observation);
    const parts = branch.split('.');
    let target = changed;
    while (parts.length > 1) target = target[parts.shift()];
    target[parts[0]] = value;
    assert.equal(installedPluginPreviewConfirmationMatches(changed, expected), false, branch);
  }
});

test('installed plugin confirmation dispatch selects the exact identity atomically among stale duplicate controls', async () => {
  const clicked = [];
  const control = (token, exactTarget) => ({
    dataset: { action: 'executeExtensionUpdate', token, exactTarget },
    hidden: false,
    disabled: false,
    getAttribute: name => name === 'data-action' ? 'executeExtensionUpdate' : null,
    closest: selector => selector === '.control-modal' ? {} : null,
    click: () => clicked.push(token)
  });
  const stale = control('token-1', 'px-owned.fixture@1.0.0');
  const exact = control('token-2', 'px-owned.fixture@2.0.0');
  const frame = {
    contentDocument: { querySelectorAll: () => [stale, exact] },
    contentWindow: {
      __PX_INSTALLED_RESPONSES__: [{ type: 'extensionUpdatePreview' }],
      __PX_INSTALLED_REQUESTS__: [{ type: 'extensionUpdatePreview' }],
      getComputedStyle: () => ({ display: 'block', visibility: 'visible' })
    }
  };
  const previousCss = globalThis.CSS;
  globalThis.CSS = { escape: value => value };
  try {
    const result = await dispatchInstalledPluginConfirmation(
      { evaluate: (operation, item) => operation(frame, item) },
      { executeAction: 'executeExtensionUpdate', token: 'token-2', exactTarget: 'px-owned.fixture@2.0.0' },
      1
    );
    assert.equal(result.dispatched, true);
    assert.equal(result.responseOffset, 1);
    assert.equal(result.requestOffset, 1);
    assert.deepEqual(clicked, ['token-2']);
  } finally {
    globalThis.CSS = previousCss;
  }
});

test('installed plugin confirmation dispatch tolerates transient replacement but never clicks a substituted identity', async () => {
  const clicked = [];
  const makeControl = (token, exactTarget) => ({
    dataset: { action: 'executeExtensionUpdate', token, exactTarget },
    hidden: false,
    disabled: false,
    getAttribute: name => name === 'data-action' ? 'executeExtensionUpdate' : null,
    closest: selector => selector === '.control-modal' ? {} : null,
    click: () => clicked.push(token)
  });
  const substituted = makeControl('token-substitute', 'px-owned.fixture@9.9.9');
  const exact = makeControl('token-exact', 'px-owned.fixture@2.0.0');
  let evaluations = 0;
  const frame = {
    contentDocument: { querySelectorAll: () => (++evaluations === 1 ? [substituted] : [substituted, exact]) },
    contentWindow: {
      __PX_INSTALLED_RESPONSES__: [],
      __PX_INSTALLED_REQUESTS__: [],
      getComputedStyle: () => ({ display: 'block', visibility: 'visible' })
    }
  };
  const previousCss = globalThis.CSS;
  globalThis.CSS = { escape: value => value };
  try {
    const result = await dispatchInstalledPluginConfirmation(
      { evaluate: (operation, item) => operation(frame, item) },
      { executeAction: 'executeExtensionUpdate', token: 'token-exact', exactTarget: 'px-owned.fixture@2.0.0' },
      500
    );
    assert.equal(result.dispatched, true);
    assert.ok(evaluations >= 2);
    assert.deepEqual(clicked, ['token-exact']);

    await assert.rejects(
      dispatchInstalledPluginConfirmation(
        { evaluate: (operation, item) => operation({ ...frame, contentDocument: { querySelectorAll: () => [substituted] } }, item) },
        { executeAction: 'executeExtensionUpdate', token: 'token-exact', exactTarget: 'px-owned.fixture@2.0.0' },
        1
      ),
      /installed-plugin-confirmation-identity-mismatch:executeExtensionUpdate/
    );
    assert.deepEqual(clicked, ['token-exact']);
  } finally {
    globalThis.CSS = previousCss;
  }
});

test('installed plugin form dispatch atomically binds exact values and response offset before clicking', async () => {
  const events = [];
  const field = {
    value: '', hidden: false, disabled: false,
    getAttribute: () => null,
    dispatchEvent: event => events.push(event.type)
  };
  const route = {
    hidden: false, disabled: false,
    classList: { contains: value => value === 'nav-item' },
    getAttribute: name => name === 'aria-current' ? 'page' : null
  };
  const content = { classList: { contains: value => value === 'surface-plugins' } };
  let clickedValue = null;
  const action = {
    hidden: false, disabled: false,
    getAttribute: () => null,
    click: () => { clickedValue = field.value; }
  };
  const document = {
    querySelectorAll: selector => selector === '[data-surface="plugins"]' ? [route] : [],
    querySelector: selector => ({ '.content': content, '#extension-conflict-id': field, '[data-action="queryExtensionConflicts"]': action })[selector] || null
  };
  const frame = {
    contentDocument: document,
    contentWindow: {
      __PX_INSTALLED_RESPONSES__: [{ type: 'prior' }],
      getComputedStyle: () => ({ display: 'block', visibility: 'visible' })
    }
  };
  const frameHost = { evaluate: async (callback, item) => callback(frame, item) };
  const priorCss = globalThis.CSS;
  globalThis.CSS = { escape: value => value };
  try {
    const before = await dispatchInstalledPluginFormAction(frameHost, { '#extension-conflict-id': 'px-owned.fixture' }, 'queryExtensionConflicts');
    assert.equal(before, 1);
    assert.equal(clickedValue, 'px-owned.fixture');
    assert.deepEqual(events, ['input']);
  } finally {
    if (priorCss === undefined) delete globalThis.CSS;
    else globalThis.CSS = priorCss;
  }
});

test('owned lifecycle probe enters eight bounded admitted delays through the real agent start form', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /#studio-agent-tool-calls/);
  assert.match(source, /pxui\.studio-lifecycle\.form\.agentRunObjective/);
  assert.match(source, /pxui\.studio-lifecycle\.form\.workflowRunInputs/);
  assert.match(source, /Array\.from\(\{ length: 8 \}, \(\) => \(\{ tool: 'delay', input: 1\.5 \}\)\)/);
  assert.match(source, /invokeRunControl\('resume'\)[\s\S]*invokeRunControl\('stop'\)/);
  assert.match(source, /candidate\.kind === 'workflow'[\s\S]*invokeRunControl\('cancel'\)/);
  assert.doesNotMatch(source, /PX_INSTALLED_WORKFLOW_TERMINATION_ACTION/);
  assert.doesNotMatch(source, /__PX_INSTALLED_ORIGINAL_POST_MESSAGE__|inner\.eval/);
});

test('owned lifecycle probe exercises governed workflow approval and retained skill rollback', () => {
  const source = fs.readFileSync(path.join(__dirname, '../scripts/run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /\['register-authority', 'validate', 'dry-run', 'approve', 'start'\]/);
  assert.match(source, /candidate\.expect_rollback \? \['rollback'\]/);
  assert.match(source, /studio-skill-revision-rollback/);
  assert.match(source, /validStudioRevisionEditObservation\(revisedSkill\)/);
});

test('state-producing owned profiles run before the general installed control probe', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const main = source.slice(source.indexOf('async function main()'));
  const builder = main.indexOf('builders[kind] = await timedProfile(');
  const probe = main.indexOf('await probeInstalledControls(dashboard, proofMatrix, hostErrors)');
  const stateProducers = [
    'runInstalledReversibleConfigurationProfile(',
    'runInstalledStudioSetupProfile(',
    'runInstalledStudioCandidateSaveProfile(',
    'runInstalledStudioLifecycleProfile(',
    'runInstalledStudioRevisionEditProfile(',
    'runInstalledKnowledgeLifecycleProfile(',
    'runInstalledLearningLifecycleProfile(',
    'runInstalledCoordinationMemoryProfile(',
    'runInstalledCleanupProfile(',
    'runInstalledPluginReadProfile(',
    'runInstalledPluginMutationProfile('
  ];
  assert.ok(builder >= 0);
  assert.ok(probe > builder);
  const preBuilderBoundary = main.slice(main.indexOf('const pluginMutationProfile'), builder);
  assert.match(preBuilderBoundary, /timedProfile\([\s\S]*'pre-builder-baseline'[\s\S]*resetInstalledDashboardBaseline\(profileDashboardBaseline\.workbench, profileDashboardBaseline\.frameHost\)[\s\S]*timeoutMs: 30_000/);
  for (const operation of stateProducers) {
    const position = main.indexOf(operation);
    assert.ok(position >= 0, `${operation} is missing from main`);
    assert.ok(builder > position, `${operation} must precede general builder inspection`);
    assert.ok(probe > position, `${operation} must precede the installed control probe`);
  }
  assert.match(main, /skippedProfileResult\('studio-candidate-save', 'studio-setup'\)/);
  assert.match(main, /skippedProfileResult\('studio-lifecycle', 'studio-candidate-save'\)/);
  assert.match(main, /skippedProfileResult\('studio-revision-edit', 'studio-candidate-save'\)/);
  assert.match(main, /profile_failures: profileFailures/);
  assert.match(main, /additionalIssues: profileFailures\.map/);
  assert.doesNotMatch(main, /throw new Error\(`profile-prerequisite-failed:/);
  assert.match(main, /profileDashboardBaseline[\s\S]*resetInstalledDashboardBaseline\(profileDashboardBaseline\.workbench, profileDashboardBaseline\.frameHost\)/);
  const reset = source.slice(source.indexOf('async function resetInstalledDashboardBaseline'), source.indexOf('async function restartInstalledDashboardWebview'));
  assert.match(reset, /navigateInstalledSurface\(frameHost, 'dashboard'/);
  assert.match(reset, /owner: 'existing-webview'/);
  assert.match(reset, /catch[\s\S]*reopenPacifyDashboardFromOwnedUi[\s\S]*owner: 'pacify-statusbar'/);
});

test('owned Knowledge lifecycle establishes a fresh authoritative baseline instead of trusting route cache', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledKnowledgeLifecycleProfile'), source.indexOf('async function waitForInstalledMemoryText'));
  const route = profile.indexOf("navigateInstalledSurface(frameHost, 'knowledgeCore'");
  const refresh = profile.indexOf("waitForKnowledgeControl(frameHost, '[data-action=\"knowledgeRefresh\"]')", route);
  const baseline = profile.indexOf("waitForStudioOperationResult(frameHost, initialBefore, 'knowledge', 'browse'", refresh);
  assert.ok(route >= 0 && refresh > route && baseline > refresh);
  assert.match(source, /advanced-navigation-expansion-timeout/);
  assert.match(source, /data-action="toggleAdvanced"/);
  assert.match(source, /knowledge_actions/);
  assert.match(source, /timedProfile\('learning-lifecycle'/);
  assert.match(source, /Array\.from|for \(let index = 0; index < 6; index \+= 1\)/);
});

test('Learning admission waits for authoritative Knowledge refresh before transitioning the proposal', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledLearningLifecycleProfile'), source.indexOf('async function waitForCoordinationResult'));
  const admitted = profile.indexOf("waitForStudioOperationResult(frameHost, admitBefore, 'knowledge', 'admit-learning'");
  const refreshed = profile.indexOf("waitForStudioOperationResult(frameHost, admitBefore, 'knowledge', 'browse'", admitted);
  const transition = profile.indexOf("for (const operation of ['verify', 'approve', 'promote'])", refreshed);
  assert.ok(admitted >= 0 && refreshed > admitted && transition > refreshed);
  assert.match(profile, /learning-admit-refresh-invalid/);
});

test('blank portable memory is rejected by native field validity without dispatch', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledCoordinationMemoryProfile'), source.indexOf('function validCleanupResult'));
  assert.match(profile, /__PX_INSTALLED_REQUESTS__/);
  assert.match(profile, /value\?\.type === 'captureCoordinationMemory'/);
  assert.match(profile, /content\.validity\?\.valueMissing === true/);
  assert.match(profile, /content\.closest\('\.control-modal'\) != null/);
  assert.match(profile, /content\.value === ''/);
});

test('focused Knowledge execution skips unrelated profiles and keeps append-only timing evidence', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /PX_OPERATIONAL_KNOWLEDGE_LIFECYCLE_ONLY === '1'/);
  assert.match(source, /const focusedProfileOnly = Boolean\(focusedProfile\)/);
  assert.match(source, /ownedReversibleConfigurationAuthority && !configurationOnly && !knowledgeLifecycleOnly[\s\S]*runInstalledStudioSetupProfile/);
  assert.match(source, /ownedReversibleConfigurationAuthority && !configurationOnly && !studioLifecycleOnly[\s\S]*runInstalledKnowledgeLifecycleProfile/);
  assert.match(source, /profile-progress\.ndjson/);
  assert.match(source, /fs\.appendFileSync\(profileProgressPath/);
  assert.match(source, /PX_OPERATIONAL_CONFIGURATION_ONLY === '1'/);
  assert.match(source, /returnedProfileErrors/);
  assert.match(source, /\(!focusedProfileOnly \|\| configurationOnly\)/);
  assert.match(source, /ownedReversibleConfigurationAuthority && !await instrumentInstalledBridge\(dashboard\)/);
  assert.match(source, /full_operational_completion_claimed: focusedProfileOnly \? false/);
  assert.match(source, /ownedKnowledgeSourceId/);
  assert.match(source, /source\.options.*option\.value === values\.sourceId/);
  assert.match(source, /evidence\.value = `sha256:\$\{values\.sourceSha256\}`/);
  const main = source.slice(source.indexOf('async function main()'));
  const advanced = main.indexOf("if (!hostSourceMismatch && !studioLifecycleOnly)");
  const knowledge = main.indexOf("timedProfile('knowledge-lifecycle'", advanced);
  assert.ok(advanced >= 0 && knowledge > advanced);
});

test('profile progress error collection normalizes keyed collections and scalar errors', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('const profileItems ='), source.indexOf('let profileDashboardBaseline'));
  assert.match(profile, /Array\.isArray\(value\)[\s\S]*Object\.values\(value\)/);
  assert.match(profile, /value == null[\s\S]*Array\.isArray\(value\) \? value : \[value\]/);
  assert.match(profile, /profileItems\(result\?\.observations\)\.flatMap\(item => profileErrors\(item\?\.errors\)\)/);
  assert.match(profile, /profileItems\(result\?\.records\)\.flatMap\(item => profileErrors\(item\?\.errors\)\)/);
  assert.match(profile, /profileErrors\(result\?\.errors\)/);
  assert.match(profile, /new Set/);
  assert.doesNotMatch(profile, /\(result\?\.observations \|\| \[\]\)\.flatMap/);
  assert.doesNotMatch(profile, /\(result\?\.records \|\| \[\]\)\.flatMap/);
});

test('post-plugin baseline and builder work emit bounded profile progress', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const timed = source.slice(source.indexOf('const timedProfile ='), source.indexOf('const browser ='));
  assert.match(timed, /\{ resetBaseline = true, timeoutMs = null \}/);
  assert.match(timed, /boundedOwnedUiAction\(execute, timeoutMs, `installed-profile-\$\{profile\}`\)/);
  const builders = source.slice(source.indexOf('// Builder inspection uses shared webview working-draft state.'), source.indexOf('// Stateful profiles intentionally precede the general probe.'));
  assert.match(builders, /timedProfile\([\s\S]*'pre-builder-baseline'[\s\S]*resetBaseline: false, timeoutMs: 30_000/);
  assert.match(builders, /`\$\{kind\}-builder`[\s\S]*inspectStudioBuilder[\s\S]*resetBaseline: false, timeoutMs: 120_000/);
});

test('installed control probe populates authoritative per-control chains without promoting missing stages', () => {
  const stageRecords = STAGES.map(stage => ({ stage, status: 'not_attempted', observed_at: '2026-08-22T00:00:00Z', reason: 'not yet attempted' }));
  const controlChains = {
    controls: [{ control_id: 'pxui.demo.action.read', rendered: false, visible: false, attempted: false, terminal_disposition: 'not_rendered', stages: stageRecords }],
    aggregates: {}
  };
  const interactionChain = Object.fromEntries(STAGES.map(stage => [stage, {
    state: stage === 'failure_handling' ? 'missing' : 'present',
    detail: `direct ${stage}`,
    evidence: ['installed-receipt:pxui.demo.action.read']
  }]));
  applyInstalledProbeObservations(controlChains, {
    schema_version: 'px.installed-operational-control-probe/1.0',
    eligible_control_count: 1,
    records: [{ control_id: 'pxui.demo.action.read', rendered: true, attempted: true, interaction_chain: interactionChain }]
  });
  const record = controlChains.controls[0];
  assert.equal(record.attempted, true);
  assert.equal(record.stages.find(stage => stage.stage === 'display').status, 'observed');
  assert.equal(record.stages.find(stage => stage.stage === 'failure_handling').status, 'not_attempted');
  assert.equal(record.terminal_disposition, 'installed_operational_interaction_partial');
  assert.equal(controlChains.aggregates.complete_interaction_chains, 0);
});

test('installed control probe marks only a fully evidenced chain complete', () => {
  const controlChains = {
    controls: [{ control_id: 'pxui.demo.action.local', rendered: false, visible: false, attempted: false, terminal_disposition: 'not_rendered', stages: STAGES.map(stage => ({ stage, status: 'not_attempted' })) }],
    aggregates: {}
  };
  applyInstalledProbeObservations(controlChains, {
    schema_version: 'px.installed-operational-control-probe/1.0',
    eligible_control_count: 1,
    records: [{
      control_id: 'pxui.demo.action.local', rendered: true, attempted: true,
      interaction_chain: Object.fromEntries(STAGES.map(stage => [stage, { state: 'present', detail: `direct ${stage}`, evidence: ['owned-host'] }]))
    }]
  });
  assert.equal(controlChains.controls[0].terminal_disposition, 'installed_operational_interaction_complete');
  assert.equal(controlChains.aggregates.complete_interaction_chains, 1);
  assert.equal(controlChains.installed_probe_observations.complete_interaction_chains, 1);
});

test('installed control probe accepts a collected profile failure only through its typed zero-denominator probe', () => {
  const controlChains = { controls: [], aggregates: {} };
  applyInstalledProbeObservations(controlChains, {
    schema_version: 'px.installed-collected-profile-failure/1.0',
    profile: 'studio-candidate-save',
    errors: ['dependency-failed:studio-setup'],
    control_probe: {
      schema_version: 'px.installed-operational-control-probe/1.0',
      authority: 'The failed profile remains retained separately and contributes no successful control observations.',
      eligible_control_count: 0,
      records: []
    }
  }, 'studio_candidate_save_observations');
  assert.equal(controlChains.studio_candidate_save_observations.eligible_control_count, 0);
  assert.equal(controlChains.studio_candidate_save_observations.complete_interaction_chains, 0);
});

test('installed control probe preserves an explicit authority-skipped terminal boundary', () => {
  const controlChains = {
    controls: [{ control_id: 'pxui.runtime-core.action.cleanupPermanent', rendered: false, visible: false, attempted: false, terminal_disposition: 'not_rendered', stages: STAGES.map(stage => ({ stage, status: 'not_attempted' })) }],
    aggregates: {}
  };
  const interactionChain = Object.fromEntries(STAGES.map(stage => [stage, {
    state: stage === 'failure_handling' ? 'present' : 'missing', detail: stage, evidence: ['owned-host']
  }]));
  applyInstalledProbeObservations(controlChains, {
    schema_version: 'px.installed-operational-control-probe/1.0', eligible_control_count: 1,
    records: [{ control_id: 'pxui.runtime-core.action.cleanupPermanent', rendered: true, attempted: true, authority_skipped: true, interaction_chain: interactionChain, errors: [] }]
  });
  assert.equal(controlChains.controls[0].terminal_disposition, 'skipped_requires_authority');
  assert.ok([
    controlChains.controls[0].authority,
    controlChains.controls[0].reason,
    controlChains.controls[0].expected_effect,
    controlChains.controls[0].return_condition
  ].every(value => typeof value === 'string' && value.trim()));
  assert.equal(controlChains.aggregates.complete_interaction_chains, 0);
});

test('installed control probe reports rendered, absent, and errored controls truthfully', () => {
  const controls = ['rendered', 'absent', 'errored'].map(name => ({
    control_id: `pxui.demo.indicator.${name}`,
    rendered: false,
    visible: false,
    attempted: false,
    terminal_disposition: 'not_rendered',
    stages: STAGES.map(stage => ({ stage, status: 'not_attempted' }))
  }));
  const incompleteChain = Object.fromEntries(STAGES.map(stage => [stage, {
    state: stage === 'display' ? 'present' : 'missing',
    detail: stage,
    evidence: ['owned-host']
  }]));
  applyInstalledProbeObservations({ controls, aggregates: {} }, {
    schema_version: 'px.installed-operational-control-probe/1.0',
    eligible_control_count: 3,
    records: [
      { control_id: controls[0].control_id, rendered: true, attempted: false, interaction_chain: incompleteChain, errors: [] },
      { control_id: controls[1].control_id, rendered: false, attempted: false, interaction_chain: incompleteChain, errors: [] },
      { control_id: controls[2].control_id, rendered: false, attempted: false, interaction_chain: incompleteChain, errors: ['exact probe failed'] }
    ]
  });
  assert.deepEqual(controls.map(control => control.terminal_disposition), [
    'installed_operational_observation_partial',
    'installed_control_not_rendered',
    'installed_operational_probe_error'
  ]);
});

test('installed lifecycle crash harness force-terminates and reconciles promotion and rollback', { timeout: 30_000 }, () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-installed-lifecycle-crash-'));
  const harness = path.join(__dirname, 'installed-harness', 'studio_lifecycle_crash_worker.py');
  try {
    for (const operation of ['promotion', 'rollback']) {
      const operationRoot = path.join(root, operation);
      const crashed = spawnSync('python', [harness, '--root', operationRoot, '--operation', operation], {
        cwd: path.resolve(__dirname, '..', '..'), encoding: 'utf8', windowsHide: true, timeout: 15_000
      });
      assert.equal(crashed.status, 91, `${operation} did not terminate at the durable projection boundary: ${crashed.stderr}`);
      assert.equal(crashed.signal, null);
      const recovered = spawnSync('python', [harness, '--root', operationRoot, '--operation', operation, '--recover'], {
        cwd: path.resolve(__dirname, '..', '..'), encoding: 'utf8', windowsHide: true, timeout: 15_000
      });
      assert.equal(recovered.status, 0, recovered.stderr);
      const receipt = JSON.parse(recovered.stdout.trim().split(/\r?\n/).at(-1));
      assert.equal(receipt.schema_version, 'px.installed-studio-lifecycle-crash/1.0');
      assert.equal(receipt.operation, operation);
      assert.equal(receipt.crash_exit, 91);
      assert.equal(receipt.canonical_exists, true);
      assert.match(receipt.canonical_tree_sha256, /^[0-9a-f]{64}$/);
      assert.equal(receipt.recovery.valid, true);
    }
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('installed late-card worker proves physical allocation and authenticated skill projection boundaries', { timeout: 60_000 }, () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-installed-late-card-'));
  const harness = path.join(__dirname, 'installed-harness', 'studio_late_card_worker.py');
  try {
    const completed = spawnSync('python', [harness, '--root', root], {
      cwd: path.resolve(__dirname, '..', '..'), encoding: 'utf8', windowsHide: true, timeout: 45_000,
      env: { ...process.env, PX_OWNED_ENGINE_ROOT: path.resolve(__dirname, '..', '..') }
    });
    assert.equal(completed.status, 0, completed.stderr);
    assert.equal(completed.signal, null);
    const receipt = JSON.parse(completed.stdout.trim().split(/\r?\n/).at(-1));
    assert.equal(receipt.schema_version, 'px.installed-studio-late-card-worker/1.0');
    assert.equal(receipt.completed, true, JSON.stringify(receipt));
    assert.equal(Object.values(receipt.physical).every(Boolean), true);
    assert.equal(Object.values(receipt.fork).every(Boolean), true);
    assert.equal(Object.values(receipt.skill).every(Boolean), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('late-card denominator fails closed and accepts only the complete exact installed evidence set', () => {
  const candidate = kind => ({ kind, typed_creation_receipt: true, webview_restarted: true, reopened_catalog_match: true, errors: [] });
  const revision = kind => ({
    kind, editor_bound: true, stale_result_rejected: true, unchanged_save_rejected: true,
    typed_creation_receipt: true, reopened_catalog_match: true, predecessor_preserved: true,
    content_changed: true, reopened_editor_content_match: true, original_owner: 'owner:before',
    changed_owner: 'owner:after', predecessor_revision_sha256: '1'.repeat(64),
    predecessor_content_sha256: '2'.repeat(64), saved_revision_sha256: '3'.repeat(64),
    saved_content_sha256: '4'.repeat(64), version_conflict_rendered: true,
    version_suggestion_accepted: true, version_conflict_host_dispatch_suppressed: true,
    fork_verified: true, errors: []
  });
  const lifecycle = kind => ({
    kind, exact_catalog_selection: true, errors: [],
    operations: (kind === 'skill' ? ['validate', 'admit', 'promote', 'rollback'] : ['status'])
      .map(operation => ({ operation, valid: true }))
  });
  const broadProxyOnly = buildInstalledLateCardScenarioProfile({
    hostSourceMismatch: false,
    observationStateProfile: { observations: { 'pxui.knowledge-graph.action.graphLoadAll': { rendered: true, attempted: true, completed: true, recovered: true } } },
    candidateProfile: { observations: ['agent', 'workflow', 'skill'].map(candidate) },
    revisionProfile: { observations: ['agent', 'workflow', 'skill'].map(revision) },
    lifecycleProfile: { observations: ['agent', 'workflow', 'skill'].map(lifecycle) },
    crashProfile: { completed: true, observations: ['promotion', 'rollback'].map(operation => ({ operation, recovered: true, terminated_exit: 91 })) }
  });
  assert.equal(broadProxyOnly.completed, false);
  assert.equal(broadProxyOnly.records.every(record => record.completed === false), true);
  const adversarialProfile = {
    records: broadProxyOnly.records.map(record => ({
      schema_version: 'px.installed-late-card-evidence/1.0',
      gap_id: record.gap_id,
      checks: Object.fromEntries(record.required_checks.map(name => [name, true])),
      evidence: [`installed-exact:${record.gap_id}`],
      errors: []
    }))
  };
  const complete = buildInstalledLateCardScenarioProfile({ hostSourceMismatch: false, adversarialProfile });
  assert.equal(complete.completed, true);
  assert.equal(complete.records.length, 15);
  assert.equal(complete.records.every(record => record.completed), true);
  const incomplete = buildInstalledLateCardScenarioProfile({ hostSourceMismatch: true, adversarialProfile });
  assert.equal(incomplete.completed, false);
  assert.equal(incomplete.records.every(record => record.completed === false), true);
});

test('installed bridge conflict profile accepts only exit two and never retries mutation', async () => {
  const profile = await runInstalledStudioBridgeConflictProfile();
  assert.equal(profile.completed, true, JSON.stringify(profile));
  assert.deepEqual(profile.checks, {
    exit_2_exact_conflict: true,
    exit_1_lookalike_rejected: true,
    no_mutation_retry: true,
    request_bound_reason: true
  });
});

test('late-card exact producer runs physical, controller, bridge, and incompleteness owners before admission', () => {
  assert.equal(typeof buildInstalledLateCardAdversarialProfile, 'function');
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const controller = source.slice(source.indexOf('async function runInstalledStudioControllerAdversarialProfile'), source.indexOf('function buildInstalledLateCardAdversarialProfile'));
  for (const predicate of [
    'stale_allocation_ignored', 'cross_kind_allocation_ignored', 'cancelled_allocation_cannot_reopen',
    'physical_skill_hash_substitution_rejected', 'missing_selection_rejected', 'initial_conflict_rejected',
    'overlapping_save_a_detached', 'save_b_preserved', 'stale_failure_a_ignored', 'matching_failure_b_clears_only_b'
  ]) assert.match(controller, new RegExp(predicate));
  const main = source.slice(source.indexOf('async function main()'));
  assert.match(main, /studio-late-card-worker[\s\S]*studio-controller-adversarial[\s\S]*studio-bridge-conflict[\s\S]*buildInstalledLateCardAdversarialProfile/);
  assert.match(main, /buildInstalledLateCardScenarioProfile\(\{[\s\S]*adversarialProfile: lateCardAdversarialProfile/);
});

test('graph load-all exposes bounded cancellation before continuing pages', () => {
  const controller = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '90-controller.js'), 'utf8');
  const surface = fs.readFileSync(path.join(__dirname, '..', 'media', 'dashboard', '48-graph-surface.js'), 'utf8');
  assert.match(controller, /state\.graphLoadAll && state\.graphPending/);
  assert.match(controller, /state\.graphLoadAll = false; renderPreservingControl/);
  assert.match(surface, /Cancel load all/);
  assert.match(surface, /!state\.graphPending \|\| state\.graphLoadAll/);
});
