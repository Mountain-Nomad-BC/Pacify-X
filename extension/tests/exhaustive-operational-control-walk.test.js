'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  STAGES, actionIdentity, candidateScore, completeChain, directSelectorFor, meaningfulTokens, revealActionFor, selectorForKind, semanticLabel, stageResult, studioDraftRequired, variantsMatch, visualVariantsMatch
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
});

test('conditional editor fields use exact DOM identities instead of fuzzy labels', () => {
  assert.equal(directSelectorFor({ control_id: 'pxui.agent-studio.field.model.version' }), '[data-agent-model-field="version"]');
  assert.equal(directSelectorFor({ control_id: 'pxui.diagnostics.field.operationalCardEvidenceGap' }), '[data-operational-card-evidence-gap]');
  assert.equal(directSelectorFor({ control_id: 'pxui.workflow-studio.field.canonicalJson' }), '#studio-draft-json');
  assert.equal(directSelectorFor({ control_id: 'pxui.knowledge-core.field.dependencyHashJson' }), '#learning-dependencies');
  assert.equal(directSelectorFor({ control_id: 'pxui.workflows.field.environmentExactTarget' }), '#environment-lifecycle-target');
  assert.equal(directSelectorFor({ control_id: 'pxui.dashboard.indicator.counts' }), null);
});

test('Studio landing actions remain outside the draft modal', () => {
  assert.equal(studioDraftRequired('agent-studio', { control_id: 'pxui.agent-studio.action.setupStudio' }), false);
  assert.equal(studioDraftRequired('workflow-studio', { control_id: 'pxui.workflow-studio.action.openStudioDraft.workflow' }), false);
  assert.equal(studioDraftRequired('skill-studio', { control_id: 'pxui.skill-studio.action.openStudioRuns.skill' }), false);
  assert.equal(studioDraftRequired('agent-studio', { control_id: 'pxui.agent-studio.field.instructions' }), true);
  assert.equal(studioDraftRequired('agents', { control_id: 'pxui.agents.action.setupStudio' }), false);
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
