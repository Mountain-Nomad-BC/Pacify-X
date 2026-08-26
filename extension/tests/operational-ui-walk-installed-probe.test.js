'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { applyInstalledProbeObservations, eligibleInstalledControl, engineOutageRecord, installedActionIdentity, installedStudioPrerequisites, knowledgeBrowseHasHead, validKnowledgeLifecycleResult, validStudioDraftReceipt, validStudioLifecycleResult, validStudioRevisionEditObservation, validStudioSetupResult } = require('../scripts/run-operational-ui-walk');

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
  assert.equal(validStudioDraftReceipt('agent', { ...agent, version: '1.0.1' }, agent.agent_id, '1.0.1'), true);
  assert.equal(validStudioDraftReceipt('workflow', { ...workflow, version: '1.0.1' }, workflow.workflow_id, '1.0.1'), true);
  assert.equal(validStudioDraftReceipt('agent', agent, agent.agent_id, '1.0.1'), false);
  assert.equal(validStudioDraftReceipt('agent', { ...agent, created: false }, agent.agent_id), false);
  assert.equal(validStudioDraftReceipt('workflow', workflow, 'workflow:other'), false);
  assert.equal(validStudioDraftReceipt('skill', { ...skill, source_tree_sha256: 'bad' }, skill.manifest.skill_id), false);
});

test('owned installed revision edit requires changed content, preserved predecessor, and physical reopen', () => {
  const observation = {
    editor_bound: true,
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
  assert.equal(validStudioRevisionEditObservation({ ...observation, saved_revision_sha256: 'invalid' }), false);
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
  assert.match(source, /studio_revision_edit_profile: studioRevisionEditProfile/);
  assert.match(source, /engine_outage_profile: engineOutageProfile/);
  assert.match(source, /beginOwnedEngineOutage\(process\.env\.PX_OWNED_ENGINE_ROOT, ownedHostToken\)/);
  assert.match(source, /querySelector\('\[data-surface="dashboard"\]'\)[\s\S]*dashboard\.click\(\);[\s\S]*querySelectorAll\('\[data-action="refresh"\]'\)/);
  assert.match(source, /runInstalledStudioRevisionEditProfile/);
  assert.match(source, /kind: 'skill', submitControlId: 'pxui\.skill-studio\.action\.submitStudioDraft\.skill'/);
  assert.match(source, /kind === 'skill' \? 'loadSkillPackageEditor' : 'openStudioFromCatalog'/);
  assert.match(source, /revision-editor-binding-timeout/);
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
  assert.match(source, /This success\/restoration profile did not inject a configuration failure/);
  assert.match(source, /isVisible\(\{ timeout: 750 \}\)/);
  assert.match(source, /invokeInstalledHostAction/);
  assert.match(source, /Lease-bound canonical retrieval is ready/);
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
});

test('owned lifecycle probe enters eight bounded admitted delays through the real agent start form', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  assert.match(source, /#studio-agent-tool-calls/);
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
  const probe = main.indexOf('await probeInstalledControls(dashboard, proofMatrix, hostErrors)');
  assert.ok(probe > main.indexOf('await runInstalledReversibleConfigurationProfile('));
  assert.ok(probe > main.indexOf('await runInstalledStudioSetupProfile('));
  assert.ok(probe > main.indexOf('await runInstalledStudioCandidateSaveProfile('));
  assert.ok(probe > main.indexOf('await runInstalledStudioLifecycleProfile('));
  assert.ok(probe > main.indexOf('await runInstalledStudioRevisionEditProfile('));
  assert.ok(probe > main.indexOf('await runInstalledKnowledgeLifecycleProfile('));
});

test('owned Knowledge lifecycle establishes a fresh authoritative baseline instead of trusting route cache', () => {
  const source = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'run-operational-ui-walk.js'), 'utf8');
  const profile = source.slice(source.indexOf('async function runInstalledKnowledgeLifecycleProfile'), source.indexOf('async function waitForInstalledMemoryText'));
  const route = profile.indexOf('[data-surface="knowledgeCore"]');
  const refresh = profile.indexOf("waitForKnowledgeControl(frameHost, '[data-action=\"knowledgeRefresh\"]')", route);
  const baseline = profile.indexOf("waitForStudioOperationResult(frameHost, initialBefore, 'knowledge', 'browse'", refresh);
  assert.ok(route >= 0 && refresh > route && baseline > refresh);
  assert.match(profile, /knowledge-route-unavailable/);
  assert.match(profile, /data-action="toggleAdvanced"/);
  assert.match(source, /knowledge_actions/);
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
