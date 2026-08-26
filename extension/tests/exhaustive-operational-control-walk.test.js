'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  STAGES, actionIdentity, candidateScore, completeChain, directSelectorFor, exactActionSelectorFor, meaningfulTokens, preparationKey, revealActionFor, resumeReceiptCompatible, selectorForKind, semanticLabel, sidebarActionSelector, sidebarFixtureMessage, stageResult, studioDraftRequired, variantsMatch, visualVariantsMatch
} = require('../scripts/run-exhaustive-operational-control-walk');

test('semantic resolver uses meaningful exact identity tokens', () => {
  assert.deepEqual(meaningfulTokens('binding.capability_id'), ['binding', 'capability', 'id']);
  assert.equal(candidateScore('binding.capability_id', { attributes: 'data-agent-binding-field=capability_id', text: 'Capability' }), 1);
  assert.ok(candidateScore('candidateMetadata', { attributes: 'class=studio-candidate-metadata', text: 'Candidate metadata' }) >= 1);
  assert.equal(candidateScore('captureActive', { attributes: 'role=status', text: 'unrelated' }), 0);
});

test('semantic label is parsed from the exact kind boundary', () => {
  assert.equal(semanticLabel({ kind: 'field', control_id: 'pxui.agent-studio.field.binding.capability_id' }), 'binding.capability_id');
  assert.equal(semanticLabel({ kind: 'indicator', control_id: 'pxui.sidebar.indicator.currentWorkspace' }), 'currentWorkspace');
  assert.throws(() => semanticLabel({ kind: 'field', control_id: 'pxui.activity.action.refresh' }), /kind boundary/);
});

test('action variants preserve exact repeated row identity', () => {
  assert.deepEqual(actionIdentity('dynamicRepair.repairNow.blocker'), { action: 'repairNow', variants: ['blocker'] });
  assert.deepEqual(actionIdentity('inspectCatalogItem.row'), { action: 'inspectCatalogItem', variants: ['row'] });
  assert.equal(variantsMatch({ recordId: 'agent:one' }, ['row']), true);
  assert.equal(variantsMatch({ kind: 'agent' }, ['workflow']), false);
  assert.equal(visualVariantsMatch({ delta: '-0.1' }, ['out'], 'agent canvas toolbar'), true);
  assert.equal(visualVariantsMatch({}, ['minimap'], 'agent-graph-minimap'), true);
});

test('state-bound semantic controls declare their exact reveal action', () => {
  assert.equal(revealActionFor({ control_id: 'pxui.knowledge-core.field.researchQuestion' }), 'learningResearch');
  assert.equal(revealActionFor({ control_id: 'pxui.knowledge-core.field.betterAlternativeFound' }), 'learningResearch');
  assert.equal(revealActionFor({ control_id: 'pxui.agent-studio.field.canonicalJson' }), 'studioEditorTab');
  assert.equal(revealActionFor({ control_id: 'pxui.workflows.field.claimTTL' }), 'claimTask');
  assert.equal(revealActionFor({ control_id: 'pxui.skills-tools.field.skillQueryGoal' }), 'skillSemanticQuery');
  assert.equal(revealActionFor({ control_id: 'pxui.dashboard.indicator.counts' }), null);
  assert.equal(revealActionFor({ control_id: 'pxui.dashboard-control-plane.action.copyModal' }), 'inspectMetric');
  assert.equal(revealActionFor({ control_id: 'pxui.dashboard-control-plane.menu.informationTabs' }), 'inspectMetric');
  assert.equal(revealActionFor({ control_id: 'pxui.dashboard-control-plane.action.commandCenter' }), null);
  assert.equal(revealActionFor({ control_id: 'pxui.dashboard-control-plane.menu.commandCenter' }), 'commandCenter');
  assert.equal(revealActionFor({ control_id: 'pxui.dashboard-control-plane.action.closeModal' }), 'commandCenter');
  assert.equal(revealActionFor({ control_id: 'pxui.knowledge-graph.action.submitGraphSavedView' }), 'graphSaveView');
  assert.equal(revealActionFor({ control_id: 'pxui.workflows.action.submitParallelPlan' }), 'newParallelPlan');
  assert.equal(revealActionFor({ control_id: 'pxui.workflows.action.submitReleaseTask' }), 'releaseTask');
  assert.equal(revealActionFor({ control_id: 'pxui.runtime-core.action.cleanupRecycle' }), 'cleanupManager');
});

test('conditional editor fields use exact DOM identities instead of fuzzy labels', () => {
  assert.equal(directSelectorFor({ control_id: 'pxui.agent-studio.field.model.version' }), '[data-agent-model-field="version"]');
  assert.equal(directSelectorFor({ control_id: 'pxui.diagnostics.field.operationalCardEvidenceGap' }), '[data-operational-card-evidence-gap]');
  assert.equal(directSelectorFor({ control_id: 'pxui.workflow-studio.field.canonicalJson' }), '#studio-draft-json');
  assert.equal(directSelectorFor({ control_id: 'pxui.knowledge-core.field.dependencyHashJson' }), '#learning-dependencies');
  assert.equal(directSelectorFor({ control_id: 'pxui.workflows.field.environmentExactTarget' }), '#environment-lifecycle-target');
  assert.equal(directSelectorFor({ control_id: 'pxui.dashboard.indicator.counts' }), '.metric-grid');
  assert.equal(directSelectorFor({ control_id: 'pxui.dashboard-control-plane.menu.mainNavigation' }), '.nav-rail');
  assert.equal(directSelectorFor({ control_id: 'pxui.knowledge-graph.gesture.ctrlWheelZoom' }), '[data-graph-canvas]');
  assert.equal(directSelectorFor({ control_id: 'pxui.knowledge-graph.menu.depth' }), '[aria-label="Relationship depth"]');
  assert.equal(directSelectorFor({ control_id: 'pxui.agent-studio.form.candidateMetadata' }), '.studio-guided-grid');
  assert.equal(directSelectorFor({ control_id: 'pxui.workflow-studio.editor.visualGraph' }), '[data-workflow-editor-canvas]');
  assert.equal(directSelectorFor({ control_id: 'pxui.skill-studio.editor.packageFile' }), '#studio-skill-file');
  assert.equal(directSelectorFor({ control_id: 'pxui.workflow-studio.gesture.dragPaletteNodeToCanvas' }), '[data-workflow-editor-canvas]');
  assert.equal(directSelectorFor({ control_id: 'pxui.dashboard.indicator.coordinationSummary' }), '.coord-summary');
  assert.equal(directSelectorFor({ control_id: 'pxui.skills-tools.indicator.queryPending' }), '.cleanup-loading');
});

test('Plugin integrity controls resolve to their truthful always-visible records', () => {
  assert.equal(directSelectorFor({ control_id: 'pxui.plugins.indicator.inventoryGeneration' }), '[data-plugin-integrity="generation"]');
  assert.equal(directSelectorFor({ control_id: 'pxui.plugins.indicator.shardHashMatch' }), '[data-plugin-integrity="shard-hash"]');
});

test('Studio lifecycle failure indicators resolve to the request-bound modal state', () => {
  assert.equal(directSelectorFor({ control_id: 'pxui.studio-lifecycle.indicator.error' }), '#modal-root [role="alert"]');
  assert.equal(directSelectorFor({ control_id: 'pxui.studio-lifecycle.indicator.notAccepted' }), '#modal-root .eyebrow');
});

test('focused current-source walks remain truthful without inherited predecessor evidence', () => {
  const source = fs.readFileSync(path.join(__dirname, '../scripts/run-exhaustive-operational-control-walk.js'), 'utf8');
  assert.doesNotMatch(source, /PX_OPERATIONAL_CONTROL_PATTERN requires --resume/);
  assert.match(source, /Control was outside this focused current-source run/);
  assert.match(source, /unselected_controls_explicitly_unattempted: !priorReceipt/);
  assert.ok(source.indexOf("if (controlPattern && selectedIndexes.length === 0)") < source.indexOf('const browser = await chromium.launch'));
});

test('variant graph actions use exact selectors', () => {
  assert.equal(exactActionSelectorFor({ control_id: 'pxui.knowledge-graph.action.graphDepth.decrease' }), '[data-action="graphDepth"][data-delta="-1"]');
  assert.equal(exactActionSelectorFor({ control_id: 'pxui.knowledge-graph.action.graphDepth.increase' }), '[data-action="graphDepth"][data-delta="1"]');
  assert.equal(exactActionSelectorFor({ control_id: 'pxui.knowledge-graph.action.graphFit.button' }), '[data-action="graphFit"]:not(.graph-minimap)');
  assert.equal(exactActionSelectorFor({ control_id: 'pxui.dashboard-control-plane.action.informationTab.machine' }), '[data-action="informationTab"][data-tab="machine"]');
  assert.equal(exactActionSelectorFor({ control_id: 'pxui.projects.action.inspectProjectMapRecord.test-link' }), '[data-action="inspectProjectMapRecord"][data-record-kind="test_links"]');
  assert.equal(exactActionSelectorFor({ control_id: 'pxui.plugins.action.inspectMachineManifest.footer' }), ':nth-match([data-action="inspectMachineManifest"], 2)');
  assert.equal(exactActionSelectorFor({ control_id: 'pxui.settings.action.openSettings.guardrails' }), ':nth-match([data-action="openSettings"], 3)');
});

test('Studio landing actions remain outside the draft modal', () => {
  assert.equal(studioDraftRequired('agent-studio', { control_id: 'pxui.agent-studio.action.setupStudio' }), false);
  assert.equal(studioDraftRequired('workflow-studio', { control_id: 'pxui.workflow-studio.action.openStudioDraft.workflow' }), false);
  assert.equal(studioDraftRequired('skill-studio', { control_id: 'pxui.skill-studio.action.openStudioRuns.skill' }), false);
  assert.equal(studioDraftRequired('agent-studio', { control_id: 'pxui.agent-studio.field.instructions' }), true);
  assert.equal(studioDraftRequired('agents', { control_id: 'pxui.agents.action.setupStudio' }), false);
});

test('conditional state fixtures have distinct preparation identities', () => {
  assert.equal(preparationKey({ surface_id: 'activity', control_id: 'pxui.activity.indicator.queryError' }), 'activity:pxui.activity.indicator.queryError');
  assert.equal(preparationKey({ surface_id: 'activity', control_id: 'pxui.activity.indicator.liveOperations' }), 'activity');
  assert.notEqual(preparationKey({ surface_id: 'agents', control_id: 'pxui.agents.indicator.catalogError' }), preparationKey({ surface_id: 'agents', control_id: 'pxui.agents.indicator.catalogPending' }));
});

test('complete chain rejects any missing or partial required stage', () => {
  const complete = Object.fromEntries(STAGES.map(stage => [stage, { state: 'not_applicable' }]));
  complete.open_load.state = 'present';
  assert.equal(completeChain(complete), true);
  complete.failure_handling.state = 'missing';
  assert.equal(completeChain(complete), false);
});

test('a semantic live-state display acknowledges only its visible result', () => {
  const requirement = { kind: 'indicator', stage_policy: Object.fromEntries(STAGES.map(stage => [stage, 'required'])) };
  const probe = { loaded: true, visible: true, attempted: false, validationObserved: false, acknowledged: true, details: {} };
  assert.equal(stageResult(requirement, probe, 'display', 'receipt:indicator').state, 'present');
  assert.equal(stageResult(requirement, probe, 'result_acknowledgement', 'receipt:indicator').state, 'present');
  assert.equal(stageResult(requirement, probe, 'runtime_effect', 'receipt:indicator').state, 'missing');
  assert.match(selectorForKind('indicator'), /h2/);
});

test('sidebar controls receive a rich typed projection and exact selectors', () => {
  const healthy = sidebarFixtureMessage();
  const disconnected = sidebarFixtureMessage({ disconnected: true });
  assert.equal(healthy.type, 'snapshot');
  assert.equal(healthy.projection.execution.planId, 'plan-live');
  assert.ok(healthy.projection.providerState.providers.length >= 2);
  assert.equal(disconnected.projection.status.state, 'disconnected');
  assert.equal(sidebarActionSelector({ control_id: 'pxui.sidebar.action.openEntity.agent' }), '[data-entity-type="agent"]');
  assert.equal(sidebarActionSelector({ control_id: 'pxui.sidebar.action.openPlanFromPunch' }), '[data-plan-punch]');
  assert.equal(sidebarActionSelector({ control_id: 'pxui.sidebar.action.toggleTask.row' }), '[data-toggle-task]');
  assert.equal(directSelectorFor({ control_id: 'pxui.sidebar.indicator.providerBudget' }), '#providers');
});

test('resume accepts a matrix metadata revision only when semantic commitments match', () => {
  const policy = Object.fromEntries(STAGES.map(stage => [stage, stage === 'progress_reporting' ? 'not_applicable_with_evidence' : 'required']));
  const control = { control_id: 'pxui.sidebar.action.retry', surface_id: 'sidebar', kind: 'action', evidence_mode: 'contained_sidebar_interaction', stage_policy: policy };
  const sourceManifest = { schema_version: 'px.current-source-control-manifest/2.0', files: [], source_sha256: 'a'.repeat(64) };
  const receipt = {
    schema_version: 'px.exhaustive-operational-control-walk/1.0',
    source: { matrix_sha256: 'b'.repeat(64), control_source_manifest: sourceManifest },
    records: [{
      control_id: control.control_id,
      surface_id: control.surface_id,
      control_kind: control.kind,
      evidence_mode: control.evidence_mode,
      interaction_chain: Object.fromEntries(STAGES.map(stage => [stage, { state: stage === 'progress_reporting' ? 'not_applicable' : 'missing' }]))
    }]
  };
  assert.equal(resumeReceiptCompatible(receipt, { controls: [control] }, 'c'.repeat(64), sourceManifest), true);
  receipt.records[0].interaction_chain.progress_reporting.state = 'missing';
  assert.equal(resumeReceiptCompatible(receipt, { controls: [control] }, 'c'.repeat(64), sourceManifest), false);
});
