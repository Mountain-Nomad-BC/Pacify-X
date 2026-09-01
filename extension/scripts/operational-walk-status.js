'use strict';

const WALK_TERMINAL_STATES = Object.freeze({
  COMPLETED: 'completed',
  INCOMPLETE: 'incomplete',
  BLOCKED: 'blocked',
  FAILED: 'failed'
});

const WALK_EXIT_CODES = Object.freeze({
  [WALK_TERMINAL_STATES.COMPLETED]: 0,
  [WALK_TERMINAL_STATES.FAILED]: 1,
  [WALK_TERMINAL_STATES.INCOMPLETE]: 2,
  [WALK_TERMINAL_STATES.BLOCKED]: 3
});

const EXACT_RECOVERED_AUTHORITY_BOUNDARY_IDS = new Set([
  'pxui.dashboard-control-plane.command.pacifyX.continueWithCodex',
  'pxui.dashboard-control-plane.command.pacifyX.refreshEnvironment',
  'pxui.dashboard-control-plane.command.pacifyX.refreshOllama',
  'pxui.dashboard-control-plane.command.pacifyX.rotateStudioApprovalIdentity',
  'pxui.dashboard-control-plane.command.pacifyX.validateControlPlane',
  'pxui.dashboard-control-plane.command.validate',
  'pxui.diagnostics.action.dynamicRepair.refreshEnvironment',
  'pxui.diagnostics.action.validate',
  'pxui.runtime-core.action.validate',
  'pxui.runtime-core.action.cleanupPermanent'
]);

function validRecoveredAuthorityBoundary(control) {
  if (!control || !EXACT_RECOVERED_AUTHORITY_BOUNDARY_IDS.has(String(control.control_id || ''))) return false;
  if (control.terminal_disposition !== 'skipped_requires_authority'
    || control.rendered !== true || control.visible !== true || control.attempted !== true
    || (Array.isArray(control.errors) && control.errors.length)) return false;
  if (![control.authority, control.reason, control.expected_effect, control.return_condition]
    .every(value => typeof value === 'string' && value.trim())) return false;
  const stages = new Map((Array.isArray(control.stages) ? control.stages : []).map(stage => [stage?.stage, stage?.status]));
  return stages.get('failure_handling') === 'observed'
    && stages.get('recovery_rollback') === 'observed'
    && [...stages.values()].some(status => !['observed', 'not_applicable'].includes(status));
}

const COMPLETE_BUILDER_DISPOSITIONS = new Set([
  'completed',
  'interaction_complete',
  'observed_complete'
]);

function canonicalSurfaceId(value) {
  return String(value || '')
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .replace(/_/g, '-')
    .toLowerCase();
}

function issue({ source, code, message, severity = 'error', blocking = true, context = null, details = null, occurrences = 1, recovered = null }) {
  return {
    source,
    code,
    severity,
    blocking: Boolean(blocking),
    message: String(message || code).slice(0, 2000),
    context: context == null ? null : String(context).slice(0, 500),
    details,
    occurrences: Number.isSafeInteger(occurrences) && occurrences > 0 ? occurrences : 1,
    recovered: typeof recovered === 'boolean' ? recovered : null
  };
}

function issueKey(item) {
  return [item.source, item.code, item.context || '', item.message].join('\u0000');
}

function dedupeIssues(items) {
  const byKey = new Map();
  for (const raw of items || []) {
    if (!raw || typeof raw !== 'object') continue;
    const normalized = issue(raw);
    const key = issueKey(normalized);
    const existing = byKey.get(key);
    if (existing) {
      existing.occurrences += normalized.occurrences;
      existing.recovered = existing.recovered === false || normalized.recovered === false
        ? false
        : existing.recovered === true || normalized.recovered === true
          ? true
          : null;
    } else {
      byKey.set(key, normalized);
    }
  }
  return [...byKey.values()].sort((left, right) =>
    `${left.source}:${left.code}:${left.context || ''}`.localeCompare(`${right.source}:${right.code}:${right.context || ''}`));
}

function isExternalVsCodeMermaidToolDiagnostic(raw) {
  if (String(raw?.source || '').toLowerCase() !== 'console') return false;
  const message = String(raw?.message || '').trim();
  const context = String(raw?.context || '').trim();
  return /^%c\s+ERR\s+color:\s+#f33\s+Tool "renderMermaidDiagram" was not contributed\.$/.test(message)
    && /^console:vscode-file:\/\/vscode-app\/.+\/resources\/app\/out\/vs\/workbench\/workbench\.desktop\.main\.js$/i.test(context.replace(/\\/g, '/'));
}

function isExternalOwnedFixtureMarketplaceDiagnostic(raw) {
  if (String(raw?.source || '').toLowerCase() !== 'console') return false;
  return String(raw?.message || '').trim() === 'Failed to load resource: the server responded with a status of 404 ()'
    && String(raw?.context || '').trim() === 'console:https://marketplace.visualstudio.com/_apis/public/gallery/vscode/px-owned/fixture/latest';
}

function normalizeHostErrors(hostErrors = []) {
  const normalized = [];
  for (const raw of Array.isArray(hostErrors) ? hostErrors : []) {
    const source = String(raw?.source || '').toLowerCase();
    const externalMermaidDiagnostic = isExternalVsCodeMermaidToolDiagnostic(raw);
    const externalOwnedFixtureDiagnostic = isExternalOwnedFixtureMarketplaceDiagnostic(raw);
    const mapping = externalMermaidDiagnostic
      ? { source: 'external_host', code: 'external-vscode-optional-tool-unavailable', severity: 'warning', blocking: false }
      : externalOwnedFixtureDiagnostic
        ? { source: 'external_host', code: 'external-vscode-owned-fixture-marketplace-miss', severity: 'warning', blocking: false }
      : source === 'console'
      ? { source: 'console', code: 'console-error' }
      : source === 'pageerror'
        ? { source: 'page', code: 'page-error' }
        : source === 'screenshot'
          ? { source: 'page', code: 'screenshot-capture-failed' }
          : { source: 'process', code: source === 'walker' ? 'walker-error' : 'unclassified-host-error' };
    normalized.push(issue({
      ...mapping,
      message: raw?.message || 'The host emitted an error without a message.',
      context: raw?.context || source || null
    }));
  }
  return dedupeIssues(normalized);
}

function exitCodeForTerminalState(terminalState) {
  return WALK_EXIT_CODES[terminalState] ?? WALK_EXIT_CODES[WALK_TERMINAL_STATES.FAILED];
}

function normalizeProcessOutput({ stdout = '', stderr = '', walkerExit = null, expectedWalkerExitCode = 0, processError = null, processTreeClosedVerified = null } = {}) {
  const stdoutLines = String(stdout || '').split(/\r?\n/).filter(Boolean);
  const stderrLines = String(stderr || '').split(/\r?\n/).filter(Boolean);
  const allLines = [...stdoutLines, ...stderrLines];
  const normalized = [];
  const unresponsive = allLines.filter(line => /extension host.*(?:is|became).*unresponsive/i.test(line));
  const responsive = allLines.filter(line => /extension host.*(?:is|became).*responsive/i.test(line) && !/unresponsive/i.test(line));
  if (unresponsive.length) {
    normalized.push(issue({
      source: 'extension_host',
      code: 'extension-host-unresponsive',
      message: unresponsive[0].trim(),
      context: 'captured-host-output',
      occurrences: unresponsive.length,
      recovered: responsive.length > 0
    }));
  }
  const tokenWarnings = allLines.filter(line => /github/i.test(line) && /token/i.test(line) && /(?:no |not |missing|unavailable|without)/i.test(line));
  if (tokenWarnings.length) {
    normalized.push(issue({
      source: 'extension_host',
      code: 'github-token-unavailable',
      severity: 'warning',
      blocking: false,
      message: tokenWarnings[0].trim(),
      context: 'captured-host-output',
      occurrences: tokenWarnings.length
    }));
  }
  const alreadyClassified = new Set([...unresponsive, ...responsive, ...tokenWarnings]);
  for (const line of stderrLines) {
    if (alreadyClassified.has(line) || !/\b(?:error|failed|failure|exception|uncaught|fatal)\b/i.test(line)) continue;
    normalized.push(issue({
      source: 'process',
      code: 'stderr-error',
      message: line.trim(),
      context: 'stderr'
    }));
  }
  if (walkerExit && (walkerExit.code !== expectedWalkerExitCode || walkerExit.signal)) {
    normalized.push(issue({
      source: 'process',
      code: 'walker-process-exit-failed',
      message: `The walker exited with code ${walkerExit.code ?? 'null'} (expected ${expectedWalkerExitCode}) and signal ${walkerExit.signal || 'none'}.`,
      context: 'walker-process'
    }));
  }
  if (processError) {
    normalized.push(issue({
      source: 'process',
      code: 'process-error',
      message: String(processError?.stack || processError?.message || processError),
      context: 'owned-host-process'
    }));
  }
  if (processTreeClosedVerified === false) {
    normalized.push(issue({
      source: 'process',
      code: 'process-tree-closure-unverified',
      message: 'The owned host process tree was not verified closed.',
      context: 'owned-host-process'
    }));
  }
  return dedupeIssues(normalized);
}

function terminalStateForIssues(issues) {
  const blocking = issues.filter(item => item.blocking);
  if (blocking.some(item => item.source === 'process' || item.source === 'page' || item.source === 'console')) {
    return WALK_TERMINAL_STATES.FAILED;
  }
  if (blocking.some(item => item.source === 'source_identity' || item.source === 'extension_host')) {
    return WALK_TERMINAL_STATES.BLOCKED;
  }
  if (blocking.length) return WALK_TERMINAL_STATES.INCOMPLETE;
  return WALK_TERMINAL_STATES.COMPLETED;
}

function summarizeIssues(issues) {
  const bySource = {};
  const bySeverity = {};
  for (const item of issues) {
    bySource[item.source] = (bySource[item.source] || 0) + item.occurrences;
    bySeverity[item.severity] = (bySeverity[item.severity] || 0) + item.occurrences;
  }
  return {
    issue_count: issues.length,
    occurrence_count: issues.reduce((total, item) => total + item.occurrences, 0),
    blocking_issue_count: issues.filter(item => item.blocking).length,
    by_source: bySource,
    by_severity: bySeverity
  };
}

function focusedProfileIssues(value) {
  const focused = String(value.focused_profile || '');
  if (!focused) return null;
  const issues = [];
  const incomplete = (code, message, details = null) => issues.push(issue({
    source: 'coverage', code, message, severity: 'incomplete', context: focused, details
  }));
  const requiredStages = ['open_load', 'display', 'user_edit_action', 'input_validation', 'authorization', 'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement', 'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'];
  const completeOwnedProbe = profile => {
    const records = Array.isArray(profile?.control_probe?.records) ? profile.control_probe.records : [];
    const eligible = Number(profile?.control_probe?.eligible_control_count || 0);
    return eligible > 0 && records.length === eligible
      && records.every(record => record?.rendered === true
        && record?.attempted === true
        && !(record?.errors || []).length
        && requiredStages.every(stage => ['present', 'not_applicable'].includes(record?.interaction_chain?.[stage]?.state)))
      && !(profile?.observation?.errors || []).length;
  };
  if (focused === 'studio-lifecycle') {
    const setup = value.studio_setup_profile?.observation;
    const candidates = value.studio_candidate_save_profile?.observations;
    const lifecycle = value.studio_lifecycle_profile?.observations;
    const revisions = value.studio_revision_edit_profile?.observations;
    if (setup?.typed_ready_result !== true || (setup?.errors || []).length) {
      incomplete('focused-studio-setup-incomplete', 'The focused Studio setup did not return a typed ready result.', setup || null);
    }
    const candidateKinds = new Set((candidates || []).filter(item => item?.attempted === true && item?.typed_creation_receipt === true && item?.reopened_catalog_match === true && !(item?.errors || []).length).map(item => item.kind));
    if (!['agent', 'workflow', 'skill'].every(kind => candidateKinds.has(kind))) {
      incomplete('focused-studio-candidates-incomplete', 'Agent, Workflow, and Skill candidates were not all saved and reopened through the installed host.', { completed_kinds: [...candidateKinds].sort() });
    }
    const lifecycleKinds = new Set((lifecycle || []).filter(item => item?.exact_catalog_selection === true && (item?.operations || []).length > 0 && (item.operations || []).every(operation => operation?.valid === true) && !(item?.errors || []).length && (!['agent', 'workflow'].includes(item.kind) || item?.durable_run_reopened === true)).map(item => item.kind));
    if (!['agent', 'workflow', 'skill'].every(kind => lifecycleKinds.has(kind))) {
      incomplete('focused-studio-lifecycle-incomplete', 'The exact Agent, Workflow, and Skill candidate lifecycle routes did not all complete.', { completed_kinds: [...lifecycleKinds].sort() });
    }
    const revisionKinds = new Set((revisions || []).filter(item => item?.attempted === true && item?.editor_bound === true && item?.typed_creation_receipt === true && item?.reopened_catalog_match === true && item?.predecessor_preserved === true && item?.content_changed === true && item?.reopened_editor_content_match === true && !(item?.errors || []).length).map(item => item.kind));
    if (!['agent', 'workflow', 'skill'].every(kind => revisionKinds.has(kind))) {
      incomplete('focused-studio-revision-edit-incomplete', 'Agent, Workflow, and Skill predecessor-bound edits were not all saved and reopened with changed content.', { completed_kinds: [...revisionKinds].sort() });
    }
  } else if (focused === 'knowledge-lifecycle') {
    const observation = value.knowledge_lifecycle_profile?.observation;
    if (observation?.attempted !== true || observation?.completed !== true || (observation?.errors || []).length) {
      incomplete('focused-knowledge-lifecycle-incomplete', 'The focused Knowledge lifecycle did not complete its source-bound mutation and refreshed-state journey.', observation || null);
    }
  } else if (focused === 'reversible-configuration') {
    const profile = value.reversible_configuration_profile;
    const records = Array.isArray(profile?.records) ? profile.records : [];
    if (!records.length || records.some(record => record?.attempted !== true || (record?.errors || []).length)) {
      incomplete('focused-configuration-incomplete', 'The focused reversible configuration journey did not complete every eligible control.', { eligible_control_count: profile?.eligible_control_count || 0, record_count: records.length });
    }
  } else if (focused === 'host-boundary') {
    const profile = value.host_boundary_profile;
    const records = Array.isArray(profile?.control_probe?.records) ? profile.control_probe.records : [];
    const eligible = Number(profile?.control_probe?.eligible_control_count || 0);
    const complete = records.length === eligible && eligible > 0 && records.every(record =>
      record?.rendered === true
      && record?.attempted === true
      && !(record?.errors || []).length
      && Object.values(record?.interaction_chain || {}).every(stage => ['present', 'not_applicable'].includes(stage?.state))
    );
    if (!complete || (profile?.observation?.errors || []).length) {
      incomplete('focused-host-boundary-incomplete', 'The focused host-boundary journey did not complete every eligible typed host handoff and required recovery stage.', { eligible_control_count: eligible, record_count: records.length, profile_errors: profile?.observation?.errors || [] });
    }
  } else if (focused === 'native-dialog-boundary') {
    const profiles = [
      ['enterprise', value.enterprise_profile],
      ['projects', value.projects_profile],
      ['plugin-mutation', value.plugin_mutation_profile]
    ];
    const incompleteProfiles = profiles.filter(([, profile]) => !completeOwnedProbe(profile)).map(([name, profile]) => ({
      name,
      eligible_control_count: Number(profile?.control_probe?.eligible_control_count || 0),
      record_count: Array.isArray(profile?.control_probe?.records) ? profile.control_probe.records.length : 0,
      errors: profile?.observation?.errors || []
    }));
    if (incompleteProfiles.length) {
      incomplete('focused-native-dialog-boundary-incomplete', 'The focused native-dialog journey did not complete Enterprise, Projects, and Plugin mutation through exact typed postconditions and recovery.', { incomplete_profiles: incompleteProfiles });
    }
  } else if (focused === 'codex-handoff') {
    const profile = value.codex_handoff_profile;
    if (!completeOwnedProbe(profile)) {
      incomplete('focused-codex-handoff-incomplete', 'The focused Codex handoff journey did not complete the exact contributed command and Runtime Core continue/cancel controls through their required recovery stages.', {
        eligible_control_count: Number(profile?.control_probe?.eligible_control_count || 0),
        record_count: Array.isArray(profile?.control_probe?.records) ? profile.control_probe.records.length : 0,
        profile_errors: profile?.observation?.errors || []
      });
    }
  } else if (focused === 'late-card-repair') {
    const observation = value.observation_state_profile;
    const graph = observation?.observations?.['pxui.knowledge-graph.action.graphLoadAll'];
    const controller = value.studio_controller_adversarial_profile;
    const requiredControllerChecks = [
      'stale_allocation_ignored',
      'cross_kind_allocation_ignored',
      'cancelled_allocation_cannot_reopen',
      'physical_skill_hash_substitution_rejected',
      'incoming_trust_released',
      'initial_conflict_rejected'
    ];
    const observationComplete = completeOwnedProbe(observation)
      && graph?.rendered === true
      && graph?.attempted === true
      && graph?.cancelled === true
      && graph?.recovered === true
      && graph?.completed === true;
    const controllerComplete = controller?.completed === true
      && !(controller?.errors || []).length
      && requiredControllerChecks.every(name => controller?.checks?.[name] === true)
      && Object.values(controller?.checks || {}).length > 0
      && Object.values(controller.checks).every(value => value === true);
    if (!observationComplete || !controllerComplete) {
      incomplete('focused-late-card-repair-incomplete', 'The focused repair journey did not complete the exact graph cancellation/recovery and Studio trust-release correlation boundaries.', {
        observation_complete: observationComplete,
        graph: graph || null,
        controller_complete: controllerComplete,
        failed_controller_checks: requiredControllerChecks.filter(name => controller?.checks?.[name] !== true),
        controller_errors: controller?.errors || []
      });
    }
  } else if (focused === 'builder') {
    const builders = value.builders && typeof value.builders === 'object' ? value.builders : {};
    const incompleteBuilders = ['agent', 'workflow'].filter(kind => {
      const builder = builders[kind];
      return builder?.terminal_disposition !== 'interaction_complete'
        || builder?.durability?.verified !== true
        || builder?.cleanup?.modal_closed !== true
        || builder?.cleanup?.candidate_saved !== false
        || builder?.cleanup?.runtime_executed !== false
        || !Array.isArray(builder?.attempted_control_ids)
        || !builder.attempted_control_ids.includes(`pxui.${kind === 'agent' ? 'agent' : 'workflow'}-studio.action.studioApplyJson`)
        || !builder.attempted_control_ids.includes(`pxui.${kind === 'agent' ? 'agent' : 'workflow'}-studio.action.resumeWorkingStudioDraft`);
    });
    if (incompleteBuilders.length) {
      incomplete('focused-builder-incomplete', 'The focused builder journey did not complete exact malformed-JSON rejection, recovery, working-draft reopen, and no-effect cleanup for both Agent and Workflow.', {
        incomplete_builders: incompleteBuilders,
        builders: Object.fromEntries(incompleteBuilders.map(kind => [kind, builders[kind] || null]))
      });
    }
  } else if (focused === 'error-indicators') {
    const requiredIds = new Set([
      'pxui.memory.indicator.queryError',
      'pxui.knowledge-core.indicator.controllerError'
    ]);
    const profile = value.installed_control_probe;
    const records = Array.isArray(profile?.records) ? profile.records : [];
    const observedIds = records.map(record => String(record?.control_id || ''));
    const exactIdentity = records.length === requiredIds.size
      && new Set(observedIds).size === requiredIds.size
      && observedIds.every(controlId => requiredIds.has(controlId));
    const complete = Number(profile?.eligible_control_count || 0) === requiredIds.size
      && exactIdentity
      && records.every(record =>
        record?.rendered === true
        && record?.observed === true
        && !(record?.errors || []).length
        && Object.keys(record?.interaction_chain || {}).length === requiredStages.length
        && requiredStages.every(stageName => {
          const stage = record?.interaction_chain?.[stageName];
          return (
          ['present', 'not_applicable'].includes(stage?.state)
          && Array.isArray(stage?.evidence)
          && stage.evidence.length > 0
          );
        })
      );
    if (!complete) {
      incomplete('focused-error-indicators-incomplete', 'The focused error-indicator journey did not prove both exact request-bound failure and recovery chains without substitution.', {
        required_control_ids: [...requiredIds],
        observed_control_ids: observedIds,
        eligible_control_count: Number(profile?.eligible_control_count || 0)
      });
    }
  } else {
    incomplete('focused-profile-unsupported', `The focused operational profile ${focused} has no scoped completion contract.`);
  }
  return { focused, issues };
}

function evaluateOperationalWalk(receipt, { additionalIssues = [] } = {}) {
  const value = receipt && typeof receipt === 'object' ? receipt : {};
  const issues = [...normalizeHostErrors(value.host_errors), ...(additionalIssues || [])];
  const declaredSourceIdentityState = String(value.source_identity?.state || '');
  const sourceIdentityState = value.host_source_mismatch === true || declaredSourceIdentityState === 'mismatch'
    ? 'mismatch'
    : declaredSourceIdentityState === 'verified'
      ? 'verified'
      : declaredSourceIdentityState === 'unknown'
        ? 'unknown'
      : value.host_source_mismatch === false
        ? 'reported_match'
        : 'unknown';
  if (sourceIdentityState === 'mismatch') {
    issues.push(issue({
      source: 'source_identity',
      code: 'host-source-identity-mismatch',
      message: 'The loaded extension host assets differ from the source that supplied the walker and inventory.',
      context: 'extensionDevelopmentPath'
    }));
  } else if (sourceIdentityState === 'unknown' || sourceIdentityState === 'reported_match') {
    issues.push(issue({
      source: 'source_identity',
      code: sourceIdentityState === 'unknown' ? 'host-source-identity-unknown' : 'host-source-identity-unverified',
      severity: 'incomplete',
      message: sourceIdentityState === 'unknown'
        ? 'The walk receipt does not state whether loaded host assets match the source authority.'
        : 'The walk reports no mismatch but does not retain a positive loaded-asset identity verification.'
    }));
  }

  if (value.sidebar_open_error) {
    issues.push(issue({ source: 'page', code: 'sidebar-open-failed', message: value.sidebar_open_error, context: 'sidebar' }));
  }
  const observedDocuments = [...(Array.isArray(value.results) ? value.results : []), value.sidebar].filter(Boolean);
  if (observedDocuments.some(item => item.provider_missing_message === true)) {
    issues.push(issue({ source: 'page', code: 'view-provider-missing', message: 'A walked surface reported that no data provider was registered.' }));
  }
  if (observedDocuments.some(item => item.invalid_union_message === true)) {
    issues.push(issue({ source: 'page', code: 'sidebar-inbound-message-invalid', message: 'A walked surface emitted sidebar-inbound-message-invalid:type:invalid_union.' }));
  }

  const focusedEvaluation = focusedProfileIssues(value);
  if (focusedEvaluation) issues.push(...focusedEvaluation.issues);
  const chain = value.control_chains;
  const controls = Array.isArray(chain?.controls) ? chain.controls : [];
  const declaredControlCount = Number(chain?.aggregates?.control_count ?? chain?.inventory?.control_count);
  const controlCount = Number.isSafeInteger(declaredControlCount) && declaredControlCount >= 0 ? declaredControlCount : controls.length;
  const attemptableKinds = new Set(['action', 'field', 'form', 'menu', 'editor', 'gesture', 'command']);
  const attemptableControls = controls.filter(control => !control?.kind || attemptableKinds.has(control.kind));
  const attemptedControlCount = controls.filter(control => control?.attempted === true).length;
  const attemptedAttemptableControlCount = attemptableControls.filter(control => control?.attempted === true).length;
  const completeChainCount = Number(chain?.aggregates?.complete_interaction_chains);
  const authoritySkippedControls = controls.filter(control => control?.terminal_disposition === 'skipped_requires_authority');
  const recoveredAuthorityBoundaries = authoritySkippedControls.filter(validRecoveredAuthorityBoundary);
  const invalidAuthorityBoundaries = authoritySkippedControls.filter(control => !validRecoveredAuthorityBoundary(control));
  const acceptedCoverageCount = (Number.isSafeInteger(completeChainCount) ? completeChainCount : 0) + recoveredAuthorityBoundaries.length;
  if (!chain || !Array.isArray(chain.controls) || !Number.isSafeInteger(controlCount) || controlCount < 1 || controls.length !== controlCount) {
    issues.push(issue({
      source: 'process',
      code: 'control-chain-receipt-invalid',
      message: `The control-chain receipt is missing or inconsistent (${controls.length} records / ${controlCount} declared).`,
      context: 'receipt-contract'
    }));
  } else if (!focusedEvaluation) {
    if (invalidAuthorityBoundaries.length) {
      issues.push(issue({
        source: 'coverage',
        code: 'authority-boundaries-invalid',
        severity: 'incomplete',
        message: `${invalidAuthorityBoundaries.length} authority-skipped control records are not exact rendered, attempted, error-free refusal-and-recovery boundaries.`,
        details: { control_ids: invalidAuthorityBoundaries.map(control => control.control_id).sort() }
      }));
    }
    if (attemptedAttemptableControlCount < attemptableControls.length) {
      issues.push(issue({
        source: 'coverage',
        code: 'controls-unattempted',
        severity: 'incomplete',
        message: `${attemptableControls.length - attemptedAttemptableControlCount} of ${attemptableControls.length} interactive controls were not attempted.`,
        details: {
          control_count: controlCount,
          attemptable_control_count: attemptableControls.length,
          attempted_control_count: attemptedControlCount,
          attempted_attemptable_control_count: attemptedAttemptableControlCount
        }
      }));
    }
    if (!Number.isSafeInteger(completeChainCount) || acceptedCoverageCount < controlCount) {
      issues.push(issue({
        source: 'coverage',
        code: 'control-chains-incomplete',
        severity: 'incomplete',
        message: `${Number.isSafeInteger(completeChainCount) ? completeChainCount : 0} complete interaction chains plus ${recoveredAuthorityBoundaries.length} exact recovered authority boundaries cover ${acceptedCoverageCount} of ${controlCount} controls.`,
        details: { control_count: controlCount, complete_interaction_chains: Number.isSafeInteger(completeChainCount) ? completeChainCount : 0, recovered_authority_boundaries: recoveredAuthorityBoundaries.length, accepted_coverage_count: acceptedCoverageCount }
      }));
    }
  }

  const builders = value.builders && typeof value.builders === 'object' ? value.builders : {};
  if (!focusedEvaluation) for (const kind of ['agent', 'workflow']) {
    const disposition = String(builders[kind]?.terminal_disposition || 'missing');
    if (!COMPLETE_BUILDER_DISPOSITIONS.has(disposition)) {
      issues.push(issue({
        source: 'coverage',
        code: `${kind}-builder-incomplete`,
        severity: 'incomplete',
        message: `The ${kind} builder terminal disposition is ${disposition}.`,
        context: `${kind}-builder`,
        details: { terminal_disposition: disposition }
      }));
    }
  }

  const expectedSurfaceIds = new Set(controls.map(control => canonicalSurfaceId(control?.surface_id)).filter(Boolean));
  const observedSurfaceIds = new Set();
  for (const result of Array.isArray(value.results) ? value.results : []) {
    if (result?.navigation_active === true) observedSurfaceIds.add(canonicalSurfaceId(result.surface));
  }
  if (value.endpoint && value.host_source_mismatch === false) observedSurfaceIds.add('dashboard-control-plane');
  if (value.sidebar) observedSurfaceIds.add('sidebar');
  if (COMPLETE_BUILDER_DISPOSITIONS.has(String(builders.agent?.terminal_disposition || ''))) observedSurfaceIds.add('agent-studio');
  if (COMPLETE_BUILDER_DISPOSITIONS.has(String(builders.workflow?.terminal_disposition || ''))) observedSurfaceIds.add('workflow-studio');
  for (const surface of Array.isArray(value.modal_surfaces) ? value.modal_surfaces : []) {
    if (COMPLETE_BUILDER_DISPOSITIONS.has(String(surface?.terminal_disposition || ''))) observedSurfaceIds.add(canonicalSurfaceId(surface.surface_id));
  }
  const missingSurfaceIds = [...expectedSurfaceIds].filter(surfaceId => !observedSurfaceIds.has(surfaceId)).sort();
  if (missingSurfaceIds.length && !focusedEvaluation) {
    issues.push(issue({
      source: 'coverage',
      code: 'surfaces-not-observed',
      severity: 'incomplete',
      message: `${missingSurfaceIds.length} inventory surfaces lack a completed live observation.`,
      details: { missing_surface_ids: missingSurfaceIds }
    }));
  }

  const normalizedIssues = dedupeIssues(issues);
  const terminalState = terminalStateForIssues(normalizedIssues);
  return {
    schema_version: 'px.operational-ui-walk-status/1.0',
    terminal_state: terminalState,
    operationally_complete: terminalState === WALK_TERMINAL_STATES.COMPLETED && !focusedEvaluation,
    scope_complete: terminalState === WALK_TERMINAL_STATES.COMPLETED,
    evaluated_scope: focusedEvaluation?.focused || 'full-operational-walk',
    source_identity: {
      state: sourceIdentityState,
      method: value.source_identity?.method || null
    },
    coverage: {
      control_count: controlCount,
      attemptable_control_count: attemptableControls.length,
      attempted_control_count: attemptedControlCount,
      attempted_attemptable_control_count: attemptedAttemptableControlCount,
      complete_interaction_chains: Number.isSafeInteger(completeChainCount) ? completeChainCount : 0,
      recovered_authority_boundary_count: recoveredAuthorityBoundaries.length,
      recovered_authority_boundary_ids: recoveredAuthorityBoundaries.map(control => control.control_id).sort(),
      accepted_coverage_count: acceptedCoverageCount,
      expected_surface_ids: [...expectedSurfaceIds].sort(),
      observed_surface_ids: [...observedSurfaceIds].sort(),
      missing_surface_ids: missingSurfaceIds
    },
    summary: summarizeIssues(normalizedIssues),
    issues: normalizedIssues
  };
}

function evaluateLauncherTerminal({ walkStatus = null, processTreeClosedVerified = null, workerExitVerified = null, error = null } = {}) {
  const issues = Array.isArray(walkStatus?.issues) ? [...walkStatus.issues] : [];
  if (!walkStatus || typeof walkStatus !== 'object') {
    issues.push(issue({ source: 'process', code: 'walk-status-missing', message: 'The child did not retain a typed walk status.' }));
  }
  if (processTreeClosedVerified !== true) {
    issues.push(issue({ source: 'process', code: 'owner-process-tree-closure-unverified', message: 'The owner did not verify closure of the complete child process tree.' }));
  }
  if (workerExitVerified !== true) {
    issues.push(issue({ source: 'process', code: 'owned-worker-exit-unverified', message: 'The owned worker exit was not verified.' }));
  }
  if (error) {
    issues.push(issue({ source: 'process', code: 'launcher-error', message: String(error?.stack || error?.message || error) }));
  }
  const normalizedIssues = dedupeIssues(issues);
  const terminalState = terminalStateForIssues(normalizedIssues);
  return {
    schema_version: 'px.operational-ui-launcher-status/1.0',
    terminal_state: terminalState,
    operationally_complete: terminalState === WALK_TERMINAL_STATES.COMPLETED,
    walk_terminal_state: walkStatus?.terminal_state || null,
    summary: summarizeIssues(normalizedIssues),
    issues: normalizedIssues
  };
}

function evaluateBootstrapActivation({ bootstrap = null, storageBoundary = null, additionalIssues = [] } = {}) {
  const value = bootstrap && typeof bootstrap === 'object' ? bootstrap : {};
  const boundary = storageBoundary && typeof storageBoundary === 'object' ? storageBoundary : {};
  const issues = [...(additionalIssues || [])];
  const required = [
    ['status', 'ready', 'bootstrap-not-ready', 'The installed extension bootstrap did not reach ready status.'],
    ['extension_found', true, 'extension-not-found', 'The exact installed extension was not discovered by the isolated host.'],
    ['activation_completed', true, 'activation-not-completed', 'The exact installed extension did not complete activation.'],
    ['command_registered', true, 'dashboard-command-not-registered', 'The dashboard command was not registered after activation.'],
    ['command_executed', true, 'dashboard-command-not-executed', 'The registered dashboard command did not execute successfully.']
  ];
  for (const [field, expected, code, message] of required) {
    if (value[field] !== expected) issues.push(issue({ source: 'extension_host', code, message, context: field }));
  }
  if (boundary.verified !== true) {
    issues.push(issue({
      source: 'process',
      code: 'shared-storage-boundary-unverified',
      message: 'The isolated host did not positively verify owned or in-memory shared storage without user-scoped storage.',
      context: 'shared-data-dir'
    }));
  }
  const normalizedIssues = dedupeIssues(issues);
  const terminalState = terminalStateForIssues(normalizedIssues);
  return {
    schema_version: 'px.operational-host-bootstrap-status/1.0',
    terminal_state: terminalState,
    operationally_complete: terminalState === WALK_TERMINAL_STATES.COMPLETED,
    bootstrap_ready: value.status === 'ready',
    extension_found: value.extension_found === true,
    activation_completed: value.activation_completed === true,
    command_registered: value.command_registered === true,
    command_executed: value.command_executed === true,
    storage_boundary_verified: boundary.verified === true,
    summary: summarizeIssues(normalizedIssues),
    issues: normalizedIssues
  };
}

module.exports = {
  WALK_EXIT_CODES,
  WALK_TERMINAL_STATES,
  dedupeIssues,
  evaluateBootstrapActivation,
  evaluateLauncherTerminal,
  evaluateOperationalWalk,
  exitCodeForTerminalState,
  isExternalOwnedFixtureMarketplaceDiagnostic,
  isExternalVsCodeMermaidToolDiagnostic,
  normalizeHostErrors,
  normalizeProcessOutput,
  validRecoveredAuthorityBoundary
};
