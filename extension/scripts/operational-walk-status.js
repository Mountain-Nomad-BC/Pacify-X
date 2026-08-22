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

function normalizeHostErrors(hostErrors = []) {
  const normalized = [];
  for (const raw of Array.isArray(hostErrors) ? hostErrors : []) {
    const source = String(raw?.source || '').toLowerCase();
    const mapping = source === 'console'
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

  const chain = value.control_chains;
  const controls = Array.isArray(chain?.controls) ? chain.controls : [];
  const declaredControlCount = Number(chain?.aggregates?.control_count ?? chain?.inventory?.control_count);
  const controlCount = Number.isSafeInteger(declaredControlCount) && declaredControlCount >= 0 ? declaredControlCount : controls.length;
  const attemptedControlCount = controls.filter(control => control?.attempted === true).length;
  const completeChainCount = Number(chain?.aggregates?.complete_interaction_chains);
  if (!chain || !Array.isArray(chain.controls) || !Number.isSafeInteger(controlCount) || controlCount < 1 || controls.length !== controlCount) {
    issues.push(issue({
      source: 'process',
      code: 'control-chain-receipt-invalid',
      message: `The control-chain receipt is missing or inconsistent (${controls.length} records / ${controlCount} declared).`,
      context: 'receipt-contract'
    }));
  } else {
    if (attemptedControlCount < controlCount) {
      issues.push(issue({
        source: 'coverage',
        code: 'controls-unattempted',
        severity: 'incomplete',
        message: `${controlCount - attemptedControlCount} of ${controlCount} controls were not attempted.`,
        details: { control_count: controlCount, attempted_control_count: attemptedControlCount }
      }));
    }
    if (!Number.isSafeInteger(completeChainCount) || completeChainCount < controlCount) {
      issues.push(issue({
        source: 'coverage',
        code: 'control-chains-incomplete',
        severity: 'incomplete',
        message: `${Number.isSafeInteger(completeChainCount) ? completeChainCount : 0} of ${controlCount} controls have complete interaction chains.`,
        details: { control_count: controlCount, complete_interaction_chains: Number.isSafeInteger(completeChainCount) ? completeChainCount : 0 }
      }));
    }
  }

  const builders = value.builders && typeof value.builders === 'object' ? value.builders : {};
  for (const kind of ['agent', 'workflow']) {
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
  if (missingSurfaceIds.length) {
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
    operationally_complete: terminalState === WALK_TERMINAL_STATES.COMPLETED,
    source_identity: {
      state: sourceIdentityState,
      method: value.source_identity?.method || null
    },
    coverage: {
      control_count: controlCount,
      attempted_control_count: attemptedControlCount,
      complete_interaction_chains: Number.isSafeInteger(completeChainCount) ? completeChainCount : 0,
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
  normalizeHostErrors,
  normalizeProcessOutput
};
