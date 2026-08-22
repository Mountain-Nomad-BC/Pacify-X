'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { applyInstalledProbeObservations, eligibleInstalledControl, installedActionIdentity, installedStudioPrerequisites, validStudioDraftReceipt, validStudioLifecycleResult, validStudioSetupResult } = require('../scripts/run-operational-ui-walk');

const STAGES = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];

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
  assert.deepEqual(installedStudioPrerequisites({ control_id: 'pxui.projects.field.identity' }), []);
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
});

test('owned installed Studio candidate save accepts only kind-exact durable receipts', () => {
  const agent = { schema_version: 'px.agent-creation-receipt/1.1', agent_id: 'agent:px-owned', version: '1.0.0', created: true, record_sha256: 'a'.repeat(64) };
  const workflow = { schema_version: 'px.workflow-revision-receipt/1.2', workflow_id: 'workflow:px-owned', version: '1.0.0', created: true, revision_sha256: 'b'.repeat(64) };
  const skill = { schema_version: 'px.skill-draft/1.1', manifest: { skill_id: 'px-owned', version: '1.0.0' }, manifest_sha256: 'c'.repeat(64), source_tree_sha256: 'd'.repeat(64) };
  assert.equal(validStudioDraftReceipt('agent', agent, agent.agent_id), true);
  assert.equal(validStudioDraftReceipt('workflow', workflow, workflow.workflow_id), true);
  assert.equal(validStudioDraftReceipt('skill', skill, skill.manifest.skill_id), true);
  assert.equal(validStudioDraftReceipt('agent', { ...agent, created: false }, agent.agent_id), false);
  assert.equal(validStudioDraftReceipt('workflow', workflow, 'workflow:other'), false);
  assert.equal(validStudioDraftReceipt('skill', { ...skill, source_tree_sha256: 'bad' }, skill.manifest.skill_id), false);
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
  assert.equal(validStudioLifecycleResult('workflow', 'runs', { schema_version: 'px.studio-run-list/1.0', kind: 'workflow', runs: [] }), true);
  assert.equal(validStudioLifecycleResult('skill', 'promote', { schema_version: 'px.skill-promotion-receipt/1.3', state: 'promoted' }), false);
  assert.equal(validStudioLifecycleResult('agent', 'admit', { schema_version: 'px.agent-admission-receipt/1.1', decision: 'rejected' }), false);
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
  assert.match(source, /id\|index\|row\|key\|path/);
  assert.match(source, /blockedSurfaces\.set\(control\.surface_id, message\)/);
  assert.match(source, /proofMatrix\.controls\.length !== inventory\.control_count/);
  assert.match(source, /const document = frame\.contentDocument/);
  assert.match(source, /inner\.__PX_INSTALLED_RESPONSES__/);
  assert.doesNotMatch(source, /elementHandle\(\).*contentFrame/);
  assert.match(source, /if \(close\) close\.click\(\)/);
  assert.match(source, /__PX_INSTALLED_BRIDGE_INSTRUMENTED__/);
  assert.match(source, /inner\.__PX_INSTALLED_RESPONSES__\.push/);
  assert.match(source, /acknowledgementDeadline = Date\.now\(\) \+ \(spec\.local \? 80 : 3_000\)/);
  assert.match(source, /\['authorization', 'backend_dispatch', 'runtime_effect'\]/);
  assert.match(source, /probe\.attempted && probe\.acknowledged/);
  assert.match(source, /installed_control_probe: installedControlProbe/);
  assert.match(source, /reversible_configuration_profile: reversibleConfigurationProfile/);
  assert.match(source, /studio_setup_profile: studioSetupProfile/);
  assert.match(source, /studio_candidate_save_profile: studioCandidateSaveProfile/);
  assert.match(source, /runInstalledStudioSetupProfile/);
  assert.match(source, /setupStudio-positive-counts-not-observed/);
  assert.match(source, /data-action="surfaceScope"\]\[data-target="agents"\]\[data-scope="core"/);
  assert.match(source, /PX_OWNED_VSCODE_HOST/);
  assert.match(source, /--px-owned-token=/);
  assert.match(source, /installed-reversible-configuration/);
  assert.match(source, /restoration-mismatch/);
  assert.match(source, /waitForInstalledConfigurationTarget/);
  assert.match(source, /This success\/restoration profile did not inject a configuration failure/);
  assert.match(source, /isVisible\(\{ timeout: 750 \}\)/);
  assert.match(source, /invokeInstalledHostAction/);
  assert.match(source, /Lease-bound canonical retrieval is ready/);
  assert.match(source, /disconnectCanonicalMemory/);
  assert.match(source, /canonical-memory-restoration-mismatch/);
  assert.match(source, /px\.installed-operational-control-probe\/1\.0/);
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
