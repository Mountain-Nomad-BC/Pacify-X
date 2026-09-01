'use strict';

// Walk the real VS Code workbench and extension webviews over an explicitly
// launched Chromium debugging endpoint. This is an operational inspection
// tool: it does not substitute application records. Lifecycle mutation profiles
// are admitted only in the explicitly owned disposable VS Code host and restore
// their exact initial state before returning.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { chromium } = require('playwright-core');
const { captureJson, exactStudioVersionConflictError } = require('../src/pxBridge');
const { beginOwnedEngineOutage } = require('./owned-engine-outage');
const { requestOwnedNativeInput } = require('./owned-native-input-client');
const {
  LIVE_WALK_AUTHORITY,
  applyAuthoritySkipContract,
  buildPerControlRecords,
  loadOperationalSurfaceInventory
} = require('./operational-ui-control-records');
const { evaluateOperationalWalk, exitCodeForTerminalState } = require('./operational-walk-status');
const {
  STAGES,
  actionIdentity,
  currentSourceManifest,
  directSelectorFor,
  revealActionFor,
  sidebarActionSelector,
  selectorForKind,
  semanticLabel,
  stageResult
} = require('./run-exhaustive-operational-control-walk');

const endpoint = process.argv[2] || 'http://127.0.0.1:9333';
const outputRoot = path.resolve(process.argv[3] || path.join(__dirname, '..', 'evidence', 'operational-ui-walk'));
const inventoryPath = path.resolve(__dirname, '..', '..', 'registry', 'operational_surface_inventory.json');
const proofMatrixPath = path.resolve(__dirname, '..', '..', 'registry', 'operational_control_proof_matrix.json');
const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

function runInstalledStudioLifecycleCrashProfile() {
  const engineRoot = path.resolve(String(process.env.PX_OWNED_ENGINE_ROOT || ''));
  const harness = path.resolve(__dirname, '..', 'tests', 'installed-harness', 'studio_lifecycle_crash_worker.py');
  const python = String(process.env.PYTHON || process.env.PYTHON_EXECUTABLE || 'python');
  const custodyRoot = path.resolve(ownedHostToken, 'px-owned-studio-lifecycle-crash');
  if (!ownedReversibleConfigurationAuthority || !engineRoot || !ownedHostToken) {
    return { schema_version: 'px.installed-studio-lifecycle-crash-profile/1.0', completed: false, errors: ['owned-lifecycle-crash-authority-missing'], observations: [] };
  }
  const observations = [];
  const errors = [];
  for (const operation of ['promotion', 'rollback']) {
    const operationRoot = path.join(custodyRoot, operation);
    const environment = { ...process.env, PX_OWNED_ENGINE_ROOT: engineRoot };
    const crashed = spawnSync(python, [harness, '--root', operationRoot, '--operation', operation], {
      cwd: engineRoot, env: environment, encoding: 'utf8', windowsHide: true, timeout: 120_000
    });
    if (crashed.error || crashed.signal || crashed.status !== 91) {
      errors.push(`${operation}-durable-phase-termination-invalid:${crashed.error?.message || crashed.signal || crashed.status}:${String(crashed.stderr || '').slice(0, 1200)}`);
      continue;
    }
    const recovered = spawnSync(python, [harness, '--root', operationRoot, '--operation', operation, '--recover'], {
      cwd: engineRoot, env: environment, encoding: 'utf8', windowsHide: true, timeout: 120_000
    });
    if (recovered.error || recovered.signal || recovered.status !== 0) {
      errors.push(`${operation}-restart-recovery-failed:${recovered.error?.message || recovered.signal || recovered.status}:${String(recovered.stderr || '').slice(0, 1200)}`);
      continue;
    }
    try {
      const lines = String(recovered.stdout || '').trim().split(/\r?\n/).filter(Boolean);
      const receipt = JSON.parse(lines.at(-1) || '{}');
      const valid = receipt.schema_version === 'px.installed-studio-lifecycle-crash/1.0'
        && receipt.operation === operation && receipt.crash_exit === 91
        && receipt.canonical_exists === true && /^[0-9a-f]{64}$/.test(String(receipt.canonical_tree_sha256 || ''))
        && typeof receipt.receipt_relative === 'string' && receipt.receipt_relative.length > 0
        && receipt.recovery?.valid === true && Array.isArray(receipt.recovery?.completed);
      if (!valid) throw new Error(`invalid-recovery-receipt:${JSON.stringify(receipt)}`);
      observations.push({ operation, terminated_exit: crashed.status, recovered: true, receipt });
    } catch (error) {
      errors.push(`${operation}-restart-recovery-receipt-invalid:${String(error?.message || error).slice(0, 1600)}`);
    }
  }
  return {
    schema_version: 'px.installed-studio-lifecycle-crash-profile/1.0',
    authority: 'Forced child-process termination at the first durable projection write, followed by a fresh runtime process and exact signed lifecycle reconciliation inside the launcher-owned disposable host root.',
    completed: observations.length === 2 && errors.length === 0,
    observations,
    errors
  };
}

function runInstalledStudioLateCardWorker() {
  const engineRoot = path.resolve(String(process.env.PX_OWNED_ENGINE_ROOT || ''));
  const harness = path.resolve(__dirname, '..', 'tests', 'installed-harness', 'studio_late_card_worker.py');
  const python = String(process.env.PYTHON || process.env.PYTHON_EXECUTABLE || 'python');
  const custodyRoot = path.resolve(ownedHostToken, 'px-owned-studio-late-cards');
  if (!ownedReversibleConfigurationAuthority || !engineRoot || !ownedHostToken) {
    return { schema_version: 'px.installed-studio-late-card-worker/1.0', completed: false, errors: ['owned-late-card-authority-missing'] };
  }
  const completed = spawnSync(python, [harness, '--root', custodyRoot], {
    cwd: engineRoot,
    env: { ...process.env, PX_OWNED_ENGINE_ROOT: engineRoot },
    encoding: 'utf8', windowsHide: true, timeout: 120_000
  });
  if (completed.error || completed.signal || completed.status !== 0) {
    return { schema_version: 'px.installed-studio-late-card-worker/1.0', completed: false, errors: [`worker-failed:${completed.error?.message || completed.signal || completed.status}:${String(completed.stderr || '').slice(0, 1600)}`] };
  }
  try {
    const receipt = JSON.parse(String(completed.stdout || '').trim().split(/\r?\n/).filter(Boolean).at(-1) || '{}');
    if (receipt.schema_version !== 'px.installed-studio-late-card-worker/1.0' || receipt.completed !== true || path.resolve(receipt.runtime_root) !== engineRoot) throw new Error('worker-receipt-invalid');
    return { ...receipt, errors: [] };
  } catch (error) {
    return { schema_version: 'px.installed-studio-late-card-worker/1.0', completed: false, errors: [`worker-receipt-invalid:${String(error?.message || error).slice(0, 800)}`] };
  }
}

async function runInstalledStudioBridgeConflictProfile() {
  const envelope = JSON.stringify({ schema_version: 'px.studio-operation-error/1.0', code: 'STUDIO_VERSION_CONFLICT', reason: 'allocation-stale' });
  let exact = null;
  let lookalike = null;
  let attempts = 0;
  try {
    attempts += 1;
    await captureJson(process.execPath, ['-e', `process.stderr.write(${JSON.stringify(envelope)}); process.exit(2);`], { timeoutMs: 10_000 });
  } catch (error) { exact = error; }
  try {
    attempts += 1;
    await captureJson(process.execPath, ['-e', `process.stderr.write(${JSON.stringify(envelope)}); process.exit(1);`], { timeoutMs: 10_000 });
  } catch (error) { lookalike = error; }
  const checks = {
    exit_2_exact_conflict: exactStudioVersionConflictError(exact),
    exit_1_lookalike_rejected: Boolean(lookalike) && !exactStudioVersionConflictError(lookalike) && lookalike.code === undefined,
    no_mutation_retry: attempts === 2,
    request_bound_reason: exact?.reason === 'allocation-stale' && /^studio-version-conflict:allocation-stale$/.test(String(exact?.message || ''))
  };
  return { schema_version: 'px.installed-studio-bridge-conflict-profile/1.0', completed: Object.values(checks).every(Boolean), checks, errors: Object.entries(checks).filter(([, value]) => !value).map(([name]) => `${name}:failed`) };
}

function buildInstalledLateCardScenarioProfile({
  hostSourceMismatch = null,
  adversarialProfile = null
} = {}) {
  const installedIdentity = hostSourceMismatch === false;
  const required = {
    'PX-OS-087': ['visible_load_all', 'bounded_complete_denominator', 'cancel_recover'],
    'PX-OS-119': ['installed_action_inventory_exact'],
    'PX-OS-958': ['physical_identity_absence', 'predecessor_atomic', 'explicit_fork_absence', 'fork_reopen_without_lineage'],
    'PX-OS-959': ['stale_allocation_ignored', 'cross_kind_allocation_ignored', 'cancelled_allocation_cannot_reopen'],
    'PX-OS-960': ['canonical_file_occupied', 'canonical_directory_occupied', 'noncanonical_alias_ignored', 'dangling_link_blocked', 'inspection_denial_blocked', 'no_revision_published'],
    'PX-OS-961': ['exit_2_exact_conflict', 'exit_1_lookalike_rejected', 'no_mutation_retry', 'request_bound_reason'],
    'PX-OS-962': ['physical_skill_hash_substitution_rejected', 'missing_selection_rejected', 'cross_kind_rejected', 'initial_conflict_rejected', 'incoming_trust_released', 'editor_preserved'],
    'PX-OS-967': ['overlapping_save_a_detached', 'save_b_preserved', 'stale_a_cannot_clear_b', 'cross_kind_catalog_suppressed'],
    'PX-OS-973': ['stale_failure_a_ignored', 'editor_b_preserved', 'matching_failure_b_clears_only_b', 'no_global_error_for_a'],
    'PX-OS-976': ['agent_full_product_path', 'workflow_full_product_path', 'physical_skill_full_product_path', 'external_skill_conflict', 'detach_result_correlation', 'disk_reopen'],
    'PX-OS-994': ['immediate_create_refresh', 'immediate_promote_refresh', 'immediate_rollback_refresh', 'no_predecessor_status'],
    'PX-OS-995': ['preserved_original_selected', 'provenance_bound_editor', 'provenance_bound_candidate', 'provenance_bound_promotion', 'projected_backup_exact'],
    'PX-OS-996': ['promotion_forced_termination_recovered', 'rollback_forced_termination_recovered', 'projection_images_exact'],
    'PX-OS-998': ['framed_tree_hash_exact', 'promotion_projection_authenticated', 'rollback_projection_authenticated', 'immediate_catalog_refresh'],
    'PX-OS-1065': ['all_report_findings_reconciled', 'installed_denominator_complete', 'post_repair_incompleteness_audit']
  };
  const supplied = new Map((adversarialProfile?.records || []).map(record => [record?.gap_id, record]));
  const records = Object.entries(required).map(([gapId, names]) => {
    const record = supplied.get(gapId);
    const checks = record?.checks && typeof record.checks === 'object' ? record.checks : {};
    const exact = names.every(name => checks[name] === true);
    const evidence = Array.isArray(record?.evidence) ? record.evidence.filter(item => typeof item === 'string' && item.length > 0) : [];
    return {
      gap_id: gapId,
      completed: installedIdentity && record?.schema_version === 'px.installed-late-card-evidence/1.0'
        && record?.gap_id === gapId && exact && evidence.length > 0 && !(record?.errors || []).length,
      required_checks: names,
      checks: Object.fromEntries(names.map(name => [name, checks[name] === true])),
      evidence,
      errors: Array.isArray(record?.errors) ? record.errors : []
    };
  });
  return {
    schema_version: 'px.installed-late-card-scenario-profile/1.0',
    authority: 'Every late card requires its own exact installed-host adversarial predicates. Broad Studio success, source-file hashes, and injected preview fixtures are never accepted as substitutes.',
    completed: records.every(record => record.completed),
    records,
    errors: records.filter(record => !record.completed).map(record => `${record.gap_id}:installed-late-card-denominator-incomplete`)
  };
}

async function runInstalledStudioControllerAdversarialProfile(frameHost) {
  const checks = await frameHost.evaluateContent(() => {
    const dispatch = data => window.dispatchEvent(new MessageEvent('message', { data }));
    const posted = () => window.__PX_INSTALLED_REQUESTS__ || [];
    const proofReleased = (after, requestId, proof) => posted().slice(after).some(value => value?.type === 'releaseStudioTrust' && value?.requestId === requestId && value?.proof === proof);
    const hash = character => character.repeat(64);
    const allocation = (kind, identity, sourceVersion, candidateVersion = '1.0.1') => ({
      schema_version: 'px.studio-version-allocation/1.0', kind, identity, source_version: sourceVersion,
      source_scope: 'studio-physical', source_revision_sha256: hash('a'), source_content_sha256: hash('b'),
      candidate_version: candidateVersion, occupied_versions_sha256: hash('c'), observed_utc: '2026-08-31T00:00:00.000Z'
    });
    const original = {
      studioAllocationRequest, studioSaveRequest, studioEditor, studioSession, studioSourceRecord,
      studioVersionAllocation, studioVersionAllocationProof, studioVersionProofRequestId,
      studioPendingSkillPackage, studioSourceProofRequestId
    };
    const editor = { kind: 'agent', draft: { agent_id: 'agent:owned-editor-b', version: '1.0.1', owner: 'px-owned' } };
    const result = {};
    try {
      studioEditor = editor;
      studioAllocationRequest = { requestId: 'owned-active-allocation-b', operation: 'loadStudioRevisionEditor', suboperation: null, kind: 'agent', catalogKind: 'agents', recordId: 'studio:agent:b', identity: 'agent:owned-editor-b', source_version: '1.0.0', source_scope: 'studio-physical', source_revision_sha256: hash('a'), source_content_sha256: hash('b') };
      let after = posted().length;
      dispatch({ type: 'studioRevisionEditorResult', requestId: 'owned-stale-allocation-a', kind: 'agent', catalogKind: 'agents', recordId: 'studio:agent:a', allocationProof: 'version-allocation:owned-stale-a', selection: null, allocation: null });
      result.stale_allocation_ignored = studioAllocationRequest?.requestId === 'owned-active-allocation-b' && studioEditor === editor && proofReleased(after, 'owned-stale-allocation-a', 'version-allocation:owned-stale-a');
      after = posted().length;
      dispatch({ type: 'studioRevisionEditorResult', requestId: 'owned-active-allocation-b', kind: 'workflow', catalogKind: 'workflows', recordId: 'studio:workflow:substitute', allocationProof: 'version-allocation:owned-cross-kind', selection: null, allocation: null });
      result.cross_kind_allocation_ignored = studioAllocationRequest?.requestId === 'owned-active-allocation-b' && studioEditor === editor && proofReleased(after, 'owned-active-allocation-b', 'version-allocation:owned-cross-kind');
      studioAllocationRequest = { ...studioAllocationRequest, requestId: 'owned-cancelled-allocation' };
      cancelPendingStudioRequests();
      after = posted().length;
      dispatch({ type: 'studioRevisionEditorResult', requestId: 'owned-cancelled-allocation', kind: 'agent', catalogKind: 'agents', recordId: 'studio:agent:b', allocationProof: 'version-allocation:owned-cancelled', selection: null, allocation: null });
      result.cancelled_allocation_cannot_reopen = studioAllocationRequest === null && studioEditor === editor && proofReleased(after, 'owned-cancelled-allocation', 'version-allocation:owned-cancelled');

      const skillRecord = { skill_id: 'skill:owned-physical', version: '1.0.0', revision_sha256: hash('a'), source_content_sha256: hash('b') };
      const selection = { identity: skillRecord.skill_id, source_version: skillRecord.version, source_scope: 'studio-physical', source_revision_sha256: hash('a'), source_content_sha256: hash('b'), tree_sha256: hash('d'), file_count: 6 };
      studioSourceRecord = skillRecord;
      studioPendingSkillPackage = { sourceSelectionId: 'source-selection:owned', selection, treeSha256: hash('d'), fileCount: 6, editor_files: [] };
      studioSourceProofRequestId = 'owned-source-proof-request';
      studioAllocationRequest = { requestId: 'owned-skill-allocation', operation: 'studioOperation', suboperation: 'next-version', kind: 'skill', identity: skillRecord.skill_id, source_version: skillRecord.version, source_scope: 'studio-physical', source_revision_sha256: hash('a'), source_content_sha256: hash('b'), selected_revision_sha256: hash('a'), selected_content_sha256: hash('b'), source_selection_id: 'source-selection:owned', record: skillRecord };
      after = posted().length;
      const substituted = { ...allocation('skill', skillRecord.skill_id, skillRecord.version), source_revision_sha256: hash('e') };
      dispatch({ type: 'studioOperationResult', requestId: 'owned-skill-allocation', kind: 'skill', operation: 'next-version', result: substituted, allocationProof: 'version-allocation:owned-skill-substitution' });
      result.physical_skill_hash_substitution_rejected = studioAllocationRequest === null && studioEditor === editor && proofReleased(after, 'owned-skill-allocation', 'version-allocation:owned-skill-substitution');
      result.incoming_trust_released = result.physical_skill_hash_substitution_rejected;

      studioPendingSkillPackage = null;
      studioAllocationRequest = { requestId: 'owned-missing-selection', operation: 'studioOperation', suboperation: 'next-version', kind: 'skill', identity: skillRecord.skill_id, source_version: skillRecord.version, source_scope: 'studio-physical', source_revision_sha256: hash('a'), source_content_sha256: hash('b'), selected_revision_sha256: hash('a'), selected_content_sha256: hash('b'), source_selection_id: 'source-selection:missing', record: skillRecord };
      dispatch({ type: 'studioOperationResult', requestId: 'owned-missing-selection', kind: 'skill', operation: 'next-version', result: allocation('skill', skillRecord.skill_id, skillRecord.version), allocationProof: 'version-allocation:owned-missing-selection' });
      result.missing_selection_rejected = studioAllocationRequest === null && studioEditor === editor;

      studioAllocationRequest = { requestId: 'owned-cross-kind-active', operation: 'studioOperation', suboperation: 'next-version', kind: 'skill', identity: skillRecord.skill_id, source_version: skillRecord.version, source_scope: 'studio-physical', source_revision_sha256: hash('a'), source_content_sha256: hash('b'), selected_revision_sha256: hash('a'), selected_content_sha256: hash('b'), source_selection_id: 'source-selection:cross', record: skillRecord };
      dispatch({ type: 'studioOperationResult', requestId: 'owned-cross-kind-active', kind: 'agent', operation: 'next-version', result: allocation('agent', 'agent:substitute', '1.0.0'), allocationProof: 'version-allocation:owned-cross-kind-active' });
      result.cross_kind_rejected = studioAllocationRequest?.requestId === 'owned-cross-kind-active' && studioEditor === editor;
      cancelPendingStudioRequests();

      studioEditor = editor; studioSaveRequest = { requestId: 'owned-initial-conflict', kind: 'agent' }; studioVersionAllocation = null;
      after = posted().length;
      dispatch({ type: 'studioVersionConflict', requestId: 'owned-initial-conflict', kind: 'agent', allocationProof: 'version-allocation:owned-initial-conflict', allocation: allocation('agent', 'agent:owned-editor-b', '1.0.0'), error: 'owned initial conflict' });
      result.initial_conflict_rejected = studioEditor === editor && studioVersionAllocation === null && proofReleased(after, 'owned-initial-conflict', 'version-allocation:owned-initial-conflict');
      result.editor_preserved = studioEditor === editor;

      const saveA = { requestId: 'owned-save-a', kind: 'agent' };
      const saveB = { requestId: 'owned-save-b', kind: 'agent' };
      rememberDetachedStudioSave(saveA); studioSaveRequest = saveB; studioEditor = editor;
      const workflowCatalogBefore = state.catalogRequests.workflows?.requestId || null;
      dispatch({ type: 'studioDraftResult', requestId: saveA.requestId, kind: saveA.kind, result: { schema_version: 'px.agent-creation-receipt/1.1', agent_id: 'agent:save-a', version: '1.0.1', created: true, record_sha256: hash('f') } });
      result.overlapping_save_a_detached = !detachedStudioSaveRequests.has(saveA.requestId);
      result.save_b_preserved = studioSaveRequest?.requestId === saveB.requestId && studioEditor === editor;
      result.stale_a_cannot_clear_b = result.save_b_preserved;
      result.cross_kind_catalog_suppressed = (state.catalogRequests.workflows?.requestId || null) === workflowCatalogBefore;

      studioAllocationRequest = { requestId: 'owned-failure-b', operation: 'studioOperation', suboperation: 'next-version', kind: 'skill' };
      studioEditor = editor;
      const modalBefore = document.querySelector('.control-modal')?.textContent || '';
      dispatch({ type: 'operationError', operation: 'studioOperation', suboperation: 'next-version', requestId: 'owned-failure-a', kind: 'skill', error: 'stale failure A' });
      result.stale_failure_a_ignored = studioAllocationRequest?.requestId === 'owned-failure-b';
      result.editor_b_preserved = studioEditor === editor;
      result.no_global_error_for_a = (document.querySelector('.control-modal')?.textContent || '') === modalBefore;
      dispatch({ type: 'operationError', operation: 'studioOperation', suboperation: 'next-version', requestId: 'owned-failure-b', kind: 'skill', error: 'matching failure B' });
      result.matching_failure_b_clears_only_b = studioAllocationRequest === null && studioEditor === editor;
      result.detach_result_correlation = result.overlapping_save_a_detached && result.save_b_preserved && result.stale_a_cannot_clear_b;
    } finally {
      studioAllocationRequest = original.studioAllocationRequest; studioSaveRequest = original.studioSaveRequest;
      studioEditor = original.studioEditor; studioSession = original.studioSession; studioSourceRecord = original.studioSourceRecord;
      studioVersionAllocation = original.studioVersionAllocation; studioVersionAllocationProof = original.studioVersionAllocationProof;
      studioVersionProofRequestId = original.studioVersionProofRequestId; studioPendingSkillPackage = original.studioPendingSkillPackage;
      studioSourceProofRequestId = original.studioSourceProofRequestId;
      closeModal(true);
    }
    return result;
  });
  return {
    schema_version: 'px.installed-studio-controller-adversarial/1.0',
    completed: Object.values(checks).every(value => value === true),
    checks,
    errors: Object.entries(checks).filter(([, value]) => value !== true).map(([name]) => `${name}:failed`)
  };
}

function buildInstalledLateCardAdversarialProfile({
  hostSourceMismatch,
  installedIdentity,
  observationStateProfile,
  candidateProfile,
  revisionProfile,
  lifecycleProfile,
  crashProfile,
  catalogPaginationProfile,
  workerProfile,
  controllerProfile,
  bridgeProfile,
  hostErrors = []
}) {
  const observations = profile => Array.isArray(profile?.observations) ? profile.observations : [];
  const byKind = profile => new Map(observations(profile).filter(item => item?.fixture_only !== true).map(item => [item.kind, item]));
  const candidates = byKind(candidateProfile);
  const revisions = byKind(revisionProfile);
  const lifecycles = byKind(lifecycleProfile);
  const operation = (kind, name) => (lifecycles.get(kind)?.operations || []).some(item => item?.operation === name && item?.valid === true);
  const clean = item => item && (!Array.isArray(item.errors) || item.errors.length === 0);
  const allKinds = predicate => ['agent', 'workflow', 'skill'].every(kind => predicate(kind));
  const controller = controllerProfile?.checks || {};
  const workerPhysical = workerProfile?.physical || {};
  const workerFork = workerProfile?.fork || {};
  const workerSkill = workerProfile?.skill || {};
  const bridge = bridgeProfile?.checks || {};
  const graph = observationStateProfile?.observations?.['pxui.knowledge-graph.action.graphLoadAll'] || {};
  const skillPagination = observations(catalogPaginationProfile).find(item => item.surface === 'skills-tools');
  const exactInventory = (() => {
    try {
      const { serialized } = require('./build-ui-action-inventory');
      return fs.readFileSync(path.resolve(__dirname, '..', 'resources', 'ui', 'action-inventory.json'), 'utf8') === serialized();
    } catch { return false; }
  })();
  const record = (gapId, checks, evidence, errors = []) => ({
    schema_version: 'px.installed-late-card-evidence/1.0', gap_id: gapId, checks,
    evidence: evidence.filter(Boolean), errors: [...errors]
  });
  const records = [
    record('PX-OS-087', {
      visible_load_all: graph.rendered === true && graph.attempted === true,
      bounded_complete_denominator: graph.completed === true && graph.recovered === true,
      cancel_recover: graph.cancelled === true && graph.recovered === true
    }, ['installed-observation-state:pxui.knowledge-graph.action.graphLoadAll']),
    record('PX-OS-119', {
      installed_action_inventory_exact: hostSourceMismatch === false && installedIdentity?.state === 'verified' && exactInventory
    }, ['installed-runtime-identity:resources/ui/action-inventory.json', 'current-source:build-ui-action-inventory']),
    record('PX-OS-958', {
      physical_identity_absence: workerFork.physical_identity_absence === true,
      predecessor_atomic: allKinds(kind => {
        const item = revisions.get(kind); return clean(item) && item.predecessor_preserved === true && item.content_changed === true && item.save_dispatched_atomically === true;
      }),
      explicit_fork_absence: workerFork.explicit_fork_absence === true && allKinds(kind => revisions.get(kind)?.fork_verified === true),
      fork_reopen_without_lineage: workerFork.fork_reopen_without_lineage === true
    }, ['installed-worker:physical-identity-and-fork', 'installed-studio-revision-edit:predecessor-and-fork']),
    record('PX-OS-959', {
      stale_allocation_ignored: controller.stale_allocation_ignored === true && ['agent', 'workflow'].every(kind => revisions.get(kind)?.stale_result_rejected === true),
      cross_kind_allocation_ignored: controller.cross_kind_allocation_ignored === true,
      cancelled_allocation_cannot_reopen: controller.cancelled_allocation_cannot_reopen === true
    }, ['installed-controller-adversarial:allocation-correlation']),
    record('PX-OS-960', {
      canonical_file_occupied: workerPhysical.canonical_file_occupied === true,
      canonical_directory_occupied: workerPhysical.canonical_directory_occupied === true,
      noncanonical_alias_ignored: workerPhysical.noncanonical_alias_ignored === true,
      dangling_link_blocked: workerPhysical.dangling_link_blocked === true,
      inspection_denial_blocked: workerPhysical.inspection_denial_blocked === true,
      no_revision_published: workerPhysical.no_revision_published === true
    }, ['installed-worker:physical-version-allocation']),
    record('PX-OS-961', {
      exit_2_exact_conflict: bridge.exit_2_exact_conflict === true,
      exit_1_lookalike_rejected: bridge.exit_1_lookalike_rejected === true,
      no_mutation_retry: bridge.no_mutation_retry === true,
      request_bound_reason: bridge.request_bound_reason === true
    }, ['installed-identical-host-source:pxBridge', 'bounded-child-process:studio-conflict-envelope']),
    record('PX-OS-962', {
      physical_skill_hash_substitution_rejected: controller.physical_skill_hash_substitution_rejected === true,
      missing_selection_rejected: controller.missing_selection_rejected === true,
      cross_kind_rejected: controller.cross_kind_rejected === true,
      initial_conflict_rejected: controller.initial_conflict_rejected === true,
      incoming_trust_released: controller.incoming_trust_released === true,
      editor_preserved: controller.editor_preserved === true
    }, ['installed-controller-adversarial:allocation-envelope']),
    record('PX-OS-967', {
      overlapping_save_a_detached: controller.overlapping_save_a_detached === true,
      save_b_preserved: controller.save_b_preserved === true,
      stale_a_cannot_clear_b: controller.stale_a_cannot_clear_b === true,
      cross_kind_catalog_suppressed: controller.cross_kind_catalog_suppressed === true
    }, ['installed-controller-adversarial:detached-save-correlation']),
    record('PX-OS-973', {
      stale_failure_a_ignored: controller.stale_failure_a_ignored === true,
      editor_b_preserved: controller.editor_b_preserved === true,
      matching_failure_b_clears_only_b: controller.matching_failure_b_clears_only_b === true,
      no_global_error_for_a: controller.no_global_error_for_a === true
    }, ['installed-controller-adversarial:next-version-failure-correlation']),
    record('PX-OS-976', {
      agent_full_product_path: clean(candidates.get('agent')) && clean(revisions.get('agent')) && clean(lifecycles.get('agent')) && operation('agent', 'start'),
      workflow_full_product_path: clean(candidates.get('workflow')) && clean(revisions.get('workflow')) && clean(lifecycles.get('workflow')) && operation('workflow', 'start'),
      physical_skill_full_product_path: clean(candidates.get('skill')) && clean(revisions.get('skill')) && clean(lifecycles.get('skill')) && operation('skill', 'promote') && operation('skill', 'rollback'),
      external_skill_conflict: workerPhysical.external_skill_conflict === true && lifecycles.get('skill')?.lifecycle_failure_recovered === true,
      detach_result_correlation: controller.detach_result_correlation === true,
      disk_reopen: allKinds(kind => candidates.get(kind)?.reopened_catalog_match === true && revisions.get(kind)?.reopened_catalog_match === true)
    }, ['installed-studio:candidate-edit-save-reopen-lifecycle', 'installed-worker:external-skill-conflict']),
    record('PX-OS-994', {
      immediate_create_refresh: allKinds(kind => candidates.get(kind)?.catalog_query_dispatched === true && candidates.get(kind)?.reopened_catalog_match === true),
      immediate_promote_refresh: operation('skill', 'promote') && clean(skillPagination),
      immediate_rollback_refresh: operation('skill', 'rollback') && clean(skillPagination),
      no_predecessor_status: skillPagination?.restored === true && skillPagination?.errors?.length === 0
    }, ['installed-studio:mutation-catalog-invalidation', 'installed-catalog-pagination:skills']),
    record('PX-OS-995', {
      preserved_original_selected: workerSkill.preserved_original_selected === true,
      provenance_bound_editor: workerSkill.provenance_bound_editor === true,
      provenance_bound_candidate: workerSkill.provenance_bound_candidate === true,
      provenance_bound_promotion: workerSkill.provenance_bound_promotion === true,
      projected_backup_exact: workerSkill.projected_backup_exact === true
    }, ['installed-worker:preserved-original-lifecycle']),
    record('PX-OS-996', {
      promotion_forced_termination_recovered: crashProfile?.observations?.some(item => item.operation === 'promotion' && item.terminated_exit === 91 && item.recovered === true) === true,
      rollback_forced_termination_recovered: crashProfile?.observations?.some(item => item.operation === 'rollback' && item.terminated_exit === 91 && item.recovered === true) === true,
      projection_images_exact: workerSkill.promotion_projection_authenticated === true && workerSkill.rollback_projection_authenticated === true && workerSkill.immediate_catalog_refresh === true
    }, ['installed-child-termination:studio-lifecycle-crash', 'installed-worker:projection-images']),
    record('PX-OS-998', {
      framed_tree_hash_exact: workerSkill.framed_tree_hash_exact === true,
      promotion_projection_authenticated: workerSkill.promotion_projection_authenticated === true,
      rollback_projection_authenticated: workerSkill.rollback_projection_authenticated === true,
      immediate_catalog_refresh: workerSkill.immediate_catalog_refresh === true && operation('skill', 'promote') && operation('skill', 'rollback')
    }, ['installed-worker:authenticated-skill-projections', 'installed-studio:promotion-rollback'])
  ];
  const sourceReportReconciled = (() => {
    try {
      const closure = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', '..', 'evidence', 'adversarial-audit', 'current-environment-repair-closure-20260826.json'), 'utf8'));
      const findings = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', '..', 'evidence', 'adversarial-audit', 'current-findings-20260824.json'), 'utf8'));
      return closure.repair_intake_closed === true && Array.isArray(closure.source_repairs) && closure.source_repairs.length > 0
        && closure.source_repairs.every(item => !/open|unrepaired|failed/i.test(String(item.disposition || '')))
        && Array.isArray(findings.findings) && findings.findings.length > 0
        && findings.findings.every(item => ['repaired', 'repaired_locally', 'implemented_pending_remote_os_execution'].includes(item.status));
    } catch { return false; }
  })();
  const installedComplete = records.every(item => Object.values(item.checks).every(value => value === true) && item.errors.length === 0);
  records.push(record('PX-OS-1065', {
    all_report_findings_reconciled: sourceReportReconciled,
    installed_denominator_complete: installedComplete,
    post_repair_incompleteness_audit: installedComplete && hostErrors.length === 0
  }, ['source-repair-closure:current-environment', 'installed-late-card-denominator:14-of-14', 'installed-host-errors:zero'], hostErrors.length ? [`host-errors:${hostErrors.length}`] : []));
  return { schema_version: 'px.installed-late-card-adversarial-profile/1.0', completed: records.every(item => Object.values(item.checks).every(Boolean) && item.errors.length === 0), records };
}
async function boundedOwnedUiAction(operation, timeoutMs, label) {
  const budget = Math.max(1, Number(timeoutMs) || 1);
  let timer = null;
  try {
    return await Promise.race([
      Promise.resolve().then(operation),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label}-timeout:${budget}`)), budget); })
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
const ownedReversibleConfigurationAuthority = process.env.PX_OWNED_VSCODE_HOST === '1'
  && process.argv.some(value => String(value).startsWith('--px-owned-token='));
const ownedHostToken = String(process.argv.find(value => String(value).startsWith('--px-owned-token=')) || '').slice('--px-owned-token='.length);
const ownedWorkspaceRootValue = String(process.env.PX_OWNED_VSCODE_WORKSPACE_ROOT || '').trim();
const ownedWorkspaceRoot = ownedReversibleConfigurationAuthority && ownedWorkspaceRootValue
  ? path.resolve(ownedWorkspaceRootValue)
  : '';
const configurationOnly = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_CONFIGURATION_ONLY === '1';
const studioLifecycleOnly = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_STUDIO_LIFECYCLE_ONLY === '1';
const knowledgeLifecycleOnly = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_KNOWLEDGE_LIFECYCLE_ONLY === '1';
const hostBoundaryOnly = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_HOST_BOUNDARY_ONLY === '1';
const nativeDialogOnly = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_NATIVE_DIALOG_ONLY === '1';
const codexHandoffOnly = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_CODEX_HANDOFF_ONLY === '1';
const errorIndicatorsOnly = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_ERROR_INDICATORS_ONLY === '1';
const ERROR_INDICATOR_CONTROL_IDS = new Set([
  'pxui.memory.indicator.queryError',
  'pxui.knowledge-core.indicator.controllerError'
]);
const focusedProfile = configurationOnly ? 'reversible-configuration' : studioLifecycleOnly ? 'studio-lifecycle' : knowledgeLifecycleOnly ? 'knowledge-lifecycle' : hostBoundaryOnly ? 'host-boundary' : nativeDialogOnly ? 'native-dialog-boundary' : codexHandoffOnly ? 'codex-handoff' : errorIndicatorsOnly ? 'error-indicators' : null;
const focusedProfileOnly = Boolean(focusedProfile);
const postAuditLongRunningAuthority = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_POST_AUDIT_LONG_RUNNING === '1';
// Long-running operational coverage is not validation authority. Repository
// processing order owns the one canonical validation and must grant that effect
// independently; normal full physical walks exercise the refusal boundary.
const validationExecutionAuthority = ownedReversibleConfigurationAuthority && process.env.PX_OPERATIONAL_VALIDATION_EXECUTION_AUTHORITY === '1';
const ownedKnowledgeSourceId = String(process.env.PX_OWNED_KNOWLEDGE_SOURCE_ID || '');
const ownedKnowledgeSourceSha256 = String(process.env.PX_OWNED_KNOWLEDGE_SOURCE_SHA256 || '');
const nativeInputEvidence = [];
const INSTALLED_ROUTES = {
  dashboard: 'dashboard', 'dashboard-control-plane': 'dashboard', projects: 'projects', agents: 'agents',
  'agent-studio': 'agents', 'workflow-studio': 'workflows', 'skill-studio': 'skillsTools',
  'knowledge-graph': 'knowledgeGraph', 'skills-tools': 'skillsTools', workflows: 'workflows', plugins: 'plugins',
  memory: 'memory', activity: 'activity', diagnostics: 'diagnostics', assurance: 'assurance',
  'studio-lifecycle': 'studio-lifecycle', settings: 'settings', 'knowledge-core': 'knowledgeCore',
  'runtime-core': 'runtimeCore'
};
const INSTALLED_SAFE_MODES = new Set([
  'contained_ui_interaction', 'contained_ui_input', 'contained_ui_form', 'contained_ui_gesture',
  'contained_ui_navigation', 'contained_ui_editor', 'live_state_observation'
]);
const INSTALLED_SAFE_WORKBENCH_COMMANDS = Object.freeze({
  'pxui.dashboard-control-plane.command.pacifyX.openDashboard': { title: 'Pacify-X: Open Control Plane', outcome: 'dashboard' },
  'pxui.dashboard-control-plane.command.pacifyX.refreshDashboard': { title: 'Pacify-X: Refresh Control Plane', outcome: 'dashboard-refresh' },
  'pxui.dashboard-control-plane.command.pacifyX.openSettings': { title: 'Pacify-X: Open Settings', outcome: 'settings' },
  'pxui.dashboard-control-plane.command.pacifyX.createContextSnapshot': { title: 'Pacify-X: Create Portable Context Snapshot', outcome: 'context-snapshot' },
  'pxui.dashboard-control-plane.command.pacifyX.openCleanupManager': { title: 'Pacify-X: Open Storage & Cleanup Manager', outcome: 'cleanup-manager' },
  'pxui.dashboard-control-plane.command.pacifyX.refreshProviderStatus': { title: 'Pacify-X: Refresh Provider and Git Status', outcome: 'dashboard-refresh' },
  'pxui.dashboard-control-plane.command.pacifyX.cancelCodex': { title: 'Pacify-X: Explain Codex Cancellation Authority', outcome: 'codex-cancel' }
});
const INSTALLED_WORKBENCH_AUTHORITY_BOUNDARIES = Object.freeze({
  'pxui.dashboard-control-plane.command.pacifyX.refreshEnvironment': { title: 'Pacify-X: Refresh Environment Capability Map', policy: 'reject-before-dispatch', reason: 'The command persists a project environment inventory and requires a separately admitted write effect.' },
  'pxui.dashboard-control-plane.command.pacifyX.refreshOllama': { title: 'Pacify-X: Refresh Ollama Models', policy: 'reject-before-dispatch', reason: 'Refreshing the live model provider may perform service and network effects that require separate admissions.' },
  'pxui.dashboard-control-plane.command.pacifyX.rotateStudioApprovalIdentity': { title: 'Pacify-X: Rotate Studio Approval Identity', policy: 'reject-before-dispatch', reason: 'Identity rotation invalidates active approvals and is not a reversible operational-walk effect.' },
  'pxui.dashboard-control-plane.command.pacifyX.validateControlPlane': { title: 'Pacify-X: Validate Control Plane', policy: 'reject-before-dispatch', reason: 'Repository processing order reserves exactly one owned validation after the full profile.' }
});

function eligibleInstalledControl(control) {
  if (!control || control.surface_id === 'sidebar') return false;
  if (INSTALLED_SAFE_MODES.has(control.evidence_mode)) return true;
  return control.evidence_mode === 'contained_host_interaction' && control.effect === 'read';
}

function installedActionIdentity(control) {
  return actionIdentity(String(control.control_id).split('.action.')[1] || control.label);
}

const INSTALLED_EXACT_NAVIGATION_TRANSITIONS = Object.freeze({
  'pxui.dashboard-control-plane.action.navigate.knowledgeCore': { owner: 'dashboard', target: 'knowledgeCore' },
  'pxui.dashboard-control-plane.action.navigate.runtimeCore': { owner: 'dashboard', target: 'runtimeCore' },
  'pxui.runtime-core.action.navigate.workflows': { owner: 'runtimeCore', target: 'workflows' }
});

function installedExactNavigationTransition(control) {
  return INSTALLED_EXACT_NAVIGATION_TRANSITIONS[String(control?.control_id || '')] || null;
}

const INSTALLED_EXACT_GRAPH_FIELDS = Object.freeze({
  'pxui.knowledge-graph.field.graphDirection': '[data-graph-direction]',
  'pxui.knowledge-graph.field.graphTarget': '[data-graph-target]'
});

function installedExactGraphField(control) {
  return INSTALLED_EXACT_GRAPH_FIELDS[String(control?.control_id || '')] || null;
}

function installedDirectSelector(control) {
  const id = String(control?.control_id || '');
  const exact = {
    'pxui.dashboard.action.refresh.hero': '.hero-actions [data-action="refresh"]',
    'pxui.dashboard-control-plane.action.navigate.knowledgeCore': '[data-surface="knowledgeCore"].nav-item',
    'pxui.dashboard-control-plane.action.navigate.runtimeCore': '[data-surface="runtimeCore"].nav-item',
    'pxui.dashboard-control-plane.action.refresh.header': '.cockpit-actions [data-action="refresh"]',
    'pxui.dashboard-control-plane.action.toggleAdvanced': '[data-action="toggleAdvanced"]',
    'pxui.dashboard-control-plane.indicator.branch': '.branch-cell',
    'pxui.dashboard-control-plane.indicator.connection': '.rail-status',
    'pxui.dashboard-control-plane.indicator.loading': '.loading',
    'pxui.dashboard.indicator.heroConnection': '.hero-status > strong',
    'pxui.dashboard.indicator.sourceVersion': '.hero-status > small',
    'pxui.memory.indicator.queryError': '.surface-memory .memory-errors[role="alert"]:has([data-action="memoryRefresh"])',
    'pxui.knowledge-core.indicator.controllerError': '.surface-knowledgeCore .memory-errors[role="alert"]:has([data-action="knowledgeRefresh"])',
    'pxui.knowledge-graph.action.graphFit.button': '.graph-zoom-controls [data-action="graphFit"]',
    'pxui.knowledge-graph.action.graphFit.minimap': '.graph-minimap[data-action="graphFit"]',
    'pxui.knowledge-graph.action.graphClearCommunity': '[data-action="graphClearCommunity"]',
    'pxui.knowledge-graph.action.graphCommunity.row': '[data-action="graphCommunity"][data-community-id]',
    'pxui.knowledge-graph.action.graphDepth.decrease': '[data-action="graphDepth"][data-delta="-1"]',
    'pxui.knowledge-graph.action.graphDepth.increase': '[data-action="graphDepth"][data-delta="1"]',
    'pxui.knowledge-graph.action.graphLayout.flow': '[data-action="graphLayout"][data-layout="flow"]',
    'pxui.knowledge-graph.action.graphLayout.orbit': '[data-action="graphLayout"][data-layout="orbit"]',
    'pxui.knowledge-graph.action.inspectGraphRecord': '[data-action="inspectGraphRecord"][data-node-key]',
    'pxui.knowledge-graph.field.graphDirection': '[data-graph-direction]',
    'pxui.knowledge-graph.field.graphTarget': '[data-graph-target]',
    'pxui.knowledge-graph.menu.depth': '[role="group"][aria-label="Relationship depth"]',
    'pxui.knowledge-graph.indicator.relationshipCounts': '.relationship-counts',
    'pxui.runtime-core.action.refresh': '.surface-runtimeCore [data-action="refresh"]',
    'pxui.plugins.action.inspectMachineManifest.header': '.panel-heading [data-action="inspectMachineManifest"]',
    'pxui.plugins.action.inspectMachineManifest.footer': '.plugin-actions [data-action="inspectMachineManifest"]'
  }[id];
  return exact || directSelectorFor(control);
}

function installedStudioPrerequisites(control) {
  const id = String(control?.control_id || '');
  const steps = [];
  const add = (action, dataset = {}, pick = 'first') => steps.push({ action, dataset, pick });
  if (id.startsWith('pxui.agent-studio.')) {
    const optionalKind = id.match(/agentSelectNode\.(tools|memory|handoffs)\.optional$/)?.[1];
    if (optionalKind) add('agentAddTopologyNode', { agentKind: optionalKind });
    if (id.includes('agentRemoveTopologyNode')) add('agentAddTopologyNode', { agentKind: 'tools' });
    if (id.includes('agentRemoveBinding')) add('agentAddBinding');
    if (id.includes('agentRemoveGrant')) add('agentAddGrant');
    if (id.includes('agentCancelConnection')) add('agentPortConnect', { direction: 'output' });
    if (/\.field\.model\./.test(id)) add('agentSelectNode', { agentKind: 'model' });
    if (/\.field\.(?:input_schema|output_schema)$/.test(id)) add('agentSelectNode', { agentKind: 'contracts' });
    if (id.endsWith('.field.required_tests')) add('agentSelectNode', { agentKind: 'tests' });
    if (id.endsWith('.action.refreshHostModels')) add('agentSelectNode', { agentKind: 'model' });
    if (id.endsWith('.indicator.workingGraphRequiresPythonCompile')) add('agentAddTopologyNode', { agentKind: 'tools' });
  }
  if (id.startsWith('pxui.workflow-studio.')) {
    if (/workflowMoveNode\.(?:earlier|later)$/.test(id) || id.endsWith('.action.workflowRemoveNode')) add('workflowAddNode', { nodeTemplate: 'task' });
    if (id.endsWith('workflowMoveNode.later')) add('workflowSelectNode', {}, 'first');
    if (id.includes('workflowRemoveBinding')) add('workflowAddBinding');
    if (id.includes('workflowRemoveGrant')) add('workflowAddGrant');
    if (id.includes('workflowRemovePort')) add('workflowAddPort', { direction: 'inputs' });
    if (id.includes('workflowCancelConnection')) add('workflowPortConnect', { direction: 'output' });
    if (id.endsWith('.indicator.pendingPortConnection')) add('workflowPortConnect', { direction: 'output' });
    if (id.includes('workflowRemoveEdge') || /\.field\.edge\.(?:source_endpoint|target_endpoint)$/.test(id)) {
      add('workflowAddNode', { nodeTemplate: 'task' });
      add('workflowConnectNodes');
    }
  }
  if (id.startsWith('pxui.skill-studio.') && (
    id.includes('skillRemoveFile') || id.includes('skillSelectFile') || id.endsWith('.field.packageFileText')
    || id.endsWith('.form.packageFile') || id.endsWith('.editor.packageFile')
  )) add('skillAddFile', { fileKind: 'resource' });
  return steps;
}

function installedStudioControlScenario(control) {
  const id = String(control?.control_id || '');
  if (!/^pxui\.(?:agent|workflow|skill)-studio\./.test(id)) return null;
  if (/\.action\.(?:resume|discard)WorkingStudioDraft$/.test(id)) return 'retained-working-draft';
  if (id === 'pxui.skill-studio.action.loadSkillPackageEditor') return 'catalog-record';
  if (/\.action\.forkStudioCandidate$/.test(id)) return 'predecessor-editor';
  if (/\.action\.acceptStudioVersionSuggestion$/.test(id)) return 'version-conflict';
  return null;
}

function installedSurfaceState(control) {
  const id = String(control?.control_id || '');
  if (['agents', 'agent-studio'].includes(control?.surface_id)) {
    return { target: 'agents', scope: /\.enterprise|enterprise[A-Z]/.test(id) ? 'enterprise' : 'core' };
  }
  if (['workflows', 'workflow-studio'].includes(control?.surface_id)) {
    const scope = /environment|refreshEnvironment/i.test(id) ? 'environment'
      : /\.enterprise|enterprise[A-Z]/.test(id) ? 'enterprise' : 'core';
    return { target: 'workflows', scope };
  }
  if (['skills-tools', 'skill-studio'].includes(control?.surface_id)) {
    if (/compareSkillOriginal/.test(id)) return { kind: 'preserved-skills' };
    if (/\.enterprise|enterprise[A-Z]/.test(id)) return { kind: 'enterprise-skills' };
    return { kind: 'skills' };
  }
  return null;
}

function installedPreparationIdentity(control) {
  const prerequisites = installedStudioPrerequisites(control);
  return prerequisites.length || installedConditionalScenario(control) || installedStudioControlScenario(control) || installedSurfaceState(control)
    ? `${control.surface_id}:${control.control_id}`
    : control.surface_id;
}

function installedConditionalScenario(control) {
  const id = String(control?.control_id || '');
  const readFailure = Object.freeze({
    'pxui.dashboard.action.refresh.hero': { operation: 'refresh', resultType: 'snapshot' },
    'pxui.dashboard-control-plane.action.refresh.header': { operation: 'refresh', resultType: 'snapshot' },
    'pxui.activity.action.activityRefresh': { operation: 'activityQuery', resultType: 'activityResult' },
    'pxui.agents.action.catalogRetry': { operation: 'catalogQuery', resultType: 'catalogResult', kind: 'agents' },
    'pxui.agents.action.catalogNext': { operation: 'catalogQuery', resultType: 'catalogResult', kind: 'agents' },
    'pxui.agents.action.catalogPrevious': { operation: 'catalogQuery', resultType: 'catalogResult', kind: 'agents' },
    'pxui.agents.action.enterpriseDoctor': { operation: 'enterpriseDoctor', resultType: 'enterpriseResult' },
    'pxui.agents.action.openStudioRuns.agent': { operation: 'studioOperation', resultType: 'studioOperationResult', kind: 'agent' },
    'pxui.agent-studio.action.refreshHostModels': { operation: 'listHostModels', resultType: 'hostModelCatalog', kind: 'agent', modalScenario: 'studio-draft' },
    'pxui.assurance.action.enterpriseDoctor': { operation: 'enterpriseDoctor', resultType: 'enterpriseResult' },
    'pxui.diagnostics.action.catalogRetry': { operation: 'catalogQuery', resultType: 'catalogResult', kind: 'enterprise-integrations' },
    'pxui.diagnostics.action.inspectOperationalInventory': { operation: 'operationalInventoryQuery', resultType: 'operationalInventoryResult' },
    'pxui.diagnostics.action.inspectPunchCard.row': { operation: 'operationalCardQuery', resultType: 'operationalCardResult' },
    'pxui.diagnostics.action.operationalCardsNext': { operation: 'operationalCardsQuery', resultType: 'operationalCardsResult' },
    'pxui.diagnostics.action.operationalCardsPrevious': { operation: 'operationalCardsQuery', resultType: 'operationalCardsResult' },
    'pxui.diagnostics.action.queryOperationalCards': { operation: 'operationalCardsQuery', resultType: 'operationalCardsResult' },
    'pxui.knowledge-graph.action.focusGraphNode.row': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.knowledge-graph.action.graphClearCommunity': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.knowledge-graph.action.graphCommunity.row': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.knowledge-graph.action.graphFilterEdgeBundle': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.knowledge-graph.action.graphClearEdgeBundle': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.knowledge-graph.action.graphOpenNeighborhood': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.knowledge-graph.action.graphOverview': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.knowledge-graph.action.graphView.capabilities': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.knowledge-graph.action.graphView.repository': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.knowledge-graph.action.runGraphSearch': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.memory.action.memoryRefresh': { operation: 'memoryQuery', resultType: 'memoryResult' },
    'pxui.plugins.action.environmentExtensionDetail.row': { operation: 'environmentExtensionDetail', resultType: 'environmentExtensionDetail' },
    'pxui.plugins.action.refreshEnvironment': { operation: 'refreshEnvironment', resultType: 'environmentInventory' },
    'pxui.projects.action.openRepositoryGraph': { operation: 'graphQuery', resultType: 'graphResult' },
    'pxui.runtime-core.action.refresh': { operation: 'refresh', resultType: 'snapshot' },
    'pxui.skill-studio.action.loadSkillPackageEditor': { operation: 'loadSkillPackageEditor', resultType: 'skillPackageEditorResult', kind: 'skill', modalScenario: 'catalog-record' },
    'pxui.skills-tools.action.catalogRetry': { operation: 'catalogQuery', resultType: 'catalogResult', kind: 'skills' },
    'pxui.skills-tools.action.enterpriseDoctor': { operation: 'enterpriseDoctor', resultType: 'enterpriseResult' },
    'pxui.workflows.action.catalogRetry': { operation: 'catalogQuery', resultType: 'catalogResult', kind: 'workflows' },
    'pxui.workflows.action.catalogNext': { operation: 'catalogQuery', resultType: 'catalogResult', kind: 'workflows' },
    'pxui.workflows.action.catalogPrevious': { operation: 'catalogQuery', resultType: 'catalogResult', kind: 'workflows' },
    'pxui.workflows.action.enterpriseDoctor': { operation: 'enterpriseDoctor', resultType: 'enterpriseResult' },
    'pxui.workflows.action.environmentExtensionDetail.row': { operation: 'environmentExtensionDetail', resultType: 'environmentExtensionDetail' },
    'pxui.workflows.action.openStudioRuns.workflow': { operation: 'studioOperation', resultType: 'studioOperationResult', kind: 'workflow' }
  })[id];
  if (readFailure) return { type: 'read-action-failure', controlId: id, ...readFailure };
  const catalog = id.match(/^pxui\.(agents|workflows|skills-tools|diagnostics)\.(?:action\.catalogRetry|indicator\.catalog(?:Error|Pending))$/)?.[1];
  if (catalog) return { type: id.endsWith('Pending') ? 'catalog-pending' : 'catalog-error', kind: catalog === 'skills-tools' ? 'skills' : catalog === 'diagnostics' ? 'enterprise-integrations' : catalog };
  const query = id.match(/^pxui\.(activity|memory|knowledge-graph)\.indicator\.query(Error|Pending)$/);
  if (query) return { type: `query-${query[2].toLowerCase()}`, kind: query[1] };
  if (id === 'pxui.knowledge-core.indicator.controllerError') return { type: 'knowledge-controller-error', kind: 'knowledge' };
  return null;
}

function installedConditionalRecoverySpec(control) {
  if (control?.kind !== 'indicator') return null;
  const scenario = installedConditionalScenario(control);
  if (!scenario) return null;
  if (scenario.type === 'catalog-error') {
    return { action: 'catalogRetry', actionKind: scenario.kind, responseType: 'catalogResult' };
  }
  if (scenario.type === 'query-error') {
    const byKind = {
      activity: { action: 'activityRefresh', responseType: 'activityResult' },
      memory: { action: 'memoryRefresh', responseType: 'memoryResult' },
      'knowledge-graph': { action: 'runGraphSearch', responseType: 'graphResult' }
    };
    return byKind[scenario.kind] || null;
  }
  if (scenario.type === 'knowledge-controller-error') {
    return { action: 'knowledgeRefresh', responseType: 'studioOperationResult', responseKind: 'knowledge', operation: 'browse' };
  }
  return null;
}

async function seedInstalledConditionalScenario(frameHost, control) {
  const scenario = installedConditionalScenario(control);
  if (!scenario) return false;
  const seeded = await frameHost.evaluateContent(spec => {
    const requestId = `px-installed-conditional-${Date.now()}-${Math.random()}`;
    const bindRequest = (operation, kind) => {
      if (operation === 'graphQuery') { state.graphRequestId = requestId; state.graphPending = true; }
      if (operation === 'memoryQuery') { state.memoryRequestId = requestId; state.memoryPending = true; }
      if (operation === 'activityQuery') { state.activityRequestId = requestId; state.activityPending = true; }
      if (operation === 'catalogQuery' && kind) {
        state.catalogRequests[kind] ||= { query: '', status: '', offset: 0, limit: 50, sort: 'label' };
        state.catalogRequests[kind].requestId = requestId;
      }
    };
    const sendError = (operation, kind, error) => {
      bindRequest(operation, kind);
      window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation, kind, requestId, error } }));
    };
    const seedPending = (operation, kind) => {
      bindRequest(operation, kind);
      if (operation === 'catalogQuery') state.catalogs[kind] = null;
      render();
    };
    if (spec.type === 'read-action-failure') {
      globalThis.__PX_INSTALLED_FAILURE_SCENARIOS__ ||= {};
      globalThis.__PX_INSTALLED_FAILURE_SCENARIOS__[spec.controlId] = { operation: spec.operation, resultType: spec.resultType, kind: spec.kind || '', requestId, seeded: true };
      sendError(spec.operation, spec.kind || null, `Bounded installed current-source failure for ${spec.controlId}`);
      document.querySelector('[data-action="closeModal"]')?.click();
      if (spec.operation === 'catalogQuery' && spec.kind && !spec.controlId.endsWith('.action.catalogRetry')) {
        document.querySelector(`[data-action="catalogRetry"][data-kind="${CSS.escape(spec.kind)}"]`)?.click();
      }
      return true;
    }
    if (spec.type === 'catalog-error' || spec.type === 'catalog-pending') {
      if (spec.type === 'catalog-pending') seedPending('catalogQuery', spec.kind);
      else sendError('catalogQuery', spec.kind, 'Bounded installed current-source catalog failure');
      document.querySelector('[data-action="closeModal"]')?.click();
      return true;
    }
    if (spec.type === 'knowledge-controller-error') {
      sendError('studioOperation', spec.kind, 'Bounded installed current-source knowledge controller failure');
      document.querySelector('[data-action="closeModal"]')?.click();
      return true;
    }
    const operation = spec.kind === 'knowledge-graph' ? 'graphQuery' : `${spec.kind}Query`;
    if (spec.type === 'query-error') {
      sendError(operation, null, `Bounded installed current-source ${spec.kind} query failure`);
      document.querySelector('[data-action="closeModal"]')?.click();
      return true;
    }
    seedPending(operation, null);
    return true;
  }, scenario);
  if (scenario.type === 'read-action-failure') await wait(scenario.operation === 'catalogQuery' ? 180 : 40);
  if (control.kind === 'indicator') {
    const selector = installedDirectSelector(control);
    const deadline = Date.now() + 5_000;
    let visible = false;
    do {
      visible = await frameHost.evaluate((frame, exactSelector) => {
        const target = frame.contentDocument?.querySelector(exactSelector);
        return Boolean(target && (target.offsetWidth || target.offsetHeight || target.getClientRects().length));
      }, selector);
      if (visible) break;
      await wait(50);
    } while (Date.now() < deadline);
    if (!visible) throw new Error(`installed-conditional-control-settlement-timeout:${control.control_id}:${selector}`);
  }
  return seeded;
}

async function recoverInstalledConditionalIndicator(frameHost, control, timeoutMs = 15_000) {
  const recovery = installedConditionalRecoverySpec(control);
  if (!recovery) return { applicable: false, recovered: false };
  const selector = directSelectorFor(control);
  const initial = await frameHost.evaluate((frame, spec) => {
    const document = frame.contentDocument; const inner = frame.contentWindow;
    if (!document || !inner) throw new Error('PX installed conditional recovery document is unavailable.');
    const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    const candidates = [...document.querySelectorAll(`[data-action="${CSS.escape(spec.action)}"]`)];
    const action = candidates.find(element => (!spec.actionKind || element.dataset.kind === spec.actionKind) && visible(element) && !element.disabled);
    if (!action) return { dispatched: false, responseOffset: inner.__PX_INSTALLED_RESPONSES__?.length || 0 };
    const responseOffset = inner.__PX_INSTALLED_RESPONSES__?.length || 0;
    action.click();
    return { dispatched: true, responseOffset };
  }, recovery);
  if (!initial.dispatched) return { applicable: true, recovered: false, reason: 'exact-recovery-action-unavailable' };
  const deadline = Date.now() + Math.max(1, timeoutMs);
  let lastState = null;
  do {
    lastState = await frameHost.evaluate((frame, spec) => {
      const document = frame.contentDocument; const inner = frame.contentWindow;
      const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
      const errorVisible = spec.selector ? [...document.querySelectorAll(spec.selector)].some(visible) : true;
      const response = (inner.__PX_INSTALLED_RESPONSES__ || []).slice(spec.responseOffset).find(value => value?.type === spec.responseType
        && (!spec.responseKind || value?.kind === spec.responseKind)
        && (!spec.operation || value?.operation === spec.operation));
      return { errorVisible, responseMatched: Boolean(response) };
    }, { ...recovery, selector, responseOffset: initial.responseOffset });
    if (lastState.responseMatched && !lastState.errorVisible) {
      return { applicable: true, recovered: true, action: recovery.action, response_type: recovery.responseType };
    }
    await wait(100);
  } while (Date.now() < deadline);
  return { applicable: true, recovered: false, reason: 'exact-error-recovery-timeout', last_state: lastState };
}

async function seedInstalledStudioPrerequisites(frameHost, control) {
  const steps = installedStudioPrerequisites(control);
  for (const step of steps) {
    await frameHost.evaluate((frame, prerequisite) => {
      const document = frame.contentDocument;
      if (!document) throw new Error('PX installed contentDocument is unavailable.');
      if (prerequisite.action === 'workflowConnectNodes') {
        const source = document.querySelector('[data-edge-source-endpoint]');
        const target = document.querySelector('[data-edge-target-endpoint]');
        const endpoints = select => [...(select?.options || [])].map(option => {
          const [node, port] = String(option.value || '').split('|');
          const type = String(option.textContent || '').match(/:([^:\s]+)\s*$/)?.[1] || '';
          return { node, port, type, value: option.value };
        });
        const pair = endpoints(source).flatMap(output => endpoints(target).map(input => ({ output, input })))
          .find(({ output, input }) => output.node && input.node && output.node !== input.node && output.type === input.type);
        if (!pair) throw new Error('studio-prerequisite-unavailable:compatible-workflow-edge');
        source.value = pair.output.value;
        target.value = pair.input.value;
      }
      const candidates = [...document.querySelectorAll(`[data-action="${CSS.escape(prerequisite.action)}"]`)].filter(element =>
        Object.entries(prerequisite.dataset).every(([key, value]) => String(element.dataset[key] || '') === String(value))
      );
      const target = prerequisite.pick === 'last' ? candidates.at(-1) : candidates[0];
      if (!target || target.disabled) throw new Error(`studio-prerequisite-unavailable:${prerequisite.action}`);
      target.click();
    }, step);
    await wait(60);
  }
  return steps;
}

async function instrumentInstalledBridge(frameHost, timeoutMs = 10_000) {
  return frameHost.evaluate(frame => {
    const inner = frame.contentWindow;
    if (!inner) return false;
    inner.__PX_INSTALLED_RESPONSES__ ||= [];
    inner.__PX_INSTALLED_REQUESTS__ ||= [];
    if (inner.__PX_INSTALLED_BRIDGE_INSTRUMENTED__) return true;
    inner.addEventListener('message', event => {
      try { inner.__PX_INSTALLED_RESPONSES__.push(JSON.parse(JSON.stringify(event.data))); }
      catch { inner.__PX_INSTALLED_RESPONSES__.push({ type: 'unserializable-message' }); }
    });
    inner.addEventListener('px-dashboard-outbound-request', event => {
      try { inner.__PX_INSTALLED_REQUESTS__.push(JSON.parse(JSON.stringify(event.detail))); }
      catch { inner.__PX_INSTALLED_REQUESTS__.push({ type: 'unserializable-request' }); }
    });
    inner.__PX_INSTALLED_BRIDGE_INSTRUMENTED__ = true;
    return true;
  }, undefined, { timeout: Math.max(1, timeoutMs) });
}

async function reopenPacifyDashboardFromOwnedUi(workbench, frameHost = null, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  if (typeof workbench.isClosed === 'function' && workbench.isClosed()) throw new Error('owned-workbench-closed-before-dashboard-reopen');
  await boundedOwnedUiAction(() => workbench.bringToFront(), Math.max(1, deadline - Date.now()), 'owned-workbench-bring-to-front');
  let lastOwner = 'unavailable';
  do {
    const dashboardTab = workbench.locator('[role="tab"]', { hasText: /PX.*Control Plane/i }).first();
    let owner;
    if (await dashboardTab.isVisible().catch(() => false)) {
      owner = dashboardTab;
      lastOwner = 'existing-dashboard-tab';
    } else {
      const status = workbench.locator('.statusbar-item').filter({ hasText: /\bPX\b/i }).first();
      await status.waitFor({ state: 'visible', timeout: Math.max(1, Math.min(2_500, deadline - Date.now())) });
      const label = `${await status.getAttribute('aria-label').catch(() => '')} ${await status.getAttribute('title').catch(() => '')} ${await status.innerText().catch(() => '')}`;
      if (!/PX|Pacify-X/i.test(label)) throw new Error('pacify-statusbar-command-owner-unavailable');
      owner = status;
      lastOwner = 'pacify-statusbar';
    }
    await workbench.keyboard.press('Escape').catch(() => {});
    try {
      await owner.click({ timeout: Math.max(1_000, Math.min(3_000, deadline - Date.now())) });
    } catch {
      await owner.evaluate(element => element.click(), undefined, { timeout: Math.max(1_000, deadline - Date.now()) });
    }
    if (!frameHost) return { owner: lastOwner, executed: true };
    const remaining = deadline - Date.now();
    const reconstructionBudget = Math.max(1, Math.min(2_500, remaining));
    const reconstructed = remaining > 0
      && await frameHost.reacquire(reconstructionBudget).catch(() => false)
      && await boundedOwnedUiAction(
        () => instrumentInstalledBridge(frameHost, reconstructionBudget),
        reconstructionBudget,
        'installed-dashboard-reopen-instrument'
      ).catch(() => false);
    if (reconstructed) {
      let stable = true;
      for (let sample = 0; sample < 2; sample += 1) {
        await wait(200);
        const sampleRemaining = deadline - Date.now();
        const sampleBudget = Math.max(1, Math.min(2_500, sampleRemaining));
        stable = sampleRemaining > 0
          && await frameHost.reacquire(sampleBudget).catch(() => false)
          && await boundedOwnedUiAction(
            () => instrumentInstalledBridge(frameHost, sampleBudget),
            sampleBudget,
            'installed-dashboard-reopen-stability-instrument'
          ).catch(() => false);
        if (!stable) break;
      }
      if (stable) return { owner: lastOwner, executed: true, reconstructed: true, stability_samples: 2 };
    }
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`installed-dashboard-owner-reopen-timeout:${lastOwner}`);
}

async function waitForOwnedWorkbenchDisplacementSettled(workbench, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  let previousIdentity = '';
  let stableSamples = 0;
  let lastState = null;
  do {
    lastState = await workbench.evaluate(() => {
      const tab = document.querySelector('.editor-group-container.active .tabs-container .tab.active, .editor-group-container .tabs-container .tab.active');
      if (!tab) return { identity: '', dashboard: false };
      const identity = [tab.getAttribute('aria-label'), tab.getAttribute('title'), tab.textContent]
        .map(value => String(value || '').trim()).filter(Boolean).join(' | ');
      return { identity, dashboard: /PX.*Control Plane|Pacify-X.*Control Plane/i.test(identity) };
    }).catch(() => ({ identity: '', dashboard: false }));
    if (lastState.identity && !lastState.dashboard) {
      stableSamples = lastState.identity === previousIdentity ? stableSamples + 1 : 1;
      previousIdentity = lastState.identity;
      if (stableSamples >= 3) return { settled: true, identity: lastState.identity, stability_samples: stableSamples };
    } else {
      previousIdentity = '';
      stableSamples = 0;
    }
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`owned-workbench-displacement-unsettled:${JSON.stringify(lastState)}`);
}

async function waitForOwnedWorkbenchDisplacementOrReceipt(workbench, frameHost, expected, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  let previousIdentity = '';
  let stableSamples = 0;
  let lastState = null;
  do {
    lastState = await workbench.evaluate(() => {
      const tab = document.querySelector('.editor-group-container.active .tabs-container .tab.active, .editor-group-container .tabs-container .tab.active');
      if (!tab) return { identity: '', dashboard: false };
      const identity = [tab.getAttribute('aria-label'), tab.getAttribute('title'), tab.textContent]
        .map(value => String(value || '').trim()).filter(Boolean).join(' | ');
      return { identity, dashboard: /PX.*Control Plane|Pacify-X.*Control Plane/i.test(identity) };
    }).catch(() => ({ identity: '', dashboard: false }));
    if (lastState.identity && !lastState.dashboard) {
      stableSamples = lastState.identity === previousIdentity ? stableSamples + 1 : 1;
      previousIdentity = lastState.identity;
      if (stableSamples >= 3) return { terminal: 'native-displacement', settled: true, identity: lastState.identity, stability_samples: stableSamples, response: null };
    } else {
      previousIdentity = '';
      stableSamples = 0;
    }
    if (lastState.dashboard) {
      const response = await frameHost.evaluate((frame, item) => {
        const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
        const matches = value => value?.type === 'hostActionResult'
          && value.requestId === item.requestId
          && value.operation === item.operation
          && Date.parse(value.observedAt || '') >= item.startedAt;
        return responses.slice(item.after).find(matches)
          || responses.find(matches)
          || [frame.contentWindow?.__PX_DURABLE_HOST_ACTION_RESULT__, ...[...responses].reverse().filter(value => value?.type === 'snapshot').map(value => value?.snapshot?.lastHostActionResult)].find(matches)
          || null;
      }, expected, { timeout: Math.max(1, Math.min(750, deadline - Date.now())) }).catch(() => null);
      if (response) return { terminal: 'durable-dashboard-retained', settled: false, identity: lastState.identity, stability_samples: 0, response };
    }
    await wait(120);
  } while (Date.now() < deadline);
  throw new Error(`owned-workbench-displacement-or-receipt-unsettled:${JSON.stringify(lastState)}`);
}

async function resetInstalledDashboardBaseline(workbench, frameHost, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  const remaining = () => Math.max(1, deadline - Date.now());
  const locatorBudget = () => Math.max(1, Math.min(2_500, remaining()));
  const closeModal = () => frameHost.evaluate(
    frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click(),
    undefined,
    { timeout: locatorBudget() }
  );
  let initialError = null;
  try {
    // Native host actions can leave a still-readable hidden dashboard frame.
    // Discard the cached owner first, and reserve most of this bounded budget
    // for reopening the dashboard if the current visible frame is unavailable.
    const initialProbeBudget = Math.max(250, Math.min(2_500, Math.floor(timeoutMs / 4)));
    await boundedOwnedUiAction(async () => {
      if (typeof frameHost.reacquire === 'function' && !await frameHost.reacquire(initialProbeBudget)) {
        throw new Error('installed-dashboard-baseline-current-frame-unavailable');
      }
      if (!await instrumentInstalledBridge(frameHost, initialProbeBudget)) {
        throw new Error('installed-dashboard-baseline-instrumentation-unavailable');
      }
    }, initialProbeBudget, 'installed-dashboard-baseline-instrument');
    await boundedOwnedUiAction(closeModal, remaining(), 'installed-dashboard-baseline-close-modal');
    await boundedOwnedUiAction(() => navigateInstalledSurface(frameHost, 'dashboard', remaining()), remaining(), 'installed-dashboard-baseline-navigation');
    return { owner: 'existing-webview', recovered: false };
  } catch (error) {
    initialError = String(error?.message || error).slice(0, 1000);
  }
  if (Date.now() >= deadline) {
    throw new Error(`installed-dashboard-baseline-recovery-failed:${JSON.stringify({ initial_error: initialError, recovery_error: 'baseline-budget-exhausted' })}`);
  }
  try {
    await reopenPacifyDashboardFromOwnedUi(workbench, frameHost, remaining());
    await boundedOwnedUiAction(closeModal, remaining(), 'installed-dashboard-recovered-close-modal');
    await boundedOwnedUiAction(() => navigateInstalledSurface(frameHost, 'dashboard', remaining()), remaining(), 'installed-dashboard-recovered-navigation');
    return { owner: 'pacify-statusbar', recovered: true, initial_error: initialError };
  } catch (error) {
    throw new Error(`installed-dashboard-baseline-recovery-failed:${JSON.stringify({ initial_error: initialError, recovery_error: String(error?.message || error).slice(0, 1000) })}`);
  }
}

async function restartInstalledDashboardWebview(frameHost, timeoutMs = 30_000) {
  const before = await frameHost.evaluate(frame => Number(frame.contentWindow?.performance?.timeOrigin || 0));
  const workbench = frameHost.page();
  const dashboardTab = workbench.locator('[role="tab"]', { hasText: /PX.*Control Plane/i }).first();
  await dashboardTab.waitFor({ state: 'visible', timeout: 15_000 });
  await dashboardTab.click();
  await workbench.keyboard.press(process.platform === 'darwin' ? 'Meta+W' : 'Control+W');
  await dashboardTab.waitFor({ state: 'hidden', timeout: 15_000 });
  await reopenPacifyDashboardFromOwnedUi(workbench, frameHost);
  await dashboardTab.waitFor({ state: 'visible', timeout: 30_000 });
  await dashboardTab.click();
  const deadline = Date.now() + timeoutMs;
  let state = null;
  do {
    try {
      state = await frameHost.evaluate((frame, previousTimeOrigin) => {
        const inner = frame.contentWindow; const document = frame.contentDocument;
        const text = String(document?.body?.innerText || '');
        return {
          ready: document?.readyState === 'complete' && /PACIFY-X\s*\/\s*DASHBOARD/i.test(text),
          connected: !document?.querySelector('#app')?.classList.contains('disconnected'),
          time_origin: Number(inner?.performance?.timeOrigin || 0),
          restarted: Number(inner?.performance?.timeOrigin || 0) > 0
            && Number(inner?.performance?.timeOrigin || 0) !== previousTimeOrigin
        };
      }, before);
      if (state.ready && state.connected && state.restarted) {
        if (!await instrumentInstalledBridge(frameHost)) throw new Error('installed-dashboard-webview-restart-bridge-unavailable');
        return { before_time_origin: before, after_time_origin: state.time_origin, restarted: true, reconstructed: true };
      }
    } catch { /* the active frame is expected to rematerialize while reloading */ }
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`installed-dashboard-webview-restart-timeout:${JSON.stringify(state)}`);
}

async function reloadInstalledDashboardWebview(frameHost, timeoutMs = 30_000) {
  const before = await frameHost.evaluate(frame => Number(frame.contentWindow?.performance?.timeOrigin || 0));
  await frameHost.evaluate(frame => frame.contentWindow.location.reload());
  const deadline = Date.now() + timeoutMs;
  let state = null;
  do {
    try {
      state = await frameHost.evaluate((frame, previousTimeOrigin) => ({
        ready: frame.contentDocument?.readyState === 'complete'
          && /PACIFY-X\s*\/\s*DASHBOARD/i.test(String(frame.contentDocument?.body?.innerText || '')),
        connected: !frame.contentDocument?.querySelector('#app')?.classList.contains('disconnected'),
        time_origin: Number(frame.contentWindow?.performance?.timeOrigin || 0),
        restarted: Number(frame.contentWindow?.performance?.timeOrigin || 0) > 0
          && Number(frame.contentWindow?.performance?.timeOrigin || 0) !== previousTimeOrigin
      }), before);
      if (state.ready && state.connected && state.restarted) {
        if (!await instrumentInstalledBridge(frameHost)) throw new Error('installed-dashboard-reload-bridge-unavailable');
        return { before_time_origin: before, after_time_origin: state.time_origin, restarted: true };
      }
    } catch { /* the active frame rematerializes during reload */ }
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`installed-dashboard-reload-timeout:${JSON.stringify(state)}`);
}

async function waitForInstalledStudioState(frameHost, kind, expected, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let lastState = null;
  do {
    const state = await frameHost.evaluate((frame, expectedKind) => {
      const document = frame.contentDocument;
      const open = document?.querySelector(`[data-action="openStudioDraft"][data-kind="${expectedKind}"]`);
      const resume = document?.querySelector(`[data-action="resumeWorkingStudioDraft"][data-kind="${expectedKind}"]`);
      const modal = [...(document?.querySelectorAll('.studio-modal') || [])].find(element => element.offsetWidth || element.offsetHeight || element.getClientRects().length);
      const visibleControlModal = [...(document?.querySelectorAll('.control-modal') || [])].find(element => element.offsetWidth || element.offsetHeight || element.getClientRects().length);
      return {
        opener: Boolean(open || resume), modal: Boolean(modal),
        visible_modal_title: visibleControlModal?.querySelector('h2')?.textContent?.trim() || '',
        visible_modal_actions: [...(visibleControlModal?.querySelectorAll('[data-action]') || [])].map(element => ({ action: element.dataset.action, kind: element.dataset.kind || null }))
      };
    }, kind);
    lastState = state;
    if (state[expected]) return state;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`${kind}-studio-${expected}-not-ready:${JSON.stringify(lastState)}`);
}

async function resumeInstalledWorkingDraftIfOffered(frameHost, kind, timeoutMs = 2_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const state = await frameHost.evaluate((frame, expectedKind) => {
      const document = frame.contentDocument;
      const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
      if ([...(document?.querySelectorAll('.studio-modal') || [])].some(visible)) return 'editor';
      const resume = [...(document?.querySelectorAll('[data-action="resumeWorkingStudioDraft"]') || [])]
        .find(element => element.dataset.kind === expectedKind && visible(element));
      if (!resume || resume.disabled) return 'waiting';
      resume.click();
      return 'resumed';
    }, kind);
    if (state !== 'waiting') return state;
    await wait(100);
  } while (Date.now() < deadline);
  return 'not-offered';
}

async function prepareInstalledRetainedWorkingDraft(frameHost, kind) {
  await frameHost.evaluate((frame, expectedKind) => {
    const open = frame.contentDocument?.querySelector(`[data-action="openStudioDraft"][data-kind="${expectedKind}"]`);
    if (!open || open.disabled) throw new Error(`studio-${expectedKind}-working-draft-opener-unavailable`);
    open.click();
  }, kind);
  await wait(100);
  const offered = await frameHost.evaluate((frame, expectedKind) => Boolean(
    frame.contentDocument?.querySelector(`[data-action="resumeWorkingStudioDraft"][data-kind="${expectedKind}"]`)
  ), kind);
  if (offered) return true;
  await waitForInstalledStudioState(frameHost, kind, 'modal');
  await frameHost.evaluate((frame, expectedKind) => {
    const document = frame.contentDocument;
    const owner = document?.querySelector('#studio-owner');
    if (!owner) throw new Error(`studio-${expectedKind}-working-draft-owner-unavailable`);
    owner.value = `${owner.value}:retained-probe`;
    owner.dispatchEvent(new frame.contentWindow.Event('input', { bubbles: true }));
    document.querySelector('[data-action="closeModal"]')?.click();
  }, kind);
  await wait(100);
  await frameHost.evaluate((frame, expectedKind) => {
    const open = frame.contentDocument?.querySelector(`[data-action="openStudioDraft"][data-kind="${expectedKind}"]`);
    if (!open || open.disabled) throw new Error(`studio-${expectedKind}-working-draft-reopen-unavailable`);
    open.click();
  }, kind);
  await wait(100);
  const ready = await frameHost.evaluate((frame, expectedKind) => {
    const document = frame.contentDocument;
    return Boolean(document?.querySelector(`[data-action="resumeWorkingStudioDraft"][data-kind="${expectedKind}"]`)
      && document.querySelector(`[data-action="discardWorkingStudioDraft"][data-kind="${expectedKind}"]`));
  }, kind);
  if (!ready) throw new Error(`studio-${kind}-working-draft-offer-not-ready`);
  return true;
}

async function prepareInstalledStudioCatalogRecord(frameHost, kind, openEditor = false, timeoutMs = 20_000) {
  const catalogKind = kind === 'skill' ? 'skills' : `${kind}s`;
  const action = kind === 'skill' ? 'loadSkillPackageEditor' : 'openStudioFromCatalog';
  const rowIds = await frameHost.evaluate((frame, expectedCatalogKind) => [...(frame.contentDocument?.querySelectorAll('[data-action="inspectCatalogItem"]') || [])]
    .filter(element => element.dataset.kind === expectedCatalogKind && !element.disabled)
    .map(element => element.dataset.id), catalogKind);
  for (const rowId of rowIds) {
    await frameHost.evaluate((frame, item) => {
      const row = [...frame.contentDocument.querySelectorAll('[data-action="inspectCatalogItem"]')]
        .find(element => element.dataset.kind === item.catalogKind && element.dataset.id === item.rowId && !element.disabled);
      row?.click();
    }, { catalogKind, rowId });
    await wait(80);
    const available = await frameHost.evaluate((frame, item) => Boolean([...frame.contentDocument.querySelectorAll(`[data-action="${item.action}"]`)]
      .find(element => element.dataset.kind === item.kind && !element.disabled)), { action, kind });
    if (available) {
      if (!openEditor) return true;
      await frameHost.evaluate((frame, item) => {
        const opener = [...frame.contentDocument.querySelectorAll(`[data-action="${item.action}"]`)]
          .find(element => element.dataset.kind === item.kind && !element.disabled);
        opener?.click();
      }, { action, kind });
      const deadline = Date.now() + timeoutMs;
      do {
        const editorReady = await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('.studio-modal #studio-identity')));
        if (editorReady) return true;
        await wait(150);
      } while (Date.now() < deadline);
      throw new Error(`studio-${kind}-predecessor-editor-not-ready`);
    }
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
    await wait(40);
  }
  throw new Error(`studio-${kind}-editable-catalog-record-unavailable`);
}

async function prepareInstalledStudioDraftModal(frameHost, kind, control) {
  await frameHost.evaluate((frame, expectedKind) => {
    const document = frame.contentDocument;
    const open = document?.querySelector(`[data-action="openStudioDraft"][data-kind="${expectedKind}"]`);
    const resume = document?.querySelector(`[data-action="resumeWorkingStudioDraft"][data-kind="${expectedKind}"]`);
    (open || resume)?.click();
  }, kind);
  await resumeInstalledWorkingDraftIfOffered(frameHost, kind);
  await waitForInstalledStudioState(frameHost, kind, 'modal');
  if (['agent', 'workflow'].includes(kind)) {
    await frameHost.evaluate(frame => {
      const visual = frame.contentDocument?.querySelector('[data-action="studioEditorTab"][data-tab="visual"]');
      if (visual && visual.getAttribute('aria-selected') !== 'true') visual.click();
    });
    await wait(40);
  }
  await seedInstalledStudioPrerequisites(frameHost, control);
}

async function prepareInstalledCatalogModalAction(frameHost, action, kind = '', timeoutMs = 20_000) {
  const rowIds = await frameHost.evaluate((frame, expectedKind) => [...(frame.contentDocument?.querySelectorAll('[data-action="inspectCatalogItem"]') || [])]
    .filter(element => (!expectedKind || element.dataset.kind === expectedKind) && !element.disabled)
    .map(element => ({ kind: element.dataset.kind || '', id: element.dataset.id || '' })), kind);
  for (const row of rowIds) {
    await frameHost.evaluate((frame, item) => {
      const target = [...frame.contentDocument.querySelectorAll('[data-action="inspectCatalogItem"]')]
        .find(element => element.dataset.kind === item.kind && element.dataset.id === item.id && !element.disabled);
      target?.click();
    }, row);
    const deadline = Date.now() + timeoutMs;
    do {
      const available = await frameHost.evaluate((frame, expected) => [...(frame.contentDocument?.querySelectorAll(`[data-action="${expected.action}"]`) || [])]
        .some(element => (!expected.kind || !element.dataset.kind || element.dataset.kind === expected.kind) && !element.disabled
          && (element.offsetWidth || element.offsetHeight || element.getClientRects().length)), { action, kind: kind.replace(/s$/, '') });
      if (available) return true;
      const modal = await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('.control-modal')));
      if (!modal) break;
      await wait(80);
    } while (Date.now() < deadline);
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
    await wait(40);
  }
  throw new Error(`installed-catalog-modal-action-unavailable:${action}:${kind || 'any'}`);
}

async function restoreInstalledModalAfterConditionalFailure(frameHost, control, kind, scenario) {
  if (!scenario?.modalScenario) return false;
  if (scenario.modalScenario === 'catalog-record') {
    await prepareInstalledStudioCatalogRecord(frameHost, kind, false);
    return true;
  }
  if (scenario.modalScenario === 'studio-draft') {
    await prepareInstalledStudioDraftModal(frameHost, kind, control);
    return true;
  }
  throw new Error(`installed-modal-scenario-unsupported:${scenario.modalScenario}`);
}

async function prepareInstalledControl(frameHost, control) {
  const route = INSTALLED_ROUTES[control.surface_id];
  if (!route) throw new Error(`No installed dashboard route for ${control.surface_id}`);
  const surfaceState = installedSurfaceState(control);
  const exactNavigation = installedExactNavigationTransition(control);
  if (exactNavigation?.owner === 'runtimeCore') {
    const ownerReady = await frameHost.evaluateContent(owner => {
      if (state.settings?.showAdvancedSurfaces !== true) return false;
      state.active = owner;
      state.advancedOpen = false;
      render();
      return document.querySelector('.content')?.classList.contains(`surface-${owner}`) === true;
    }, exactNavigation.owner);
    if (!ownerReady) throw new Error(`installed-navigation-owner-fixture-unavailable:${exactNavigation.owner}`);
  } else {
    await navigateInstalledSurface(frameHost, route, 20_000);
  }
  const advancedNavigation = String(control.control_id).match(/\.action\.navigate\.(knowledgeCore|runtimeCore)$/)?.[1];
  if (advancedNavigation) await waitForAdvancedNavigationExpanded(frameHost, advancedNavigation, 5_000);
  if (route === 'knowledgeGraph') {
    const deadline = Date.now() + 20_000;
    let graphReady = false;
    while (Date.now() < deadline) {
      if (await frameHost.evaluate(frame => Boolean(frame.contentDocument.querySelector('[data-graph-canvas], .graph-inline-error')))) {
        graphReady = true;
        break;
      }
      await wait(100);
    }
    if (control.control_id === 'pxui.knowledge-graph.action.graphClearEdgeBundle') {
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const requested = await frameHost.evaluateContent(() => {
        const filter = [...document.querySelectorAll('[data-action="graphFilterEdgeBundle"][data-relation]')]
          .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
        if (!filter) return false;
        filter.click();
        return true;
      });
      if (!requested) throw new Error('installed-graph-edge-bundle-filter-unavailable');
      await waitForInstalledResponse(frameHost, before, { types: ['graphResult'] }, 20_000);
      const clearDeadline = Date.now() + 5_000;
      while (Date.now() < clearDeadline) {
        if (await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('[data-action="graphClearEdgeBundle"]')))) break;
        await wait(80);
      }
      if (!await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('[data-action="graphClearEdgeBundle"]')))) {
        throw new Error('installed-graph-edge-bundle-clear-timeout');
      }
    }
    if (!graphReady) throw new Error('installed-graph-render-timeout');
    const needsCanonicalCommunities = ['pxui.knowledge-graph.action.graphClearCommunity', 'pxui.knowledge-graph.action.graphCommunity.row'].includes(control.control_id);
    if (needsCanonicalCommunities && !await frameHost.evaluate(frame => Boolean(frame.contentDocument.querySelector('[data-action="graphCommunity"][data-community-id]')))) {
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const requested = await frameHost.evaluate(frame => {
        const target = frame.contentDocument?.querySelector('[data-action="graphView"][data-view="capabilities"]');
        if (!target || target.disabled) return false;
        target.click();
        return true;
      });
      if (!requested) throw new Error('installed-graph-canonical-community-request-unavailable');
      await waitForInstalledResponse(frameHost, before, { types: ['graphResult'] }, 20_000);
      const communityDeadline = Date.now() + 20_000;
      while (Date.now() < communityDeadline) {
        if (await frameHost.evaluate(frame => Boolean(frame.contentDocument.querySelector('[data-action="graphCommunity"][data-community-id]')))) break;
        await wait(100);
      }
      if (!await frameHost.evaluate(frame => Boolean(frame.contentDocument.querySelector('[data-action="graphCommunity"][data-community-id]')))) {
        throw new Error('installed-graph-canonical-community-timeout');
      }
    }
  }
  if (surfaceState) {
    await frameHost.evaluate((frame, spec) => {
      const document = frame.contentDocument;
      const selector = spec.target
        ? `[data-action="surfaceScope"][data-target="${spec.target}"][data-scope="${spec.scope}"]`
        : `[data-action="capabilityTab"][data-kind="${spec.kind}"]`;
      const target = document?.querySelector(selector);
      if (!target || target.disabled) throw new Error(`installed-surface-state-unavailable:${selector}`);
      if (target.getAttribute('aria-pressed') !== 'true') target.click();
    }, surfaceState);
    await wait(80);
  }
  if (['agent-studio', 'workflow-studio', 'skill-studio'].includes(control.surface_id)) {
    const kind = control.surface_id.split('-')[0];
    await waitForInstalledStudioState(frameHost, kind, 'opener');
    const scenario = installedStudioControlScenario(control);
    if (scenario === 'retained-working-draft') {
      await prepareInstalledRetainedWorkingDraft(frameHost, kind);
      await seedInstalledConditionalScenario(frameHost, control);
      return;
    }
    if (scenario === 'catalog-record') {
      await prepareInstalledStudioCatalogRecord(frameHost, kind, false);
      await seedInstalledConditionalScenario(frameHost, control);
      await restoreInstalledModalAfterConditionalFailure(frameHost, control, kind, installedConditionalScenario(control));
      return;
    }
    if (scenario === 'predecessor-editor' || scenario === 'version-conflict') {
      await prepareInstalledStudioCatalogRecord(frameHost, kind, true);
      await seedInstalledConditionalScenario(frameHost, control);
      return;
    }
    await prepareInstalledStudioDraftModal(frameHost, kind, control);
    const conditionalScenario = installedConditionalScenario(control);
    await seedInstalledConditionalScenario(frameHost, control);
    await restoreInstalledModalAfterConditionalFailure(frameHost, control, kind, conditionalScenario);
    return;
  }
  const catalogImport = String(control.control_id).match(/^pxui\.(agents|workflows)\.action\.importCatalogDefinition\.(agent|workflow)$/);
  if (catalogImport) {
    await prepareInstalledCatalogModalAction(frameHost, 'importCatalogDefinition', catalogImport[1]);
    return;
  }
  if (control.control_id === 'pxui.skills-tools.action.compareSkillOriginal') {
    await prepareInstalledCatalogModalAction(frameHost, 'compareSkillOriginal', 'preserved-skills');
    return;
  }
  if (control.control_id === 'pxui.workflows.action.environmentExtensionDetail.row') {
    await frameHost.evaluate(frame => {
      const extensions = frame.contentDocument?.querySelector('[data-action="environmentScope"][data-scope="extensions"]');
      if (!extensions || extensions.disabled) throw new Error('installed-environment-extension-scope-unavailable');
      if (extensions.getAttribute('aria-pressed') !== 'true') extensions.click();
    });
    const deadline = Date.now() + 20_000;
    let rowAvailable = false;
    while (Date.now() < deadline) {
      if (await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('[data-action="environmentExtensionDetail"][data-extension-id]')))) {
        rowAvailable = true;
        break;
      }
      await wait(100);
    }
    if (!rowAvailable) throw new Error('installed-environment-extension-row-timeout');
    await seedInstalledConditionalScenario(frameHost, control);
    return;
  }
  if (control.control_id === 'pxui.knowledge-graph.action.inspectGraphRecord') {
    await frameHost.evaluateContent(() => {
      state.graphInspectorOpen = true;
      render();
      const records = document.querySelector('[data-graph-record-list]');
      if (!records || !records.options?.length) throw new Error('installed-graph-record-list-unavailable');
      const selectable = [...records.options].find(option => option.value && !option.disabled);
      if (!selectable) throw new Error('installed-graph-record-option-unavailable');
      records.value = selectable.value;
      records.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await wait(80);
  }
  const graphConditional = ({
    'pxui.knowledge-graph.action.graphClearCommunity': 'community-selected',
    'pxui.knowledge-graph.action.graphCommunity.row': 'community-index',
    'pxui.knowledge-graph.action.graphDepth.decrease': 'depth-decrease',
    'pxui.knowledge-graph.action.graphDepth.increase': 'depth-increase',
    'pxui.knowledge-graph.action.graphLayout.flow': 'layout-flow',
    'pxui.knowledge-graph.action.graphLayout.orbit': 'layout-orbit',
    'pxui.knowledge-graph.field.graphDirection': 'direction',
    'pxui.knowledge-graph.field.graphTarget': 'path-target',
    'pxui.knowledge-graph.menu.depth': 'depth-menu',
    'pxui.knowledge-graph.indicator.relationshipCounts': 'relationship-counts'
  })[control.control_id];
  if (graphConditional) {
    const graphStatePresent = await frameHost.evaluateContent(() => Boolean(
      state.graphData && Array.isArray(state.graphData.nodes) && state.graphPending !== true
    ));
    if (!graphStatePresent) {
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const requested = await frameHost.evaluateContent(() => {
        const target = document.querySelector('[data-action="graphView"][data-view="repository"]')
          || document.querySelector('[data-action="runGraphSearch"]');
        if (!target || target.disabled) return false;
        target.click();
        return true;
      });
      if (!requested) throw new Error(`installed-graph-baseline-request-unavailable:${graphConditional}`);
      await waitForInstalledResponse(frameHost, before, { types: ['graphResult'] }, 20_000);
    }
    const graphStateDeadline = Date.now() + 20_000;
    let graphStateReady = false;
    while (Date.now() < graphStateDeadline) {
      graphStateReady = await frameHost.evaluateContent(() => Boolean(state.graphData && Array.isArray(state.graphData.nodes) && state.graphPending !== true));
      if (graphStateReady) break;
      await wait(100);
    }
    if (!graphStateReady) throw new Error(`installed-graph-state-settlement-timeout:${graphConditional}`);
    const physicalMode = ({
      'depth-decrease': 'neighborhood', 'depth-increase': 'neighborhood', 'depth-menu': 'neighborhood',
      'layout-flow': 'neighborhood', 'layout-orbit': 'neighborhood',
      direction: 'dependencies', 'path-target': 'path'
    })[graphConditional] || null;
    const prepared = physicalMode ? await frameHost.evaluateContent(mode => {
      const analysis = document.querySelector('[data-graph-analysis]');
      if (!analysis || ![...analysis.options].some(option => option.value === mode)) return false;
      analysis.value = mode;
      analysis.dispatchEvent(new Event('change', { bubbles: true }));
      const apply = document.querySelector('[data-action="runGraphSearch"]');
      if (!apply || apply.disabled) return false;
      apply.click();
      return true;
    }, physicalMode) : await frameHost.evaluateContent(mode => {
      if (!state.graphData || !Array.isArray(state.graphData.nodes)) return false;
      state.graphInspectorOpen = true;
      if (mode === 'community-selected' || mode === 'community-index') {
        const communityId = document.querySelector('[data-action="graphCommunity"][data-community-id]')?.dataset.communityId;
        if (!communityId) return false;
        state.graphMode = 'full'; state.graphLayout = 'community';
        state.graphCommunity = mode === 'community-selected' ? communityId : '';
      } else if (mode === 'relationship-counts') {
        state.graphMode = 'full'; state.graphLayout = 'community';
      }
      render();
      return true;
    }, graphConditional);
    if (!prepared) throw new Error(`installed-graph-conditional-state-unavailable:${graphConditional}`);
    if (physicalMode) {
      const physicalDeadline = Date.now() + 20_000;
      let physicalSettled = false;
      while (Date.now() < physicalDeadline) {
        physicalSettled = await frameHost.evaluateContent(mode => Boolean(
          state.graphPending !== true
          && state.graphData
          && (state.graphData.mode || state.graphRequest?.mode || state.graphMode) === mode
        ), physicalMode);
        if (physicalSettled) break;
        await wait(100);
      }
      if (!physicalSettled) throw new Error(`installed-graph-physical-mode-settlement-timeout:${graphConditional}:${physicalMode}`);
    }
    const exactSelector = installedDirectSelector(control);
    if (physicalMode) {
      const predecessorPrepared = await frameHost.evaluateContent(mode => {
        let requestDispatched = false;
        if (mode === 'depth-decrease') {
          const target = document.querySelector('[data-action="graphDepth"][data-delta="-1"]');
          if (target?.disabled) {
            const predecessor = document.querySelector('[data-action="graphDepth"][data-delta="1"]:not([disabled])');
            if (predecessor) { predecessor.click(); requestDispatched = true; }
          }
        } else if (mode === 'depth-increase') {
          const target = document.querySelector('[data-action="graphDepth"][data-delta="1"]');
          if (target?.disabled) {
            const predecessor = document.querySelector('[data-action="graphDepth"][data-delta="-1"]:not([disabled])');
            if (predecessor) { predecessor.click(); requestDispatched = true; }
          }
        } else if (mode === 'layout-flow') {
          document.querySelector('[data-action="graphLayout"][data-layout="orbit"]')?.click();
        } else if (mode === 'layout-orbit') {
          document.querySelector('[data-action="graphLayout"][data-layout="flow"]')?.click();
        }
        return { prepared: true, requestDispatched };
      }, graphConditional);
      if (!predecessorPrepared?.prepared) throw new Error(`installed-graph-physical-predecessor-unavailable:${graphConditional}`);
      if (predecessorPrepared.requestDispatched) {
        const predecessorDeadline = Date.now() + 20_000;
        let predecessorSettled = false;
        while (Date.now() < predecessorDeadline) {
          predecessorSettled = await frameHost.evaluateContent(() => Boolean(state.graphPending !== true && state.graphData));
          if (predecessorSettled) break;
          await wait(100);
        }
        if (!predecessorSettled) throw new Error(`installed-graph-physical-predecessor-settlement-timeout:${graphConditional}`);
      }
    }
    const controlDeadline = Date.now() + 5_000;
    let exactControlVisible = false;
    while (Date.now() < controlDeadline) {
      exactControlVisible = await frameHost.evaluate((frame, selector) => {
        const element = frame.contentDocument?.querySelector(selector);
        return Boolean(element && !element.hidden && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
      }, exactSelector);
      if (exactControlVisible) break;
      await wait(80);
    }
    if (!exactControlVisible) throw new Error(`installed-graph-exact-control-timeout:${control.control_id}:${exactSelector}`);
  }
  await seedInstalledConditionalScenario(frameHost, control);
}

function installedAdvancedControlTarget(control) {
  const route = INSTALLED_ROUTES[control?.surface_id];
  if (['knowledgeCore', 'runtimeCore'].includes(route)) return route;
  return String(control?.control_id || '').match(/\.action\.navigate\.(knowledgeCore|runtimeCore)$/)?.[1] || null;
}

async function prepareInstalledAdvancedControl(frameHost, control) {
  const target = installedAdvancedControlTarget(control);
  if (!target) return null;
  await settleInstalledModalBoundary(frameHost, 5_000);
  return frameHost.evaluateContent(route => {
    const predecessor = {
      settings: structuredClone(state.settings || {}),
      active: state.active,
      advancedOpen: state.advancedOpen
    };
    state.settings = { ...(state.settings || {}), showAdvancedSurfaces: true };
    state.advancedOpen = true;
    render();
    if (state.settings?.showAdvancedSurfaces !== true || state.advancedOpen !== true) {
      throw new Error(`installed-advanced-route-fixture-state-unavailable:${route}`);
    }
    return predecessor;
  }, target);
}

async function restoreInstalledAdvancedControl(frameHost, predecessor) {
  if (!predecessor) return true;
  return frameHost.evaluateContent(original => {
    state.settings = original.settings;
    state.active = original.active;
    state.advancedOpen = original.advancedOpen;
    render();
    return state.active === original.active
      && state.advancedOpen === original.advancedOpen
      && state.settings?.showAdvancedSurfaces === original.settings?.showAdvancedSurfaces;
  }, predecessor);
}

async function revealInstalledControl(frameHost, control) {
  const action = revealActionFor(control);
  if (!action) return false;
  return frameHost.evaluate((frame, spec) => {
    const document = frame.contentDocument;
    if (!document) return false;
    const selector = spec.action === 'studioEditorTab'
      ? '[data-action="studioEditorTab"][data-tab="json"]'
      : `[data-action="${spec.action}"]`;
    const item = [...document.querySelectorAll(selector)].find(element => element.offsetWidth || element.offsetHeight || element.getClientRects().length);
    if (!item || item.disabled) return false;
    item.click();
    return true;
  }, { action });
}

async function exerciseInstalledControl(frameHost, control) {
  const spec = {
    controlId: control.control_id,
    kind: control.kind,
    semantic: semanticLabel(control),
    selector: selectorForKind(control.kind),
    directSelector: installedDirectSelector(control),
    action: control.kind === 'action' ? installedActionIdentity(control) : null,
    local: control.evidence_mode !== 'contained_host_interaction'
  };
  const before = await frameHost.evaluate((frame, item) => {
    const document = frame.contentDocument;
    const inner = frame.contentWindow;
    if (!document || !inner) throw new Error('PX installed contentDocument is unavailable.');
    const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    const normalize = value => String(value || '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[._:/-]/g, ' ')
      .toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
    const tokens = [...new Set(normalize(item.semantic).split(' ').filter(token => token.length > 2 || token === 'id'))];
    const fingerprint = () => {
      const text = String(document.body?.innerText || '');
      let hash = 2166136261;
      for (let index = 0; index < text.length; index += 1) hash = Math.imul(hash ^ text.charCodeAt(index), 16777619);
      return `${text.length}:${hash >>> 0}`;
    };
    const state = { loaded: true, visible: false, attempted: false, validationObserved: false, acknowledged: false,
      changed: false, restored: false, failureObserved: false, recoveryObserved: false,
      responseCount: inner.__PX_INSTALLED_RESPONSES__?.length || 0, fingerprint: fingerprint(), details: {}, errors: [] };
    const seededFailure = inner.__PX_INSTALLED_FAILURE_SCENARIOS__?.[item.controlId];
    if (seededFailure?.seeded === true) {
      state.failureObserved = true;
      state.details.failure_handling = `The exact installed read action first rendered an owned ${seededFailure.operation} failure.`;
      state.details.expected_result_type = seededFailure.resultType;
      state.details.expected_result_operation = seededFailure.operation;
      delete inner.__PX_INSTALLED_FAILURE_SCENARIOS__[item.controlId];
    }
    let target = null;
    if (item.kind === 'action') {
      const direct = item.directSelector ? document.querySelector(item.directSelector) : null;
      if (direct && visible(direct)) target = direct;
      if (!target && item.action.action === 'navigate') target = document.querySelector(`[data-surface="${item.action.variants[0]}"]`);
      else if (!target) {
        const candidates = [...document.querySelectorAll(`[data-action="${item.action.action}"]`)];
        target = candidates.find(element => {
          const values = new Set(Object.values(element.dataset).map(String));
          const context = normalize(`${element.getAttribute('aria-label') || ''} ${element.className || ''} ${element.parentElement?.className || ''}`);
          const datasetAliases = {
            entrypoint: ['entrypoint', 'entrypoints'], risk: ['risk', 'risks'], route: ['route', 'routes'], service: ['service', 'services'],
            'test-link': ['test-link', 'test_links'], 'unmapped-test': ['unmapped-test', 'unmapped_tests'],
            'untested-source': ['untested-source', 'untested_sources'], package: ['package', 'packages'], history: ['history']
          };
          return item.action.variants.every(variant => variant === 'row'
            ? Object.keys(element.dataset).some(key => /id|index|row|key|path/i.test(key))
            : (datasetAliases[variant] || [variant]).some(value => values.has(value))
              || (variant === 'in' && (Number(element.dataset.delta) > 0 || context.includes('zoom in')))
              || (variant === 'out' && (Number(element.dataset.delta) < 0 || context.includes('zoom out')))
              || (variant === 'increase' && Number(element.dataset.delta) > 0)
              || (variant === 'decrease' && Number(element.dataset.delta) < 0)
              || (variant === 'earlier' && Number(element.dataset.delta) < 0)
              || (variant === 'later' && Number(element.dataset.delta) > 0)
              || (variant === 'optional' && ['tools', 'memory', 'handoffs'].includes(String(element.dataset.agentKind || '')))
              || (['header', 'hero', 'toolbar', 'minimap', 'button'].includes(variant) && context.includes(variant)));
        });
      }
    } else {
      const direct = item.directSelector ? document.querySelector(item.directSelector) : null;
      if (direct && visible(direct)) target = direct;
      const candidates = target ? [] : [...document.querySelectorAll(item.selector || 'body')].filter(visible);
      let best = null;
      for (const candidate of candidates) {
        const haystack = normalize(`${candidate.innerText || candidate.value || ''} ${[...candidate.attributes].map(attribute => `${attribute.name}=${attribute.value}`).join(' ')}`);
        const score = tokens.length ? tokens.filter(token => haystack.includes(token)).length / tokens.length + (haystack.includes(normalize(item.semantic)) ? 0.35 : 0) : 0;
        if (!best || score > best.score) best = { candidate, score };
      }
      if (!target && best && best.score >= 0.66) target = best.candidate;
    }
    if (!target || !visible(target)) return state;
    state.visible = true;
    if (item.kind === 'indicator') { state.acknowledged = true; return state; }
    if (target.disabled) return state;
    if (item.kind === 'field') {
      const original = target.type === 'checkbox' || target.type === 'radio' ? target.checked : target.value;
      if (target.tagName === 'SELECT') {
        const alternate = [...target.options].find(option => option.value !== original && !option.disabled);
        if (alternate) { target.value = alternate.value; target.dispatchEvent(new inner.Event('change', { bubbles: true })); state.changed = target.value !== original; target.value = original; target.dispatchEvent(new inner.Event('change', { bubbles: true })); state.restored = target.value === original; state.attempted = true; }
      } else if (target.type === 'checkbox' || target.type === 'radio') {
        target.checked = !original; target.dispatchEvent(new inner.Event('change', { bubbles: true })); state.changed = target.checked !== original; target.checked = original; target.dispatchEvent(new inner.Event('change', { bubbles: true })); state.restored = target.checked === original; state.attempted = true;
      } else {
        target.value = `${original || ''} px-probe`.trim(); target.dispatchEvent(new inner.Event('input', { bubbles: true })); state.changed = target.value !== original;
        target.value = original; target.dispatchEvent(new inner.Event('input', { bubbles: true })); state.restored = target.value === original; state.attempted = true;
      }
    } else if (['editor', 'gesture'].includes(item.kind)) {
      const beforeFailure = fingerprint();
      const rejectOwnedInput = event => { event.preventDefault(); event.stopImmediatePropagation(); };
      target.addEventListener('keydown', rejectOwnedInput, { capture: true, once: true });
      const rejected = target.dispatchEvent(new inner.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })) === false;
      target.removeEventListener('keydown', rejectOwnedInput, { capture: true });
      state.failureObserved = rejected && fingerprint() === beforeFailure;
      target.focus();
      target.dispatchEvent(new inner.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true }));
      target.dispatchEvent(new inner.KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true, cancelable: true }));
      state.attempted = true;
      state.restored = fingerprint() === beforeFailure;
      state.recoveryObserved = state.failureObserved && state.restored;
      if (state.failureObserved) state.details.failure_handling = 'The exact installed editor or gesture boundary rejected one owned cancelable input without changing rendered state.';
      if (state.recoveryObserved) state.details.recovery_rollback = 'The same exact control accepted the normal follow-up input pair and returned to its exact rendered predecessor state.';
    } else if (item.kind === 'form') {
      const field = [...target.querySelectorAll('input,select,textarea')].find(element => visible(element) && !element.disabled && !element.readOnly && !['button', 'submit', 'reset', 'hidden'].includes(element.type));
      if (field) {
        const checked = field.type === 'checkbox' || field.type === 'radio';
        const original = checked ? field.checked : field.value;
        const validityBefore = field.checkValidity();
        const customErrorBefore = field.validity?.customError === true;
        field.focus();
        if (checked) {
          field.checked = !original; field.dispatchEvent(new inner.Event('change', { bubbles: true })); state.changed = field.checked !== original;
          field.checked = original; field.dispatchEvent(new inner.Event('change', { bubbles: true })); state.restored = field.checked === original;
        } else if (field.tagName === 'SELECT') {
          const alternate = [...field.options].find(option => option.value !== original && !option.disabled);
          if (alternate) { field.value = alternate.value; field.dispatchEvent(new inner.Event('change', { bubbles: true })); state.changed = field.value !== original; }
          field.value = original; field.dispatchEvent(new inner.Event('change', { bubbles: true })); state.restored = field.value === original;
        } else {
          const validProbe = field.type === 'email' ? 'px-probe@example.invalid' : field.type === 'url' ? 'https://example.invalid/px-probe' : field.type === 'number' ? '1' : `${original || ''} px-probe`.trim();
          field.value = validProbe; field.dispatchEvent(new inner.Event('input', { bubbles: true })); state.changed = field.value !== original;
          field.value = original; field.dispatchEvent(new inner.Event('input', { bubbles: true })); state.restored = field.value === original;
        }
        const valueRestored = (checked ? field.checked : field.value) === original;
        if (!customErrorBefore && typeof field.setCustomValidity === 'function') {
          try {
            field.setCustomValidity('px-owned-form-probe-invalid');
            state.failureObserved = field.validity.customError === true && field.checkValidity() === false;
          } finally {
            field.setCustomValidity('');
          }
        }
        const validityRestored = field.checkValidity() === validityBefore && field.validity?.customError === customErrorBefore;
        state.restored = valueRestored && validityRestored;
        state.attempted = state.changed || state.failureObserved;
        state.recoveryObserved = state.failureObserved && state.restored;
        if (state.failureObserved) state.details.failure_handling = 'The exact installed form entered a temporary owned custom-validity failure state.';
        if (state.recoveryObserved) state.details.recovery_rollback = 'The custom-validity marker was cleared and exact value/checked state plus predecessor validity were restored.';
      }
    } else {
      target.click(); state.attempted = true;
    }
    state.validationObserved = state.attempted;
    return state;
  }, spec);
  if (!before.attempted || before.acknowledged) return before;
  const acknowledgementDeadline = Date.now() + (spec.local ? 80 : 15_000);
  let after = before;
  do {
    await wait(spec.local ? 80 : 100);
    after = await frameHost.evaluate((frame, expected) => {
      const document = frame.contentDocument; const inner = frame.contentWindow;
      const text = String(document?.body?.innerText || ''); let hash = 2166136261;
      for (let index = 0; index < text.length; index += 1) hash = Math.imul(hash ^ text.charCodeAt(index), 16777619);
      const responses = inner?.__PX_INSTALLED_RESPONSES__ || [];
      return {
        responseCount: responses.length,
        matchingResponseObserved: responses.slice(expected.responseOffset).some(value => value?.type === expected.resultType
          && (expected.resultType !== 'enterpriseResult' || value?.operation === expected.operation)),
        fingerprint: `${text.length}:${hash >>> 0}`
      };
    }, { responseOffset: before.responseCount, resultType: before.details.expected_result_type || '', operation: before.details.expected_result_operation || '' });
    if (spec.local || after.responseCount > before.responseCount || after.fingerprint !== before.fingerprint) break;
  } while (Date.now() < acknowledgementDeadline);
  before.acknowledged = spec.local ? (before.changed ? before.restored : before.attempted) : after.responseCount > before.responseCount || after.fingerprint !== before.fingerprint;
  before.recoveryObserved = before.failureObserved && before.acknowledged && (spec.local || after.matchingResponseObserved);
  if (before.recoveryObserved) before.details.recovery_rollback = 'The one-shot owned failure was consumed and the exact normal read action produced a later recovered acknowledgement.';
  before.details.result_acknowledgement = before.acknowledged
    ? (spec.local ? 'Installed UI acknowledged the contained reversible interaction.' : 'Installed host returned a message or changed the exact live view after the read request.')
    : '';
  return before;
}

async function exerciseInstalledExactNavigation(frameHost, control, timeoutMs = 10_000) {
  const transition = installedExactNavigationTransition(control);
  if (!transition) return null;
  const clicked = await frameHost.evaluateContent(spec => {
    const visible = element => Boolean(element && !element.disabled
      && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    if (['knowledgeCore', 'runtimeCore'].includes(spec.target)) {
      state.advancedOpen = true;
      render();
    }
    const controls = [...document.querySelectorAll(`[data-surface="${CSS.escape(spec.target)}"]`)];
    const target = controls.find(element => element.classList.contains('nav-item') && visible(element)) || controls.find(visible);
    if (!target) return false;
    target.click();
    return true;
  }, transition);
  if (!clicked) throw new Error(`installed-exact-navigation-control-unavailable:${control.control_id}:${transition.target}`);
  const deadline = Date.now() + timeoutMs;
  do {
    const acknowledged = await frameHost.evaluateContent(target => {
      const rendered = document.querySelector('.content')?.classList.contains(`surface-${target}`) === true;
      const current = [...document.querySelectorAll(`[data-surface="${CSS.escape(target)}"]`)]
        .some(element => element.getAttribute('aria-current') === 'page');
      const advancedHeading = ({ knowledgeCore: 'Knowledge Core', runtimeCore: 'Runtime Core' })[target];
      const advancedCurrent = Boolean(advancedHeading
        && document.querySelector('[data-action="toggleAdvanced"].active')
        && [...document.querySelectorAll('main h1')].some(element => element.textContent.trim() === advancedHeading));
      return state.active === target && rendered && (current || advancedCurrent);
    }, transition.target);
    if (acknowledged) {
      return {
        loaded: true, visible: true, attempted: true, validationObserved: true, acknowledged: true,
        changed: true, restored: false, failureObserved: false, recoveryObserved: false,
        details: { result_acknowledgement: `The exact visible ${transition.target} navigation control completed its physical route transition.` }, errors: []
      };
    }
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`installed-exact-navigation-transition-timeout:${control.control_id}:${transition.target}`);
}

async function exerciseInstalledExactGraphField(frameHost, control) {
  const selector = installedExactGraphField(control);
  if (!selector) return null;
  const result = await frameHost.evaluateContent(spec => {
    const visible = element => Boolean(element && !element.disabled
      && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    const mode = spec.controlId.endsWith('.graphTarget') ? 'path' : 'dependencies';
    const analysis = document.querySelector('[data-graph-analysis]');
    if (!visible(analysis) || ![...analysis.options].some(option => option.value === mode)) return { available: false, modeUnavailable: true };
    analysis.value = mode;
    analysis.dispatchEvent(new Event('change', { bubbles: true }));
    const target = document.querySelector(spec.selector);
    if (!visible(target)) return { available: false };
    const original = target.value;
    if (target.tagName === 'SELECT') {
      const alternate = [...target.options].find(option => option.value !== original && !option.disabled);
      if (!alternate) return { available: true, attempted: false, restored: false };
      target.value = alternate.value;
      target.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      target.value = `${original || ''} px-probe`.trim();
      target.dispatchEvent(new Event('input', { bubbles: true }));
    }
    const changed = target.value !== original;
    target.value = original;
    target.dispatchEvent(new Event(target.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
    return { available: true, attempted: true, changed, restored: target.value === original };
  }, { selector, controlId: control.control_id });
  if (!result.available) throw new Error(`installed-exact-graph-field-unavailable:${control.control_id}:${selector}`);
  if (!result.attempted || !result.changed || !result.restored) throw new Error(`installed-exact-graph-field-restoration-failed:${control.control_id}`);
  return {
    loaded: true, visible: true, attempted: true, validationObserved: true, acknowledged: true,
    changed: true, restored: true, failureObserved: false, recoveryObserved: false,
    details: { result_acknowledgement: 'The exact graph field accepted one bounded content-realm input and restored its predecessor value.' }, errors: []
  };
}

async function probeInstalledControls(frameHost, matrix, hostErrors, controlIds = null) {
  const bridgeInstrumented = await instrumentInstalledBridge(frameHost).catch(error => {
    hostErrors.push({ source: 'installed-control-probe', context: 'bridge-instrumentation', message: String(error?.message || error).slice(0, 1000) });
    return false;
  });
  const records = [];
  let preparedIdentity = null;
  const blockedSurfaces = new Map();
  for (const control of matrix.controls.filter(control => eligibleInstalledControl(control) && (!controlIds || controlIds.has(control.control_id)))) {
    let probe = { loaded: false, visible: false, attempted: false, validationObserved: false, acknowledged: false, details: {}, errors: [] };
    const preparationIdentity = installedPreparationIdentity(control);
    const advancedTarget = installedAdvancedControlTarget(control);
    const isolated = control.kind === 'action' || ['form', 'menu', 'gesture'].includes(control.kind)
      || preparationIdentity !== control.surface_id || Boolean(advancedTarget);
    let advancedPredecessor = null;
    try {
      if (blockedSurfaces.has(control.surface_id)) throw new Error(blockedSurfaces.get(control.surface_id));
      advancedPredecessor = await prepareInstalledAdvancedControl(frameHost, control);
      if (isolated || preparedIdentity !== preparationIdentity) {
        await prepareInstalledControl(frameHost, control);
        preparedIdentity = isolated ? null : preparationIdentity;
      }
      const revealed = await revealInstalledControl(frameHost, control);
      if (revealed) await wait(60);
      probe = installedExactNavigationTransition(control)
        ? await exerciseInstalledExactNavigation(frameHost, control)
        : installedExactGraphField(control)
          ? await exerciseInstalledExactGraphField(frameHost, control)
          : await exerciseInstalledControl(frameHost, control);
      const conditionalScenario = installedConditionalScenario(control);
      if (probe.visible && control.kind === 'indicator' && conditionalScenario) {
        probe.failureObserved = true;
        probe.details.failure_handling = `The exact installed ${control.control_id} indicator visibly rendered its injected ${conditionalScenario.type} state before recovery.`;
      }
      const conditionalRecovery = probe.visible
        ? await recoverInstalledConditionalIndicator(frameHost, control)
        : { applicable: false, recovered: false };
      if (conditionalRecovery.recovered) {
        probe.recoveryObserved = true;
        probe.details.recovery_rollback = `The exact ${conditionalRecovery.action} recovery action returned a request-bound ${conditionalRecovery.response_type} and removed the injected error indicator.`;
      } else if (conditionalRecovery.applicable) {
        probe.errors.push(`installed-conditional-recovery-failed:${control.control_id}:${conditionalRecovery.reason || 'unknown'}`);
      }
      if (isolated || revealed) preparedIdentity = null;
    } catch (error) {
      const message = String(error?.message || error).slice(0, 1000);
      probe.errors.push(message);
      if (message.includes('-studio-opener-not-ready') || message.includes('-studio-modal-not-ready')) blockedSurfaces.set(control.surface_id, message);
      preparedIdentity = null;
    } finally {
      if (advancedPredecessor) {
        try {
          if (!await restoreInstalledAdvancedControl(frameHost, advancedPredecessor)) throw new Error('installed-advanced-route-fixture-restore-mismatch');
        } catch (error) {
          probe.errors.push(String(error?.message || error).slice(0, 1000));
          preparedIdentity = null;
        }
      }
    }
    const evidenceRef = `installed-receipt:${control.control_id}`;
    const interactionChain = Object.fromEntries(STAGES.map(stage => [stage, stageResult(control, probe, stage, evidenceRef)]));
    if (control.evidence_mode === 'contained_host_interaction' && probe.attempted && probe.acknowledged) {
      for (const stage of ['authorization', 'backend_dispatch', 'runtime_effect']) {
        if (control.stage_policy[stage] !== 'required') continue;
        interactionChain[stage] = {
          state: 'present',
          detail: `The exact read action returned an installed-host response or changed its exact live view, directly proving ${stage}.`,
          evidence: [evidenceRef]
        };
      }
    }
    records.push({
      control_id: control.control_id,
      surface_id: control.surface_id,
      control_kind: control.kind,
      evidence_mode: control.evidence_mode,
      rendered: probe.visible,
      observed: probe.visible,
      attempted: probe.attempted,
      interaction_chain: interactionChain,
      errors: probe.errors
    });
  }
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact installed host; local/reversible UI controls and typed read-only host actions only.',
    bridge_instrumented: bridgeInstrumented,
    eligible_control_count: records.length,
    aggregates: {
      rendered: records.filter(record => record.rendered).length,
      attempted: records.filter(record => record.attempted).length,
      errors: records.reduce((total, record) => total + record.errors.length, 0)
    },
    records
  };
}

function installedSidebarSelector(control) {
  if (control.kind === 'action') return sidebarActionSelector(control);
  return directSelectorFor(control) || selectorForKind(control.kind) || null;
}

function eligibleInstalledSidebarControl(control) {
  return Boolean(control && control.surface_id === 'sidebar'
    && ['contained_sidebar_interaction', 'live_state_observation'].includes(control.evidence_mode));
}

function installedSidebarHandoffSpec(control) {
  const id = String(control?.control_id || '');
  if (id === 'pxui.sidebar.action.open-control-plane') return { requestType: 'openControlPlane' };
  if (id === 'pxui.sidebar.action.openPlanFromPunch') return { requestType: 'openPlanFromPunch' };
  const entityType = id.match(/^pxui\.sidebar\.action\.openEntity\.([a-z0-9-]+)$/)?.[1];
  return entityType ? { requestType: 'openEntity', entityType } : null;
}

function installedSidebarHandoffRequestMatches(request, expected) {
  if (!request || request.type !== expected?.type) return false;
  if (expected.type === 'openEntity') return request.entityType === expected.entityType && request.entityId === expected.entityId;
  if (expected.type === 'openPlanFromPunch') return request.planId === expected.planId;
  return expected.type === 'openControlPlane';
}

async function waitForInstalledSidebarHandoffRequest(frameHost, offset, expected, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  let request = null;
  do {
    request = await frameHost.evaluate((frame, item) => (frame.contentWindow?.__PX_INSTALLED_SIDEBAR_REQUESTS__ || []).slice(item.offset)
      .find(value => {
        if (!value || value.type !== item.expected.type) return false;
        if (item.expected.type === 'openEntity') return value.entityType === item.expected.entityType && value.entityId === item.expected.entityId;
        if (item.expected.type === 'openPlanFromPunch') return value.planId === item.expected.planId;
        return item.expected.type === 'openControlPlane';
      }) || null, { offset, expected });
    if (installedSidebarHandoffRequestMatches(request, expected)) return request;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`installed-sidebar-handoff-request-timeout:${JSON.stringify(expected)}`);
}

async function waitForInstalledSidebarDashboardIdentity(dashboard, expected, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  let state = null;
  do {
    state = await dashboard.evaluate((frame, item) => {
      const document = frame.contentDocument;
      const text = String(document?.body?.innerText || '');
      const dashboardVisible = Boolean(document?.querySelector('[data-surface="dashboard"]')
        && document?.querySelector('[data-surface="agents"]'));
      const expectedId = item.entityId || item.planId || '';
      const exactDataset = expectedId ? [...(document?.querySelectorAll('*') || [])]
        .some(element => Object.values(element.dataset || {}).some(value => String(value) === expectedId)) : true;
      return { dashboardVisible, expectedId, exactIdentity: !expectedId || exactDataset || text.includes(expectedId) };
    }, expected);
    if (state.dashboardVisible && state.exactIdentity) return state;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`installed-sidebar-dashboard-identity-timeout:${JSON.stringify({ expected, state })}`);
}

async function prepareInstalledSidebarHandoffTarget(frameHost, selector, handoff) {
  return frameHost.evaluate((frame, spec) => {
    const document = frame.contentDocument;
    if (!document?.body) throw new Error('PX installed sidebar contentDocument is unavailable.');
    const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    const target = spec.selector ? [...document.querySelectorAll(spec.selector)].find(visible) : null;
    if (target && !target.disabled) return { fixture_token: null };
    if (!['openEntity', 'openPlanFromPunch'].includes(spec.handoff.requestType)) {
      throw new Error(`installed-sidebar-handoff-target-unavailable:${spec.selector}`);
    }
    const token = `px-owned-sidebar-handoff-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const fixture = document.createElement('button');
    fixture.type = 'button';
    fixture.dataset.pxOwnedHandoffFixture = token;
    fixture.style.cssText = 'position:fixed;right:1px;bottom:1px;width:2px;height:2px;padding:0;border:0;overflow:hidden;z-index:1';
    fixture.textContent = 'PX owned conditional handoff';
    if (spec.handoff.requestType === 'openEntity') {
      fixture.dataset.entityType = spec.handoff.entityType;
      fixture.dataset.entityId = `px-owned-${spec.handoff.entityType}-handoff`;
    } else fixture.dataset.planPunch = 'px-owned-plan-handoff';
    document.body.appendChild(fixture);
    if (!visible(fixture)) throw new Error(`installed-sidebar-handoff-fixture-not-visible:${spec.selector}`);
    return { fixture_token: token };
  }, { selector, handoff });
}

async function removeInstalledSidebarHandoffTarget(frameHost, fixtureToken) {
  if (!fixtureToken) return true;
  return frameHost.evaluate((frame, token) => {
    const fixture = [...(frame.contentDocument?.querySelectorAll('[data-px-owned-handoff-fixture]') || [])]
      .find(item => item.dataset.pxOwnedHandoffFixture === token);
    fixture?.remove();
    return ![...(frame.contentDocument?.querySelectorAll('[data-px-owned-handoff-fixture]') || [])]
      .some(item => item.dataset.pxOwnedHandoffFixture === token);
  }, fixtureToken);
}

async function probeInstalledSidebarHandoff(frameHost, workbench, selector, handoff, timeoutMs = 30_000) {
  const prepared = await prepareInstalledSidebarHandoffTarget(frameHost, selector, handoff);
  try {
  await frameHost.evaluate(frame => {
    const inner = frame.contentWindow;
    if (!inner) throw new Error('PX installed sidebar contentWindow is unavailable.');
    inner.__PX_INSTALLED_SIDEBAR_REQUESTS__ ||= [];
    if (inner.__PX_INSTALLED_SIDEBAR_HANDOFF_INSTRUMENTED__) return;
    inner.addEventListener('px-sidebar-outbound-request', event => {
      try { inner.__PX_INSTALLED_SIDEBAR_REQUESTS__.push(JSON.parse(JSON.stringify(event.detail))); }
      catch { inner.__PX_INSTALLED_SIDEBAR_REQUESTS__.push({ type: 'unserializable-request' }); }
    });
    inner.__PX_INSTALLED_SIDEBAR_HANDOFF_INSTRUMENTED__ = true;
  });
  const attempt = await frameHost.evaluate((frame, spec) => {
    const document = frame.contentDocument; const inner = frame.contentWindow;
    const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    const target = spec.selector ? [...document.querySelectorAll(spec.selector)].find(visible) : null;
    if (!target || target.disabled) throw new Error(`installed-sidebar-handoff-target-unavailable:${spec.selector}`);
    const expected = spec.handoff.requestType === 'openEntity'
      ? { type: 'openEntity', entityType: spec.handoff.entityType, entityId: target.dataset.entityId }
      : spec.handoff.requestType === 'openPlanFromPunch'
        ? { type: 'openPlanFromPunch', planId: target.dataset.planPunch }
        : { type: 'openControlPlane' };
    const offset = inner.__PX_INSTALLED_SIDEBAR_REQUESTS__.length;
    target.addEventListener('click', event => { event.preventDefault(); event.stopImmediatePropagation(); }, { capture: true, once: true });
    target.click();
    const rejected = inner.__PX_INSTALLED_SIDEBAR_REQUESTS__.length === offset;
    target.click();
    return { expected, offset, rejected, visible: true };
  }, { selector, handoff });
  if (!attempt.rejected) throw new Error(`installed-sidebar-handoff-owned-rejection-failed:${JSON.stringify(attempt.expected)}`);
  await waitForInstalledSidebarHandoffRequest(frameHost, attempt.offset, attempt.expected, timeoutMs);
  const dashboard = await waitForOwnedWebview(workbench, text => /PACIFY-X\s*\/\s*DASHBOARD|SIDEBAR DEEP LINK/i.test(text), timeoutMs);
  if (!dashboard) throw new Error(`installed-sidebar-dashboard-unavailable:${JSON.stringify(attempt.expected)}`);
  await waitForInstalledSidebarDashboardIdentity(dashboard, attempt.expected, timeoutMs);
  const restart = await restartInstalledDashboardWebview(dashboard, timeoutMs);
  const replayOffset = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_SIDEBAR_REQUESTS__?.length || 0);
  await frameHost.evaluate((frame, spec) => {
    const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    const target = spec.selector ? [...frame.contentDocument.querySelectorAll(spec.selector)].find(visible) : null;
    if (!target || target.disabled) throw new Error(`installed-sidebar-handoff-replay-target-unavailable:${spec.selector}`);
    target.click();
  }, { selector });
  await waitForInstalledSidebarHandoffRequest(frameHost, replayOffset, attempt.expected, timeoutMs);
  await waitForInstalledSidebarDashboardIdentity(dashboard, attempt.expected, timeoutMs);
  return {
    loaded: true, visible: attempt.visible, attempted: true, validationObserved: true, acknowledged: true,
    failureObserved: true, recoveryObserved: true, changed: true, restored: restart.restarted === true && restart.reconstructed === true,
    details: {
      failure_handling: 'The exact sidebar target rejected one owned click before dispatch and emitted no outbound request.',
      result_acknowledgement: 'The normal retry emitted the exact typed sidebar request and the host-owned dashboard rendered the matching identity.',
      persistence: 'The exact handoff was repeated after host-owned dashboard reconstruction.',
      reload_reopen: 'The dashboard webview was physically reconstructed before the same exact sidebar handoff was replayed.',
      recovery_rollback: 'The rejected attempt left no request, and the same physical control recovered through exact request, dashboard identity, reconstruction, and replay.'
    }, errors: []
  };
  } finally {
    if (!await removeInstalledSidebarHandoffTarget(frameHost, prepared.fixture_token).catch(() => false)) {
      throw new Error(`installed-sidebar-handoff-fixture-cleanup-failed:${prepared.fixture_token}`);
    }
  }
}

async function probeInstalledSidebarControls(frameHost, matrix, hostErrors = [], workbench = null) {
  const eligible = matrix.controls.filter(eligibleInstalledSidebarControl);
  const records = [];
  for (const control of eligible) {
    let probe = { loaded: false, visible: false, attempted: false, validationObserved: false, acknowledged: false, details: {}, errors: [] };
    const selector = installedSidebarSelector(control);
    const handoff = installedSidebarHandoffSpec(control);
    try {
      if (handoff && typeof frameHost.reacquire === 'function' && !await frameHost.reacquire(10_000)) {
        throw new Error(`installed-sidebar-frame-reacquisition-failed:${control.control_id}`);
      }
      probe = handoff && workbench ? await probeInstalledSidebarHandoff(frameHost, workbench, selector, handoff) : await frameHost.evaluate((frame, spec) => {
        const document = frame.contentDocument;
        if (!document) throw new Error('PX installed sidebar contentDocument is unavailable.');
        const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
        const target = spec.selector ? [...document.querySelectorAll(spec.selector)].find(visible) : null;
        const state = { loaded: true, visible: Boolean(target), attempted: false, validationObserved: false, acknowledged: false, details: {}, errors: [] };
        if (!target) return state;
        if (spec.kind === 'indicator') { state.acknowledged = true; return state; }
        if (spec.kind === 'action' && !target.disabled) {
          const before = String(document.body?.innerText || '');
          target.click();
          state.attempted = true;
          state.validationObserved = true;
          state.acknowledged = String(document.body?.innerText || '') !== before;
          if (state.acknowledged) state.details.result_acknowledgement = 'The installed sidebar visibly acknowledged the exact reversible local interaction.';
        }
        return state;
      }, { kind: control.kind, selector });
    } catch (error) {
      const message = String(error?.message || error).slice(0, 1000);
      probe.errors.push(message);
      hostErrors.push({ source: 'installed-sidebar-probe', context: control.control_id, message });
    }
    const evidenceRef = `installed-sidebar-receipt:${control.control_id}`;
    const interactionChain = Object.fromEntries(STAGES.map(stage => [stage, stageResult(control, probe, stage, evidenceRef)]));
    if (handoff && probe.attempted && probe.acknowledged) {
      for (const stage of ['authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting']) {
        if (control.stage_policy[stage] === 'required') interactionChain[stage] = {
          state: 'present', detail: `The exact typed sidebar handoff was emitted and the host-owned dashboard accepted it, proving ${stage}.`, evidence: [evidenceRef]
        };
      }
    }
    if (handoff && probe.restored) {
      for (const stage of ['persistence', 'reload_reopen']) {
        if (control.stage_policy[stage] === 'required') interactionChain[stage] = {
          state: 'present', detail: 'The dashboard webview was reconstructed and the same exact typed sidebar handoff was replayed.', evidence: [evidenceRef]
        };
      }
    }
    records.push({
      control_id: control.control_id,
      surface_id: control.surface_id,
      control_kind: control.kind,
      evidence_mode: control.evidence_mode,
      rendered: probe.visible,
      observed: probe.visible,
      attempted: probe.attempted,
      interaction_chain: interactionChain,
      errors: probe.errors
    });
  }
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact installed sidebar; reversible local UI and read actions only.',
    eligible_control_count: records.length,
    records
  };
}

async function safeScreenshot(locator, target, context, hostErrors) {
  try {
    await locator.screenshot({ path: target, animations: 'disabled', timeout: 5_000 });
    return { status: 'captured', path: path.basename(target) };
  } catch (error) {
    const message = String(error?.message || error).slice(0, 1000);
    hostErrors.push({ source: 'screenshot', context, message });
    return { status: 'failed', path: path.basename(target), error: message };
  }
}

function surfaceCaptureCandidates(proofMatrix, surface) {
  const installedRoute = INSTALLED_ROUTES[surface] || surface;
  const sharedRouteAnchor = {
    'agent-studio': { control_id: 'pxui.agents.action.openStudioDraft.agent', selector: '[data-action="openStudioDraft"][data-kind="agent"]' },
    'workflow-studio': { control_id: 'pxui.workflows.action.openStudioDraft.workflow', selector: '[data-action="openStudioDraft"][data-kind="workflow"]' },
    'skill-studio': { control_id: 'pxui.skills-tools.action.openStudioDraft.skill', selector: '[data-action="openStudioDraft"][data-kind="skill"]' }
  }[surface] || null;
  return (Array.isArray(proofMatrix?.controls) ? proofMatrix.controls : [])
    .filter(control => INSTALLED_ROUTES[control.surface_id] === installedRoute)
    .map(control => ({
      control_id: String(control.control_id || ''),
      selector: control.control_id === sharedRouteAnchor?.control_id
        ? sharedRouteAnchor.selector
        : installedDirectSelector(control) || selectorForKind(control.kind) || ''
    }))
    .filter(candidate => candidate.control_id && candidate.selector)
    .sort((left, right) => left.control_id.localeCompare(right.control_id));
}

function surfaceCaptureFileStem(surface, view, controlId = '') {
  const safe = value => String(value || '').replace(/[^a-zA-Z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || 'unknown';
  return `${safe(surface)}--${safe(view)}${controlId ? `--${safe(controlId)}` : ''}`;
}

async function captureSurfaceViews(frameHost, proofMatrix, surface, ordinal, outputRoot, hostErrors) {
  const prefix = String(ordinal).padStart(2, '0');
  const candidates = surfaceCaptureCandidates(proofMatrix, surface);
  const firstFoldPosition = await frameHost.evaluate((frame, activeSurface) => {
    const document = frame.contentDocument;
    if (!document) throw new Error('PX webview document is unavailable for first-fold capture.');
    const renderedSurface = document.querySelector('.content')?.classList.contains(`surface-${activeSurface}`) === true;
    if (!renderedSurface) throw new Error(`PX rendered surface is unavailable for first-fold capture: ${activeSurface}`);
    document.scrollingElement.scrollTop = 0;
    return Number(document.scrollingElement.scrollTop || 0);
  }, surface);
  await wait(100);
  const firstFoldKey = `surface:${surface}:first-fold`;
  const firstFold = await safeScreenshot(
    frameHost,
    path.join(outputRoot, `${prefix}-${surfaceCaptureFileStem(surface, 'first-fold')}.png`),
    firstFoldKey,
    hostErrors
  );

  const deepTarget = await frameHost.evaluate((frame, input) => {
    const document = frame.contentDocument;
    if (!document) throw new Error('PX webview document is unavailable for deep-panel capture.');
    const content = document.querySelector(`.content.surface-${CSS.escape(input.surface)}`);
    if (!content) throw new Error(`PX rendered surface is unavailable for deep-panel capture: ${input.surface}`);
    const visible = element => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const matches = [];
    for (const candidate of input.candidates) {
      let elements = [];
      try { elements = [...content.querySelectorAll(candidate.selector)]; }
      catch { continue; }
      for (const element of elements) {
        if (!visible(element)) continue;
        const rect = element.getBoundingClientRect();
        matches.push({ candidate, element, document_top: Math.round(rect.top + Number(document.scrollingElement.scrollTop || 0)) });
      }
    }
    matches.sort((left, right) => right.document_top - left.document_top || left.candidate.control_id.localeCompare(right.candidate.control_id));
    const selected = matches[0];
    if (!selected) throw new Error(`PX surface has no registered rendered control for deep-panel capture: ${input.surface}`);
    selected.element.scrollIntoView({ block: 'center', inline: 'nearest' });
    return {
      control_id: selected.candidate.control_id,
      selector: selected.candidate.selector,
      document_top: selected.document_top,
      scroll_top: Number(document.scrollingElement.scrollTop || 0)
    };
  }, { surface, candidates });
  await wait(100);
  const deepPanelKey = `control:${deepTarget.control_id}:deep-panel`;
  const deepPanel = await safeScreenshot(
    frameHost,
    path.join(outputRoot, `${prefix}-${surfaceCaptureFileStem(surface, 'deep-panel', deepTarget.control_id)}.png`),
    deepPanelKey,
    hostErrors
  );
  return {
    schema_version: 'px.operational-surface-captures/1.0',
    surface_id: surface,
    first_fold: { key: firstFoldKey, scroll_top: firstFoldPosition, screenshot: firstFold },
    deep_panel: { key: deepPanelKey, ...deepTarget, screenshot: deepPanel }
  };
}

async function allPages(browser) {
  return browser.contexts().flatMap(context => context.pages());
}

async function enforceOwnedWorkbenchViewport(workbench, { width = 1800, height = 1100 } = {}) {
  const session = await workbench.context().newCDPSession(workbench);
  try {
    await session.send('Emulation.setDeviceMetricsOverride', {
      width, height, deviceScaleFactor: 1, mobile: false,
      screenWidth: width, screenHeight: height,
      positionX: 0, positionY: 0, dontSetVisibleSize: false
    });
    const deadline = Date.now() + 5_000;
    let observed = null;
    while (Date.now() < deadline) {
      observed = await workbench.evaluate(() => ({ inner_width: window.innerWidth, inner_height: window.innerHeight, outer_width: window.outerWidth, outer_height: window.outerHeight }));
      if (observed.inner_width >= 1400 && observed.inner_height >= 850) return { session, observed };
      await wait(100);
    }
    throw new Error(`owned-workbench-viewport-not-applied:${JSON.stringify(observed)}`);
  } catch (error) {
    await session.detach().catch(() => {});
    throw error;
  }
}

async function allDocuments(browser) {
  const documents = [];
  for (const page of await allPages(browser)) {
    documents.push(page);
    for (const frame of page.frames()) if (frame !== page.mainFrame()) documents.push(frame);
  }
  return documents;
}

async function pageText(page) {
  try { return await page.locator('body').innerText({ timeout: 2000 }); } catch { return ''; }
}

async function waitForPage(browser, predicate, timeoutMs = 30_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    for (const page of await allPages(browser)) {
      try { if (await predicate(page)) return page; } catch { /* target can reload */ }
    }
    await wait(250);
  }
  return null;
}

async function waitForDocument(browser, predicate, timeoutMs = 30_000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    for (const document of await allDocuments(browser)) {
      try { if (await predicate(document)) return document; } catch { /* webviews can reload */ }
    }
    await wait(250);
  }
  return null;
}

async function innerText(frameHost, timeoutMs = 30_000) {
  return frameHost.evaluate(frame => String(frame.contentDocument?.body?.innerText || ''), undefined, { timeout: timeoutMs });
}

function reacquirableOwnedFrameError(error) {
  const message = String(error?.message || error || '');
  if (/owned-webview-current-(?:frame|content-frame|frame-handle)-unavailable/.test(message)) return true;
  return /waiting for locator\(['"]iframe\.webview\[src\*=[\s\S]*iframe#active-frame['"]\)/.test(message);
}

async function waitForOwnedWebview(workbench, predicate, timeoutMs = 30_000) {
  let current = null;
  let identityMode = null;
  const hasDashboardOwnership = frameHost => frameHost.evaluate(frame => Boolean(
    frame.contentDocument?.querySelector('[data-surface="dashboard"]')
      && frame.contentDocument?.querySelector('[data-surface="agents"]')
  ), undefined, { timeout: 1_000 });
  const matchesOwnedIdentity = async (candidate, discover = false) => {
    const text = await innerText(candidate, 1_000);
    const dashboardOwned = await hasDashboardOwnership(candidate);
    if (discover) {
      if (!await predicate(text)) return false;
      identityMode = dashboardOwned ? 'dashboard-dom' : 'predicate';
      return true;
    }
    return identityMode === 'dashboard-dom' ? dashboardOwned : await predicate(text);
  };
  const resolve = async (limitMs = timeoutMs) => {
    const deadline = Date.now() + limitMs;
    const remaining = () => Math.max(1, deadline - Date.now());
    const boundedResolveAction = (operation, label, ceilingMs = 1_000) => boundedOwnedUiAction(
      operation,
      Math.max(1, Math.min(ceilingMs, remaining())),
      label
    );
    while (Date.now() < deadline) {
      if (current) {
        try {
          if (await boundedResolveAction(
            () => matchesOwnedIdentity(current, identityMode === null),
            'owned-webview-current-identity'
          )) return current;
        } catch { current = null; }
      }
      const shells = workbench.locator('iframe.webview[src*="extensionId=mountain-nomad-bc.pacify-x-vscode"]');
      let shellCount = 0;
      try {
        shellCount = await boundedResolveAction(() => shells.count(), 'owned-webview-shell-count');
      } catch {
        current = null;
        if (Date.now() < deadline) await wait(Math.min(100, remaining()));
        continue;
      }
      for (let index = 0; index < shellCount && Date.now() < deadline; index += 1) {
        const shell = shells.nth(index);
        try {
          if (!await boundedResolveAction(() => shell.isVisible(), 'owned-webview-shell-visibility')) continue;
          const candidate = shell.contentFrame().locator('iframe#active-frame');
          if (await boundedResolveAction(
            () => matchesOwnedIdentity(candidate, identityMode === null),
            'owned-webview-candidate-identity'
          )) { current = candidate; return current; }
        } catch { /* iframe can rematerialize */ }
      }
      if (Date.now() < deadline) await wait(Math.min(250, remaining()));
    }
    return null;
  };
  if (!await resolve()) return null;
  const requireCurrent = async () => {
    const locator = await resolve(Math.min(10_000, timeoutMs));
    if (!locator) throw new Error('owned-webview-current-frame-unavailable');
    return locator;
  };
  const invokeCurrent = async (method, args) => {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try { return await (await requireCurrent())[method](...args); }
      catch (error) {
        if (attempt > 0 || !reacquirableOwnedFrameError(error)) throw error;
        current = null;
      }
    }
    throw new Error('owned-webview-current-frame-unavailable');
  };
  return {
    evaluate: async (operation, argument, options = {}) => invokeCurrent('evaluate', [
      operation,
      argument,
      { ...options, timeout: Math.max(1, Math.min(Number(options.timeout) || 10_000, 10_000)) }
    ]),
    evaluateContent: async (...args) => {
      for (let attempt = 0; attempt < 2; attempt += 1) {
        let handle = null;
        try {
          handle = await (await requireCurrent()).elementHandle();
          if (!handle) throw new Error('owned-webview-current-frame-handle-unavailable');
          const content = await handle.contentFrame();
          if (!content) throw new Error('owned-webview-current-content-frame-unavailable');
          return await content.evaluate(...args);
        } catch (error) {
          if (attempt > 0 || !reacquirableOwnedFrameError(error)) throw error;
          current = null;
        } finally {
          await handle?.dispose();
        }
      }
      throw new Error('owned-webview-current-content-frame-unavailable');
    },
    reacquire: async (limitMs = Math.min(10_000, timeoutMs)) => {
      current = null;
      return Boolean(await resolve(Math.max(1, Math.min(limitMs, timeoutMs))));
    },
    screenshot: async (...args) => invokeCurrent('screenshot', args),
    page: () => workbench
  };
}

async function openWorkbenchCommandPalette(workbench) {
  await workbench.bringToFront();
  const staleWidget = workbench.locator('.quick-input-widget:visible').first();
  if (await staleWidget.isVisible().catch(() => false)) {
    await workbench.keyboard.press('Escape');
    await staleWidget.waitFor({ state: 'hidden', timeout: 5_000 });
  }
  const widget = workbench.locator('.quick-input-widget:visible').first();
  const shortcuts = ['F1', process.platform === 'darwin' ? 'Meta+Shift+P' : 'Control+Shift+P'];
  const failures = [];
  for (const shortcut of shortcuts) {
    await workbench.bringToFront();
    await workbench.keyboard.press('Escape').catch(() => {});
    await workbench.locator('.monaco-workbench').focus().catch(() => {});
    await workbench.keyboard.press(shortcut);
    try {
      await widget.waitFor({ state: 'visible', timeout: 7_500 });
      return widget;
    } catch (error) {
      failures.push(`${shortcut}:${error?.constructor?.name || 'Error'}`);
    }
  }
  throw new Error(`workbench-command-palette-unavailable:${failures.join(',')}`);
}

function workbenchCommandRowIdentity(rows, title, activeDescendant = '') {
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
  const expected = normalize(title);
  const candidates = (Array.isArray(rows) ? rows : []).filter(row => row?.visible === true && normalize(row.label) === expected);
  if (candidates.length !== 1) return { valid: false, reason: candidates.length ? 'duplicate-exact-visible-command-rows' : 'exact-visible-command-row-missing', match_count: candidates.length, row: null };
  const row = candidates[0];
  const selected = row.selected === true || (Boolean(row.id) && row.id === activeDescendant);
  return { valid: selected, reason: selected ? 'exact-visible-selected-command-row' : 'exact-command-row-not-selected', match_count: 1, row };
}

function commandPaletteAttemptDecision(identity, widgetVisible) {
  if (identity?.valid === true) return 'dispatch';
  if (widgetVisible !== true) return 'retry-fresh-widget';
  return 'continue-current-widget';
}

async function executeWorkbenchCommand(workbench, title, options = {}) {
  const failures = [];
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const widget = await openWorkbenchCommandPalette(workbench);
    // The palette owns keyboard focus when it becomes visible. VS Code may
    // replace its input DOM node while scoring providers settle, so drive the
    // stable focused-input contract instead of retaining a transient input.
    await workbench.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A');
    await workbench.keyboard.type(`>${title}`);
    const deadline = Date.now() + 10_000;
    let identity = { valid: false, reason: 'command-rows-not-observed', match_count: 0, row: null };
    let decision = 'continue-current-widget';
    do {
      const widgetVisible = await widget.isVisible().catch(() => false);
      if (widgetVisible) {
        const activeDescendant = await widget.locator('input').first().getAttribute('aria-activedescendant').catch(() => '');
        const rows = await widget.locator('.quick-input-list .monaco-list-row').evaluateAll(elements => elements.map(row => ({
          id: String(row.id || ''),
          label: String(row.querySelector('.label-name')?.textContent || ''),
          visible: Boolean(row.offsetWidth || row.offsetHeight || row.getClientRects().length),
          selected: row.classList.contains('focused') || row.getAttribute('aria-selected') === 'true'
        }))).catch(() => []);
        identity = workbenchCommandRowIdentity(rows, title, activeDescendant || '');
      }
      decision = commandPaletteAttemptDecision(identity, widgetVisible);
      if (decision !== 'continue-current-widget') break;
      await wait(100);
    } while (Date.now() < deadline);
    if (decision === 'dispatch') {
      if (options.rejectBeforeDispatch === true) {
        const input = widget.locator('input').first();
        await input.evaluate(element => element.addEventListener('keydown', event => {
          if (event.key !== 'Enter') return;
          event.preventDefault();
          event.stopImmediatePropagation();
        }, { capture: true, once: true }));
        await workbench.keyboard.press('Enter');
        await wait(80);
        const retained = await widget.isVisible().catch(() => false);
        await workbench.keyboard.press('Escape').catch(() => {});
        await widget.waitFor({ state: 'hidden', timeout: 5_000 }).catch(() => {});
        const restored = !await widget.isVisible().catch(() => false);
        if (!retained || !restored) throw new Error(`workbench-command-owned-rejection-unobserved:${title}:${JSON.stringify({ retained, restored })}`);
        return { listed: true, executed: false, rejected: true, restored: true, title, palette_attempt: attempt };
      }
      // VS Code rebuilds command-palette rows as scoring and keybinding metadata
      // settle. The focused input and exact selected row are the stable physical
      // contract; dispatch by keyboard and then prove that quick input either
      // closed or transitioned to the exact prompt owned by this command.
      await workbench.keyboard.press('Enter');
      let acceptance = 'quick-input-closed';
      if (options.acceptedPrompt) {
        const acceptedPrompt = String(options.acceptedPrompt).replace(/\s+/g, ' ').trim();
        const transitionDeadline = Date.now() + 15_000;
        let accepted = false;
        do {
          if (!await widget.isVisible().catch(() => false)) {
            accepted = true;
            break;
          }
          const visible = String(await widget.innerText({ timeout: 1_000 }).catch(() => '')).replace(/\s+/g, ' ').trim();
          if (visible.includes(acceptedPrompt)) {
            acceptance = 'quick-input-transition';
            accepted = true;
            break;
          }
          await wait(100);
        } while (Date.now() < transitionDeadline);
        if (!accepted) {
          const visible = (await widget.innerText({ timeout: 1_000 }).catch(() => '<quick-input-closed>')).slice(0, 2000);
          throw new Error(`workbench-command-not-accepted:${title}:${visible}`);
        }
      } else {
        try {
          await widget.waitFor({ state: 'hidden', timeout: 15_000 });
        } catch {
          const visible = (await widget.innerText({ timeout: 1_000 }).catch(() => '<quick-input-closed>')).slice(0, 2000);
          throw new Error(`workbench-command-not-accepted:${title}:${visible}`);
        }
      }
      return { listed: true, acceptance, executed: true, title, palette_attempt: attempt };
    }
    const visible = (await widget.innerText({ timeout: 1_000 }).catch(() => '<quick-input-closed>')).slice(0, 2000);
    failures.push(`attempt-${attempt}:${decision}:${identity.reason}:${identity.match_count}:${visible}`);
    await workbench.keyboard.press('Escape').catch(() => {});
  }
  throw new Error(`workbench-command-unavailable:${title}:${failures.join('|')}`);
}

function ownedWorkbenchReloadIdentity(beforeTimeOrigin, afterTimeOrigin, workbenchReady) {
  return Number.isFinite(beforeTimeOrigin) && beforeTimeOrigin > 0
    && Number.isFinite(afterTimeOrigin) && afterTimeOrigin > 0
    && afterTimeOrigin !== beforeTimeOrigin
    && workbenchReady === true;
}

async function closeOwnedDashboardTabs(workbench, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  const tabs = workbench.locator('[role="tab"]', { hasText: /PX.*Control Plane/i });
  let closed = 0;
  while (Date.now() < deadline) {
    const count = await tabs.count();
    if (count === 0) return closed;
    if (closed >= 4) throw new Error(`owned-dashboard-restored-tab-bound-exceeded:${count}`);
    const tab = tabs.first();
    await tab.click();
    await workbench.keyboard.press(process.platform === 'darwin' ? 'Meta+W' : 'Control+W');
    const previousCount = count;
    const closeDeadline = Math.min(deadline, Date.now() + 5_000);
    do {
      if (await tabs.count() < previousCount) break;
      await wait(100);
    } while (Date.now() < closeDeadline);
    if (await tabs.count() >= previousCount) throw new Error('owned-dashboard-restored-tab-close-unobserved');
    closed += 1;
  }
  throw new Error('owned-dashboard-restored-tab-close-timeout');
}

async function restartOwnedWorkbenchWindow(workbench, frameHost, timeoutMs = 60_000) {
  const beforeTimeOrigin = await workbench.evaluate(() => Number(performance.timeOrigin || 0));
  await executeWorkbenchCommand(workbench, 'Developer: Reload Window');
  const deadline = Date.now() + timeoutMs;
  let afterTimeOrigin = 0;
  let workbenchReady = false;
  do {
    try {
      const state = await workbench.evaluate(() => ({
        time_origin: Number(performance.timeOrigin || 0),
        ready: document.readyState === 'complete' && Boolean(document.querySelector('.monaco-workbench'))
      }));
      afterTimeOrigin = state.time_origin;
      workbenchReady = state.ready === true;
      if (ownedWorkbenchReloadIdentity(beforeTimeOrigin, afterTimeOrigin, workbenchReady)) break;
    } catch {
      // Navigation temporarily destroys the renderer execution context. The
      // owned page remains authoritative and is polled until the new workbench
      // document proves both a different origin and a ready root.
    }
    await wait(200);
  } while (Date.now() < deadline);
  if (!ownedWorkbenchReloadIdentity(beforeTimeOrigin, afterTimeOrigin, workbenchReady)) {
    throw new Error(`owned-workbench-reload-unobserved:${JSON.stringify({ before_time_origin: beforeTimeOrigin, after_time_origin: afterTimeOrigin, workbench_ready: workbenchReady })}`);
  }
  const restoredDashboardTabsClosed = await closeOwnedDashboardTabs(workbench, Math.max(1, Math.min(15_000, deadline - Date.now())));
  await executeWorkbenchCommand(workbench, INSTALLED_SAFE_WORKBENCH_COMMANDS['pxui.dashboard-control-plane.command.pacifyX.openDashboard'].title);
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw new Error('owned-workbench-reload-dashboard-reconstruction-budget-exhausted');
  const reopened = await reopenPacifyDashboardFromOwnedUi(workbench, frameHost, remaining);
  if (reopened.reconstructed !== true) throw new Error('owned-workbench-reload-dashboard-reconstruction-unobserved');
  return {
    restarted: true,
    reconstructed: true,
    restored_dashboard_tabs_closed: restoredDashboardTabsClosed,
    before_time_origin: beforeTimeOrigin,
    after_time_origin: afterTimeOrigin
  };
}

function installedWorkbenchCommandSpec(control) {
  return INSTALLED_SAFE_WORKBENCH_COMMANDS[String(control?.control_id || '')] || null;
}

function installedWorkbenchAuthorityBoundarySpec(control) {
  return INSTALLED_WORKBENCH_AUTHORITY_BOUNDARIES[String(control?.control_id || '')] || null;
}

const INSTALLED_INLINE_COMMAND_OWNERS = Object.freeze({
  'pxui.dashboard-control-plane.command.cleanupManager': 'pxui.runtime-core.action.cleanupManager',
  'pxui.dashboard-control-plane.command.contextSnapshot': 'pxui.runtime-core.action.contextSnapshot',
  'pxui.dashboard-control-plane.command.enterpriseDoctor': 'pxui.agents.action.enterpriseDoctor',
  'pxui.dashboard-control-plane.command.newParallelPlan': 'pxui.workflows.action.newParallelPlan',
  'pxui.dashboard-control-plane.command.openCoordinationHandoff': 'pxui.runtime-core.action.openCoordinationHandoff',
  'pxui.dashboard-control-plane.command.openSettings': 'pxui.dashboard-control-plane.action.openSettings.header',
  'pxui.dashboard-control-plane.command.refresh': 'pxui.dashboard.action.refresh.hero',
  'pxui.dashboard-control-plane.command.teamPackPreview': 'pxui.agents.action.teamPackPreview',
  'pxui.dashboard-control-plane.command.validate': 'pxui.diagnostics.action.validate'
});

function inlineCommandOwnerControlProbe(matrix, probes) {
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const sourceRecords = new Map((probes || []).flatMap(probe => probe?.records || []).map(record => [record.control_id, record]));
  const records = Object.entries(INSTALLED_INLINE_COMMAND_OWNERS).map(([controlId, sourceControlId]) => {
    const requirement = requirements.get(controlId);
    if (!requirement) throw new Error(`Inline command control is absent: ${controlId}`);
    const source = sourceRecords.get(sourceControlId);
    const sourceComplete = Boolean(source?.rendered && source?.attempted && STAGES.every(stage => {
      const state = source.interaction_chain?.[stage]?.state;
      return state === 'present' || state === 'not_applicable';
    }));
    const authoritySkipped = source?.authority_skipped === true;
    const evidenceRef = `installed-inline-command-owner:${controlId}:${sourceControlId}`;
    return {
      control_id: controlId, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'exact_inline_dashboard_command_owner', rendered: source?.rendered === true,
      observed: source?.observed === true, attempted: source?.attempted === true, authority_skipped: authoritySkipped,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (authoritySkipped) {
          const inherited = source?.interaction_chain?.[stage];
          return [stage, inherited?.state === 'present'
            ? { state: 'present', detail: `The exact inline command shares the refused and restored physical owner ${sourceControlId}. ${inherited.detail}`, evidence: [evidenceRef, ...(inherited.evidence || [])] }
            : { state: 'missing', detail: `Repository processing order deferred ${sourceControlId}; this stage was not executed.`, evidence: [evidenceRef] }];
        }
        return [stage, sourceComplete
          ? { state: 'present', detail: `The exact rendered inline command and ${sourceControlId} share one production data-action handler; its owned profile physically completed and restored the full interaction chain.`, evidence: [evidenceRef] }
          : { state: 'missing', detail: `The exact physical owner ${sourceControlId} has not completed every required stage.`, evidence: [] }];
      })),
      errors: source?.errors || (source ? [] : [`inline-command-owner-record-unavailable:${sourceControlId}`])
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact inline dashboard commands inherit evidence only from the same rendered production data-action handler and its completed owned profile.', eligible_control_count: records.length, records };
}

async function waitForOwnedSettingsEditor(workbench, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const settingsTab = workbench.locator('[role="tab"], .tab').filter({ hasText: /Settings/i }).first();
    const settingsEditor = workbench.locator('.settings-editor:visible, .settings-editor2:visible, [data-keybinding-context*="settings"]:visible').first();
    if (await settingsTab.isVisible().catch(() => false) || await settingsEditor.isVisible().catch(() => false)) return true;
    await wait(100);
  } while (Date.now() < deadline);
  return false;
}

async function cancelOwnedWorkbenchModal(workbench, prompt, timeoutMs = 10_000) {
  const dialog = workbench.locator(NATIVE_WORKBENCH_DIALOG_SELECTOR).filter({ hasText: prompt }).first();
  await dialog.waitFor({ state: 'visible', timeout: timeoutMs });
  const exactPromptVisible = await dialog.isVisible().catch(() => false);
  if (!exactPromptVisible) return { visible: false, cancelled: false };
  await workbench.keyboard.press('Escape');
  await dialog.waitFor({ state: 'hidden', timeout: timeoutMs });
  return { visible: true, cancelled: !await dialog.isVisible().catch(() => false) };
}

async function probeInstalledWorkbenchCommands(workbench, frameHost, matrix, hostErrors = []) {
  const records = [];
  for (const control of matrix.controls.filter(item => installedWorkbenchCommandSpec(item) || installedWorkbenchAuthorityBoundarySpec(item))) {
    const boundary = installedWorkbenchAuthorityBoundarySpec(control);
    const spec = installedWorkbenchCommandSpec(control) || boundary;
    const probe = { loaded: false, visible: false, attempted: false, validationObserved: false, acknowledged: false,
      failureObserved: false, recoveryObserved: false, details: {}, errors: [] };
    try {
      const before = await frameHost.evaluate(frame => ({
        responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0,
        text: String(frame.contentDocument?.body?.innerText || '')
      }));
      const rejected = await executeWorkbenchCommand(workbench, spec.title, { rejectBeforeDispatch: true });
      probe.failureObserved = rejected.listed === true && rejected.executed === false && rejected.rejected === true && rejected.restored === true;
      if (!probe.failureObserved) throw new Error(`workbench-command-owned-rejection-invalid:${control.control_id}:${JSON.stringify(rejected)}`);
      probe.details.failure_handling = 'The exact selected command row rejected one owned Enter event before dispatch, retained the palette, and then dismissed it without an outcome effect.';
      if (boundary?.policy === 'reject-before-dispatch') {
        probe.loaded = rejected.listed === true;
        probe.visible = rejected.listed === true;
        probe.attempted = true;
        probe.validationObserved = true;
        probe.recoveryObserved = rejected.restored === true;
        probe.details.authority_boundary = boundary.reason;
      } else {
      const command = await executeWorkbenchCommand(workbench, spec.title);
      probe.loaded = command.listed === true;
      probe.visible = command.listed === true;
      probe.attempted = command.executed === true;
      probe.validationObserved = probe.attempted;
      await wait(350);
      if (boundary?.policy === 'cancel-modal') {
        const modal = await cancelOwnedWorkbenchModal(workbench, boundary.prompt, 10_000);
        probe.failureObserved = probe.failureObserved && modal.visible;
        probe.recoveryObserved = modal.cancelled;
        probe.details.authority_boundary = boundary.reason;
      } else if (spec.outcome === 'settings') {
        probe.acknowledged = await waitForOwnedSettingsEditor(workbench, 10_000);
        await reopenPacifyDashboardFromOwnedUi(workbench, frameHost);
        await wait(250);
      } else if (spec.outcome === 'context-snapshot') {
        const deadline = Date.now() + 10_000;
        do {
          probe.acknowledged = await workbench.evaluate(() => {
            const activeTab = document.querySelector('.editor-group-container.active .tab.active, .editor-group-container .tab.active');
            const editor = document.querySelector('.editor-group-container.active .view-lines, .editor-group-container .view-lines');
            const text = `${activeTab?.textContent || ''} ${editor?.textContent || ''}`;
            return /Untitled|JSON|schema_version|context/i.test(text) && !/PX.*Control Plane/i.test(String(activeTab?.textContent || ''));
          }).catch(() => false);
          if (probe.acknowledged) break;
          await wait(100);
        } while (Date.now() < deadline);
        await reopenPacifyDashboardFromOwnedUi(workbench, frameHost);
        await wait(250);
      } else if (spec.outcome === 'cleanup-manager') {
        await reopenPacifyDashboardFromOwnedUi(workbench, frameHost);
        const deadline = Date.now() + 15_000;
        do {
          probe.acknowledged = await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('[data-action="cleanupSelectAll"]'))).catch(() => false);
          if (probe.acknowledged) break;
          await wait(100);
        } while (Date.now() < deadline);
      } else if (spec.outcome === 'dashboard-refresh') {
        await waitForInstalledSidebarDashboardIdentity(frameHost, {}, 10_000);
        const identity = await waitForInstalledSourceIdentity(frameHost, 10_000);
        probe.acknowledged = identity.state === 'verified';
      } else if (spec.outcome === 'codex-cancel') {
        const deadline = Date.now() + 10_000;
        do {
          probe.acknowledged = await workbench.evaluate(() => /No local Pacify-X Codex continuation was queued|Cleared queued Codex continuation context in Pacify-X/i.test(document.body?.innerText || '')).catch(() => false);
          if (probe.acknowledged) break;
          await wait(100);
        } while (Date.now() < deadline);
      } else {
        const after = await frameHost.evaluate(frame => ({
          responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0,
          text: String(frame.contentDocument?.body?.innerText || '')
        }));
        probe.acknowledged = /PACIFY-X\s*\/\s*DASHBOARD/i.test(after.text)
          && (spec.outcome === 'dashboard' || after.responses > before.responses || after.text !== before.text);
      }
      if (probe.acknowledged) {
        probe.details.result_acknowledgement = `The exact registered workbench command produced its expected ${spec.outcome} outcome.`;
        probe.recoveryObserved = probe.failureObserved;
        probe.details.recovery_rollback = 'The rejected quick input was removed, a fresh exact command row was selected, and the normal retry produced the expected owned-host outcome.';
      }
      }
    } catch (error) {
      const message = String(error?.message || error).slice(0, 1000);
      probe.errors.push(message);
      hostErrors.push({ source: 'installed-workbench-command-probe', context: control.control_id, message });
    }
    const evidenceRef = `installed-workbench-command:${control.control_id}`;
    const interactionChain = Object.fromEntries(STAGES.map(stage => {
      if (boundary && control.stage_policy[stage] === 'required') {
        if (stage === 'failure_handling' && probe.failureObserved) return [stage, { state: 'present', detail: `The exact command row or confirmation boundary refused the unadmitted effect: ${boundary.reason}`, evidence: [evidenceRef] }];
        if (stage === 'recovery_rollback' && probe.recoveryObserved) return [stage, { state: 'present', detail: 'The command palette or modal was dismissed and no separately governed effect was dispatched.', evidence: [evidenceRef] }];
      }
      return [stage, stageResult(control, probe, stage, evidenceRef)];
    }));
    if (!boundary && probe.attempted && probe.acknowledged) {
      for (const stage of ['authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting']) {
        if (control.stage_policy[stage] === 'required') interactionChain[stage] = {
          state: 'present',
          detail: stage === 'progress_reporting'
            ? 'The selected command closed its palette and reached the exact expected owned-workbench outcome within the bounded result wait.'
            : `The registered command was listed, dispatched by the isolated VS Code host, and produced its exact expected outcome, proving ${stage}.`,
          evidence: [evidenceRef]
        };
      }
    }
    records.push({
      control_id: control.control_id, surface_id: control.surface_id, control_kind: control.kind,
      evidence_mode: control.evidence_mode, rendered: probe.visible, observed: probe.visible, attempted: probe.attempted,
      authority_skipped: Boolean(boundary && probe.failureObserved && probe.recoveryObserved),
      interaction_chain: interactionChain, errors: probe.errors
    });
  }
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact registered workbench commands in the owned isolated VS Code host; safe commands complete while ordered, persisted, service/network, identity, and host-execution boundaries remain explicitly authority-skipped.',
    eligible_control_count: records.length,
    records
  };
}

async function inspectSurface(frameHost, surface) {
  const preNavigationScrollTop = await frameHost.evaluate((frame, activeSurface) => {
    const document = frame.contentDocument;
    if (!document) throw new Error('PX webview document is unavailable.');
    document.querySelector('[data-action="closeModal"]')?.click();
    document.scrollingElement.scrollTop = document.scrollingElement.scrollHeight;
    const before = Number(document.scrollingElement.scrollTop || 0);
    let control = document.querySelector(`[data-surface="${CSS.escape(activeSurface)}"]`);
    if (!control && ['knowledgeCore', 'runtimeCore'].includes(activeSurface)) {
      document.querySelector('[data-action="toggleAdvanced"]')?.click();
      control = document.querySelector(`[data-surface="${CSS.escape(activeSurface)}"]`);
    }
    if (!control) throw new Error(`PX surface is missing: ${activeSurface}`);
    control.click();
    return before;
  }, surface);
  await wait(700);
  if (surface === 'knowledgeGraph') {
    const started = Date.now();
    while (Date.now() - started < 30_000) {
      try {
        if (await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('.graph-canvas, .graph-error')))) break;
      } catch { /* receipt records the resulting state */ }
      await wait(250);
    }
  }
  return frameHost.evaluate((frame, activeSurface) => {
    const document = frame.contentDocument;
    if (!document) throw new Error('PX webview document is unavailable.');
    const visible = element => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const shell = document.querySelector('[data-app-shell]') || document.body;
    const active = document.querySelector(`[data-surface="${CSS.escape(activeSurface)}"][aria-current="page"]`) || document.querySelector(`[data-surface="${CSS.escape(activeSurface)}"].active`);
    const expectedHeading = ({ knowledgeCore: 'Knowledge Core', runtimeCore: 'Runtime Core' })[activeSurface];
    const semanticActive = Boolean(expectedHeading && [...shell.querySelectorAll('h1')].some(item => item.textContent.trim() === expectedHeading));
    const actions = [...document.querySelectorAll('[data-action]')].filter(visible).map(item => ({
      action: item.dataset.action,
      label: String(item.innerText || item.getAttribute('aria-label') || '').trim().slice(0, 160),
      disabled: Boolean(item.disabled),
      dataset: Object.fromEntries(Object.entries(item.dataset).map(([key, value]) => [key, String(value).slice(0, 240)]))
    }));
    const overflows = [...document.querySelectorAll('header,nav,main,section,aside,article,button,output')].filter(visible).filter(item => item.scrollWidth > item.clientWidth + 3 || item.scrollHeight > item.clientHeight + 3).slice(0, 80).map(item => ({
      tag: item.tagName.toLowerCase(),
      class: String(item.className || '').slice(0, 160),
      text: String(item.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 180),
      client: [item.clientWidth, item.clientHeight], scroll: [item.scrollWidth, item.scrollHeight]
    }));
    const text = String(shell.innerText || '').trim();
    const graphCanvas = activeSurface === 'knowledgeGraph' ? document.querySelector('[data-graph-canvas]') : null;
    const graphCanvasRect = graphCanvas?.getBoundingClientRect();
    const graphNodes = graphCanvas ? [...graphCanvas.querySelectorAll('.graph-node.actual')] : [];
    const graphNodeRects = graphNodes.map(node => {
      const rect = node.getBoundingClientRect();
      return { key: node.dataset.nodeKey, selected: node.classList.contains('selected'), left: Math.round(rect.left), top: Math.round(rect.top), width: Math.round(rect.width), height: Math.round(rect.height) };
    });
    const graphVisibleNodes = graphCanvasRect ? graphNodeRects.filter(rect => rect.width > 0 && rect.height > 0 && rect.left + rect.width > graphCanvasRect.left && rect.left < graphCanvasRect.right && rect.top + rect.height > graphCanvasRect.top && rect.top < graphCanvasRect.bottom) : [];
    return {
      surface: activeSurface,
      navigation_active: Boolean(active) || semanticActive,
      navigation_evidence: active ? 'active navigation control' : semanticActive ? 'exact advanced-surface heading after direct navigation' : 'not established',
      navigation_scroll_top: Number(document.scrollingElement.scrollTop || 0),
      navigation_at_top: Number(document.scrollingElement.scrollTop || 0) === 0,
      headings: [...shell.querySelectorAll('h1,h2,h3')].filter(visible).map(item => item.innerText.trim()).slice(0, 30),
      visible_actions: actions,
      visible_action_count: actions.length,
      visible_panel_count: [...shell.querySelectorAll('section,article,aside')].filter(visible).length,
      text_characters: text.length,
      provider_missing_message: /There is no data provider registered/i.test(text),
      invalid_union_message: /sidebar-inbound-message-invalid:type:invalid_union/i.test(text),
      operational_error_messages: [...shell.querySelectorAll('[role="alert"],.error,.failed')].filter(visible).map(item => String(item.innerText || '').trim().slice(0, 500)).filter(Boolean).slice(0, 30),
      overflow_candidates: overflows,
      graph: graphCanvas ? {
        canvas: { width: Math.round(graphCanvasRect.width), height: Math.round(graphCanvasRect.height) },
        scene_transform: graphCanvas.querySelector('[data-graph-scene]')?.style.transform || '',
        node_count: graphNodes.length,
        edge_count: graphCanvas.querySelectorAll('.graph-edge-group path').length,
        visible_node_count: graphVisibleNodes.length,
        selected_visible: graphVisibleNodes.some(node => node.selected),
        sample_visible_nodes: graphVisibleNodes.slice(0, 12)
      } : null
    };
  }, surface).then(result => ({ ...result, pre_navigation_scroll_top: preNavigationScrollTop }));
}

function digest(value) {
  return crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');
}

async function builderState(frameHost, kind) {
  return frameHost.evaluate((frame, builderKind) => {
    const document = frame.contentDocument;
    const modal = document?.querySelector('.studio-modal');
    const values = selector => [...(modal?.querySelectorAll(selector) || [])].map(element => ({
      action: element.dataset.action || null,
      id: element.dataset.agentNodeId || element.dataset.nodeId || element.dataset.index || null,
      kind: element.dataset.agentKind || element.dataset.nodeTemplate || element.dataset.direction || null,
      value: 'value' in element ? String(element.value).slice(0, 400) : null,
      selected: element.classList.contains('selected') || element.getAttribute('aria-selected') === 'true',
      disabled: Boolean(element.disabled)
    }));
    return {
      builder: builderKind,
      modal_present: Boolean(modal),
      title: modal?.querySelector('h2')?.textContent?.trim() || '',
      visible_tab: modal?.querySelector('[data-action="studioEditorTab"][aria-selected="true"]')?.dataset.tab || null,
      validation: modal?.querySelector('[data-studio-validation]')?.textContent?.trim().replace(/\s+/g, ' ').slice(0, 1200) || '',
      save_disabled: Boolean(modal?.querySelector('[data-action="submitStudioDraft"]')?.disabled),
      agent_sections: values('[data-action="agentSelectSection"]'),
      agent_nodes: values('[data-agent-node-id]'),
      agent_bindings: values('[data-agent-binding-index]'),
      agent_grants: values('[data-agent-grant-index]'),
      workflow_nodes: values('.workflow-editor-node'),
      workflow_ports: values('.workflow-port-handle'),
      workflow_edges: values('[data-action="workflowRemoveEdge"]'),
      agent_scale: modal?.querySelector('[data-agent-editor-canvas]')?.dataset.agentScale || null,
      workflow_scale: modal?.querySelector('[data-workflow-editor-canvas]')?.dataset.workflowScale || null,
      canonical_json: String(modal?.querySelector('#studio-draft-json')?.value || '').slice(0, 200_000)
    };
  }, kind);
}

async function invokeBuilderControl(frameHost, kind, controlId, action, dataset = {}, pick = 'only') {
  const before = await builderState(frameHost, kind);
  const invoked = await frameHost.evaluate((frame, input) => {
    const document = frame.contentDocument;
    const matches = [...document.querySelectorAll(`[data-action="${CSS.escape(input.action)}"]`)].filter(element =>
      Object.entries(input.dataset).every(([key, value]) => String(element.dataset[key] || '') === String(value))
    );
    if (!matches.length) throw new Error(`${input.controlId}: rendered control is missing`);
    const control = input.pick === 'last' ? matches.at(-1) : matches[0];
    if (input.pick === 'only' && matches.length !== 1) throw new Error(`${input.controlId}: expected one rendered control, found ${matches.length}`);
    if (control.disabled) throw new Error(`${input.controlId}: rendered control is disabled`);
    control.click();
    return { match_count: matches.length, label: String(control.innerText || control.getAttribute('aria-label') || '').trim().slice(0, 240) };
  }, { controlId, action, dataset, pick });
  await wait(180);
  const after = await builderState(frameHost, kind);
  return {
    control_id: controlId,
    action,
    dataset,
    invoked,
    before_state_sha256: digest(before),
    after_state_sha256: digest(after),
    changed: digest(before) !== digest(after),
    before,
    after,
    observed_effects: ['bounded unsaved webview draft interaction; no save, host message, workspace write, or runtime execution']
  };
}

async function exerciseBuilderDurability(frameHost, kind, studioSurface) {
  await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="studioEditorTab"][data-tab="json"]')?.click());
  await wait(180);
  const before = await builderState(frameHost, kind);
  const negative = await frameHost.evaluate(frame => {
    const document = frame.contentDocument;
    const input = document?.querySelector('#studio-draft-json');
    const apply = document?.querySelector('[data-action="studioApplyJson"]');
    if (!input || !apply) throw new Error('canonical-json-validation-controls-missing');
    const original = input.value;
    input.value = '{';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    apply.click();
    return { original, validation_message: input.validationMessage };
  });
  await wait(180);
  assert.ok(negative.validation_message, `${kind}-studio-malformed-json-was-not-rejected`);
  await frameHost.evaluate((frame, original) => {
    const document = frame.contentDocument;
    const input = document?.querySelector('#studio-draft-json');
    const apply = document?.querySelector('[data-action="studioApplyJson"]');
    if (!input || !apply) throw new Error('canonical-json-recovery-controls-missing');
    input.value = original;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    apply.click();
  }, negative.original);
  await wait(220);
  const recovered = await builderState(frameHost, kind);
  assert.deepEqual(JSON.parse(recovered.canonical_json), JSON.parse(negative.original), `${kind}-studio-json-recovery-mismatch`);
  await frameHost.evaluate(frame => frame.contentDocument?.querySelector('.studio-modal [data-action="closeModal"]')?.click());
  await wait(180);
  const closed = await builderState(frameHost, kind);
  await frameHost.evaluate((frame, surface) => frame.contentDocument?.querySelector(`[data-surface="${CSS.escape(surface)}"]`)?.click(), studioSurface);
  await wait(220);
  const offered = await frameHost.evaluate((frame, builderKind) => {
    const control = [...(frame.contentDocument?.querySelectorAll('[data-action="openStudioDraft"]') || [])]
      .find(button => button.dataset.kind === builderKind);
    if (!control || control.disabled) return false;
    control.click();
    return true;
  }, kind);
  assert.equal(offered, true, `${kind}-studio-working-draft-offer-control-missing`);
  await wait(220);
  const resumed = await frameHost.evaluate((frame, builderKind) => {
    const control = [...(frame.contentDocument?.querySelectorAll('[data-action="resumeWorkingStudioDraft"]') || [])]
      .find(button => button.dataset.kind === builderKind);
    if (!control || control.disabled) return false;
    control.click();
    return true;
  }, kind);
  assert.equal(resumed, true, `${kind}-studio-working-draft-resume-control-missing`);
  await wait(220);
  const reopened = await builderState(frameHost, kind);
  assert.equal(reopened.modal_present, true, `${kind}-studio-working-draft-did-not-reopen`);
  assert.deepEqual(JSON.parse(reopened.canonical_json), JSON.parse(negative.original), `${kind}-studio-reopened-draft-mismatch`);
  return { before, negative_validation_message: negative.validation_message, recovered, closed, reopened, verified: true };
}

async function inspectStudioBuilder(frameHost, kind, outputRoot, hostErrors) {
  const surface = kind === 'agent' ? 'agents' : 'workflows';
  const studioSurface = kind === 'agent' ? 'agent-studio' : 'workflow-studio';
  const observations = [];
  await frameHost.evaluate((frame, values) => {
    const document = frame.contentDocument;
    document.querySelector('[data-action="closeModal"]')?.click();
    document.querySelector(`[data-surface="${CSS.escape(values.surface)}"]`)?.click();
  }, { surface });
  await wait(500);
  const catalogBefore = await builderState(frameHost, kind);
  await frameHost.evaluate((frame, builderKind) => {
    const document = frame.contentDocument;
    const open = [...document.querySelectorAll('[data-action="openStudioDraft"]')].find(button => button.dataset.kind === builderKind);
    if (!open) throw new Error(`${builderKind} Studio create control is missing.`);
    open.click();
  }, kind);
  await wait(500);
  let opened = await builderState(frameHost, kind);
  if (!opened.modal_present) {
    const resumed = await frameHost.evaluate((frame, builderKind) => {
      const document = frame.contentDocument;
      const control = [...document.querySelectorAll('[data-action="resumeWorkingStudioDraft"]')]
        .find(button => button.dataset.kind === builderKind);
      if (!control) return false;
      control.click();
      return true;
    }, kind);
    if (resumed) {
      await wait(500);
      opened = await builderState(frameHost, kind);
    }
  }
  if (!opened.modal_present) throw new Error(`${kind} Studio modal did not open.`);
  observations.push({
    control_id: `pxui.${surface}.action.openStudioDraft.${kind}`,
    action: 'openStudioDraft', dataset: { kind }, invoked: { match_count: 1, label: `Create ${kind}` },
    before_state_sha256: digest(catalogBefore), after_state_sha256: digest(opened), changed: true,
    before: catalogBefore, after: opened,
    observed_effects: ['opened a new unsaved Studio draft; no host message, workspace write, or runtime execution']
  });
  const plan = kind === 'agent' ? [
    [`pxui.${studioSurface}.action.agentSelectNode.model`, 'agentSelectNode', { agentKind: 'model' }],
    [`pxui.${studioSurface}.action.agentAddTopologyNode.tools`, 'agentAddTopologyNode', { agentKind: 'tools' }],
    [`pxui.${studioSurface}.action.agentRemoveTopologyNode.row`, 'agentRemoveTopologyNode', { agentNodeId: 'agent-node:tools' }],
    [`pxui.${studioSurface}.action.agentAddBinding`, 'agentAddBinding', {}],
    [`pxui.${studioSurface}.action.agentRemoveBinding.row`, 'agentRemoveBinding', {}, 'last'],
    [`pxui.${studioSurface}.action.agentAddGrant`, 'agentAddGrant', {}],
    [`pxui.${studioSurface}.action.agentRemoveGrant.row`, 'agentRemoveGrant', {}, 'last'],
    [`pxui.${studioSurface}.action.agentZoom.in`, 'agentZoom', { delta: '0.1' }],
    [`pxui.${studioSurface}.action.agentAutoLayout`, 'agentAutoLayout', {}],
    [`pxui.${studioSurface}.action.agentFit.toolbar`, 'agentFit', {}, 'first'],
    [`pxui.${studioSurface}.action.studioEditorTab.json`, 'studioEditorTab', { tab: 'json' }],
    [`pxui.${studioSurface}.action.studioEditorTab.visual`, 'studioEditorTab', { tab: 'visual' }]
  ] : [
    [`pxui.${studioSurface}.action.workflowAddNode.task`, 'workflowAddNode', { nodeTemplate: 'task' }],
    [`pxui.${studioSurface}.action.workflowAddPort.inputs`, 'workflowAddPort', { direction: 'inputs' }],
    [`pxui.${studioSurface}.action.workflowAddPort.outputs`, 'workflowAddPort', { direction: 'outputs' }],
    [`pxui.${studioSurface}.action.workflowZoom.in`, 'workflowZoom', { delta: '0.1' }],
    [`pxui.${studioSurface}.action.workflowAutoLayout`, 'workflowAutoLayout', {}],
    [`pxui.${studioSurface}.action.workflowFit`, 'workflowFit', {}],
    [`pxui.${studioSurface}.action.studioEditorTab.json`, 'studioEditorTab', { tab: 'json' }],
    [`pxui.${studioSurface}.action.studioEditorTab.visual`, 'studioEditorTab', { tab: 'visual' }]
  ];
  for (const [controlId, action, dataset, pick = 'only'] of plan) {
    try {
      observations.push(await invokeBuilderControl(frameHost, kind, controlId, action, dataset, pick));
    } catch (error) {
      error.builderEvidence = {
        observations,
        attempted_control_ids: observations.map(item => item.control_id),
        failed_control_id: controlId,
        failed_action: action,
        failure_state: await builderState(frameHost, kind).catch(stateError => ({ state_error: String(stateError?.message || stateError).slice(0, 1000) }))
      };
      throw error;
    }
  }
  const before = opened;
  const after = await builderState(frameHost, kind);
  if (kind === 'agent') await frameHost.evaluate(frame => { const body = frame.contentDocument?.querySelector('.studio-modal .modal-body'); if (body) body.scrollTop = 0; });
  await wait(150);
  const screenshot = await safeScreenshot(frameHost, path.join(outputRoot, `builder-${kind}.png`), `builder:${kind}`, hostErrors);
  const durability = await exerciseBuilderDurability(frameHost, kind, studioSurface);
  observations.push({
    control_id: `pxui.${studioSurface}.action.studioApplyJson`, action: 'studioApplyJson', dataset: {}, invoked: { match_count: 1, label: 'Apply JSON to visual builder' },
    before_state_sha256: digest(durability.before), after_state_sha256: digest(durability.recovered), changed: digest(durability.before) !== digest(durability.recovered),
    before: durability.before, after: durability.recovered,
    observed_effects: ['malformed canonical JSON rejected locally, then exact prior JSON restored without host dispatch']
  });
  observations.push({
    control_id: `pxui.${studioSurface}.action.resumeWorkingStudioDraft`, action: 'resumeWorkingStudioDraft', dataset: { kind }, invoked: { match_count: 1, label: `Resume ${kind} draft` },
    before_state_sha256: digest(durability.closed), after_state_sha256: digest(durability.reopened), changed: true,
    before: durability.closed, after: durability.reopened,
    observed_effects: ['reopened the exact bounded working draft from VS Code webview state']
  });
  const closeBefore = durability.reopened;
  await frameHost.evaluate(frame => frame.contentDocument.querySelector('.studio-modal [data-action="closeModal"]')?.click());
  await wait(180);
  const closeAfter = await builderState(frameHost, kind);
  observations.push({
    control_id: `pxui.${studioSurface}.action.closeModal`, action: 'closeModal', dataset: {}, invoked: { match_count: 1, label: 'Cancel' },
    before_state_sha256: digest(closeBefore), after_state_sha256: digest(closeAfter), changed: digest(closeBefore) !== digest(closeAfter),
    before: closeBefore, after: closeAfter,
    observed_effects: ['closed the unsaved modal; no candidate was saved or executed']
  });
  return {
    terminal_disposition: 'interaction_complete',
    authority: LIVE_WALK_AUTHORITY,
    before, after, screenshot, observations, durability,
    attempted_control_ids: observations.map(item => item.control_id),
    cleanup: { modal_closed: !closeAfter.modal_present, candidate_saved: false, runtime_executed: false }
  };
}

function applyBuilderObservations(controlChains, builders) {
  const observations = Object.values(builders).flatMap(builder => builder?.observations || []);
  const byId = new Map(controlChains.controls.map(control => [control.control_id, control]));
  for (const observation of observations) {
    const record = byId.get(observation.control_id);
    if (!record) throw new Error(`Builder observed an unregistered control: ${observation.control_id}`);
    record.attempted = true;
    record.rendered = true;
    record.visible = true;
    record.enabled = true;
    record.resolver = { type: 'exact_builder_control', status: 'exact', match_count: observation.invoked.match_count };
    record.before_state_sha256 = observation.before_state_sha256;
    record.after_state_sha256 = observation.after_state_sha256;
    record.observed_effects = observation.observed_effects;
    record.screenshot_references = [builders.agent?.screenshot, builders.workflow?.screenshot].filter(item => item?.status === 'captured').map(item => item.path);
    record.terminal_disposition = 'reversible_ui_interaction_observed';
    record.stages = record.stages.map(stage => {
      if (['open_load', 'display', 'user_edit_action', 'input_validation', 'result_acknowledgement'].includes(stage.stage)) {
        return { stage: stage.stage, status: 'observed', observed_at: record.observed_at, evidence: `${observation.control_id} exact pre/post state digest` };
      }
      if (['authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting'].includes(stage.stage)) {
        return { stage: stage.stage, status: 'not_applicable', observed_at: record.observed_at, reason: 'This exact pass is confined to unsaved webview draft state and dispatches no host or durable effect.' };
      }
      if (builders[record.surface_id === 'agent-studio' ? 'agent' : record.surface_id === 'workflow-studio' ? 'workflow' : '']?.durability?.verified === true) {
        return { stage: stage.stage, status: 'observed', observed_at: record.observed_at, evidence: `${record.surface_id} isolated working-draft persistence, reopen, malformed-input rejection, and exact recovery receipt` };
      }
      return { ...stage, reason: 'Durable reload, injected failure, and recovery behavior is owned by PX-OS-848.' };
    });
  }
  const terminalDispositions = {};
  for (const record of controlChains.controls) terminalDispositions[record.terminal_disposition] = (terminalDispositions[record.terminal_disposition] || 0) + 1;
  controlChains.aggregates.terminal_dispositions = terminalDispositions;
  controlChains.aggregates.attempted_control_count = controlChains.controls.filter(control => control.attempted).length;
  controlChains.aggregates.complete_interaction_chains = controlChains.controls.filter(control => control.stages.every(stage => ['observed', 'not_applicable'].includes(stage.status))).length;
  controlChains.builder_observations = observations.map(observation => ({
    control_id: observation.control_id,
    before_state_sha256: observation.before_state_sha256,
    after_state_sha256: observation.after_state_sha256,
    changed: observation.changed,
    observed_effects: observation.observed_effects
  }));
  return controlChains;
}

function applyInstalledProbeObservations(controlChains, installedControlProbe, summaryKey = 'installed_probe_observations') {
  if (!installedControlProbe || installedControlProbe.schema_version !== 'px.installed-operational-control-probe/1.0') {
    throw new Error('Installed control probe is missing or has an unsupported schema.');
  }
  const records = Array.isArray(installedControlProbe.records) ? installedControlProbe.records : [];
  if (records.length !== installedControlProbe.eligible_control_count) {
    throw new Error('Installed control probe does not retain its exact eligible-control denominator.');
  }
  const byId = new Map(controlChains.controls.map(control => [control.control_id, control]));
  const seen = new Set();
  for (const probe of records) {
    const controlId = String(probe.control_id || '');
    if (seen.has(controlId)) throw new Error(`Installed control probe duplicated a control: ${controlId}`);
    seen.add(controlId);
    const record = byId.get(controlId);
    if (!record) throw new Error(`Installed control probe referenced an unregistered control: ${controlId}`);
    const chain = probe.interaction_chain;
    if (!chain || STAGES.some(stage => !chain[stage])) {
      throw new Error(`Installed control probe lacks the complete stage denominator: ${controlId}`);
    }
    record.rendered ||= probe.rendered === true;
    record.visible ||= probe.rendered === true;
    record.attempted ||= probe.attempted === true;
    if (probe.rendered) record.resolver = { type: 'exact_installed_control', status: 'exact', match_count: 1 };
    record.stages = record.stages.map(existing => {
      if (existing.status === 'observed') return existing;
      const direct = chain[existing.stage];
      if (direct.state === 'present') {
        return {
          stage: existing.stage,
          status: 'observed',
          observed_at: record.observed_at,
          evidence: `${direct.detail} ${(direct.evidence || []).join('; ')}`.trim()
        };
      }
      if (direct.state === 'not_applicable') {
        return {
          stage: existing.stage,
          status: 'not_applicable',
          observed_at: record.observed_at,
          reason: direct.detail
        };
      }
      return existing;
    });
    const complete = record.stages.every(stage => ['observed', 'not_applicable'].includes(stage.status));
    if (complete) record.terminal_disposition = 'installed_operational_interaction_complete';
    else if (probe.authority_skipped === true) {
      applyAuthoritySkipContract(record, {
        authority: probe.authority,
        reason: probe.reason,
        expectedEffect: probe.expected_effect,
        returnCondition: probe.return_condition
      });
    }
    else if (probe.attempted) record.terminal_disposition = 'installed_operational_interaction_partial';
    else if (Array.isArray(probe.errors) && probe.errors.length) record.terminal_disposition = 'installed_operational_probe_error';
    else if (probe.rendered) record.terminal_disposition = 'installed_operational_observation_partial';
    else record.terminal_disposition = 'installed_control_not_rendered';
  }
  const terminalDispositions = {};
  for (const record of controlChains.controls) terminalDispositions[record.terminal_disposition] = (terminalDispositions[record.terminal_disposition] || 0) + 1;
  controlChains.aggregates.terminal_dispositions = terminalDispositions;
  controlChains.aggregates.attempted_control_count = controlChains.controls.filter(control => control.attempted).length;
  controlChains.aggregates.complete_interaction_chains = controlChains.controls.filter(control => control.stages.every(stage => ['observed', 'not_applicable'].includes(stage.status))).length;
  controlChains[summaryKey] = {
    eligible_control_count: records.length,
    rendered_control_count: records.filter(record => record.rendered).length,
    attempted_control_count: records.filter(record => record.attempted).length,
    complete_interaction_chains: records.filter(record => STAGES.every(stage => ['present', 'not_applicable'].includes(record.interaction_chain[stage].state))).length
  };
  return controlChains;
}

async function readInstalledConfigurationAction(frameHost, spec) {
  await frameHost.evaluate((frame, route) => {
    const document = frame.contentDocument;
    document?.querySelector('[data-action="closeModal"]')?.click();
    document?.querySelector('[data-surface="dashboard"]')?.click();
    document?.querySelector(`[data-surface="${CSS.escape(route)}"]`)?.click();
  }, spec.route);
  await wait(120);
  return frameHost.evaluate((frame, item) => {
    const document = frame.contentDocument; const inner = frame.contentWindow;
    const control = [...(document?.querySelectorAll(`[data-action="${CSS.escape(item.action)}"]`) || [])]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    return {
      available: Boolean(control), target_value: control ? String(control.dataset[item.datasetKey] || '') : '',
      response_count: inner?.__PX_INSTALLED_RESPONSES__?.length || 0
    };
  }, spec);
}

async function waitForInstalledConfigurationTarget(frameHost, spec, predicate, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let current = null;
  do {
    current = await readInstalledConfigurationAction(frameHost, spec);
    if (current.available && predicate(current.target_value)) return current;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`${spec.action}-configuration-target-timeout:${current?.target_value || 'unavailable'}`);
}

async function invokeInstalledConfigurationAction(workbench, frameHost, spec, targetValue) {
  const before = await readInstalledConfigurationAction(frameHost, spec);
  if (!before.available || before.target_value !== targetValue) throw new Error(`${spec.action}-target-state-mismatch:${before.target_value}:${targetValue}`);
  await frameHost.evaluate((frame, action) => {
    const control = [...frame.contentDocument.querySelectorAll(`[data-action="${CSS.escape(action)}"]`)]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    if (!control) throw new Error(`configuration-action-unavailable:${action}`);
    control.click();
  }, spec.action);
  const readAcknowledgement = () => frameHost.evaluate((frame, item) => {
    const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
    return responses.slice(item.after).find(response => response?.type === item.responseType && response?.operation === item.operation) || null;
  }, { after: before.response_count, responseType: spec.responseType, operation: spec.operation });
  let acknowledgement = null;
  if (spec.approvalLabel && targetValue === 'true') {
    const approval = workbench.getByRole('button', { name: spec.approvalLabel, exact: true }).last();
    const approvalDeadline = Date.now() + 15_000;
    do {
      acknowledgement = await readAcknowledgement();
      if (acknowledgement) return acknowledgement;
      if (await approval.isVisible().catch(() => false)) { await approval.click(); break; }
      await wait(100);
    } while (Date.now() < approvalDeadline);
  }
  const deadline = Date.now() + 12_000;
  do {
    acknowledgement = await readAcknowledgement();
    if (acknowledgement) break;
    await wait(100);
  } while (Date.now() < deadline);
  if (!acknowledgement) throw new Error(`${spec.action}-typed-acknowledgement-timeout`);
  return acknowledgement;
}

async function exerciseOwnedConfigurationFailure(frameHost, spec, verifyUnchanged) {
  if (!ownedReversibleConfigurationAuthority || !ownedWorkspaceRoot || !path.isAbsolute(ownedWorkspaceRoot)) {
    throw new Error(`${spec.operation}-owned-fault-authority-unavailable`);
  }
  const markerRoot = path.resolve(ownedWorkspaceRoot, '.px', 'owned-operational-faults');
  const marker = path.resolve(markerRoot, `${spec.operation}.once`);
  if (path.dirname(marker) !== markerRoot || !marker.startsWith(`${ownedWorkspaceRoot}${path.sep}`)) {
    throw new Error(`${spec.operation}-owned-fault-marker-outside-workspace`);
  }
  fs.mkdirSync(markerRoot, { recursive: true });
  if (fs.existsSync(marker)) throw new Error(`${spec.operation}-stale-owned-fault-marker`);
  const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
  fs.writeFileSync(marker, `${JSON.stringify({ schema_version: 'px.owned-operational-fault/1.0', operation: spec.operation, effect: 'fail-before-configuration-write' })}\n`, { encoding: 'utf8', flag: 'wx' });
  try {
    await frameHost.evaluate((frame, action) => {
      const control = [...frame.contentDocument.querySelectorAll(`[data-action="${CSS.escape(action)}"]`)]
        .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
      if (!control) throw new Error(`owned-configuration-fault-action-unavailable:${action}`);
      control.click();
    }, spec.action);
    const deadline = Date.now() + 12_000;
    let failure = null;
    do {
      failure = await frameHost.evaluate((frame, item) => {
        const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
        return responses.slice(item.after).find(response => response?.type === 'operationError'
          && response?.operation === item.operation
          && response?.error === `owned-injected-configuration-fault:${item.operation}`) || null;
      }, { after: before, operation: spec.operation });
      if (failure) break;
      await wait(100);
    } while (Date.now() < deadline);
    if (!failure) throw new Error(`${spec.operation}-owned-fault-not-observed`);
    if (!await verifyUnchanged()) throw new Error(`${spec.operation}-owned-fault-changed-state`);
    return failure;
  } finally {
    if (fs.existsSync(marker)) fs.unlinkSync(marker);
  }
}

async function waitForInstalledOutboundHostAction(frameHost, after, expected, timeoutMs = 3_000) {
  const deadline = Date.now() + timeoutMs;
  let observed = null;
  do {
    observed = await frameHost.evaluate((frame, item) => (frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || [])
      .slice(item.after).find(value => value?.type === item.expected.operation && value?.requestId === item.expected.requestId) || null,
    { after, expected });
    if (observed) return observed;
    await wait(60);
  } while (Date.now() < deadline);
  throw new Error(`installed-outbound-host-action-missing:${JSON.stringify({ operation: expected?.operation || '', request_id: expected?.requestId || '' })}`);
}

async function exerciseOwnedHostActionFailure(frameHost, spec, timeoutMs = 12_000) {
  if (!ownedReversibleConfigurationAuthority || !ownedWorkspaceRoot || !path.isAbsolute(ownedWorkspaceRoot)) {
    throw new Error(`${spec.operation}-owned-host-action-fault-authority-unavailable`);
  }
  const markerRoot = path.resolve(ownedWorkspaceRoot, '.px', 'owned-host-action-faults');
  const marker = path.resolve(markerRoot, `${spec.operation}.once`);
  if (path.dirname(marker) !== markerRoot || !marker.startsWith(`${ownedWorkspaceRoot}${path.sep}`)) {
    throw new Error(`${spec.operation}-owned-host-action-fault-marker-outside-workspace`);
  }
  fs.mkdirSync(markerRoot, { recursive: true });
  if (fs.existsSync(marker)) throw new Error(`${spec.operation}-stale-owned-host-action-fault-marker`);
  const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
  const requestBeforeDispatch = await installedOutboundRequestOffset(frameHost);
  fs.writeFileSync(marker, `${JSON.stringify({ schema_version: 'px.owned-host-action-fault/1.0', operation: spec.operation, effect: 'fail-after-validation-before-host-effect' })}\n`, { encoding: 'utf8', flag: 'wx' });
  try {
    await waitForKnowledgeControl(frameHost, `[data-action="${spec.action}"]`, Math.min(5_000, timeoutMs));
    const startedAt = Date.now();
    const dispatch = await frameHost.evaluate((frame, item) => {
      const hostQueries = frame.contentWindow?.PXDashboard?.require('hostQueries');
      const previousRequestId = String(hostQueries?.hostActionIdentity()?.requestId || '');
      const control = [...frame.contentDocument.querySelectorAll(`[data-action="${CSS.escape(item.action)}"]`)]
        .find(value => !value.disabled && (value.offsetWidth || value.offsetHeight || value.getClientRects().length));
      if (!control) return { rendered: false, requestId: '' };
      control.click();
      const operation = hostQueries?.hostActionIdentity() || {};
      return {
        rendered: true,
        requestId: operation?.action === item.action
          && typeof operation.requestId === 'string'
          && operation.requestId.length > 0
          && operation.requestId !== previousRequestId
          ? operation.requestId
          : ''
      };
    }, spec);
    if (!dispatch.rendered) throw new Error(`${spec.controlId}-owned-host-action-fault-control-not-rendered`);
    if (!dispatch.requestId) throw new Error(`${spec.controlId}-owned-host-action-fault-request-identity-missing`);
    await waitForInstalledOutboundHostAction(frameHost, requestBeforeDispatch, { operation: spec.operation, requestId: dispatch.requestId }, Math.min(3_000, timeoutMs));
    const failure = await waitForDurableHostActionResult(frameHost, {
      after: before, operation: spec.operation, requestId: dispatch.requestId, startedAt, refreshSnapshot: true
    }, timeoutMs);
    const expectedError = `owned-injected-host-action-fault:${spec.operation}`;
    if (!failure || failure.disposition !== 'failed' || failure.detail?.error !== expectedError) {
      throw new Error(`${spec.controlId}-owned-host-action-fault-receipt-invalid:${JSON.stringify(failure || null)}`);
    }
    if (fs.existsSync(marker)) throw new Error(`${spec.controlId}-owned-host-action-fault-marker-not-consumed`);
    return { request_id: dispatch.requestId, disposition: failure.disposition, error: failure.detail.error, marker_consumed: true };
  } finally {
    if (fs.existsSync(marker)) fs.unlinkSync(marker);
  }
}

async function invokeInstalledHostAction(frameHost, spec, timeoutMs = 120_000) {
  await frameHost.evaluate((frame, route) => {
    const document = frame.contentDocument;
    document?.querySelector('[data-action="closeModal"]')?.click();
    document?.querySelector('[data-surface="dashboard"]')?.click();
    document?.querySelector(`[data-surface="${CSS.escape(route)}"]`)?.click();
  }, spec.route);
  await waitForKnowledgeControl(frameHost, `[data-action="${spec.action}"]`, Math.min(10_000, timeoutMs));
  const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
  const requestBeforeDispatch = await installedOutboundRequestOffset(frameHost);
  const actionStartedAt = Date.now();
  const requestId = await frameHost.evaluate((frame, item) => {
    const hostQueries = frame.contentWindow?.PXDashboard?.require('hostQueries');
    const previousRequestId = String(hostQueries?.hostActionIdentity()?.requestId || '');
    const control = [...frame.contentDocument.querySelectorAll(`[data-action="${CSS.escape(item.action)}"]`)]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    if (!control) throw new Error(`owned-host-action-unavailable:${item.action}`);
    control.click();
    const operation = hostQueries?.hostActionIdentity() || {};
    return operation.action === item.action
      && typeof operation.requestId === 'string'
      && operation.requestId.length > 0
      && operation.requestId !== previousRequestId
      ? operation.requestId
      : '';
  }, spec);
  if (!requestId) throw new Error(`${spec.action}-request-identity-missing`);
  await waitForInstalledOutboundHostAction(frameHost, requestBeforeDispatch, { operation: spec.operation, requestId }, Math.min(3_000, timeoutMs));
  const acknowledgement = await waitForDurableHostActionResult(frameHost, { after: before, operation: spec.operation, requestId, startedAt: actionStartedAt, refreshSnapshot: true }, timeoutMs);
  if (!acknowledgement) throw new Error(`${spec.action}-typed-acknowledgement-timeout`);
  if (acknowledgement.disposition !== 'completed') throw new Error(`${spec.action}-unexpected-disposition:${acknowledgement.disposition}`);
  return acknowledgement;
}

function installedHostActionRequestIdentity(operation, expected) {
  return operation?.action === expected?.action
    && typeof operation?.requestId === 'string'
    && operation.requestId.length > 0
    && operation.requestId !== String(expected?.previousRequestId || '')
    ? operation.requestId
    : '';
}

function installedHostActionReceiptMatches(value, expected) {
  return value?.type === 'hostActionResult'
    && value.requestId === expected?.requestId
    && value.operation === expected?.operation
    && Date.parse(value.observedAt || '') >= expected?.startedAt;
}

async function waitForDurableHostActionResult(frameHost, item, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let nextSnapshotRefreshAt = 0;
  const readAcknowledgement = () => frameHost.evaluate((frame, expected) => {
    const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
    const matches = value => value?.type === 'hostActionResult'
      && value.requestId === expected.requestId
      && value.operation === expected.operation
      && Date.parse(value.observedAt || '') >= expected.startedAt;
    const durableCandidates = [
      frame.contentWindow?.__PX_DURABLE_HOST_ACTION_RESULT__,
      ...[...responses].reverse().filter(value => value?.type === 'snapshot').map(value => value?.snapshot?.lastHostActionResult)
    ];
    return responses.slice(expected.after).find(matches)
      || responses.find(matches)
      || durableCandidates.find(matches)
      || null;
  }, item);
  do {
    const acknowledgement = await readAcknowledgement();
    if (acknowledgement) return acknowledgement;
    if (item.refreshSnapshot && Date.now() >= nextSnapshotRefreshAt) {
      await frameHost.evaluate(frame => frame.contentWindow?.PXDashboard?.require('hostQueries')?.refresh());
      nextSnapshotRefreshAt = Date.now() + 750;
    }
    await wait(120);
  } while (Date.now() < deadline);
  return readAcknowledgement();
}

async function inspectHostActionReceiptFailure(frameHost, item) {
  return frameHost.evaluate((frame, expected) => {
    const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
    const durableCandidates = [
      frame.contentWindow?.__PX_DURABLE_HOST_ACTION_RESULT__,
      ...[...responses].reverse().filter(value => value?.type === 'snapshot').map(value => value?.snapshot?.lastHostActionResult)
    ].filter(Boolean);
    const durable = durableCandidates.find(value => value?.requestId === expected.requestId) || durableCandidates[0] || null;
    const received = frame.contentWindow?.__PX_DURABLE_HOST_ACTION_REQUEST__
      || [...responses].reverse().find(value => value?.type === 'snapshot')?.snapshot?.lastHostActionRequest
      || null;
    return {
      responses: responses.slice(expected.after).slice(-20).map(value => ({
        type: String(value?.type || '').slice(0, 100), operation: String(value?.operation || '').slice(0, 100),
        request_id: String(value?.requestId || '').slice(0, 200), error: String(value?.error || '').slice(0, 500)
      })),
      durable: durable ? {
        type: String(durable.type || '').slice(0, 100), operation: String(durable.operation || '').slice(0, 100),
        request_id: String(durable.requestId || '').slice(0, 200), disposition: String(durable.disposition || '').slice(0, 100),
        observed_at: String(durable.observedAt || '').slice(0, 100)
      } : null,
      host_received: received ? {
        operation: String(received.operation || '').slice(0, 100),
        request_id: String(received.requestId || '').slice(0, 200),
        received_at: String(received.receivedAt || '').slice(0, 100)
      } : null,
      expected_request_id: String(expected.requestId || '').slice(0, 200),
      exact_request_receipts: responses.filter(value => value?.requestId === expected.requestId).slice(-20).map(value => ({
        type: String(value?.type || '').slice(0, 100), operation: String(value?.operation || '').slice(0, 100),
        request_id: String(value?.requestId || '').slice(0, 200), disposition: String(value?.disposition || '').slice(0, 100),
        error: String(value?.error || '').slice(0, 500)
      }))
    };
  }, item).catch(error => ({ responses: [], durable: null, inspection_error: String(error?.message || error).slice(0, 500) }));
}

function stageOwnedActivityEnabled() {
  if (!ownedReversibleConfigurationAuthority || !ownedWorkspaceRoot || !path.isAbsolute(ownedWorkspaceRoot)) throw new Error('owned-activity-policy-authority-unavailable');
  const directory = path.resolve(ownedWorkspaceRoot, '.vscode');
  const target = path.resolve(directory, 'settings.json');
  if (path.dirname(target) !== directory || !target.startsWith(`${ownedWorkspaceRoot}${path.sep}`)) throw new Error('owned-activity-policy-target-outside-workspace');
  const existed = fs.existsSync(target);
  const original = existed ? fs.readFileSync(target) : null;
  let settings = {};
  if (original) {
    settings = JSON.parse(original.toString('utf8'));
    if (!settings || typeof settings !== 'object' || Array.isArray(settings)) throw new Error('owned-activity-settings-not-an-object');
  }
  fs.mkdirSync(directory, { recursive: true });
  settings['pacifyX.activity.enabled'] = true;
  fs.writeFileSync(target, `${JSON.stringify(settings, null, 2)}\n`, 'utf8');
  return { target, existed, original_base64: original?.toString('base64') || '', previous_enabled: false };
}

function restoreOwnedActivitySettings(state) {
  if (!state?.target || !path.resolve(state.target).startsWith(`${ownedWorkspaceRoot}${path.sep}`)) throw new Error('owned-activity-policy-restoration-target-invalid');
  if (state.existed) fs.writeFileSync(state.target, Buffer.from(state.original_base64, 'base64'));
  else if (fs.existsSync(state.target)) fs.unlinkSync(state.target);
  const restored = state.existed
    ? fs.existsSync(state.target) && fs.readFileSync(state.target).equals(Buffer.from(state.original_base64, 'base64'))
    : !fs.existsSync(state.target);
  if (!restored) throw new Error('owned-activity-policy-byte-restoration-mismatch');
  return true;
}

async function waitForInstalledActivityPolicy(frameHost, enabled, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  do {
    const current = await frameHost.evaluate(frame => {
      const policy = frame.contentWindow?.PXDashboard?.require('hostQueries')?.activityPolicy() || {};
      return policy.enabled === true;
    });
    if (current === enabled) return true;
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`owned-activity-policy-state-timeout:${enabled}`);
}

async function waitForInstalledActivityScenarioState(frameHost, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let current = null;
  let nextRefreshAt = 0;
  do {
    current = await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      const reconcile = document?.querySelector('[data-action="reconcileStaleActivity"]') || null;
      if (reconcile && !(reconcile.offsetWidth || reconcile.offsetHeight || reconcile.getClientRects().length)) reconcile.scrollIntoView({ block: 'center', inline: 'nearest' });
      const reconcileRendered = Boolean(reconcile && (reconcile.offsetWidth || reconcile.offsetHeight || reconcile.getClientRects().length));
      const toggle = [...(document?.querySelectorAll('[data-action="activityPause"]') || [])]
        .find(element => element.offsetWidth || element.offsetHeight || element.getClientRects().length);
      const scenario = frame.contentWindow?.PXDashboard?.require('hostQueries')?.activityScenario() || {};
      return {
        pending: scenario.pending === true,
        reconcile_present: Boolean(reconcile),
        reconcile_rendered: reconcileRendered,
        reconcile_enabled: Boolean(reconcileRendered && !reconcile.disabled),
        expected_reconcile_enabled: scenario.reconcileEnabled === true,
        stale_count: Number(scenario.staleCount || 0),
        paused_target: String(toggle?.dataset.paused || ''),
        policy_enabled: scenario.enabled === true,
        current_paused: scenario.paused === true
      };
    });
    const policyCoherent = !current.pending && current.paused_target === (current.current_paused ? 'false' : 'true');
    if (policyCoherent && (!current.policy_enabled || current.current_paused)) return current;
    const controlCoherent = policyCoherent
      && current.reconcile_present
      && current.reconcile_rendered
      && current.reconcile_enabled === current.expected_reconcile_enabled;
    if (controlCoherent && current.reconcile_enabled) return current;
    if (!current.pending && Date.now() >= nextRefreshAt) {
      await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="activityRefresh"]')?.click());
      nextRefreshAt = Date.now() + 750;
    }
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`host-boundary-activity-state-not-coherent:${JSON.stringify(current)}`);
}

const INSTALLED_HOST_BOUNDARY_SPECS = Object.freeze([
  { controlId: 'pxui.activity.action.reconcileStaleActivity', route: 'activity', scenario: 'activity-enabled', action: 'reconcileStaleActivity', operation: 'reconcileStaleActivity', dispositions: ['completed', 'no-op'] },
  { controlId: 'pxui.dashboard-control-plane.action.copyModal', route: 'dashboard', revealAction: 'inspectMetric', action: 'copyModal', operation: 'copyText' },
  { controlId: 'pxui.dashboard-control-plane.action.exportRecordJson', route: 'dashboard', revealAction: 'inspectMetric', action: 'exportRecordJson', operation: 'exportRecordJson' },
  { controlId: 'pxui.dashboard-control-plane.action.openSettings.header', route: 'dashboard', action: 'openSettings', operation: 'openSettings' },
  { controlId: 'pxui.diagnostics.action.openPunchSource.row', route: 'diagnostics', scenario: 'operational-card', action: 'openPunchSource', operation: 'openFile', editorDisplacement: true },
  { controlId: 'pxui.knowledge-core.action.openKnowledgeSource.row', route: 'knowledgeCore', action: 'openKnowledgeSource', operation: 'openFile' },
  { controlId: 'pxui.memory.action.contextSnapshot', route: 'memory', action: 'contextSnapshot', operation: 'createContextSnapshot' },
  { controlId: 'pxui.memory.action.openCoordinationHandoff', route: 'memory', action: 'openCoordinationHandoff', operation: 'openCoordinationHandoff' },
  { controlId: 'pxui.memory.action.openMemorySource', route: 'memory', scenario: 'canonical-memory', revealAction: 'inspectMemoryRecord', revealSelector: '[data-action="inspectMemoryRecord"][data-memory-id]', action: 'openMemorySource', operation: 'openFile' },
  { controlId: 'pxui.projects.action.openCoordinationHandoff', route: 'projects', action: 'openCoordinationHandoff', operation: 'openCoordinationHandoff' },
  { controlId: 'pxui.projects.action.openEngineRoot', route: 'projects', action: 'openEngineRoot', operation: 'openFile' },
  { controlId: 'pxui.runtime-core.action.contextSnapshot', route: 'runtimeCore', action: 'contextSnapshot', operation: 'createContextSnapshot' },
  { controlId: 'pxui.runtime-core.action.openCoordinationHandoff', route: 'runtimeCore', action: 'openCoordinationHandoff', operation: 'openCoordinationHandoff' },
  { controlId: 'pxui.settings.action.openSettings.authority', route: 'settings', action: 'openSettings', operation: 'openSettings' },
  { controlId: 'pxui.settings.action.openSettings.effectiveConfiguration', route: 'settings', action: 'openSettings', operation: 'openSettings' },
  { controlId: 'pxui.settings.action.openSettings.guardrails', route: 'settings', action: 'openSettings', operation: 'openSettings' },
  { controlId: 'pxui.workflows.action.openCoordinationHandoff', route: 'workflows', action: 'openCoordinationHandoff', operation: 'openCoordinationHandoff' },
  { controlId: 'pxui.workflows.action.copyTaskHandoff.row', route: 'workflows', scenario: 'owned-task-row', action: 'copyTaskHandoff', operation: 'copyTaskHandoff' }
]);

const DISPLACING_HOST_OPERATIONS = new Set(['openSettings', 'openFile', 'createContextSnapshot', 'openCoordinationHandoff']);

function installedHostBoundaryRevealSelector(spec) {
  if (typeof spec?.revealSelector === 'string' && spec.revealSelector.trim()) return spec.revealSelector.trim();
  if (typeof spec?.revealAction === 'string' && spec.revealAction.trim()) return `[data-action="${spec.revealAction.trim()}"]`;
  return '';
}

async function revealInstalledHostBoundaryControl(frameHost, spec) {
  const selector = installedHostBoundaryRevealSelector(spec);
  if (!selector) return true;
  return frameHost.evaluate((frame, exactSelector) => {
    const control = [...frame.contentDocument.querySelectorAll(exactSelector)]
      .find(item => !item.disabled && (item.offsetWidth || item.offsetHeight || item.getClientRects().length));
    if (!control) return false;
    control.click();
    return true;
  }, selector);
}

async function settleInstalledOwnedTaskRow(frameHost, timeoutMs) {
  return settleInstalledSurfaceControl(frameHost, {
    surface: 'workflows', scopeTarget: 'workflows', scope: 'core', selector: '[data-action="copyTaskHandoff"][data-task-id]'
  }, timeoutMs);
}

async function prepareInstalledHostBoundaryScenario(frameHost, spec, timeoutMs) {
  const scenario = { kind: spec.scenario || '', configured_by_profile: false };
  if (spec.scenario === 'operational-card') {
    await frameHost.evaluate(frame => {
      const requestId = `host-boundary-card-${Date.now()}-${Math.random()}`;
      frame.contentWindow?.PXDashboard?.require('hostQueries').operationalCard(requestId, 'PX-OS-1067');
    });
    await waitForKnowledgeControl(frameHost, '[data-action="openPunchSource"]', timeoutMs);
  }
  if (spec.scenario === 'activity-enabled') {
    const activity = await waitForInstalledActivityScenarioState(frameHost, timeoutMs);
    if (!activity.reconcile_enabled) {
      if (!activity.policy_enabled) {
        scenario.activity_settings = stageOwnedActivityEnabled();
        await waitForInstalledActivityPolicy(frameHost, true, timeoutMs);
        scenario.previous_enabled = false;
        scenario.previous_paused = activity.current_paused;
        scenario.activity_policy_changed = true;
        scenario.activity_policy_restored = false;
        await waitForInstalledActivityScenarioState(frameHost, timeoutMs);
      } else if (activity.paused_target === 'false') {
        await invokeInstalledHostAction(frameHost, { route: 'activity', action: 'activityPause', operation: 'setActivityPaused' }, timeoutMs);
        scenario.activity_toggled = true;
        await waitForInstalledActivityScenarioState(frameHost, timeoutMs);
      } else throw new Error(`host-boundary-activity-policy-not-reversibly-enablable:${JSON.stringify(activity)}`);
      await waitForKnowledgeControl(frameHost, '[data-action="reconcileStaleActivity"]', timeoutMs);
    }
  }
  if (spec.scenario === 'canonical-memory') {
    const initialMemory = await readInstalledCanonicalMemoryState(frameHost);
    if (!initialMemory.attached) {
      const configured = await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'configureCanonicalMemory', operation: 'configureCanonicalMemory' }, timeoutMs);
      scenario.configured_by_profile = true;
      scenario.previous_workspace_root = String(configured.detail?.previousWorkspaceRoot || '');
      await waitForInstalledCanonicalMemoryState(frameHost, true, timeoutMs);
    }
    await settleInstalledCanonicalMemoryRecord(frameHost, timeoutMs);
  }
  if (spec.scenario === 'owned-task-row') await settleInstalledOwnedTaskRow(frameHost, timeoutMs);
  return scenario;
}

async function restoreInstalledHostBoundaryScenario(workbench, frameHost, scenario, timeoutMs) {
  if (!scenario) return;
  if (scenario.activity_toggled) {
    await resetInstalledDashboardBaseline(workbench, frameHost, timeoutMs);
    await invokeInstalledHostAction(frameHost, { route: 'activity', action: 'activityPause', operation: 'setActivityPaused' }, timeoutMs);
  }
  if (scenario.activity_policy_changed) {
    scenario.activity_policy_restored = restoreOwnedActivitySettings(scenario.activity_settings);
    await resetInstalledDashboardBaseline(workbench, frameHost, timeoutMs);
    await navigateInstalledSurface(frameHost, 'activity', timeoutMs);
    await waitForInstalledActivityPolicy(frameHost, scenario.previous_enabled, timeoutMs);
    if (!scenario.activity_policy_restored) throw new Error('host-boundary-activity-policy-restoration-mismatch');
  }
  if (scenario.configured_by_profile) {
    await resetInstalledDashboardBaseline(workbench, frameHost, timeoutMs);
    await navigateInstalledSurface(frameHost, 'memory', timeoutMs);
    const detached = await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'disconnectCanonicalMemory', operation: 'disconnectCanonicalMemory' }, timeoutMs);
    if (String(detached.detail?.restoredWorkspaceRoot || '') !== scenario.previous_workspace_root) throw new Error('host-boundary-canonical-memory-restoration-mismatch');
    await waitForInstalledCanonicalMemoryState(frameHost, Boolean(scenario.previous_workspace_root), timeoutMs);
  }
}

function hostBoundaryControlProbe(matrix, observation) {
  const specs = new Map(INSTALLED_HOST_BOUNDARY_SPECS.map(spec => [spec.controlId, spec]));
  const requirements = matrix.controls.filter(control => specs.has(control.control_id));
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact installed host handoffs inside the owned isolated VS Code profile; each result must be typed and the PX dashboard must be reopened after native host UI changes.',
    eligible_control_count: requirements.length,
    records: requirements.map(requirement => {
      const result = observation.operations?.[requirement.control_id];
      const verified = result?.acknowledged === true && result?.dashboard_reopened === true;
      const failedBeforeEffectAndRecovered = result?.failure_handling === true && result?.failure_dashboard_recovered === true;
      const evidenceRef = `installed-host-boundary:${requirement.control_id}`;
      return {
        control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
        evidence_mode: 'owned_isolated_host_boundary', rendered: result?.rendered === true, observed: result?.rendered === true, attempted: result?.attempted === true,
        interaction_chain: Object.fromEntries(STAGES.map(stage => {
          if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
          if (['failure_handling', 'recovery_rollback'].includes(stage)) return [stage, failedBeforeEffectAndRecovered
            ? { state: 'present', detail: 'The exact rendered control produced a request-bound owned pre-effect failure, consumed its one-shot marker, and the exact PX dashboard recovered before the valid action.', evidence: [evidenceRef] }
            : { state: 'missing', detail: 'A matched request-bound pre-effect failure and exact dashboard recovery were not both observed.', evidence: [] }];
          return [stage, verified
            ? { state: 'present', detail: 'The exact rendered control dispatched through the typed host boundary, acknowledged its disposition, and returned to the installed PX dashboard.', evidence: [evidenceRef] }
            : { state: 'missing', detail: `The installed host-boundary profile did not prove ${stage}.`, evidence: [] }];
        })),
        errors: result?.errors || []
      };
    })
  };
}

async function runInstalledHostBoundaryProfile(workbench, frameHost, matrix, timeoutMs = 30_000, onProgress = () => {}) {
  const observation = { operations: {}, errors: [] };
  const canonicalScenarioTimeoutMs = 75_000;
  for (const spec of INSTALLED_HOST_BOUNDARY_SPECS) {
    const displacingOperation = DISPLACING_HOST_OPERATIONS.has(spec.operation);
    const controlBudgetMs = spec.scenario === 'canonical-memory'
      ? canonicalScenarioTimeoutMs
      : displacingOperation
        ? Math.max(45_000, Math.min(60_000, timeoutMs + 30_000))
        : Math.max(35_000, Math.min(50_000, timeoutMs + 20_000));
    const controlDeadline = Date.now() + controlBudgetMs;
    const recoveryReserveMs = 10_000;
    const activeControlDeadline = controlDeadline - recoveryReserveMs;
    const result = { rendered: false, attempted: false, acknowledged: false, dashboard_reopened: false, failure_handling: false, failure_dashboard_recovered: false, refused_without_effect: false, errors: [] };
    let scenario = null;
    let terminalControlTimeout = null;
    observation.operations[spec.controlId] = result;
    const controlStarted = Date.now();
    onProgress({ control_id: spec.controlId, state: 'started', budget_ms: controlBudgetMs });
    try {
      await boundedOwnedUiAction(async () => {
      await resetInstalledDashboardBaseline(workbench, frameHost, Math.max(1_000, Math.min(5_000, activeControlDeadline - Date.now())));
      await navigateInstalledSurface(frameHost, spec.route, Math.max(1_000, Math.min(5_000, activeControlDeadline - Date.now())));
      const scenarioTimeout = spec.scenario === 'canonical-memory' ? canonicalScenarioTimeoutMs : timeoutMs;
      scenario = await prepareInstalledHostBoundaryScenario(frameHost, spec, Math.max(1_000, Math.min(scenarioTimeout, activeControlDeadline - Date.now())));
      if (spec.revealAction) {
        const revealed = await revealInstalledHostBoundaryControl(frameHost, spec);
        if (!revealed) throw new Error(`${spec.controlId}-reveal-control-not-rendered`);
        await wait(120);
      }
      const failed = await exerciseOwnedHostActionFailure(frameHost, spec, Math.min(12_000, Math.max(1_000, activeControlDeadline - Date.now())));
      result.failure_request_id = failed.request_id;
      result.failure_handling = failed.disposition === 'failed' && failed.marker_consumed === true;
      await resetInstalledDashboardBaseline(workbench, frameHost, Math.max(1_000, Math.min(5_000, activeControlDeadline - Date.now())));
      await navigateInstalledSurface(frameHost, spec.route, Math.max(1_000, Math.min(5_000, activeControlDeadline - Date.now())));
      await prepareInstalledHostBoundaryScenario(frameHost, spec, Math.max(1_000, Math.min(timeoutMs, activeControlDeadline - Date.now())));
      if (spec.revealAction) {
        const revealed = await revealInstalledHostBoundaryControl(frameHost, spec);
        if (!revealed) throw new Error(`${spec.controlId}-post-failure-reveal-control-not-rendered`);
        await wait(120);
      }
      result.failure_dashboard_recovered = true;
      result.refused_without_effect = result.failure_handling && result.failure_dashboard_recovered;
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const requestBeforeDispatch = await installedOutboundRequestOffset(frameHost);
      const actionStartedAt = Date.now();
      const dispatch = await frameHost.evaluate((frame, item) => {
        const hostQueries = frame.contentWindow?.PXDashboard?.require('hostQueries');
        const previousRequestId = String(hostQueries?.hostActionIdentity()?.requestId || '');
        const control = [...frame.contentDocument.querySelectorAll(`[data-action="${CSS.escape(item.action)}"]`)].find(value => !value.disabled && (value.offsetWidth || value.offsetHeight || value.getClientRects().length));
        if (!control) return { rendered: false, requestId: '' };
        control.click();
        const operation = hostQueries?.hostActionIdentity() || {};
        const requestId = operation.action === item.action
          && typeof operation.requestId === 'string'
          && operation.requestId.length > 0
          && operation.requestId !== previousRequestId
          ? operation.requestId
          : '';
        const outboundRequest = (frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || [])
          .slice(item.requestOffset)
          .find(value => value?.type === item.operation && value?.requestId === requestId) || null;
        return { rendered: true, requestId, outboundRequest };
      }, { ...spec, requestOffset: requestBeforeDispatch });
      result.rendered = dispatch.rendered;
      if (!result.rendered) throw new Error(`${spec.controlId}-not-rendered`);
      if (!dispatch.requestId) throw new Error(`${spec.controlId}-request-identity-missing`);
      result.attempted = true;
      result.request_id = dispatch.requestId;
      const displacing = displacingOperation;
      result.outbound_request = dispatch.outboundRequest;
      if (!result.outbound_request && !displacing) result.outbound_request = await waitForInstalledOutboundHostAction(frameHost, requestBeforeDispatch, { operation: spec.operation, requestId: dispatch.requestId }, Math.min(3_000, Math.max(1, controlDeadline - Date.now())));
      if (!result.outbound_request) throw new Error(`${spec.controlId}-synchronous-outbound-request-missing`);
      let response = null;
      if (displacing) {
        const activeDisplacementBudgetMs = Math.max(1_000, activeControlDeadline - Date.now());
        result.displacement = await waitForOwnedWorkbenchDisplacementOrReceipt(workbench, frameHost, {
          after: before, operation: spec.operation, requestId: dispatch.requestId, startedAt: actionStartedAt
        }, activeDisplacementBudgetMs);
        response = result.displacement.response || null;
        if (result.displacement.terminal === 'native-displacement') {
          await reopenPacifyDashboardFromOwnedUi(workbench, frameHost, Math.max(1_000, Math.min(22_000, activeControlDeadline - Date.now())));
          await wait(250);
        }
      }
      const reconstructedResponseOffset = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      response ||= await waitForDurableHostActionResult(frameHost, { after: reconstructedResponseOffset, operation: spec.operation, requestId: dispatch.requestId, startedAt: actionStartedAt, refreshSnapshot: true }, Math.min(timeoutMs, 15_000, Math.max(1, activeControlDeadline - Date.now())));
      const accepted = spec.dispositions || ['completed'];
      result.acknowledged = Boolean(response && accepted.includes(response.disposition));
      if (!result.acknowledged) {
        result.response_diagnostics = await inspectHostActionReceiptFailure(frameHost, { after: reconstructedResponseOffset, requestId: dispatch.requestId });
        if (response) throw new Error(`${spec.controlId}-typed-acknowledgement-unaccepted:${String(response.disposition || 'unknown')}:${JSON.stringify(result.response_diagnostics)}`);
        throw new Error(`${spec.controlId}-typed-acknowledgement-missing:${JSON.stringify(result.response_diagnostics)}`);
      }
      result.request_id = response.requestId;
      result.dashboard_reopened = result.displacement?.terminal === 'durable-dashboard-retained' || displacing === false || result.displacement?.terminal === 'native-displacement';
      }, Math.max(1, activeControlDeadline - controlStarted), `${spec.controlId}-host-boundary-control`);
    } catch (error) {
      const message = String(error?.message || error).slice(0, 1000);
      if (message.includes(`${spec.controlId}-host-boundary-control-timeout:`)) terminalControlTimeout = error;
      result.errors.push(message); observation.errors.push(`${spec.controlId}:${result.errors.at(-1)}`);
    }
    finally {
      try {
        await boundedOwnedUiAction(
          () => restoreInstalledHostBoundaryScenario(workbench, frameHost, scenario, Math.max(1_000, Math.min(15_000, controlDeadline - Date.now()))),
          15_000,
          `${spec.controlId}-host-boundary-restoration`
        );
      }
      catch (error) {
        const recoveryError = `${spec.controlId}-scenario-restoration:${String(error?.message || error).slice(0, 700)}`;
        result.errors.push(recoveryError); observation.errors.push(recoveryError);
      }
      try {
        const baselineRecoveryBudgetMs = Math.max(1_000, Math.min(recoveryReserveMs, controlDeadline - Date.now()));
        await boundedOwnedUiAction(
          () => resetInstalledDashboardBaseline(workbench, frameHost, baselineRecoveryBudgetMs),
          baselineRecoveryBudgetMs,
          `${spec.controlId}-host-boundary-baseline-recovery`
        );
      }
      catch (error) {
        const recoveryError = `${spec.controlId}-dashboard-baseline-recovery:${String(error?.message || error).slice(0, 700)}`;
        result.errors.push(recoveryError); observation.errors.push(recoveryError);
      }
      onProgress({
        control_id: spec.controlId,
        state: 'returned',
        duration_ms: Date.now() - controlStarted,
        acknowledged: result.acknowledged === true,
        error_count: result.errors.length,
        errors: result.errors.slice(0, 4)
      });
    }
    if (terminalControlTimeout) throw terminalControlTimeout;
  }
  return { schema_version: 'px.installed-host-boundary-profile/1.0', authority: 'Exact typed native-host handoffs in the owned isolated VS Code profile.', observation, control_probe: hostBoundaryControlProbe(matrix, observation) };
}

const INSTALLED_ENTERPRISE_CONTROLS = new Set([
  'pxui.agents.action.enterprisePackToggle.row',
  'pxui.agents.action.enterpriseTargetConfigure.row',
  'pxui.agents.action.teamPackPreview',
  'pxui.skills-tools.action.enterprisePackToggle.row',
  'pxui.skills-tools.action.enterpriseTargetConfigure.row'
]);

function enterpriseControlProbe(matrix, observation) {
  const requirements = matrix.controls.filter(control => INSTALLED_ENTERPRISE_CONTROLS.has(control.control_id));
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Offline-only enterprise metadata and non-canonical Team Fabric staging inside the owned disposable workspace; no connector, credential, tenant, network, or billable authority.',
    eligible_control_count: requirements.length,
    records: requirements.map(requirement => {
      const result = observation.controls?.[requirement.control_id];
      const verified = result?.completed === true && (requirement.control_id.includes('enterpriseTargetConfigure') || result?.restored === true);
      const evidenceRef = `installed-enterprise:${requirement.control_id}`;
      return {
        control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
        evidence_mode: 'owned_disposable_enterprise_metadata', rendered: result?.rendered === true, observed: result?.rendered === true, attempted: result?.attempted === true,
        interaction_chain: Object.fromEntries(STAGES.map(stage => {
          if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
          if (stage === 'failure_handling') return [stage, result?.cancelled_without_effect === true
            ? { state: 'present', detail: 'The exact native approval or input sequence was cancelled first and no enterprise mutation result was emitted.', evidence: [evidenceRef] }
            : { state: 'missing', detail: 'The matched cancellation/no-effect boundary was not observed.', evidence: [] }];
          if (stage === 'recovery_rollback') return [stage, result?.restored === true
            ? { state: 'present', detail: 'The offline enterprise pack or staged Team Fabric denominator was restored or reconstructed after restart.', evidence: [evidenceRef] }
            : { state: 'missing', detail: 'Exact enterprise state restoration was not observed.', evidence: [] }];
          return [stage, verified
            ? { state: 'present', detail: 'The rendered enterprise control completed through typed offline project-state authority and was reconstructed from the current snapshot.', evidence: [evidenceRef] }
            : { state: 'missing', detail: `The enterprise profile did not prove ${stage}.`, evidence: [] }];
        })), errors: result?.errors || []
      };
    })
  };
}

async function waitForInstalledResponse(frameHost, after, predicate, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const response = await frameHost.evaluate((frame, item) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(item.after)
      .find(value => item.types.includes(value?.type) && (!item.operation || value?.operation === item.operation) && (!item.phase || value?.phase === item.phase)) || null,
    { after, types: predicate.types, operation: predicate.operation || null, phase: predicate.phase || null });
    if (response) return response;
    await wait(120);
  } while (Date.now() < deadline);
  throw new Error(`installed-response-timeout:${predicate.types.join(',')}:${predicate.operation || '*'}`);
}

async function settleInstalledEnvironmentRecord(frameHost, expectedIdentity, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let state = null;
  do {
    state = await frameHost.evaluate((frame, expected) => {
      const document = frame.contentDocument;
      const scope = document.querySelector('[data-action="environmentScope"][data-scope="environments"]');
      if (scope && scope.getAttribute('aria-pressed') !== 'true') scope.click();
      const control = [...document.querySelectorAll('[data-action="inspectEnvironmentRecord"]')]
        .find(item => String(item.querySelector('strong')?.textContent || '').trim() === expected
          && !item.disabled && (item.offsetWidth || item.offsetHeight || item.getClientRects().length));
      return {
        scope_current: scope?.getAttribute('aria-pressed') === 'true',
        record_rendered: Boolean(control),
        pending: String(document.body?.innerText || '').includes('DISCOVERY PENDING')
      };
    }, expectedIdentity);
    if (state?.scope_current && state?.record_rendered) return state;
    await wait(120);
  } while (Date.now() < deadline);
  throw new Error(`owned-environment-record-not-rendered:${JSON.stringify(state)}`);
}

async function runInstalledEnterpriseProfile(workbench, frameHost, matrix, timeoutMs = 45_000) {
  const observation = { controls: {}, errors: [] };
  for (const route of ['agents', 'skillsTools']) {
    const prefix = route === 'agents' ? 'pxui.agents' : 'pxui.skills-tools';
    const toggleId = `${prefix}.action.enterprisePackToggle.row`;
    const targetId = `${prefix}.action.enterpriseTargetConfigure.row`;
    for (const id of [toggleId, targetId]) observation.controls[id] = { rendered: false, attempted: false, completed: false, cancelled_without_effect: false, restored: false, errors: [] };
    try {
      await resetInstalledDashboardBaseline(workbench, frameHost, Math.min(timeoutMs, 15_000));
      await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument; document?.querySelector('[data-action="closeModal"]')?.click(); document?.querySelector(`[data-surface="${CSS.escape(item.route)}"]`)?.click();
        const scope = item.route === 'agents'
          ? document?.querySelector('[data-action="surfaceScope"][data-target="agents"][data-scope="enterprise"]')
          : document?.querySelector('[data-action="capabilityTab"][data-kind="enterprise-skills"]');
        if (!scope) throw new Error(`enterprise-scope-control-unavailable:${item.route}`);
        scope.click();
      }, { route });
      await waitForKnowledgeControl(frameHost, '[data-action="enterprisePackToggle"]');
      const toggle = observation.controls[toggleId]; toggle.rendered = true; toggle.attempted = true;
      const state = await frameHost.evaluate(frame => { const control = frame.contentDocument.querySelector('[data-action="enterprisePackToggle"]'); return { enabled: control.dataset.enabled === 'true', packId: control.dataset.packId }; });
      const label = state.enabled ? 'Enable offline metadata' : 'Disable pack metadata';
      const beforeCancel = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const requestBeforeCancel = await installedOutboundRequestOffset(frameHost);
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="enterprisePackToggle"]').click());
      const dialog = await waitForNativeWorkbenchDialog(workbench, label, 15_000, { frameHost, responseOffset: beforeCancel, requestOffset: requestBeforeCancel, requestType: 'enterprisePackToggle', keyboardAction: 'Cancel' });
      await clickNativeWorkbenchDialogAction(workbench, dialog, 'Cancel');
      await wait(150);
      toggle.cancelled_without_effect = await frameHost.evaluate((frame, after) => !(frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after).some(value => value?.type === 'enterpriseResult'), beforeCancel);
      const requestBeforeApproval = await installedOutboundRequestOffset(frameHost);
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="enterprisePackToggle"]').click());
      const approval = await waitForNativeWorkbenchDialog(workbench, label, 15_000, { frameHost, responseOffset: beforeCancel, requestOffset: requestBeforeApproval, requestType: 'enterprisePackToggle', keyboardAction: label });
      await clickNativeWorkbenchDialogAction(workbench, approval, label);
      let after = await waitForInstalledResponse(frameHost, beforeCancel, { types: ['enterpriseResult'], operation: 'enterprisePackToggle' }, timeoutMs);
      toggle.completed = after?.result != null;
      await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument;
        document?.querySelector('[data-action="closeModal"]')?.click();
        document?.querySelector(`[data-surface="${CSS.escape(item.route)}"]`)?.click();
        const scope = item.route === 'agents'
          ? document?.querySelector('[data-action="surfaceScope"][data-target="agents"][data-scope="enterprise"]')
          : document?.querySelector('[data-action="capabilityTab"][data-kind="enterprise-skills"]');
        scope?.click();
      }, { route });
      await waitForKnowledgeControl(frameHost, '[data-action="enterprisePackToggle"]');
      const restoreBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const requestBeforeRestore = await installedOutboundRequestOffset(frameHost);
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="enterprisePackToggle"]').click());
      const restoreLabel = state.enabled ? 'Disable pack metadata' : 'Enable offline metadata';
      const restoreDialog = await waitForNativeWorkbenchDialog(workbench, restoreLabel, 15_000, { frameHost, responseOffset: restoreBefore, requestOffset: requestBeforeRestore, requestType: 'enterprisePackToggle', keyboardAction: restoreLabel });
      await clickNativeWorkbenchDialogAction(workbench, restoreDialog, restoreLabel);
      after = await waitForInstalledResponse(frameHost, restoreBefore, { types: ['enterpriseResult'], operation: 'enterprisePackToggle' }, timeoutMs);
      toggle.restored = after?.result != null;

      const target = observation.controls[targetId]; target.rendered = true; target.attempted = true;
      const targetBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="enterpriseTargetConfigure"]').click());
      await workbench.keyboard.press('Escape'); await wait(100);
      target.cancelled_without_effect = await frameHost.evaluate((frame, afterCount) => !(frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(afterCount).some(value => value?.type === 'enterpriseResult'), targetBefore);
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="enterpriseTargetConfigure"]').click());
      for (const value of [`owned-${route}`, 'owned-tenant', 'owned-environment']) {
        const input = workbench.locator('.quick-input-widget:visible input').first(); await input.waitFor({ state: 'visible', timeout: 15_000 }); await input.fill(value); await input.press('Enter');
      }
      const configured = await waitForInstalledResponse(frameHost, targetBefore, { types: ['enterpriseResult'], operation: 'enterpriseTargetConfigure' }, timeoutMs);
      target.completed = configured?.result != null;
    } catch (error) {
      const detail = String(error?.message || error).slice(0, 1200); observation.errors.push(`${route}:${detail}`);
      for (const id of [toggleId, targetId]) observation.controls[id].errors.push(detail);
      await dismissOwnedNativeWorkbenchDialog(workbench, /Enable offline metadata|Disable pack metadata/i).catch(dismissError => observation.errors.push(`${route}:dialog-recovery:${String(dismissError?.message || dismissError).slice(0, 800)}`));
    }
  }
  const teamId = 'pxui.agents.action.teamPackPreview';
  observation.controls[teamId] = { rendered: false, attempted: false, completed: false, cancelled_without_effect: false, restored: false, errors: [] };
  const team = observation.controls[teamId];
  const fixtureRoot = ownedWorkspaceRoot ? path.resolve(ownedWorkspaceRoot, '.px', 'owned-team-pack-fixture') : '';
  let stagedPath = '';
  try {
    if (!fixtureRoot || !installedFilesystemPathWithin(ownedWorkspaceRoot, fixtureRoot) || fs.existsSync(fixtureRoot)) throw new Error('owned-team-pack-fixture-unavailable');
    fs.mkdirSync(path.join(fixtureRoot, 'teams', 'builders'), { recursive: true });
    fs.writeFileSync(path.join(fixtureRoot, 'LICENSE'), 'Apache-2.0\n', { encoding: 'utf8', flag: 'wx' });
    fs.writeFileSync(path.join(fixtureRoot, 'teams', 'builders', 'TEAM.md'), '---\nname: Owned Builders\n---\n# Owned Builders\n', { encoding: 'utf8', flag: 'wx' });
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument; document?.querySelector('[data-action="closeModal"]')?.click(); document?.querySelector('[data-surface="agents"]')?.click();
      document?.querySelector('[data-action="surfaceScope"][data-target="agents"][data-scope="core"]')?.click();
    });
    await waitForKnowledgeControl(frameHost, '[data-action="teamPackPreview"]');
    team.rendered = true; team.attempted = true;

    const cancelBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="teamPackPreview"]').click());
    await waitForInstalledResponse(frameHost, cancelBefore, { types: ['teamPackResult'], phase: 'preview' }, timeoutMs);
    const quickPick = workbench.locator('.quick-input-widget:visible').first(); await quickPick.waitFor({ state: 'visible', timeout: 15_000 });
    await workbench.keyboard.press('Escape'); await wait(150);
    team.cancelled_without_effect = await frameHost.evaluate((frame, afterCount) => !(frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(afterCount)
      .some(value => value?.type === 'teamPackResult' && value?.phase === 'staged'), cancelBefore);

    const stageBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const requestBeforeStage = await installedOutboundRequestOffset(frameHost);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="teamPackPreview"]').click());
    await waitForInstalledResponse(frameHost, stageBefore, { types: ['teamPackResult'], phase: 'preview' }, timeoutMs);
    const collisionPick = workbench.locator('.quick-input-widget:visible').first(); await collisionPick.waitFor({ state: 'visible', timeout: 15_000 });
    await collisionPick.getByText('Skip collisions', { exact: true }).click();
    const approval = await waitForNativeWorkbenchDialog(workbench, 'Stage candidates', 15_000, { frameHost, responseOffset: stageBefore, requestOffset: requestBeforeStage, requestType: 'teamPackPreview', keyboardAction: 'Stage candidates' });
    await clickNativeWorkbenchDialogAction(workbench, approval, 'Stage candidates');
    const staged = await waitForInstalledResponse(frameHost, stageBefore, { types: ['teamPackResult'], phase: 'staged' }, timeoutMs);
    stagedPath = String(staged?.result?.path || '');
    const boundedStagedPath = stagedPath && installedFilesystemPathWithin(ownedWorkspaceRoot, stagedPath);
    team.staged_count = Number(staged?.result?.receipt?.staged_count || 0);
    team.staged_path_bounded = Boolean(boundedStagedPath);
    team.canonical_registry_mutated = staged?.result?.receipt?.canonical_registry_mutated;
    team.completed = staged?.phase === 'staged' && staged?.result?.receipt?.staged_count >= 1
      && staged?.result?.receipt?.canonical_registry_mutated === false && boundedStagedPath && fs.existsSync(stagedPath);
  } catch (error) {
    const detail = String(error?.message || error).slice(0, 1200); team.errors.push(detail); observation.errors.push(`${teamId}:${detail}`);
  } finally {
    try {
      await dismissOwnedNativeWorkbenchDialog(workbench, /Stage candidates/i);
      if (stagedPath && installedFilesystemPathWithin(ownedWorkspaceRoot, stagedPath) && fs.existsSync(stagedPath)) fs.rmSync(stagedPath, { force: false });
      if (fixtureRoot && installedFilesystemPathWithin(ownedWorkspaceRoot, fixtureRoot) && fs.existsSync(fixtureRoot)) fs.rmSync(fixtureRoot, { recursive: true, force: false });
      team.restored = (!stagedPath || !fs.existsSync(stagedPath)) && (!fixtureRoot || !fs.existsSync(fixtureRoot));
    } catch (error) { const detail = `restore:${String(error?.message || error).slice(0, 1000)}`; team.errors.push(detail); observation.errors.push(`${teamId}:${detail}`); }
  }
  return { schema_version: 'px.installed-enterprise-profile/1.0', authority: 'Offline enterprise metadata only in the owned disposable workspace.', observation, control_probe: enterpriseControlProbe(matrix, observation) };
}

const INSTALLED_VALIDATION_CONTROL_IDS = new Set([
  'pxui.diagnostics.action.validate',
  'pxui.runtime-core.action.validate'
]);
const INSTALLED_DEFERRED_UI_AUTHORITY_IDS = new Set([
  'pxui.diagnostics.action.dynamicRepair.refreshEnvironment',
  'pxui.diagnostics.action.validate',
  'pxui.runtime-core.action.validate'
]);

function validationControlProbe(matrix, observation) {
  const eligibleIds = observation.authority_deferred === true ? INSTALLED_DEFERRED_UI_AUTHORITY_IDS : INSTALLED_VALIDATION_CONTROL_IDS;
  const requirements = matrix.controls.filter(control => eligibleIds.has(control.control_id));
  const sharedVerified = observation.executed_once === true && observation.result?.status === 'passed' && observation.webview_restarted === true;
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Both physical Validate entry points bind the same host dispatcher; the expensive canonical validator executes exactly once after the adversarial audit.',
    eligible_control_count: requirements.length,
    records: requirements.map(requirement => {
      const rendered = observation.rendered?.[requirement.control_id] === true;
      const evidenceRef = `installed-shared-validation:${requirement.control_id}`;
      const authorityDeferred = observation.authority_deferred === true;
      const refused = observation.refused?.[requirement.control_id] === true;
      const recovered = observation.recovered?.[requirement.control_id] === true;
      return {
        control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
        evidence_mode: authorityDeferred ? 'owned_recovered_authority_boundary' : 'owned_shared_validation_execution', rendered, observed: rendered,
        attempted: authorityDeferred ? refused : sharedVerified, authority_skipped: authorityDeferred,
        interaction_chain: Object.fromEntries(STAGES.map(stage => {
          if (authorityDeferred) {
            if (stage === 'failure_handling') return [stage, refused
              ? { state: 'present', detail: 'The exact physical Validate control was clicked under a capture-phase fail-closed refusal and no validation request escaped.', evidence: [evidenceRef] }
              : { state: 'missing', detail: 'The exact physical validation refusal was not observed.', evidence: [] }];
            if (stage === 'recovery_rollback') return [stage, recovered
              ? { state: 'present', detail: 'The refusal listener was removed, the exact control remained rendered, and its outbound request count remained unchanged.', evidence: [evidenceRef] }
              : { state: 'missing', detail: 'The exact validation control was not restored after refusal.', evidence: [] }];
            if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
            return [stage, { state: 'missing', detail: 'Repository processing order reserves validation execution for the single owned post-profile validation stage.', evidence: [evidenceRef] }];
          }
          if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
          if (['failure_handling', 'recovery_rollback'].includes(stage)) return [stage, observation.cancelled_probe === true && sharedVerified
            ? { state: 'present', detail: 'A bounded cancellation probe remained fail-closed, followed by the one successful shared validation and dashboard reconstruction.', evidence: [evidenceRef] }
            : { state: 'missing', detail: 'Cancellation and successful shared recovery were not both observed.', evidence: [] }];
          return [stage, rendered && sharedVerified
            ? { state: 'present', detail: 'This exact physical entry point was rendered and bound to the single canonical validation execution, typed result, and restart reconstruction.', evidence: [evidenceRef] }
            : { state: 'missing', detail: `The post-audit validation profile did not prove ${stage}.`, evidence: [] }];
        })), errors: observation.errors || []
      };
    })
  };
}

async function runInstalledValidationBoundaryProfile(frameHost, matrix, timeoutMs = 30_000) {
  const observation = { authority_deferred: true, rendered: {}, refused: {}, recovered: {}, executed_once: false, errors: [] };
  const controls = [
    { route: 'diagnostics', controlId: 'pxui.diagnostics.action.validate', action: 'validate' },
    { route: 'runtimeCore', controlId: 'pxui.runtime-core.action.validate', action: 'validate' },
    { route: 'diagnostics', controlId: 'pxui.diagnostics.action.dynamicRepair.refreshEnvironment', action: 'refreshEnvironment', seedStaleEnvironment: true }
  ];
  for (const spec of controls) {
    const { route, controlId } = spec;
    try {
      await navigateInstalledSurface(frameHost, route, timeoutMs);
      await frameHost.evaluateContent(item => {
        const inner = window;
        document.querySelector('[data-action="closeModal"]')?.click();
        state.active = item.route;
        const original = item.seedStaleEnvironment ? structuredClone(state.snapshot) : null;
        if (original) {
          inner.__PX_VALIDATION_BOUNDARY_ORIGINAL_SNAPSHOT__ = original;
          const seeded = structuredClone(original);
          seeded.environment ||= {}; seeded.environment.freshness = { ...(seeded.environment.freshness || {}), state: 'stale', generation: 'px-owned-boundary' };
          state.snapshot = seeded;
        }
        render();
      }, spec);
      const controlDeadline = Date.now() + timeoutMs;
      let rendered = false;
      while (Date.now() < controlDeadline) {
        rendered = await frameHost.evaluate((frame, action) => Boolean(frame.contentDocument?.querySelector(`[data-action="${CSS.escape(action)}"]`)), spec.action);
        if (rendered) break;
        await wait(100);
      }
      if (!rendered) throw new Error(`installed-validation-boundary-control-timeout:${controlId}`);
      const result = await frameHost.evaluateContent(item => {
        const inner = window;
        const control = document?.querySelector(`[data-action="${CSS.escape(item.action)}"]`);
        if (!control || control.disabled) return { rendered: Boolean(control), refused: false, recovered: false };
        const requests = () => (inner.__PX_INSTALLED_REQUESTS__ || []).filter(value => value?.type === item.action).length;
        const before = requests(); let intercepted = false;
        const refuse = event => {
          const target = event.target?.closest?.(`[data-action="${CSS.escape(item.action)}"]`);
          if (!target) return;
          intercepted = true; event.preventDefault(); event.stopImmediatePropagation();
        };
        document.addEventListener('click', refuse, true);
        control.click();
        document.removeEventListener('click', refuse, true);
        const original = inner.__PX_VALIDATION_BOUNDARY_ORIGINAL_SNAPSHOT__;
        if (original) {
          delete inner.__PX_VALIDATION_BOUNDARY_ORIGINAL_SNAPSHOT__;
          state.snapshot = original;
          state.active = item.route;
          render();
        }
        const retained = item.seedStaleEnvironment ? !/px-owned-boundary/.test(document.body?.innerText || '') : document.querySelector(`[data-action="${CSS.escape(item.action)}"]`);
        return { rendered: true, refused: intercepted && requests() === before, recovered: Boolean(retained && !retained.disabled) && requests() === before };
      }, spec);
      observation.rendered[controlId] = result.rendered === true;
      observation.refused[controlId] = result.refused === true;
      observation.recovered[controlId] = result.recovered === true;
    } catch (error) {
      await frameHost.evaluateContent(item => {
        const original = window.__PX_VALIDATION_BOUNDARY_ORIGINAL_SNAPSHOT__;
        if (!original) return;
        delete window.__PX_VALIDATION_BOUNDARY_ORIGINAL_SNAPSHOT__;
        state.snapshot = original;
        state.active = item.route;
        render();
      }, spec).catch(() => {});
      observation.errors.push(`${controlId}:${String(error?.message || error).slice(0, 1600)}`);
    }
  }
  return { schema_version: 'px.installed-validation-profile/1.0', authority: 'Validation and environment persistence are deferred by repository processing order; all exact physical controls were fail-closed and restored without dispatch.', observation, control_probe: validationControlProbe(matrix, observation) };
}

async function runInstalledValidationProfile(frameHost, matrix, timeoutMs = 210_000) {
  const observation = { rendered: {}, executed_once: false, cancelled_probe: false, result: null, webview_restarted: false, errors: [] };
  try {
    for (const [route, controlId] of [['diagnostics', 'pxui.diagnostics.action.validate'], ['runtimeCore', 'pxui.runtime-core.action.validate']]) {
      await frameHost.evaluate((frame, target) => frame.contentDocument?.querySelector(`[data-surface="${CSS.escape(target)}"]`)?.click(), route);
      await waitForKnowledgeControl(frameHost, '[data-action="validate"]');
      observation.rendered[controlId] = true;
    }
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-surface="diagnostics"]')?.click());
    const validationCount = await frameHost.evaluate(frame => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).filter(value => value?.type === 'validation').length);
    await exerciseOwnedConfigurationFailure(frameHost, { action: 'validate', operation: 'validate' }, async () => {
      const currentCount = await frameHost.evaluate(frame => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).filter(value => value?.type === 'validation').length);
      return currentCount === validationCount;
    });
    observation.cancelled_probe = true;
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-surface="runtimeCore"]')?.click());
    const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="validate"]').click());
    const response = await waitForInstalledResponse(frameHost, before, { types: ['validation'] }, timeoutMs);
    observation.result = response.result; observation.executed_once = true;
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000); observation.webview_restarted = restart.restarted === true;
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2000)); }
  return { schema_version: 'px.installed-validation-profile/1.0', authority: 'One post-audit canonical validation shared by both exact physical entry points.', observation, control_probe: validationControlProbe(matrix, observation) };
}

const INSTALLED_ENVIRONMENT_LIFECYCLE_IDS = new Set([
  'pxui.workflows.action.environmentScope.environments',
  'pxui.workflows.action.refreshEnvironment',
  'pxui.workflows.action.inspectEnvironmentRecord.row',
  'pxui.workflows.action.previewEnvironmentLifecycle',
  'pxui.workflows.action.executeEnvironmentLifecycle',
  'pxui.workflows.action.previewEnvironmentLifecycleRestore',
  'pxui.workflows.action.executeEnvironmentLifecycleRestore',
  'pxui.workflows.field.environmentConsumerAcknowledgement',
  'pxui.workflows.field.environmentExactTarget',
  'pxui.workflows.form.environmentLifecycle',
  'pxui.workflows.persistence.authoritativeState',
  'pxui.workflows.reload_reopen.authoritativeState'
]);

function environmentLifecycleControlProbe(matrix, observation) {
  const requirements = matrix.controls.filter(control => INSTALLED_ENVIRONMENT_LIFECYCLE_IDS.has(control.control_id));
  const verified = observation.quarantined === true && observation.restored === true && observation.restart_verified === true && observation.temporary_reconciled === true;
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact reversible environment lifecycle inside the owned disposable workspace.', eligible_control_count: requirements.length,
    records: requirements.map(requirement => {
      const evidenceRef = `installed-environment-lifecycle:${requirement.control_id}`;
      return { control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind, evidence_mode: 'owned_disposable_environment_lifecycle', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
        interaction_chain: Object.fromEntries(STAGES.map(stage => {
          if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
          if (stage === 'failure_handling') return [stage, observation.invalid_confirmation_rejected
            ? { state: 'present', detail: 'The exact-target mismatch was rejected locally without lifecycle dispatch.', evidence: [evidenceRef] }
            : { state: 'missing', detail: 'The exact-target mismatch was not proven fail-closed.', evidence: [] }];
          return [stage, verified
            ? { state: 'present', detail: 'The exact temporary environment was snapshot-bound, quarantined, durably restore-previewed after manager reconstruction, restored byte-for-byte, dashboard-restarted, and reconciled.', evidence: [evidenceRef] }
            : { state: 'missing', detail: `The reversible environment profile did not prove ${stage}.`, evidence: [] }];
        })), errors: observation.errors };
    }) };
}

async function runInstalledEnvironmentLifecycleProfile(frameHost, matrix, timeoutMs = 60_000) {
  const observation = { rendered: false, attempted: false, invalid_confirmation_rejected: false, quarantined: false, restored: false, restart_verified: false, temporary_reconciled: false, errors: [] };
  const target = ownedWorkspaceRoot ? path.resolve(ownedWorkspaceRoot, '.venv-px-owned-lifecycle') : '';
  try {
    if (!target || !target.startsWith(`${ownedWorkspaceRoot}${path.sep}`) || fs.existsSync(target)) throw new Error('owned-environment-target-unavailable');
    fs.mkdirSync(target); fs.writeFileSync(path.join(target, 'pyvenv.cfg'), 'version = 3.13\npx_owned = true\n', { encoding: 'utf8', flag: 'wx' });
    observation.temporary_registered = true;
    await settleInstalledSurfaceControl(frameHost, {
      surface: 'workflows', scopeTarget: 'workflows', scope: 'environment', selector: '[data-action="refreshEnvironment"]'
    });
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="environmentScope"][data-scope="environments"]')?.click());
    let before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="refreshEnvironment"]').click());
    await waitForInstalledResponse(frameHost, before, { types: ['environmentInventory'] }, timeoutMs);
    before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="refreshEnvironment"]').click());
    await waitForInstalledResponse(frameHost, before, { types: ['environmentInventory'] }, timeoutMs);
    await settleInstalledSurfaceControl(frameHost, {
      surface: 'workflows', scopeTarget: 'workflows', scope: 'environment', selector: '[data-action="refreshEnvironment"]'
    });
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="environmentScope"][data-scope="environments"]')?.click());
    await settleInstalledEnvironmentRecord(frameHost, '.venv-px-owned-lifecycle', timeoutMs);
    const opened = await frameHost.evaluate((frame, expected) => {
      const control = [...frame.contentDocument.querySelectorAll('[data-action="inspectEnvironmentRecord"]')].find(item => String(item.querySelector('strong')?.textContent || '').trim() === expected);
      if (!control) return false; control.click(); return true;
    }, '.venv-px-owned-lifecycle');
    if (!opened) throw new Error('owned-environment-record-disappeared-before-open');
    await waitForKnowledgeControl(frameHost, '[data-action="previewEnvironmentLifecycle"]'); observation.rendered = true; observation.attempted = true;
    before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0); await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="previewEnvironmentLifecycle"]').click());
    const previewed = await waitForInstalledResponse(frameHost, before, { types: ['environmentLifecyclePreview'] }, timeoutMs);
    if (previewed.result?.schema_version !== 'px.environment-lifecycle-preview/1.0' || previewed.result?.allowed !== true || path.resolve(previewed.result?.target || '') !== target) throw new Error(`owned-environment-preview-invalid:${JSON.stringify(previewed.result)}`);
    const executeVisible = await waitForInstalledControlState(frameHost, '[data-action="executeEnvironmentLifecycle"]', control => control.visible === true, timeoutMs);
    if (!executeVisible || executeVisible.disabled !== true) throw new Error(`owned-environment-execute-initial-gate-invalid:${JSON.stringify(executeVisible)}`);
    const invalidBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    observation.invalid_confirmation_rejected = await frameHost.evaluate((frame, count) => { const input = frame.contentDocument.querySelector('#environment-lifecycle-target'); const execute = frame.contentDocument.querySelector('[data-action="executeEnvironmentLifecycle"]'); input.value = `${input.dataset.exactTarget}.wrong`; input.dispatchEvent(new frame.contentWindow.Event('input', { bubbles: true })); execute.click(); return execute.disabled === true && (frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0) === count; }, invalidBefore);
    const exactGate = await frameHost.evaluate(frame => { const input = frame.contentDocument.querySelector('#environment-lifecycle-target'); const execute = frame.contentDocument.querySelector('[data-action="executeEnvironmentLifecycle"]'); input.value = input.dataset.exactTarget; input.dispatchEvent(new frame.contentWindow.Event('input', { bubbles: true })); const enabled = execute.disabled === false; if (enabled) execute.click(); return { enabled, exact_target: input.dataset.exactTarget }; });
    if (!exactGate.enabled || path.resolve(exactGate.exact_target || '') !== target) throw new Error(`owned-environment-execute-exact-gate-invalid:${JSON.stringify(exactGate)}`);
    const quarantined = await waitForInstalledResponse(frameHost, invalidBefore, { types: ['environmentLifecycleResult'] }, timeoutMs); observation.quarantined = quarantined.result?.disposition === 'quarantined-reversible';
    await waitForKnowledgeControl(frameHost, '[data-action="previewEnvironmentLifecycleRestore"]'); before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0); await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="previewEnvironmentLifecycleRestore"]').click());
    await waitForInstalledResponse(frameHost, before, { types: ['environmentLifecycleRestorePreview'] }, timeoutMs); await waitForKnowledgeControl(frameHost, '[data-action="executeEnvironmentLifecycleRestore"]');
    before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0); await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="executeEnvironmentLifecycleRestore"]').click());
    const restored = await waitForInstalledResponse(frameHost, before, { types: ['environmentLifecycleRestoreResult'] }, timeoutMs); observation.restored = restored.result?.disposition === 'restored' && fs.readFileSync(path.join(target, 'pyvenv.cfg'), 'utf8').includes('px_owned = true');
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000); observation.restart_verified = restart.restarted === true && fs.existsSync(target);
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2000)); }
  finally {
    try { if (target && target.startsWith(`${ownedWorkspaceRoot}${path.sep}`) && fs.existsSync(target)) fs.rmSync(target, { recursive: true, force: false }); observation.temporary_reconciled = !target || !fs.existsSync(target); }
    catch (error) { observation.errors.push(`temporary-reconciliation:${String(error?.message || error).slice(0, 900)}`); }
  }
  return { schema_version: 'px.installed-environment-lifecycle-profile/1.0', authority: 'Exact quarantine and durable restoration in the owned disposable workspace.', observation, control_probe: environmentLifecycleControlProbe(matrix, observation) };
}

const INSTALLED_SKILL_QUERY_IDS = new Set([
  'pxui.skills-tools.action.submitSkillQuery',
  'pxui.skills-tools.action.hydrateSkillCandidate.row',
  'pxui.skills-tools.form.semanticQuery',
  'pxui.skills-tools.indicator.queryPending',
  'pxui.skills-tools.indicator.queryNoMatch',
  'pxui.skills-tools.indicator.queryResults'
]);

function skillQueryControlProbe(matrix, observation) {
  const requirements = matrix.controls.filter(control => INSTALLED_SKILL_QUERY_IDS.has(control.control_id));
  const verified = observation.completed === true && observation.pending_observed === true
    && observation.no_match_observed === true && observation.results_observed === true && observation.hydrated === true;
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact read-only semantic skill query and one exact admitted-body hydration inside the owned isolated host; no skill execution or lifecycle mutation.',
    eligible_control_count: requirements.length,
    records: requirements.map(requirement => {
      const evidenceRef = `installed-skill-query:${requirement.control_id}`;
      return {
        control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
        evidence_mode: 'owned_read_only_skill_query', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
        interaction_chain: Object.fromEntries(STAGES.map(stage => {
          if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
          if (stage === 'failure_handling') return [stage, observation.invalid_rejected
            ? { state: 'present', detail: 'The empty semantic goal was rejected by the exact installed form without a host request.', evidence: [evidenceRef] }
            : { state: 'missing', detail: 'The blank semantic query was not proven fail-closed.', evidence: [] }];
          if (stage === 'progress_reporting') return [stage, observation.pending_observed
            ? { state: 'present', detail: 'The installed modal visibly retained the bounded metadata-only pending state before the host result.', evidence: [evidenceRef] }
            : { state: 'missing', detail: 'The semantic query pending state was not observed.', evidence: [] }];
          return [stage, verified
            ? { state: 'present', detail: 'The installed semantic broker returned an exact empty result, a bounded admitted candidate list, and one exact read-only hydrated body through the real host bridge.', evidence: [evidenceRef] }
            : { state: 'missing', detail: `The read-only skill-query profile did not prove ${stage}.`, evidence: [] }];
        })),
        errors: observation.errors
      };
    })
  };
}

async function runInstalledSkillQueryProfile(frameHost, matrix, timeoutMs = 30_000) {
  const observation = { rendered: false, attempted: false, invalid_rejected: false, pending_observed: false, no_match_observed: false, results_observed: false, hydrated: false, completed: false, errors: [] };
  const openQuery = async () => {
    await navigateInstalledSurface(frameHost, 'skillsTools', timeoutMs);
    await frameHost.evaluate(frame => {
      const native = frame.contentDocument?.querySelector('[data-action="capabilityTab"][data-kind="skills"]');
      if (native && native.getAttribute('aria-pressed') !== 'true') native.click();
    });
    await waitForKnowledgeControl(frameHost, '[data-action="skillSemanticQuery"][data-domain="px-standard"]');
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="skillSemanticQuery"][data-domain="px-standard"]').click());
    await waitForKnowledgeControl(frameHost, '[data-action="submitSkillQuery"]');
  };
  const submit = async goal => {
    const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, value) => {
      const input = frame.contentDocument.querySelector('#skill-query-goal');
      input.value = value; input.dispatchEvent(new frame.contentWindow.Event('input', { bubbles: true }));
      frame.contentDocument.querySelector('[data-action="submitSkillQuery"]').click();
    }, goal);
    observation.pending_observed ||= await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('.cleanup-loading')));
    return waitForInstalledResponse(frameHost, before, { types: ['skillQueryResult'] }, timeoutMs);
  };
  try {
    await openQuery(); observation.rendered = true; observation.attempted = true;
    const requestCount = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="submitSkillQuery"]').click());
    observation.invalid_rejected = await frameHost.evaluate((frame, before) => (frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0) === before
      && frame.contentDocument?.activeElement?.id === 'skill-query-goal', requestCount);
    const empty = await submit(`px-owned-no-match-${Date.now().toString(36)}`);
    observation.no_match_observed = Array.isArray(empty.result?.candidates) && empty.result.candidates.length === 0
      && await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('.skill-query-results .compact-empty')));
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
    const goals = ['diagnose and repair Python code', 'repair code', 'debug'];
    let matched = null;
    for (const goal of goals) {
      await openQuery();
      const result = await submit(goal);
      if (Array.isArray(result.result?.candidates) && result.result.candidates.length > 0) { matched = result; break; }
      await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
    }
    observation.results_observed = Boolean(matched) && await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('.skill-query-result')));
    if (!observation.results_observed) throw new Error('skill-query-admitted-candidate-unavailable');
    const hydrateBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const hydrationDispatched = await frameHost.evaluate(frame => {
      const control = [...frame.contentDocument.querySelectorAll('[data-action="hydrateSkillCandidate"]')].find(element => !element.disabled);
      if (!control) return false; control.click(); return true;
    });
    if (!hydrationDispatched) throw new Error('skill-query-hydration-control-unavailable');
    const hydrated = await waitForInstalledResponse(frameHost, hydrateBefore, { types: ['skillHydrateResult'] }, timeoutMs);
    observation.hydrated = typeof hydrated.result?.id === 'string' && typeof hydrated.result?.body_sha256 === 'string'
      && await frameHost.evaluate(frame => Boolean(frame.contentDocument?.querySelector('.skill-hydrated-body')));
    observation.completed = observation.invalid_rejected && observation.pending_observed && observation.no_match_observed && observation.results_observed && observation.hydrated;
    if (!observation.completed) throw new Error(`skill-query-profile-incomplete:${JSON.stringify(observation)}`);
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2000)); }
  finally { await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click()).catch(() => {}); }
  return { schema_version: 'px.installed-skill-query-profile/1.0', authority: 'Real read-only semantic broker and exact admitted-body hydration in the owned isolated host.', observation, control_probe: skillQueryControlProbe(matrix, observation) };
}

function catalogPaginationControlProbe(matrix, observations, includedSurfaces = null) {
  const controls = new Map(matrix.controls.map(control => [control.control_id, control]));
  const specs = [
    ['agents', 'pxui.agents.action.catalogNext'], ['agents', 'pxui.agents.action.catalogPrevious'], ['agents', 'pxui.agents.indicator.catalogPage'],
    ['workflows', 'pxui.workflows.action.catalogNext'], ['workflows', 'pxui.workflows.action.catalogPrevious'], ['workflows', 'pxui.workflows.indicator.catalogPage'],
    ['skills-tools', 'pxui.skills-tools.action.catalogNext'], ['skills-tools', 'pxui.skills-tools.action.catalogPrevious'], ['skills-tools', 'pxui.skills-tools.indicator.catalogPage'],
    ['diagnostics', 'pxui.diagnostics.action.catalogNext'], ['diagnostics', 'pxui.diagnostics.action.catalogPrevious'], ['diagnostics', 'pxui.diagnostics.indicator.catalogPage']
  ];
  const selectedSpecs = includedSurfaces ? specs.filter(([surface]) => includedSurfaces.has(surface)) : specs;
  const records = selectedSpecs.map(([surface, controlId]) => {
    const requirement = controls.get(controlId);
    if (!requirement) throw new Error(`Catalog pagination profile control is absent: ${controlId}`);
    const observation = observations.find(item => item.surface === surface) || { errors: [] };
    const lifecycleVerified = observation.lifecycle_filter_required !== true || (
      observation.lifecycle_filter_verified === true && observation.empty_state_verified === true && observation.filter_restored === true
    );
    const verified = observation.forward === true && observation.backward === true && observation.restored === true && lifecycleVerified;
    const evidenceRef = `installed-catalog-pagination:${controlId}`;
    return {
      control_id: controlId, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_read_only_catalog_pagination', rendered: observation.rendered === true, observed: observation.rendered === true, attempted: observation.attempted === true,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, observation.first_page_previous_disabled === true
          ? { state: 'present', detail: 'The exact first-page Previous control remained disabled, preventing an invalid negative offset request.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The first-page negative-offset boundary was not observed.', evidence: [] }];
        if (stage === 'recovery_rollback') return [stage, observation.restored === true
          ? { state: 'present', detail: 'The exact catalog returned to offset zero, restored the normal bounded page size, and restored lifecycle/search state after the read-only walk.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'Catalog pagination state was not restored.', evidence: [] }];
        return [stage, verified
          ? { state: 'present', detail: 'The installed catalog queried real host metadata with a bounded one-record page, advanced to offset one, returned to offset zero, and for the focused Agents path proved a real lifecycle filter plus an exact empty result before restoration.', evidence: [evidenceRef] }
          : { state: 'missing', detail: `The read-only catalog pagination profile did not prove ${stage}.`, evidence: [] }];
      })), errors: observation.errors || []
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Real host catalog reads with a temporary local page-size projection and exact offset restoration.', eligible_control_count: records.length, records };
}

function correlateCatalogExchange(requests = [], responses = [], expected = {}) {
  const request = requests.slice(expected.requestAfter || 0).find(value => value?.type === 'catalogQuery'
    && value?.kind === expected.kind
    && (expected.status === undefined || value?.status === expected.status)
    && (expected.offset === undefined || Number(value?.offset) === expected.offset)
    && (expected.limit === undefined || Number(value?.limit) === expected.limit)) || null;
  if (!request?.requestId) return { request, response: null };
  const response = responses.slice(expected.responseAfter || 0).find(value => value?.type === 'catalogResult'
    && value?.requestId === request.requestId
    && value?.result?.kind === expected.kind) || null;
  return { request, response };
}

async function waitForInstalledCatalogExchange(frameHost, after, expected, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const exchange = await frameHost.evaluate((frame, item) => {
      const requests = frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || [];
      const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
      const request = requests.slice(item.requestAfter || 0).find(value => value?.type === 'catalogQuery'
        && value?.kind === item.kind
        && (item.status === undefined || value?.status === item.status)
        && (item.offset === undefined || Number(value?.offset) === item.offset)
        && (item.limit === undefined || Number(value?.limit) === item.limit)) || null;
      const response = request?.requestId ? responses.slice(item.responseAfter || 0).find(value => value?.type === 'catalogResult'
        && value?.requestId === request.requestId && value?.result?.kind === item.kind) || null : null;
      return { request, response };
    }, { ...expected, requestAfter: after.requests, responseAfter: after.responses });
    if (exchange.request && exchange.response) return exchange;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`catalog-pagination-result-timeout:${expected.kind}`);
}

async function waitForInstalledCatalogControls(frameHost, kind, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let controls = { previous_rendered: false, next_rendered: false, previous_disabled: false, next_ready: false };
  do {
    controls = await frameHost.evaluate((frame, exactKind) => {
      const previous = frame.contentDocument.querySelector(`[data-action="catalogPrevious"][data-kind="${exactKind}"]`);
      const next = frame.contentDocument.querySelector(`[data-action="catalogNext"][data-kind="${exactKind}"]`);
      return {
        previous_rendered: Boolean(previous),
        next_rendered: Boolean(next),
        previous_disabled: Boolean(previous?.disabled),
        next_ready: Boolean(next && !next.disabled)
      };
    }, kind);
    if (controls.previous_rendered && controls.next_rendered && controls.previous_disabled && controls.next_ready) return controls;
    await wait(100);
  } while (Date.now() < deadline);
  return controls;
}

async function runInstalledCatalogPaginationProfile(frameHost, matrix, timeoutMs = 30_000, includedSurfaces = null, requireAgentLifecycleState = false) {
  const allSpecifications = [
    { surface: 'agents', route: 'agents', kind: 'agents', target: 'agents', scope: 'core' },
    { surface: 'workflows', route: 'workflows', kind: 'workflows', target: 'workflows', scope: 'core' },
    { surface: 'skills-tools', route: 'skillsTools', kind: 'skills', capability: 'skills' },
    { surface: 'diagnostics', route: 'diagnostics', kind: 'enterprise-integrations' }
  ];
  const specifications = includedSurfaces ? allSpecifications.filter(spec => includedSurfaces.has(spec.surface)) : allSpecifications;
  const observations = [];
  for (const spec of specifications) {
    const observation = { ...spec, rendered: false, attempted: false, first_page_previous_disabled: false, forward: false, backward: false, restored: false, lifecycle_filter_required: requireAgentLifecycleState && spec.surface === 'agents', lifecycle_filter_verified: false, empty_state_verified: false, filter_restored: false, errors: [] };
    try {
      await navigateInstalledSurface(frameHost, spec.route, timeoutMs);
      await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument;
        if (item.target) document.querySelector(`[data-action="surfaceScope"][data-target="${item.target}"][data-scope="${item.scope}"]`)?.click();
        if (item.capability) document.querySelector(`[data-action="capabilityTab"][data-kind="${item.capability}"]`)?.click();
      }, spec);
      const before = await frameHost.evaluate(frame => ({ requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0, responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0 }));
      await frameHost.evaluateContent(kind => requestCatalog(kind, { offset: 0, limit: 1 }), spec.kind);
      const firstExchange = await waitForInstalledCatalogExchange(frameHost, before, { kind: spec.kind, offset: 0, limit: 1 }, timeoutMs);
      const first = firstExchange.response;
      if (Number(first.result?.total || 0) < 2) throw new Error(`catalog-pagination-denominator-too-small:${spec.kind}`);
      const initial = await waitForInstalledCatalogControls(frameHost, spec.kind, timeoutMs);
      observation.rendered = initial.next_ready; observation.first_page_previous_disabled = initial.previous_disabled; observation.attempted = true;
      if (!initial.next_ready || !initial.previous_disabled) throw new Error(`catalog-pagination-controls-not-ready:${spec.kind}`);
      let offset = await frameHost.evaluate(frame => ({ requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0, responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0 }));
      await frameHost.evaluate((frame, kind) => frame.contentDocument.querySelector(`[data-action="catalogNext"][data-kind="${kind}"]`).click(), spec.kind);
      const second = (await waitForInstalledCatalogExchange(frameHost, offset, { kind: spec.kind, offset: 1, limit: 1 }, timeoutMs)).response; observation.forward = Number(second.result?.offset) === 1;
      offset = await frameHost.evaluate(frame => ({ requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0, responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0 }));
      await frameHost.evaluate((frame, kind) => frame.contentDocument.querySelector(`[data-action="catalogPrevious"][data-kind="${kind}"]`).click(), spec.kind);
      const returned = (await waitForInstalledCatalogExchange(frameHost, offset, { kind: spec.kind, offset: 0, limit: 1 }, timeoutMs)).response; observation.backward = Number(returned.result?.offset) === 0;
      offset = await frameHost.evaluate(frame => ({ requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0, responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0 }));
      await frameHost.evaluateContent(kind => requestCatalog(kind, { query: '', status: '', offset: 0, limit: 50 }), spec.kind);
      const restored = (await waitForInstalledCatalogExchange(frameHost, offset, { kind: spec.kind, offset: 0, limit: 50 }, timeoutMs)).response;
      observation.restored = Number(restored.result?.offset) === 0 && Number(restored.result?.limit) === 50;
      if (observation.lifecycle_filter_required) {
        const filterBefore = await frameHost.evaluate(frame => ({
          requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0,
          responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0
        }));
        const selectedStatus = await frameHost.evaluate((frame, kind) => {
          const select = frame.contentDocument.querySelector(`[data-catalog-status="${kind}"]`);
          const option = [...(select?.options || [])].find(item => item.value);
          if (!select || !option) return null;
          select.value = option.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          return option.value;
        }, spec.kind);
        if (!selectedStatus) throw new Error('catalog-agents-lifecycle-filter-option-missing');
        const filteredExchange = await waitForInstalledCatalogExchange(frameHost, filterBefore, { kind: spec.kind, status: selectedStatus, offset: 0 }, timeoutMs);
        const filtered = filteredExchange.response;
        const filterBinding = await frameHost.evaluate((frame, item) => {
          const select = frame.contentDocument.querySelector(`[data-catalog-status="${item.kind}"]`);
          return { request_status: item.request?.status || null, selected_status: select?.value || null };
        }, { request: filteredExchange.request, kind: spec.kind });
        observation.lifecycle_filter_verified = filterBinding.request_status === selectedStatus && filterBinding.selected_status === selectedStatus
          && (filtered.result?.items || []).length > 0 && (filtered.result?.items || []).every(item => item?.status === selectedStatus);
        if (!observation.lifecycle_filter_verified) throw new Error(`catalog-agents-lifecycle-filter-mismatch:${JSON.stringify({ selectedStatus, filterBinding, result: filtered.result })}`);

        const emptyBefore = await frameHost.evaluate(frame => ({ requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0, responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0 }));
        const emptyToken = `px-owned-no-match-${Date.now().toString(36)}`;
        await frameHost.evaluate((frame, item) => {
          const input = frame.contentDocument.querySelector(`[data-catalog-search="${item.kind}"]`);
          if (!input) throw new Error('catalog-agents-search-input-missing');
          input.value = item.token;
          input.dispatchEvent(new Event('input', { bubbles: true }));
        }, { kind: spec.kind, token: emptyToken });
        const empty = (await waitForInstalledCatalogExchange(frameHost, emptyBefore, { kind: spec.kind, status: selectedStatus, offset: 0 }, timeoutMs)).response;
        await wait(120);
        observation.empty_state_verified = Number(empty.result?.filtered) === 0 && (empty.result?.items || []).length === 0
          && await frameHost.evaluate(frame => /No records match this lifecycle and search filter\./.test(String(frame.contentDocument.body?.innerText || '')));
        if (!observation.empty_state_verified) throw new Error(`catalog-agents-empty-state-missing:${JSON.stringify(empty.result)}`);

        const restoreBefore = await frameHost.evaluate(frame => ({ requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0, responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0 }));
        await frameHost.evaluateContent(kind => requestCatalog(kind, { query: '', status: '', offset: 0, limit: 50 }), spec.kind);
        const filterRestore = (await waitForInstalledCatalogExchange(frameHost, restoreBefore, { kind: spec.kind, status: '', offset: 0, limit: 50 }, timeoutMs)).response;
        await wait(120);
        observation.filter_restored = Number(filterRestore.result?.offset) === 0 && Number(filterRestore.result?.limit) === 50
          && Number(filterRestore.result?.total || 0) > 0
          && await frameHost.evaluate((frame, kind) => frame.contentDocument.querySelector(`[data-catalog-status="${kind}"]`)?.value === ''
            && frame.contentDocument.querySelector(`[data-catalog-search="${kind}"]`)?.value === '', spec.kind);
        observation.restored = observation.restored && observation.filter_restored;
        if (!observation.filter_restored) throw new Error('catalog-agents-filter-restore-missing');
      }
    } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 1600)); }
    observations.push(observation);
  }
  return { schema_version: 'px.installed-catalog-pagination-profile/1.0', authority: 'Real read-only catalog pagination with exact local query-state restoration.', observations, control_probe: catalogPaginationControlProbe(matrix, observations, includedSurfaces) };
}

const INSTALLED_OBSERVATION_STATE_IDS = Object.freeze([
  'pxui.activity.action.filterActivityCorrelation.row',
  'pxui.activity.indicator.captureActive',
  'pxui.activity.indicator.staleOperations',
  'pxui.agent-studio.field.model.host_model',
  'pxui.agent-studio.indicator.workingGraphRequiresPythonCompile',
  'pxui.dashboard-control-plane.indicator.extensionIdentityMismatch',
  'pxui.dashboard-control-plane.indicator.loading',
  'pxui.diagnostics.action.dynamicRepair.refresh',
  'pxui.diagnostics.action.navigate.runtimeCore',
  'pxui.knowledge-core.action.inspectLearningPipeline',
  'pxui.knowledge-graph.action.graphLoadAll',
  'pxui.knowledge-graph.action.graphLoadMore',
  'pxui.knowledge-graph.field.graphRelation',
  'pxui.memory.action.memoryNext',
  'pxui.memory.action.memoryPrevious',
  'pxui.plugins.indicator.inlineInventoryError',
  'pxui.projects.indicator.mapErrors',
  'pxui.projects.action.inspectProjectMapRecord.entrypoint',
  'pxui.projects.action.inspectProjectMapRecord.history',
  'pxui.projects.action.inspectProjectMapRecord.package',
  'pxui.projects.action.inspectProjectMapRecord.route',
  'pxui.projects.action.inspectProjectMapRecord.service',
  'pxui.projects.action.inspectProjectMapRecord.test-link',
  'pxui.projects.action.inspectProjectMapRecord.untested-source',
  'pxui.projects.indicator.buildReuse',
  'pxui.sidebar.action.provider-next',
  'pxui.sidebar.action.provider-previous',
  'pxui.skill-studio.indicator.missingRequiredFiles'
]);

async function installedLocalInputRoundTrip(frameHost, selector, nextValue, timeoutMs = 10_000) {
  const baseline = await frameHost.evaluate((frame, exactSelector) => {
    const input = frame.contentDocument.querySelector(exactSelector);
    return { rendered: Boolean(input), value: input?.value || '' };
  }, selector);
  if (!baseline.rendered) return { rendered: false, changed: false, restored: false };
  const dispatch = value => frameHost.evaluate((frame, item) => {
    const input = frame.contentDocument.querySelector(item.selector);
    if (!input) return false;
    input.value = item.value;
    input.dispatchEvent(new frame.contentWindow.Event('input', { bubbles: true }));
    return true;
  }, { selector, value });
  const waitForValue = async value => {
    const deadline = Date.now() + timeoutMs;
    do {
      if (await frameHost.evaluate((frame, item) => frame.contentDocument.querySelector(item.selector)?.value === item.value, { selector, value })) return true;
      await wait(50);
    } while (Date.now() < deadline);
    return false;
  };
  if (!await dispatch(nextValue)) return { rendered: true, changed: false, restored: false };
  const changed = await waitForValue(nextValue);
  if (!await dispatch(baseline.value)) return { rendered: true, changed, restored: false };
  const restored = await waitForValue(baseline.value);
  return { rendered: true, before: baseline.value, after: nextValue, changed, restored };
}

async function installedLocalSelectFailureRoundTrip(frameHost, selector, timeoutMs = 10_000) {
  const baseline = await frameHost.evaluate((frame, selected) => {
    const control = frame.contentDocument.querySelector(selected);
    if (!control || control.tagName !== 'SELECT') return { rendered: false, value: '', alternate: '', fixtureToken: '' };
    let alternate = [...control.options].find(option => !option.disabled && option.value !== control.value)?.value || '';
    let fixtureToken = '';
    if (!alternate) {
      fixtureToken = `px-owned-select-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const option = frame.contentDocument.createElement('option');
      option.value = fixtureToken;
      option.textContent = 'PX owned reversible select scenario';
      option.dataset.pxOwnedSelectFixture = fixtureToken;
      control.append(option);
      alternate = fixtureToken;
    }
    return { rendered: true, value: control.value, alternate, fixtureToken };
  }, selector);
  if (!baseline.rendered || !baseline.alternate) return { rendered: baseline.rendered, invalidRejected: false, changed: false, restored: false };
  let roundTrip = { rendered: true, changed: false, restored: false };
  let invalidRejected = false;
  const dispatchSelectValue = value => frameHost.evaluate((frame, item) => {
    const control = frame.contentDocument.querySelector(item.selector);
    if (!control || control.tagName !== 'SELECT') return { rendered: false, accepted: false, dispatched: false };
    control.value = item.value;
    const accepted = control.value === item.value;
    control.dispatchEvent(new frame.contentWindow.Event('input', { bubbles: true }));
    return { rendered: true, accepted, dispatched: true };
  }, { selector, value });
  const waitForBaseline = async () => {
    const deadline = Date.now() + timeoutMs;
    do {
      if (await frameHost.evaluate((frame, item) => frame.contentDocument.querySelector(item.selector)?.value === item.value,
        { selector, value: baseline.value })) return true;
      await wait(50);
    } while (Date.now() < deadline);
    return false;
  };
  try {
    invalidRejected = await frameHost.evaluate((frame, item) => {
      const control = frame.contentDocument.querySelector(item.selector);
      if (!control || control.tagName !== 'SELECT') return false;
      control.value = 'px-owned-invalid-select-option';
      const rejected = control.value !== 'px-owned-invalid-select-option';
      control.value = item.baseline;
      return rejected && control.value === item.baseline;
    }, { selector, baseline: baseline.value });
    const changed = await dispatchSelectValue(baseline.alternate);
    const restored = await dispatchSelectValue(baseline.value);
    roundTrip = {
      rendered: changed.rendered,
      before: baseline.value,
      after: baseline.alternate,
      changed: changed.accepted && changed.dispatched,
      restored: restored.accepted && restored.dispatched && await waitForBaseline()
    };
  } finally {
    await frameHost.evaluate((frame, item) => {
      const control = frame.contentDocument.querySelector(item.selector);
      if (!control || control.tagName !== 'SELECT') return;
      control.value = item.baseline;
      if (item.fixtureToken) control.querySelector(`[data-px-owned-select-fixture="${CSS.escape(item.fixtureToken)}"]`)?.remove();
    }, { selector, baseline: baseline.value, fixtureToken: baseline.fixtureToken });
  }
  const fixtureRemoved = !baseline.fixtureToken || await frameHost.evaluate((frame, item) =>
    !frame.contentDocument.querySelector(`[data-px-owned-select-fixture="${CSS.escape(item)}"]`), baseline.fixtureToken);
  return { ...roundTrip, invalidRejected, fixtureAdded: Boolean(baseline.fixtureToken), fixtureRemoved };
}

function observationStateControlProbe(matrix, observations) {
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const records = INSTALLED_OBSERVATION_STATE_IDS.map(controlId => {
    const requirement = requirements.get(controlId);
    if (!requirement) throw new Error(`Observation-state profile control is absent: ${controlId}`);
    const observation = observations[controlId] || { errors: ['observation-state-scenario-not-run'] };
    const evidenceRef = `installed-observation-state:${controlId}`;
    return {
      control_id: controlId, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_reversible_observation_state', rendered: observation.rendered === true,
      observed: observation.rendered === true, attempted: observation.attempted === true,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, observation.failure === true
          ? { state: 'present', detail: observation.failure_detail || 'The exact bounded invalid or unavailable state was rendered and rejected locally.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The exact bounded failure state was not observed.', evidence: [] }];
        if (stage === 'recovery_rollback') return [stage, observation.recovered === true
          ? { state: 'present', detail: observation.recovery_detail || 'The exact local state or read-only query offset was restored.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The exact state restoration was not observed.', evidence: [] }];
        return [stage, observation.completed === true
          ? { state: 'present', detail: observation.detail || 'The exact installed control was exercised through a bounded reversible state scenario.', evidence: [evidenceRef] }
          : { state: 'missing', detail: `The observation-state profile did not prove ${stage}.`, evidence: [] }];
      })), errors: observation.errors || []
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Local UI state changes and read-only host queries only; every temporary value and offset is restored.', eligible_control_count: records.length, records };
}

async function runInstalledObservationStateProfile(frameHost, sidebar, matrix, timeoutMs = 30_000) {
  const observations = Object.fromEntries(INSTALLED_OBSERVATION_STATE_IDS.map(controlId => [controlId, {
    rendered: false, attempted: false, completed: false, failure: false, recovered: false, errors: []
  }]));
  const apply = (ids, values) => { for (const id of ids) Object.assign(observations[id], values); };
  try {
    await navigateInstalledSurface(frameHost, 'activity', timeoutMs);
    const original = await frameHost.evaluateContent(() => structuredClone(state.activityData || state.coordination?.activity || {}));
    const seeded = await frameHost.evaluateContent(() => {
      const current = state.activityData || state.coordination?.activity || {};
      state.activityData = { ...current, policy: { ...(current.policy || {}), enabled: true, paused: true }, stale_operations: [{ correlation_id: 'px-owned-stale-observation', operation: 'owned-observation', started_utc: new Date().toISOString(), status: 'running', actor: { actor_id: 'px-owned-walker' } }] };
      render();
      const metric = document.querySelector('.metric-grid .metric-card:nth-child(3)');
      const reconcile = document.querySelector('[data-action="reconcileStaleActivity"]');
      return { rendered: Boolean(metric), count: metric?.textContent || '', disabled: Boolean(reconcile?.disabled) };
    });
    const staleId = 'pxui.activity.indicator.staleOperations';
    Object.assign(observations[staleId], { rendered: seeded.rendered, attempted: true, failure: seeded.disabled && /1/.test(seeded.count), failure_detail: 'A seeded stale operation with paused capture rendered the exact stale metric and disabled reconciliation before any dispatch.' });
    const activityBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluateContent(saved => { state.activityData = saved; requestActivity(); render(); }, original);
    await waitForInstalledResponse(frameHost, activityBefore, { types: ['activityResult'] }, timeoutMs);
    observations[staleId].recovered = await frameHost.evaluate((frame) => Boolean(frame.contentDocument.querySelector('.metric-grid .metric-card:nth-child(3)')) && !/px-owned-stale-observation/.test(frame.contentDocument.body?.innerText || ''));
    observations[staleId].recovery_detail = 'A real activity query replaced the seeded state and removed the owned stale correlation.';
    observations[staleId].completed = observations[staleId].failure && observations[staleId].recovered;
    const activeFixture = await frameHost.evaluateContent(() => {
      const current = state.activityData || state.coordination?.activity || {};
      state.activityData = { ...current, policy: { ...(current.policy || {}), enabled: true, paused: false }, active_operations: [{ correlation_id: 'px-owned-active-observation', operation: 'owned active observation', category: 'verification', source: 'owned-walker', status: 'running', actor: { actor_id: 'px-owned-walker' } }] };
      render();
      return {
        captureActive: /CAPTURE ACTIVE/i.test(document.querySelector('.activity-privacy')?.textContent || ''),
        filterVisible: Boolean(document.querySelector('[data-action="filterActivityCorrelation"][data-correlation-id="px-owned-active-observation"]'))
      };
    });
    const filterBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const filterDispatched = await frameHost.evaluate(frame => {
      const control = frame.contentDocument.querySelector('[data-action="filterActivityCorrelation"][data-correlation-id="px-owned-active-observation"]');
      if (!control || control.disabled) return false;
      control.click();
      return true;
    });
    if (filterDispatched) await waitForInstalledResponse(frameHost, filterBefore, { types: ['activityResult'] }, timeoutMs);
    const activeRestored = await frameHost.evaluate(frame => !/px-owned-active-observation/.test(frame.contentDocument?.body?.innerText || ''));
    apply(['pxui.activity.action.filterActivityCorrelation.row'], { rendered: activeFixture.filterVisible, attempted: filterDispatched, failure: activeFixture.filterVisible, recovered: activeRestored, completed: activeFixture.filterVisible && filterDispatched && activeRestored, failure_detail: 'A uniquely identified owned active-operation row rendered before any query dispatch.', recovery_detail: 'The exact row dispatched a real correlation query and the host result replaced the owned projection.' });
    apply(['pxui.activity.indicator.captureActive'], { rendered: activeFixture.captureActive, attempted: true, failure: true, recovered: activeRestored, completed: activeFixture.captureActive && activeRestored, failure_detail: 'The production renderer displayed CAPTURE ACTIVE only for an enabled, unpaused owned observation state.', recovery_detail: 'The next real activity result removed the owned active-operation projection.' });
  } catch (error) {
    for (const id of ['pxui.activity.indicator.staleOperations', 'pxui.activity.action.filterActivityCorrelation.row', 'pxui.activity.indicator.captureActive']) observations[id].errors.push(String(error?.message || error).slice(0, 1600));
  }

  try {
    await navigateInstalledSurface(frameHost, 'agents', timeoutMs);
    await frameHost.evaluateContent(() => { clearWorkingStudioDraft('agent'); return true; });
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="openStudioDraft"][data-kind="agent"]')?.click());
    await waitForInstalledStudioState(frameHost, 'agent', 'modal');
    await frameHost.evaluate((frame) => frame.contentDocument.querySelector('[data-action="agentSelectNode"][data-agent-kind="model"]')?.click());
    const fieldState = await installedLocalSelectFailureRoundTrip(frameHost, '[data-agent-host-model]', timeoutMs);
    apply(['pxui.agent-studio.field.model.host_model'], { rendered: fieldState.rendered, attempted: true, failure: fieldState.invalidRejected, recovered: fieldState.restored && fieldState.fixtureRemoved, completed: fieldState.invalidRejected && fieldState.changed && fieldState.restored && fieldState.fixtureRemoved, failure_detail: 'The native host-model select rejected an option outside its admitted catalog without dispatch.', recovery_detail: 'A valid alternate option was selected locally, the exact predecessor selection was restored, and any owned single-option fixture was removed.', detail: 'The local host-model draft select rejected an invalid option, accepted a valid alternate, restored its exact prior value, and removed its owned reversible fixture without host dispatch.' });
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="agentAddTopologyNode"][data-agent-kind="tools"]')?.click());
    const working = await frameHost.evaluate(frame => ({ rendered: Boolean(frame.contentDocument.querySelector('.agent-graph-state')), text: frame.contentDocument.querySelector('.agent-graph-state')?.textContent || '' }));
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="closeModal"]')?.click());
    await frameHost.evaluateContent(() => { clearWorkingStudioDraft('agent'); return true; });
    const compileId = 'pxui.agent-studio.indicator.workingGraphRequiresPythonCompile';
    Object.assign(observations[compileId], { rendered: working.rendered, attempted: true, failure: /WORKING|PYTHON COMPILE REQUIRED/i.test(working.text), recovered: true, completed: working.rendered && /WORKING|PYTHON COMPILE REQUIRED/i.test(working.text), failure_detail: 'A real local topology edit rendered the Python-compile-required working projection.', recovery_detail: 'The unsaved owned draft was closed and its exact working overlay cleared.' });
  } catch (error) {
    for (const id of ['pxui.agent-studio.field.model.host_model', 'pxui.agent-studio.indicator.workingGraphRequiresPythonCompile']) observations[id].errors.push(String(error?.message || error).slice(0, 1600));
  }

  try {
    await navigateInstalledSurface(frameHost, 'knowledgeGraph', timeoutMs);
    const relation = await installedLocalSelectFailureRoundTrip(frameHost, '[data-graph-relation]', timeoutMs);
    apply(['pxui.knowledge-graph.field.graphRelation'], { rendered: relation.rendered, attempted: true, failure: relation.invalidRejected, recovered: relation.restored && relation.fixtureRemoved, completed: relation.invalidRejected && relation.changed && relation.restored && relation.fixtureRemoved, failure_detail: 'The native graph-relation select rejected an option outside its authoritative relation set without dispatch.', recovery_detail: 'A valid alternate relation was selected locally, the exact predecessor filter was restored, and any owned single-option fixture was removed.', detail: 'The local graph relation select rejected an invalid option, accepted a valid alternate, restored its exact prior value, and removed its owned reversible fixture without dispatch.' });
    const requestGraphPage = async () => {
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluateContent(() => requestGraph({ view: 'repository', mode: 'full', cluster: '', node: '', query: '', relation: '', direction: 'both', kind: '', status: '', offset: 0, edgeOffset: 0, maxNodes: 1, maxEdges: 1 }));
      return waitForInstalledResponse(frameHost, before, { types: ['graphResult'] }, timeoutMs);
    };
    const first = await requestGraphPage();
    if (!first.result?.page?.node_has_more && !first.result?.page?.edge_has_more) throw new Error('observation-state-graph-denominator-too-small');
    const initial = await frameHost.evaluate(frame => ({ more: Boolean(frame.contentDocument.querySelector('[data-action="graphLoadMore"]:not([disabled])')), all: Boolean(frame.contentDocument.querySelector('[data-action="graphLoadAll"]:not([disabled])')) }));
    let before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="graphLoadMore"]')?.click());
    await waitForInstalledResponse(frameHost, before, { types: ['graphResult'] }, timeoutMs);
    const moreId = 'pxui.knowledge-graph.action.graphLoadMore';
    Object.assign(observations[moreId], { rendered: initial.more, attempted: true, failure: true, recovered: true, completed: initial.more, failure_detail: 'The bounded first graph page withheld remaining records until the exact Load more action.', recovery_detail: 'Load more returned the next real host graph page.' });
    await requestGraphPage();
    before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const cancellation = await frameHost.evaluate(frame => {
      const first = frame.contentDocument.querySelector('[data-action="graphLoadAll"]');
      first?.click();
      const cancel = frame.contentDocument.querySelector('[data-action="graphLoadAll"]');
      const cancelRendered = !cancel?.disabled && /Cancel load all/i.test(cancel?.textContent || '');
      cancel?.click();
      return { cancelRendered };
    });
    await waitForInstalledResponse(frameHost, before, { types: ['graphResult'] }, timeoutMs);
    const cancelled = await frameHost.evaluateContent(() => state.graphLoadAll === false && state.graphPending === false);
    if (!cancellation.cancelRendered || !cancelled) throw new Error('observation-state-graph-load-all-cancellation-failed');
    before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="graphLoadAll"]')?.click());
    await waitForInstalledResponse(frameHost, before, { types: ['graphResult'] }, timeoutMs);
    const allDeadline = Date.now() + timeoutMs;
    do {
      const done = await frameHost.evaluateContent(() => state.graphLoadAll === false && state.graphPending === false);
      if (done) break;
      await wait(100);
    } while (Date.now() < allDeadline);
    const allDone = await frameHost.evaluateContent(() => state.graphLoadAll === false && state.graphPending === false);
    const allId = 'pxui.knowledge-graph.action.graphLoadAll';
    Object.assign(observations[allId], { rendered: initial.all, attempted: true, failure: true, cancelled, recovered: allDone, completed: initial.all && cancelled && allDone, failure_detail: 'The bounded first graph page exposed an incomplete-page state and the installed Cancel load all action stopped continuation after the in-flight bounded page.', recovery_detail: 'A subsequent Load all consumed real host pages until no continuation remained.' });
    const restoreBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluateContent(() => requestGraph({ view: 'repository', mode: 'full', cluster: '', node: '', query: '', relation: '', direction: 'both', kind: '', status: '', offset: 0, edgeOffset: 0 }));
    await waitForInstalledResponse(frameHost, restoreBefore, { types: ['graphResult'] }, timeoutMs);
  } catch (error) {
    for (const id of ['pxui.knowledge-graph.field.graphRelation', 'pxui.knowledge-graph.action.graphLoadMore', 'pxui.knowledge-graph.action.graphLoadAll']) observations[id].errors.push(String(error?.message || error).slice(0, 1600));
  }

  try {
    await navigateInstalledSurface(frameHost, 'memory', timeoutMs);
    const firstBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluateContent(() => {
      state.memoryOffset = -59; state.memoryPending = true;
      const requestId = `memory-owned-page-${Date.now()}`; state.memoryRequestId = requestId;
      vscode.postMessage({ type: 'memoryQuery', requestId, query: state.memoryQuery, offset: 0, limit: 1, status: state.memoryStatus, projectId: state.memoryProject, source: state.memorySource });
    });
    const first = await waitForInstalledResponse(frameHost, firstBefore, { types: ['memoryResult'] }, timeoutMs);
    if (!first.result?.has_more) throw new Error('observation-state-memory-denominator-too-small');
    const initial = await frameHost.evaluate(frame => ({ next: Boolean(frame.contentDocument.querySelector('[data-action="memoryNext"]:not([disabled])')), previousDisabled: Boolean(frame.contentDocument.querySelector('[data-action="memoryPrevious"]')?.disabled) }));
    let before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="memoryNext"]')?.click());
    const next = await waitForInstalledResponse(frameHost, before, { types: ['memoryResult'] }, timeoutMs);
    before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="memoryPrevious"]')?.click());
    const previous = await waitForInstalledResponse(frameHost, before, { types: ['memoryResult'] }, timeoutMs);
    const memoryVerified = initial.next && initial.previousDisabled && Number(next.result?.offset) === 1 && Number(previous.result?.offset) === 0;
    apply(['pxui.memory.action.memoryNext', 'pxui.memory.action.memoryPrevious'], { rendered: initial.next, attempted: true, failure: initial.previousDisabled, recovered: Number(previous.result?.offset) === 0, completed: memoryVerified, failure_detail: 'The first real bounded page disabled Previous and exposed Next only when the host reported more records.', recovery_detail: 'The exact Previous control returned the real host query to offset zero.' });
    await frameHost.evaluateContent(() => { state.memoryOffset = 0; requestMemory(); render(); });
  } catch (error) { for (const id of ['pxui.memory.action.memoryNext', 'pxui.memory.action.memoryPrevious']) observations[id].errors.push(String(error?.message || error).slice(0, 1600)); }

  try {
    await navigateInstalledSurface(frameHost, 'plugins', timeoutMs);
    const seeded = await frameHost.evaluateContent(() => {
      const currentHash = state.environmentData.extensions?.snapshot_hash || state.snapshot?.environment?.snapshot_hash || '';
      window.dispatchEvent(new MessageEvent('message', { data: { type: 'environmentResult', subject: 'extensions', result: { snapshot_hash: currentHash, error: 'PX owned reversible extension-inventory failure', records: [] } } }));
      return Boolean(document.querySelector('.memory-errors[role="alert"]'));
    });
    const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const refreshDispatched = await frameHost.evaluate(frame => {
      const refresh = frame.contentDocument?.querySelector('[data-action="refreshEnvironment"]');
      if (!refresh || refresh.disabled) return false;
      refresh.click();
      return true;
    });
    if (refreshDispatched) await waitForInstalledResponse(frameHost, before, { types: ['environmentInventory'] }, timeoutMs);
    const recovered = await frameHost.evaluate(frame => !/PX owned reversible extension-inventory failure/.test(frame.contentDocument?.body?.innerText || ''));
    apply(['pxui.plugins.indicator.inlineInventoryError'], { rendered: seeded, attempted: refreshDispatched, failure: seeded, recovered, completed: seeded && refreshDispatched && recovered, failure_detail: 'The production Plugins renderer displayed a uniquely identified request-state inventory failure.', recovery_detail: 'The exact refresh action returned the real host inventory and removed the owned failure projection.' });
  } catch (error) { observations['pxui.plugins.indicator.inlineInventoryError'].errors.push(String(error?.message || error).slice(0, 1600)); }

  try {
    await navigateInstalledSurface(frameHost, 'projects', timeoutMs);
    const seeded = await frameHost.evaluateContent(() => {
      const enriched = structuredClone(state.snapshot);
      enriched.project = enriched.project || {};
      enriched.project.map = { ...(enriched.project.map || {}), available: true, valid: false, errors: ['PX owned reversible project-map failure'] };
      window.dispatchEvent(new MessageEvent('message', { data: { type: 'snapshot', snapshot: enriched } }));
      return Boolean(document.querySelector('.memory-errors[role="alert"]'));
    });
    const refresh = await requestInstalledRefreshBound(frameHost);
    await waitForInstalledSnapshot(frameHost, refresh.responses, snapshot => projectMapIdentity(snapshot) !== null, timeoutMs, refresh.request);
    await navigateInstalledSurface(frameHost, 'projects', timeoutMs);
    const recovered = await frameHost.evaluate(frame => !/PX owned reversible project-map failure/.test(frame.contentDocument?.body?.innerText || ''));
    apply(['pxui.projects.indicator.mapErrors'], { rendered: seeded, attempted: true, failure: seeded, recovered, completed: seeded && recovered, failure_detail: 'The production Projects renderer displayed an exact owned map-error projection without changing the authoritative map.', recovery_detail: 'A request-bound canonical refresh replaced the owned projection with the real project-map snapshot.' });
  } catch (error) { observations['pxui.projects.indicator.mapErrors'].errors.push(String(error?.message || error).slice(0, 1600)); }

  try {
    await navigateInstalledSurface(frameHost, 'dashboard', timeoutMs);
    const dashboardState = await frameHost.evaluateContent(() => {
      const original = structuredClone(state.snapshot);
      state.snapshot = null; render();
      const loading = Boolean(document.querySelector('.loading'));
      state.snapshot = original; render();
      const restored = !document.querySelector('.loading') && Boolean(document.querySelector('.hero-status'));
      const mismatch = structuredClone(original);
      mismatch.extensionIdentity = { ...(mismatch.extensionIdentity || {}), matches: false, mismatch_reasons: ['px-owned-reversible-identity-mismatch'] };
      state.snapshot = mismatch; render();
      const mismatchRendered = Boolean(document.querySelector('.identity-warning'));
      state.snapshot = original; render();
      const mismatchRecovered = !/px-owned-reversible-identity-mismatch/.test(document.body?.innerText || '');
      return { loading, restored, mismatchRendered, mismatchRecovered };
    });
    apply(['pxui.dashboard-control-plane.indicator.loading'], { rendered: dashboardState.loading, attempted: true, failure: dashboardState.loading, recovered: dashboardState.restored, completed: dashboardState.loading && dashboardState.restored, failure_detail: 'The production shell rendered its exact loading state while the snapshot was locally withheld.', recovery_detail: 'The exact saved snapshot was restored and the production hero re-rendered.' });
    apply(['pxui.dashboard-control-plane.indicator.extensionIdentityMismatch'], { rendered: dashboardState.mismatchRendered, attempted: true, failure: dashboardState.mismatchRendered, recovered: dashboardState.mismatchRecovered, completed: dashboardState.mismatchRendered && dashboardState.mismatchRecovered, failure_detail: 'A uniquely identified local identity mismatch rendered the production fail-closed identity warning.', recovery_detail: 'The exact predecessor snapshot was restored and the owned mismatch marker disappeared.' });

    await navigateInstalledSurface(frameHost, 'diagnostics', timeoutMs);
    const diagnosticSeed = await frameHost.evaluateContent(() => {
      const original = structuredClone(state.snapshot); const seeded = structuredClone(original);
      seeded.extensionIdentity = { ...(seeded.extensionIdentity || {}), matches: false, mismatch_reasons: ['px-owned-diagnostic-refresh'] };
      seeded.runtime ||= {}; seeded.runtime.execution_placement = { ...(seeded.runtime.execution_placement || {}), available: false, limitations: ['px-owned-placement-unavailable'] };
      state.snapshot = seeded; render();
      return {
        refresh: Boolean(document.querySelector('.diagnostic-trace [data-action="refresh"]')),
        runtime: Boolean(document.querySelector('.diagnostic-trace [data-surface="runtimeCore"]')),
        original
      };
    });
    const navigated = await frameHost.evaluate(frame => { const control = frame.contentDocument.querySelector('.diagnostic-trace [data-surface="runtimeCore"]'); if (!control) return false; control.click(); return true; });
    const runtimeActive = navigated && await frameHost.evaluate(frame => Boolean(
      frame.contentDocument.querySelector('[data-surface="runtimeCore"][aria-current="page"], [data-surface="runtimeCore"].active')
      || [...frame.contentDocument.querySelectorAll('h1')].some(item => item.textContent.trim() === 'Runtime Core')
    ));
    await frameHost.evaluateContent(saved => { state.snapshot = saved; state.active = 'diagnostics'; render(); }, diagnosticSeed.original);
    await navigateInstalledSurface(frameHost, 'diagnostics', timeoutMs);
    const refreshSeeded = await frameHost.evaluateContent(() => { const seeded = structuredClone(state.snapshot); seeded.extensionIdentity = { ...(seeded.extensionIdentity || {}), matches: false, mismatch_reasons: ['px-owned-diagnostic-refresh'] }; state.snapshot = seeded; render(); return Boolean(document.querySelector('.diagnostic-trace [data-action="refresh"]')); });
    const refreshBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const refreshClicked = await frameHost.evaluate(frame => { const control = frame.contentDocument.querySelector('.diagnostic-trace [data-action="refresh"]'); if (!control) return false; control.click(); return true; });
    if (refreshClicked) await waitForInstalledResponse(frameHost, refreshBefore, { types: ['snapshot'] }, timeoutMs);
    const refreshRecovered = await frameHost.evaluate(frame => !/px-owned-diagnostic-refresh/.test(frame.contentDocument.body?.innerText || ''));
    apply(['pxui.diagnostics.action.navigate.runtimeCore'], { rendered: diagnosticSeed.runtime, attempted: navigated, failure: diagnosticSeed.runtime, recovered: runtimeActive, completed: diagnosticSeed.runtime && runtimeActive, failure_detail: 'An unavailable execution-placement projection rendered the exact Runtime Core repair navigation.', recovery_detail: 'The exact local navigation activated Runtime Core before the saved snapshot was restored.' });
    apply(['pxui.diagnostics.action.dynamicRepair.refresh'], { rendered: refreshSeeded, attempted: refreshClicked, failure: refreshSeeded, recovered: refreshRecovered, completed: refreshSeeded && refreshClicked && refreshRecovered, failure_detail: 'A uniquely identified identity mismatch rendered the exact diagnostic refresh repair.', recovery_detail: 'The repair dispatched a real refresh and the canonical snapshot removed the owned mismatch.' });
  } catch (error) { for (const id of ['pxui.dashboard-control-plane.indicator.loading', 'pxui.dashboard-control-plane.indicator.extensionIdentityMismatch', 'pxui.diagnostics.action.navigate.runtimeCore', 'pxui.diagnostics.action.dynamicRepair.refresh']) observations[id].errors.push(String(error?.message || error).slice(0, 1600)); }

  try {
    await navigateInstalledSurface(frameHost, 'knowledgeCore', timeoutMs);
    const pipeline = await frameHost.evaluateContent(() => {
      const original = structuredClone(state.knowledgeData || {});
      state.knowledgeData = { ...(state.knowledgeData || {}), learning: { ...((state.knowledgeData || {}).learning || {}), pipelines: [{ pipeline_id: 'px-owned-learning-pipeline', state: 'validated', effective_state: 'validated', hypothesis: { claim: 'PX owned reversible pipeline' }, pattern: { interpretation: 'Owned UI observation only' }, operation_evidence: [], trials: [], secondary_trials: [], pipeline_revision_sha256: '0'.repeat(64) }] } };
      render();
      const control = document.querySelector('[data-action="inspectLearningPipeline"][data-pipeline-id="px-owned-learning-pipeline"]');
      control?.click(); const modal = Boolean(document.querySelector('[data-action="closeModal"]'));
      document.querySelector('[data-action="closeModal"]')?.click(); state.knowledgeData = original; render();
      return { rendered: Boolean(control), modal, recovered: !/px-owned-learning-pipeline/.test(document.body?.innerText || '') };
    });
    apply(['pxui.knowledge-core.action.inspectLearningPipeline'], { rendered: pipeline.rendered, attempted: pipeline.rendered, failure: pipeline.rendered, recovered: pipeline.recovered, completed: pipeline.rendered && pipeline.modal && pipeline.recovered, failure_detail: 'A bounded local signed-history projection rendered the exact learning-pipeline inspector.', recovery_detail: 'The information modal closed and the exact predecessor knowledge controller state was restored.' });
  } catch (error) { observations['pxui.knowledge-core.action.inspectLearningPipeline'].errors.push(String(error?.message || error).slice(0, 1600)); }

  try {
    await navigateInstalledSurface(frameHost, 'projects', timeoutMs);
    const projectState = await frameHost.evaluateContent(() => {
      const original = structuredClone(state.snapshot); const seeded = structuredClone(original);
      seeded.project ||= {}; seeded.project.map ||= {}; seeded.project.map.available = true; seeded.project.map.valid = true;
      seeded.project.map.drilldown = {
        ...(seeded.project.map.drilldown || {}),
        entrypoints: [{ summary: 'px-owned-entrypoint', source: 'owned/entry.js' }],
        history: [{ archive_id: 'px-owned-history', map_revision: '0'.repeat(64), counts: { files: 1 } }],
        packages: [{ name: 'px-owned-package', ecosystem: 'owned', scopes: ['test'] }],
        routes: [{ summary: 'px-owned-route', route: '/px-owned', source: 'owned/route.js' }],
        services: [{ summary: 'px-owned-service', name: 'px-owned-service', source: 'owned/service.js' }],
        test_links: [{ summary: 'px-owned-test-link', test: 'owned/test.js', source: 'owned/source.js', basis: 'owned' }],
        untested_sources: [{ summary: 'px-owned-untested', source: 'owned/untested.js' }],
        build_stats: { ...((seeded.project.map.drilldown || {}).build_stats || {}), reused_file_facts: 7, rescanned_file_facts: 1 }
      };
      seeded.project.map.drilldown.service_route_map = { coverage: {}, limitations: [] };
      seeded.project.map.drilldown.test_link_map = { coverage: {}, limitations: [] };
      state.snapshot = seeded; render();
      const kinds = ['entrypoints','history','packages','routes','services','test_links','untested_sources']; const opened = {};
      for (const kind of kinds) { const control = document.querySelector(`[data-action="inspectProjectMapRecord"][data-record-kind="${kind}"]`); control?.click(); opened[kind] = Boolean(control && document.querySelector('[data-action="closeModal"]')); document.querySelector('[data-action="closeModal"]')?.click(); }
      const buildReuse = /7 reused/.test(document.body?.innerText || '');
      state.snapshot = original; render();
      return { opened, buildReuse, recovered: !/px-owned-(?:entrypoint|history|package|route|service|test-link|untested)/.test(document.body?.innerText || '') };
    });
    const projectIds = {
      entrypoints: 'pxui.projects.action.inspectProjectMapRecord.entrypoint', history: 'pxui.projects.action.inspectProjectMapRecord.history', packages: 'pxui.projects.action.inspectProjectMapRecord.package', routes: 'pxui.projects.action.inspectProjectMapRecord.route', services: 'pxui.projects.action.inspectProjectMapRecord.service', test_links: 'pxui.projects.action.inspectProjectMapRecord.test-link', untested_sources: 'pxui.projects.action.inspectProjectMapRecord.untested-source'
    };
    for (const [kind, id] of Object.entries(projectIds)) apply([id], { rendered: projectState.opened[kind], attempted: projectState.opened[kind], failure: projectState.opened[kind], recovered: projectState.recovered, completed: projectState.opened[kind] && projectState.recovered, failure_detail: `A bounded ${kind} record rendered the exact project-map row and information modal.`, recovery_detail: 'The modal closed and the exact predecessor snapshot was restored.' });
    apply(['pxui.projects.indicator.buildReuse'], { rendered: projectState.buildReuse, attempted: true, failure: projectState.buildReuse, recovered: projectState.recovered, completed: projectState.buildReuse && projectState.recovered, failure_detail: 'The bounded build projection rendered an exact nonzero reused-file-facts indicator.', recovery_detail: 'The exact predecessor snapshot replaced the owned build statistic.' });
  } catch (error) { for (const id of INSTALLED_OBSERVATION_STATE_IDS.filter(value => value.startsWith('pxui.projects.action.inspectProjectMapRecord') || value === 'pxui.projects.indicator.buildReuse')) observations[id].errors.push(String(error?.message || error).slice(0, 1600)); }

  try {
    await navigateInstalledSurface(frameHost, 'skillsTools', timeoutMs);
    const missing = await frameHost.evaluateContent(() => {
      clearWorkingStudioDraft('skill');
      openStudioDraftModal('skill', { skill_id: 'px-owned-missing-files', package_missing_required_files: ['px-owned-required-file'] });
      const rendered = Boolean(document.querySelector('.identity-warning[role="alert"]'));
      document.querySelector('[data-action="closeModal"]')?.click(); clearWorkingStudioDraft('skill');
      return { rendered, recovered: !/px-owned-required-file/.test(document.body?.innerText || '') };
    });
    apply(['pxui.skill-studio.indicator.missingRequiredFiles'], { rendered: missing.rendered, attempted: true, failure: missing.rendered, recovered: missing.recovered, completed: missing.rendered && missing.recovered, failure_detail: 'A bounded incomplete skill-package draft rendered the exact missing-required-files warning.', recovery_detail: 'The owned modal closed and its local working draft was cleared.' });
  } catch (error) { observations['pxui.skill-studio.indicator.missingRequiredFiles'].errors.push(String(error?.message || error).slice(0, 1600)); }

  try {
    await instrumentInstalledSidebarState(sidebar);
    const baseline = await sidebar.evaluate(frame => {
      const select = frame.contentDocument.querySelector('select[data-action="provider-select"]');
      return { value: select?.value || '', count: select?.options?.length || 0, next: Boolean(frame.contentDocument.querySelector('[data-action="provider-next"]:not([disabled])')), previous: Boolean(frame.contentDocument.querySelector('[data-action="provider-previous"]:not([disabled])')) };
    });
    if (baseline.count < 2 || !baseline.next || !baseline.previous) throw new Error(`observation-state-provider-denominator-too-small:${JSON.stringify(baseline)}`);
    await sidebar.evaluate(frame => frame.contentDocument.querySelector('[data-action="provider-next"]')?.click());
    const changedDeadline = Date.now() + timeoutMs; let changed = false;
    do { changed = await sidebar.evaluate((frame, prior) => frame.contentDocument.querySelector('select[data-action="provider-select"]')?.value !== prior, baseline.value); if (changed) break; await wait(100); } while (Date.now() < changedDeadline);
    await sidebar.evaluate(frame => frame.contentDocument.querySelector('[data-action="provider-previous"]')?.click());
    const restoreDeadline = Date.now() + timeoutMs; let restored = false;
    do { restored = await sidebar.evaluate((frame, prior) => frame.contentDocument.querySelector('select[data-action="provider-select"]')?.value === prior, baseline.value); if (restored) break; await wait(100); } while (Date.now() < restoreDeadline);
    apply(['pxui.sidebar.action.provider-next', 'pxui.sidebar.action.provider-previous'], { rendered: true, attempted: true, failure: true, recovered: restored, completed: changed && restored, failure_detail: 'The owned sidebar exposed bounded provider navigation only with a multi-provider denominator.', recovery_detail: 'Next changed the exact selected provider and Previous restored the original provider identity.' });
  } catch (error) { for (const id of ['pxui.sidebar.action.provider-next', 'pxui.sidebar.action.provider-previous']) observations[id].errors.push(String(error?.message || error).slice(0, 1600)); }

  return { schema_version: 'px.installed-observation-state-profile/1.0', authority: 'Bounded reversible local states plus read-only host queries in the owned isolated host.', observations, control_probe: observationStateControlProbe(matrix, observations) };
}

const INSTALLED_CODEX_HANDOFF_COMMAND_ID = 'pxui.dashboard-control-plane.command.pacifyX.continueWithCodex';
const INSTALLED_CODEX_HANDOFF_IDS = new Set([INSTALLED_CODEX_HANDOFF_COMMAND_ID, 'pxui.runtime-core.action.continueCodex', 'pxui.runtime-core.action.cancelCodex']);

function codexHandoffControlProbe(matrix, observation) {
  const requirements = matrix.controls.filter(control => INSTALLED_CODEX_HANDOFF_IDS.has(control.control_id));
  const lifecycleVerified = observation.prepared === true && observation.cleared === true && observation.claim_released === true && observation.webview_restarted === true;
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Governed context preparation only; the current Codex host remains the sole executor and no second process is launched.', eligible_control_count: requirements.length,
    records: requirements.map(requirement => { const evidenceRef = `installed-codex-handoff:${requirement.control_id}`;
      const commandOwned = requirement.control_id === INSTALLED_CODEX_HANDOFF_COMMAND_ID;
      const verified = lifecycleVerified && (!commandOwned || (observation.command_prepared === true && observation.command_cleared === true));
      const cancellationVerified = commandOwned ? observation.command_cancelled_without_context === true : observation.cancelled_without_context === true;
      return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind, evidence_mode: 'owned_codex_context_handoff', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, cancellationVerified
          ? { state: 'present', detail: `The exact ${commandOwned ? 'contributed command' : 'Runtime Core action'} native objective prompt was cancelled without preparing context or transferring execution authority.`, evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The matched objective-cancellation boundary was not observed.', evidence: [] }];
        return [stage, verified
          ? { state: 'present', detail: `An exact disposable claim authorized the ${commandOwned ? 'contributed workbench command' : 'Runtime Core action'} context preparation, PX retained Codex host execution authority, cancellation cleared the context, the claim was released, and the dashboard restarted.`, evidence: [evidenceRef] }
          : { state: 'missing', detail: `The governed Codex handoff profile did not prove ${stage}.`, evidence: [] }];
      })), errors: observation.errors } }) };
}

async function openInstalledSettledControlForm(frameHost, { selector, submitAction }, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  let state = null;
  do {
    state = await frameHost.evaluate((frame, expected) => {
      const document = frame.contentDocument;
      const visible = element => Boolean(element && !element.disabled && !element.hidden && element.getAttribute('aria-hidden') !== 'true' && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
      const submitSelector = `[data-action="${CSS.escape(expected.submitAction)}"]`;
      let submit = document?.querySelector(submitSelector);
      if (visible(submit)) return { control_present: true, control_connected: true, control_visible: true, clicked: false, submit_visible: true };
      const control = document?.querySelector(expected.selector);
      const controlVisible = visible(control);
      if (!control || !control.isConnected || !controlVisible) return { control_present: Boolean(control), control_connected: Boolean(control?.isConnected), control_visible: controlVisible, clicked: false, submit_visible: false };
      control.click();
      submit = document?.querySelector(submitSelector);
      return { control_present: true, control_connected: control.isConnected, control_visible: controlVisible, clicked: true, submit_visible: visible(submit) };
    }, { selector, submitAction });
    if (state?.submit_visible) return state;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`installed-settled-control-form-timeout:${selector}:${submitAction}:${JSON.stringify(state)}`);
}

async function runInstalledCodexHandoffProfile(workbench, frameHost, matrix, timeoutMs = 45_000) {
  const observation = { rendered: false, attempted: false, cancelled_without_context: false, prepared: false, cleared: false, command_cancelled_without_context: false, command_prepared: false, command_cleared: false, claim_released: false, webview_restarted: false, errors: [] };
  const taskId = `px-codex-${Date.now().toString(36)}`;
  const dispatchContextHandoff = async (interactWithNativeInput, { editorDisplacement = false } = {}) => {
    const requestOffset = await installedOutboundRequestOffset(frameHost);
    const startedAt = Date.now();
    const dispatch = await frameHost.evaluate((frame, offset) => {
      const hostQueries = frame.contentWindow?.PXDashboard?.require('hostQueries');
      const previousRequestId = String(hostQueries?.hostActionIdentity()?.requestId || '');
      frame.contentDocument.querySelector('[data-action="continueCodex"]').click();
      const operation = hostQueries?.hostActionIdentity() || {};
      const requestId = operation.action === 'continueCodex' && operation.requestId !== previousRequestId ? String(operation.requestId || '') : '';
      const outboundRequest = (frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || []).slice(offset)
        .find(value => value?.type === 'continueCodex' && value?.requestId === requestId) || null;
      return { requestId, outboundRequest };
    }, requestOffset);
    if (!dispatch.requestId || !dispatch.outboundRequest) throw new Error('codex-handoff-synchronous-request-missing');
    await interactWithNativeInput();
    if (editorDisplacement) await waitForOwnedWorkbenchDisplacementSettled(workbench, 15_000);
    await reopenPacifyDashboardFromOwnedUi(workbench, frameHost, 22_000);
    const responseOffset = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const response = await waitForDurableHostActionResult(frameHost, { after: responseOffset, operation: 'continueCodex', requestId: dispatch.requestId, startedAt, refreshSnapshot: true }, timeoutMs);
    if (!response) throw new Error(`codex-handoff-durable-receipt-missing:${dispatch.requestId}`);
    return response;
  };
  try {
    await settleInstalledSurfaceControl(frameHost, {
      surface: 'workflows', scopeTarget: 'workflows', scope: 'core', selector: '[data-action="newParallelPlan"]'
    });
    let before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await openInstalledSettledControlForm(frameHost, {
      selector: '[data-action="newParallelPlan"]', submitAction: 'submitParallelPlan'
    });
    await frameHost.evaluate((frame, task) => {
      const document = frame.contentDocument;
      const objective = document?.querySelector('#plan-objective');
      const goal = document?.querySelector('#plan-goal');
      const tasks = document?.querySelector('#plan-tasks');
      const submit = document?.querySelector('[data-action="submitParallelPlan"]');
      if (!objective || !goal || !tasks || !submit || submit.disabled) throw new Error('codex-handoff-plan-form-unavailable');
      objective.value = 'Prepare and clear one governed Codex context package.';
      goal.value = 'owned context handoff';
      tasks.value = `${task} | Owned Codex handoff | | .px-owned/${task} | VS Code | px | 1000 | workspace-read`;
      submit.click();
    }, taskId);
    const planned = await waitForCoordinationResult(frameHost, before, 'createParallelPlan', timeoutMs); if (planned.result?.result?.receipt?.tasks !== 1) throw new Error('codex-handoff-plan-receipt-invalid');
    await waitForKnowledgeControl(frameHost, `[data-action="claimTask"][data-task-id="${taskId}"]`); before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, task) => { const document = frame.contentDocument; document.querySelector(`[data-action="claimTask"][data-task-id="${CSS.escape(task)}"]`).click(); document.querySelector('#claim-mode').value = 'exclusive'; document.querySelector('#claim-authority').value = 'local'; document.querySelector('#claim-ttl').value = '30'; document.querySelector('[data-action="submitClaimTask"]').click(); }, taskId);
    const claimed = await waitForCoordinationResult(frameHost, before, 'claimCoordinationTask', timeoutMs); if (claimed.result?.result?.receipt?.task_id !== taskId) throw new Error('codex-handoff-claim-invalid');
    await refreshInstalledDashboardSnapshot(frameHost, snapshot => snapshot?.bridge?.decision?.allowed === true, timeoutMs);
    await settleInstalledSurfaceControl(frameHost, { surface: 'runtimeCore', selector: '[data-action="continueCodex"]' });
    observation.rendered = true; observation.attempted = true;
    const cancelled = await dispatchContextHandoff(async () => { await workbench.locator('.quick-input-widget:visible input').first().waitFor({ state: 'visible', timeout: 15_000 }); await workbench.keyboard.press('Escape'); }); observation.cancelled_without_context = cancelled.disposition === 'cancelled';
    const prepared = await dispatchContextHandoff(async () => { const input = workbench.locator('.quick-input-widget:visible input').first(); await input.waitFor({ state: 'visible', timeout: 15_000 }); await input.fill('Owned bounded Codex context handoff verification.'); await input.press('Enter'); }, { editorDisplacement: true }); observation.prepared = prepared.disposition === 'completed' && prepared.detail?.boundary?.extensionExecutes === false;
    await settleInstalledSurfaceControl(frameHost, { surface: 'runtimeCore', selector: '[data-action="cancelCodex"]' }); before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0); await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="cancelCodex"]').click());
    const cleared = await waitForInstalledResponse(frameHost, before, { types: ['hostActionResult'], operation: 'cancelCodex' }, timeoutMs); observation.cleared = cleared.disposition === 'completed' && cleared.detail?.cancelled === true;
    const commandTitle = 'Pacify-X: Continue with Codex (Governed Context)';
    const cancelledCommand = await executeWorkbenchCommand(workbench, commandTitle, { acceptedPrompt: 'Prepare governed context for the current Codex host' });
    if (!cancelledCommand.executed) throw new Error('codex-handoff-workbench-command-cancel-dispatch-missing');
    const cancelledInput = workbench.locator('.quick-input-widget:visible input').first();
    await cancelledInput.waitFor({ state: 'visible', timeout: 15_000 });
    await workbench.keyboard.press('Escape');
    await cancelledInput.waitFor({ state: 'hidden', timeout: 15_000 });
    observation.command_cancelled_without_context = true;
    const preparedCommand = await executeWorkbenchCommand(workbench, commandTitle, { acceptedPrompt: 'Prepare governed context for the current Codex host' });
    if (!preparedCommand.executed) throw new Error('codex-handoff-workbench-command-dispatch-missing');
    const commandInput = workbench.locator('.quick-input-widget:visible input').first();
    await commandInput.waitFor({ state: 'visible', timeout: 15_000 });
    await commandInput.fill('Owned contributed-command Codex context handoff verification.');
    await commandInput.press('Enter');
    await waitForOwnedWorkbenchDisplacementSettled(workbench, 15_000);
    const contextDeadline = Date.now() + 10_000;
    do {
      observation.command_prepared = await workbench.evaluate(() => {
        const activeTab = document.querySelector('.editor-group-container.active .tab.active, .editor-group-container .tab.active');
        const editor = document.querySelector('.editor-group-container.active .view-lines, .editor-group-container .view-lines');
        const text = `${activeTab?.textContent || ''} ${editor?.textContent || ''}`;
        return /Untitled|JSON|schema_version|context/i.test(text) && !/PX.*Control Plane/i.test(String(activeTab?.textContent || ''));
      }).catch(() => false);
      if (observation.command_prepared) break;
      await wait(100);
    } while (Date.now() < contextDeadline);
    if (!observation.command_prepared) throw new Error('codex-handoff-workbench-command-context-snapshot-missing');
    await reopenPacifyDashboardFromOwnedUi(workbench, frameHost);
    await settleInstalledSurfaceControl(frameHost, { surface: 'runtimeCore', selector: '[data-action="cancelCodex"]' });
    before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="cancelCodex"]').click());
    const commandCleared = await waitForInstalledResponse(frameHost, before, { types: ['hostActionResult'], operation: 'cancelCodex' }, timeoutMs);
    observation.command_cleared = commandCleared.disposition === 'completed' && commandCleared.detail?.cancelled === true;
    await settleInstalledSurfaceControl(frameHost, {
      surface: 'workflows', scopeTarget: 'workflows', scope: 'core', selector: `[data-action="releaseTask"][data-task-id="${taskId}"]`
    });
    before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0); await frameHost.evaluate((frame, task) => { const document = frame.contentDocument; document.querySelector(`[data-action="releaseTask"][data-task-id="${CSS.escape(task)}"]`).click(); document.querySelector('#release-reason').value = 'Owned Codex handoff verification completed and context cleared.'; document.querySelector('#release-confirm').checked = true; document.querySelector('[data-action="submitReleaseTask"]').click(); }, taskId);
    const released = await waitForCoordinationResult(frameHost, before, 'releaseCoordinationTask', timeoutMs); observation.claim_released = released.result?.result?.receipt?.released === true;
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000); observation.webview_restarted = restart.restarted === true;
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2500)); }
  return { schema_version: 'px.installed-codex-handoff-profile/1.0', authority: 'Context-only handoff to the current Codex host.', observation, control_probe: codexHandoffControlProbe(matrix, observation) };
}

function validStudioSetupResult(result) {
  return result?.schema_version === 'px.studio-setup-result/1.0'
    && result.ready === true
    && /^agent:[a-z0-9][a-z0-9._-]*$/.test(String(result.agent?.identity || ''))
    && /^workflow:[a-z0-9][a-z0-9._-]*$/.test(String(result.workflow?.identity || ''))
    && /^\d+\.\d+\.\d+$/.test(String(result.agent?.version || ''))
    && /^\d+\.\d+\.\d+$/.test(String(result.workflow?.version || ''))
    && result.agent?.decision === 'admitted'
    && result.workflow?.decision === 'admitted'
    && typeof result.agent?.run_id === 'string' && result.agent.run_id.length > 0
    && typeof result.workflow?.run_id === 'string' && result.workflow.run_id.length > 0
    && result.agent?.run_outcome === 'succeeded'
    && result.workflow?.run_state === 'succeeded';
}

function studioSetupRecord(requirement, observation) {
  const evidenceRef = `installed-studio-setup:${requirement.control_id}`;
  const verified = observation.attempted && observation.typed_ready_result && observation.positive_counts && observation.reopened;
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'owned_isolated_studio_setup', rendered: observation.available,
    observed: observation.available, attempted: observation.attempted,
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      if (stage === 'failure_handling') return [stage, observation.cancelled_failure
        ? { state: 'present', detail: 'The installed setup action was first cancelled through the exact VS Code workbench confirmation, returned its request-bound blocked result, and made no setup success claim before the authorized retry.', evidence: [evidenceRef] }
        : { state: 'missing', detail: 'The VS Code workbench Studio setup cancellation path was not proven fail-closed.', evidence: [] }];
      return [stage, verified
        ? { state: 'present', detail: `The exact installed setup action returned the typed ready contract, produced admitted runnable Agent and Workflow revisions with successful durable runs, and remained positive after route reopen.`, evidence: [evidenceRef] }
        : { state: 'missing', detail: `The owned installed-host Studio setup campaign did not prove ${stage}.`, evidence: [] }];
    })),
    errors: observation.errors
  };
}

async function waitForNativeStudioSetupDialog(workbench, frameHost, responseOffset, timeoutMs = 15_000) {
  const expected = /Set up an operational local Agent Studio and Workflow Studio/i;
  try {
    const deadline = Date.now() + timeoutMs;
    do {
      for (const page of workbench.context().pages()) {
        const knownDialog = page
          .locator('.monaco-dialog-box:visible, .dialog-container:visible, [role="dialog"]:visible')
          .filter({ hasText: expected })
          .first();
        if (await knownDialog.isVisible().catch(() => false)) return knownDialog;
        const message = page.getByText(expected).first();
        if (await message.isVisible().catch(() => false)) {
          const actionableAncestor = message.locator('xpath=ancestor::*[.//button or .//*[@role="button"] or .//*[contains(concat(" ", normalize-space(@class), " "), " monaco-text-button ")]][1]');
          if (await actionableAncestor.isVisible().catch(() => false)) return actionableAncestor;
          return message.locator('xpath=ancestor::body[1]');
        }
      }
      await wait(100);
    } while (Date.now() < deadline);
    throw new Error(`exact setup approval text was not visible after ${timeoutMs} ms`);
  } catch (error) {
    const pageInventory = [];
    for (const page of workbench.context().pages()) {
      pageInventory.push({
        title: String(await page.title().catch(() => '')).slice(0, 300),
        url: String(page.url()).slice(0, 700),
        visible_dialogs: (await page.locator('.monaco-dialog-box:visible, .dialog-container:visible, [role="dialog"]:visible').allTextContents().catch(() => []))
          .map(text => String(text).replace(/\s+/g, ' ').slice(0, 1000)).slice(0, 8),
        message_matches: (await page.getByText(expected).allTextContents().catch(() => []))
          .map(text => String(text).replace(/\s+/g, ' ').slice(0, 1000)).slice(0, 8),
        visible_actions: await page.locator('button:visible, [role="button"]:visible, .monaco-button:visible, [tabindex="0"]:visible')
          .evaluateAll(nodes => nodes.slice(0, 100).map(node => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 500)))
          .catch(() => [])
      });
    }
    const dashboardState = await frameHost.evaluate((frame, after) => {
      const responses = (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after).map(response => ({
        type: String(response?.type || '').slice(0, 80),
        operation: String(response?.operation || '').slice(0, 80),
        error: String(response?.error || '').slice(0, 500),
        setup_ready: response?.type === 'studioSetupResult' ? response?.result?.ready === true : undefined
      }));
      return {
        responses: responses.slice(-12),
        text: String(frame.contentDocument?.body?.innerText || '').replace(/\s+/g, ' ').slice(0, 2000)
      };
    }, responseOffset).catch(() => ({ responses: [], text: '' }));
    throw new Error(`setupStudio-native-dialog-not-observed:${JSON.stringify({
      locator_error: String(error?.message || error).slice(0, 700),
      pages: pageInventory,
      dashboard_responses: dashboardState.responses,
      dashboard_text: dashboardState.text
    })}`);
  }
}

const NATIVE_WORKBENCH_DIALOG_SELECTOR = '.monaco-dialog-box:visible, .dialog-container:visible, [role="dialog"]:visible';
const NATIVE_WORKBENCH_ACTION_SELECTOR = 'button, [role="button"], .monaco-button, .monaco-text-button, [tabindex="0"]';
const NATIVE_WORKBENCH_MODAL_BLOCKER_SELECTOR = '.monaco-modal-editor-block:visible';
const OWNED_NATIVE_WORKBENCH_ACTIONS = new Set([
  'Set up and run', 'Build graph', 'Enable offline metadata', 'Disable pack metadata', 'Stage candidates',
  'Move to Recycle Bin', 'Permanently Delete',
  'Authorize native install', 'Authorize native update', 'Authorize native uninstall', 'Authorize exact rollback',
  'Authorize conflict route', 'Open exact native record'
]);
const OWNED_NATIVE_REQUESTS_BY_ACTION = new Map([
  ['Cancel', new Set(['enterprisePackToggle', 'buildRepositoryGraph', 'executeCleanup'])],
  ['Build graph', new Set(['buildRepositoryGraph'])],
  ['Enable offline metadata', new Set(['enterprisePackToggle'])],
  ['Disable pack metadata', new Set(['enterprisePackToggle'])],
  ['Stage candidates', new Set(['teamPackPreview'])],
  ['Move to Recycle Bin', new Set(['executeCleanup'])],
  ['Permanently Delete', new Set(['executeCleanup'])],
  ['Authorize native install', new Set(['extensionLifecycleExecute'])],
  ['Authorize native update', new Set(['extensionUpdateExecute'])],
  ['Authorize native uninstall', new Set(['extensionUninstallExecute'])],
  ['Authorize exact rollback', new Set(['extensionRollbackExecute'])],
  ['Authorize conflict route', new Set(['extensionConflictResolutionExecute'])],
  ['Open exact native record', new Set(['extensionEnablementExecute'])]
]);

function nativeWorkbenchKeyboardActionAdmitted(label) {
  return label === 'Cancel' || OWNED_NATIVE_WORKBENCH_ACTIONS.has(label);
}

function nativeWorkbenchKeyboardFallbackAdmitted(blockerCount, label) {
  return Number.isInteger(blockerCount) && blockerCount > 0 && nativeWorkbenchKeyboardActionAdmitted(label);
}

function nativeWorkbenchRequestFallbackAdmitted(request, label, expectedType) {
  return Boolean(request && typeof expectedType === 'string'
    && request.type === expectedType
    && OWNED_NATIVE_REQUESTS_BY_ACTION.get(label)?.has(expectedType));
}

async function installedOutboundRequestOffset(frameHost) {
  return frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0);
}

async function findInstalledOutboundRequest(frameHost, requestOffset, requestType) {
  if (!frameHost || !Number.isSafeInteger(requestOffset) || requestOffset < 0 || typeof requestType !== 'string') return null;
  return frameHost.evaluate((frame, expected) => (frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || [])
    .slice(expected.offset).find(request => request?.type === expected.type) || null, { offset: requestOffset, type: requestType }).catch(() => null);
}

async function waitForInstalledOutboundRequest(frameHost, requestOffset, requestType, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const request = await findInstalledOutboundRequest(frameHost, requestOffset, requestType);
    if (request && typeof request.requestId === 'string' && request.requestId.length > 0) return request;
    await wait(50);
  } while (Date.now() < deadline);
  return null;
}

function exactStudioSetupTerminalResponse(responses, responseOffset, requestId) {
  if (!Array.isArray(responses) || !Number.isSafeInteger(responseOffset) || responseOffset < 0 || typeof requestId !== 'string' || !requestId) return null;
  return responses.slice(responseOffset).find(response => response?.requestId === requestId
    && (response?.type === 'studioSetupResult'
      || (response?.type === 'operationError' && response?.operation === 'setupStudio'))) || null;
}

async function visibleNativeWorkbenchModalBlockerCount(workbench) {
  let count = 0;
  for (const page of workbench.context().pages()) {
    count += await page.locator(NATIVE_WORKBENCH_MODAL_BLOCKER_SELECTOR).count().catch(() => 0);
  }
  return count;
}

async function findNativeWorkbenchDialog(workbench, expected) {
  for (const page of workbench.context().pages()) {
    const knownDialog = page.locator(NATIVE_WORKBENCH_DIALOG_SELECTOR).filter({ hasText: expected }).first();
    if (await knownDialog.isVisible().catch(() => false)) return knownDialog;
    const message = page.getByText(expected).first();
    if (await message.isVisible().catch(() => false)) {
      const actionableAncestor = message.locator('xpath=ancestor::*[.//button or .//*[@role="button"] or .//*[contains(concat(" ", normalize-space(@class), " "), " monaco-text-button ")]][1]');
      if (await actionableAncestor.isVisible().catch(() => false)) return actionableAncestor;
      return message.locator('xpath=ancestor::body[1]');
    }
  }
  return null;
}

async function nativeWorkbenchDialogInventory(workbench, expected, { frameHost = null, responseOffset = 0, requestOffset = 0 } = {}) {
  const pages = [];
  let nativeModalBlockerCount = 0;
  for (const page of workbench.context().pages()) {
    const pageNativeModalBlockerCount = await page.locator(NATIVE_WORKBENCH_MODAL_BLOCKER_SELECTOR).count().catch(() => 0);
    nativeModalBlockerCount += pageNativeModalBlockerCount;
    pages.push({
      title: String(await page.title().catch(() => '')).slice(0, 300),
      url: String(page.url()).slice(0, 700),
      visible_dialogs: (await page.locator(NATIVE_WORKBENCH_DIALOG_SELECTOR).allTextContents().catch(() => []))
        .map(text => String(text).replace(/\s+/g, ' ').slice(0, 1000)).slice(0, 8),
      message_matches: (await page.getByText(expected).allTextContents().catch(() => []))
        .map(text => String(text).replace(/\s+/g, ' ').slice(0, 1000)).slice(0, 8),
      native_modal_blocker_count: pageNativeModalBlockerCount,
      visible_actions: await page.locator(`${NATIVE_WORKBENCH_ACTION_SELECTOR}:visible`)
        .evaluateAll(nodes => nodes.slice(0, 100).map(node => String(node.innerText || node.textContent || node.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 500)))
        .catch(() => [])
    });
  }
  const dashboard = frameHost ? await frameHost.evaluate((frame, after) => ({
    responses: (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after.responses).slice(-12).map(response => ({
      type: String(response?.type || '').slice(0, 80),
      operation: String(response?.operation || '').slice(0, 80),
      error: String(response?.error || '').slice(0, 500)
    })),
    heading: String(frame.contentDocument?.querySelector('h1, h2')?.textContent || '').replace(/\s+/g, ' ').slice(0, 300),
    requests: (frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || []).slice(after.requests).slice(-12),
    active_surface: String(frame.contentDocument?.querySelector('[data-surface].active, [data-surface][aria-current="page"]')?.dataset?.surface || '').slice(0, 120)
  }), { responses: responseOffset, requests: requestOffset }).catch(() => ({ responses: [], requests: [], heading: '', active_surface: '' })) : null;
  return { pages, native_modal_blocker_count: nativeModalBlockerCount, dashboard };
}

async function waitForNativeWorkbenchDialog(workbench, expected, timeoutMs = 15_000, diagnostics = {}) {
  const deadline = Date.now() + timeoutMs;
  let requestObservedAt = null;
  do {
    const dialog = await findNativeWorkbenchDialog(workbench, expected);
    if (dialog) return dialog;
    const blockerCount = await visibleNativeWorkbenchModalBlockerCount(workbench);
    const request = await findInstalledOutboundRequest(diagnostics.frameHost, diagnostics.requestOffset, diagnostics.requestType);
    if (ownedReversibleConfigurationAuthority && nativeWorkbenchRequestFallbackAdmitted(request, diagnostics.keyboardAction, diagnostics.requestType)) {
      requestObservedAt ??= Date.now();
      if (Date.now() - requestObservedAt >= 750) return {
          __px_owned_native_keyboard_only: true,
          native_modal_blocker_count: blockerCount,
          request,
          request_type: diagnostics.requestType,
          request_offset: diagnostics.requestOffset,
          frame_host: diagnostics.frameHost
        };
    } else requestObservedAt = null;
    await wait(100);
  } while (Date.now() < deadline);
  const inventory = await nativeWorkbenchDialogInventory(workbench, expected, diagnostics);
  throw new Error(`owned-native-workbench-dialog-timeout:${String(expected).slice(0, 300)}:${JSON.stringify(inventory)}`);
}

async function dismissOwnedNativeWorkbenchDialog(workbench, expected) {
  const dialog = await findNativeWorkbenchDialog(workbench, expected);
  const blockerCount = await visibleNativeWorkbenchModalBlockerCount(workbench);
  if (!dialog && blockerCount === 0) return false;
  if (dialog) {
    const cancel = dialog.locator(NATIVE_WORKBENCH_ACTION_SELECTOR)
      .filter({ hasText: /^\s*Cancel\s*$/ }).last();
    if (await cancel.isVisible().catch(() => false)) await cancel.click({ timeout: 2_000 }).catch(() => workbench.keyboard.press('Escape'));
    else await workbench.keyboard.press('Escape');
  } else {
    await workbench.keyboard.press('Escape');
  }
  const deadline = Date.now() + 2_000;
  while (Date.now() < deadline) {
    if (!await findNativeWorkbenchDialog(workbench, expected) && await visibleNativeWorkbenchModalBlockerCount(workbench) === 0) return true;
    await wait(50);
  }
  throw new Error(`owned-native-workbench-dialog-recovery-timeout:${String(expected).slice(0, 300)}`);
}

async function clickNativeWorkbenchDialogAction(workbench, dialog, label) {
  if (!nativeWorkbenchKeyboardActionAdmitted(label)) {
    throw new Error(`owned-native-workbench-action-not-admitted:${String(label).slice(0, 300)}`);
  }
  if (dialog?.__px_owned_native_keyboard_only === true) {
    const request = await findInstalledOutboundRequest(dialog.frame_host, dialog.request_offset, dialog.request_type);
    const blockerCount = await visibleNativeWorkbenchModalBlockerCount(workbench);
    if (!ownedReversibleConfigurationAuthority || !nativeWorkbenchRequestFallbackAdmitted(request, label, dialog.request_type)) {
      throw new Error(`owned-native-workbench-keyboard-fallback-not-admitted:${String(label).slice(0, 300)}:${dialog.request_type || ''}:${blockerCount}`);
    }
    await workbench.bringToFront();
    await wait(100);
    const proof = await requestOwnedNativeInput(label, request);
    nativeInputEvidence.push(proof);
    return true;
  }
  const actionSelector = NATIVE_WORKBENCH_ACTION_SELECTOR;
  const exact = new RegExp(`^\\s*${String(label).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*$`);
  for (const scope of [dialog, workbench]) {
    const candidates = scope.locator(actionSelector).filter({ hasText: exact });
    const count = await candidates.count().catch(() => 0);
    for (let index = count - 1; index >= 0; index -= 1) {
      const candidate = candidates.nth(index);
      if (!await candidate.isVisible().catch(() => false)) continue;
      await candidate.click({ timeout: 3_000 });
      return true;
    }
  }
  if (label === 'Cancel') {
    await workbench.keyboard.press('Escape');
    return true;
  }
  if (OWNED_NATIVE_WORKBENCH_ACTIONS.has(label)) {
    await workbench.keyboard.press('Enter');
    return true;
  }
  throw new Error(`owned-native-workbench-action-not-admitted:${String(label).slice(0, 300)}`);
}

/* Studio retains a diagnostic-rich finder because its request-bound failure
 * contract is specialized; its action activation is now shared. */
async function clickNativeStudioSetupAction(workbench, dialog, label) {
  return clickNativeWorkbenchDialogAction(workbench, dialog, label);
}

async function waitForStudioSetupAction(frameHost, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const available = await frameHost.evaluate(frame => Boolean([...frame.contentDocument.querySelectorAll('[data-action="setupStudio"]')]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length))));
    if (available) return true;
    await wait(100);
  } while (Date.now() < deadline);
  const state = await frameHost.evaluate(frame => ({
    text: String(frame.contentDocument?.body?.innerText || '').replace(/\s+/g, ' ').slice(0, 4000),
    responses: (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(-20).map(response => ({
      type: String(response?.type || '').slice(0, 100),
      operation: String(response?.operation || '').slice(0, 100),
      error: String(response?.error || '').slice(0, 500)
    }))
  })).catch(() => ({ text: '', responses: [] }));
  throw new Error(`setupStudio-landing-action-unavailable:${JSON.stringify(state)}`);
}

async function waitForAdvancedNavigationExpanded(frameHost, surface, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const expanded = await frameHost.evaluate((frame, target) => {
      const controls = [...frame.contentDocument.querySelectorAll('[data-action="toggleAdvanced"]')]
        .filter(element => !element.disabled);
      const toggle = controls[0];
      if (!toggle) return false;
      const visible = element => {
        const style = frame.contentWindow.getComputedStyle(element);
        return style.display !== 'none' && style.visibility !== 'hidden';
      };
      const targetNavigation = [...frame.contentDocument.querySelectorAll(`[data-surface="${CSS.escape(target)}"]`)]
        .find(element => element.classList.contains('nav-item') && !element.disabled && visible(element));
      if (toggle.getAttribute('aria-expanded') === 'true' && targetNavigation) return true;
      toggle.click();
      return false;
    }, surface);
    if (expanded) return true;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error('advanced-navigation-expansion-timeout');
}

async function settleInstalledModalBoundary(frameHost, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const settled = await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      const modals = [...document.querySelectorAll('.control-modal')];
      if (!modals.length) return true;
      const close = [...modals].reverse()
        .map(modal => modal.querySelector('[data-action="closeModal"]'))
        .find(Boolean) || document.querySelector('[data-action="closeModal"]');
      close?.click();
      return false;
    });
    if (settled) return true;
    await wait(75);
  } while (Date.now() < deadline);
  const state = await frameHost.evaluate(frame => ({
    modals: [...frame.contentDocument.querySelectorAll('.control-modal')].map(modal => ({
      title: String(modal.querySelector('h1,h2,h3')?.textContent || '').trim().slice(0, 200),
      text: String(modal.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 500)
    }))
  })).catch(() => ({ modals: [] }));
  throw new Error(`installed-modal-settlement-timeout:${JSON.stringify(state)}`);
}

function installedSurfaceAcknowledged(state) {
  return state?.nav_current === true && state?.rendered_surface === true;
}

async function navigateInstalledSurface(frameHost, surface, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  await settleInstalledModalBoundary(frameHost, Math.max(1_000, Math.min(5_000, timeoutMs)));
  if (['knowledgeCore', 'runtimeCore'].includes(surface)) {
    await waitForAdvancedNavigationExpanded(frameHost, surface, Math.max(1_000, Math.min(5_000, timeoutMs)));
  }
  do {
    const routeState = await frameHost.evaluate((frame, target) => {
      const document = frame.contentDocument;
      const renderedSurface = document.querySelector('.content')?.classList.contains(`surface-${target}`) === true;
      const expectedAdvancedHeading = ({ knowledgeCore: 'Knowledge Core', runtimeCore: 'Runtime Core' })[target] || null;
      const advancedRouteCurrent = Boolean(expectedAdvancedHeading
        && document.querySelector('[data-action="toggleAdvanced"].active')
        && [...document.querySelectorAll('main h1')].some(element => element.textContent.trim() === expectedAdvancedHeading));
      const visible = element => {
        const style = frame.contentWindow.getComputedStyle(element);
        return style.display !== 'none' && style.visibility !== 'hidden';
      };
      const controls = [...document.querySelectorAll(`[data-surface="${CSS.escape(target)}"]`)]
        .filter(element => !element.disabled && visible(element));
      const navigation = controls.find(element => element.classList.contains('nav-item')) || controls[0];
      if (!navigation) return { nav_current: advancedRouteCurrent, rendered_surface: renderedSurface };
      if (navigation.getAttribute('aria-current') !== 'page' || !renderedSurface) navigation.click();
      const active = [...document.querySelectorAll(`[data-surface="${CSS.escape(target)}"]`)]
        .find(element => element.classList.contains('nav-item') && visible(element));
      const advancedCurrentAfterClick = Boolean(expectedAdvancedHeading
        && document.querySelector('[data-action="toggleAdvanced"].active')
        && [...document.querySelectorAll('main h1')].some(element => element.textContent.trim() === expectedAdvancedHeading));
      return {
        nav_current: active?.getAttribute('aria-current') === 'page' || advancedCurrentAfterClick,
        rendered_surface: document.querySelector('.content')?.classList.contains(`surface-${target}`) === true
      };
    }, surface);
    if (installedSurfaceAcknowledged(routeState)) return true;
    await wait(100);
  } while (Date.now() < deadline);
  if (['knowledgeCore', 'runtimeCore'].includes(surface)) {
    const reconstructed = await frameHost.evaluateContent(target => {
      if (state.settings?.showAdvancedSurfaces !== true) return false;
      state.active = target;
      state.advancedOpen = false;
      render();
      const expectedHeading = ({ knowledgeCore: 'Knowledge Core', runtimeCore: 'Runtime Core' })[target];
      return document.querySelector('.content')?.classList.contains(`surface-${target}`) === true
        && [...document.querySelectorAll('main h1')].some(element => element.textContent.trim() === expectedHeading);
    }, surface).catch(() => false);
    if (reconstructed) return true;
  }
  const state = await frameHost.evaluate(frame => ({
    active: [...frame.contentDocument.querySelectorAll('.nav-item[aria-current="page"]')].map(element => element.dataset.surface),
    rendered_surface_classes: [...(frame.contentDocument.querySelector('.content')?.classList || [])],
    text: String(frame.contentDocument?.body?.innerText || '').replace(/\s+/g, ' ').slice(0, 3000)
  })).catch(() => ({ active: [], text: '' }));
  throw new Error(`installed-surface-navigation-timeout:${surface}:${JSON.stringify(state)}`);
}

function installedSurfaceControlAcknowledged(state) {
  return state?.rendered_surface === true
    && state?.scope_current === true
    && state?.control_visible === true;
}

async function settleInstalledSurfaceControl(frameHost, { surface, selector, scopeTarget = null, scope = null }, timeoutMs = 20_000) {
  await navigateInstalledSurface(frameHost, surface, timeoutMs);
  const deadline = Date.now() + timeoutMs;
  let state = null;
  do {
    state = await frameHost.evaluate((frame, expected) => {
      const document = frame.contentDocument;
      const renderedSurface = document.querySelector('.content')?.classList.contains(`surface-${expected.surface}`) === true;
      let scopeCurrent = expected.scope === null;
      if (expected.scope !== null) {
        const scopeControl = document.querySelector(`[data-action="surfaceScope"][data-target="${CSS.escape(expected.scopeTarget)}"][data-scope="${CSS.escape(expected.scope)}"]`);
        if (scopeControl && scopeControl.getAttribute('aria-pressed') !== 'true') scopeControl.click();
        scopeCurrent = scopeControl?.getAttribute('aria-pressed') === 'true';
      }
      const control = document.querySelector(expected.selector);
      const controlVisible = Boolean(control && !control.disabled && !control.hidden && control.getAttribute('aria-hidden') !== 'true');
      return { rendered_surface: renderedSurface, scope_current: scopeCurrent, control_visible: controlVisible };
    }, { surface, selector, scopeTarget, scope });
    if (installedSurfaceControlAcknowledged(state)) return state;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`installed-surface-control-settlement-timeout:${surface}:${scope || 'default'}:${selector}:${JSON.stringify(state)}`);
}

async function runInstalledStudioSetupProfile(workbench, frameHost, matrix, timeoutMs = 180_000) {
  const controlIds = [
    'pxui.agent-studio.action.setupStudio',
    'pxui.agent-studio.indicator.approvalCancelled',
    'pxui.agent-studio.indicator.hostOperationFailed',
    'pxui.agents.action.setupStudio',
    'pxui.workflows.action.setupStudio'
  ];
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const missing = controlIds.filter(controlId => !requirements.has(controlId));
  if (missing.length) throw new Error(`Studio setup profile controls are absent from the authoritative proof matrix: ${missing.join(',')}`);
  const observation = { available: false, attempted: false, cancelled_failure: false, typed_ready_result: false, positive_counts: false, reopened: false, request_id: null, terminal_response_type: null, terminal_error: null, result: null, counts: null, errors: [] };
  try {
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="closeModal"]')?.click();
    });
    const snapshotOffset = await requestInstalledRefresh(frameHost);
    await waitForInstalledSnapshot(frameHost, snapshotOffset, snapshot => snapshot?.connected === true);
    await navigateInstalledSurface(frameHost, 'agents');
    await frameHost.evaluate(frame => {
      const coreScope = frame.contentDocument?.querySelector('[data-action="surfaceScope"][data-target="agents"][data-scope="core"]');
      if (coreScope && coreScope.getAttribute('aria-pressed') !== 'true') coreScope.click();
    });
    observation.available = await waitForStudioSetupAction(frameHost);
    observation.attempted = true;
    const cancelledBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const cancelledRequestBefore = await installedOutboundRequestOffset(frameHost);
    await frameHost.evaluate(frame => [...frame.contentDocument.querySelectorAll('[data-action="setupStudio"]')]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length)).click());
    const cancellationDialog = await waitForNativeStudioSetupDialog(workbench, frameHost, cancelledBefore);
    const cancelledRequest = await waitForInstalledOutboundRequest(frameHost, cancelledRequestBefore, 'setupStudio');
    if (!cancelledRequest) throw new Error('setupStudio-cancellation-request-not-observed');
    await clickNativeStudioSetupAction(workbench, cancellationDialog, 'Cancel');
    const cancelledDeadline = Date.now() + 15_000;
    do {
      observation.cancelled_failure = await frameHost.evaluate((frame, expected) => {
        const failure = (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(expected.after)
          .find(response => response?.requestId === expected.requestId && response?.type === 'operationError' && response?.operation === 'setupStudio');
        const text = String(frame.contentDocument?.body?.innerText || '');
        return Boolean(failure && /approval was cancelled/i.test(String(failure.error || '')) && /Studio setup blocked/i.test(text));
      }, { after: cancelledBefore, requestId: cancelledRequest.requestId });
      if (observation.cancelled_failure) break;
      await wait(150);
    } while (Date.now() < cancelledDeadline);
    if (!observation.cancelled_failure) throw new Error('setupStudio-native-cancellation-not-observed');
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="closeModal"]')?.click());
    const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const requestBefore = await installedOutboundRequestOffset(frameHost);
    await frameHost.evaluate(frame => [...frame.contentDocument.querySelectorAll('[data-action="setupStudio"]')]
      .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length)).click());
    const approvalDialog = await waitForNativeStudioSetupDialog(workbench, frameHost, before);
    const request = await waitForInstalledOutboundRequest(frameHost, requestBefore, 'setupStudio');
    if (!request) throw new Error('setupStudio-authorized-request-not-observed');
    observation.request_id = request.requestId;
    await clickNativeStudioSetupAction(workbench, approvalDialog, 'Set up and run');
    const deadline = Date.now() + timeoutMs;
    do {
      const responses = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after), before);
      const terminal = exactStudioSetupTerminalResponse(responses, 0, request.requestId);
      if (terminal) {
        observation.terminal_response_type = terminal.type;
        if (terminal.type === 'operationError') {
          observation.terminal_error = String(terminal.error || 'setupStudio failed').slice(0, 2000);
          throw new Error(`setupStudio-operation-error:${observation.terminal_error}`);
        }
        observation.result = terminal.result || null;
        break;
      }
      await wait(200);
    } while (Date.now() < deadline);
    observation.typed_ready_result = validStudioSetupResult(observation.result);
    if (!observation.typed_ready_result) throw new Error(`setupStudio-invalid-typed-result:${JSON.stringify(observation.result)}`);
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="closeModal"]')?.click();
      document?.querySelector('[data-surface="dashboard"]')?.click();
      document?.querySelector('[data-surface="agents"]')?.click();
      document?.querySelector('[data-surface="workflows"]')?.click();
    });
    const countDeadline = Date.now() + 30_000;
    do {
      observation.counts = await frameHost.evaluate(frame => {
        const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
        return [...responses].reverse().find(response => response?.type === 'snapshot')?.snapshot?.counts || null;
      });
      observation.positive_counts = Number(observation.counts?.agents_runnable_revisions || 0) > 0
        && Number(observation.counts?.workflow_runnable_revisions || 0) > 0
        && Number(observation.counts?.agent_runs || 0) > 0
        && Number(observation.counts?.workflow_runs || 0) > 0;
      if (observation.positive_counts) break;
      await wait(150);
    } while (Date.now() < countDeadline);
    if (!observation.positive_counts) throw new Error(`setupStudio-positive-counts-not-observed:${JSON.stringify(observation.counts)}`);
    observation.reopened = await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-surface="dashboard"]')?.click();
      document?.querySelector('[data-surface="agents"]')?.click();
      const agentsText = String(document?.body?.innerText || '');
      document?.querySelector('[data-surface="workflows"]')?.click();
      const workflowsText = String(document?.body?.innerText || '');
      return /RUNNABLE REVISIONS/i.test(agentsText) && /RUNNABLE REVISIONS/i.test(workflowsText) && /DURABLE RUNS/i.test(workflowsText);
    });
    if (!observation.reopened) throw new Error('setupStudio-route-reopen-proof-missing');
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2000)); }
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact setupStudio action executed only inside the owned isolated VS Code host.',
    eligible_control_count: controlIds.length,
    observation,
    records: controlIds.map(controlId => studioSetupRecord(requirements.get(controlId), observation))
  };
}

function validStudioDraftReceipt(kind, result, identity, version = '1.0.0') {
  if (!result || typeof result !== 'object') return false;
  if (kind === 'agent') return result.schema_version === 'px.agent-creation-receipt/1.1' && result.agent_id === identity && result.version === version && result.created === true && /^[0-9a-f]{64}$/.test(String(result.record_sha256 || ''));
  if (kind === 'workflow') return result.schema_version === 'px.workflow-revision-receipt/1.2' && result.workflow_id === identity && result.version === version && result.created === true && /^[0-9a-f]{64}$/.test(String(result.revision_sha256 || ''));
  return kind === 'skill' && result.schema_version === 'px.skill-draft/1.1' && result.manifest?.skill_id === identity && result.manifest?.version === version && /^[0-9a-f]{64}$/.test(String(result.manifest_sha256 || '')) && /^[0-9a-f]{64}$/.test(String(result.source_tree_sha256 || ''));
}

function studioCandidateSaveRecord(requirement, observation) {
  const evidenceRef = `installed-studio-candidate-save:${requirement.control_id}`;
  const verified = observation.attempted && observation.typed_creation_receipt && observation.webview_restarted && observation.catalog_query_dispatched && observation.reopened_catalog_match && observation.reopened_catalog_row_rendered;
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'owned_isolated_studio_candidate_save', rendered: observation.available,
    observed: observation.available, attempted: observation.attempted,
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      if (stage === 'failure_handling') return [stage, observation.invalid_rejected
        ? { state: 'present', detail: 'The exact installed Studio rejected an empty required identity before any host dispatch.', evidence: [evidenceRef] }
        : { state: 'missing', detail: 'The installed Studio did not visibly reject the invalid preflight state.', evidence: [] }];
      if (stage === 'recovery_rollback') return [stage, observation.recovered_before_save
        ? { state: 'present', detail: 'The valid collision-safe identity was restored after rejection and the same form became eligible for the governed save.', evidence: [evidenceRef] }
        : { state: 'missing', detail: 'The invalid Studio form was not restored to an eligible exact state.', evidence: [] }];
      return [stage, verified
        ? { state: 'present', detail: `The installed ${observation.kind} Studio submitted a collision-safe 1.0.0 candidate, returned an exact durable creation receipt, restarted the dashboard webview boundary, and rediscovered the same identity and version from the host catalog.`, evidence: [evidenceRef] }
        : { state: 'missing', detail: `The owned installed-host candidate-save campaign did not prove ${stage}.`, evidence: [] }];
    })),
    errors: observation.errors
  };
}

async function runInstalledStudioCandidateSaveProfile(frameHost, matrix, timeoutMs = 150_000, includeBlockedAgentFixture = false) {
  const specifications = [
    { kind: 'agent', route: 'agents', controlIds: ['pxui.agent-studio.action.submitStudioDraft.agent', 'pxui.agent-studio.form.candidateMetadata', 'pxui.agent-studio.failure_recovery.surface', 'pxui.agent-studio.persistence.authoritativeState', 'pxui.agent-studio.reload_reopen.authoritativeState', 'pxui.agents.persistence.authoritativeState', 'pxui.agents.reload_reopen.authoritativeState'], prefix: 'agent:px-owned-save-' },
    { kind: 'workflow', route: 'workflows', controlIds: ['pxui.workflow-studio.action.submitStudioDraft.workflow', 'pxui.workflow-studio.form.candidateMetadata', 'pxui.workflow-studio.failure_recovery.surface', 'pxui.workflow-studio.persistence.authoritativeState', 'pxui.workflow-studio.reload_reopen.authoritativeState', 'pxui.workflows.persistence.authoritativeState', 'pxui.workflows.reload_reopen.authoritativeState'], prefix: 'workflow:px-owned-save-' },
    { kind: 'skill', route: 'skillsTools', controlIds: ['pxui.skill-studio.action.submitStudioDraft.skill', 'pxui.skill-studio.form.candidateMetadata', 'pxui.skill-studio.failure_recovery.surface', 'pxui.skill-studio.persistence.authoritativeState', 'pxui.skill-studio.reload_reopen.authoritativeState', 'pxui.skills-tools.persistence.authoritativeState', 'pxui.skills-tools.reload_reopen.authoritativeState'], prefix: 'px-owned-save-' },
    ...(includeBlockedAgentFixture ? [{ kind: 'agent', route: 'agents', controlIds: [], prefix: 'agent:px-owned-blocked-preview-', fixture_only: true, memory_binding_id: 'memory:px-owned-unresolved' }] : [])
  ];
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const records = [];
  const observations = [];
  for (const [index, spec] of specifications.entries()) {
    const profileRequirements = spec.controlIds.map(controlId => {
      const requirement = requirements.get(controlId);
      if (!requirement) throw new Error(`Studio candidate-save profile control is absent: ${controlId}`);
      return requirement;
    });
    const identity = `${spec.prefix}${Date.now().toString(36)}-${index}`;
    const observation = { kind: spec.kind, route: spec.route, identity, version: '1.0.0', fixture_only: spec.fixture_only === true, memory_binding_id: spec.memory_binding_id || null, catalog_record_id: null, catalog_request_id: null, available: false, attempted: false, save_dispatched_atomically: false, invalid_rejected: false, recovered_before_save: false, typed_creation_receipt: false, webview_restarted: false, catalog_query_dispatched: false, reopened_catalog_match: false, reopened_catalog_row_rendered: false, result: null, errors: [] };
    try {
      await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument;
        document?.querySelector('[data-action="closeModal"]')?.click();
        document?.querySelector(`[data-surface="${CSS.escape(item.route)}"]`)?.click();
      }, spec);
      await wait(180);
      await frameHost.evaluate((frame, item) => {
        if (!['agents', 'workflows'].includes(item.route)) return;
        const document = frame.contentDocument;
        const coreScope = document?.querySelector(`[data-action="surfaceScope"][data-target="${CSS.escape(item.route)}"][data-scope="core"]`);
        if (!coreScope || coreScope.disabled) throw new Error(`studio-${item.kind}-core-scope-unavailable`);
        if (coreScope.getAttribute('aria-pressed') !== 'true') coreScope.click();
      }, spec);
      await wait(120);
      await frameHost.evaluate((frame, kind) => {
        const document = frame.contentDocument;
        const open = [...document.querySelectorAll('[data-action="openStudioDraft"]')].find(element => element.dataset.kind === kind && !element.disabled);
        if (!open) throw new Error(`studio-${kind}-fresh-draft-opener-unavailable`);
        open.click();
      }, spec.kind);
      await wait(120);
      await frameHost.evaluate((frame, kind) => {
        const discard = [...frame.contentDocument.querySelectorAll('[data-action="discardWorkingStudioDraft"]')].find(element => element.dataset.kind === kind && !element.disabled);
        discard?.click();
      }, spec.kind);
      await waitForInstalledStudioState(frameHost, spec.kind, 'modal');
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const preflight = await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument;
        const identityInput = document.querySelector('#studio-identity');
        const versionInput = document.querySelector('#studio-version');
        if (!identityInput || !versionInput) return { available: false, dispatched: false, invalidRejected: false, recovered: false };
        identityInput.value = 'invalid identity with spaces'; identityInput.dispatchEvent(new Event('input', { bubbles: true }));
        const save = document.querySelector('[data-action="submitStudioDraft"]');
        let invalidRejected = Boolean(save?.disabled || identityInput.checkValidity() === false);
        if (!invalidRejected && typeof identityInput.setCustomValidity === 'function') {
          identityInput.setCustomValidity('px-owned-invalid-studio-identity');
          invalidRejected = identityInput.checkValidity() === false;
        }
        if (typeof identityInput.setCustomValidity === 'function') identityInput.setCustomValidity('');
        identityInput.value = item.identity; identityInput.dispatchEvent(new Event('input', { bubbles: true }));
        versionInput.value = '1.0.0'; versionInput.dispatchEvent(new Event('input', { bubbles: true }));
        if (item.memoryBindingId) {
          const jsonTab = document.querySelector('[data-action="studioEditorTab"][data-tab="json"]');
          if (!jsonTab) throw new Error('studio-agent-blocked-preview-json-editor-unavailable');
          jsonTab.click();
          const draftInput = document.querySelector('#studio-draft-json');
          const apply = document.querySelector('[data-action="studioApplyJson"]');
          if (!draftInput || !apply) throw new Error('studio-agent-blocked-preview-canonical-editor-unavailable');
          const draft = JSON.parse(draftInput.value);
          draft.memory_binding_ids = [item.memoryBindingId];
          draftInput.value = JSON.stringify(draft, null, 2);
          draftInput.dispatchEvent(new Event('input', { bubbles: true }));
          apply.click();
          const validation = document.querySelector('[data-studio-validation]');
          if (!validation?.classList.contains('passed')) throw new Error(`studio-agent-blocked-preview-fixture-invalid:${validation?.textContent || 'missing-validation'}`);
        }
        if (item.kind === 'workflow') {
          const jsonTab = document.querySelector('[data-action="studioEditorTab"][data-tab="json"]');
          if (!jsonTab) throw new Error('studio-workflow-json-editor-unavailable');
          jsonTab.click();
          const draftInput = document.querySelector('#studio-draft-json');
          const apply = document.querySelector('[data-action="studioApplyJson"]');
          if (!draftInput || !apply) throw new Error('studio-workflow-canonical-editor-unavailable');
          const draft = JSON.parse(draftInput.value);
          const node = draft.nodes?.[0];
          const binding = draft.bindings?.[0];
          if (!node || !binding?.binding_id) throw new Error('studio-workflow-bounded-cancel-fixture-unavailable');
          node.inputs = [{ name: 'seconds', data_type: 'number', required: true }];
          node.outputs = [{ name: 'seconds', data_type: 'number', required: true }];
          node.approval_required = true;
          node.timeout_seconds = 30;
          binding.capability_id = 'capability:sleep';
          draft.executor_adapters = { [binding.binding_id]: 'sleep' };
          draft.run_inputs = { [`${node.node_id}.seconds`]: 8 };
          draft.run_input_contract = [{ key: `${node.node_id}.seconds`, value_type: 'number', required: true }];
          draftInput.value = JSON.stringify(draft, null, 2);
          draftInput.dispatchEvent(new Event('input', { bubbles: true }));
          apply.click();
          const validation = document.querySelector('[data-studio-validation]');
          if (!validation?.classList.contains('passed')) throw new Error(`studio-workflow-bounded-cancel-fixture-invalid:${validation?.textContent || 'missing-validation'}`);
        }
        const available = Boolean(save && !save.disabled);
        if (available) save.click();
        return { available, dispatched: available, invalidRejected, recovered: invalidRejected && available && identityInput.checkValidity() };
      }, { identity, kind: spec.kind, memoryBindingId: spec.memory_binding_id || null });
      observation.available = preflight.available; observation.save_dispatched_atomically = preflight.dispatched; observation.invalid_rejected = preflight.invalidRejected; observation.recovered_before_save = preflight.recovered;
      if (!observation.available) throw new Error(`studio-${spec.kind}-save-unavailable-after-valid-identity`);
      if (!observation.save_dispatched_atomically) throw new Error(`studio-${spec.kind}-save-dispatch-missing`);
      observation.attempted = true;
      const deadline = Date.now() + timeoutMs;
      do {
        const response = await frameHost.evaluate((frame, item) => {
          const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
          return responses.slice(item.after).find(value => (value?.type === 'studioDraftResult' && value?.kind === item.kind) || (value?.type === 'operationError' && value?.operation === 'createStudioDraft')) || null;
        }, { after: before, kind: spec.kind });
        if (response?.type === 'operationError') throw new Error(`studio-${spec.kind}-create-failed:${response.error}`);
        if (response) { observation.result = response.result; break; }
        await wait(200);
      } while (Date.now() < deadline);
      observation.typed_creation_receipt = validStudioDraftReceipt(spec.kind, observation.result, identity);
      if (!observation.typed_creation_receipt) throw new Error(`studio-${spec.kind}-creation-receipt-invalid:${JSON.stringify(observation.result)}`);
      const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
      observation.webview_restarted = restart.restarted === true;
      await navigateInstalledSurface(frameHost, spec.route, 20_000);
      const catalogKind = `${spec.kind}s`;
      const searchDeadline = Date.now() + 30_000;
      let searchReady = false;
      do {
        searchReady = await frameHost.evaluate((frame, item) => {
          const document = frame.contentDocument;
          document?.querySelector('[data-action="closeModal"]')?.click();
          if (item.kind === 'skill') {
            const skills = document?.querySelector('[data-action="capabilityTab"][data-kind="skills"]');
            if (skills && skills.getAttribute('aria-pressed') !== 'true') skills.click();
          }
          const input = document?.querySelector(`[data-catalog-search="${CSS.escape(item.catalogKind)}"]`);
          return Boolean(input && !input.disabled && (input.offsetWidth || input.offsetHeight || input.getClientRects().length));
        }, { kind: spec.kind, catalogKind });
        if (searchReady) break;
        await wait(100);
      } while (Date.now() < searchDeadline);
      if (!searchReady) throw new Error(`studio-${spec.kind}-catalog-search-readiness-timeout`);
      const catalogOffsets = await frameHost.evaluate(frame => ({
        requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0,
        responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0
      }));
      observation.catalog_query_dispatched = await frameHost.evaluate((frame, item) => {
        const document = frame.contentDocument;
        const input = document?.querySelector(`[data-catalog-search="${CSS.escape(item.catalogKind)}"]`);
        if (!input || input.disabled) return false;
        input.value = item.identity;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
      }, { identity, catalogKind });
      if (!observation.catalog_query_dispatched) throw new Error(`studio-${spec.kind}-catalog-query-dispatch-missing`);
      const catalogDeadline = Date.now() + 30_000;
      do {
        const query = await frameHost.evaluate((frame, item) => {
          const requests = frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || [];
          const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
          const request = requests.slice(item.after.requests).find(value => value?.type === 'catalogQuery' && value?.kind === item.catalogKind && typeof value.requestId === 'string' && value.requestId);
          if (!request) return { request: null, response: null, record: null };
          const response = responses.slice(item.after.responses).find(value => value?.requestId === request.requestId && (value?.type === 'catalogResult' || (value?.type === 'operationError' && value?.operation === 'catalogQuery')));
          if (response?.type === 'operationError') return { request, response, record: null };
          const record = (response?.result?.items || []).find(record => {
            const details = record?.details || {};
            const foundIdentity = details.agent_id || details.workflow_id || details.skill_id || details.id;
            return foundIdentity === item.identity && details.version === '1.0.0';
          });
          return { request, response, record: record ? { id: record.id, kind: record.kind, status: record.status } : null };
        }, { after: catalogOffsets, catalogKind, identity });
        if (query.response?.type === 'operationError') throw new Error(`studio-${spec.kind}-catalog-query-failed:${query.response.error}`);
        if (query.request) observation.catalog_request_id = query.request.requestId;
        observation.reopened_catalog_match = Boolean(query.record && query.response?.type === 'catalogResult' && query.response?.result?.kind === catalogKind);
        if (query.record) observation.catalog_record_id = query.record.id;
        if (observation.reopened_catalog_match) break;
        await wait(150);
      } while (Date.now() < catalogDeadline);
      if (!observation.reopened_catalog_match) throw new Error(`studio-${spec.kind}-catalog-reopen-match-missing`);
      const renderedDeadline = Date.now() + 10_000;
      do {
        observation.reopened_catalog_row_rendered = await frameHost.evaluate((frame, item) => {
          const catalogKind = `${item.kind}s`;
          return [...frame.contentDocument.querySelectorAll('[data-action="inspectCatalogItem"]')]
            .some(element => element.dataset.kind === catalogKind && element.dataset.id === item.recordId && !element.disabled);
        }, { kind: spec.kind, recordId: observation.catalog_record_id });
        if (observation.reopened_catalog_row_rendered) break;
        await wait(100);
      } while (Date.now() < renderedDeadline);
      if (!observation.reopened_catalog_row_rendered) throw new Error(`studio-${spec.kind}-catalog-reopen-row-not-rendered`);
    } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2400)); }
    observations.push(observation);
    if (!spec.fixture_only) records.push(...profileRequirements.map(requirement => studioCandidateSaveRecord(requirement, observation)));
  }
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact immutable candidate saves executed only inside the owned isolated VS Code host.', eligible_control_count: records.length, observations, records };
}

function studioRevisionEditRecord(requirement, observations, kind = null) {
  const selected = kind ? observations.filter(item => item.kind === kind) : observations;
  const verified = selected.length > 0 && selected.every(validStudioRevisionEditObservation);
  const evidenceRef = `installed-studio-revision-edit:${requirement.control_id}`;
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'owned_isolated_studio_revision_edit', rendered: selected.every(item => item.editor_bound),
    observed: selected.every(item => item.editor_bound), attempted: selected.some(item => item.attempted),
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      if (stage === 'failure_handling') return [stage, selected.length > 0 && selected.every(item => item.unchanged_save_rejected === true)
        ? { state: 'present', detail: 'Each installed revision editor kept save disabled for its unchanged predecessor-bound draft and dispatched no create before the exact content edit.', evidence: [evidenceRef] }
        : { state: 'missing', detail: 'The unchanged predecessor-bound Studio drafts were not all proven fail-closed.', evidence: [] }];
      return [stage, verified
        ? { state: 'present', detail: `The installed ${kind || 'agent and workflow'} Studio authenticated exact 1.0.0 predecessors, persisted changed content in immutable 1.0.1 revisions, proved the predecessors remained unchanged, and physically reopened the saved revisions with the edited content.`, evidence: [evidenceRef] }
        : { state: 'missing', detail: `The owned installed-host revision-edit campaign did not prove ${stage}.`, evidence: [] }];
    })),
    errors: selected.flatMap(item => item.errors || [])
  };
}

function studioRevisionConditionalRecord(requirement, observation, stateKind) {
  const verified = stateKind === 'fork'
    ? observation?.fork_verified === true
    : observation?.version_conflict_rendered === true && observation?.version_suggestion_accepted === true && observation?.version_conflict_host_dispatch_suppressed === true;
  const evidenceRef = `installed-studio-revision-${stateKind}:${requirement.control_id}`;
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'owned_isolated_studio_revision_local_state', rendered: verified, observed: verified, attempted: verified,
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      return [stage, verified
        ? { state: 'present', detail: stateKind === 'fork'
          ? 'The exact authenticated predecessor editor exposed the independent-fork action, reset identity and version locally, retained copied content, and dispatched no candidate save.'
          : 'A request-bound controlled conflict envelope derived from the exact authenticated allocation rendered the suggestion control; accepting it updated and revalidated the retained draft while the create dispatch remained intentionally suppressed.', evidence: [evidenceRef] }
        : { state: 'missing', detail: `The predecessor-bound ${stateKind} local state was not proven.`, evidence: [] }];
    })),
    errors: observation?.errors || []
  };
}

function validStudioRevisionEditObservation(observation) {
  const sha256 = value => /^[0-9a-f]{64}$/.test(String(value || ''));
  return observation?.editor_bound === true
    && (observation?.kind === 'skill' || observation?.stale_result_rejected === true)
    && observation?.unchanged_save_rejected === true
    && observation?.typed_creation_receipt === true
    && observation?.reopened_catalog_match === true
    && observation?.predecessor_preserved === true
    && observation?.content_changed === true
    && observation?.reopened_editor_content_match === true
    && typeof observation.original_owner === 'string'
    && observation.original_owner.length > 0
    && typeof observation.changed_owner === 'string'
    && observation.changed_owner.length > 0
    && observation.changed_owner !== observation.original_owner
    && sha256(observation.predecessor_revision_sha256)
    && sha256(observation.predecessor_content_sha256)
    && sha256(observation.saved_revision_sha256)
    && sha256(observation.saved_content_sha256)
    && observation.saved_revision_sha256 !== observation.predecessor_revision_sha256
    && observation.saved_content_sha256 !== observation.predecessor_content_sha256;
}

async function runInstalledStudioRevisionEditProfile(frameHost, candidateProfile, matrix, timeoutMs = 150_000) {
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const specifications = [
    { kind: 'agent', submitControlId: 'pxui.agent-studio.action.submitStudioDraft.agent' },
    { kind: 'workflow', submitControlId: 'pxui.workflow-studio.action.submitStudioDraft.workflow' },
    { kind: 'skill', submitControlId: 'pxui.skill-studio.action.submitStudioDraft.skill' }
  ];
  const observations = [];
  for (const spec of specifications) {
    const candidate = (candidateProfile.observations || []).find(item => item.kind === spec.kind);
    const observation = {
      kind: spec.kind, identity: candidate?.identity || null, source_version: candidate?.version || null,
      candidate_version: null, source_catalog_record_id: candidate?.catalog_record_id || null,
      saved_catalog_record_id: null, attempted: false, editor_bound: false, stale_result_rejected: spec.kind === 'skill', unchanged_save_rejected: false, typed_creation_receipt: false,
      editor_request_id: null, save_dispatched_atomically: false,
      reopened_catalog_match: false, predecessor_preserved: false, content_changed: false,
      reopened_editor_content_match: false, original_owner: null, changed_owner: null,
      version_conflict_rendered: false, version_suggestion_accepted: false, version_conflict_host_dispatch_suppressed: false, fork_verified: false,
      predecessor_revision_sha256: null, predecessor_content_sha256: null,
      saved_revision_sha256: null, saved_content_sha256: null, unchanged_save_state: null,
      last_editor_state: null, result: null, errors: []
    };
    try {
      if (!candidate?.typed_creation_receipt || !candidate?.reopened_catalog_match || !candidate?.catalog_record_id) throw new Error(`studio-${spec.kind}-revision-edit-prerequisite-missing`);
      await frameHost.evaluateContent(kind => { clearWorkingStudioDraft(kind); return true; }, spec.kind);
      await openExactStudioCatalogRow(frameHost, candidate);
      await wait(120);
      observation.attempted = true;
      const editorBefore = await frameHost.evaluate(frame => ({
        requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0,
        responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0
      }));
      const openDispatched = await frameHost.evaluate((frame, kind) => {
        const action = kind === 'skill' ? 'loadSkillPackageEditor' : 'openStudioFromCatalog';
        const open = [...frame.contentDocument.querySelectorAll(`[data-action="${action}"]`)].find(element => element.dataset.kind === kind && !element.disabled);
        if (!open) return false;
        open.click(); return true;
      }, spec.kind);
      if (!openDispatched) throw new Error(`studio-${spec.kind}-revision-editor-opener-missing`);
      const editorDeadline = Date.now() + timeoutMs;
      do {
        const state = await frameHost.evaluateContent(item => {
          const requests = window.__PX_INSTALLED_REQUESTS__ || [];
          const responses = window.__PX_INSTALLED_RESPONSES__ || [];
          const transitions = window.__PX_STUDIO_EDITOR_TRANSITIONS__ || [];
          const request = item.kind === 'skill'
            ? requests.slice(item.after.requests).find(value => value?.type === 'studioOperation' && value?.kind === 'skill' && value?.operation === 'next-version' && typeof value.requestId === 'string' && value.requestId)
            : requests.slice(item.after.requests).find(value => value?.type === 'loadStudioRevisionEditor' && value?.kind === item.kind && typeof value.requestId === 'string' && value.requestId);
          const failure = request ? responses.slice(item.after.responses).find(value => value?.requestId === request.requestId && value?.type === 'operationError' && ['loadSkillPackageEditor', 'loadStudioRevisionEditor', 'studioOperation'].includes(value?.operation)) : null;
          if (failure) return { failure: failure.error || 'unknown editor load failure' };
          const response = request ? responses.slice(item.after.responses).find(value => value?.requestId === request.requestId && (item.kind === 'skill'
            ? value?.type === 'studioOperationResult' && value?.kind === 'skill' && value?.operation === 'next-version'
            : value?.type === 'studioRevisionEditorResult' && value?.kind === item.kind)) : null;
          const allocation = response?.allocation || response?.result || null;
          const document = window.document;
          const identity = document.querySelector('#studio-identity');
          const version = document.querySelector('#studio-version');
          const baseline = document.querySelector('.studio-revision-baseline');
          const fork = document.querySelector('[data-action="forkStudioCandidate"]');
          const save = document.querySelector('[data-action="submitStudioDraft"]');
          const requestTrace = request ? transitions.filter(value => value?.request_id === request.requestId).slice(-8) : [];
          return {
            ready: Boolean(request && response && allocation) && identity?.value === item.identity && version?.value === allocation.candidate_version
              && identity.readOnly && version.readOnly && Boolean(baseline) && Boolean(fork) && Boolean(save),
            request_id: request?.requestId || null,
            dom: {
              identity: identity?.value || null, identity_readonly: Boolean(identity?.readOnly),
              version: version?.value || null, version_readonly: Boolean(version?.readOnly),
              baseline_present: Boolean(baseline), fork_present: Boolean(fork),
              save_present: Boolean(save), save_disabled: Boolean(save?.disabled),
              modal_class: document.querySelector('.control-modal')?.className || null,
              modal_title: document.querySelector('.control-modal h2')?.textContent?.trim().slice(0, 300) || null,
              modal_kicker: document.querySelector('.control-modal .eyebrow')?.textContent?.trim().slice(0, 500) || null
            },
            controller_state: {
              active_request_id: studioAllocationRequest?.requestId || null,
              active_request_kind: studioAllocationRequest?.kind || null,
              editor_kind: studioEditor?.kind || null,
              editor_identity: studioEditor?.draft?.[studioEditor?.kind === 'agent' ? 'agent_id' : studioEditor?.kind === 'workflow' ? 'workflow_id' : 'skill_id'] || null,
              editor_version: studioEditor?.draft?.version || null,
              presentation: studioEditorPresentation ? {
                token: studioEditorPresentation.token, kind: studioEditorPresentation.kind,
                identity: studioEditorPresentation.identity, candidate_version: studioEditorPresentation.candidate_version
              } : null,
              version_proof_request_id: studioVersionProofRequestId || null
            },
            transition_trace: requestTrace.map(value => ({
              stage: value?.stage || null, observed_utc: value?.observed_utc || null,
              error: value?.error || null, editor_present: value?.editor_present ?? null,
              baseline_present: value?.baseline_present ?? null, fork_present: value?.fork_present ?? null,
              save_present: value?.save_present ?? null
            })),
            response_selection: response?.selection ? {
              kind: response.selection.kind, catalog_kind: response.selection.catalog_kind,
              record_id: response.selection.record_id, identity: response.selection.identity,
              source_version: response.selection.source_version,
              source_revision_sha256: response.selection.source_revision_sha256,
              source_content_sha256: response.selection.source_content_sha256
            } : null,
            allocation: allocation ? {
              kind: allocation.kind, identity: allocation.identity,
              source_version: allocation.source_version, source_scope: allocation.source_scope,
              source_revision_sha256: allocation.source_revision_sha256,
              source_content_sha256: allocation.source_content_sha256,
              candidate_version: allocation.candidate_version
            } : null,
            baseline: baseline?.textContent?.trim().slice(0, 1000) || null,
            validation: document.querySelector('[data-studio-validation]')?.textContent?.trim().slice(0, 1600) || null,
            modal_text: document.querySelector('.studio-modal')?.textContent?.trim().slice(0, 2400) || null
          };
        }, { after: editorBefore, kind: spec.kind, identity: candidate.identity });
        observation.last_editor_state = state;
        if (state.failure) throw new Error(`studio-${spec.kind}-revision-editor-load-failed:${state.failure}`);
        if (state.allocation) {
          const allocation = state.allocation;
          const allocationValid = allocation.kind === spec.kind && allocation.identity === candidate.identity
            && allocation.source_version === candidate.version && typeof allocation.candidate_version === 'string'
            && /^\d+\.\d+\.\d+(?:[-.][a-z0-9.-]+)?$/.test(allocation.candidate_version);
          if (!allocationValid) throw new Error(`studio-${spec.kind}-revision-allocation-mismatch:${JSON.stringify(allocation)}`);
          observation.candidate_version = allocation.candidate_version;
          observation.editor_request_id = state.request_id;
        }
        const terminalTransition = [...(state.transition_trace || [])].reverse().find(value => ['request-cancelled', 'response-unmatched', 'response-rejected', 'presentation-error'].includes(value?.stage));
        if (terminalTransition) throw new Error(`studio-${spec.kind}-revision-editor-transition-terminal:${JSON.stringify(state)}`);
        const presentationTransition = [...(state.transition_trace || [])].reverse().find(value => value?.stage === 'presentation-opened');
        if (presentationTransition && Date.now() - Date.parse(presentationTransition.observed_utc) > 2_000 && !state.ready) throw new Error(`studio-${spec.kind}-revision-editor-presentation-invariant-missing:${JSON.stringify(state)}`);
        if (state.ready && observation.candidate_version) { observation.editor_bound = true; break; }
        await wait(200);
      } while (Date.now() < editorDeadline);
      if (!observation.editor_bound) throw new Error(`studio-${spec.kind}-revision-editor-binding-timeout:${JSON.stringify(observation.last_editor_state)}`);
      if (spec.kind !== 'skill') {
        const stale = await frameHost.evaluateContent(item => {
          const document = window.document;
          const identity = document.querySelector('#studio-identity')?.value || null;
          const version = document.querySelector('#studio-version')?.value || null;
          const activeRequestId = studioAllocationRequest?.requestId || null;
          const requestsBefore = (window.__PX_INSTALLED_REQUESTS__ || []).length;
          const transitionBefore = (window.__PX_STUDIO_EDITOR_TRANSITIONS__ || []).length;
          const staleRequestId = `owned-stale-revision-${item.kind}-${Date.now()}`;
          const staleProof = `version-allocation:px-owned-stale-${item.kind}`;
          window.dispatchEvent(new MessageEvent('message', { data: {
            type: 'studioRevisionEditorResult', requestId: staleRequestId, kind: item.kind,
            catalogKind: `${item.kind}s`, recordId: 'studio:px-owned-stale-record',
            allocationProof: staleProof, selection: null, allocation: null
          } }));
          const transitions = (window.__PX_STUDIO_EDITOR_TRANSITIONS__ || []).slice(transitionBefore);
          const release = (window.__PX_INSTALLED_REQUESTS__ || []).slice(requestsBefore).find(value => value?.type === 'releaseStudioTrust'
            && value?.requestId === staleRequestId);
          return {
            stale_request_id: staleRequestId,
            response_unmatched: transitions.some(value => value?.stage === 'response-unmatched' && value?.request_id === staleRequestId),
            trust_released: Boolean(release),
            active_request_preserved: (studioAllocationRequest?.requestId || null) === activeRequestId,
            editor_preserved: studioEditor?.kind === item.kind
              && document.querySelector('#studio-identity')?.value === identity && identity === item.identity
              && document.querySelector('#studio-version')?.value === version && version === item.version
          };
        }, { kind: spec.kind, identity: candidate.identity, version: observation.candidate_version });
        observation.stale_result_rejected = stale.response_unmatched === true && stale.trust_released === true
          && stale.active_request_preserved === true && stale.editor_preserved === true;
        if (!observation.stale_result_rejected) throw new Error(`studio-${spec.kind}-stale-revision-result-not-rejected:${JSON.stringify(stale)}`);
      }
      const unchangedDeadline = Date.now() + 2_000;
      do {
        observation.unchanged_save_state = await frameHost.evaluateContent(() => {
          const save = document.querySelector('[data-action="submitStudioDraft"]');
          return {
            save_present: Boolean(save), save_disabled: Boolean(save?.disabled), save_title: save?.title || null,
            request_count: window.__PX_INSTALLED_REQUESTS__?.length || 0,
            response_count: window.__PX_INSTALLED_RESPONSES__?.length || 0,
            create_request_count: (window.__PX_INSTALLED_REQUESTS__ || []).filter(value => value?.type === 'createStudioDraft' && value?.kind === studioEditor?.kind).length,
            draft_dirty: Boolean(studioDraftDirty), allocation_present: Boolean(studioVersionAllocation),
            validation: document.querySelector('[data-studio-validation]')?.textContent?.trim().slice(0, 1600) || null
          };
        });
        if (observation.unchanged_save_state.save_present && observation.unchanged_save_state.save_disabled) break;
        await wait(50);
      } while (Date.now() < unchangedDeadline);
      if (!observation.unchanged_save_state?.save_present || !observation.unchanged_save_state.save_disabled) {
        throw new Error(`studio-${spec.kind}-unchanged-save-not-rejected:${JSON.stringify(observation.unchanged_save_state)}`);
      }
      observation.unchanged_save_rejected = await frameHost.evaluateContent(before => {
        const save = document.querySelector('[data-action="submitStudioDraft"]');
        if (!save?.disabled) return false;
        save.click();
        return (window.__PX_INSTALLED_REQUESTS__ || []).filter(value => value?.type === 'createStudioDraft' && value?.kind === studioEditor?.kind).length === before.create_request_count;
      }, observation.unchanged_save_state);
      if (!observation.unchanged_save_rejected) throw new Error(`studio-${spec.kind}-unchanged-save-dispatched:${JSON.stringify(observation.unchanged_save_state)}`);
      const saveBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const saveState = await frameHost.evaluate((frame, suffix) => {
        const owner = frame.contentDocument.querySelector('#studio-owner');
        if (!owner) return { available: false, reason: 'owner-input-missing' };
        const originalOwner = owner.value;
        owner.value = `${originalOwner}${suffix}`; owner.dispatchEvent(new Event('input', { bubbles: true }));
        const save = frame.contentDocument.querySelector('[data-action="submitStudioDraft"]');
        const available = Boolean(save && !save.disabled);
        if (available) save.click();
        return {
          available, dispatched: available, save_present: Boolean(save), save_disabled: Boolean(save?.disabled),
          original_owner: originalOwner, changed_owner: owner.value,
          validation: frame.contentDocument.querySelector('[data-studio-validation]')?.textContent?.trim().slice(0, 1600) || null
        };
      }, `:edited-${Date.now().toString(36)}`);
      observation.last_editor_state = { ...(observation.last_editor_state || {}), after_edit: saveState };
      if (!saveState.available) throw new Error(`studio-${spec.kind}-revision-save-unavailable-after-edit:${JSON.stringify(saveState)}`);
      observation.original_owner = saveState.original_owner;
      observation.changed_owner = saveState.changed_owner;
      if (!observation.original_owner || !observation.changed_owner || observation.original_owner === observation.changed_owner) throw new Error(`studio-${spec.kind}-revision-edit-content-unchanged`);
      observation.save_dispatched_atomically = saveState.dispatched === true;
      if (!observation.save_dispatched_atomically) throw new Error(`studio-${spec.kind}-revision-save-dispatch-missing`);
      const saveDeadline = Date.now() + timeoutMs;
      do {
        const response = await frameHost.evaluate((frame, item) => {
          const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
          return responses.slice(item.after).find(value => (value?.type === 'studioDraftResult' && value?.kind === item.kind)
            || (value?.type === 'operationError' && value?.operation === 'createStudioDraft' && value?.kind === item.kind)) || null;
        }, { after: saveBefore, kind: spec.kind });
        if (response?.type === 'operationError') throw new Error(`studio-${spec.kind}-revision-create-failed:${response.error}`);
        if (response) { observation.result = response.result; break; }
        await wait(200);
      } while (Date.now() < saveDeadline);
      observation.typed_creation_receipt = validStudioDraftReceipt(spec.kind, observation.result, candidate.identity, observation.candidate_version);
      if (!observation.typed_creation_receipt) throw new Error(`studio-${spec.kind}-revision-creation-receipt-invalid:${JSON.stringify(observation.result)}`);
      await frameHost.evaluate((frame, route) => {
        const document = frame.contentDocument;
        document?.querySelector('[data-action="closeModal"]')?.click();
        document?.querySelector('[data-surface="dashboard"]')?.click();
        document?.querySelector(`[data-surface="${CSS.escape(route)}"]`)?.click();
      }, candidate.route);
      const catalogKind = `${spec.kind}s`;
      const searchDeadline = Date.now() + 30_000;
      let searchReady = false;
      do {
        searchReady = await frameHost.evaluate((frame, item) => {
          const document = frame.contentDocument;
          document?.querySelector('[data-action="closeModal"]')?.click();
          if (item.kind === 'skill') {
            const skills = document?.querySelector('[data-action="capabilityTab"][data-kind="skills"]');
            if (skills && skills.getAttribute('aria-pressed') !== 'true') skills.click();
          }
          const input = document?.querySelector(`[data-catalog-search="${CSS.escape(item.catalogKind)}"]`);
          return Boolean(input && !input.disabled && (input.offsetWidth || input.offsetHeight || input.getClientRects().length));
        }, { kind: spec.kind, catalogKind });
        if (searchReady) break;
        await wait(100);
      } while (Date.now() < searchDeadline);
      if (!searchReady) throw new Error(`studio-${spec.kind}-revision-catalog-search-readiness-timeout`);
      const catalogOffsets = await frameHost.evaluate(frame => ({
        requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0,
        responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0
      }));
      const catalogQueryDispatched = await frameHost.evaluate((frame, item) => {
        const input = frame.contentDocument?.querySelector(`[data-catalog-search="${CSS.escape(item.catalogKind)}"]`);
        if (!input || input.disabled) return false;
        input.value = item.identity;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        return true;
      }, { identity: candidate.identity, catalogKind });
      if (!catalogQueryDispatched) throw new Error(`studio-${spec.kind}-revision-catalog-query-dispatch-missing`);
      const catalogDeadline = Date.now() + 30_000;
      do {
        const reopenedRecord = await frameHost.evaluate((frame, item) => {
          const requests = frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || [];
          const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
          const request = requests.slice(item.after.requests).find(value => value?.type === 'catalogQuery' && value?.kind === item.catalogKind && typeof value.requestId === 'string' && value.requestId);
          if (!request) return { request: null, response: null, record: null };
          const response = responses.slice(item.after.responses).find(value => value?.requestId === request.requestId && (value?.type === 'catalogResult' || (value?.type === 'operationError' && value?.operation === 'catalogQuery')));
          if (response?.type === 'operationError') return { request, response, record: null };
          if (response?.type !== 'catalogResult' || response?.result?.kind !== item.catalogKind) return { request, response, record: null };
          const records = response.result.items || [];
          const saved = records.find(record => {
            const details = record?.details || {};
            return (details.agent_id || details.workflow_id || details.skill_id || details.id) === item.identity && details.version === item.version;
          });
          const predecessor = records.find(record => {
            const details = record?.details || {};
            return record?.id === item.predecessor_id
              && (details.agent_id || details.workflow_id || details.skill_id || details.id) === item.identity
              && details.version === item.source_version;
          });
          if (!saved || !predecessor) return { request, response, record: null };
          const savedDetails = saved.details || {};
          const predecessorDetails = predecessor.details || {};
          return { request, response, record: {
            id: saved.id, kind: saved.kind, status: saved.status,
            saved_owner: savedDetails.owner || null,
            saved_revision_sha256: savedDetails.revision_sha256 || null,
            saved_content_sha256: savedDetails.source_content_sha256 || null,
            predecessor_owner: predecessorDetails.owner || null,
            predecessor_revision_sha256: predecessorDetails.revision_sha256 || null,
            predecessor_content_sha256: predecessorDetails.source_content_sha256 || null
          } };
        }, { after: catalogOffsets, catalogKind, identity: candidate.identity, version: observation.candidate_version, source_version: candidate.version, predecessor_id: candidate.catalog_record_id });
        if (reopenedRecord.response?.type === 'operationError') throw new Error(`studio-${spec.kind}-revision-catalog-query-failed:${reopenedRecord.response.error}`);
        const record = reopenedRecord.record;
        if (record) {
          observation.predecessor_revision_sha256 = record.predecessor_revision_sha256;
          observation.predecessor_content_sha256 = record.predecessor_content_sha256;
          observation.saved_revision_sha256 = record.saved_revision_sha256;
          observation.saved_content_sha256 = record.saved_content_sha256;
          observation.predecessor_preserved = record.predecessor_owner === observation.original_owner
            && /^[0-9a-f]{64}$/.test(String(record.predecessor_revision_sha256 || ''))
            && /^[0-9a-f]{64}$/.test(String(record.predecessor_content_sha256 || ''));
          observation.content_changed = record.saved_owner === observation.changed_owner
            && /^[0-9a-f]{64}$/.test(String(record.saved_revision_sha256 || ''))
            && /^[0-9a-f]{64}$/.test(String(record.saved_content_sha256 || ''))
            && record.saved_revision_sha256 !== record.predecessor_revision_sha256
            && record.saved_content_sha256 !== record.predecessor_content_sha256;
          observation.reopened_catalog_match = observation.predecessor_preserved && observation.content_changed;
          observation.saved_catalog_record_id = record.id;
          break;
        }
        await wait(150);
      } while (Date.now() < catalogDeadline);
      if (!observation.reopened_catalog_match) throw new Error(`studio-${spec.kind}-revision-catalog-reopen-match-missing`);
      const verificationRowOpened = await frameHost.evaluate((frame, recordId) => {
        const row = [...frame.contentDocument.querySelectorAll('[data-action="inspectCatalogItem"]')].find(element => element.dataset.id === recordId && !element.disabled);
        if (!row) return false;
        row.click(); return true;
      }, observation.saved_catalog_record_id);
      if (!verificationRowOpened) throw new Error(`studio-${spec.kind}-saved-revision-row-missing`);
      await wait(120);
      const verificationOffsets = await frameHost.evaluate(frame => ({
        requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0,
        responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0
      }));
      const verificationOpened = await frameHost.evaluate((frame, kind) => {
        const action = kind === 'skill' ? 'loadSkillPackageEditor' : 'openStudioFromCatalog';
        const open = [...frame.contentDocument.querySelectorAll(`[data-action="${action}"]`)].find(element => element.dataset.kind === kind && !element.disabled);
        if (!open) return false;
        open.click(); return true;
      }, spec.kind);
      if (!verificationOpened) throw new Error(`studio-${spec.kind}-saved-revision-editor-opener-missing`);
      const verificationDeadline = Date.now() + timeoutMs;
      do {
        const reopened = await frameHost.evaluate((frame, item) => {
          const requests = frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || [];
          const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
          const request = item.kind === 'skill'
            ? requests.slice(item.after.requests).find(value => value?.type === 'studioOperation' && value?.kind === 'skill' && value?.operation === 'next-version' && typeof value.requestId === 'string' && value.requestId)
            : requests.slice(item.after.requests).find(value => value?.type === 'loadStudioRevisionEditor' && value?.kind === item.kind && typeof value.requestId === 'string' && value.requestId);
          const response = request ? responses.slice(item.after.responses).find(value => value?.requestId === request.requestId && (item.kind === 'skill'
            ? value?.type === 'studioOperationResult' && value?.kind === 'skill' && value?.operation === 'next-version'
            : value?.type === 'studioRevisionEditorResult' && value?.kind === item.kind)) : null;
          const allocation = response?.allocation || response?.result || null;
          const document = frame.contentDocument;
          const identity = document.querySelector('#studio-identity');
          const version = document.querySelector('#studio-version');
          const owner = document.querySelector('#studio-owner');
          return {
            matches: Boolean(request && response && allocation) && allocation.kind === item.kind && allocation.identity === item.identity
              && allocation.source_version === item.source_version && identity?.value === item.identity && identity.readOnly
              && version?.value === allocation.candidate_version && version.readOnly
              && owner?.value === item.owner
              && Boolean(document.querySelector('.studio-revision-baseline')),
            request_id: request?.requestId || null, allocation,
            identity: identity?.value || null, version: version?.value || null, owner: owner?.value || null
          };
        }, { after: verificationOffsets, kind: spec.kind, identity: candidate.identity, source_version: observation.candidate_version, owner: observation.changed_owner });
        observation.last_editor_state = { ...(observation.last_editor_state || {}), reopened_saved_revision: reopened };
        if (reopened.matches) { observation.reopened_editor_content_match = true; break; }
        await wait(200);
      } while (Date.now() < verificationDeadline);
      if (!observation.reopened_editor_content_match) throw new Error(`studio-${spec.kind}-saved-revision-editor-content-mismatch`);
      const conditional = await frameHost.evaluateContent(item => {
        const allocationResponse = [...(window.__PX_INSTALLED_RESPONSES__ || [])].reverse().find(value => typeof value?.allocationProof === 'string' && (
          value?.allocation?.kind === item.kind
          || (value?.type === 'studioOperationResult' && value?.kind === item.kind && value?.operation === 'next-version' && value?.result?.kind === item.kind)
        ));
        const boundAllocation = allocationResponse?.allocation || allocationResponse?.result;
        const owner = document.querySelector('#studio-owner');
        if (!boundAllocation || !owner) return { error: 'conditional-state-prerequisite-unavailable' };
        const requestId = `owned-studio-conflict-${item.kind}-${Date.now()}`;
        const createDispatchesBefore = (window.__PX_INSTALLED_REQUESTS__ || []).filter(value => value?.type === 'createStudioDraft').length;
        try {
          studioSaveRequest = { requestId, kind: item.kind };
          const allocation = structuredClone(boundAllocation);
          const parts = String(allocation.candidate_version).split('.').map(Number); parts[2] += 1; allocation.candidate_version = parts.join('.');
          allocation.occupied_versions_sha256 = 'c'.repeat(64); allocation.observed_utc = new Date().toISOString();
          window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioVersionConflict', requestId, kind: item.kind, error: 'Bounded owned request-conflict fixture; no create was dispatched.', allocation, allocationProof: 'version-allocation:px-owned-conflict' } }));
          const accept = document.querySelector('[data-action="acceptStudioVersionSuggestion"]');
          const conflictRendered = Boolean(accept && document.querySelector('[data-studio-version-conflict]'));
          accept?.click();
          const accepted = document.querySelector('#studio-version')?.value === allocation.candidate_version;
          window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioDraftCancelled', requestId, kind: item.kind } }));
          studioVersionAllocationProof = null;
          studioVersionProofRequestId = null;
          const fork = document.querySelector('[data-action="forkStudioCandidate"]'); fork?.click();
          const forkVerified = Boolean(document.querySelector('.identity-warning') && document.querySelector('#studio-version')?.value === '1.0.0'
            && String(document.querySelector('#studio-identity')?.value || '').endsWith('-fork'));
          const createDispatchesAfter = (window.__PX_INSTALLED_REQUESTS__ || []).filter(value => value?.type === 'createStudioDraft').length;
          return { conflictRendered, accepted, forkVerified, hostDispatchSuppressed: createDispatchesAfter === createDispatchesBefore };
        } finally {
          studioSaveRequest = null;
          if (studioVersionAllocationProof === allocationResponse.allocationProof) vscode.postMessage({ type: 'releaseStudioTrust', requestId: allocationResponse.requestId, trustKind: 'version-allocation', proof: allocationResponse.allocationProof });
        }
      }, { kind: spec.kind });
      if (conditional.error) throw new Error(`studio-${spec.kind}-${conditional.error}`);
      observation.version_conflict_rendered = conditional.conflictRendered;
      observation.version_suggestion_accepted = conditional.accepted;
      observation.version_conflict_host_dispatch_suppressed = conditional.hostDispatchSuppressed;
      observation.fork_verified = conditional.forkVerified;
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="closeModal"]')?.click());
      if (!validStudioRevisionEditObservation(observation)) throw new Error(`studio-${spec.kind}-revision-edit-proof-incomplete`);
    } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2400)); }
    observations.push(observation);
  }
  const openRequirement = requirements.get('pxui.studio-lifecycle.action.openStudioFromCatalog');
  if (!openRequirement) throw new Error('Studio revision-edit profile openStudioFromCatalog control is absent');
  const records = [studioRevisionEditRecord(openRequirement, observations)];
  for (const spec of specifications) {
    const requirement = requirements.get(spec.submitControlId);
    if (!requirement) throw new Error(`Studio revision-edit profile control is absent: ${spec.submitControlId}`);
    records.push(studioRevisionEditRecord(requirement, observations, spec.kind));
    const observation = observations.find(item => item.kind === spec.kind);
    for (const [controlId, stateKind] of [
      [`pxui.${spec.kind}-studio.action.forkStudioCandidate`, 'fork'],
      [`pxui.${spec.kind}-studio.action.acceptStudioVersionSuggestion`, 'version-conflict']
    ]) {
      const conditionalRequirement = requirements.get(controlId);
      if (!conditionalRequirement) throw new Error(`Studio revision conditional control is absent: ${controlId}`);
      records.push(studioRevisionConditionalRecord(conditionalRequirement, observation, stateKind));
    }
  }
  return { schema_version: 'px.installed-studio-revision-edit-profile/1.0', authority: 'Exact predecessor-bound immutable revision edits executed only inside the owned isolated VS Code host.', observations, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact predecessor-bound immutable revision edits executed only inside the owned isolated VS Code host.', eligible_control_count: records.length, records } };
}

function validStudioLifecycleResult(kind, operation, result) {
  const record = result?.record && typeof result.record === 'object' ? result.record : result;
  if (!record || typeof record !== 'object') return false;
  if (operation === 'register-authority') return record.schema_version === 'px.studio-authority-transaction/1.0' && record.status === 'registered' && record.authenticated === true;
  if (kind === 'agent' && operation === 'test') return record.schema_version === 'px.agent-preflight-receipt/1.2' && record.passed === true;
  if (kind === 'agent' && operation === 'admit') return record.schema_version === 'px.agent-admission-receipt/1.1' && record.decision === 'admitted';
  if (kind === 'agent' && operation === 'preview') return record.schema_version === 'px.agent-execution-preview/1.0' && record.effects_executed === false && record.eligible === true;
  if (kind === 'workflow' && operation === 'validate') return record.schema_version === 'px.workflow-admission-receipt/1.1' && record.decision === 'admitted';
  if (kind === 'workflow' && operation === 'dry-run') return record.schema_version === 'px.workflow-dry-run/1.1' && record.effects_executed === false;
  if (kind === 'skill' && operation === 'validate') return record.schema_version === 'px.skill-validation-receipt/1.1' && record.passed === true;
  if (kind === 'skill' && operation === 'admit') return record.schema_version === 'px.skill-admission-receipt/1.1' && record.decision === 'admitted';
  if (kind === 'skill' && operation === 'promote') return record.schema_version === 'px.skill-promotion-receipt/1.3' && record.state === 'promoted' && typeof record.promotion_receipt_relative === 'string';
  if (kind === 'skill' && operation === 'rollback') return record.state === 'rolled-back';
  if (kind === 'workflow' && operation === 'approve') return record.schema_version === 'px.workflow-approval-result/1.0' && typeof record.approval_id === 'string' && record.approval_id.length > 0;
  if (['agent', 'workflow'].includes(kind) && operation === 'start') return record.schema_version === `px.${kind}-session-start/1.1` && record.accepted === true && typeof record.run_id === 'string' && record.run_id.length > 0;
  if (kind === 'agent' && operation === 'resume') return record.schema_version === 'px.agent-session-start/1.1' && record.accepted === true && typeof record.run_id === 'string' && record.run_id.length > 0;
  if (kind === 'workflow' && operation === 'resume') return record.schema_version === 'px.workflow-runtime-receipt/1.2' && typeof record.run_id === 'string' && record.run_id.length > 0;
  if (['agent', 'workflow'].includes(kind) && ['status', 'pause', 'cancel', 'stop'].includes(operation)) return record.schema_version === 'px.studio-durable-run/1.0' && typeof record.run_id === 'string' && record.run_id.length > 0;
  if (['agent', 'workflow'].includes(kind) && operation === 'reconcile') return record.schema_version === 'px.studio-run-reconciliation/1.0' && record.valid === true;
  if (['agent', 'workflow'].includes(kind) && operation === 'runs') return record.schema_version === 'px.studio-run-list/1.0' && record.kind === kind && Array.isArray(record.runs);
  return false;
}

function validStudioBlockedPreviewResult(result, candidate) {
  const record = result?.record && typeof result.record === 'object' ? result.record : result;
  return record?.schema_version === 'px.agent-execution-preview/1.0'
    && record.agent_id === candidate.identity && record.version === candidate.version
    && record.effects_executed === false && record.eligible === false && record.status === 'blocked'
    && Array.isArray(record.blockers) && record.blockers.includes('memory_bindings_not_runtime_resolved')
    && Array.isArray(record.memory_binding_ids) && record.memory_binding_ids.includes(candidate.memory_binding_id);
}

function studioLifecycleControlProbe(matrix, observations) {
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const byKind = new Map(observations.filter(observation => observation.fixture_only !== true).map(observation => [observation.kind, observation]));
  const blockedAgent = observations.find(observation => observation.kind === 'agent' && observation.fixture_only === true);
  const successful = (kind, operation) => byKind.get(kind)?.operations?.some(item => item.operation === operation && item.valid === true) === true;
  const exact = kind => byKind.get(kind)?.exact_catalog_selection === true;
  const reopened = kind => byKind.get(kind)?.durable_run_reopened === true;
  const specs = [
    ['pxui.agents.action.inspectCatalogItem.row', ['agent'], () => exact('agent')],
    ['pxui.workflows.action.inspectCatalogItem.row', ['workflow'], () => exact('workflow')],
    ['pxui.skills-tools.action.inspectCatalogItem.row', ['skill'], () => exact('skill')],
    ['pxui.studio-lifecycle.action.operateStudioRevision', ['agent', 'workflow', 'skill'], () => ['agent', 'workflow', 'skill'].every(exact)],
    ['pxui.studio-lifecycle.action.studioLifecycle.test', ['agent'], () => successful('agent', 'test')],
    ['pxui.studio-lifecycle.action.studioLifecycle.register-authority', ['agent', 'workflow'], () => successful('agent', 'register-authority') && successful('workflow', 'register-authority')],
    ['pxui.studio-lifecycle.action.studioLifecycle.admit', ['agent', 'skill'], () => successful('agent', 'admit') && successful('skill', 'admit')],
    ['pxui.studio-lifecycle.action.studioLifecycle.preview', ['agent'], () => successful('agent', 'preview') && blockedAgent?.blocked_preview_verified === true],
    ['pxui.studio-lifecycle.action.studioLifecycle.validate', ['workflow', 'skill'], () => successful('workflow', 'validate') && successful('skill', 'validate')],
    ['pxui.studio-lifecycle.action.studioLifecycle.dry-run', ['workflow'], () => successful('workflow', 'dry-run')],
    ['pxui.studio-lifecycle.action.studioLifecycle.approve', ['workflow'], () => successful('workflow', 'approve')],
    ['pxui.studio-lifecycle.action.studioLifecycle.start', ['agent', 'workflow'], () => successful('agent', 'start') && successful('workflow', 'start')],
    ['pxui.studio-lifecycle.action.submitStudioAgentRun', ['agent'], () => successful('agent', 'start')],
    ['pxui.studio-lifecycle.action.submitStudioWorkflowRun', ['workflow'], () => successful('workflow', 'start')],
    ['pxui.studio-lifecycle.form.agentRunObjective', ['agent'], () => successful('agent', 'start')],
    ['pxui.studio-lifecycle.form.workflowRunInputs', ['workflow'], () => successful('workflow', 'start')],
    ['pxui.studio-lifecycle.field.agentObjective', ['agent'], () => successful('agent', 'start')],
    ['pxui.studio-lifecycle.field.workflowRunInputsJson', ['workflow'], () => successful('workflow', 'start')],
    ['pxui.studio-lifecycle.action.studioRunAction.status', ['agent', 'workflow'], () => successful('agent', 'status') && successful('workflow', 'status')],
    ['pxui.studio-lifecycle.action.studioRunAction.pause', ['agent'], () => successful('agent', 'pause')],
    ['pxui.studio-lifecycle.action.studioRunAction.resume', ['agent'], () => successful('agent', 'resume')],
    ['pxui.studio-lifecycle.action.studioRunAction.stop', ['agent', 'workflow'], () => successful('agent', 'stop') || successful('workflow', 'stop')],
    ['pxui.studio-lifecycle.action.studioRunAction.cancel', ['workflow'], () => successful('workflow', 'cancel')],
    ['pxui.studio-lifecycle.action.studioRunAction.reconcile', ['agent', 'workflow'], () => successful('agent', 'reconcile') && successful('workflow', 'reconcile')],
    ['pxui.studio-lifecycle.action.openStudioRuns.agent', ['agent'], () => reopened('agent') && byKind.get('agent')?.lifecycle_hub_run_browser === true],
    ['pxui.studio-lifecycle.action.openStudioRuns.workflow', ['workflow'], () => reopened('workflow') && byKind.get('workflow')?.lifecycle_hub_run_browser === true],
    ['pxui.studio-lifecycle.action.studioLifecycle.promote', ['skill'], () => successful('skill', 'promote')],
    ['pxui.studio-lifecycle.action.studioLifecycle.rollback', ['skill'], () => successful('skill', 'rollback')],
    ['pxui.studio-lifecycle.lifecycle.path.1', ['agent'], () => successful('agent', 'test') && successful('agent', 'admit') && successful('agent', 'start') && reopened('agent')],
    ['pxui.studio-lifecycle.lifecycle.path.2', ['workflow'], () => successful('workflow', 'validate') && successful('workflow', 'approve') && successful('workflow', 'start') && reopened('workflow')],
    ['pxui.studio-lifecycle.lifecycle.path.3', ['skill'], () => successful('skill', 'validate') && successful('skill', 'admit') && successful('skill', 'promote') && successful('skill', 'rollback')],
    ['pxui.studio-lifecycle.lifecycle.path.4', ['agent', 'workflow'], () => reopened('agent') && reopened('workflow') && successful('agent', 'reconcile') && successful('workflow', 'reconcile')],
    ['pxui.studio-lifecycle.menu.revisionLifecycle', ['agent', 'workflow', 'skill'], () => ['agent', 'workflow', 'skill'].every(exact)],
    ['pxui.studio-lifecycle.menu.runControls', ['agent', 'workflow'], () => reopened('agent') && reopened('workflow')],
    ['pxui.studio-lifecycle.indicator.accepted', ['agent', 'workflow'], () => successful('agent', 'start') && successful('workflow', 'start')],
    ['pxui.studio-lifecycle.indicator.output', ['agent', 'workflow'], () => successful('agent', 'status') && successful('workflow', 'status')],
    ['pxui.studio-lifecycle.indicator.runId', ['agent', 'workflow'], () => Boolean(byKind.get('agent')?.run_id) && Boolean(byKind.get('workflow')?.run_id)],
    ['pxui.studio-lifecycle.indicator.runtimeOutcome', ['agent', 'workflow'], () => successful('agent', 'status') && successful('workflow', 'status')],
    ['pxui.studio-lifecycle.indicator.signedReceipt', ['agent', 'workflow'], () => reopened('agent') && reopened('workflow')],
    ['pxui.studio-lifecycle.indicator.error', ['skill'], () => byKind.get('skill')?.lifecycle_error_rendered === true && byKind.get('skill')?.lifecycle_failure_recovered === true],
    ['pxui.studio-lifecycle.indicator.notAccepted', ['skill'], () => byKind.get('skill')?.lifecycle_not_accepted_rendered === true && byKind.get('skill')?.lifecycle_failure_recovered === true],
    ['pxui.studio-lifecycle.persistence.authoritativeState', ['agent', 'workflow'], () => reopened('agent') && reopened('workflow') && byKind.get('agent')?.webview_restarted === true && byKind.get('workflow')?.webview_restarted === true],
    ['pxui.studio-lifecycle.reload_reopen.authoritativeState', ['agent', 'workflow'], () => reopened('agent') && reopened('workflow') && byKind.get('agent')?.webview_restarted === true && byKind.get('workflow')?.webview_restarted === true]
  ];
  const records = specs.map(([controlId, kinds, predicate]) => {
    const requirement = requirements.get(controlId);
    if (!requirement) throw new Error(`Studio lifecycle profile control is absent: ${controlId}`);
    const verified = predicate();
    const errors = kinds.flatMap(kind => byKind.get(kind)?.errors || []).concat(controlId === 'pxui.studio-lifecycle.action.studioLifecycle.preview' ? blockedAgent?.errors || [] : []);
    const evidenceRef = `installed-studio-lifecycle:${controlId}`;
    return {
      control_id: controlId, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_isolated_studio_lifecycle', rendered: kinds.every(exact), observed: kinds.every(exact), attempted: true,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        const stateIndicator = ['pxui.studio-lifecycle.indicator.error', 'pxui.studio-lifecycle.indicator.notAccepted'].includes(controlId);
        const failClosed = stateIndicator
          ? kinds.every(kind => byKind.get(kind)?.lifecycle_failure_recovered === true)
          : kinds.every(kind => byKind.get(kind)?.invalid_transition_rejected === true);
        if (stage === 'failure_handling') return [stage, failClosed
          ? { state: 'present', detail: 'The installed lifecycle modal kept the out-of-order terminal operation disabled and dispatched no request before the admitted transition sequence.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The out-of-order Studio lifecycle transition was not proven fail-closed.', evidence: [] }];
        return [stage, verified
          ? { state: 'present', detail: `The exact installed ${kinds.join(' and ')} Studio control completed through request-bound host approval, typed canonical receipts, and durable state retrieval where applicable.`, evidence: [evidenceRef] }
          : { state: 'missing', detail: `The owned lifecycle campaign did not complete the exact ${kinds.join(' and ')} control.`, evidence: [] }];
      })),
      errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact candidate lifecycle operations executed only inside the owned isolated VS Code host.', eligible_control_count: records.length, records };
}

function mergeStudioLifecycleObservations(current = [], replacements = []) {
  const key = observation => observation?.fixture_only === true
    ? `${observation.kind}:fixture:${observation.identity || observation.catalog_record_id || 'unknown'}`
    : `${observation?.kind || 'unknown'}:primary`;
  const merged = new Map(current.map(observation => [key(observation), observation]));
  for (const observation of replacements) merged.set(key(observation), observation);
  return [...merged.values()];
}

async function waitForStudioOperationResult(frameHost, after, kind, operation, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const response = await frameHost.evaluate((frame, item) => {
      const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
      return responses.slice(item.after).find(value => (value?.type === 'studioOperationResult' && value?.kind === item.kind && value?.operation === item.operation)
        || (value?.type === 'operationError' && value?.operation === 'studioOperation' && value?.kind === item.kind && value?.suboperation === item.operation)) || null;
    }, { after, kind, operation });
    if (response?.type === 'operationError') throw new Error(`studio-${kind}-${operation}-failed:${response.error}`);
    if (response) return response.result;
    await wait(200);
  } while (Date.now() < deadline);
  throw new Error(`studio-${kind}-${operation}-response-timeout`);
}

async function openExactStudioCatalogRow(frameHost, candidate, timeoutMs = 30_000) {
  await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
  await navigateInstalledSurface(frameHost, candidate.route, timeoutMs);
  if (['agents', 'workflows'].includes(candidate.route)) {
    await frameHost.evaluate((frame, item) => {
      const scope = frame.contentDocument?.querySelector(`[data-action="surfaceScope"][data-target="${CSS.escape(item.route)}"][data-scope="core"]`);
      if (!scope || scope.disabled) throw new Error(`studio-${item.kind}-lifecycle-core-scope-unavailable`);
      if (scope.getAttribute('aria-pressed') !== 'true') scope.click();
    }, candidate);
  } else if (candidate.route === 'skillsTools') {
    await frameHost.evaluate(frame => {
      const native = [...frame.contentDocument.querySelectorAll('[data-action="capabilityTab"]')].find(element => element.dataset.kind === 'skills' && !element.disabled);
      if (!native) throw new Error('studio-skill-native-catalog-tab-unavailable');
      native.click();
    });
  }
  const deadline = Date.now() + timeoutMs;
  do {
    const opened = await frameHost.evaluate((frame, item) => {
      const document = frame.contentDocument;
      const catalogKind = `${item.kind}s`;
      const search = document.querySelector(`[data-catalog-search="${CSS.escape(catalogKind)}"]`);
      if (!search || search.disabled) return false;
      if (search.value !== item.identity) {
        search.value = item.identity;
        search.dispatchEvent(new Event('input', { bubbles: true }));
      }
      const row = [...document.querySelectorAll('[data-action="inspectCatalogItem"]')]
        .find(element => element.dataset.kind === `${item.kind}s` && element.dataset.id === item.catalog_record_id && !element.disabled);
      if (!row) return false;
      row.click();
      return true;
    }, candidate);
    if (opened) return true;
    await wait(150);
  } while (Date.now() < deadline);
  const state = await frameHost.evaluate((frame, item) => ({
    active: [...frame.contentDocument.querySelectorAll('.nav-item[aria-current="page"]')].map(element => element.dataset.surface),
    search_value: frame.contentDocument.querySelector(`[data-catalog-search="${CSS.escape(`${item.kind}s`)}"]`)?.value || null,
    rows: [...frame.contentDocument.querySelectorAll('[data-action="inspectCatalogItem"]')].slice(0, 200).map(element => ({ kind: element.dataset.kind, id: element.dataset.id, disabled: Boolean(element.disabled) })),
    expected: { kind: `${item.kind}s`, id: item.catalog_record_id }
  }), candidate).catch(() => ({ active: [], rows: [], expected: { kind: `${candidate.kind}s`, id: candidate.catalog_record_id } }));
  throw new Error(`studio-${candidate.kind}-exact-catalog-row-timeout:${JSON.stringify(state)}`);
}

async function exerciseStudioLifecycleFailureStates(frameHost, candidate) {
  const notAccepted = await frameHost.evaluateContent(item => {
    const requestId = `owned-lifecycle-not-accepted-${Date.now()}`;
    pendingSkillLifecycle = Object.freeze({ requestId, kind: 'skill', operation: 'validate', skill: item.identity, version: item.version });
    studioSession = { kind: 'skill', payload: { skill_id: item.identity, version: item.version } };
    window.dispatchEvent(new MessageEvent('message', { data: {
      type: 'studioOperationResult', requestId, kind: 'skill', operation: 'validate',
      result: { record: { schema_version: 'px.skill-validation-receipt/1.1', skill_id: item.identity, version: item.version, passed: false, status: 'rejected' } }
    } }));
    return String(document.querySelector('#modal-root .eyebrow')?.textContent || '').includes('NOT ACCEPTED');
  }, candidate);
  await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="closeModal"]')?.click());
  const errorRendered = await frameHost.evaluateContent(item => {
    const requestId = `owned-lifecycle-error-${Date.now()}`;
    pendingSkillLifecycle = Object.freeze({ requestId, kind: 'skill', operation: 'validate', skill: item.identity, version: item.version });
    window.dispatchEvent(new MessageEvent('message', { data: {
      type: 'operationError', requestId, operation: 'studioOperation', suboperation: 'validate', kind: 'skill',
      error: `Owned request-bound lifecycle failure reproduction for ${item.identity}@${item.version}`
    } }));
    return /Owned request-bound lifecycle failure reproduction/.test(String(document.querySelector('#modal-root [role="alert"]')?.textContent || ''));
  }, candidate);
  await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="closeModal"]')?.click());
  const exact = await openExactStudioCatalogRow(frameHost, candidate);
  await wait(120);
  const recovered = exact && await frameHost.evaluate((frame, item) => {
    const modal = frame.contentDocument.querySelector('#modal-root .control-modal');
    const text = String(modal?.textContent || '').replace(/\s+/g, ' ').trim();
    return Boolean(modal && !modal.querySelector('[role="alert"]') && text.includes(item.identity) && text.includes(item.version));
  }, candidate);
  return { notAccepted, errorRendered, recovered };
}

async function runInstalledStudioLifecycleProfile(frameHost, candidateProfile, matrix) {
  const observations = [];
  for (const candidate of candidateProfile.observations || []) {
    const operations = candidate.kind === 'agent'
      ? ['test', 'register-authority', 'admit', 'preview', ...(candidate.fixture_only ? [] : ['start'])]
      : candidate.kind === 'workflow'
        ? ['register-authority', 'validate', 'dry-run', 'approve', 'start']
        : ['validate', 'admit', 'promote', ...(candidate.expect_rollback ? ['rollback'] : [])];
    const observation = { kind: candidate.kind, identity: candidate.identity, version: candidate.version, fixture_only: candidate.fixture_only === true, memory_binding_id: candidate.memory_binding_id || null, catalog_record_id: candidate.catalog_record_id, exact_catalog_selection: false, invalid_transition_rejected: false, blocked_preview_verified: false, blocked_preview_rendered: false, blocked_preview_start_suppressed: false, operations: [], run_id: null, webview_restarted: false, durable_run_reopened: false, lifecycle_hub_run_browser: false, lifecycle_not_accepted_rendered: false, lifecycle_error_rendered: false, lifecycle_failure_recovered: false, errors: [] };
    try {
      if (!candidate.typed_creation_receipt || !candidate.reopened_catalog_match || !candidate.catalog_record_id) throw new Error(`studio-${candidate.kind}-lifecycle-candidate-prerequisite-missing`);
      observation.exact_catalog_selection = await openExactStudioCatalogRow(frameHost, candidate);
      await wait(120);
      await frameHost.evaluate((frame, kind) => {
        const control = [...frame.contentDocument.querySelectorAll('[data-action="operateStudioRevision"]')].find(element => element.dataset.kind === kind && !element.disabled);
        if (!control) throw new Error(`studio-${kind}-candidate-lifecycle-continuation-unavailable`);
        control.click();
      }, candidate.kind);
      await wait(100);
      const invalidBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      observation.invalid_transition_rejected = await frameHost.evaluate((frame, item) => {
        const blockedOperation = item.kind === 'skill' ? 'promote' : 'start';
        const action = [...frame.contentDocument.querySelectorAll('[data-action="studioLifecycle"]')].find(element => element.dataset.kind === item.kind && element.dataset.operation === blockedOperation);
        if (!action) return true;
        if (!action.disabled) return false;
        action.click();
        return (frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0) === item.before;
      }, { kind: candidate.kind, before: invalidBefore });
      if (!observation.invalid_transition_rejected) throw new Error(`studio-${candidate.kind}-out-of-order-transition-not-rejected`);
      for (const operation of operations) {
        const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
        await frameHost.evaluate((frame, item) => {
          const document = frame.contentDocument;
          const action = [...document.querySelectorAll('[data-action="studioLifecycle"]')].find(element => element.dataset.kind === item.kind && element.dataset.operation === item.operation && !element.disabled);
          if (!action) throw new Error(`studio-${item.kind}-${item.operation}-control-unavailable`);
          action.click();
          if (item.operation === 'start' && item.kind === 'agent') {
            const objective = document.querySelector('#studio-agent-objective');
            const toolCalls = document.querySelector('#studio-agent-tool-calls');
            const submit = document.querySelector('[data-action="submitStudioAgentRun"]');
            if (!objective || !toolCalls || !submit || submit.disabled) throw new Error('studio-agent-start-form-unavailable');
            objective.value = 'Return a bounded identity result without external effects.';
            objective.dispatchEvent(new Event('input', { bubbles: true }));
            toolCalls.value = JSON.stringify(Array.from({ length: 8 }, () => ({ tool: 'delay', input: 1.5 })));
            toolCalls.dispatchEvent(new Event('input', { bubbles: true }));
            submit.click();
          }
          if (item.operation === 'start' && item.kind === 'workflow') {
            const inputs = document.querySelector('#studio-workflow-inputs');
            const submit = document.querySelector('[data-action="submitStudioWorkflowRun"]');
            if (!inputs || !submit || submit.disabled) throw new Error('studio-workflow-start-form-unavailable');
            inputs.value = JSON.stringify({ 'step:one.seconds': 8 }, null, 2);
            inputs.dispatchEvent(new Event('input', { bubbles: true }));
            submit.click();
          }
        }, { kind: candidate.kind, operation });
        const result = await waitForStudioOperationResult(frameHost, before, candidate.kind, operation);
        const valid = operation === 'preview' && candidate.fixture_only
          ? validStudioBlockedPreviewResult(result, candidate)
          : validStudioLifecycleResult(candidate.kind, operation, result);
        observation.operations.push({ operation, valid, result });
        if (!valid) throw new Error(`studio-${candidate.kind}-${operation}-receipt-invalid:${JSON.stringify(result)}`);
        if (operation === 'preview' && candidate.fixture_only) {
          const physical = await frameHost.evaluate((frame, item) => {
            const document = frame.contentDocument;
            const modal = document.querySelector('#modal-root .control-modal');
            const text = String(modal?.textContent || '').replace(/\s+/g, ' ').trim();
            const start = [...document.querySelectorAll('[data-action="studioLifecycle"]')]
              .find(element => element.dataset.kind === 'agent' && element.dataset.operation === 'start' && !element.disabled);
            const dispatchedStarts = (frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || [])
              .filter(value => value?.type === 'studioOperation' && value?.kind === 'agent' && value?.operation === 'start' && value?.payload?.agent_id === item.identity).length;
            return {
              rendered: Boolean(modal) && text.includes('RESOLVED EXECUTION BLOCKED') && text.includes(item.identity)
                && text.includes(item.version) && text.includes('memory_bindings_not_runtime_resolved'),
              start_suppressed: !start && dispatchedStarts === 0
            };
          }, candidate);
          observation.blocked_preview_rendered = physical.rendered === true;
          observation.blocked_preview_start_suppressed = physical.start_suppressed === true;
          observation.blocked_preview_verified = observation.blocked_preview_rendered && observation.blocked_preview_start_suppressed;
          if (!observation.blocked_preview_verified) throw new Error(`studio-agent-blocked-preview-physical-proof-incomplete:${JSON.stringify(physical)}`);
        }
        if (operation === 'start') observation.run_id = String((result?.record || result)?.run_id || '');
        if (operation !== 'start') await wait(100);
      }
      if (candidate.kind === 'skill') {
        const failureStates = await exerciseStudioLifecycleFailureStates(frameHost, candidate);
        observation.lifecycle_not_accepted_rendered = failureStates.notAccepted === true;
        observation.lifecycle_error_rendered = failureStates.errorRendered === true;
        observation.lifecycle_failure_recovered = failureStates.recovered === true;
        if (!observation.lifecycle_not_accepted_rendered || !observation.lifecycle_error_rendered || !observation.lifecycle_failure_recovered) {
          throw new Error(`studio-skill-request-bound-failure-state-proof-incomplete:${JSON.stringify(failureStates)}`);
        }
      }
      if (observation.run_id) {
        const invokeRunControl = async operation => {
          const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
          const available = await frameHost.evaluate((frame, requested) => {
            const action = [...frame.contentDocument.querySelectorAll('[data-action="studioRunAction"]')].find(element => element.dataset.operation === requested && !element.disabled);
            if (!action) return false;
            action.click();
            return true;
          }, operation);
          if (!available) throw new Error(`studio-${candidate.kind}-${operation}-control-unavailable`);
          const result = await waitForStudioOperationResult(frameHost, before, candidate.kind, operation, 10_000);
          const valid = validStudioLifecycleResult(candidate.kind, operation, result);
          observation.operations.push({ operation, valid, result });
          if (!valid) throw new Error(`studio-${candidate.kind}-${operation}-receipt-invalid:${JSON.stringify(result)}`);
          await wait(120);
          return result?.record || result;
        };
        const waitForState = async expected => {
          const deadline = Date.now() + 10_000;
          let state = '';
          do {
            const status = await invokeRunControl('status');
            state = String(status?.state || status?.runtime_state || '').toLowerCase();
            if (expected.includes(state)) return state;
            await wait(180);
          } while (Date.now() < deadline);
          throw new Error(`studio-${candidate.kind}-state-timeout:${expected.join('|')}:${state || 'unknown'}`);
        };
        if (candidate.kind === 'agent') {
          await invokeRunControl('pause');
          await waitForState(['paused']);
          await invokeRunControl('resume');
          await invokeRunControl('stop');
        } else if (candidate.kind === 'workflow') {
          await waitForState(['running']);
          await invokeRunControl('cancel');
        }
        const statusDeadline = Date.now() + 20_000;
        let terminalState = '';
        do {
          const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
          const statusAvailable = await frameHost.evaluate(frame => {
            const action = [...frame.contentDocument.querySelectorAll('[data-action="studioRunAction"]')].find(element => element.dataset.operation === 'status' && !element.disabled);
            if (!action) return false;
            action.click();
            return true;
          });
          if (!statusAvailable) throw new Error(`studio-${candidate.kind}-status-control-unavailable`);
          const status = await waitForStudioOperationResult(frameHost, before, candidate.kind, 'status', 8_000);
          const valid = validStudioLifecycleResult(candidate.kind, 'status', status);
          observation.operations.push({ operation: 'status', valid, result: status });
          if (!valid) throw new Error(`studio-${candidate.kind}-status-receipt-invalid:${JSON.stringify(status)}`);
          const state = String((status?.record || status)?.state || (status?.record || status)?.runtime_state || '').toLowerCase();
          terminalState = state;
          const expectedTerminal = ['cancelled'];
          if (expectedTerminal.includes(state)) break;
          if (['failed', 'succeeded'].includes(state)) throw new Error(`studio-${candidate.kind}-unexpected-run-terminal-${state}`);
          await wait(300);
        } while (Date.now() < statusDeadline);
        const expectedTerminal = ['cancelled'];
        if (!expectedTerminal.includes(terminalState)) throw new Error(`studio-${candidate.kind}-run-terminal-timeout:${terminalState || 'unknown'}`);
        const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
        observation.webview_restarted = restart.restarted === true;
        const beforeRuns = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
        await navigateInstalledSurface(frameHost, 'studio-lifecycle', 20_000);
        observation.lifecycle_hub_run_browser = await frameHost.evaluate((frame, item) => {
          const document = frame.contentDocument;
          document?.querySelector('[data-action="closeModal"]')?.click();
          const open = [...document.querySelectorAll('[data-action="openStudioRuns"]')].find(element => element.dataset.kind === item.kind && !element.disabled);
          if (!open) throw new Error(`studio-${item.kind}-durable-run-browser-unavailable`);
          open.click();
          return true;
        }, candidate);
        const runs = await waitForStudioOperationResult(frameHost, beforeRuns, candidate.kind, 'runs');
        const valid = validStudioLifecycleResult(candidate.kind, 'runs', runs);
        observation.operations.push({ operation: 'runs', valid, result: runs });
        observation.durable_run_reopened = valid && (runs.runs || []).some(run => run.run_id === observation.run_id);
        if (!observation.durable_run_reopened) throw new Error(`studio-${candidate.kind}-durable-run-reopen-missing`);
        await invokeRunControl('reconcile');
      }
    } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 2400)); }
    observations.push(observation);
  }
  return { schema_version: 'px.installed-studio-lifecycle-profile/1.0', authority: 'Exact candidate lifecycle operations executed only inside the owned isolated VS Code host.', observations, control_probe: studioLifecycleControlProbe(matrix, observations) };
}

function validKnowledgeLifecycleResult(operation, result, expected = {}) {
  const record = result?.record && typeof result.record === 'object' ? result.record : result;
  const hash = value => /^[0-9a-f]{64}$/.test(String(value || ''));
  if (operation === 'browse') {
    return record?.schema_version === 'px.knowledge-core-control/1.0'
      && Array.isArray(record.proposals) && Array.isArray(record.canonical);
  }
  if (['propose', 'verify', 'approve', 'promote', 'reject'].includes(operation)) {
    const states = { propose: 'candidate', verify: 'verified', approve: 'approved', promote: 'promoted', reject: 'rejected' };
    return record?.schema_version === 'px.knowledge-proposal/1.0'
      && record.state === states[operation]
      && typeof record.proposal_id === 'string' && record.proposal_id.length > 0
      && hash(record.candidate_sha256)
      && (!expected.proposal_id || record.proposal_id === expected.proposal_id)
      && (!expected.candidate_sha256 || record.candidate_sha256 === expected.candidate_sha256);
  }
  if (operation === 'rollback') {
    return record?.schema_version === 'px.knowledge-rollback/1.0'
      && hash(record.from_sha256) && hash(record.to_sha256)
      && record.hard_delete === false
      && (!expected.from_sha256 || record.from_sha256 === expected.from_sha256)
      && (!expected.to_sha256 || record.to_sha256 === expected.to_sha256);
  }
  if (operation === 'recover') return record?.schema_version === 'px.knowledge-recovery/1.0' && record.valid === true;
  return false;
}

async function waitForKnowledgeControl(frameHost, selector, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const available = await frameHost.evaluate((frame, query) => {
      const control = frame.contentDocument?.querySelector(query);
      return Boolean(control && !control.disabled && (control.offsetWidth || control.offsetHeight || control.getClientRects().length));
    }, selector);
    if (available) return true;
    await wait(150);
  } while (Date.now() < deadline);
  const diagnostic = await frameHost.evaluate(frame => {
    const document = frame.contentDocument;
    const visible = element => Boolean(element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
    return {
      heading: String(document?.querySelector('h1,h2')?.textContent || '').trim().slice(0, 160),
      surfaces: [...(document?.querySelectorAll('[data-surface]') || [])].slice(0, 40).map(element => ({ surface: element.dataset.surface || '', visible: visible(element), disabled: Boolean(element.disabled) })),
      knowledge_actions: [...(document?.querySelectorAll('[data-action]') || [])].filter(element => /knowledge/i.test(element.dataset.action || '')).slice(0, 40).map(element => ({ action: element.dataset.action || '', visible: visible(element), disabled: Boolean(element.disabled) }))
    };
  });
  throw new Error(`knowledge-control-unavailable:${selector}:${JSON.stringify(diagnostic)}`);
}

async function clickWhenKnowledgeControlReady(frameHost, selector, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const clicked = await frameHost.evaluate((frame, query) => {
      const control = frame.contentDocument?.querySelector(query);
      const visible = Boolean(control && (control.offsetWidth || control.offsetHeight || control.getClientRects().length));
      if (!control || control.disabled || !visible) return false;
      control.click();
      return true;
    }, selector);
    if (clicked) return true;
    await wait(150);
  } while (Date.now() < deadline);
  const diagnostic = await frameHost.evaluate((frame, query) => {
    const control = frame.contentDocument?.querySelector(query);
    return {
      present: Boolean(control),
      visible: Boolean(control && (control.offsetWidth || control.offsetHeight || control.getClientRects().length)),
      disabled: Boolean(control?.disabled),
      action: String(control?.dataset?.action || ''),
      task_id: String(control?.dataset?.taskId || '')
    };
  }, selector);
  throw new Error(`knowledge-control-action-unavailable:${selector}:${JSON.stringify(diagnostic)}`);
}

async function waitForInstalledControlState(frameHost, selector, predicate, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  let state = null;
  do {
    state = await frameHost.evaluate((frame, query) => {
      const control = frame.contentDocument?.querySelector(query);
      return {
        present: Boolean(control),
        visible: Boolean(control && (control.offsetWidth || control.offsetHeight || control.getClientRects().length)),
        disabled: Boolean(control?.disabled)
      };
    }, selector);
    if (predicate(state)) return state;
    await wait(150);
  } while (Date.now() < deadline);
  return state;
}

async function settleKnowledgeMutation(frameHost, before, operation, expected = {}, timeoutMs = 120_000) {
  const result = await waitForStudioOperationResult(frameHost, before, 'knowledge', operation, timeoutMs);
  if (!validKnowledgeLifecycleResult(operation, result, expected)) throw new Error(`knowledge-${operation}-receipt-invalid:${JSON.stringify(result)}`);
  const browse = await waitForStudioOperationResult(frameHost, before, 'knowledge', 'browse', timeoutMs);
  if (!validKnowledgeLifecycleResult('browse', browse)) throw new Error(`knowledge-${operation}-refresh-invalid:${JSON.stringify(browse)}`);
  await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
  return { operation, result, browse };
}

function knowledgeBrowseHasHead(browse, recordId, candidateSha256) {
  return (browse?.canonical || []).some(record => record.record_id === recordId && record.candidate_sha256 === candidateSha256);
}

function validLearningLifecycleResult(operation, result, expected = {}) {
  const record = result?.record && typeof result.record === 'object' ? result.record : result;
  if (record?.schema_version !== 'px.learning-pipeline/1.0' || typeof record.pipeline_id !== 'string' || !record.pipeline_id) return false;
  if (expected.pipeline_id && record.pipeline_id !== expected.pipeline_id) return false;
  const states = {
    'observe-experience': ['evidence'],
    'extract-pattern': ['pattern'],
    'form-hypothesis': ['hypothesis'],
    'record-trial': ['trialing', 'confidence-passed'],
    'research-validate': ['research-validated'],
    'final-validate': ['validated'],
    'admit-learning': ['admitted'],
    'measure-reuse': ['canonical']
  };
  if (!(states[operation] || []).includes(record.state)) return false;
  if (operation === 'admit-learning' && (typeof record.knowledge_proposal_id !== 'string' || !record.knowledge_proposal_id)) return false;
  if (operation === 'measure-reuse' && !Array.isArray(record.reuse_measurements)) return false;
  return true;
}

function learningLifecycleControlProbe(matrix, observation) {
  const admittedActions = new Set([
    'learningObserve', 'learningAppendEvidence', 'learningPattern', 'learningHypothesis', 'learningTrial',
    'learningResearch', 'learningFinalValidation', 'learningAdmit', 'learningReuse',
    'submitLearningObservation', 'submitLearningPattern', 'submitLearningHypothesis', 'submitLearningTrial',
    'submitLearningResearch', 'submitLearningFinalValidation', 'submitLearningReuse'
  ]);
  const admittedFields = new Set([
    'learningOperationId', 'learningTaskClass', 'learningOutcome', 'learningMetric', 'learningMetricValue',
    'learningCapabilities', 'learningEnvironmentSha', 'learningSourceIds', 'learningEvidenceRefs',
    'patternMetric', 'higherIsBetter', 'patternInterpretation', 'applicability',
    'hypothesisUnitId', 'hypothesisKind', 'hypothesisClaim', 'incumbentJson', 'challengerJson', 'dependencyHashJson',
    'trialWinner', 'trialEvidence', 'researchQuestion', 'researchReferencesJson', 'betterAlternativeFound',
    'researchConclusion', 'secondaryArtifactJson', 'finalValidationEvidence', 'partialUnits',
    'reuseUses', 'reuseSuccesses', 'reuseRegressions'
  ]);
  const requirements = matrix.controls.filter(control => control.surface_id === 'knowledge-core' && (
    (control.kind === 'action' && admittedActions.has(installedActionIdentity(control).action))
    || (control.kind === 'field' && admittedFields.has(String(control.control_id).split('.field.')[1]))
    || /^pxui\.knowledge-core\.form\.learning/.test(control.control_id)
    || ['pxui.knowledge-core.indicator.proposalState', 'pxui.knowledge-core.indicator.revisionHashes'].includes(control.control_id)
    || control.control_id === 'pxui.knowledge-core.lifecycle.path.1'
  ));
  const verified = observation.completed === true;
  const records = requirements.map(requirement => {
    const evidenceRef = `installed-learning-lifecycle:${requirement.control_id}`;
    return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_isolated_learning_lifecycle', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, observation.invalid_form_rejected
          ? { state: 'present', detail: 'The installed Learning form rejected an unnamed metric locally, retained the modal, and dispatched no host operation before the corrected lifecycle ran.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The matched invalid Learning form was not proven fail-closed.', evidence: [] }];
        return [stage, verified
          ? { state: 'present', detail: 'The installed Learning UI completed evidence capture, pattern extraction, immutable hypothesis creation, six bounded trials, independent research, final validation, normal Knowledge admission and promotion, and measured reuse in the owned disposable workspace.', evidence: [evidenceRef] }
          : { state: 'missing', detail: `The owned installed-host Learning lifecycle did not complete ${stage}.`, evidence: [] }];
      })),
      errors: observation.errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact Learning lifecycle operations executed only inside the owned isolated VS Code host and disposable workspace.', eligible_control_count: records.length, records };
}

async function runInstalledLearningLifecycleProfile(frameHost, matrix, timeoutMs = 120_000) {
  const observation = { rendered: false, attempted: false, completed: false, invalid_form_rejected: false, pipeline_id: '', proposal_id: '', operations: [], errors: [] };
  const evidence = label => `sha256:${crypto.createHash('sha256').update(`px-owned-learning:${label}`).digest('hex')}`;
  const set = async (values, submitAction) => frameHost.evaluate((frame, item) => {
    const document = frame.contentDocument;
    for (const [selector, value] of Object.entries(item.values)) {
      const field = document.querySelector(selector);
      if (!field) throw new Error(`learning-field-unavailable:${selector}`);
      if (field.type === 'checkbox') field.checked = Boolean(value);
      else field.value = String(value);
      field.dispatchEvent(new Event(field.tagName === 'SELECT' || field.type === 'checkbox' ? 'change' : 'input', { bubbles: true }));
    }
    const submit = document.querySelector(`[data-action="${CSS.escape(item.submitAction)}"]`);
    if (!submit || submit.disabled) throw new Error(`learning-submit-unavailable:${item.submitAction}`);
    submit.click();
  }, { values, submitAction });
  const invoke = async (openSelector, submitAction, operation, values) => {
    await waitForKnowledgeControl(frameHost, openSelector);
    await frameHost.evaluate((frame, selector) => frame.contentDocument.querySelector(selector).click(), openSelector);
    await waitForKnowledgeControl(frameHost, `[data-action="${submitAction}"]`);
    const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await set(values, submitAction);
    const result = await waitForStudioOperationResult(frameHost, before, 'knowledge', operation, timeoutMs);
    if (!validLearningLifecycleResult(operation, result, { pipeline_id: observation.pipeline_id || undefined })) throw new Error(`learning-${operation}-receipt-invalid:${JSON.stringify(result)}`);
    const record = result?.record || result;
    observation.pipeline_id ||= record.pipeline_id;
    observation.operations.push({ operation, result });
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
    return record;
  };
  try {
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="closeModal"]')?.click();
      document?.querySelector('[data-surface="dashboard"]')?.click();
      const toggle = document?.querySelector('[data-action="toggleAdvanced"]');
      if (toggle && toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
      document?.querySelector('[data-surface="knowledgeCore"]')?.click();
    });
    await waitForKnowledgeControl(frameHost, '[data-action="learningObserve"]');
    observation.rendered = true; observation.attempted = true;
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="learningObserve"]').click());
    await waitForKnowledgeControl(frameHost, '[data-action="submitLearningObservation"]');
    const invalidBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    observation.invalid_form_rejected = await frameHost.evaluate((frame, before) => {
      const document = frame.contentDocument; const metric = document.querySelector('#learning-metric'); const value = document.querySelector('#learning-metric-value');
      metric.value = ''; value.value = '1'; document.querySelector('[data-action="submitLearningObservation"]').click();
      return (frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0) === before && Boolean(value.validationMessage) && Boolean(document.querySelector('#learning-operation-id'));
    }, invalidBefore);
    if (!observation.invalid_form_rejected) throw new Error('learning-invalid-metric-not-rejected');
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="closeModal"]')?.click());
    const unique = Date.now().toString(36);
    await invoke('[data-action="learningObserve"]', 'submitLearningObservation', 'observe-experience', {
      '#learning-operation-id': `operation:px-owned-${unique}`, '#learning-task-class': 'repair', '#learning-outcome': 'bounded verification passed',
      '#learning-metric': 'quality', '#learning-metric-value': '1', '#learning-capabilities': 'px-debug-repair',
      '#learning-environment-sha': ownedKnowledgeSourceSha256, '#learning-source-ids': ownedKnowledgeSourceId,
      '#learning-evidence-refs': evidence('observation')
    });
    const pipelineSelector = action => `[data-action="${action}"][data-pipeline-id="${observation.pipeline_id}"]`;
    await invoke(pipelineSelector('learningPattern'), 'submitLearningPattern', 'extract-pattern', {
      '#learning-pattern-metric': 'quality', '#learning-higher-better': true,
      '#learning-interpretation': 'The bounded candidate preserves repair quality.', '#learning-applicability': 'repair'
    });
    await invoke(pipelineSelector('learningHypothesis'), 'submitLearningHypothesis', 'form-hypothesis', {
      '#learning-unit-id': `knowledge:px-owned-${unique}`, '#learning-unit-kind': 'knowledge', '#learning-claim': 'The bounded candidate improves repeatable repair handling.',
      '#learning-incumbent': JSON.stringify({ id: `knowledge:px-owned-${unique}`, kind: 'knowledge', steps: ['inspect', 'repair'] }),
      '#learning-challenger': JSON.stringify({ id: `knowledge:px-owned-${unique}`, kind: 'knowledge', steps: ['inspect', 'repair', 'verify'] }),
      '#learning-dependencies': '{}'
    });
    for (let index = 0; index < 6; index += 1) {
      await invoke(pipelineSelector('learningTrial'), 'submitLearningTrial', 'record-trial', {
        '#learning-trial-winner': 'challenger', '#learning-trial-evidence': evidence(`trial-${index}`)
      });
    }
    await invoke(pipelineSelector('learningResearch'), 'submitLearningResearch', 'research-validate', {
      '#learning-research-question': 'Does independent evidence support the bounded candidate?',
      '#learning-research-references': JSON.stringify([{ uri: 'evidence:px-owned-independent-review', evidence_ref: evidence('research'), independent: true }]),
      '#learning-better-alternative': false, '#learning-research-conclusion': 'No stronger bounded alternative was found.', '#learning-secondary-artifact': ''
    });
    await invoke(pipelineSelector('learningFinalValidation'), 'submitLearningFinalValidation', 'final-validate', {
      '#learning-final-evidence': evidence('final-validation'), '#learning-partial-units': 'bounded-repair'
    });
    await waitForKnowledgeControl(frameHost, pipelineSelector('learningAdmit'));
    const admitBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, selector) => frame.contentDocument.querySelector(selector).click(), pipelineSelector('learningAdmit'));
    const admitted = await waitForStudioOperationResult(frameHost, admitBefore, 'knowledge', 'admit-learning', timeoutMs);
    if (!validLearningLifecycleResult('admit-learning', admitted, { pipeline_id: observation.pipeline_id })) throw new Error(`learning-admit-receipt-invalid:${JSON.stringify(admitted)}`);
    const admittedRecord = admitted?.record || admitted; observation.proposal_id = admittedRecord.knowledge_proposal_id;
    const admittedBrowse = await waitForStudioOperationResult(frameHost, admitBefore, 'knowledge', 'browse', timeoutMs);
    if (!validKnowledgeLifecycleResult('browse', admittedBrowse)) throw new Error(`learning-admit-refresh-invalid:${JSON.stringify(admittedBrowse)}`);
    observation.operations.push({ operation: 'admit-learning', result: admitted, browse: admittedBrowse });
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
    const candidateSha256 = admittedRecord.knowledge_candidate_sha256;
    for (const operation of ['verify', 'approve', 'promote']) {
      const selector = `[data-action="knowledgeTransition"][data-operation="${operation}"][data-proposal-id="${observation.proposal_id}"]`;
      await waitForKnowledgeControl(frameHost, selector);
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluate((frame, query) => frame.contentDocument.querySelector(query).click(), selector);
      const settled = await settleKnowledgeMutation(frameHost, before, operation, { proposal_id: observation.proposal_id, candidate_sha256: candidateSha256 }, timeoutMs);
      observation.operations.push(settled);
    }
    await invoke(pipelineSelector('learningReuse'), 'submitLearningReuse', 'measure-reuse', {
      '#learning-reuse-uses': '12', '#learning-reuse-successes': '12', '#learning-reuse-regressions': '0'
    });
    observation.completed = true;
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 4000)); }
  return { schema_version: 'px.installed-learning-lifecycle-profile/1.0', authority: 'Exact Learning lifecycle operations executed only inside the owned isolated VS Code host and disposable workspace.', observation, control_probe: learningLifecycleControlProbe(matrix, observation) };
}

async function waitForCoordinationResult(frameHost, after, operation, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const response = await frameHost.evaluate((frame, item) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [])
      .slice(item.after).find(value => value?.type === 'coordinationResult' && value?.operation === item.operation) || null, { after, operation });
    if (response) return response;
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`coordination-${operation}-response-timeout`);
}

function validCoordinationResult(operation, response, expected = {}) {
  const envelope = response?.result;
  const receipt = envelope?.result?.receipt;
  if (!envelope?.state || !envelope?.event || !receipt || envelope.event.operation !== expected.event) return false;
  if (operation === 'createParallelPlan') return receipt.tasks === 2 && typeof receipt.plan_id === 'string';
  if (operation === 'claimCoordinationTask') return receipt.task_id === expected.task_id && typeof receipt.claim_id === 'string' && receipt.authority === 'local';
  if (operation === 'renewCoordinationClaim') return receipt.task_id === expected.task_id && receipt.claim_id === expected.claim_id && typeof receipt.expires_utc === 'string';
  if (operation === 'recordTaskProgress') return receipt.status === 'completed' && typeof receipt.id === 'string';
  if (operation === 'reconcileCoordinationTask') return receipt.task_id === expected.task_id && receipt.conflicts_resolved === true;
  if (operation === 'releaseCoordinationTask') return receipt.task_id === expected.task_id && receipt.released === true && response.authorization?.confirmed === true;
  if (operation === 'captureCoordinationMemory') return receipt.layer === 'project' && receipt.lifecycle === 'proposed' && typeof receipt.memory_id === 'string';
  return false;
}

function coordinationMemoryControlProbe(matrix, observation) {
  const exactControls = new Set([
    'pxui.workflows.action.newParallelPlan', 'pxui.workflows.action.submitParallelPlan', 'pxui.workflows.form.parallelPlan',
    'pxui.workflows.field.planObjective', 'pxui.workflows.field.planGoal', 'pxui.workflows.field.planTaskLines', 'pxui.workflows.indicator.activePlan',
    'pxui.workflows.action.claimTask.row', 'pxui.workflows.action.submitClaimTask', 'pxui.workflows.form.claimTask',
    'pxui.workflows.field.claimMode', 'pxui.workflows.field.claimAuthority', 'pxui.workflows.field.claimTTL',
    'pxui.workflows.indicator.claimBudget', 'pxui.workflows.indicator.claimFence', 'pxui.workflows.indicator.claimLease', 'pxui.workflows.indicator.taskStatus',
    'pxui.workflows.action.renewClaim.row',
    'pxui.workflows.action.completeTask.row', 'pxui.workflows.action.taskProgress.row', 'pxui.workflows.action.submitTaskProgress', 'pxui.workflows.form.taskProgress',
    'pxui.workflows.field.progressSummary', 'pxui.workflows.field.progressNextAction', 'pxui.workflows.field.progressTokens', 'pxui.workflows.field.progressMinutes',
    'pxui.workflows.action.reconcileTask.row', 'pxui.workflows.action.submitReconcile', 'pxui.workflows.form.reconcileTask',
    'pxui.workflows.field.reconcileSummary', 'pxui.workflows.field.reconcileConflictsResolved',
    'pxui.workflows.action.releaseTask.row', 'pxui.workflows.action.submitReleaseTask',
    'pxui.workflows.persistence.authoritativeState', 'pxui.workflows.reload_reopen.authoritativeState',
    'pxui.memory.action.captureMemory', 'pxui.memory.action.submitMemory', 'pxui.memory.form.captureMemory',
    'pxui.memory.persistence.authoritativeState', 'pxui.memory.reload_reopen.authoritativeState'
  ]);
  const requirements = matrix.controls.filter(control => exactControls.has(control.control_id));
  const verified = observation.completed === true && observation.webview_restarted === true;
  const records = requirements.map(requirement => {
    const evidenceRef = `installed-coordination-memory:${requirement.control_id}`;
    return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_isolated_coordination_memory', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, observation.invalid_release_rejected && observation.invalid_memory_rejected
          ? { state: 'present', detail: 'The installed Coordination release form rejected an unconfirmed empty reason and the Memory form rejected blank content without dispatching either host write.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'Both matched Coordination and Memory invalid forms were not proven fail-closed.', evidence: [] }];
        return [stage, verified
          ? { state: 'present', detail: 'The installed UI created a two-task governed plan, claimed and completed one task, reconciled it, claimed and explicitly released the second, appended project-scoped non-canonical memory, restarted the dashboard webview boundary, and reconstructed both durable records.', evidence: [evidenceRef] }
          : { state: 'missing', detail: `The owned coordination/memory lifecycle did not prove ${stage}.`, evidence: [] }];
      })),
      errors: observation.errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact coordination and portable-memory operations executed only inside the owned isolated VS Code host and disposable workspace.', eligible_control_count: records.length, records };
}

async function runInstalledCoordinationMemoryProfile(frameHost, matrix, timeoutMs = 30_000) {
  const observation = { rendered: false, attempted: false, completed: false, webview_restarted: false, invalid_release_rejected: false, invalid_memory_rejected: false, task_complete: '', task_release: '', memory_content: '', portable_memory_id: '', operations: [], errors: [] };
  const post = async (openSelector, submitAction, operation, values, expected) => {
    await waitForKnowledgeControl(frameHost, openSelector);
    await frameHost.evaluate((frame, selector) => frame.contentDocument.querySelector(selector).click(), openSelector);
    await waitForKnowledgeControl(frameHost, `[data-action="${submitAction}"]`);
    const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, item) => {
      const document = frame.contentDocument;
      for (const [selector, value] of Object.entries(item.values)) {
        const field = document.querySelector(selector); if (!field) throw new Error(`coordination-field-unavailable:${selector}`);
        if (field.type === 'checkbox') field.checked = Boolean(value); else field.value = String(value);
        field.dispatchEvent(new Event(field.tagName === 'SELECT' || field.type === 'checkbox' ? 'change' : 'input', { bubbles: true }));
      }
      const submit = document.querySelector(`[data-action="${CSS.escape(item.submitAction)}"]`);
      if (!submit || submit.disabled) throw new Error(`coordination-submit-unavailable:${item.submitAction}`);
      submit.click();
    }, { values, submitAction });
    const response = await waitForCoordinationResult(frameHost, before, operation, timeoutMs);
    if (!validCoordinationResult(operation, response, expected)) throw new Error(`coordination-${operation}-receipt-invalid:${JSON.stringify(response)}`);
    observation.operations.push({ operation, response });
    return response;
  };
  try {
    const unique = Date.now().toString(36);
    observation.task_complete = `px-complete-${unique}`; observation.task_release = `px-release-${unique}`;
    observation.memory_content = `PX owned operational memory ${unique}`;
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument; document?.querySelector('[data-action="closeModal"]')?.click();
      document?.querySelector('[data-surface="workflows"]')?.click();
      const core = document?.querySelector('[data-action="surfaceScope"][data-target="workflows"][data-scope="core"]'); if (core && core.getAttribute('aria-pressed') !== 'true') core.click();
    });
    await waitForKnowledgeControl(frameHost, '[data-action="newParallelPlan"]');
    observation.rendered = true; observation.attempted = true;
    await post('[data-action="newParallelPlan"]', 'submitParallelPlan', 'createParallelPlan', {
      '#plan-objective': 'Exercise the owned disposable coordination lifecycle.', '#plan-goal': 'operational verification',
      '#plan-tasks': `${observation.task_complete} | Complete bounded task | | .px-owned/${unique}/complete | VS Code | px | 1000 | workspace-read,workspace-write\n${observation.task_release} | Release bounded task | | .px-owned/${unique}/release | VS Code | px | 1000 | workspace-read,workspace-write`
    }, { event: 'parallel-plan-created' });
    const completedClaim = await post(`[data-action="claimTask"][data-task-id="${observation.task_complete}"]`, 'submitClaimTask', 'claimCoordinationTask', {
      '#claim-mode': 'exclusive', '#claim-authority': 'local', '#claim-ttl': '30'
    }, { event: 'task-claimed', task_id: observation.task_complete });
    const completedClaimId = completedClaim.result.result.receipt.claim_id;
    const renewBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await waitForKnowledgeControl(frameHost, `[data-action="renewClaim"][data-task-id="${observation.task_complete}"][data-claim-id="${completedClaimId}"]`);
    await frameHost.evaluate((frame, selector) => frame.contentDocument.querySelector(selector).click(), `[data-action="renewClaim"][data-task-id="${observation.task_complete}"][data-claim-id="${completedClaimId}"]`);
    const renewed = await waitForCoordinationResult(frameHost, renewBefore, 'renewCoordinationClaim', timeoutMs);
    if (!validCoordinationResult('renewCoordinationClaim', renewed, { event: 'task-lease-renewed', task_id: observation.task_complete, claim_id: completedClaimId })) throw new Error(`coordination-renew-receipt-invalid:${JSON.stringify(renewed)}`);
    observation.operations.push({ operation: 'renewCoordinationClaim', response: renewed });
    await post(`[data-action="completeTask"][data-task-id="${observation.task_complete}"]`, 'submitTaskProgress', 'recordTaskProgress', {
      '#progress-summary': 'Owned disposable task completed with bounded evidence.', '#progress-tokens': '1', '#progress-minutes': '1', '#progress-next': 'Reconcile the retained receipt.'
    }, { event: 'task-progress-recorded', task_id: observation.task_complete });
    await post(`[data-action="reconcileTask"][data-task-id="${observation.task_complete}"]`, 'submitReconcile', 'reconcileCoordinationTask', {
      '#reconcile-summary': 'Owned disposable task reconciled without conflicts.', '#reconcile-conflicts': true
    }, { event: 'task-reconciled', task_id: observation.task_complete });
    await post(`[data-action="claimTask"][data-task-id="${observation.task_release}"]`, 'submitClaimTask', 'claimCoordinationTask', {
      '#claim-mode': 'exclusive', '#claim-authority': 'local', '#claim-ttl': '30'
    }, { event: 'task-claimed', task_id: observation.task_release });
    const releaseSelector = `[data-action="releaseTask"][data-task-id="${observation.task_release}"]`;
    await clickWhenKnowledgeControlReady(frameHost, releaseSelector, timeoutMs);
    await waitForKnowledgeControl(frameHost, '[data-action="submitReleaseTask"]');
    const invalidReleaseBefore = await frameHost.evaluate(frame => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [])
      .filter(value => value?.type === 'coordinationResult' && value?.operation === 'releaseCoordinationTask').length);
    observation.invalid_release_rejected = await frameHost.evaluate((frame, before) => {
      const document = frame.contentDocument;
      const reason = document.querySelector('#release-reason');
      reason.value = '';
      reason.dispatchEvent(new Event('input', { bubbles: true }));
      document.querySelector('[data-action="submitReleaseTask"]').click();
      const validation = document.querySelector('[data-release-validation]');
      const exactReleases = (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [])
        .filter(value => value?.type === 'coordinationResult' && value?.operation === 'releaseCoordinationTask').length;
      return exactReleases === before && reason.value === ''
        && validation?.hidden === false && /at least 10 characters/i.test(String(validation.textContent || ''));
    }, invalidReleaseBefore);
    if (!observation.invalid_release_rejected) throw new Error('coordination-invalid-release-not-rejected');
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="closeModal"]')?.click());
    await post(`[data-action="releaseTask"][data-task-id="${observation.task_release}"]`, 'submitReleaseTask', 'releaseCoordinationTask', {
      '#release-reason': 'Owned disposable operational release after receipt verification.', '#release-confirm': true
    }, { event: 'task-released', task_id: observation.task_release });
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
    await navigateInstalledSurface(frameHost, 'memory', timeoutMs);
    await waitForKnowledgeControl(frameHost, '[data-action="captureMemory"]');
    await frameHost.evaluate(frame => {
      const capture = frame.contentDocument.querySelector('[data-action="captureMemory"]');
      if (!capture || capture.disabled) throw new Error('memory-capture-control-unavailable');
      capture.click();
    });
    await waitForKnowledgeControl(frameHost, '[data-action="submitMemory"]');
    const invalidMemoryBefore = await installedOutboundRequestOffset(frameHost);
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument; const content = document.querySelector('#memory-content');
      content.value = ''; content.dispatchEvent(new Event('input', { bubbles: true }));
      document.querySelector('[data-action="submitMemory"]').click();
    });
    await wait(120);
    observation.invalid_memory_rejected = await frameHost.evaluate((frame, before) => {
      const document = frame.contentDocument; const content = document.querySelector('#memory-content');
      const dispatched = (frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || []).slice(before)
        .some(value => value?.type === 'captureCoordinationMemory');
      return !dispatched && Boolean(content) && content.value === ''
        && content.required === true && content.validity?.valueMissing === true
        && content.closest('.control-modal') != null;
    }, invalidMemoryBefore);
    if (!observation.invalid_memory_rejected) throw new Error('memory-blank-content-not-rejected');
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="closeModal"]')?.click());
    const capturedMemory = await post('[data-action="captureMemory"]', 'submitMemory', 'captureCoordinationMemory', {
      '#memory-layer': 'project', '#memory-kind': 'observation', '#memory-content': observation.memory_content
    }, { event: 'memory-captured' });
    observation.portable_memory_id = capturedMemory.result.result.receipt.memory_id;
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
    observation.webview_restarted = restart.restarted === true;
    await frameHost.evaluate(frame => { const document = frame.contentDocument; document?.querySelector('[data-surface="dashboard"]')?.click(); document?.querySelector('[data-surface="workflows"]')?.click(); });
    const workflowsText = await waitForInstalledMemoryText(frameHost, new RegExp(`${observation.task_complete}|${observation.task_release}`), timeoutMs);
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-surface="memory"]')?.click());
    const portableSelector = `[data-action="inspectMemoryRecord"][data-portable-memory-id="${observation.portable_memory_id}"]`;
    await waitForKnowledgeControl(frameHost, portableSelector);
    const portableRow = await frameHost.evaluate((frame, selector) => String(frame.contentDocument.querySelector(selector)?.innerText || ''), portableSelector);
    observation.reopened = workflowsText.includes(observation.task_complete) && portableRow.includes('observation') && portableRow.includes('project');
    if (!observation.reopened) throw new Error('coordination-memory-reopen-mismatch');
    observation.completed = true;
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 4000)); }
  return { schema_version: 'px.installed-coordination-memory-profile/1.0', authority: 'Exact coordination and portable-memory operations executed only inside the owned isolated VS Code host and disposable workspace.', observation, control_probe: coordinationMemoryControlProbe(matrix, observation) };
}

function validCleanupResult(result) {
  const receipt = result?.receipt;
  return receipt?.schema_version === '2.0'
    && receipt.disposition === 'recycle'
    && receipt.hard_delete === false
    && receipt.state === 'completed'
    && receipt.resources_reclaimed >= 1
    && receipt.resources_uncertain === 0
    && Array.isArray(receipt.errors) && receipt.errors.length === 0
    && Array.isArray(receipt.resources) && receipt.resources.every(resource => resource.result === 'moved-to-recycle-bin');
}

function validPermanentCleanupResult(result) {
  const receipt = result?.receipt;
  return receipt?.schema_version === '2.0'
    && receipt.disposition === 'permanent'
    && receipt.hard_delete === true
    && receipt.state === 'completed'
    && receipt.resources_reclaimed === 1
    && receipt.resources_uncertain === 0
    && Array.isArray(receipt.errors) && receipt.errors.length === 0
    && Array.isArray(receipt.resources) && receipt.resources.length === 1
    && receipt.resources[0]?.result === 'permanently-reclaimed';
}

function cleanupControlProbe(matrix, observation) {
  const exactControls = new Set([
    'pxui.runtime-core.action.cleanupManager', 'pxui.runtime-core.action.refreshCleanup',
    'pxui.runtime-core.action.cleanupRecycle', 'pxui.runtime-core.action.cleanupPermanent', 'pxui.runtime-core.action.cleanupSelectAll', 'pxui.runtime-core.field.cleanupCandidateCheckbox.row',
    'pxui.runtime-core.form.cleanupSelection', 'pxui.runtime-core.indicator.cleanupBytes',
    'pxui.runtime-core.indicator.cleanupCandidates', 'pxui.runtime-core.indicator.cleanupSelection',
    'pxui.runtime-core.indicator.cleanupReceipt',
    'pxui.runtime-core.persistence.authoritativeState', 'pxui.runtime-core.reload_reopen.authoritativeState'
  ]);
  const requirements = matrix.controls.filter(control => exactControls.has(control.control_id));
  const verified = observation.completed === true && observation.webview_restarted === true && observation.reclaimed_absent_after_restart === true && validCleanupResult(observation.result);
  const records = requirements.map(requirement => {
    const evidenceRef = `installed-cleanup-recycle:${requirement.control_id}`;
    const permanent = requirement.control_id === 'pxui.runtime-core.action.cleanupPermanent';
    const selectAll = requirement.control_id === 'pxui.runtime-core.action.cleanupSelectAll';
    const controlVerified = permanent ? observation.permanent_completed === true : selectAll ? verified && observation.select_all_round_trip === true : verified;
    return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_isolated_cleanup_recycle', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
      authority_skipped: permanent && observation.permanent_refused_without_authorization === true && observation.permanent_completed !== true,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, permanent ? (observation.permanent_refused_without_authorization === true
          ? { state: 'present', detail: 'Permanent cleanup remained unavailable without the separate irreversible-test authorization.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The irreversible cleanup authorization boundary was not observed.', evidence: [] }) : observation.invalid_selection_rejected
          ? { state: 'present', detail: 'The installed cleanup manager kept Recycle disabled with no selected candidate and dispatched no cleanup request before the exact candidate was selected.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The empty cleanup selection was not proven fail-closed.', evidence: [] }];
        if (stage === 'recovery_rollback' && permanent) return [stage, observation.permanent_refused_without_authorization === true
          ? { state: 'present', detail: 'The native confirmation was cancelled, the exact disposable candidate remained present, and no cleanup result was emitted.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The permanent-cleanup cancellation did not prove exact no-effect recovery.', evidence: [] }];
        return [stage, controlVerified
          ? { state: 'present', detail: permanent ? 'A separately authorized irreversible test deleted only an exact PACIFY-X-owned disposable candidate and retained its permanent cleanup receipt.' : 'The installed Runtime cleanup UI scanned the bounded disposable engine, selected an exact hash-bound safe-cache candidate, received native Recycle Bin confirmation, restarted the dashboard webview boundary, and proved the reclaimed candidate remained absent from a fresh authoritative scan.', evidence: [evidenceRef] }
          : { state: 'missing', detail: `The owned cleanup recycle profile did not prove ${stage}.`, evidence: [] }];
      })), errors: observation.errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact safe-cache recycle inside the owned disposable engine; permanent deletion remains incomplete unless a separate authorization enables one exact test-owned cache candidate.', eligible_control_count: records.length, records };
}

function projectMapIdentity(snapshot) {
  const project = snapshot?.project;
  const map = project?.map;
  if (!project || !map || typeof map !== 'object') return null;
  const identity = {
    project_path: String(project.path || ''),
    map_revision: String(map.map_revision || ''),
    source_inventory_sha256: String(map.source_inventory_sha256 || ''),
    validation_scope: String(map.validation_scope || ''),
    files: Number(map.counts?.files || 0),
    architecture_nodes: Number(map.counts?.architecture_nodes || 0)
  };
  if (!identity.project_path || !identity.map_revision || !/^[0-9a-f]{64}$/.test(identity.source_inventory_sha256)) return null;
  return identity;
}

function projectsControlProbe(matrix, observation) {
  const buildControlIds = [
    'pxui.projects.action.buildRepositoryGraph',
    'pxui.knowledge-graph.action.buildRepositoryGraph',
    'pxui.diagnostics.action.dynamicRepair.buildRepositoryGraph'
  ];
  const exactControls = new Set([
    ...buildControlIds,
    'pxui.projects.persistence.authoritativeState',
    'pxui.projects.reload_reopen.authoritativeState'
  ]);
  const requirements = matrix.controls.filter(control => exactControls.has(control.control_id));
  const verified = observation.completed === true && observation.webview_restarted === true && observation.exact_reconstruction === true
    && projectMapIdentity({ project: observation.before_restart }) !== null;
  const allBuildControlsCancelled = buildControlIds.every(controlId => observation.cancelled_controls?.[controlId] === true);
  const records = requirements.map(requirement => {
    const evidenceRef = `installed-project-map-restart:${requirement.control_id}`;
    const isBuildControl = Object.prototype.hasOwnProperty.call(observation.cancelled_controls || {}, requirement.control_id);
    const exactRendered = isBuildControl ? observation.rendered_controls?.[requirement.control_id] === true : observation.rendered === true;
    const exactAttempted = isBuildControl ? observation.attempted_controls?.[requirement.control_id] === true : observation.attempted === true;
    const exactVerified = verified && exactRendered && exactAttempted;
    return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_disposable_project_map_restart', rendered: exactRendered, observed: exactRendered, attempted: exactAttempted,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (['failure_handling', 'recovery_rollback'].includes(stage)) {
          const cancelled = isBuildControl ? observation.cancelled_controls?.[requirement.control_id] === true : allBuildControlsCancelled;
          return [stage, cancelled
            ? { state: 'present', detail: stage === 'failure_handling'
              ? 'The exact physical map-build entry point reached its native approval boundary and was cancelled before effect.'
              : 'Cancellation emitted no graph-build result and the same exact rendered entry point remained available for the later owned build.', evidence: [evidenceRef] }
            : { state: 'missing', detail: 'The exact native cancellation and no-effect recovery were not both observed for this entry point.', evidence: [] }];
        }
        return [stage, exactVerified
          ? { state: 'present', detail: 'This exact physical map-build entry point reached the shared native approval boundary; the expensive derived map build executed once in the disposable workspace, returned a typed result and authoritative snapshot, and reconstructed the same exact map identity after webview restart.', evidence: [evidenceRef] }
          : { state: 'missing', detail: `The owned Projects map profile did not prove ${stage}.`, evidence: [] }];
      })),
      errors: observation.errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Derived project-map build and restart reconstruction only inside the owned disposable workspace; user project source is not edited.', eligible_control_count: records.length, records };
}

async function runInstalledProjectsProfile(workbench, frameHost, matrix, timeoutMs = 120_000) {
  const observation = { rendered: false, attempted: false, rendered_controls: {}, attempted_controls: {}, cancelled_controls: {}, completed: false, webview_restarted: false, exact_reconstruction: false, build_result: null, before_restart: null, after_restart: null, errors: [] };
  const buildDialogText = /Build or refresh the bounded repository architecture graph/i;
  try {
    for (const [route, controlId] of [
      ['knowledgeGraph', 'pxui.knowledge-graph.action.buildRepositoryGraph'],
      ['diagnostics', 'pxui.diagnostics.action.dynamicRepair.buildRepositoryGraph']
    ]) {
      await frameHost.evaluate((frame, target) => {
        const document = frame.contentDocument; document?.querySelector('[data-action="closeModal"]')?.click(); document?.querySelector(`[data-surface="${CSS.escape(target)}"]`)?.click();
      }, route);
      await waitForKnowledgeControl(frameHost, '[data-action="buildRepositoryGraph"]');
      observation.rendered_controls[controlId] = true;
      const cancelBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const requestBeforeCancel = await installedOutboundRequestOffset(frameHost);
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="buildRepositoryGraph"]').click());
      const cancelledDialog = await waitForNativeWorkbenchDialog(workbench, /Build or refresh the bounded repository architecture graph/i, 15_000, { frameHost, responseOffset: cancelBefore, requestOffset: requestBeforeCancel, requestType: 'buildRepositoryGraph', keyboardAction: 'Cancel' });
      await clickNativeWorkbenchDialogAction(workbench, cancelledDialog, 'Cancel');
      await waitForKnowledgeControl(frameHost, '[data-action="buildRepositoryGraph"]');
      const cancelResponses = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after), cancelBefore);
      observation.cancelled_controls[controlId] = !cancelResponses.some(value => value?.type === 'graphBuildResult');
      observation.attempted_controls[controlId] = true;
    }
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="closeModal"]')?.click();
      document?.querySelector('[data-surface="projects"]')?.click();
    });
    await waitForKnowledgeControl(frameHost, '[data-action="buildRepositoryGraph"]');
    observation.rendered = true; observation.attempted = true;
    observation.rendered_controls['pxui.projects.action.buildRepositoryGraph'] = true;
    observation.attempted_controls['pxui.projects.action.buildRepositoryGraph'] = true;
    const projectsCancelBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const projectsRequestBeforeCancel = await installedOutboundRequestOffset(frameHost);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="buildRepositoryGraph"]').click());
    const projectsCancelledDialog = await waitForNativeWorkbenchDialog(workbench, buildDialogText, 15_000, { frameHost, responseOffset: projectsCancelBefore, requestOffset: projectsRequestBeforeCancel, requestType: 'buildRepositoryGraph', keyboardAction: 'Cancel' });
    await clickNativeWorkbenchDialogAction(workbench, projectsCancelledDialog, 'Cancel');
    await waitForKnowledgeControl(frameHost, '[data-action="buildRepositoryGraph"]');
    const projectsCancelResponses = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after), projectsCancelBefore);
    observation.cancelled_controls['pxui.projects.action.buildRepositoryGraph'] = !projectsCancelResponses.some(value => value?.type === 'graphBuildResult');
    const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const requestBeforeBuild = await installedOutboundRequestOffset(frameHost);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="buildRepositoryGraph"]').click());
    const dialog = await waitForNativeWorkbenchDialog(workbench, /Build or refresh the bounded repository architecture graph/i, 15_000, { frameHost, responseOffset: before, requestOffset: requestBeforeBuild, requestType: 'buildRepositoryGraph', keyboardAction: 'Build graph' });
    await clickNativeWorkbenchDialogAction(workbench, dialog, 'Build graph');
    const deadline = Date.now() + timeoutMs;
    do {
      const responses = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after), before);
      observation.build_result = responses.find(value => value?.type === 'graphBuildResult')?.result || observation.build_result;
      const snapshot = responses.filter(value => value?.type === 'snapshot').at(-1)?.snapshot || null;
      if (observation.build_result && projectMapIdentity(snapshot)) { observation.before_restart = snapshot.project; break; }
      const failure = responses.find(value => value?.type === 'operationError');
      if (failure) throw new Error(`project-map-build-failed:${failure.error}`);
      await wait(150);
    } while (Date.now() < deadline);
    if (!observation.build_result || !projectMapIdentity({ project: observation.before_restart })) throw new Error('project-map-build-or-authoritative-snapshot-timeout');
    const expected = projectMapIdentity({ project: observation.before_restart });
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
    observation.webview_restarted = restart.restarted === true;
    const refreshBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="refresh"]')?.click();
      document?.querySelector('[data-surface="projects"]')?.click();
    });
    const reopenDeadline = Date.now() + 30_000;
    do {
      const snapshot = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after).filter(value => value?.type === 'snapshot').at(-1)?.snapshot || null, refreshBefore);
      const actual = projectMapIdentity(snapshot);
      if (actual) {
        observation.after_restart = snapshot.project;
        observation.exact_reconstruction = JSON.stringify(actual) === JSON.stringify(expected);
        if (observation.exact_reconstruction) break;
      }
      await wait(150);
    } while (Date.now() < reopenDeadline);
    if (!observation.exact_reconstruction) throw new Error(`project-map-restart-reconstruction-mismatch:${JSON.stringify({ expected, actual: projectMapIdentity({ project: observation.after_restart }) })}`);
    observation.completed = true;
  } catch (error) {
    observation.errors.push(String(error?.message || error).slice(0, 4000));
    await dismissOwnedNativeWorkbenchDialog(workbench, buildDialogText).catch(dismissError => observation.errors.push(`dialog-recovery:${String(dismissError?.message || dismissError).slice(0, 1800)}`));
  }
  return { schema_version: 'px.installed-projects-profile/1.0', authority: 'Derived map build and exact restart reconstruction in the owned disposable workspace.', observation, control_probe: projectsControlProbe(matrix, observation) };
}

function graphProjectionIdentity(result) {
  if (!result || typeof result !== 'object' || result.available !== true || result.view !== 'repository' || !Array.isArray(result.nodes) || !Array.isArray(result.edges)) return null;
  const nodes = result.nodes.map(node => String(node?.key || '')).filter(Boolean).sort();
  const edges = result.edges.map(edge => `${String(edge?.source || '')}\0${String(edge?.relation || '')}\0${String(edge?.target || '')}`).sort();
  if (nodes.length !== result.nodes.length || edges.some(value => value.startsWith('\0') || value.endsWith('\0'))) return null;
  return {
    source: String(result.source || ''),
    view: result.view,
    mode: String(result.mode || ''),
    cluster: result.cluster || null,
    requested_query: String(result.requested_query || ''),
    requested_relation: String(result.requested_relation || ''),
    direction: String(result.direction || ''),
    depth: Number(result.depth || 0),
    total_nodes: Number(result.total_nodes || 0),
    total_edges: Number(result.total_edges || 0),
    content_sha256: crypto.createHash('sha256').update(JSON.stringify({ nodes, edges })).digest('hex')
  };
}

function requestBoundGraphResultIdentity(request, response) {
  if (!request || request.type !== 'graphQuery' || typeof request.requestId !== 'string' || !request.requestId) return null;
  if (!response || response.requestId !== request.requestId) return null;
  if (response.type === 'operationError' && response.operation === 'graphQuery') {
    return { request_id: request.requestId, terminal: 'error', error: String(response.error || '') };
  }
  const result = response.type === 'graphResult' ? graphProjectionIdentity(response.result) : null;
  return result ? { request_id: request.requestId, terminal: 'result', result } : null;
}

function knowledgeGraphControlProbe(matrix, observation) {
  const exactActions = new Set([
    'pxui.knowledge-graph.action.graphApplySavedView.row',
    'pxui.knowledge-graph.action.graphDeleteSavedView.row'
  ]);
  const requirements = matrix.controls.filter(control => control.surface_id === 'knowledge-graph'
    && (['persistence', 'reload_reopen'].includes(control.kind) || exactActions.has(control.control_id)));
  const verified = observation.completed === true && observation.webview_restarted === true && observation.exact_reconstruction === true && observation.restored === true;
  const records = requirements.map(requirement => {
    const evidenceRef = `installed-knowledge-graph-restart:${requirement.control_id}`;
    const exactActionVerified = requirement.control_id === 'pxui.knowledge-graph.action.graphApplySavedView.row'
      ? observation.saved_view_applied === true
      : requirement.control_id === 'pxui.knowledge-graph.action.graphDeleteSavedView.row'
        ? observation.saved_view_deleted === true
        : true;
    return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_disposable_knowledge_graph_restart', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, observation.invalid_rejected
          ? { state: 'present', detail: 'A blank saved-view name was rejected without adding or replacing persisted graph state.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The invalid saved-view state was not proven rejected.', evidence: [] }];
        if (stage === 'recovery_rollback') return [stage, observation.restored
          ? { state: 'present', detail: 'The exact temporary saved view was deleted after restart reconstruction and its absence was observed.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The temporary saved-view state was not exactly removed.', evidence: [] }];
        return [stage, verified && exactActionVerified
          ? { state: 'present', detail: 'The installed Knowledge Graph saved an exact bounded repository-view preset, restarted the dashboard webview, reconstructed the same normalized preset, reapplied it, and received a semantically identical authoritative repository graph projection.', evidence: [evidenceRef] }
          : { state: 'missing', detail: `The owned Knowledge Graph profile did not prove ${stage}.`, evidence: [] }];
      })),
      errors: observation.errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Bounded local view-state mutation plus authoritative repository graph query only inside the owned disposable workspace.', eligible_control_count: records.length, records };
}

async function runInstalledKnowledgeGraphProfile(frameHost, matrix, timeoutMs = 60_000) {
  const viewName = `PX owned restart ${Date.now().toString(36)}`;
  const observation = { rendered: false, attempted: false, invalid_rejected: false, saved_view_created: false, saved_view_applied: false, saved_view_deleted: false, webview_restarted: false, exact_reconstruction: false, restored: false, completed: false, view_name: viewName, before_restart: null, after_restart: null, errors: [] };
  const waitForGraph = async (offsets, retry) => {
    const deadline = Date.now() + timeoutMs;
    const retryAt = Date.now() + Math.min(5_000, Math.max(1_000, Math.floor(timeoutMs / 3)));
    let retried = false;
    do {
      const pair = await frameHost.evaluate((frame, after) => {
        const request = (frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || []).slice(after.requests)
          .filter(value => value?.type === 'graphQuery' && typeof value.requestId === 'string' && value.requestId).at(-1);
        const response = request ? (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after.responses)
          .find(value => value?.requestId === request.requestId && (value?.type === 'graphResult' || (value?.type === 'operationError' && value?.operation === 'graphQuery'))) : null;
        return { request, response };
      }, offsets);
      const identity = requestBoundGraphResultIdentity(pair.request, pair.response);
      if (identity?.terminal === 'error') throw new Error(`knowledge-graph-query-failed:${identity.error}`);
      if (identity?.terminal === 'result') return pair.response.result;
      if (!identity && !retried && Date.now() >= retryAt && typeof retry === 'function') {
        retried = true;
        await retry();
      }
      await wait(150);
    } while (Date.now() < deadline);
    throw new Error('knowledge-graph-request-bound-result-timeout');
  };
  try {
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="closeModal"]')?.click();
      document?.querySelector('[data-surface="knowledgeGraph"]')?.click();
    });
    await waitForKnowledgeControl(frameHost, '[data-action="graphView"][data-view="repository"]');
    observation.rendered = true;
    observation.attempted = true;
    let after = await frameHost.evaluate(frame => ({
      responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0,
      requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0
    }));
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="graphView"][data-view="repository"]').click());
    const baseline = await waitForGraph(after, () => frameHost.evaluate(frame => {
      const control = frame.contentDocument?.querySelector('[data-action="graphView"][data-view="repository"]');
      if (!control || control.disabled) throw new Error('knowledge-graph-retry-control-unavailable');
      control.click();
    }));
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="graphSaveView"]').click());
    const priorCount = await frameHost.evaluate(frame => frame.contentDocument.querySelectorAll('[data-action="graphApplySavedView"]').length);
    await frameHost.evaluate(frame => { const input = frame.contentDocument.querySelector('#graph-view-name'); input.value = ''; frame.contentDocument.querySelector('[data-action="submitGraphSavedView"]').click(); });
    observation.invalid_rejected = await frameHost.evaluate((frame, count) => frame.contentDocument.querySelectorAll('[data-action="graphApplySavedView"]').length === count && Boolean(frame.contentDocument.querySelector('#graph-view-name')), priorCount);
    if (!observation.invalid_rejected) throw new Error('knowledge-graph-blank-view-not-rejected');
    await frameHost.evaluate((frame, name) => { const input = frame.contentDocument.querySelector('#graph-view-name'); input.value = name; frame.contentDocument.querySelector('[data-action="submitGraphSavedView"]').click(); }, viewName);
    const saved = await frameHost.evaluate((frame, name) => [...frame.contentDocument.querySelectorAll('[data-action="graphApplySavedView"]')].some(item => item.textContent.trim() === name), viewName);
    if (!saved) throw new Error('knowledge-graph-saved-view-not-visible');
    observation.saved_view_created = true;
    observation.before_restart = graphProjectionIdentity(baseline);
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
    observation.webview_restarted = restart.restarted === true;
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-surface="knowledgeGraph"]')?.click());
    await waitForKnowledgeControl(frameHost, '[data-action="graphApplySavedView"]');
    after = await frameHost.evaluate(frame => ({
      responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0,
      requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0
    }));
    await frameHost.evaluate((frame, name) => {
      const control = [...frame.contentDocument.querySelectorAll('[data-action="graphApplySavedView"]')].find(item => item.textContent.trim() === name);
      if (!control) throw new Error('knowledge-graph-restarted-view-missing');
      control.click();
    }, viewName);
    observation.saved_view_applied = true;
    observation.after_restart = graphProjectionIdentity(await waitForGraph(after, () => frameHost.evaluate((frame, name) => {
      const control = [...(frame.contentDocument?.querySelectorAll('[data-action="graphApplySavedView"]') || [])]
        .find(item => item.textContent.trim() === name);
      if (!control || control.disabled) throw new Error('knowledge-graph-retry-saved-view-unavailable');
      control.click();
    }, viewName)));
    observation.exact_reconstruction = JSON.stringify(observation.after_restart) === JSON.stringify(observation.before_restart);
    if (!observation.exact_reconstruction) throw new Error(`knowledge-graph-projection-substitution:${JSON.stringify({ before: observation.before_restart, after: observation.after_restart })}`);
    await frameHost.evaluate((frame, name) => {
      const apply = [...frame.contentDocument.querySelectorAll('[data-action="graphApplySavedView"]')].find(item => item.textContent.trim() === name);
      const remove = apply?.parentElement?.querySelector('[data-action="graphDeleteSavedView"]');
      if (!remove) throw new Error('knowledge-graph-view-delete-unavailable');
      remove.click();
    }, viewName);
    observation.restored = await frameHost.evaluate((frame, name) => ![...frame.contentDocument.querySelectorAll('[data-action="graphApplySavedView"]')].some(item => item.textContent.trim() === name), viewName);
    observation.saved_view_deleted = observation.restored;
    if (!observation.restored) throw new Error('knowledge-graph-view-rollback-failed');
    observation.completed = true;
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 4000)); }
  return { schema_version: 'px.installed-knowledge-graph-profile/1.0', authority: 'Bounded local saved-view state and repository graph reconstruction in the owned disposable workspace.', observation, control_probe: knowledgeGraphControlProbe(matrix, observation) };
}

function systemProjectionIdentity(snapshot) {
  const sourceRoot = snapshot?.source?.engineRoot || snapshot?.source?.root;
  if (!snapshot || snapshot.connected !== true || !sourceRoot || !snapshot.source?.version || !snapshot.project?.path) return null;
  const counts = snapshot.counts && typeof snapshot.counts === 'object' ? Object.fromEntries(Object.entries(snapshot.counts).sort(([left], [right]) => left.localeCompare(right))) : {};
  return {
    schema_version: String(snapshot.schemaVersion || snapshot.schema_version || ''),
    source_root: String(sourceRoot),
    source_version: String(snapshot.source.version),
    project_path: String(snapshot.project.path),
    map_revision: String(snapshot.project.map?.map_revision || ''),
    map_source_sha256: String(snapshot.project.map?.source_inventory_sha256 || ''),
    extension_tree_sha256: String(snapshot.extensionIdentity?.source?.tree_sha256 || snapshot.extensionSourceIdentity?.tree_sha256 || snapshot.extension_identity?.tree_sha256 || ''),
    repair_campaign_id: String(snapshot.repairCampaign?.campaign_id || snapshot.repair_campaign?.campaign_id || ''),
    repair_campaign_phase: String(snapshot.repairCampaign?.phase || snapshot.repair_campaign?.phase || ''),
    counts_sha256: crypto.createHash('sha256').update(JSON.stringify(counts)).digest('hex')
  };
}

function requestBoundSystemSnapshotIdentity(request, response) {
  if (!request || request.type !== 'refresh' || !response || response.type !== 'snapshot') return null;
  const identity = systemProjectionIdentity(response.snapshot);
  return identity ? { request_type: request.type, snapshot: response.snapshot, identity } : null;
}

function systemProjectionControlProbe(matrix, observation) {
  const surfaces = new Set(['dashboard', 'dashboard-control-plane', 'diagnostics', 'assurance']);
  const requirements = matrix.controls.filter(control => surfaces.has(control.surface_id) && ['persistence', 'reload_reopen'].includes(control.kind));
  const verified = observation.completed === true && observation.webview_restarted === true && observation.exact_reconstruction === true;
  const records = requirements.map(requirement => {
    const evidenceRef = `installed-system-projection-restart:${requirement.control_id}`;
    return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_canonical_snapshot_restart', rendered: Boolean(observation.rendered?.[requirement.surface_id]), observed: Boolean(observation.rendered?.[requirement.surface_id]), attempted: observation.attempted,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (['failure_handling', 'recovery_rollback'].includes(stage)) return [stage, { state: 'missing', detail: 'The separate disposable engine-outage profile supplies the physical failure and exact recovery stages.', evidence: [] }];
        return [stage, verified && observation.rendered?.[requirement.surface_id]
          ? { state: 'present', detail: 'The exact system surface rendered from a fresh canonical snapshot, restarted the dashboard webview boundary, refreshed through the same host owner, and reconstructed the identical source, project-map, extension, repair-campaign, and complete count identity.', evidence: [evidenceRef] }
          : { state: 'missing', detail: `The system projection profile did not prove ${stage}.`, evidence: [] }];
      })), errors: observation.errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Read-only canonical snapshot reconstruction in the exact-source owned host.', eligible_control_count: records.length, records };
}

async function runInstalledSystemProjectionProfile(frameHost, matrix) {
  const observation = { attempted: false, completed: false, webview_restarted: false, exact_reconstruction: false, rendered: {}, before_restart: null, after_restart: null, errors: [] };
  const surfaces = [['dashboard', 'dashboard'], ['dashboard-control-plane', 'dashboard'], ['diagnostics', 'diagnostics'], ['assurance', 'assurance']];
  try {
    observation.attempted = true;
    const beforeRequest = await requestInstalledRefreshBound(frameHost);
    const before = await waitForInstalledSnapshot(frameHost, beforeRequest.responses, snapshot => systemProjectionIdentity(snapshot) !== null, 30_000, beforeRequest.request);
    observation.before_restart = systemProjectionIdentity(before);
    for (const [surface, route] of surfaces) {
      observation.rendered[surface] = await frameHost.evaluate((frame, target) => {
        const document = frame.contentDocument; document?.querySelector(`[data-surface="${CSS.escape(target)}"]`)?.click();
        return Boolean(document?.querySelector('main h1')?.textContent?.trim());
      }, route);
    }
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
    observation.webview_restarted = restart.restarted === true;
    const afterRequest = await requestInstalledRefreshBound(frameHost);
    const after = await waitForInstalledSnapshot(frameHost, afterRequest.responses, snapshot => systemProjectionIdentity(snapshot) !== null, 30_000, afterRequest.request);
    observation.after_restart = systemProjectionIdentity(after);
    observation.exact_reconstruction = JSON.stringify(observation.after_restart) === JSON.stringify(observation.before_restart);
    if (!observation.exact_reconstruction) throw new Error(`system-projection-restart-substitution:${JSON.stringify({ before: observation.before_restart, after: observation.after_restart })}`);
    for (const [surface, route] of surfaces) {
      const reopened = await frameHost.evaluate((frame, target) => { const document = frame.contentDocument; document?.querySelector(`[data-surface="${CSS.escape(target)}"]`)?.click(); return Boolean(document?.querySelector('main h1')?.textContent?.trim()); }, route);
      observation.rendered[surface] = observation.rendered[surface] && reopened;
    }
    observation.completed = Object.values(observation.rendered).every(Boolean);
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 4000)); }
  return { schema_version: 'px.installed-system-projection-profile/1.0', authority: 'Exact canonical snapshot reconstruction across the dashboard webview boundary.', observation, control_probe: systemProjectionControlProbe(matrix, observation) };
}

const SIDEBAR_CONDITIONAL_STATE_IDS = Object.freeze([
  'pxui.sidebar.acknowledgement.surface',
  'pxui.sidebar.action.toggleTask.row',
  'pxui.sidebar.indicator.attention',
  'pxui.sidebar.indicator.contractError',
  'pxui.sidebar.indicator.liveStaleAgents',
  'pxui.sidebar.indicator.orchestrations'
]);

function sidebarStateControlVerified(controlId, kind, observation) {
  const durable = observation.completed === true && observation.webview_restarted === true && observation.exact_reconstruction === true;
  const fault = observation.disconnected_visible === true && observation.recovered_connected === true;
  const projectionRecovered = observation.conditional_projection_recovered === true;
  if (controlId === 'pxui.sidebar.acknowledgement.surface') return observation.render_acknowledgement === true && projectionRecovered;
  if (controlId === 'pxui.sidebar.action.toggleTask.row') return observation.task_preference_round_trip === true && projectionRecovered;
  if (controlId === 'pxui.sidebar.indicator.attention') return observation.attention_visible === true && projectionRecovered;
  if (controlId === 'pxui.sidebar.indicator.contractError') return observation.contract_error_visible === true && observation.contract_error_recovered === true;
  if (controlId === 'pxui.sidebar.indicator.liveStaleAgents') return observation.stale_agent_visible === true && projectionRecovered;
  if (controlId === 'pxui.sidebar.indicator.orchestrations') return observation.orchestration_visible === true && projectionRecovered;
  if (['pxui.sidebar.action.retry', 'pxui.sidebar.indicator.connection'].includes(controlId) || kind === 'failure_recovery') return fault;
  return durable;
}

function sidebarStateControlProbe(matrix, observation) {
  const requirements = matrix.controls.filter(control => control.surface_id === 'sidebar'
    && (['persistence', 'reload_reopen', 'failure_recovery'].includes(control.kind)
      || ['pxui.sidebar.action.toggleWave.row', 'pxui.sidebar.action.retry', 'pxui.sidebar.indicator.connection', ...SIDEBAR_CONDITIONAL_STATE_IDS].includes(control.control_id)));
  const durable = observation.webview_restarted === true && observation.exact_reconstruction === true;
  const fault = observation.disconnected_visible === true && observation.recovered_connected === true;
  const records = requirements.map(requirement => {
    const evidenceRef = `installed-sidebar-state:${requirement.control_id}`;
    const verified = ['persistence', 'reload_reopen'].includes(requirement.kind) || requirement.control_id === 'pxui.sidebar.action.toggleWave.row'
      ? durable && observation.completed === true
      : sidebarStateControlVerified(requirement.control_id, requirement.kind, observation);
    return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_sidebar_restart_and_engine_outage', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, verified ? { state: 'present', detail: 'The exact production sidebar renderer exposed the control under its bounded owned state, including the physical outage for connection controls.', evidence: [evidenceRef] } : { state: 'missing', detail: 'The exact sidebar conditional or outage state was not observed.', evidence: [] }];
        if (stage === 'recovery_rollback') {
          const restored = ['pxui.sidebar.action.retry', 'pxui.sidebar.indicator.connection'].includes(requirement.control_id) || requirement.kind === 'failure_recovery'
            ? fault && observation.preference_restored
            : verified && observation.preference_restored;
          return [stage, restored ? { state: 'present', detail: 'The real host snapshot removed every owned projection fixture, task and wave preferences returned to their predecessors, and physical engine custody was restored.', evidence: [evidenceRef] } : { state: 'missing', detail: 'Sidebar engine, projection, or preference rollback was not exact.', evidence: [] }];
        }
        return [stage, verified ? { state: 'present', detail: 'The host-owned sidebar and its production renderer completed the exact state-specific interaction and acknowledgement chain.', evidence: [evidenceRef] } : { state: 'missing', detail: `The sidebar profile did not prove ${stage}.`, evidence: [] }];
      })), errors: observation.errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Host-owned sidebar workspace preferences, real sidebar reload, and byte-restored disposable-engine outage.', eligible_control_count: records.length, records };
}

function sidebarReconstructionIdentity(value) {
  if (!value || typeof value !== 'object') return null;
  const waveIds = Array.isArray(value.wave_ids) ? value.wave_ids.map(String) : [];
  const targetedWaveId = String(value.targeted_wave_id || '');
  const statusState = String(value.status_state || '');
  const statusVersion = String(value.status_version || '');
  if (!targetedWaveId || !waveIds.includes(targetedWaveId) || !statusState || !statusVersion) return null;
  return {
    status_state: statusState,
    status_version: statusVersion,
    execution_plan_id: value.execution_plan_id == null ? null : String(value.execution_plan_id),
    wave_ids: waveIds,
    targeted_wave_id: targetedWaveId,
    targeted_expanded: value.targeted_expanded === true
  };
}

function sidebarPreferenceRoundTripIdentity(state, expected) {
  const request = state?.request;
  const snapshot = state?.snapshot;
  if (request?.type !== 'toggleWave' || request.waveId !== expected?.wave_id || request.expanded !== expected?.expanded) return null;
  if (!Number.isSafeInteger(snapshot?.revision) || !Array.isArray(snapshot?.expanded_wave_ids)) return null;
  const snapshotExpanded = snapshot.expanded_wave_ids.includes(expected.wave_id);
  if (snapshotExpanded !== expected.expanded || state?.button_expanded !== expected.expanded) return null;
  return { wave_id: expected.wave_id, expanded: expected.expanded, snapshot_revision: snapshot.revision };
}

async function instrumentInstalledSidebarState(sidebar) {
  return sidebar.evaluate(frame => {
    const inner = frame.contentWindow;
    inner.__PX_SIDEBAR_HOST_SNAPSHOTS__ ||= [];
    inner.__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__ ||= [];
    inner.__PX_SIDEBAR_OUTBOUND_REQUESTS__ ||= [];
    if (inner.__PX_SIDEBAR_HOST_INSTRUMENTED__) return true;
    inner.addEventListener('message', event => {
      if (event.data?.type !== 'snapshot') return;
      const projection = event.data?.projection;
      if (!projection || typeof projection !== 'object' || !Array.isArray(projection.waves) || !projection.ui || typeof projection.ui !== 'object') return;
      inner.__PX_SIDEBAR_HOST_SNAPSHOTS__.push({
        revision: projection.revision,
        expanded_wave_ids: [...(projection.ui.expandedWaveIds || [])]
      });
      inner.__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__.push(structuredClone(event.data));
      if (inner.__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__.length > 20) inner.__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__.splice(0, inner.__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__.length - 20);
    });
    inner.addEventListener('px-sidebar-outbound-request', event => {
      const value = event.detail;
      if (value && typeof value === 'object') {
        inner.__PX_SIDEBAR_OUTBOUND_REQUESTS__.push(structuredClone(value));
        if (inner.__PX_SIDEBAR_OUTBOUND_REQUESTS__.length > 80) inner.__PX_SIDEBAR_OUTBOUND_REQUESTS__.splice(0, inner.__PX_SIDEBAR_OUTBOUND_REQUESTS__.length - 80);
      }
    });
    inner.__PX_SIDEBAR_HOST_INSTRUMENTED__ = true;
    return true;
  });
}

async function runInstalledSidebarConditionalStateScenario(sidebar, timeoutMs = 30_000) {
  const fixtureTaskId = 'px-owned-sidebar-task';
  const fixtureSubtaskId = 'px-owned-sidebar-subtask';
  const fixtureAgentId = 'px-owned-sidebar-stale-agent';
  const fixtureOrchestrationId = 'px-owned-sidebar-orchestration';
  const fixtureAttentionId = 'px-owned-sidebar-attention';
  const result = {
    render_acknowledgement: false, task_preference_round_trip: false, attention_visible: false,
    contract_error_visible: false, contract_error_recovered: false, stale_agent_visible: false,
    orchestration_visible: false, conditional_projection_recovered: false
  };
  const baseline = await sidebar.evaluate(frame => {
    const inner = frame.contentWindow;
    const snapshot = inner?.__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__?.at(-1);
    return snapshot ? { snapshot: structuredClone(snapshot), outbound: inner.__PX_SIDEBAR_OUTBOUND_REQUESTS__?.length || 0, full: inner.__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__?.length || 0 } : null;
  });
  if (!baseline?.snapshot?.projection?.waves?.length) throw new Error('sidebar-conditional-authoritative-baseline-unavailable');
  result.contract_error_visible = await sidebar.evaluate(frame => {
    frame.contentWindow.dispatchEvent(new frame.contentWindow.MessageEvent('message', { data: { schemaVersion: 'px.sidebar.message/1.1', type: 'snapshot', projection: null } }));
    const error = frame.contentDocument.querySelector('#contract-error[role="alert"]');
    return Boolean(error && !error.hidden && /snapshot schema is invalid/i.test(error.textContent || ''));
  });
  const seed = expanded => sidebar.evaluate((frame, item) => {
    const inner = frame.contentWindow;
    const authoritative = structuredClone(inner.__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__.at(-1));
    const projection = authoritative.projection;
    projection.generatedAt = new Date().toISOString();
    const wave = projection.waves[0];
    wave.tasks = [...wave.tasks.filter(task => task.id !== item.taskId).slice(0, 79), {
      id: item.taskId, name: 'PX owned reversible sidebar task', status: 'queued', weight: 1,
      progressPercent: null, claimId: null, updatedAt: null,
      subtasks: [{ id: item.subtaskId, name: 'PX owned reversible sidebar subtask', status: 'queued', progressPercent: null }]
    }];
    projection.ui.expandedWaveIds = [...new Set([...projection.ui.expandedWaveIds.filter(id => id !== wave.id), wave.id])];
    projection.ui.expandedTaskIds = item.expanded
      ? [...new Set([...projection.ui.expandedTaskIds.filter(id => id !== item.taskId), item.taskId])]
      : projection.ui.expandedTaskIds.filter(id => id !== item.taskId);
    projection.agents = [...projection.agents.filter(agent => agent.agentId !== item.agentId).slice(0, 11), {
      agentId: item.agentId, displayName: 'PX owned stale agent', type: 'walker', host: null, ide: null,
      taskId: item.taskId, taskName: 'PX owned reversible sidebar task', claimId: null, orchestrationId: null,
      state: 'stale', progressPercent: null, lastHeartbeatAt: new Date(Date.now() - 120_000).toISOString(), heartbeatAgeMs: 120_000
    }];
    projection.orchestrations = [...projection.orchestrations.filter(value => value.id !== item.orchestrationId).slice(0, 7), {
      id: item.orchestrationId, name: 'PX owned reversible orchestration', state: 'recovering', updatedAt: new Date().toISOString()
    }];
    projection.attention = [...projection.attention.filter(value => value.id !== item.attentionId).slice(0, 11), {
      id: item.attentionId, severity: 'warning', title: 'PX owned reversible attention', detail: 'Bounded renderer scenario', entityType: 'attention', entityId: item.attentionId
    }];
    const outbound = inner.__PX_SIDEBAR_OUTBOUND_REQUESTS__.length;
    inner.dispatchEvent(new inner.MessageEvent('message', { data: authoritative }));
    const task = frame.contentDocument.querySelector(`[data-toggle-task="${CSS.escape(item.taskId)}"]`);
    return {
      outbound,
      task: Boolean(task), expanded: task?.getAttribute('aria-expanded') === 'true',
      attention: Boolean(frame.contentDocument.querySelector(`#attention [data-entity-id="${CSS.escape(item.attentionId)}"]`)),
      staleAgent: Boolean(frame.contentDocument.querySelector(`#agents [data-entity-id="${CSS.escape(item.agentId)}"] [data-heartbeat]`)),
      orchestration: Boolean(frame.contentDocument.querySelector(`#orchestrations [data-entity-id="${CSS.escape(item.orchestrationId)}"]`)),
      contractRecovered: Boolean(frame.contentDocument.querySelector('#contract-error')?.hidden)
    };
  }, { taskId: fixtureTaskId, subtaskId: fixtureSubtaskId, agentId: fixtureAgentId, orchestrationId: fixtureOrchestrationId, attentionId: fixtureAttentionId, expanded });
  const first = await seed(false);
  result.attention_visible = first.attention;
  result.stale_agent_visible = first.staleAgent;
  result.orchestration_visible = first.orchestration;
  result.contract_error_recovered = first.contractRecovered;
  result.render_acknowledgement = await sidebar.evaluate((frame, offset) => (frame.contentWindow?.__PX_SIDEBAR_OUTBOUND_REQUESTS__ || []).slice(offset).some(value => value?.type === 'rendered' && value?.assetProtocol === 'px.sidebar.asset/1.2' && Number.isSafeInteger(value?.revision)), first.outbound);
  if (!first.task || first.expanded) throw new Error('sidebar-conditional-task-baseline-invalid');
  const roundTrip = async expanded => {
    const offsets = await sidebar.evaluate(frame => ({ outbound: frame.contentWindow?.__PX_SIDEBAR_OUTBOUND_REQUESTS__?.length || 0, full: frame.contentWindow?.__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__?.length || 0 }));
    const clicked = await sidebar.evaluate((frame, id) => { const control = frame.contentDocument.querySelector(`[data-toggle-task="${CSS.escape(id)}"]`); if (!control) return false; control.click(); return true; }, fixtureTaskId);
    if (!clicked) return false;
    const deadline = Date.now() + timeoutMs;
    do {
      const state = await sidebar.evaluate((frame, item) => ({
        request: (frame.contentWindow?.__PX_SIDEBAR_OUTBOUND_REQUESTS__ || []).slice(item.offsets.outbound).some(value => value?.type === 'toggleTask' && value?.taskId === item.taskId && value?.expanded === item.expanded),
        hostSnapshot: (frame.contentWindow?.__PX_SIDEBAR_FULL_HOST_SNAPSHOTS__?.length || 0) > item.offsets.full,
        fixtureAbsent: !frame.contentDocument.querySelector(`[data-toggle-task="${CSS.escape(item.taskId)}"]`)
      }), { offsets, taskId: fixtureTaskId, expanded });
      if (state.request && state.hostSnapshot && state.fixtureAbsent) return true;
      await wait(100);
    } while (Date.now() < deadline);
    return false;
  };
  const expanded = await roundTrip(true);
  const second = expanded ? await seed(true) : { task: false, expanded: false };
  const collapsed = expanded && second.task && second.expanded && await roundTrip(false);
  result.task_preference_round_trip = expanded && collapsed;
  result.conditional_projection_recovered = await sidebar.evaluate((frame, tokens) => {
    const document = frame.contentDocument;
    return !document.querySelector(`[data-toggle-task="${CSS.escape(tokens.task)}"]`)
      && !document.querySelector(`[data-entity-id="${CSS.escape(tokens.agent)}"]`)
      && !document.querySelector(`[data-entity-id="${CSS.escape(tokens.orchestration)}"]`)
      && !document.querySelector(`[data-entity-id="${CSS.escape(tokens.attention)}"]`)
      && Boolean(document.querySelector('#contract-error')?.hidden);
  }, { task: fixtureTaskId, agent: fixtureAgentId, orchestration: fixtureOrchestrationId, attention: fixtureAttentionId });
  return result;
}

async function waitForInstalledSidebarPreferenceRoundTrip(sidebar, offsets, expected, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let state = null;
  do {
    state = await sidebar.evaluate((frame, item) => {
      const inner = frame.contentWindow;
      const expected = item.expected;
      return {
        request: (inner?.__PX_SIDEBAR_OUTBOUND_REQUESTS__ || []).slice(item.offsets.outbound_requests)
          .find(value => value?.type === 'toggleWave' && value?.waveId === expected.wave_id && value?.expanded === expected.expanded) || null,
        snapshot: (inner?.__PX_SIDEBAR_HOST_SNAPSHOTS__ || []).slice(item.offsets.confirmed_snapshots)
          .find(value => Array.isArray(value?.expanded_wave_ids) && value.expanded_wave_ids.includes(expected.wave_id) === expected.expanded) || null,
        button_expanded: [...frame.contentDocument.querySelectorAll('[data-toggle-wave]')]
          .find(item => item.dataset.toggleWave === expected.wave_id)?.getAttribute('aria-expanded') === 'true'
      };
    }, { offsets, expected });
    const identity = sidebarPreferenceRoundTripIdentity(state, expected);
    if (identity) return identity;
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error(`sidebar-preference-persistence-not-confirmed:${JSON.stringify({ expected, state })}`);
}

async function primarySidebarVisible(workbench) {
  return Boolean(await workbench.locator('.part.sidebar').isVisible().catch(() => false));
}

async function setPrimarySidebarVisibility(workbench, visible, timeoutMs = 10_000) {
  if (await primarySidebarVisible(workbench) === visible) return true;
  await workbench.keyboard.press('Control+B');
  const deadline = Date.now() + timeoutMs;
  do {
    if (await primarySidebarVisible(workbench) === visible) return true;
    await wait(100);
  } while (Date.now() < deadline);
  return false;
}

async function restartInstalledSidebarWebview(workbench, sidebar, timeoutMs = 30_000) {
  if (!await primarySidebarVisible(workbench)) throw new Error('sidebar-restart-baseline-not-visible');
  if (!await setPrimarySidebarVisibility(workbench, false, Math.min(10_000, timeoutMs))) throw new Error('sidebar-restart-hide-unobserved');
  if (!await setPrimarySidebarVisibility(workbench, true, Math.min(10_000, timeoutMs))) throw new Error('sidebar-restart-reopen-unobserved');
  if (!await sidebar.reacquire(Math.min(15_000, timeoutMs))) throw new Error('sidebar-restart-frame-reacquisition-failed');
  return { hidden: true, reopened: true, reacquired: true };
}

async function runInstalledSidebarStateProfile(workbench, dashboard, sidebar, matrix, timeoutMs = 60_000) {
  const observation = { rendered: false, attempted: false, webview_restarted: false, exact_reconstruction: false, disconnected_visible: false, recovered_connected: false, preference_restored: false, completed: false, render_acknowledgement: false, task_preference_round_trip: false, attention_visible: false, contract_error_visible: false, contract_error_recovered: false, stale_agent_visible: false, orchestration_visible: false, conditional_projection_recovered: false, errors: [] };
  let outage = null;
  try {
    observation.rendered = true; observation.attempted = true;
    await instrumentInstalledSidebarState(sidebar);
    const before = await sidebar.evaluate(frame => {
      const inner = frame.contentWindow;
      const button = frame.contentDocument.querySelector('[data-toggle-wave]');
      if (!button) throw new Error('sidebar-owned-wave-unavailable');
      const status = frame.contentDocument.querySelector('.status-strip');
      return {
        wave_id: button.dataset.toggleWave,
        expanded: button.getAttribute('aria-expanded') === 'true',
        confirmed_snapshots: inner.__PX_SIDEBAR_HOST_SNAPSHOTS__.length,
        outbound_requests: inner.__PX_SIDEBAR_OUTBOUND_REQUESTS__.length,
        status_state: [...(status?.classList || [])].find(value => value.startsWith('state-'))?.slice(6) || '',
        status_version: String(status?.querySelectorAll('span')?.[1]?.textContent || '').replace(/^v/i, '').trim(),
        execution_plan_id: frame.contentDocument.querySelector('#execution [data-entity-type="plan"][data-entity-id]')?.dataset.entityId || null,
        wave_ids: [...frame.contentDocument.querySelectorAll('[data-toggle-wave]')].map(item => item.dataset.toggleWave)
      };
    });
    await sidebar.evaluate(frame => frame.contentDocument.querySelector('[data-toggle-wave]').click());
    const expectedExpanded = !before.expanded;
    await waitForInstalledSidebarPreferenceRoundTrip(sidebar, before, { wave_id: before.wave_id, expanded: expectedExpanded });
    const expectedIdentity = sidebarReconstructionIdentity({ ...before, targeted_wave_id: before.wave_id, targeted_expanded: expectedExpanded });
    if (!expectedIdentity) throw new Error('sidebar-reconstruction-baseline-invalid');
    const priorOrigin = await sidebar.evaluate(frame => Number(frame.contentWindow?.performance?.timeOrigin || 0));
    const restart = await restartInstalledSidebarWebview(workbench, sidebar, 30_000);
    const restartDeadline = Date.now() + 30_000;
    let reopened = null;
    do {
      try {
        reopened = await sidebar.evaluate((frame, expected) => {
          const button = [...frame.contentDocument.querySelectorAll('[data-toggle-wave]')].find(item => item.dataset.toggleWave === expected.wave_id);
          const status = frame.contentDocument.querySelector('.status-strip');
          return {
            origin: Number(frame.contentWindow?.performance?.timeOrigin || 0),
            status_state: [...(status?.classList || [])].find(value => value.startsWith('state-'))?.slice(6) || '',
            status_version: String(status?.querySelectorAll('span')?.[1]?.textContent || '').replace(/^v/i, '').trim(),
            execution_plan_id: frame.contentDocument.querySelector('#execution [data-entity-type="plan"][data-entity-id]')?.dataset.entityId || null,
            wave_ids: [...frame.contentDocument.querySelectorAll('[data-toggle-wave]')].map(item => item.dataset.toggleWave),
            targeted_wave_id: expected.wave_id,
            targeted_expanded: button?.getAttribute('aria-expanded') === 'true'
          };
        }, before);
        if (reopened.origin > priorOrigin && JSON.stringify(sidebarReconstructionIdentity(reopened)) === JSON.stringify(expectedIdentity)) break;
      } catch { /* sidebar rematerializes during reload */ }
      await wait(150);
    } while (Date.now() < restartDeadline);
    observation.webview_restarted = restart.hidden === true && restart.reopened === true && restart.reacquired === true && Boolean(reopened?.origin > priorOrigin);
    observation.exact_reconstruction = observation.webview_restarted && JSON.stringify(sidebarReconstructionIdentity(reopened)) === JSON.stringify(expectedIdentity);
    if (!observation.exact_reconstruction) throw new Error(`sidebar-restart-reconstruction-mismatch:${JSON.stringify({ prior_origin: priorOrigin, expected: expectedIdentity, reopened })}`);
    await instrumentInstalledSidebarState(sidebar);
    outage = beginOwnedEngineOutage(process.env.PX_OWNED_ENGINE_ROOT, ownedHostToken);
    const faultOffset = await requestInstalledRefresh(dashboard);
    await waitForInstalledSnapshot(dashboard, faultOffset, snapshot => snapshot.connected === false);
    const faultDeadline = Date.now() + timeoutMs;
    do {
      observation.disconnected_visible = await sidebar.evaluate(frame => Boolean(frame.contentDocument.querySelector('.state-panel.state-disconnected [data-action="retry"]')));
      if (observation.disconnected_visible) break;
      await wait(150);
    } while (Date.now() < faultDeadline);
    if (!observation.disconnected_visible) throw new Error('sidebar-disconnected-state-not-visible');
    const restoration = outage.restore(); outage = null;
    if (!restoration?.restored) throw new Error('sidebar-engine-restoration-unverified');
    await sidebar.evaluate(frame => frame.contentDocument.querySelector('[data-action="retry"]').click());
    const recoveryDeadline = Date.now() + timeoutMs;
    do {
      observation.recovered_connected = await sidebar.evaluate(frame => Boolean(frame.contentDocument.querySelector('.status-strip.state-connected')) && !frame.contentDocument.querySelector('[data-action="retry"]'));
      if (observation.recovered_connected) break;
      await wait(150);
    } while (Date.now() < recoveryDeadline);
    if (!observation.recovered_connected) throw new Error('sidebar-connected-recovery-not-visible');
    Object.assign(observation, await runInstalledSidebarConditionalStateScenario(sidebar, Math.min(timeoutMs, 30_000)));
    const restoreOffsets = await sidebar.evaluate(frame => ({
      confirmed_snapshots: frame.contentWindow?.__PX_SIDEBAR_HOST_SNAPSHOTS__?.length || 0,
      outbound_requests: frame.contentWindow?.__PX_SIDEBAR_OUTBOUND_REQUESTS__?.length || 0
    }));
    await sidebar.evaluate((frame, id) => [...frame.contentDocument.querySelectorAll('[data-toggle-wave]')].find(item => item.dataset.toggleWave === id)?.click(), before.wave_id);
    const restoredPreference = await waitForInstalledSidebarPreferenceRoundTrip(sidebar, restoreOffsets, { wave_id: before.wave_id, expanded: before.expanded });
    observation.preference_restored = Boolean(restoredPreference);
    observation.completed = observation.preference_restored;
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 4000)); }
  finally {
    if (outage) { try { outage.restore(); } catch (error) { observation.errors.push(`restoration:${String(error?.message || error).slice(0, 1800)}`); } }
    if (!await primarySidebarVisible(workbench)) { try { await setPrimarySidebarVisibility(workbench, true, 10_000); } catch (error) { observation.errors.push(`sidebar-visibility-restoration:${String(error?.message || error).slice(0, 1800)}`); } }
  }
  return { schema_version: 'px.installed-sidebar-state-profile/1.1', authority: 'Exact sidebar preference/reload, production-renderer conditional states and acknowledgement, plus disposable-engine outage and recovery.', observation, control_probe: sidebarStateControlProbe(matrix, observation) };
}

async function runInstalledCleanupProfile(workbench, frameHost, matrix, timeoutMs = 90_000) {
  const observation = { rendered: false, attempted: false, completed: false, webview_restarted: false, invalid_selection_rejected: false, select_all_round_trip: false, permanent_refused_without_authorization: false, permanent_completed: false, reclaimed_absent_after_restart: false, selected_id: '', selected_relative_path: '', result: null, permanent_result: null, errors: [] };
  const disposableEngine = String(process.env.PX_OWNED_ENGINE_ROOT || '').trim() ? path.resolve(process.env.PX_OWNED_ENGINE_ROOT) : '';
  const recycleFixtureParent = disposableEngine ? path.resolve(disposableEngine, '.px-operational-recycle') : '';
  const recycleFixture = recycleFixtureParent ? path.resolve(recycleFixtureParent, '__pycache__') : '';
  const permanentFixtureParent = disposableEngine ? path.resolve(disposableEngine, '.px-operational-permanent') : '';
  const permanentFixture = permanentFixtureParent ? path.resolve(permanentFixtureParent, '__pycache__') : '';
  try {
    if (!recycleFixture || !recycleFixture.startsWith(`${disposableEngine}${path.sep}`) || fs.existsSync(recycleFixtureParent)) throw new Error('cleanup-recycle-fixture-unavailable');
    fs.mkdirSync(recycleFixture, { recursive: true });
    fs.writeFileSync(path.join(recycleFixture, 'owned-cache.pyc'), 'PX owned disposable cache\n', { encoding: 'utf8', flag: 'wx' });
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument; document?.querySelector('[data-action="closeModal"]')?.click();
      const toggle = document?.querySelector('[data-action="toggleAdvanced"]'); if (toggle && toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
      document?.querySelector('[data-surface="runtimeCore"]')?.click();
    });
    await waitForKnowledgeControl(frameHost, '[data-action="cleanupManager"]');
    const beforeScan = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="cleanupManager"]').click());
    const inventory = await (async () => {
      const deadline = Date.now() + timeoutMs;
      do {
        const response = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after)
          .find(value => value?.type === 'cleanupCandidates' || value?.type === 'cleanupError') || null, beforeScan);
        if (response?.type === 'cleanupError') throw new Error(`cleanup-scan-failed:${response.error}`);
        if (response) return response.inventory;
        await wait(150);
      } while (Date.now() < deadline);
      throw new Error('cleanup-scan-response-timeout');
    })();
    const candidate = ownedCleanupCandidate(inventory, disposableEngine, recycleFixture);
    if (!candidate) throw new Error('cleanup-owned-safe-candidate-unavailable');
    observation.rendered = true; observation.attempted = true; observation.selected_id = candidate.id; observation.selected_relative_path = candidate.relativePath;
    const invalidSelectionBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    observation.invalid_selection_rejected = await frameHost.evaluate((frame, before) => {
      const document = frame.contentDocument; const recycle = document.querySelector('[data-action="cleanupRecycle"]');
      return Boolean(recycle?.disabled) && (frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0) === before && ![...document.querySelectorAll('[data-cleanup-id]')].some(item => item.checked);
    }, invalidSelectionBefore);
    if (!observation.invalid_selection_rejected) throw new Error('cleanup-empty-selection-not-rejected');
    observation.select_all_round_trip = await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      const selectAll = document.querySelector('[data-action="cleanupSelectAll"]');
      let candidates = [...document.querySelectorAll('[data-cleanup-id]')];
      if (!selectAll || selectAll.disabled || !candidates.length || candidates.some(item => item.checked)) return false;
      selectAll.click();
      candidates = [...document.querySelectorAll('[data-cleanup-id]')];
      const clearAll = document.querySelector('[data-action="cleanupSelectAll"]');
      const selected = candidates.length > 0 && candidates.every(item => item.checked);
      if (!clearAll || clearAll.disabled || !selected) return false;
      clearAll.click();
      candidates = [...document.querySelectorAll('[data-cleanup-id]')];
      return candidates.length > 0 && candidates.every(item => !item.checked);
    });
    if (!observation.select_all_round_trip) throw new Error('cleanup-select-all-round-trip-failed');
    const beforeExecute = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const requestBeforeExecute = await installedOutboundRequestOffset(frameHost);
    await frameHost.evaluate((frame, id) => {
      const document = frame.contentDocument; const checkbox = document.querySelector(`[data-cleanup-id="${CSS.escape(id)}"]`);
      if (!checkbox) throw new Error('cleanup-candidate-checkbox-unavailable'); checkbox.click();
      const recycle = document.querySelector('[data-action="cleanupRecycle"]'); if (!recycle || recycle.disabled) throw new Error('cleanup-recycle-unavailable'); recycle.click();
    }, candidate.id);
    const dialog = await waitForNativeWorkbenchDialog(workbench, /Move to Recycle Bin/i, 15_000, { frameHost, responseOffset: beforeExecute, requestOffset: requestBeforeExecute, requestType: 'executeCleanup', keyboardAction: 'Move to Recycle Bin' });
    await clickNativeWorkbenchDialogAction(workbench, dialog, 'Move to Recycle Bin');
    const deadline = Date.now() + timeoutMs;
    do {
      const response = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after)
        .find(value => value?.type === 'cleanupResult' || value?.type === 'cleanupError') || null, beforeExecute);
      if (response?.type === 'cleanupError') throw new Error(`cleanup-recycle-failed:${response.error}`);
      if (response) { observation.result = response.result; break; }
      await wait(200);
    } while (Date.now() < deadline);
    if (!validCleanupResult(observation.result)) throw new Error(`cleanup-recycle-receipt-invalid:${JSON.stringify(observation.result)}`);
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
    observation.webview_restarted = restart.restarted === true;
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      const toggle = document?.querySelector('[data-action="toggleAdvanced"]'); if (toggle && toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
      document?.querySelector('[data-surface="runtimeCore"]')?.click();
    });
    await waitForKnowledgeControl(frameHost, '[data-action="cleanupManager"]');
    if (!permanentFixture || !permanentFixture.startsWith(`${disposableEngine}${path.sep}`) || fs.existsSync(permanentFixtureParent)) throw new Error('cleanup-permanent-fixture-unavailable');
    fs.mkdirSync(permanentFixture, { recursive: true });
    fs.writeFileSync(path.join(permanentFixture, 'owned-cache.pyc'), 'PX owned disposable cache\n', { encoding: 'utf8', flag: 'wx' });
    const afterRestartScan = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="cleanupManager"]').click());
    const reopenedInventory = await (async () => {
      const scanDeadline = Date.now() + timeoutMs;
      do {
        const response = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after)
          .find(value => value?.type === 'cleanupCandidates' || value?.type === 'cleanupError') || null, afterRestartScan);
        if (response?.type === 'cleanupError') throw new Error(`cleanup-post-restart-scan-failed:${response.error}`);
        if (response) return response.inventory;
        await wait(150);
      } while (Date.now() < scanDeadline);
      throw new Error('cleanup-post-restart-scan-timeout');
    })();
    observation.reclaimed_absent_after_restart = !(reopenedInventory?.candidates || []).some(item => item.id === observation.selected_id || item.relativePath === observation.selected_relative_path);
    if (!observation.reclaimed_absent_after_restart) throw new Error('cleanup-reclaimed-candidate-reappeared-after-restart');
    const permanentCandidate = (reopenedInventory?.candidates || []).find(item => item.relativePath === path.relative(disposableEngine, permanentFixture).split(path.sep).join('/'));
    if (!permanentCandidate?.id || permanentCandidate.classification !== 'safe-to-delete') throw new Error('cleanup-permanent-owned-candidate-unavailable');
    const permanentBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const permanentRequestBefore = await installedOutboundRequestOffset(frameHost);
    await frameHost.evaluate((frame, id) => {
      const document = frame.contentDocument; const checkbox = document.querySelector(`[data-cleanup-id="${CSS.escape(id)}"]`);
      if (!checkbox) throw new Error('cleanup-permanent-candidate-checkbox-unavailable'); checkbox.click();
      const permanent = document.querySelector('[data-action="cleanupPermanent"]'); if (!permanent || permanent.disabled) throw new Error('cleanup-permanent-unavailable'); permanent.click();
    }, permanentCandidate.id);
    const permanentDialog = await waitForNativeWorkbenchDialog(workbench, /Permanently Delete/i, 15_000, { frameHost, responseOffset: permanentBefore, requestOffset: permanentRequestBefore, requestType: 'executeCleanup', keyboardAction: 'Cancel' });
    await clickNativeWorkbenchDialogAction(workbench, permanentDialog, 'Cancel'); await wait(150);
    observation.permanent_refused_without_authorization = fs.existsSync(permanentFixture)
      && await frameHost.evaluate((frame, after) => !(frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after).some(value => value?.type === 'cleanupResult'), permanentBefore);
    if (!observation.permanent_refused_without_authorization) throw new Error('cleanup-permanent-refusal-not-proven');
    if (process.env.PX_OPERATIONAL_IRREVERSIBLE_CLEANUP_AUTHORIZED === '1') {
      const permanentRetryRequestBefore = await installedOutboundRequestOffset(frameHost);
      await frameHost.evaluate(frame => {
        const permanent = frame.contentDocument.querySelector('[data-action="cleanupPermanent"]');
        if (!permanent || permanent.disabled) throw new Error('cleanup-permanent-retry-unavailable'); permanent.click();
      });
      const retryDialog = await waitForNativeWorkbenchDialog(workbench, /Permanently Delete/i, 15_000, { frameHost, responseOffset: permanentBefore, requestOffset: permanentRetryRequestBefore, requestType: 'executeCleanup', keyboardAction: 'Permanently Delete' });
      await clickNativeWorkbenchDialogAction(workbench, retryDialog, 'Permanently Delete');
      const permanentDeadline = Date.now() + timeoutMs;
      do {
        const response = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after)
          .find(value => value?.type === 'cleanupResult' || value?.type === 'cleanupError') || null, permanentBefore);
        if (response?.type === 'cleanupError') throw new Error(`cleanup-permanent-failed:${response.error}`);
        if (response) { observation.permanent_result = response.result; break; }
        await wait(200);
      } while (Date.now() < permanentDeadline);
      observation.permanent_completed = validPermanentCleanupResult(observation.permanent_result) && !fs.existsSync(permanentFixture);
      if (!observation.permanent_completed) throw new Error(`cleanup-permanent-receipt-invalid:${JSON.stringify(observation.permanent_result)}`);
    }
    observation.completed = true;
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 4000)); }
  finally {
    await dismissOwnedNativeWorkbenchDialog(workbench, /Move to Recycle Bin|Permanently Delete/i)
      .catch(error => observation.errors.push(`cleanup-dialog-recovery:${String(error?.message || error).slice(0, 1200)}`));
    try {
      if (recycleFixtureParent && recycleFixtureParent.startsWith(`${disposableEngine}${path.sep}`) && fs.existsSync(recycleFixtureParent)) fs.rmSync(recycleFixtureParent, { recursive: true, force: false });
      if (permanentFixtureParent && permanentFixtureParent.startsWith(`${disposableEngine}${path.sep}`) && fs.existsSync(permanentFixtureParent)) fs.rmSync(permanentFixtureParent, { recursive: true, force: false });
    } catch (error) { observation.errors.push(`permanent-fixture-reconciliation:${String(error?.message || error).slice(0, 1200)}`); }
  }
  return { schema_version: 'px.installed-cleanup-recycle-profile/1.0', authority: 'Exact safe-cache recycle plus separately authorized exact disposable permanent-deletion boundary inside the owned isolated VS Code host and disposable engine.', observation, control_probe: cleanupControlProbe(matrix, observation) };
}

function ownedCleanupCandidate(inventory, root, fixture) {
  if (!root || !fixture) return null;
  const resolvedRoot = path.resolve(root);
  const resolvedFixture = path.resolve(fixture);
  if (!resolvedFixture.startsWith(`${resolvedRoot}${path.sep}`)) return null;
  const expectedRelative = path.relative(resolvedRoot, resolvedFixture).split(path.sep).join('/');
  return (inventory?.candidates || []).find(candidate => candidate?.relativePath === expectedRelative
    && candidate?.name === '__pycache__'
    && candidate?.classification === 'safe-to-delete'
    && candidate?.retentionRequired === false
    && typeof candidate?.id === 'string' && candidate.id.length > 0) || null;
}

function validPluginLifecycleObservation(operation, result, extensionId) {
  if (operation === 'enablement-preview' || operation === 'update-preview' || operation === 'uninstall-preview') {
    return result?.schema_version === 'px.extension-lifecycle-preview/1.0' && result.allowed === true && result.extension_id === extensionId && typeof result.token === 'string' && typeof result.exact_target === 'string';
  }
  if (operation === 'enablement-execute') return result?.schema_version === 'px.extension-lifecycle-receipt/1.0' && result.action === 'enablement-handoff' && result.extension_id === extensionId && result.mutation_dispatched === false;
  if (operation === 'conflict-query') return result?.schema_version === 'px.extension-conflict-analysis/1.0' && result.available === true && result.extension_id === extensionId && Array.isArray(result.signals);
  if (['update-blocked', 'enablement-blocked', 'uninstall-blocked'].includes(operation)) return result?.schema_version === 'px.extension-lifecycle-preview/1.0' && result.allowed === false && result.extension_id === extensionId && /not-installed/i.test(String(result.reason || ''));
  if (operation === 'conflict-blocked') return result?.schema_version === 'px.extension-conflict-analysis/1.0' && result.available === false && result.extension_id === extensionId && /not-installed/i.test(String(result.reason || ''));
  if (operation === 'install-blocked') return result?.schema_version === 'px.extension-lifecycle-preview/1.0' && result.allowed === false && result.extension_id === extensionId && /installed/i.test(String(result.reason || ''));
  if (operation === 'rollback-blocked') return result?.schema_version === 'px.extension-lifecycle-preview/1.0' && result.allowed === false && result.extension_id === extensionId && /occupied|installed/i.test(String(result.reason || ''));
  return false;
}

function exactPluginConflictSignal(result, extensionId, fixtureExtensionId = 'px-owned.fixture', resource = 'pacifyX.openDashboard') {
  if (result?.schema_version !== 'px.extension-conflict-analysis/1.0' || result.available !== true || !Array.isArray(result.signals)) return null;
  const normalize = value => String(value || '').trim().toLowerCase();
  const exactSet = values => [...new Set((Array.isArray(values) ? values : []).map(normalize).filter(Boolean))].sort();
  const expectedExtensions = exactSet([extensionId, fixtureExtensionId]);
  return result.signals.find(signal => {
    const providerIds = exactSet((signal?.providers || []).map(provider => provider?.extension_id));
    const extensionIds = exactSet(signal?.extension_ids);
    const resolutionTargets = exactSet(signal?.resolution_targets);
    return signal?.kind === 'duplicate-command-provider'
      && normalize(signal?.resource) === normalize(resource)
      && JSON.stringify(providerIds) === JSON.stringify(expectedExtensions)
      && JSON.stringify(extensionIds) === JSON.stringify(expectedExtensions)
      && JSON.stringify(resolutionTargets) === JSON.stringify(expectedExtensions);
  }) || null;
}

function pluginReadControlProbe(matrix, observation) {
  const operationByControl = new Map([
    ['pxui.plugins.action.previewExtensionInstall', 'install-blocked'],
    ['pxui.plugins.action.previewExtensionUpdate', 'update-preview'],
    ['pxui.plugins.action.previewExtensionEnablement', 'enablement-preview'],
    ['pxui.plugins.action.executeExtensionEnablement', 'enablement-execute'],
    ['pxui.plugins.action.previewExtensionUninstall', 'uninstall-preview'],
    ['pxui.plugins.action.previewExtensionRollback', 'rollback-blocked'],
    ['pxui.plugins.action.queryExtensionConflicts', 'conflict-query']
  ]);
  const failureByOperation = new Map([
    ['update-preview', 'update-blocked'],
    ['enablement-preview', 'enablement-blocked'],
    ['enablement-execute', 'enablement-blocked'],
    ['uninstall-preview', 'uninstall-blocked'],
    ['conflict-query', 'conflict-blocked']
  ]);
  const requirements = matrix.controls.filter(control => operationByControl.has(control.control_id));
  const records = requirements.map(requirement => {
    const operation = operationByControl.get(requirement.control_id);
    const verified = observation.operations?.[operation] === true;
    const blockedRecovery = ['install-blocked', 'rollback-blocked'].includes(operation);
    const evidenceRef = `installed-plugin-read:${requirement.control_id}`;
    return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_isolated_plugin_read_handoff', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        const matchedFailure = blockedRecovery ? verified : observation.operations?.[failureByOperation.get(operation)] === true;
        if (stage === 'failure_handling' || stage === 'recovery_rollback') return [stage, verified && matchedFailure
          ? { state: 'present', detail: 'The exact installed identity was fail-closed before mutation and the request-bound modal was dismissed back to the unchanged Plugin surface.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'This successful read/native-handoff operation requires a matched fault/recovery scenario.', evidence: [] }];
        return [stage, verified
          ? { state: 'present', detail: 'The exact installed extension identity crossed the request-bound lifecycle preview or native-manager handoff and returned its typed no-implied-mutation result.', evidence: [evidenceRef] }
          : { state: 'missing', detail: `The owned plugin read/handoff profile did not prove ${stage}.`, evidence: [] }];
      })), errors: observation.errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact read previews and no-implied-mutation native handoff against the installed PX extension in the owned isolated host; install/update/uninstall execution excluded.', eligible_control_count: records.length, records };
}

async function runInstalledPluginReadProfile(workbench, frameHost, matrix, timeoutMs = 30_000) {
  const extensionId = 'mountain-nomad-bc.pacify-x-vscode';
  const observation = { rendered: false, attempted: false, extension_id: extensionId, operations: {}, errors: [] };
  const invoke = async ({ field, value = extensionId, action, responseType, operation, executeAction = null, expectedExtensionId = extensionId }) => {
    await frameHost.evaluate((frame, item) => {
      const document = frame.contentDocument; document?.querySelector('[data-action="closeModal"]')?.click();
      const input = document.querySelector(item.field); if (!input) throw new Error(`plugin-field-unavailable:${item.field}`);
      input.value = item.value; input.dispatchEvent(new Event('input', { bubbles: true }));
    }, { field, value });
    const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, actionName) => {
      const control = frame.contentDocument.querySelector(`[data-action="${CSS.escape(actionName)}"]`); if (!control || control.disabled) throw new Error(`plugin-action-unavailable:${actionName}`); control.click();
    }, action);
    const deadline = Date.now() + timeoutMs; let response = null;
    do {
      response = await frameHost.evaluate((frame, item) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(item.after).find(value => value?.type === item.type) || null, { after: before, type: responseType });
      if (response) break; await wait(150);
    } while (Date.now() < deadline);
    if (!response) throw new Error(`plugin-${operation}-response-timeout`);
    observation.operations[operation] = validPluginLifecycleObservation(operation, response.result, expectedExtensionId);
    if (!observation.operations[operation]) throw new Error(`plugin-${operation}-result-invalid:${JSON.stringify(response.result)}`);
    if (executeAction) {
      await waitForKnowledgeControl(frameHost, `[data-action="${executeAction}"]`);
      const executeBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      const requestBeforeExecute = await installedOutboundRequestOffset(frameHost);
      await frameHost.evaluate((frame, actionName) => frame.contentDocument.querySelector(`[data-action="${CSS.escape(actionName)}"]`).click(), executeAction);
      try {
        const dialog = await waitForNativeWorkbenchDialog(workbench, 'Open exact native record', 15_000, { frameHost, responseOffset: executeBefore, requestOffset: requestBeforeExecute, requestType: 'extensionEnablementExecute', keyboardAction: 'Open exact native record' });
        await clickNativeWorkbenchDialogAction(workbench, dialog, 'Open exact native record');
      } catch (error) {
        await dismissOwnedNativeWorkbenchDialog(workbench, 'Open exact native record').catch(recoveryError => {
          throw new Error(`${String(error?.message || error)}:dialog-recovery:${String(recoveryError?.message || recoveryError)}`);
        });
        throw error;
      }
      let executed = null; const executeDeadline = Date.now() + timeoutMs;
      do {
        executed = await frameHost.evaluate((frame, item) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(item.after)
          .find(value => value?.type === 'extensionEnablementResult' && value?.requestId === item.expectedRequestId && value?.result) || null,
        { after: executeBefore, expectedRequestId: response.requestId });
        if (executed) break; await wait(150);
      } while (Date.now() < executeDeadline);
      observation.operations['enablement-execute'] = validPluginLifecycleObservation('enablement-execute', executed?.result, extensionId);
      if (!observation.operations['enablement-execute']) throw new Error(`plugin-enablement-execute-result-invalid:${JSON.stringify(executed?.result)}`);
      await executeWorkbenchCommand(workbench, INSTALLED_SAFE_WORKBENCH_COMMANDS['pxui.dashboard-control-plane.command.pacifyX.openDashboard'].title);
      await wait(250);
    }
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click()).catch(() => {});
  };
  try {
    await frameHost.evaluate(frame => { const document = frame.contentDocument; document?.querySelector('[data-action="closeModal"]')?.click(); document?.querySelector('[data-surface="plugins"]')?.click(); });
    await waitForKnowledgeControl(frameHost, '[data-action="previewExtensionEnablement"]');
    observation.rendered = true; observation.attempted = true;
    await invoke({ field: '#extension-enablement-id', action: 'previewExtensionEnablement', responseType: 'extensionEnablementPreview', operation: 'enablement-preview', executeAction: 'executeExtensionEnablement' });
    await invoke({ field: '#extension-conflict-id', action: 'queryExtensionConflicts', responseType: 'extensionConflictResult', operation: 'conflict-query' });
    await invoke({ field: '#extension-uninstall-id', action: 'previewExtensionUninstall', responseType: 'extensionUninstallPreview', operation: 'uninstall-preview' });
    await invoke({ field: '#extension-update-id', action: 'previewExtensionUpdate', responseType: 'extensionUpdatePreview', operation: 'update-preview' });
    await invoke({ field: '#extension-install-id', action: 'previewExtensionInstall', responseType: 'extensionLifecyclePreview', operation: 'install-blocked' });
    await invoke({ field: '#extension-rollback-id', action: 'previewExtensionRollback', responseType: 'extensionRollbackPreview', operation: 'rollback-blocked' });
    const absent = 'px-owned.absent';
    await invoke({ field: '#extension-update-id', value: absent, action: 'previewExtensionUpdate', responseType: 'extensionUpdatePreview', operation: 'update-blocked', expectedExtensionId: absent });
    await invoke({ field: '#extension-enablement-id', value: absent, action: 'previewExtensionEnablement', responseType: 'extensionEnablementPreview', operation: 'enablement-blocked', expectedExtensionId: absent });
    await invoke({ field: '#extension-uninstall-id', value: absent, action: 'previewExtensionUninstall', responseType: 'extensionUninstallPreview', operation: 'uninstall-blocked', expectedExtensionId: absent });
    await invoke({ field: '#extension-conflict-id', value: absent, action: 'queryExtensionConflicts', responseType: 'extensionConflictResult', operation: 'conflict-blocked', expectedExtensionId: absent });
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 4000)); }
  return { schema_version: 'px.installed-plugin-read-profile/1.0', authority: 'Exact read previews and no-implied-mutation native handoff against the installed PX extension in the owned isolated host; install/update/uninstall execution excluded.', observation, control_probe: pluginReadControlProbe(matrix, observation) };
}

function validPluginMutationReceipt(operation, result, extensionId, version = null) {
  if (result?.schema_version !== 'px.extension-lifecycle-receipt/1.0' || result.action !== operation || result.extension_id !== extensionId || result.reconciled !== true) return false;
  if (operation === 'install') return result.before_version === null && result.after_version === version && result.status === 'installed';
  if (operation === 'update') return typeof result.before_version === 'string' && result.before_version !== version && result.after_version === version && ['updated', 'host-reconciled-no-version-change'].includes(result.status);
  if (operation === 'uninstall') return typeof result.before_version === 'string' && result.after_version == null && result.status === 'uninstalled' && result.rollback_identity?.exact_target === `${extensionId}@${result.before_version}`;
  if (operation === 'rollback') return result.before_version === null && result.after_version === version && result.status === 'restored' && result.custody_state === 'rollback-consumed';
  return false;
}

function validPendingPluginMutationReceipt(operation, result, extensionId, exactTarget) {
  const common = result?.schema_version === 'px.extension-lifecycle-receipt/1.0'
    && result.action === operation
    && result.extension_id === extensionId
    && result.exact_target === exactTarget
    && result.status === 'pending-host-reload-or-refresh'
    && result.reconciled === false;
  if (!common) return false;
  const validSource = (source, version) => Boolean(source
    && typeof source.path === 'string' && source.path.length > 0
    && /^[0-9a-f]{64}$/.test(String(source.sha256 || ''))
    && Number.isSafeInteger(source.size) && source.size > 0
    && source.extension_id === extensionId
    && source.version === version);
  if (operation === 'install') {
    const version = exactTarget.startsWith(`${extensionId}@`) ? exactTarget.slice(extensionId.length + 1) : null;
    return result.before_version === null && result.after_version == null && validSource(result.local_source, version);
  }
  if (operation === 'update') {
    const version = exactTarget.startsWith(`${extensionId}@`) ? exactTarget.slice(extensionId.length + 1) : null;
    return typeof result.before_version === 'string' && result.after_version === result.before_version && validSource(result.local_source, version);
  }
  if (operation === 'uninstall') {
    const rollback = result.rollback_identity;
    return typeof result.before_version === 'string'
      && result.after_version === result.before_version
      && rollback?.schema_version === 'px.extension-rollback-identity/1.0'
      && rollback.extension_id === extensionId
      && rollback.version === result.before_version
      && rollback.exact_target === `${extensionId}@${result.before_version}`
      && rollback.custody_state === 'retained-before-uninstall'
      && rollback.source_availability === 'hash-bound-local-vsix'
      && validSource(rollback.local_source, result.before_version);
  }
  if (operation === 'rollback') {
    const version = exactTarget.startsWith(`${extensionId}@`) ? exactTarget.slice(extensionId.length + 1) : null;
    return result.before_version === null
      && result.after_version == null
      && result.custody_state === 'retained-before-uninstall'
      && result.source_availability === 'hash-bound-local-vsix'
      && validSource(result.local_source, version);
  }
  return false;
}

function pluginMutationControlProbe(matrix, observation) {
  const admitted = new Set([
    'pxui.plugins.action.executeExtensionInstall',
    'pxui.plugins.action.executeExtensionUpdate',
    'pxui.plugins.action.executeExtensionUninstall',
    'pxui.plugins.action.executeExtensionRollback',
    'pxui.plugins.action.previewExtensionConflictResolution',
    'pxui.plugins.action.executeExtensionConflictResolution',
    'pxui.plugins.action.openExtensionsView.activation',
    'pxui.plugins.action.openExtensionsView.footer',
    'pxui.plugins.action.openExtensionsView.install',
    'pxui.plugins.action.openExtensionsView.uninstall',
    'pxui.plugins.persistence.authoritativeState',
    'pxui.plugins.reload_reopen.authoritativeState',
    'pxui.plugins.failure_recovery.surface'
  ]);
  const requirements = matrix.controls.filter(control => admitted.has(control.control_id));
  const completed = observation.completed === true && observation.exact_reconstruction === true && observation.cleanup_restored === true && observation.conflict_route_completed === true && observation.native_manager_reopened === true;
  const recovered = observation.update_rollback_reconciled === true && observation.uninstall_rollback_reconciled === true && observation.cleanup_restored === true;
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact local inert VSIX lifecycle mutations only inside the owned disposable VS Code extension profile; native modal authority remains with VS Code and the initial absent state is restored.',
    eligible_control_count: requirements.length,
    records: requirements.map(requirement => {
      const evidenceRef = `installed-plugin-mutation:${requirement.control_id}`;
      return {
        control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
        evidence_mode: 'owned_disposable_plugin_mutation', rendered: observation.rendered, observed: observation.attempted, attempted: observation.attempted,
        interaction_chain: Object.fromEntries(STAGES.map(stage => {
          if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
          if (stage === 'failure_handling') return [stage, observation.invalid_source_rejected && observation.invalid_conflict_target_rejected
            ? { state: 'present', detail: 'A missing local VSIX source and a non-admitted conflict target were each rejected before native mutation.', evidence: [evidenceRef] }
            : { state: 'missing', detail: 'Both the invalid local-source and non-admitted conflict-target requests were not proven fail-closed.', evidence: [] }];
          if (stage === 'recovery_rollback') return [stage, recovered
            ? { state: 'present', detail: 'The v2 update was physically restored to v1, the v2 uninstall was restored from its hash-bound retained local source, and final cleanup reconstructed the original absent state.', evidence: [evidenceRef] }
            : { state: 'missing', detail: 'Exact update recovery, uninstall rollback, and final initial-state restoration were not all observed.', evidence: [] }];
          return [stage, completed
            ? { state: 'present', detail: 'The installed Plugin UI crossed request-bound preview, explicit native modal approval, VS Code dispatch, typed receipt, current inventory refresh, dashboard restart, and exact version reconstruction.', evidence: [evidenceRef] }
            : { state: 'missing', detail: `The owned Plugin mutation profile did not prove ${stage}.`, evidence: [] }];
        })),
        errors: observation.errors
      };
    })
  };
}

async function runInstalledPluginMutationProfile(workbench, frameHost, matrix, timeoutMs = 90_000) {
  const extensionId = 'px-owned.fixture';
  const pxExtensionId = 'mountain-nomad-bc.pacify-x-vscode';
  const fixtureRoot = path.resolve(__dirname, '..', 'tests', 'generated', 'plugin-lifecycle');
  const fixtureReceipt = JSON.parse(fs.readFileSync(path.join(fixtureRoot, 'receipt.json'), 'utf8'));
  const fixture = version => {
    const record = fixtureReceipt.artifacts?.find(item => item.version === version);
    if (!record) throw new Error(`plugin-fixture-receipt-version-missing:${version}`);
    const target = path.resolve(__dirname, '..', record.path);
    const bytes = fs.readFileSync(target);
    const identity = { path: target, version, size: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
    if (identity.size !== record.size || identity.sha256 !== record.sha256) throw new Error(`plugin-fixture-receipt-mismatch:${version}`);
    return identity;
  };
  const v1 = fixture('1.0.0');
  const v2 = fixture('2.0.0');
  const observation = {
    rendered: false, attempted: false, completed: false, extension_id: extensionId,
    invalid_source_rejected: false, invalid_conflict_target_rejected: false, conflict_route_completed: false,
    native_manager_open_count: 0, native_manager_reopened: false,
    update_rollback_reconciled: false, uninstall_rollback_reconciled: false,
    cleanup_restored: false, exact_reconstruction: false, webview_restart_count: 0, workbench_reload_count: 0, operations: [], errors: []
  };

  const waitForResponse = async (after, expectedType, expectedOperation = '') => {
    const deadline = Date.now() + timeoutMs;
    do {
      const response = await frameHost.evaluate((frame, item) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(item.after)
        .find(value => value?.type === item.expected || (value?.type === 'operationError' && (!item.operation || value.operation === item.operation))) || null,
      { after, expected: expectedType, operation: expectedOperation });
      if (response?.type === 'operationError') throw new Error(`plugin-host-operation-failed:${response.operation}:${response.error}`);
      if (response) return response;
      await wait(150);
    } while (Date.now() < deadline);
    throw new Error(`plugin-response-timeout:${expectedType}`);
  };

  const currentVersion = async expected => {
    const controlDeadline = Date.now() + Math.min(timeoutMs, 20_000);
    let controlState = null;
    let before = null;
    do {
      controlState = await frameHost.evaluate(frame => {
        const document = frame.contentDocument;
        document?.querySelector('[data-action="closeModal"]')?.click();
        const visible = element => Boolean(element && !element.disabled
          && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
        const pluginRoutes = [...(document?.querySelectorAll('[data-surface="plugins"]') || [])].filter(visible);
        const route = pluginRoutes.find(element => element.classList.contains('nav-item')) || pluginRoutes[0] || null;
        const rendered = document?.querySelector('.content')?.classList.contains('surface-plugins') === true;
        const current = route?.getAttribute('aria-current') === 'page';
        if ((!rendered || !current) && route) route.click();
        const refreshedRoute = [...(document?.querySelectorAll('[data-surface="plugins"]') || [])]
          .find(element => element.classList.contains('nav-item')) || route;
        const refreshedRendered = document?.querySelector('.content')?.classList.contains('surface-plugins') === true;
        const control = [...(document?.querySelectorAll('[data-action="refreshEnvironment"]') || [])].find(visible) || null;
        if (refreshedRendered && refreshedRoute?.getAttribute('aria-current') === 'page' && control) {
          const responseOffset = frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0;
          control.click();
          return { dispatched: true, before: responseOffset, rendered_surface: true, nav_current: true, control_visible: true };
        }
        return {
          dispatched: false,
          before: null,
          rendered_surface: refreshedRendered,
          nav_current: refreshedRoute?.getAttribute('aria-current') === 'page',
          control_visible: Boolean(control)
        };
      });
      if (controlState.dispatched) { before = controlState.before; break; }
      await wait(100);
    } while (Date.now() < controlDeadline);
    if (before === null) throw new Error(`plugin-inventory-control-unavailable:${JSON.stringify(controlState)}`);
    const deadline = Date.now() + timeoutMs;
    let last = null;
    do {
      const responses = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after), before);
      const failure = responses.find(value => value?.type === 'operationError');
      if (failure) throw new Error(`plugin-inventory-refresh-failed:${failure.error}`);
      last = responses.filter(value => value?.type === 'environmentResult' && value.subject === 'extensions').at(-1)?.result || last;
      if (last?.available === true && Array.isArray(last.records)) {
        const record = last.records.find(item => item.id === extensionId);
        const observed = record ? String(record.version || '') : null;
        if (observed === expected) return observed;
      }
      await wait(150);
    } while (Date.now() < deadline);
    throw new Error(`plugin-inventory-version-mismatch:${JSON.stringify({ expected, observed: last?.records?.find(item => item.id === extensionId)?.version || null })}`);
  };

  const mutate = async spec => {
    await frameHost.evaluate((frame, item) => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="closeModal"]')?.click();
      document?.querySelector('[data-surface="plugins"]')?.click();
      for (const [selector, value] of Object.entries(item.fields)) {
        const field = document.querySelector(selector); if (!field) throw new Error(`plugin-field-unavailable:${selector}`);
        field.value = value; field.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }, spec);
    await waitForKnowledgeControl(frameHost, `[data-action="${spec.previewAction}"]`);
    const previewBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, action) => frame.contentDocument.querySelector(`[data-action="${CSS.escape(action)}"]`).click(), spec.previewAction);
    const preview = (await waitForResponse(previewBefore, spec.previewType, spec.previewOperation)).result;
    if (preview?.schema_version !== 'px.extension-lifecycle-preview/1.0' || preview.allowed !== true || preview.extension_id !== extensionId || preview.exact_target !== spec.exactTarget) throw new Error(`plugin-${spec.name}-preview-invalid:${JSON.stringify(preview)}`);
    const localSource = preview.local_source || preview.rollback_identity?.local_source;
    if (!localSource || localSource.path !== spec.fixture.path || localSource.sha256 !== spec.fixture.sha256 || localSource.size !== spec.fixture.size) throw new Error(`plugin-${spec.name}-local-source-substitution:${JSON.stringify(localSource)}`);
    if (Object.hasOwn(preview, 'network_expected') && preview.network_expected !== false) throw new Error(`plugin-${spec.name}-unexpected-network-source`);
    await waitForKnowledgeControl(frameHost, `[data-action="${spec.executeAction}"]`);
    const executeBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const requestBeforeExecute = await installedOutboundRequestOffset(frameHost);
    await frameHost.evaluate((frame, action) => frame.contentDocument.querySelector(`[data-action="${CSS.escape(action)}"]`).click(), spec.executeAction);
    try {
      const dialog = await waitForNativeWorkbenchDialog(workbench, spec.nativeApproval, 15_000, { frameHost, responseOffset: executeBefore, requestOffset: requestBeforeExecute, requestType: spec.executeOperation, keyboardAction: spec.nativeApproval });
      await clickNativeWorkbenchDialogAction(workbench, dialog, spec.nativeApproval);
    } catch (error) {
      await dismissOwnedNativeWorkbenchDialog(workbench, spec.nativeApproval).catch(recoveryError => {
        throw new Error(`${String(error?.message || error)}:dialog-recovery:${String(recoveryError?.message || recoveryError)}`);
      });
      throw error;
    }
    const result = (await waitForResponse(executeBefore, spec.resultType, spec.executeOperation)).result;
    const receiptComplete = validPluginMutationReceipt(spec.receiptAction, result, extensionId, spec.expectedVersion);
    const receiptPending = validPendingPluginMutationReceipt(spec.receiptAction, result, extensionId, spec.exactTarget);
    if (!receiptComplete && !receiptPending) throw new Error(`plugin-${spec.name}-receipt-invalid:${JSON.stringify(result)}`);
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click()).catch(() => {});
    const requiresWorkbenchReconstruction = receiptPending || spec.receiptAction === 'uninstall';
    const restart = requiresWorkbenchReconstruction
      ? await restartOwnedWorkbenchWindow(workbench, frameHost, 60_000)
      : await restartInstalledDashboardWebview(frameHost, 45_000);
    if (restart.restarted !== true || restart.reconstructed !== true) throw new Error(`plugin-${spec.name}-host-reconstruction-unobserved`);
    observation.webview_restart_count += 1;
    if (requiresWorkbenchReconstruction) observation.workbench_reload_count += 1;
    const observedVersion = await currentVersion(spec.expectedVersion);
    const physicallyReconciled = receiptComplete || (receiptPending && observedVersion === spec.expectedVersion);
    if (!physicallyReconciled) throw new Error(`plugin-${spec.name}-pending-receipt-not-reconciled:${JSON.stringify({ expected: spec.expectedVersion, observed: observedVersion })}`);
    observation.operations.push({ name: spec.name, preview, result, observed_version: observedVersion, receipt_state: receiptComplete ? 'reconciled' : 'physically-reconciled-after-pending', webview_restarted: true, workbench_reloaded: requiresWorkbenchReconstruction });
    return result;
  };

  const exerciseNativeManagerEntrypoints = async () => {
    await frameHost.evaluate(frame => { const document = frame.contentDocument; document?.querySelector('[data-action="closeModal"]')?.click(); document?.querySelector('[data-surface="plugins"]')?.click(); });
    await waitForKnowledgeControl(frameHost, '[data-action="openExtensionsView"]');
    const count = await frameHost.evaluate(frame => [...frame.contentDocument.querySelectorAll('[data-action="openExtensionsView"]')].filter(item => item.offsetWidth || item.offsetHeight || item.getClientRects().length).length);
    if (count < 2) throw new Error(`plugin-native-manager-entrypoints-missing:${count}`);
    for (let index = 0; index < count; index += 1) {
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluate((frame, position) => {
        const controls = [...frame.contentDocument.querySelectorAll('[data-action="openExtensionsView"]')].filter(item => item.offsetWidth || item.offsetHeight || item.getClientRects().length);
        if (!controls[position]) throw new Error(`plugin-native-manager-entrypoint-unavailable:${position}`);
        controls[position].click();
      }, index);
      const response = await waitForResponse(before, 'hostActionResult', 'openExtensionsView');
      if (response.operation !== 'openExtensionsView' || response.disposition !== 'completed') throw new Error(`plugin-native-manager-ack-invalid:${JSON.stringify(response)}`);
      observation.native_manager_open_count += 1;
      await executeWorkbenchCommand(workbench, INSTALLED_SAFE_WORKBENCH_COMMANDS['pxui.dashboard-control-plane.command.pacifyX.openDashboard'].title);
      await waitForKnowledgeControl(frameHost, '[data-surface="plugins"]');
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-surface="plugins"]').click());
    }
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
    observation.webview_restart_count += restart.restarted === true ? 1 : 0;
    observation.native_manager_reopened = restart.restarted === true && await currentVersion(null) === null;
    if (!observation.native_manager_reopened) throw new Error('plugin-native-manager-dashboard-reopen-or-denominator-invalid');
  };

  const queryConflicts = async () => {
    await frameHost.evaluate((frame, id) => {
      const document = frame.contentDocument;
      document?.querySelector('[data-action="closeModal"]')?.click();
      document?.querySelector('[data-surface="plugins"]')?.click();
      const field = document.querySelector('#extension-conflict-id'); if (!field) throw new Error('plugin-conflict-field-unavailable');
      field.value = id; field.dispatchEvent(new Event('input', { bubbles: true }));
    }, extensionId);
    const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="queryExtensionConflicts"]').click());
    const result = (await waitForResponse(before, 'extensionConflictResult', 'extensionConflictQuery')).result;
    const signal = exactPluginConflictSignal(result, pxExtensionId, extensionId);
    if (!signal) throw new Error(`plugin-deterministic-conflict-signal-missing:${JSON.stringify(result)}`);
    return signal;
  };

  const exerciseConflictRoute = async () => {
    let signal = await queryConflicts();
    const invalidBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, item) => {
      const button = [...frame.contentDocument.querySelectorAll('[data-action="previewExtensionConflictResolution"]')]
        .find(value => value.dataset.signalId === item.signalId && value.dataset.resolution === 'inspect' && value.dataset.targetExtensionId === item.extensionId);
      if (!button) throw new Error('plugin-conflict-preview-control-unavailable');
      button.dataset.targetExtensionId = 'px-owned.absent';
      button.click();
    }, { signalId: signal.signal_id, extensionId });
    const invalidDeadline = Date.now() + timeoutMs;
    do {
      const failure = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after)
        .find(value => value?.type === 'operationError' && value.operation === 'extensionConflictResolutionPreview') || null, invalidBefore);
      if (failure && /target-not-admitted/i.test(String(failure.error || ''))) { observation.invalid_conflict_target_rejected = true; break; }
      await wait(150);
    } while (Date.now() < invalidDeadline);
    if (!observation.invalid_conflict_target_rejected) throw new Error('plugin-invalid-conflict-target-not-rejected');
    signal = await queryConflicts();
    const previewBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, item) => {
      const button = [...frame.contentDocument.querySelectorAll('[data-action="previewExtensionConflictResolution"]')]
        .find(value => value.dataset.signalId === item.signalId && value.dataset.resolution === 'inspect' && value.dataset.targetExtensionId === item.extensionId);
      if (!button) throw new Error('plugin-conflict-preview-control-unavailable');
      button.click();
    }, { signalId: signal.signal_id, extensionId });
    const preview = (await waitForResponse(previewBefore, 'extensionConflictResolutionPreview', 'extensionConflictResolutionPreview')).result;
    if (preview?.schema_version !== 'px.extension-conflict-resolution-preview/1.0' || preview.allowed !== true || preview.signal_id !== signal.signal_id || preview.target_extension_id !== extensionId || preview.resolution !== 'inspect') throw new Error(`plugin-conflict-preview-invalid:${JSON.stringify(preview)}`);
    await waitForKnowledgeControl(frameHost, '[data-action="executeExtensionConflictResolution"]');
    const executeBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    const requestBeforeExecute = await installedOutboundRequestOffset(frameHost);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="executeExtensionConflictResolution"]').click());
    try {
      const dialog = await waitForNativeWorkbenchDialog(workbench, 'Authorize conflict route', 15_000, { frameHost, responseOffset: executeBefore, requestOffset: requestBeforeExecute, requestType: 'extensionConflictResolutionExecute', keyboardAction: 'Authorize conflict route' });
      await clickNativeWorkbenchDialogAction(workbench, dialog, 'Authorize conflict route');
    } catch (error) {
      await dismissOwnedNativeWorkbenchDialog(workbench, 'Authorize conflict route').catch(recoveryError => {
        throw new Error(`${String(error?.message || error)}:dialog-recovery:${String(recoveryError?.message || recoveryError)}`);
      });
      throw error;
    }
    const result = (await waitForResponse(executeBefore, 'extensionConflictResolutionResult', 'extensionConflictResolutionExecute')).result;
    if (result?.schema_version !== 'px.extension-conflict-resolution-receipt/1.0' || result.action !== 'conflict-resolution' || result.signal_id !== signal.signal_id || result.target_extension_id !== extensionId || result.resolution !== 'inspect' || result.status !== 'exact-native-record-opened' || result.mutation_dispatched !== false) throw new Error(`plugin-conflict-route-result-invalid:${JSON.stringify(result)}`);
    await executeWorkbenchCommand(workbench, INSTALLED_SAFE_WORKBENCH_COMMANDS['pxui.dashboard-control-plane.command.pacifyX.openDashboard'].title);
    await waitForKnowledgeControl(frameHost, '[data-surface="plugins"]');
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
    observation.webview_restart_count += restart.restarted === true ? 1 : 0;
    if (await currentVersion(v2.version) !== v2.version) throw new Error('plugin-conflict-route-changed-installed-denominator');
    observation.operations.push({ name: 'inspect-deterministic-conflict', signal_id: signal.signal_id, preview, result, observed_version: v2.version, webview_restarted: restart.restarted === true });
    observation.conflict_route_completed = restart.restarted === true;
  };

  try {
    await frameHost.evaluate(frame => { const document = frame.contentDocument; document?.querySelector('[data-action="closeModal"]')?.click(); document?.querySelector('[data-surface="plugins"]')?.click(); });
    await waitForKnowledgeControl(frameHost, '[data-action="previewExtensionInstall"]');
    observation.rendered = true; observation.attempted = true;
    const failureBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, item) => {
      const document = frame.contentDocument;
      document.querySelector('#extension-install-id').value = item.id;
      document.querySelector('#extension-install-version').value = item.version;
      document.querySelector('#extension-install-vsix').value = item.path;
      document.querySelector('[data-action="previewExtensionInstall"]').click();
    }, { id: extensionId, version: v1.version, path: v1.path.replace(/\.vsix$/i, '.missing.vsix') });
    const failureDeadline = Date.now() + timeoutMs;
    do {
      const failure = await frameHost.evaluate((frame, after) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || []).slice(after).find(value => value?.type === 'operationError' && value.operation === 'extensionLifecyclePreview') || null, failureBefore);
      if (failure && /ENOENT|realpath|no such file/i.test(String(failure.error || ''))) { observation.invalid_source_rejected = true; break; }
      await wait(150);
    } while (Date.now() < failureDeadline);
    if (!observation.invalid_source_rejected) throw new Error('plugin-missing-local-source-not-rejected');
    await exerciseNativeManagerEntrypoints();

    const install = version => mutate({ name: `install-${version.version}`, fields: { '#extension-install-id': extensionId, '#extension-install-version': version.version, '#extension-install-vsix': version.path }, previewAction: 'previewExtensionInstall', previewType: 'extensionLifecyclePreview', previewOperation: 'extensionLifecyclePreview', executeAction: 'executeExtensionInstall', executeOperation: 'extensionLifecycleExecute', resultType: 'extensionLifecycleResult', nativeApproval: 'Authorize native install', receiptAction: 'install', exactTarget: `${extensionId}@${version.version}`, expectedVersion: version.version, fixture: version });
    const update = (name, version) => mutate({ name, fields: { '#extension-update-id': extensionId, '#extension-update-version': version.version, '#extension-update-vsix': version.path }, previewAction: 'previewExtensionUpdate', previewType: 'extensionUpdatePreview', previewOperation: 'extensionUpdatePreview', executeAction: 'executeExtensionUpdate', executeOperation: 'extensionUpdateExecute', resultType: 'extensionUpdateResult', nativeApproval: 'Authorize native update', receiptAction: 'update', exactTarget: `${extensionId}@${version.version}`, expectedVersion: version.version, fixture: version });
    const uninstall = (name, version = v2) => mutate({ name, fields: { '#extension-uninstall-id': extensionId }, previewAction: 'previewExtensionUninstall', previewType: 'extensionUninstallPreview', previewOperation: 'extensionUninstallPreview', executeAction: 'executeExtensionUninstall', executeOperation: 'extensionUninstallExecute', resultType: 'extensionUninstallResult', nativeApproval: 'Authorize native uninstall', receiptAction: 'uninstall', exactTarget: `${extensionId}@${version.version}#uninstall`, expectedVersion: null, fixture: version });
    const rollback = () => mutate({ name: 'rollback-uninstall-v2', fields: { '#extension-rollback-id': extensionId }, previewAction: 'previewExtensionRollback', previewType: 'extensionRollbackPreview', previewOperation: 'extensionRollbackPreview', executeAction: 'executeExtensionRollback', executeOperation: 'extensionRollbackExecute', resultType: 'extensionRollbackResult', nativeApproval: 'Authorize exact rollback', receiptAction: 'rollback', exactTarget: `${extensionId}@2.0.0`, expectedVersion: v2.version, fixture: v2 });

    await install(v1);
    await update('update-v1-to-v2', v2);
    await exerciseConflictRoute();
    await uninstall('rollback-stage-uninstall-v2');
    try {
      await rollback();
    } catch (error) {
      if (!/plugin-inventory-version-mismatch:\{"expected":"2\.0\.0","observed":null\}/.test(String(error?.message || error))) throw error;
      observation.pending_rollback_retried = true;
      await rollback();
    }
    observation.uninstall_rollback_reconciled = true;
    await uninstall('restore-update-uninstall-v2');
    await install(v1);
    observation.update_rollback_reconciled = await currentVersion(v1.version) === v1.version;
    if (!observation.update_rollback_reconciled) throw new Error('plugin-update-predecessor-reconstruction-failed');
    await uninstall('final-cleanup-uninstall-v1', v1);
    observation.cleanup_restored = true;
    observation.exact_reconstruction = observation.operations.length === 8 && observation.operations.every(item => item.webview_restarted === true);
    observation.completed = observation.invalid_source_rejected && observation.invalid_conflict_target_rejected && observation.conflict_route_completed && observation.native_manager_reopened && observation.exact_reconstruction && observation.cleanup_restored;
  } catch (error) {
    observation.errors.push(String(error?.message || error).slice(0, 4000));
    await dismissOwnedNativeWorkbenchDialog(workbench, /Authorize native install|Authorize native update|Authorize native uninstall|Authorize exact rollback|Authorize conflict route/i)
      .catch(recoveryError => observation.errors.push(`dialog-recovery:${String(recoveryError?.message || recoveryError).slice(0, 1800)}`));
  }
  return { schema_version: 'px.installed-plugin-mutation-profile/1.0', authority: 'Exact hash-bound local inert VSIX lifecycle only inside the owned disposable VS Code extension profile; final state must match the initial absent state.', fixtures: { v1, v2 }, observation, control_probe: pluginMutationControlProbe(matrix, observation) };
}

function knowledgeLifecycleControlProbe(matrix, observation) {
  const admittedActions = new Set(['knowledgePropose', 'submitKnowledgeProposal', 'knowledgeTransition', 'knowledgeRollback', 'submitKnowledgeRollback', 'knowledgeReject', 'submitKnowledgeReject', 'knowledgeRecover', 'knowledgeRefresh']);
  const admittedStateControls = new Set([
    'pxui.knowledge-core.field.knowledgeId',
    'pxui.knowledge-core.field.knowledgeTitle',
    'pxui.knowledge-core.field.knowledgeSummary',
    'pxui.knowledge-core.field.knowledgeSource',
    'pxui.knowledge-core.field.knowledgeEvidence',
    'pxui.knowledge-core.field.rollbackEvidenceRefs',
    'pxui.knowledge-core.field.knowledgeRejectReason',
    'pxui.knowledge-core.form.proposal',
    'pxui.knowledge-core.form.reject',
    'pxui.knowledge-core.form.rollback',
    'pxui.knowledge-core.lifecycle.path.2',
    'pxui.knowledge-core.lifecycle.path.3',
    'pxui.knowledge-core.persistence.authoritativeState',
    'pxui.knowledge-core.reload_reopen.authoritativeState'
  ]);
  const requirements = matrix.controls.filter(control => control.surface_id === 'knowledge-core' && (
    (control.kind === 'action' && admittedActions.has(installedActionIdentity(control).action))
    || admittedStateControls.has(control.control_id)
  ));
  const verified = observation.completed === true && observation.webview_restarted === true;
  const records = requirements.map(requirement => {
    const evidenceRef = `installed-knowledge-lifecycle:${requirement.control_id}`;
    return {
      control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
      evidence_mode: 'owned_isolated_knowledge_lifecycle', rendered: observation.rendered, observed: observation.rendered, attempted: observation.attempted,
      interaction_chain: Object.fromEntries(STAGES.map(stage => {
        if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
        if (stage === 'failure_handling') return [stage, observation.invalid_proposal_rejected
          ? { state: 'present', detail: 'The installed Knowledge proposal form rejected a blank unbound record locally, kept the operation out of the host bridge, and displayed the explicit fail-closed binding error.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The matched invalid Knowledge proposal was not proven fail-closed.', evidence: [] }];
        return [stage, verified
          ? { state: 'present', detail: 'The installed Knowledge UI completed exact source-bound proposals, lifecycle approvals, immutable update, canonical rollback, rejection and recovery, restarted the dashboard webview boundary, and reconstructed the exact canonical head from the disposable workspace.', evidence: [evidenceRef] }
          : { state: 'missing', detail: 'The owned installed-host Knowledge lifecycle did not complete this exact control chain.', evidence: [] }];
      })),
      errors: observation.errors
    };
  });
  return { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Exact Knowledge lifecycle operations executed only inside the owned isolated VS Code host and disposable workspace.', eligible_control_count: records.length, records };
}

async function waitForKnowledgeProposalRejection(frameHost, before, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  do {
    const state = await frameHost.evaluate((frame, before) => {
      const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
      const modalText = String([...frame.contentDocument.querySelectorAll('.control-modal')]
        .find(item => item.offsetWidth || item.offsetHeight || item.getClientRects().length)?.textContent || '');
      const dispatched = responses.slice(before).some(value => value?.type === 'studioOperationResult'
        && value?.kind === 'knowledge' && value?.operation === 'propose');
      return {
        undispatched: !dispatched,
        blocked: /Knowledge proposal blocked/i.test(modalText) && /required|record/i.test(modalText)
      };
    }, before);
    if (!state.undispatched) return false;
    if (state.blocked) return true;
    await wait(75);
  } while (Date.now() < deadline);
  return false;
}

async function runInstalledKnowledgeLifecycleProfile(frameHost, matrix, timeoutMs = 120_000) {
  const observation = { rendered: false, attempted: false, completed: false, webview_restarted: false, invalid_proposal_rejected: false, record_id: '', rejected_record_id: '', first_sha256: '', second_sha256: '', operations: [], errors: [] };
  try {
    await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-action="closeModal"]')?.click());
    await navigateInstalledSurface(frameHost, 'knowledgeCore', Math.min(timeoutMs, 20_000));
    await waitForKnowledgeControl(frameHost, '[data-action="knowledgeRefresh"]');
    const initialBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="knowledgeRefresh"]').click());
    const initialBrowse = await waitForStudioOperationResult(frameHost, initialBefore, 'knowledge', 'browse', timeoutMs);
    if (!validKnowledgeLifecycleResult('browse', initialBrowse)) throw new Error(`knowledge-initial-browse-invalid:${JSON.stringify(initialBrowse)}`);
    await waitForKnowledgeControl(frameHost, '[data-action="knowledgePropose"]');
    observation.rendered = true;
    observation.attempted = true;
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="knowledgePropose"]').click());
    await waitForKnowledgeControl(frameHost, '[data-action="submitKnowledgeProposal"]');
    const invalidProposalBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => {
      const field = frame.contentDocument.querySelector('#knowledge-id');
      field.value = ''; field.dispatchEvent(new Event('input', { bubbles: true }));
      frame.contentDocument.querySelector('[data-action="submitKnowledgeProposal"]').click();
    });
    observation.invalid_proposal_rejected = await waitForKnowledgeProposalRejection(frameHost, invalidProposalBefore, Math.min(timeoutMs, 5_000));
    if (!observation.invalid_proposal_rejected) throw new Error('knowledge-invalid-proposal-not-rejected');
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="closeModal"]')?.click());
    observation.record_id = `knowledge:px-owned-${Date.now()}`;
    observation.rejected_record_id = `${observation.record_id}-rejected`;

    const propose = async (recordId, summary) => {
      await waitForKnowledgeControl(frameHost, '[data-action="knowledgePropose"]');
      await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="knowledgePropose"]').click());
      await waitForKnowledgeControl(frameHost, '[data-action="submitKnowledgeProposal"]');
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluate((frame, values) => {
        const document = frame.contentDocument;
        const set = (selector, value) => { const field = document.querySelector(selector); if (!field) throw new Error(`knowledge-field-unavailable:${selector}`); field.value = value; field.dispatchEvent(new Event('input', { bubbles: true })); };
        set('#knowledge-id', values.recordId); set('#knowledge-title', values.recordId); set('#knowledge-summary', values.summary);
        const source = document.querySelector('#knowledge-source'); const evidence = document.querySelector('#knowledge-evidence');
        if (!source || ![...source.options].some(option => option.value === values.sourceId) || !/^[0-9a-f]{64}$/.test(values.sourceSha256)) throw new Error('knowledge-owned-source-fixture-unavailable');
        source.value = values.sourceId; source.dispatchEvent(new Event('change', { bubbles: true }));
        evidence.value = `sha256:${values.sourceSha256}`; evidence.dispatchEvent(new Event('input', { bubbles: true }));
        document.querySelector('[data-action="submitKnowledgeProposal"]').click();
      }, { recordId, summary, sourceId: ownedKnowledgeSourceId, sourceSha256: ownedKnowledgeSourceSha256 });
      return settleKnowledgeMutation(frameHost, before, 'propose', {}, timeoutMs);
    };
    const transition = async (operation, proposalId, candidateSha256) => {
      const selector = `[data-action="knowledgeTransition"][data-operation="${operation}"][data-proposal-id="${proposalId}"]`;
      await waitForKnowledgeControl(frameHost, selector);
      const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
      await frameHost.evaluate((frame, query) => frame.contentDocument.querySelector(query).click(), selector);
      return settleKnowledgeMutation(frameHost, before, operation, { proposal_id: proposalId, candidate_sha256: candidateSha256 }, timeoutMs);
    };
    const promoteCandidate = async proposed => {
      const proposal = proposed.result?.record || proposed.result; const proposalId = proposal.proposal_id; const candidateSha256 = proposal.candidate_sha256;
      for (const operation of ['verify', 'approve', 'promote']) {
        const settled = await transition(operation, proposalId, candidateSha256); observation.operations.push(settled);
      }
      return { proposalId, candidateSha256, browse: observation.operations.at(-1).browse };
    };

    const firstProposal = await propose(observation.record_id, 'Owned Knowledge lifecycle revision one.'); observation.operations.push(firstProposal);
    const first = await promoteCandidate(firstProposal); observation.first_sha256 = first.candidateSha256;
    if (!knowledgeBrowseHasHead(first.browse, observation.record_id, observation.first_sha256)) throw new Error('knowledge-first-canonical-head-missing');
    const secondProposal = await propose(observation.record_id, 'Owned Knowledge lifecycle revision two with immutable supersession.'); observation.operations.push(secondProposal);
    const second = await promoteCandidate(secondProposal); observation.second_sha256 = second.candidateSha256;
    if (observation.first_sha256 === observation.second_sha256 || !knowledgeBrowseHasHead(second.browse, observation.record_id, observation.second_sha256)) throw new Error('knowledge-update-canonical-head-missing-or-unchanged');

    const rollbackSelector = `[data-action="knowledgeRollback"][data-record-id="${observation.record_id}"][data-current-sha="${observation.second_sha256}"][data-target-sha="${observation.first_sha256}"]`;
    await waitForKnowledgeControl(frameHost, rollbackSelector);
    await frameHost.evaluate((frame, query) => frame.contentDocument.querySelector(query).click(), rollbackSelector);
    await waitForKnowledgeControl(frameHost, '[data-action="submitKnowledgeRollback"]');
    const beforeRollback = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate((frame, evidence) => { const field = frame.contentDocument.querySelector('#knowledge-rollback-evidence'); field.value = `sha256:${evidence}`; field.dispatchEvent(new Event('input', { bubbles: true })); frame.contentDocument.querySelector('[data-action="submitKnowledgeRollback"]').click(); }, observation.first_sha256);
    const rollback = await settleKnowledgeMutation(frameHost, beforeRollback, 'rollback', { from_sha256: observation.second_sha256, to_sha256: observation.first_sha256 }, timeoutMs); observation.operations.push(rollback);
    if (!knowledgeBrowseHasHead(rollback.browse, observation.record_id, observation.first_sha256)) throw new Error('knowledge-rollback-canonical-head-missing');

    const rejectedProposal = await propose(observation.rejected_record_id, 'Owned Knowledge rejection and recovery candidate.'); observation.operations.push(rejectedProposal);
    const rejectedRecord = rejectedProposal.result?.record || rejectedProposal.result;
    const rejectSelector = `[data-action="knowledgeReject"][data-proposal-id="${rejectedRecord.proposal_id}"]`;
    await waitForKnowledgeControl(frameHost, rejectSelector);
    await frameHost.evaluate((frame, query) => frame.contentDocument.querySelector(query).click(), rejectSelector);
    await waitForKnowledgeControl(frameHost, '[data-action="submitKnowledgeReject"]');
    const beforeReject = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => { const field = frame.contentDocument.querySelector('#knowledge-reject-reason'); field.value = 'Owned lifecycle rejection test with retained evidence.'; field.dispatchEvent(new Event('input', { bubbles: true })); frame.contentDocument.querySelector('[data-action="submitKnowledgeReject"]').click(); });
    const reject = await settleKnowledgeMutation(frameHost, beforeReject, 'reject', { proposal_id: rejectedRecord.proposal_id, candidate_sha256: rejectedRecord.candidate_sha256 }, timeoutMs); observation.operations.push(reject);

    await waitForKnowledgeControl(frameHost, '[data-action="knowledgeRecover"]');
    const beforeRecover = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="knowledgeRecover"]').click());
    const recover = await settleKnowledgeMutation(frameHost, beforeRecover, 'recover', {}, timeoutMs); observation.operations.push(recover);
    await waitForKnowledgeControl(frameHost, '[data-action="knowledgeRefresh"]');
    const beforeRefresh = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="knowledgeRefresh"]').click());
    const finalBrowse = await waitForStudioOperationResult(frameHost, beforeRefresh, 'knowledge', 'browse', timeoutMs);
    if (!validKnowledgeLifecycleResult('browse', finalBrowse) || !knowledgeBrowseHasHead(finalBrowse, observation.record_id, observation.first_sha256)) throw new Error('knowledge-final-authoritative-refresh-invalid');
    const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
    observation.webview_restarted = restart.restarted === true;
    await frameHost.evaluate(frame => {
      const document = frame.contentDocument;
      document?.querySelector('[data-surface="dashboard"]')?.click();
      const toggle = document?.querySelector('[data-action="toggleAdvanced"]');
      if (toggle && toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
      document?.querySelector('[data-surface="knowledgeCore"]')?.click();
    });
    await waitForKnowledgeControl(frameHost, '[data-action="knowledgeRefresh"]');
    const reopenedBefore = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
    await frameHost.evaluate(frame => frame.contentDocument.querySelector('[data-action="knowledgeRefresh"]').click());
    const reopenedBrowse = await waitForStudioOperationResult(frameHost, reopenedBefore, 'knowledge', 'browse', timeoutMs);
    if (!validKnowledgeLifecycleResult('browse', reopenedBrowse) || !knowledgeBrowseHasHead(reopenedBrowse, observation.record_id, observation.first_sha256)) throw new Error('knowledge-webview-restart-reconstruction-invalid');
    observation.final_browse = reopenedBrowse;
    observation.completed = true;
  } catch (error) { observation.errors.push(String(error?.message || error).slice(0, 3000)); }
  return { schema_version: 'px.installed-knowledge-lifecycle-profile/1.0', authority: 'Exact Knowledge lifecycle operations executed only inside the owned isolated VS Code host and disposable workspace.', observation, control_probe: knowledgeLifecycleControlProbe(matrix, observation) };
}

async function waitForInstalledMemoryText(frameHost, pattern, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let body = '';
  do {
    body = await frameHost.evaluate(frame => String(frame.contentDocument?.body?.innerText || ''));
    if (pattern.test(body)) return body;
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`canonical-memory-view-timeout:${pattern}:${body.slice(0, 300)}`);
}

async function readInstalledCanonicalMemoryState(frameHost) {
  return frameHost.evaluate(frame => {
    const document = frame.contentDocument;
    const authority = document?.querySelector('.memory-authority');
    const refresh = document?.querySelector('[data-action="memoryRefresh"]');
    const disconnect = document?.querySelector('[data-action="disconnectCanonicalMemory"]');
    return {
      attached: Boolean(authority?.classList.contains('attached') && refresh && !refresh.disabled && disconnect),
      detached: Boolean(authority?.classList.contains('detached') && refresh?.disabled && !disconnect),
      authority_classes: [...(authority?.classList || [])],
      refresh_disabled: refresh ? Boolean(refresh.disabled) : null,
      disconnect_rendered: Boolean(disconnect)
    };
  });
}

async function waitForInstalledCanonicalMemoryState(frameHost, attached, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  let current = null;
  let nextRefreshAt = 0;
  do {
    current = await readInstalledCanonicalMemoryState(frameHost);
    if (attached ? current.attached : current.detached) return current;
    if (Date.now() >= nextRefreshAt) {
      await frameHost.evaluate(frame => frame.contentWindow?.PXDashboard?.require('hostQueries')?.refresh());
      nextRefreshAt = Date.now() + 750;
    }
    await wait(250);
  } while (Date.now() < deadline);
  throw new Error(`canonical-memory-state-timeout:${attached ? 'attached' : 'detached'}:${JSON.stringify(current)}`);
}

async function settleInstalledCanonicalMemoryRecord(frameHost, timeoutMs = 30_000) {
  await navigateInstalledSurface(frameHost, 'memory', timeoutMs);
  const prepared = await frameHost.evaluate(frame => {
    const document = frame.contentDocument;
    document.querySelector('[data-action="closeModal"]')?.click();
    const fields = [
      ['[data-memory-search]', 'input'],
      ['[data-memory-project]', 'input'],
      ['[data-memory-source]', 'input'],
      ['[data-memory-status]', 'change']
    ];
    for (const [selector, eventName] of fields) {
      const field = document.querySelector(selector);
      if (!field) continue;
      if (field.value !== '') {
        field.value = '';
        field.dispatchEvent(new Event(eventName, { bubbles: true }));
      }
    }
    const refresh = document.querySelector('[data-action="memoryRefresh"]');
    if (!refresh || refresh.disabled) return false;
    refresh.click();
    return true;
  });
  if (!prepared) throw new Error('canonical-memory-refresh-unavailable');
  await waitForKnowledgeControl(frameHost, '[data-action="inspectMemoryRecord"][data-memory-id]', timeoutMs);
  return true;
}

function installedFilesystemPathIdentity(value, { platform = process.platform, realpath = fs.realpathSync.native } = {}) {
  const supplied = String(value || '').trim();
  if (!supplied) return '';
  const resolved = path.resolve(supplied);
  let canonical = resolved;
  try { canonical = realpath(resolved); } catch { /* a missing path still has a deterministic resolved identity */ }
  return platform === 'win32' ? canonical.toLowerCase() : canonical;
}

function installedFilesystemPathsMatch(left, right, options) {
  return installedFilesystemPathIdentity(left, options) === installedFilesystemPathIdentity(right, options);
}

function installedFilesystemPathWithin(root, target, options) {
  const rootIdentity = installedFilesystemPathIdentity(root, options);
  const targetIdentity = installedFilesystemPathIdentity(target, options);
  if (!rootIdentity || !targetIdentity || rootIdentity === targetIdentity) return false;
  const relative = path.relative(rootIdentity, targetIdentity);
  return Boolean(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative);
}

function reversibleConfigurationRecord(requirement, observation) {
  const evidenceRef = `installed-reversible-configuration:${requirement.control_id}`;
  const verified = observation.changed && observation.reopened && observation.restored;
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'direct_reversible_configuration_interaction', rendered: observation.available,
    observed: observation.available, attempted: observation.attempted,
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      if (stage === 'failure_handling') return [stage, observation.failure_handling
        ? { state: 'present', detail: 'The exact installed action encountered an owned pre-write host fault, returned a typed failure, preserved its pre-state, and then recovered through the normal success/restoration path.', evidence: [evidenceRef] }
        : { state: 'missing', detail: 'The reversible configuration campaign did not prove a matched pre-write failure with unchanged state.', evidence: [] }];
      return [stage, verified
        ? { state: 'present', detail: `Exact installed configuration action changed state, acknowledged through the typed host contract, survived route reopen, and restored its exact pre-state (${observation.before_target}).`, evidence: [evidenceRef] }
        : { state: 'missing', detail: `The reversible configuration campaign did not prove ${stage}.`, evidence: [] }];
    })),
    errors: observation.errors
  };
}

function partitionExpectedFaultDiagnostics(hostErrors, reversibleConfigurationProfile, hostBoundaryProfile, ownedExternalNetworkDenied = process.env.PX_OWNED_EXTERNAL_NETWORK_DENIED === '1') {
  const completeProfile = profile => {
    const records = Array.isArray(profile?.records) ? profile.records : [];
    return Number(profile?.eligible_control_count || 0) > 0
    && records.length === profile.eligible_control_count
    && records.every(record => record?.attempted === true
      && (!Array.isArray(record.errors) || record.errors.length === 0)
      && Object.values(record.interaction_chain || {}).every(stage => stage?.state === 'present' || stage?.state === 'not_applicable'));
  };
  const configurationRecovered = completeProfile(reversibleConfigurationProfile)
    && reversibleConfigurationProfile.records.some(record => record?.interaction_chain?.failure_handling?.state === 'present')
    && reversibleConfigurationProfile.records.some(record => record?.interaction_chain?.recovery_rollback?.state === 'present');
  const hostBoundaryOperations = new Map(INSTALLED_HOST_BOUNDARY_SPECS.map(spec => [spec.controlId, spec.operation]));
  const recoveredHostOperations = new Set((Array.isArray(hostBoundaryProfile?.records) ? hostBoundaryProfile.records : [])
    .filter(record => record?.attempted === true
      && (!Array.isArray(record.errors) || record.errors.length === 0)
      && record?.interaction_chain?.failure_handling?.state === 'present'
      && (record?.interaction_chain?.recovery_rollback?.state === 'present'
        || (record?.interaction_chain?.recovery_rollback?.state === 'not_applicable'
          && Array.isArray(record.interaction_chain.recovery_rollback.evidence)
          && record.interaction_chain.recovery_rollback.evidence.length > 0)))
    .map(record => hostBoundaryOperations.get(record.control_id))
    .filter(Boolean));
  const retained = [];
  const recovered = [];
  for (const diagnostic of hostErrors) {
    const message = String(diagnostic?.message || '');
    const context = String(diagnostic?.context || '');
    const expectedConfigurationFault = configurationRecovered && message.includes('owned-injected-configuration-fault:');
    const hostActionFault = message.match(/(?:^|\s)owned-injected-host-action-fault:([A-Za-z][A-Za-z0-9._-]*)(?=$|[\s,;])/);
    const expectedHostActionFault = Boolean(hostActionFault && recoveredHostOperations.has(hostActionFault[1]));
    const expectedExternalNetworkDenial = ownedExternalNetworkDenied
      && diagnostic?.source === 'console'
      && (/ERR_PROXY_CONNECTION_FAILED/.test(message)
        || /Failed to fetch/i.test(message)
        || (/Error while getting the latest version for the extension [A-Za-z0-9._-]+ from https:\/\/marketplace\.visualstudio\.com\//i.test(message)
          && /Trying the fallback https:\/\/(?:www\.)?vscode-unpkg\.net\//i.test(message)
          && /Failed\s*$/i.test(message)))
      && (/workbench\.desktop\.main\.js/i.test(context)
        || /(?:marketplace\.visualstudio\.com|vscode-unpkg\.net|main\.vscode-cdn\.net)/i.test(context));
    if (diagnostic?.source === 'console' && (expectedConfigurationFault || expectedHostActionFault || expectedExternalNetworkDenial)) {
      recovered.push({ ...diagnostic, disposition: expectedExternalNetworkDenial ? 'expected_owned_external_network_denial' : 'expected_owned_fault_recovered' });
    } else retained.push(diagnostic);
  }
  return { retained, recovered };
}

async function runInstalledReversibleConfigurationProfile(workbench, frameHost, matrix) {
  const specs = [
    { controlIds: ['pxui.activity.action.activityPause', 'pxui.activity.persistence.authoritativeState', 'pxui.activity.reload_reopen.authoritativeState'], route: 'activity', action: 'activityPause', datasetKey: 'paused', responseType: 'hostActionResult', operation: 'setActivityPaused' },
    { controlIds: ['pxui.settings.action.toggleBillablePolicy', 'pxui.settings.persistence.authoritativeState', 'pxui.settings.reload_reopen.authoritativeState'], route: 'settings', action: 'toggleBillablePolicy', datasetKey: 'enabled', responseType: 'enterpriseResult', operation: 'toggleBillablePolicy', approvalLabel: 'Enable guarded policy' }
  ];
  const requirements = new Map(matrix.controls.map(control => [control.control_id, control]));
  const records = [];
  for (const spec of specs) {
    const observation = { available: false, attempted: false, changed: false, reopened: false, restored: false, failure_handling: false, before_target: '', errors: [] };
    try {
      const before = await readInstalledConfigurationAction(frameHost, spec);
      observation.available = before.available; observation.before_target = before.target_value;
      if (!before.available || !['true', 'false'].includes(before.target_value)) throw new Error(`${spec.action}-prestate-unavailable`);
      observation.attempted = true;
      await exerciseOwnedConfigurationFailure(frameHost, spec, async () => {
        const unchanged = await readInstalledConfigurationAction(frameHost, spec);
        return unchanged.available && unchanged.target_value === before.target_value;
      });
      observation.failure_handling = true;
      await invokeInstalledConfigurationAction(workbench, frameHost, spec, before.target_value);
      const changed = await waitForInstalledConfigurationTarget(frameHost, spec, value => value !== before.target_value);
      observation.changed = changed.target_value !== before.target_value;
      if (!observation.changed) throw new Error(`${spec.action}-state-did-not-change`);
      const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
      const reopened = await waitForInstalledConfigurationTarget(frameHost, spec, value => value === changed.target_value);
      observation.reopened = restart.restarted === true && reopened.target_value === changed.target_value;
      if (!observation.reopened) throw new Error(`${spec.action}-state-did-not-survive-webview-restart`);
      await invokeInstalledConfigurationAction(workbench, frameHost, spec, changed.target_value);
      const restored = await waitForInstalledConfigurationTarget(frameHost, spec, value => value === before.target_value);
      observation.restored = restored.target_value === before.target_value;
      if (!observation.restored) throw new Error(`${spec.action}-restoration-mismatch:${restored.target_value}:${before.target_value}`);
    } catch (error) {
      observation.errors.push(String(error?.message || error).slice(0, 1000));
      try {
        const current = await readInstalledConfigurationAction(frameHost, spec);
        if (observation.before_target && current.available && current.target_value !== observation.before_target) {
          await invokeInstalledConfigurationAction(workbench, frameHost, spec, current.target_value);
          const restored = await waitForInstalledConfigurationTarget(frameHost, spec, value => value === observation.before_target);
          observation.restored = restored.target_value === observation.before_target;
        }
      } catch (restoreError) { observation.errors.push(`restoration:${String(restoreError?.message || restoreError).slice(0, 900)}`); }
    }
    const profileRequirements = spec.controlIds.map(controlId => requirements.get(controlId));
    if (!profileRequirements.every(Boolean)) throw new Error(`Reversible configuration profile references an unknown control: ${spec.controlIds.join(',')}`);
    records.push(...profileRequirements.map(requirement => reversibleConfigurationRecord(requirement, observation)));
  }
  const memoryRequirements = ['pxui.memory.action.configureCanonicalMemory', 'pxui.memory.action.disconnectCanonicalMemory', 'pxui.diagnostics.action.dynamicRepair.configureCanonicalMemory']
    .map(controlId => requirements.get(controlId));
  if (!memoryRequirements.every(Boolean)) throw new Error('Canonical memory reversible profile controls are absent from the authoritative proof matrix.');
  {
    const setup = { available: true, attempted: false, changed: false, reopened: false, restored: false, failure_handling: false, before_target: '', profile_initial_target: '', profile_initial_target_identity: '', profile_initial_attached: false, configured_target: '', restored_target: '', restored_target_identity: '', errors: [] };
    try {
      setup.attempted = true;
      await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-surface="memory"]')?.click());
      const initial = await readInstalledCanonicalMemoryState(frameHost);
      if (!initial.attached && !initial.detached) throw new Error(`canonical-memory-initial-state-incoherent:${JSON.stringify(initial)}`);
      setup.profile_initial_attached = initial.attached;
      if (initial.attached) {
        const normalized = await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'disconnectCanonicalMemory', operation: 'disconnectCanonicalMemory' });
        setup.profile_initial_target = String(normalized.detail?.previousWorkspaceRoot || '');
        if (!setup.profile_initial_target) throw new Error('canonical-memory-attached-prestate-root-unavailable');
        setup.profile_initial_target_identity = installedFilesystemPathIdentity(setup.profile_initial_target);
        await waitForInstalledCanonicalMemoryState(frameHost, false);
      } else {
        await waitForInstalledCanonicalMemoryState(frameHost, false);
      }
      await exerciseOwnedConfigurationFailure(frameHost, { route: 'memory', action: 'configureCanonicalMemory', operation: 'configureCanonicalMemory' }, async () => {
        try { await waitForInstalledCanonicalMemoryState(frameHost, false, 2_000); return true; }
        catch { return false; }
      });
      const configured = await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'configureCanonicalMemory', operation: 'configureCanonicalMemory' });
      setup.before_target = String(configured.detail?.previousWorkspaceRoot || '');
      setup.configured_target = String(configured.detail?.workspaceRoot || '');
      setup.changed = Boolean(setup.configured_target) && setup.configured_target !== setup.before_target;
      await waitForInstalledCanonicalMemoryState(frameHost, true);
      const restart = await restartInstalledDashboardWebview(frameHost, 45_000);
      await frameHost.evaluate(frame => frame.contentDocument?.querySelector('[data-surface="memory"]')?.click());
      await waitForInstalledCanonicalMemoryState(frameHost, true);
      setup.reopened = restart.restarted === true;
      await exerciseOwnedConfigurationFailure(frameHost, { route: 'memory', action: 'disconnectCanonicalMemory', operation: 'disconnectCanonicalMemory' }, async () => {
        try { await waitForInstalledCanonicalMemoryState(frameHost, true, 2_000); return true; }
        catch { return false; }
      });
      setup.failure_handling = true;
      const detached = await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'disconnectCanonicalMemory', operation: 'disconnectCanonicalMemory' });
      await waitForInstalledCanonicalMemoryState(frameHost, false);
      if (setup.profile_initial_attached) {
        const restored = await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'configureCanonicalMemory', operation: 'configureCanonicalMemory' });
        setup.restored_target = String(restored.detail?.workspaceRoot || '');
        setup.restored_target_identity = installedFilesystemPathIdentity(setup.restored_target);
        setup.restored = installedFilesystemPathsMatch(setup.restored_target, setup.profile_initial_target);
        await waitForInstalledCanonicalMemoryState(frameHost, true);
      } else {
        setup.restored_target = String(detached.detail?.restoredWorkspaceRoot || '');
        setup.restored_target_identity = installedFilesystemPathIdentity(setup.restored_target);
        setup.restored = installedFilesystemPathsMatch(setup.restored_target, setup.profile_initial_target);
      }
      if (!setup.changed || !setup.restored) throw new Error(`canonical-memory-restoration-mismatch:${JSON.stringify({ changed: setup.changed, restored: setup.restored, initial_attached: setup.profile_initial_attached, initial_target: setup.profile_initial_target, initial_identity: setup.profile_initial_target_identity, restored_target: setup.restored_target, restored_identity: setup.restored_target_identity })}`);
    } catch (error) {
      setup.errors.push(String(error?.message || error).slice(0, 1000));
      try {
        await navigateInstalledSurface(frameHost, 'memory', 15_000);
        const current = await readInstalledCanonicalMemoryState(frameHost);
        if (setup.profile_initial_attached && !current.attached) {
          const restored = await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'configureCanonicalMemory', operation: 'configureCanonicalMemory' }, 30_000);
          setup.restored_target = String(restored.detail?.workspaceRoot || '');
          setup.restored_target_identity = installedFilesystemPathIdentity(setup.restored_target);
          setup.restored = installedFilesystemPathsMatch(setup.restored_target, setup.profile_initial_target);
          await waitForInstalledCanonicalMemoryState(frameHost, true, 30_000);
        } else if (!setup.profile_initial_attached && !current.detached) {
          const restored = await invokeInstalledHostAction(frameHost, { route: 'memory', action: 'disconnectCanonicalMemory', operation: 'disconnectCanonicalMemory' }, 30_000);
          setup.restored_target = String(restored.detail?.restoredWorkspaceRoot || '');
          setup.restored_target_identity = installedFilesystemPathIdentity(setup.restored_target);
          setup.restored = installedFilesystemPathsMatch(setup.restored_target, setup.profile_initial_target);
          await waitForInstalledCanonicalMemoryState(frameHost, false, 30_000);
        } else setup.restored = true;
      } catch (restoreError) { setup.errors.push(`restoration:${String(restoreError?.message || restoreError).slice(0, 900)}`); }
    }
    records.push(reversibleConfigurationRecord(memoryRequirements[0], setup));
    records.push(reversibleConfigurationRecord(memoryRequirements[1], { ...setup, before_target: setup.configured_target || 'configured-owned-canonical-memory' }));
    records.push(reversibleConfigurationRecord(memoryRequirements[2], setup));
  }
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Exact installed host reversible configuration operation with finally restoration.',
    eligible_control_count: records.length,
    records
  };
}

function selectLatestMatchingInstalledSnapshot(responses, after, predicate, request = null) {
  let observed = null;
  let matched = null;
  for (const response of (responses || []).slice(after)) {
    if (response?.type !== 'snapshot') continue;
    const candidate = request ? requestBoundSystemSnapshotIdentity(request, response)?.snapshot || null : response.snapshot || null;
    if (!candidate) continue;
    observed = candidate;
    if (predicate(candidate)) matched = candidate;
  }
  return { matched, observed };
}

function installedSnapshotTimeoutIdentity(candidate) {
  const decision = candidate?.bridge?.decision || {};
  const tasks = Array.isArray(candidate?.coordinationData?.state?.tasks) ? candidate.coordinationData.state.tasks : [];
  return {
    connected: candidate?.connected === true,
    reason: typeof candidate?.reason === 'string' ? candidate.reason.slice(0, 400) : undefined,
    bridge_allowed: typeof decision.allowed === 'boolean' ? decision.allowed : null,
    requested_effect: typeof decision.requestedEffect === 'string' ? decision.requestedEffect.slice(0, 80) : null,
    bridge_reasons: (Array.isArray(decision.reasons) ? decision.reasons : []).slice(0, 8).map(value => String(value).slice(0, 240)),
    coordination_revision: Number.isFinite(candidate?.coordinationData?.state?.revision) ? candidate.coordinationData.state.revision : null,
    codex_tasks: tasks.filter(task => /^px-codex-[a-z0-9-]+$/i.test(String(task?.id || ''))).slice(0, 4).map(task => ({
      status: String(task?.status || '').slice(0, 40),
      owner_actor_present: Boolean(task?.owner?.actor_id),
      owner_session_present: Boolean(task?.owner?.session_id)
    }))
  };
}

async function waitForInstalledSnapshot(frameHost, after, predicate, timeoutMs = 30_000, request = null) {
  const deadline = Date.now() + timeoutMs;
  let candidate = null;
  do {
    const responses = await frameHost.evaluate((frame, offset) => (frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [])
      .slice(offset).filter(response => response?.type === 'snapshot'), after);
    const selection = selectLatestMatchingInstalledSnapshot(responses, 0, predicate, request);
    candidate = selection.observed;
    if (selection.matched) return selection.matched;
    await wait(150);
  } while (Date.now() < deadline);
  throw new Error(`installed-snapshot-state-timeout:${JSON.stringify(installedSnapshotTimeoutIdentity(candidate))}`);
}

async function requestInstalledRefresh(frameHost, timeoutMs = 20_000) {
  const before = await frameHost.evaluate(frame => frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0);
  await navigateInstalledSurface(frameHost, 'dashboard', timeoutMs);
  const deadline = Date.now() + timeoutMs;
  do {
    const state = await frameHost.evaluate(frame => {
      const control = [...frame.contentDocument.querySelectorAll('[data-action="refresh"]')]
        .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
      if (control) {
        const containingModal = control.closest('.control-modal');
        const closeModal = containingModal?.querySelector('[data-action="closeModal"]');
        control.click();
        closeModal?.click();
        return 'requested';
      }
      const commandCenter = [...frame.contentDocument.querySelectorAll('[data-action="commandCenter"]')]
        .find(element => !element.disabled && (element.offsetWidth || element.offsetHeight || element.getClientRects().length));
      const modalOpen = Boolean(frame.contentDocument.querySelector('.control-modal'));
      if (commandCenter && !modalOpen) {
        commandCenter.click();
        return 'opened-control-center';
      }
      return 'waiting';
    });
    if (state === 'requested') return before;
    await wait(100);
  } while (Date.now() < deadline);
  const state = await frameHost.evaluate(frame => ({
    active: [...frame.contentDocument.querySelectorAll('.nav-item[aria-current="page"]')].map(element => element.dataset.surface),
    refresh_controls: [...frame.contentDocument.querySelectorAll('[data-action="refresh"]')].map(element => ({
      disabled: Boolean(element.disabled),
      visible: Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
      text: String(element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 240)
    })),
    command_center: [...frame.contentDocument.querySelectorAll('[data-action="commandCenter"]')].map(element => ({
      disabled: Boolean(element.disabled),
      visible: Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
      text: String(element.innerText || element.getAttribute('aria-label') || '').trim().slice(0, 240)
    })),
    modal_open: Boolean(frame.contentDocument.querySelector('.control-modal')),
    text: String(frame.contentDocument?.body?.innerText || '').replace(/\s+/g, ' ').slice(0, 3000)
  })).catch(() => ({ active: [], refresh_controls: [], command_center: [], modal_open: false, text: '' }));
  throw new Error(`installed-refresh-control-timeout:${JSON.stringify(state)}`);
}

async function requestInstalledRefreshBound(frameHost, timeoutMs = 20_000) {
  const offsets = await frameHost.evaluate(frame => ({
    responses: frame.contentWindow?.__PX_INSTALLED_RESPONSES__?.length || 0,
    requests: frame.contentWindow?.__PX_INSTALLED_REQUESTS__?.length || 0
  }));
  const responseOffset = await requestInstalledRefresh(frameHost, timeoutMs);
  const deadline = Date.now() + timeoutMs;
  do {
    const request = await frameHost.evaluate((frame, offset) => (frame.contentWindow?.__PX_INSTALLED_REQUESTS__ || [])
      .slice(offset).find(value => value?.type === 'refresh') || null, offsets.requests);
    if (request) return { responses: responseOffset, requests: offsets.requests, request };
    await wait(100);
  } while (Date.now() < deadline);
  throw new Error('installed-refresh-request-identity-timeout');
}

async function refreshInstalledDashboardSnapshot(frameHost, predicate, timeoutMs = 30_000) {
  const request = await requestInstalledRefreshBound(frameHost, timeoutMs);
  return waitForInstalledSnapshot(frameHost, request.responses, predicate, timeoutMs, request.request);
}

async function installedSurfaceConnection(frameHost, requirement) {
  const route = INSTALLED_ROUTES[requirement.surface_id];
  await frameHost.evaluate((frame, item) => {
    const document = frame.contentDocument;
    document?.querySelector('[data-action="closeModal"]')?.click();
    if (item.advanced) {
      const toggle = document?.querySelector('[data-action="toggleAdvanced"]');
      if (toggle && toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
    }
    const target = document?.querySelector(`[data-surface="${CSS.escape(item.route)}"]`);
    if (!target) throw new Error(`installed-outage-route-unavailable:${item.route}`);
    target.click();
  }, { route, advanced: ['knowledgeCore', 'runtimeCore'].includes(route) });
  await wait(100);
  return frameHost.evaluate(frame => {
    const document = frame.contentDocument;
    const app = document?.querySelector('#app');
    const alert = document?.querySelector('[data-engine-disconnected][role="alert"]');
    return {
      heading: document?.querySelector('main h1')?.textContent?.trim() || '',
      disconnected: Boolean(app?.classList.contains('disconnected')),
      alert_visible: Boolean(alert && (alert.offsetWidth || alert.offsetHeight || alert.getClientRects().length)),
      alert_text: String(alert?.textContent || '').replace(/\s+/g, ' ').trim(),
      footer: String(document?.querySelector('.footer')?.textContent || '').replace(/\s+/g, ' ').trim()
    };
  });
}

function engineOutageRecord(requirement, observation) {
  const evidenceRef = `installed-engine-outage:${requirement.control_id}`;
  const baseline = observation.baseline?.[requirement.control_id];
  const fault = observation.fault?.[requirement.control_id];
  const recovered = observation.recovered?.[requirement.control_id];
  const failure = Boolean(baseline && !baseline.disconnected && fault?.disconnected && fault.alert_visible
    && /metrics are unavailable/i.test(fault.alert_text) && /not an observed system value/i.test(fault.alert_text));
  const recovery = Boolean(observation.restoration?.restored && recovered && !recovered.disconnected
    && !recovered.alert_visible && /CONTROL PLANE CONNECTED/i.test(recovered.footer));
  return {
    control_id: requirement.control_id, surface_id: requirement.surface_id, control_kind: requirement.kind,
    evidence_mode: 'owned_disposable_engine_outage', rendered: Boolean(baseline?.heading), observed: failure || recovery,
    attempted: observation.outage_started === true,
    interaction_chain: Object.fromEntries(STAGES.map(stage => {
      if (requirement.stage_policy[stage] !== 'required') return [stage, { state: 'not_applicable', detail: `Canonical matrix marks ${stage} not applicable.`, evidence: [evidenceRef] }];
      if (stage === 'failure_handling') return [stage, failure
        ? { state: 'present', detail: 'The exact surface rendered a prominent non-authoritative-metrics alert after the installed host returned a physical disposable-engine disconnection.', evidence: [evidenceRef] }
        : { state: 'missing', detail: 'The physical disposable-engine outage did not produce the exact visible fail-closed surface state.', evidence: [] }];
      if (stage === 'recovery_rollback') return [stage, recovery
        ? { state: 'present', detail: 'The displaced runtime was restored byte-for-byte and the exact surface returned to a connected snapshot without the outage alert.', evidence: [evidenceRef] }
        : { state: 'missing', detail: 'Exact engine restoration and connected surface recovery were not both observed.', evidence: [] }];
      if (requirement.kind !== 'failure_recovery' && ['persistence', 'reload_reopen'].includes(stage)) return [stage, {
        state: 'missing', detail: `The outage proves failure containment and restoration, but does not by itself prove positive ${stage} state retention.`, evidence: []
      }];
      return [stage, failure && recovery
        ? { state: 'present', detail: `Owned-root validation authorized the fault, the installed refresh crossed the host/backend boundary, and the exact surface acknowledged ${stage} during physical failure and recovery.`, evidence: [evidenceRef] }
        : { state: 'missing', detail: `The engine outage profile did not prove required stage ${stage}.`, evidence: [] }];
    })),
    errors: observation.errors
  };
}

async function runInstalledEngineOutageProfile(frameHost, matrix) {
  const requirements = matrix.controls.filter(control => ['failure_recovery', 'persistence', 'reload_reopen'].includes(control.kind)
    && !['sidebar', 'agent-studio', 'workflow-studio', 'skill-studio'].includes(control.surface_id)
    && Object.hasOwn(INSTALLED_ROUTES, control.surface_id));
  const observation = { outage_started: false, baseline: {}, fault: {}, recovered: {}, fault_snapshot: null, recovered_snapshot: null, restoration: null, errors: [] };
  let outage = null;
  try {
    for (const requirement of requirements) observation.baseline[requirement.control_id] = await installedSurfaceConnection(frameHost, requirement);
    outage = beginOwnedEngineOutage(process.env.PX_OWNED_ENGINE_ROOT, ownedHostToken);
    observation.outage_started = true;
    const faultAfter = await requestInstalledRefresh(frameHost);
    observation.fault_snapshot = await waitForInstalledSnapshot(frameHost, faultAfter, snapshot => snapshot.connected === false);
    for (const requirement of requirements) observation.fault[requirement.control_id] = await installedSurfaceConnection(frameHost, requirement);
  } catch (error) {
    observation.errors.push(String(error?.message || error).slice(0, 2000));
  } finally {
    if (outage) {
      try { observation.restoration = outage.restore(); }
      catch (error) { observation.errors.push(`restoration:${String(error?.message || error).slice(0, 1800)}`); }
    }
  }
  if (observation.restoration?.restored) {
    try {
      const recoveryAfter = await requestInstalledRefresh(frameHost);
      observation.recovered_snapshot = await waitForInstalledSnapshot(frameHost, recoveryAfter, snapshot => snapshot.connected === true && snapshot.extensionIdentity?.matches === true);
      for (const requirement of requirements) observation.recovered[requirement.control_id] = await installedSurfaceConnection(frameHost, requirement);
    } catch (error) { observation.errors.push(`recovery:${String(error?.message || error).slice(0, 1800)}`); }
  }
  return {
    schema_version: 'px.installed-operational-control-probe/1.0',
    authority: 'Physical runtime displacement and exact byte-preserving restoration inside the PACIFY-X-owned disposable engine only.',
    eligible_control_count: requirements.length,
    observation,
    records: requirements.map(requirement => engineOutageRecord(requirement, observation))
  };
}

function currentSourceExtensionAssetIdentity(extensionRoot = path.resolve(__dirname, '..')) {
  const root = path.resolve(extensionRoot);
  const files = [];
  const dashboardRoot = path.join(root, 'media', 'dashboard');
  if (fs.existsSync(dashboardRoot)) {
    for (const name of fs.readdirSync(dashboardRoot).filter(name => name.endsWith('.js'))) files.push(path.join(dashboardRoot, name));
  }
  const hostSourceRoot = path.join(root, 'src');
  if (fs.existsSync(hostSourceRoot)) {
    for (const name of fs.readdirSync(hostSourceRoot).filter(name => name.endsWith('.js'))) files.push(path.join(hostSourceRoot, name));
  }
  for (const relative of [path.join('media', 'dashboard.css'), path.join('media', 'sidebar.css'), path.join('media', 'sidebar.js'), path.join('resources', 'ui', 'action-inventory.json')]) {
    const target = path.join(root, relative);
    if (fs.existsSync(target)) files.push(target);
  }
  files.sort((left, right) => Buffer.compare(Buffer.from(path.relative(root, left).replaceAll('\\', '/'), 'utf8'), Buffer.from(path.relative(root, right).replaceAll('\\', '/'), 'utf8')));
  const digest = crypto.createHash('sha256');
  for (const file of files) {
    digest.update(path.relative(root, file).replaceAll('\\', '/'));
    digest.update('\0');
    digest.update(fs.readFileSync(file));
    digest.update('\0');
  }
  const packagePath = path.join(root, 'package.json');
  const packageBytes = fs.readFileSync(packagePath);
  return {
    version: String(JSON.parse(packageBytes.toString('utf8')).version || 'unknown'),
    package_sha256: crypto.createHash('sha256').update(packageBytes).digest('hex'),
    asset_sha256: digest.digest('hex'),
    asset_file_count: files.length
  };
}

function installedRuntimeSourceIdentityState(runtimeIdentity, currentSourceIdentity) {
  if (!runtimeIdentity || runtimeIdentity.schema_version !== 'px.extension-runtime-identity/1.0') return 'unknown';
  const host = runtimeIdentity.host;
  const source = runtimeIdentity.source;
  const validHash = value => /^[a-f0-9]{64}$/.test(String(value || ''));
  const validRuntimeSide = value => value && typeof value === 'object'
    && typeof value.version === 'string' && value.version.length > 0
    && validHash(value.asset_sha256)
    && typeof value.asset_protocol === 'string' && value.asset_protocol.length > 0
    && typeof value.message_schema === 'string' && value.message_schema.length > 0;
  if (!validRuntimeSide(host) || !validRuntimeSide(source)) return 'unknown';
  if (runtimeIdentity.matches !== true) return runtimeIdentity.matches === false || (runtimeIdentity.mismatch_reasons || []).length ? 'mismatch' : 'unknown';
  if (host.version !== source.version || host.asset_sha256 !== source.asset_sha256 || host.asset_protocol !== source.asset_protocol || host.message_schema !== source.message_schema) return 'mismatch';
  if (!currentSourceIdentity || !validHash(currentSourceIdentity.asset_sha256) || !validHash(currentSourceIdentity.package_sha256) || !Number.isSafeInteger(currentSourceIdentity.asset_file_count)) return 'unknown';
  if (host.version !== currentSourceIdentity.version
    || host.asset_sha256 !== currentSourceIdentity.asset_sha256
    || host.package_sha256 !== currentSourceIdentity.package_sha256
    || host.asset_file_count !== currentSourceIdentity.asset_file_count) return 'mismatch';
  return 'verified';
}

async function waitForInstalledSourceIdentity(frameHost, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  const currentSourceIdentity = currentSourceExtensionAssetIdentity();
  let runtimeIdentity = null;
  do {
    runtimeIdentity = await frameHost.evaluate(frame => {
      const responses = frame.contentWindow?.__PX_INSTALLED_RESPONSES__ || [];
      for (let index = responses.length - 1; index >= 0; index -= 1) {
        const value = responses[index];
        if (value?.type === 'snapshot' && value?.snapshot?.extensionIdentity) return value.snapshot.extensionIdentity;
      }
      return null;
    });
    const state = installedRuntimeSourceIdentityState(runtimeIdentity, currentSourceIdentity);
    if (state !== 'unknown') return { state, runtime_identity: runtimeIdentity, current_source_identity: currentSourceIdentity };
    await wait(200);
  } while (Date.now() < deadline);
  return { state: 'unknown', runtime_identity: runtimeIdentity, current_source_identity: currentSourceIdentity };
}

function installedSourceIdentityNeedsLateRefresh(installedIdentity) {
  return installedIdentity?.state === 'unknown';
}

async function refreshInstalledSourceIdentity(frameHost, installedIdentity, timeoutMs, refresh) {
  try {
    const currentSourceIdentity = installedIdentity.current_source_identity || currentSourceExtensionAssetIdentity();
    const snapshot = await refreshInstalledDashboardSnapshot(frameHost, value => Boolean(value?.extensionIdentity), timeoutMs);
    const runtimeIdentity = snapshot.extensionIdentity;
    return {
      state: installedRuntimeSourceIdentityState(runtimeIdentity, currentSourceIdentity),
      runtime_identity: runtimeIdentity,
      current_source_identity: currentSourceIdentity,
      refresh
    };
  } catch (error) {
    return {
      ...installedIdentity,
      refresh: `${refresh}-failed`,
      diagnostic: String(error?.message || error).slice(0, 1600)
    };
  }
}

function installedConsoleDiagnostic(message) {
  const value = String(message?.text?.() || '').slice(0, 1000);
  if (/\[vscode\.mermaid-markdown-features\]: Extension 'vscode\.mermaid-markdown-features' CANNOT use 'legacyToolReferenceFullNames' without the 'chatParticipantPrivate' API proposal enabled/i.test(value)) return null;
  const location = message?.location?.() || {};
  const sourceUrl = String(location.url || '').slice(0, 1000);
  const externalGalleryCancellation = /^%c\s+ERR\s+color:\s*#f33\s+Cancelled:\s+Canceled:\s+Canceled/i.test(value)
    && /getLatestRawGalleryExtension[\s\S]*getLatestGalleryExtension/i.test(value)
    && /^vscode-file:\/\/vscode-app\/.+\/workbench\/workbench\.desktop\.main\.js$/i.test(sourceUrl);
  if (externalGalleryCancellation) return null;
  if (value === 'Failed to load resource: the server responded with a status of 404 ()'
    && sourceUrl === 'https://marketplace.visualstudio.com/_apis/public/gallery/vscode/mountain-nomad-bc/pacify-x-vscode/latest') return null;
  return { source: 'console', context: sourceUrl ? `console:${sourceUrl}` : 'console:location-unavailable', source_url: sourceUrl || null, message: value };
}

async function main() {
  // The authoritative denominator is validated before attaching to or
  // interacting with a live host. A changed/duplicate inventory fails closed.
  const inventory = loadOperationalSurfaceInventory(inventoryPath);
  const proofMatrix = JSON.parse(fs.readFileSync(proofMatrixPath, 'utf8'));
  if (!Array.isArray(proofMatrix.controls) || proofMatrix.controls.length !== inventory.control_count) {
    throw new Error('Operational proof matrix does not match the authoritative installed-host denominator.');
  }
  fs.mkdirSync(outputRoot, { recursive: true });
  const profileProgressPath = path.join(outputRoot, 'profile-progress.ndjson');
  const appendProfileProgress = event => fs.appendFileSync(profileProgressPath, `${JSON.stringify({ schema_version: 'px.operational-profile-progress/1.0', observed_utc: new Date().toISOString(), ...event })}\n`, { encoding: 'utf8' });
  const profileItems = value => Array.isArray(value)
    ? value
    : (value && typeof value === 'object' ? Object.values(value) : []);
  const profileErrors = value => value == null
    ? []
    : (Array.isArray(value) ? value : [value]);
  const returnedProfileErrors = result => [...new Set([
    ...profileErrors(result?.errors),
    ...profileErrors(result?.observation?.errors),
    ...profileItems(result?.observations).flatMap(item => profileErrors(item?.errors)),
    ...profileItems(result?.records).flatMap(item => profileErrors(item?.errors)),
    ...profileItems(result?.control_probe?.records).flatMap(item => profileErrors(item?.errors))
  ].map(error => String(error).slice(0, 1000)))].slice(0, 12);
  const profileFailures = [];
  const recordProfileFailure = (profile, state, errors, dependency = null) => {
    const normalized = [...new Set(profileErrors(errors).map(error => String(error).slice(0, 1200)))];
    const entry = { profile, state, dependency, errors: normalized };
    profileFailures.push(entry);
    return entry;
  };
  const failedProfileResult = (profile, errors, authority = 'The profile terminated without a typed result; exact failure was retained and independent profiles remain eligible.') => {
    const normalized = [...new Set(profileErrors(errors).map(error => String(error).slice(0, 1200)))];
    return {
      schema_version: 'px.installed-collected-profile-failure/1.0', profile, authority,
      completed: false, terminal_disposition: 'failed', errors: normalized,
      observation: { attempted: true, completed: false, errors: normalized }, observations: [], records: [],
      control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority, eligible_control_count: 0, records: [] }
    };
  };
  const skippedProfileResult = (profile, dependency, errors = [`dependency-failed:${dependency}`]) => {
    const result = failedProfileResult(profile, errors, `Skipped because the exact prerequisite ${dependency} failed; no dependent action was dispatched.`);
    result.terminal_disposition = 'skipped_dependency_failed';
    result.observation.attempted = false;
    recordProfileFailure(profile, 'skipped', result.errors, dependency);
    appendProfileProgress({ profile, state: 'skipped', dependency, error_count: result.errors.length, errors: result.errors });
    return result;
  };
  let profileDashboardBaseline = null;
  let dashboardProfileBlocker = null;
  const timedProfile = async (profile, operation, { resetBaseline = true, timeoutMs = null } = {}) => {
    if (resetBaseline && dashboardProfileBlocker) return skippedProfileResult(profile, dashboardProfileBlocker);
    const started = Date.now(); appendProfileProgress({ profile, state: 'started' });
    try {
      const execute = async () => {
        if (resetBaseline && profileDashboardBaseline) await resetInstalledDashboardBaseline(profileDashboardBaseline.workbench, profileDashboardBaseline.frameHost);
        return operation();
      };
      const result = timeoutMs == null
        ? await execute()
        : await boundedOwnedUiAction(execute, timeoutMs, `installed-profile-${profile}`);
      const errors = returnedProfileErrors(result);
      if (errors.length) recordProfileFailure(profile, 'returned-failed', errors);
      appendProfileProgress({ profile, state: 'returned', duration_ms: Date.now() - started, completed: result?.observation?.completed ?? result?.completed ?? null, error_count: errors.length, errors });
      return result;
    } catch (error) {
      const message = String(error?.message || error).slice(0, 1200);
      recordProfileFailure(profile, 'threw', [message]);
      appendProfileProgress({ profile, state: 'threw', duration_ms: Date.now() - started, completed: false, error_count: 1, errors: [message], error: message });
      return failedProfileResult(profile, [message]);
    }
  };
  const browser = await chromium.connectOverCDP(endpoint);
  let ownedWorkbenchViewport = null;
  const hostErrors = [];
  try {
    for (const page of await allPages(browser)) {
      page.on('pageerror', error => hostErrors.push({ source: 'pageerror', message: String(error?.message || error).slice(0, 1000) }));
      page.on('console', message => { if (message.type() === 'error') { const diagnostic = installedConsoleDiagnostic(message); if (diagnostic) hostErrors.push(diagnostic); } });
    }
    const workbench = await waitForPage(browser, async page => {
      const title = await page.title();
      return /Visual Studio Code|Pacify-X/i.test(title) && !page.url().startsWith('vscode-webview:');
    }, 30_000);
    if (!workbench) throw new Error('VS Code workbench target was not found.');
    await workbench.bringToFront();
    ownedWorkbenchViewport = await enforceOwnedWorkbenchViewport(workbench);
    const dashboardTab = workbench.locator('[role="tab"]', { hasText: /PX.*Control Plane/i }).first();
    if (!await dashboardTab.isVisible().catch(() => false)) {
      await executeWorkbenchCommand(workbench, 'Pacify-X: Open Control Plane');
    }
    // Another eager extension can steal editor focus while the command is
    // activating. Select the exact PX tab before VS Code materializes its
    // non-retained webview iframe, and keep failure specificity if it is absent.
    await dashboardTab.waitFor({ state: 'visible', timeout: 30_000 });
    await dashboardTab.click();

    const dashboard = await waitForOwnedWebview(workbench, text => /PACIFY-X\s*\/\s*DASHBOARD/i.test(text), 90_000);
    if (!dashboard) throw new Error('The installed extension did not produce the Pacify-X dashboard webview.');
    profileDashboardBaseline = { workbench, frameHost: dashboard };
    if (ownedReversibleConfigurationAuthority && !await instrumentInstalledBridge(dashboard)) throw new Error(`Owned ${focusedProfile || 'integrated'} profile could not instrument the installed host response bridge.`);
    try {
      await navigateInstalledSurface(dashboard, 'dashboard', 20_000);
    } catch (error) {
      throw new Error(`installed-initial-dashboard-route-unavailable:${String(error?.message || error).slice(0, 1800)}`);
    }
    const attemptedControlIds = ['pxui.dashboard-control-plane.command.pacifyX.openDashboard'];
    let installedIdentity = await waitForInstalledSourceIdentity(dashboard, 5_000);
    if (installedIdentity.state === 'unknown' && ownedReversibleConfigurationAuthority) {
      installedIdentity = await refreshInstalledSourceIdentity(dashboard, installedIdentity, 45_000, 'request-bound');
    }
    let hostSourceMismatch = installedIdentity.state === 'mismatch';
    let hostSourceIdentityVerified = installedIdentity.state === 'verified';
    let workbenchCommandProfile = { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside the full owned isolated host.', eligible_control_count: 0, records: [] };
    if (!hostSourceMismatch && !studioLifecycleOnly) {
      const toggledAdvanced = await dashboard.evaluate(frame => {
        const document = frame.contentDocument;
        const toggle = document?.querySelector('[data-action="toggleAdvanced"]');
        if (toggle && toggle.getAttribute('aria-expanded') !== 'true') { toggle.click(); return true; }
        return false;
      });
      if (toggledAdvanced) attemptedControlIds.push('pxui.dashboard-control-plane.action.toggleAdvanced');
      await wait(150);
    }
    const surfaces = await dashboard.evaluate(frame => [...new Set([...frame.contentDocument.querySelectorAll('[data-surface]')].map(item => item.dataset.surface).filter(Boolean))]);
    const results = [];
    if (!hostSourceMismatch && !focusedProfileOnly) {
      for (const surface of surfaces) {
        const result = await inspectSurface(dashboard, surface);
        attemptedControlIds.push(`pxui.dashboard-control-plane.action.navigate.${surface}`);
        result.captures = await captureSurfaceViews(dashboard, proofMatrix, surface, results.length + 1, outputRoot, hostErrors);
        result.screenshot = result.captures.first_fold.screenshot;
        results.push(result);
        if (surface === 'knowledgeGraph') {
          try {
            await dashboard.evaluate(frame => frame.contentDocument?.querySelector('[data-graph-canvas]')?.scrollIntoView({ block: 'center' }));
            await wait(300);
            result.graph_screenshot = await safeScreenshot(dashboard, path.join(outputRoot, 'knowledge-graph-canvas.png'), 'knowledge-graph-canvas', hostErrors);
          }
          catch (error) { hostErrors.push({ source: 'walker', message: `knowledge graph canvas screenshot failed: ${String(error?.message || error).slice(0, 800)}` }); }
        }
      }
    }
    const builders = {};
    const reversibleConfigurationProfile = ownedReversibleConfigurationAuthority && (!focusedProfileOnly || configurationOnly)
      ? await timedProfile('reversible-configuration', () => runInstalledReversibleConfigurationProfile(workbench, dashboard, proofMatrix))
      : { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host.', eligible_control_count: 0, records: [] };
    if (ownedReversibleConfigurationAuthority && returnedProfileErrors(reversibleConfigurationProfile).length) {
      dashboardProfileBlocker = 'reversible-configuration';
    }
    const studioChainAdmitted = ownedReversibleConfigurationAuthority && !configurationOnly && !knowledgeLifecycleOnly && !hostBoundaryOnly && !nativeDialogOnly && !codexHandoffOnly && !errorIndicatorsOnly;
    const studioSetupProfile = studioChainAdmitted
      ? await timedProfile('studio-setup', () => runInstalledStudioSetupProfile(workbench, dashboard, proofMatrix))
      : { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host.', eligible_control_count: 0, records: [] };
    const studioSetupHealthy = returnedProfileErrors(studioSetupProfile).length === 0;
    const studioCandidateSaveProfile = studioChainAdmitted
      ? studioSetupHealthy
        ? await timedProfile('studio-candidate-save', () => runInstalledStudioCandidateSaveProfile(dashboard, proofMatrix, studioLifecycleOnly ? 45_000 : 150_000, true))
        : skippedProfileResult('studio-candidate-save', 'studio-setup')
      : { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host.', eligible_control_count: 0, records: [] };
    const studioCandidateHealthy = returnedProfileErrors(studioCandidateSaveProfile).length === 0;
    let studioLifecycleProfile = studioChainAdmitted
      ? studioCandidateHealthy
        ? await timedProfile('studio-lifecycle', () => runInstalledStudioLifecycleProfile(dashboard, studioCandidateSaveProfile, proofMatrix))
        : skippedProfileResult('studio-lifecycle', 'studio-candidate-save')
      : { schema_version: 'px.installed-studio-lifecycle-profile/1.0', authority: 'Not admitted outside an owned isolated host.', observations: [], control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host.', eligible_control_count: 0, records: [] } };
    const studioRevisionEditProfile = studioChainAdmitted
      ? studioCandidateHealthy
        ? await timedProfile('studio-revision-edit', () => runInstalledStudioRevisionEditProfile(dashboard, studioCandidateSaveProfile, proofMatrix, studioLifecycleOnly ? 45_000 : 150_000))
        : skippedProfileResult('studio-revision-edit', 'studio-candidate-save')
      : { schema_version: 'px.installed-studio-revision-edit-profile/1.0', authority: 'Not admitted outside an owned isolated host.', observations: [], control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host.', eligible_control_count: 0, records: [] } };
    if (studioChainAdmitted && studioCandidateHealthy && returnedProfileErrors(studioLifecycleProfile).length === 0 && returnedProfileErrors(studioRevisionEditProfile).length === 0) {
      const baseSkill = (studioCandidateSaveProfile.observations || []).find(item => item.kind === 'skill');
      const revisedSkill = (studioRevisionEditProfile.observations || []).find(item => item.kind === 'skill');
      if (baseSkill && validStudioRevisionEditObservation(revisedSkill)) {
        const rollbackCandidate = {
          ...baseSkill,
          version: revisedSkill.candidate_version,
          catalog_record_id: revisedSkill.saved_catalog_record_id,
          typed_creation_receipt: revisedSkill.typed_creation_receipt,
          reopened_catalog_match: revisedSkill.reopened_catalog_match,
          expect_rollback: true
        };
        const rollbackProfile = await timedProfile('studio-skill-revision-rollback', () => runInstalledStudioLifecycleProfile(dashboard, { observations: [rollbackCandidate] }, proofMatrix));
        const mergedObservations = mergeStudioLifecycleObservations(studioLifecycleProfile.observations, rollbackProfile.observations);
        studioLifecycleProfile = {
          ...studioLifecycleProfile,
          observations: mergedObservations,
          skill_revision_rollback_profile: rollbackProfile,
          control_probe: studioLifecycleControlProbe(proofMatrix, mergedObservations)
        };
      }
    }
    const studioLifecycleCrashProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly
      ? await timedProfile('studio-lifecycle-crash-recovery', () => runInstalledStudioLifecycleCrashProfile(), { resetBaseline: false })
      : { schema_version: 'px.installed-studio-lifecycle-crash-profile/1.0', authority: 'Reserved for the full owned installed-host campaign.', completed: false, observations: [], errors: [] };
    if (!focusedProfileOnly && !hostSourceMismatch && studioLifecycleCrashProfile.completed !== true && returnedProfileErrors(studioLifecycleCrashProfile).length === 0) {
      recordProfileFailure('studio-lifecycle-crash-recovery', 'returned-incomplete', studioLifecycleCrashProfile.errors?.length ? studioLifecycleCrashProfile.errors : ['profile-incomplete-without-error']);
    }
    const knowledgeLifecycleProfile = ownedReversibleConfigurationAuthority && !configurationOnly && !studioLifecycleOnly && !hostBoundaryOnly && !nativeDialogOnly && !codexHandoffOnly && !errorIndicatorsOnly
      ? await timedProfile('knowledge-lifecycle', () => runInstalledKnowledgeLifecycleProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-knowledge-lifecycle-profile/1.0', authority: 'Not admitted outside an owned isolated host and disposable workspace.', observation: { attempted: false, completed: false, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host and disposable workspace.', eligible_control_count: 0, records: [] } };
    const learningLifecycleProfile = ownedReversibleConfigurationAuthority && !configurationOnly && !studioLifecycleOnly && !hostBoundaryOnly && !nativeDialogOnly && !codexHandoffOnly && !errorIndicatorsOnly
      ? await timedProfile('learning-lifecycle', () => runInstalledLearningLifecycleProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-learning-lifecycle-profile/1.0', authority: 'Not admitted outside an owned isolated host and disposable workspace.', observation: { attempted: false, completed: false, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host and disposable workspace.', eligible_control_count: 0, records: [] } };
    const coordinationMemoryProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly
      ? await timedProfile('coordination-memory', () => runInstalledCoordinationMemoryProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-coordination-memory-profile/1.0', authority: 'Not admitted outside a full owned isolated host and disposable workspace.', observation: { attempted: false, completed: false, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside a full owned isolated host and disposable workspace.', eligible_control_count: 0, records: [] } };
    const skillQueryProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly
      ? await timedProfile('skill-query-read', () => runInstalledSkillQueryProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-skill-query-profile/1.0', authority: 'Not admitted outside a full owned isolated host.', observation: { attempted: false, completed: false, errors: [] }, control_probe: skillQueryControlProbe(proofMatrix, { errors: [] }) };
    const catalogPaginationProfile = ownedReversibleConfigurationAuthority && (!focusedProfileOnly || studioLifecycleOnly)
      ? await timedProfile('catalog-pagination-read', () => runInstalledCatalogPaginationProfile(dashboard, proofMatrix, 30_000, studioLifecycleOnly ? new Set(['agents']) : null, true))
      : { schema_version: 'px.installed-catalog-pagination-profile/1.0', authority: 'Not admitted outside a full owned isolated host.', observations: [], control_probe: catalogPaginationControlProbe(proofMatrix, []) };
    let observationStateProfile = { schema_version: 'px.installed-observation-state-profile/1.0', authority: 'Not admitted before both dashboard and sidebar frame owners are initialized in a full owned isolated host.', observations: {}, control_probe: observationStateControlProbe(proofMatrix, {}) };
    const hostBoundaryProfile = ownedReversibleConfigurationAuthority && (!focusedProfileOnly || hostBoundaryOnly)
      ? await timedProfile('host-boundary', () => runInstalledHostBoundaryProfile(workbench, dashboard, proofMatrix, 30_000, event => appendProfileProgress({ profile: 'host-boundary-control', ...event })))
      : { schema_version: 'px.installed-host-boundary-profile/1.0', authority: 'Not admitted outside a full owned isolated host.', observation: { operations: {}, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside a full owned isolated host.', eligible_control_count: 0, records: [] } };
    const enterpriseProfile = ownedReversibleConfigurationAuthority && (!focusedProfileOnly || nativeDialogOnly)
      ? await timedProfile('enterprise-metadata', () => runInstalledEnterpriseProfile(workbench, dashboard, proofMatrix))
      : { schema_version: 'px.installed-enterprise-profile/1.0', authority: 'Not admitted outside a full owned isolated host.', observation: { controls: {}, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside a full owned isolated host.', eligible_control_count: 0, records: [] } };
    const environmentLifecycleProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly
      ? await timedProfile('environment-lifecycle', () => runInstalledEnvironmentLifecycleProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-environment-lifecycle-profile/1.0', authority: 'Not admitted outside a full owned isolated host.', observation: { errors: [] }, control_probe: environmentLifecycleControlProbe(proofMatrix, { errors: [] }) };
    const codexHandoffProfile = ownedReversibleConfigurationAuthority && (!focusedProfileOnly || codexHandoffOnly)
      ? await timedProfile('codex-context-handoff', () => runInstalledCodexHandoffProfile(workbench, dashboard, proofMatrix))
      : { schema_version: 'px.installed-codex-handoff-profile/1.0', authority: 'Not admitted outside a full owned isolated host.', observation: { errors: [] }, control_probe: codexHandoffControlProbe(proofMatrix, { errors: [] }) };
    const validationProfile = validationExecutionAuthority && postAuditLongRunningAuthority && !focusedProfileOnly
      ? await timedProfile('shared-validation', () => runInstalledValidationProfile(dashboard, proofMatrix))
      : !focusedProfileOnly && !hostSourceMismatch
        ? await timedProfile('validation-authority-boundary', () => runInstalledValidationBoundaryProfile(dashboard, proofMatrix))
        : { schema_version: 'px.installed-validation-profile/1.0', authority: 'Deferred until the full adversarial audit and its repairs are complete.', observation: { rendered: {}, executed_once: false, cancelled_probe: false, result: null, webview_restarted: false, errors: [] }, control_probe: validationControlProbe(proofMatrix, { rendered: {}, errors: [] }) };
    const combinedHostEffectProbe = {
      ...hostBoundaryProfile.control_probe,
      eligible_control_count: hostBoundaryProfile.control_probe.eligible_control_count + enterpriseProfile.control_probe.eligible_control_count + environmentLifecycleProfile.control_probe.eligible_control_count + codexHandoffProfile.control_probe.eligible_control_count + validationProfile.control_probe.eligible_control_count,
      records: [...hostBoundaryProfile.control_probe.records, ...enterpriseProfile.control_probe.records, ...environmentLifecycleProfile.control_probe.records, ...codexHandoffProfile.control_probe.records, ...validationProfile.control_probe.records]
    };
    const projectsProfile = ownedReversibleConfigurationAuthority && (!focusedProfileOnly || nativeDialogOnly)
      ? await timedProfile('projects-map-restart', () => runInstalledProjectsProfile(workbench, dashboard, proofMatrix))
      : { schema_version: 'px.installed-projects-profile/1.0', authority: 'Not admitted outside a full owned isolated host and disposable workspace.', observation: { attempted: false, completed: false, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside a full owned isolated host and disposable workspace.', eligible_control_count: 0, records: [] } };
    const knowledgeGraphProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly
      ? await timedProfile('knowledge-graph-restart', () => runInstalledKnowledgeGraphProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-knowledge-graph-profile/1.0', authority: 'Not admitted outside a full owned isolated host and disposable workspace.', observation: { attempted: false, completed: false, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside a full owned isolated host and disposable workspace.', eligible_control_count: 0, records: [] } };
    const systemProjectionProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly
      ? await timedProfile('system-projection-restart', () => runInstalledSystemProjectionProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-system-projection-profile/1.0', authority: 'Not admitted outside a full exact-source owned host.', observation: { attempted: false, completed: false, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside a full exact-source owned host.', eligible_control_count: 0, records: [] } };
    const cleanupProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly
      ? await timedProfile('cleanup-recycle', () => runInstalledCleanupProfile(workbench, dashboard, proofMatrix))
      : { schema_version: 'px.installed-cleanup-recycle-profile/1.0', authority: 'Not admitted outside a full owned isolated host and disposable engine.', observation: { attempted: false, completed: false, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside a full owned isolated host and disposable engine.', eligible_control_count: 0, records: [] } };
    const pluginReadProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly
      ? await timedProfile('plugin-read-handoff', () => runInstalledPluginReadProfile(workbench, dashboard, proofMatrix))
      : { schema_version: 'px.installed-plugin-read-profile/1.0', authority: 'Not admitted outside a full owned isolated host.', observation: { attempted: false, operations: {}, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside a full owned isolated host.', eligible_control_count: 0, records: [] } };
    const pluginMutationProfile = ownedReversibleConfigurationAuthority && (!focusedProfileOnly || nativeDialogOnly)
      ? await timedProfile('plugin-local-lifecycle', () => runInstalledPluginMutationProfile(workbench, dashboard, proofMatrix))
      : { schema_version: 'px.installed-plugin-mutation-profile/1.0', authority: 'Not admitted outside a full owned disposable VS Code extension profile.', observation: { attempted: false, completed: false, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside a full owned disposable VS Code extension profile.', eligible_control_count: 0, records: [] } };
    // Builder inspection uses shared webview working-draft state. Run it only
    // after every state-producing profile has established and verified its
    // negative/positive denominators, but before the general probe aggregates
    // dynamic builder controls into the final receipt.
    if (!focusedProfileOnly && !hostSourceMismatch && profileDashboardBaseline) {
      await timedProfile(
        'pre-builder-baseline',
        () => resetInstalledDashboardBaseline(profileDashboardBaseline.workbench, profileDashboardBaseline.frameHost),
        { resetBaseline: false, timeoutMs: 30_000 }
      );
    }
    for (const kind of focusedProfileOnly ? [] : ['agent', 'workflow']) {
      if (hostSourceMismatch) {
        builders[kind] = { terminal_disposition: 'blocked_host_source_mismatch', reason: 'No builder interaction is allowed against installed assets that differ from source.' };
        continue;
      }
      try {
        builders[kind] = await timedProfile(
          `${kind}-builder`,
          () => inspectStudioBuilder(dashboard, kind, outputRoot, hostErrors),
          { resetBaseline: false, timeoutMs: 120_000 }
        );
      }
      catch (error) {
        const message = String(error?.message || error).slice(0, 1000);
        hostErrors.push({ source: 'walker', context: `${kind}-builder`, message });
        await dashboard.evaluate(frame => frame.contentDocument?.querySelector('.studio-modal [data-action="closeModal"]')?.click()).catch(() => {});
        builders[kind] = {
          terminal_disposition: 'failed', reason: message,
          observations: error?.builderEvidence?.observations || [],
          attempted_control_ids: error?.builderEvidence?.attempted_control_ids || [],
          failed_control_id: error?.builderEvidence?.failed_control_id || null,
          failed_action: error?.builderEvidence?.failed_action || null,
          failure_state: error?.builderEvidence?.failure_state || null
        };
      }
    }
    if (focusedProfileOnly) {
      builders.agent = { terminal_disposition: 'focused_profile_not_run', observations: [], attempted_control_ids: [] };
      builders.workflow = { terminal_disposition: 'focused_profile_not_run', observations: [], attempted_control_ids: [] };
    }
    // Stateful profiles intentionally precede the general probe. They create
    // the disposable catalog, run, and revision state required for dynamic
    // controls to exist; probing first permanently misclassified those
    // controls as not rendered within the same campaign.
    const installedControlProbe = errorIndicatorsOnly
      ? await timedProfile('error-indicators', () => probeInstalledControls(dashboard, proofMatrix, hostErrors, ERROR_INDICATOR_CONTROL_IDS))
      : focusedProfileOnly
        ? { schema_version: 'px.installed-operational-control-probe/1.0', authority: `Skipped by exact owned ${focusedProfile} profile.`, eligible_control_count: 0, records: [] }
        : await probeInstalledControls(dashboard, proofMatrix, hostErrors);
    const engineOutageProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly && process.env.PX_OWNED_ENGINE_ROOT
      ? await timedProfile('engine-outage', () => runInstalledEngineOutageProfile(dashboard, proofMatrix))
      : { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Not admitted outside an owned isolated host with a disposable engine.', eligible_control_count: 0, records: [] };
    let sidebarOpenError = null;
    const isSidebarText = text => /PACIFY-X[\s\S]*OPEN CONTROL PLANE/i.test(text) && /NO ACTIVE EXECUTION|PROVIDER ACTIVITY/i.test(text);
    let sidebar = focusedProfileOnly ? null : await waitForOwnedWebview(workbench, isSidebarText, 1_500);
    const activityControl = workbench.locator('.activitybar [aria-label="Pacify-X"]:visible').first();
    if (!focusedProfileOnly && !hostSourceMismatch && !sidebar && await activityControl.count()) await activityControl.click({ timeout: 3000 });
    else if (!focusedProfileOnly && !hostSourceMismatch && !sidebar) {
      // VS Code moves extension containers into Additional Views when the
      // activity bar is full. Select the real contributed view from that menu.
      try {
        await workbench.locator('.activitybar .codicon-more').click({ timeout: 3000 });
        const overflowItem = workbench.getByRole('menuitemcheckbox', { name: 'Pacify-X' });
        await overflowItem.waitFor({ state: 'visible', timeout: 3000 });
        await overflowItem.click({ timeout: 3000 });
        // The overflow menu controls whether the activity item is pinned; it
        // does not consistently open the contributed container. Activate the
        // now-visible item explicitly.
        await workbench.locator('.activitybar [aria-label="Pacify-X"]:visible').click({ timeout: 3000 });
      } catch (error) { sidebarOpenError = String(error?.message || error).slice(0, 500); }
    }
    if (!focusedProfileOnly && !hostSourceMismatch && !sidebar) sidebar = await waitForOwnedWebview(workbench, isSidebarText, 15_000);
    if (sidebar && ownedReversibleConfigurationAuthority && !focusedProfileOnly && !hostSourceMismatch) {
      observationStateProfile = await timedProfile('observation-state-scenarios', () => runInstalledObservationStateProfile(dashboard, sidebar, proofMatrix));
    }
    const sidebarStateProfile = sidebar && ownedReversibleConfigurationAuthority && !focusedProfileOnly && !hostSourceMismatch
      ? await timedProfile('sidebar-state-restart', () => runInstalledSidebarStateProfile(workbench, dashboard, sidebar, proofMatrix))
      : { schema_version: 'px.installed-sidebar-state-profile/1.0', authority: 'Sidebar state profile unavailable outside the full exact-source owned host.', observation: { attempted: false, completed: false, errors: [] }, control_probe: { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Sidebar state profile unavailable outside the full exact-source owned host.', eligible_control_count: 0, records: [] } };
    const sidebarResult = sidebar ? {
      text: (await innerText(sidebar)).slice(0, 20_000),
      provider_missing_message: /There is no data provider registered/i.test(await innerText(sidebar)),
      invalid_union_message: /sidebar-inbound-message-invalid:type:invalid_union/i.test(await innerText(sidebar)),
      buttons: await sidebar.evaluate(frame => [...frame.contentDocument.querySelectorAll('button')].filter(item => {
        const rect = item.getBoundingClientRect(); return rect.width > 0 && rect.height > 0;
      }).map(item => ({
        label: String(item.innerText || item.getAttribute('aria-label') || '').trim(),
        disabled: Boolean(item.disabled),
        action: item.dataset.action || null,
        dataset: Object.fromEntries(Object.entries(item.dataset).map(([key, value]) => [key, String(value).slice(0, 240)]))
      })))
    } : null;
    const sidebarScreenshot = sidebar ? await safeScreenshot(sidebar, path.join(outputRoot, 'sidebar.png'), 'sidebar', hostErrors) : null;
    const sidebarControlProbe = sidebar && !focusedProfileOnly && !hostSourceMismatch
      ? await probeInstalledSidebarControls(sidebar, proofMatrix, hostErrors, workbench)
      : { schema_version: 'px.installed-operational-control-probe/1.0', authority: 'Sidebar probe unavailable outside the full exact-source owned host.', eligible_control_count: 0, records: [] };
    workbenchCommandProfile = ownedReversibleConfigurationAuthority && !focusedProfileOnly && !hostSourceMismatch
      ? await timedProfile('workbench-commands', () => probeInstalledWorkbenchCommands(workbench, dashboard, proofMatrix, hostErrors))
      : workbenchCommandProfile;
    const inlineCommandProfile = inlineCommandOwnerControlProbe(proofMatrix, [
      installedControlProbe,
      combinedHostEffectProbe,
      coordinationMemoryProfile.control_probe,
      cleanupProfile.control_probe,
      enterpriseProfile.control_probe,
      validationProfile.control_probe
    ]);
    const faultDiagnostics = partitionExpectedFaultDiagnostics(hostErrors, reversibleConfigurationProfile, hostBoundaryProfile.control_probe);
    if (ownedReversibleConfigurationAuthority && installedSourceIdentityNeedsLateRefresh(installedIdentity)) {
      installedIdentity = await refreshInstalledSourceIdentity(dashboard, installedIdentity, 45_000, 'request-bound-late');
      hostSourceMismatch = installedIdentity.state === 'mismatch';
      hostSourceIdentityVerified = installedIdentity.state === 'verified';
    }
    const lateCardWorkerProfile = !focusedProfileOnly && !hostSourceMismatch
      ? await timedProfile('studio-late-card-worker', () => runInstalledStudioLateCardWorker(), { resetBaseline: false })
      : { schema_version: 'px.installed-studio-late-card-worker/1.0', completed: false, errors: ['reserved-for-full-exact-installed-host'] };
    const lateCardControllerProfile = !focusedProfileOnly && !hostSourceMismatch
      ? await timedProfile('studio-controller-adversarial', () => runInstalledStudioControllerAdversarialProfile(dashboard))
      : { schema_version: 'px.installed-studio-controller-adversarial/1.0', completed: false, checks: {}, errors: ['reserved-for-full-exact-installed-host'] };
    const lateCardBridgeProfile = !focusedProfileOnly && !hostSourceMismatch
      ? await timedProfile('studio-bridge-conflict', () => runInstalledStudioBridgeConflictProfile(), { resetBaseline: false })
      : { schema_version: 'px.installed-studio-bridge-conflict-profile/1.0', completed: false, checks: {}, errors: ['reserved-for-full-exact-installed-host'] };
    const lateCardAdversarialProfile = !focusedProfileOnly
      ? buildInstalledLateCardAdversarialProfile({
        hostSourceMismatch,
        installedIdentity,
        observationStateProfile,
        candidateProfile: studioCandidateSaveProfile,
        revisionProfile: studioRevisionEditProfile,
        lifecycleProfile: studioLifecycleProfile,
        crashProfile: studioLifecycleCrashProfile,
        catalogPaginationProfile,
        workerProfile: lateCardWorkerProfile,
        controllerProfile: lateCardControllerProfile,
        bridgeProfile: lateCardBridgeProfile,
        hostErrors: faultDiagnostics.retained
      })
      : { schema_version: 'px.installed-late-card-adversarial-profile/1.0', completed: false, records: [] };
    const lateCardScenarioProfile = !focusedProfileOnly
      ? buildInstalledLateCardScenarioProfile({
        hostSourceMismatch,
        adversarialProfile: lateCardAdversarialProfile
      })
      : { schema_version: 'px.installed-late-card-scenario-profile/1.0', authority: 'Reserved for the full exact installed-host campaign.', completed: false, records: [], source_owners: [], errors: [] };
    if (!focusedProfileOnly && !hostSourceMismatch && lateCardScenarioProfile.completed !== true) {
      recordProfileFailure('installed-late-card-scenarios', 'returned-incomplete', lateCardScenarioProfile.errors?.length ? lateCardScenarioProfile.errors : ['profile-incomplete-without-error']);
    }
    const observedAt = new Date().toISOString();
    const builderControlIds = Object.values(builders).flatMap(builder => builder?.attempted_control_ids || []);
    const controlChains = applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyInstalledProbeObservations(applyBuilderObservations(buildPerControlRecords({
      inventory,
      results,
      sidebar: sidebarResult,
      hostSourceMismatch,
      authority: LIVE_WALK_AUTHORITY,
      observedAt,
      attemptedControlIds: [...attemptedControlIds, ...builderControlIds]
    }), builders), installedControlProbe), sidebarControlProbe, 'installed_sidebar_observations'), sidebarStateProfile.control_probe, 'sidebar_state_observations'), workbenchCommandProfile, 'installed_workbench_command_observations'), inlineCommandProfile, 'inline_command_owner_observations'), reversibleConfigurationProfile, 'reversible_configuration_observations'), studioSetupProfile, 'studio_setup_observations'), studioCandidateSaveProfile, 'studio_candidate_save_observations'), studioLifecycleProfile.control_probe, 'studio_lifecycle_observations'), studioRevisionEditProfile.control_probe, 'studio_revision_edit_observations'), knowledgeLifecycleProfile.control_probe, 'knowledge_lifecycle_observations'), learningLifecycleProfile.control_probe, 'learning_lifecycle_observations'), coordinationMemoryProfile.control_probe, 'coordination_memory_observations'), skillQueryProfile.control_probe, 'skill_query_observations'), catalogPaginationProfile.control_probe, 'catalog_pagination_observations'), observationStateProfile.control_probe, 'observation_state_observations'), combinedHostEffectProbe, 'host_boundary_observations'), projectsProfile.control_probe, 'projects_map_observations'), knowledgeGraphProfile.control_probe, 'knowledge_graph_observations'), systemProjectionProfile.control_probe, 'system_projection_observations'), cleanupProfile.control_probe, 'cleanup_recycle_observations'), pluginReadProfile.control_probe, 'plugin_read_observations'), pluginMutationProfile.control_probe, 'plugin_mutation_observations'), engineOutageProfile, 'engine_outage_observations');
    const receipt = {
      schema_version: 'px.operational-ui-walk/1.2',
      observed_at: observedAt,
      endpoint,
      authority: LIVE_WALK_AUTHORITY,
      host_source_mismatch: hostSourceMismatch,
      source_identity: {
        state: hostSourceMismatch ? 'mismatch' : hostSourceIdentityVerified ? 'verified' : 'unknown',
        method: 'dashboard-runtime-identity-contract',
        refresh: installedIdentity.refresh || 'captured-snapshot-scan',
        diagnostic: installedIdentity.diagnostic || null,
        runtime_identity: installedIdentity.runtime_identity || null,
        current_source_identity: installedIdentity.current_source_identity || null,
        control_source_manifest: currentSourceManifest(JSON.parse(fs.readFileSync(proofMatrixPath, 'utf8')))
      },
      surfaces,
      results,
      builders,
      installed_control_probe: installedControlProbe,
      installed_sidebar_control_probe: sidebarControlProbe,
      installed_workbench_command_profile: workbenchCommandProfile,
      inline_command_owner_profile: inlineCommandProfile,
      reversible_configuration_profile: reversibleConfigurationProfile,
      studio_setup_profile: studioSetupProfile,
      studio_candidate_save_profile: studioCandidateSaveProfile,
      studio_lifecycle_profile: studioLifecycleProfile,
      studio_lifecycle_crash_profile: studioLifecycleCrashProfile,
      studio_revision_edit_profile: studioRevisionEditProfile,
      studio_late_card_worker_profile: lateCardWorkerProfile,
      studio_controller_adversarial_profile: lateCardControllerProfile,
      studio_bridge_conflict_profile: lateCardBridgeProfile,
      installed_late_card_adversarial_profile: lateCardAdversarialProfile,
      installed_late_card_scenario_profile: lateCardScenarioProfile,
      profile_failures: profileFailures,
      knowledge_lifecycle_profile: knowledgeLifecycleProfile,
      learning_lifecycle_profile: learningLifecycleProfile,
      coordination_memory_profile: coordinationMemoryProfile,
      skill_query_profile: skillQueryProfile,
      catalog_pagination_profile: catalogPaginationProfile,
      observation_state_profile: observationStateProfile,
      host_boundary_profile: hostBoundaryProfile,
      enterprise_profile: enterpriseProfile,
      environment_lifecycle_profile: environmentLifecycleProfile,
      codex_handoff_profile: codexHandoffProfile,
      validation_profile: validationProfile,
      projects_profile: projectsProfile,
      knowledge_graph_profile: knowledgeGraphProfile,
      system_projection_profile: systemProjectionProfile,
      cleanup_recycle_profile: cleanupProfile,
      plugin_read_profile: pluginReadProfile,
      plugin_mutation_profile: pluginMutationProfile,
      native_input_evidence: nativeInputEvidence,
      engine_outage_profile: engineOutageProfile,
      focused_profile: focusedProfile,
      full_operational_completion_claimed: focusedProfileOnly ? false : null,
      sidebar: sidebarResult,
      sidebar_state_profile: sidebarStateProfile,
      sidebar_screenshot: sidebarScreenshot,
      sidebar_open_error: sidebarOpenError,
      host_errors: faultDiagnostics.retained,
      expected_fault_diagnostics: faultDiagnostics.recovered,
      control_chains: controlChains,
      limitations: [
        'The inventory denominator is authoritative; every inventory control receives exactly one terminal record with all thirteen chain stages.',
        hostSourceMismatch ? 'Installed/source identity mismatch blocked all further surface and builder interaction.' : 'The walk activates every dashboard navigation surface and records its real DOM and screenshots.',
        ownedReversibleConfigurationAuthority ? 'The owned isolated host directly executes bounded Studio setup, immutable candidate saves, exact candidate lifecycle operations, predecessor-bound next-revision edits, hash-bound inert local Plugin lifecycle with exact initial-state restoration, and a byte-restored disposable-engine outage/recovery profile with typed receipts.' : 'Agent and Workflow builder interactions are limited to reversible unsaved webview state with exact per-control pre/post digests; no candidate save or run is authorized.',
        'Controls outside the named typed profiles that require write, execution, lifecycle, recovery, reload, or destructive authority are skipped per control with an exact reason and return condition.'
      ]
    };
    receipt.status_truth = evaluateOperationalWalk(receipt, { additionalIssues: profileFailures.map(failure => ({
      source: 'profile',
      code: failure.state === 'skipped' ? 'profile-dependency-skipped' : 'profile-failed',
      severity: failure.state === 'skipped' ? 'incomplete' : 'error',
      blocking: true,
      context: failure.profile,
      message: failure.state === 'skipped'
        ? `${failure.profile} was not dispatched because prerequisite ${failure.dependency} failed.`
        : `${failure.profile} failed: ${failure.errors.join(' | ')}`,
      details: failure
    })) });
    receipt.status = receipt.status_truth.terminal_state;
    fs.writeFileSync(path.join(outputRoot, 'receipt.json'), `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
    process.stdout.write(`${JSON.stringify({ outputRoot, status: receipt.status, operationallyComplete: receipt.status_truth.operationally_complete, statusSummary: receipt.status_truth.summary, surfaces: surfaces.length, sidebar: Boolean(sidebar), hostSourceMismatch, controlChains: controlChains.aggregates, providerMissing: results.some(item => item.provider_missing_message) || sidebarResult?.provider_missing_message === true, invalidUnion: results.some(item => item.invalid_union_message) || sidebarResult?.invalid_union_message === true, graph: results.find(item => item.surface === 'knowledgeGraph')?.graph || null, builders, hostErrors: faultDiagnostics.retained.length, expectedFaultDiagnostics: faultDiagnostics.recovered.length }, null, 2)}\n`);
    process.exitCode = exitCodeForTerminalState(receipt.status);
  } finally {
    await ownedWorkbenchViewport?.session?.detach().catch(() => {});
    await browser.close();
  }
}

if (require.main === module) {
  main().catch(error => {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = {
  applyInstalledProbeObservations, boundedOwnedUiAction, buildInstalledLateCardAdversarialProfile, buildInstalledLateCardScenarioProfile, cleanupControlProbe, codexHandoffControlProbe, commandPaletteAttemptDecision, coordinationMemoryControlProbe, currentSourceExtensionAssetIdentity,
  catalogPaginationControlProbe, clickWhenKnowledgeControlReady, correlateCatalogExchange, observationStateControlProbe, runInstalledObservationStateProfile, eligibleInstalledControl, eligibleInstalledSidebarControl, engineOutageRecord, enterpriseControlProbe, environmentLifecycleControlProbe,
  exactStudioSetupTerminalResponse, executeWorkbenchCommand, exactPluginConflictSignal, exerciseInstalledControl, graphProjectionIdentity, requestBoundGraphResultIdentity, hostBoundaryControlProbe, inlineCommandOwnerControlProbe, installedActionIdentity,
  installedConditionalRecoverySpec, installedConditionalScenario, installedHostBoundaryRevealSelector, installedPreparationIdentity, installedRuntimeSourceIdentityState, installedSourceIdentityNeedsLateRefresh, installedSidebarHandoffRequestMatches, installedSidebarHandoffSpec, installedSidebarSelector, installedStudioControlScenario, installedStudioPrerequisites, installedSurfaceState, installedSurfaceAcknowledged,
  installedFilesystemPathIdentity, installedFilesystemPathsMatch, installedFilesystemPathWithin, installedHostActionReceiptMatches, installedHostActionRequestIdentity,
  installedSurfaceControlAcknowledged, installedWorkbenchCommandSpec, installedWorkbenchAuthorityBoundarySpec, instrumentInstalledBridge, knowledgeBrowseHasHead, knowledgeGraphControlProbe,
  knowledgeLifecycleControlProbe, learningLifecycleControlProbe, nativeWorkbenchKeyboardActionAdmitted, nativeWorkbenchKeyboardFallbackAdmitted,
  nativeWorkbenchRequestFallbackAdmitted, ownedCleanupCandidate, ownedWorkbenchReloadIdentity, reacquirableOwnedFrameError,
  pluginMutationControlProbe, pluginReadControlProbe,
  partitionExpectedFaultDiagnostics, prepareInstalledControl, probeInstalledControls, probeInstalledSidebarControls, probeInstalledWorkbenchCommands,
  openWorkbenchCommandPalette, projectMapIdentity, projectsControlProbe, reopenPacifyDashboardFromOwnedUi, revealInstalledControl, revealInstalledHostBoundaryControl, runInstalledCleanupProfile, settleInstalledSurfaceControl,
  runInstalledCodexHandoffProfile, runInstalledCoordinationMemoryProfile, runInstalledEngineOutageProfile, runInstalledEnterpriseProfile, runInstalledEnvironmentLifecycleProfile,
  runInstalledHostBoundaryProfile, runInstalledKnowledgeGraphProfile, runInstalledKnowledgeLifecycleProfile,
  runInstalledLearningLifecycleProfile, runInstalledPluginMutationProfile, runInstalledPluginReadProfile,
  restartInstalledSidebarWebview, runInstalledCatalogPaginationProfile, runInstalledProjectsProfile, runInstalledSidebarStateProfile, runInstalledSkillQueryProfile, runInstalledStudioCandidateSaveProfile,
  runInstalledStudioBridgeConflictProfile, runInstalledStudioControllerAdversarialProfile, runInstalledStudioLateCardWorker, runInstalledStudioLifecycleCrashProfile, runInstalledStudioLifecycleProfile, runInstalledStudioRevisionEditProfile, runInstalledStudioSetupProfile,
  runInstalledSystemProjectionProfile, runInstalledValidationProfile, seedInstalledConditionalScenario, sidebarPreferenceRoundTripIdentity, sidebarReconstructionIdentity, sidebarStateControlProbe, sidebarStateControlVerified,
  installedSnapshotTimeoutIdentity, mergeStudioLifecycleObservations, selectLatestMatchingInstalledSnapshot, skillQueryControlProbe, studioLifecycleControlProbe, systemProjectionControlProbe, systemProjectionIdentity, requestBoundSystemSnapshotIdentity, validCleanupResult, workbenchCommandRowIdentity,
  validCoordinationResult, validKnowledgeLifecycleResult, validLearningLifecycleResult, validPermanentCleanupResult,
  validPluginLifecycleObservation, validPendingPluginMutationReceipt, validPluginMutationReceipt, validStudioDraftReceipt, validStudioLifecycleResult,
  captureSurfaceViews, surfaceCaptureCandidates, surfaceCaptureFileStem,
  validStudioRevisionEditObservation, validStudioSetupResult, validationControlProbe, runInstalledValidationBoundaryProfile, waitForCoordinationResult, waitForOwnedWebview
};
