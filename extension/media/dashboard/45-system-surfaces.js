'use strict';

(() => {
  const dashboard = globalThis.PXDashboard;
  if (!dashboard) throw new Error('PXDashboard foundation must load before system surfaces.');
  const components = dashboard.require('components');
  const { escapeHtml: esc, number, badge, card, section, empty } = components;

  function requireContext(context) {
    if (!context || typeof context !== 'object') throw new TypeError('System surface context is required.');
    if (!context.state?.snapshot) throw new TypeError('System surfaces require a canonical snapshot.');
    if (typeof context.serviceGrid !== 'function' || typeof context.catalogPanel !== 'function') {
      throw new TypeError('System surfaces require service-grid and catalog-panel renderers.');
    }
    if (!context.healthState || typeof context.healthState.operational !== 'function' || typeof context.healthState.feature !== 'function') {
      throw new TypeError('System surfaces require the canonical health-state interpreter.');
    }
    return context;
  }

  function readinessScoreAttribute(value) {
    const numeric = Number(value);
    const bounded = Number.isFinite(numeric) ? Math.min(5, Math.max(0, numeric)) : 0;
    return esc(String(Number(bounded.toFixed(4))));
  }

  function readinessMatrix(context) {
    const readiness = context.state.snapshot.readiness || { dimensions: [], summary: {}, maturity: {} };
    const snapshot = context.state.snapshot || {};
    const freshness = String(snapshot.environment?.freshness?.state || 'unavailable').toLowerCase();
    const operationalBlockers = [];
    if (snapshot.extensionIdentity?.matches !== true) {
      operationalBlockers.push('Host/source identity mismatch');
    }
    if (snapshot.project?.map?.valid !== true) {
      operationalBlockers.push('Project map is unavailable or stale');
    }
    if (snapshot.memory?.retrieval_ready !== true) {
      operationalBlockers.push('Canonical memory is not ready');
    }
    if (Number(snapshot.runtime?.core?.counters?.failures || 0) > 0) {
      operationalBlockers.push(`${number(snapshot.runtime.core.counters.failures)} runtime failures are retained`);
    }
    if (freshness === 'stale') {
      operationalBlockers.push('Environment inventory is stale');
    }
    const mcp = snapshot.observability?.mcp || {};
    if (mcp.runtime_verified !== true) {
      operationalBlockers.push('MCP runtime verification is not current');
    }
    const rows = (readiness.dimensions || []).map(item => `<button class="readiness-row" data-action="inspectReadiness" data-readiness-id="${esc(item.id)}"><span><b>${esc(item.id)}</b><strong>${esc(item.name)}</strong><small>${esc(item.question)}</small></span><span class="readiness-meter" aria-label="${esc(`${item.score} of ${item.maximum}`)}"><i data-readiness-score="${readinessScoreAttribute(item.score)}"></i></span><span>${badge(`${item.score}/${item.maximum}`, item.status === 'ready' ? 'success' : item.status === 'partial' ? 'warning' : 'neutral')}</span><span>${item.blocking ? badge('CEILING', 'info') : badge(String(item.status || 'unknown').toUpperCase(), item.status === 'ready' ? 'success' : 'neutral')}</span><b>EXPLAIN</b></button>`).join('');
    const gaps = (readiness.priority_gaps || []).map(value => `<li>${esc(value)}</li>`).join('');
    const noteLabel = operationalBlockers.length ? 'Live readiness blockers' : 'Advisory structural assessment';
    const noteText = operationalBlockers.length
      ? `${operationalBlockers.length} live blockers are currently blocking operational readiness: ${operationalBlockers.join('; ')}`
      : readiness.score_cap_reason || readiness.authority || 'Fresh certification remains separate.';
    return `<div class="readiness-summary"><div><span>MATURITY</span><strong>Level ${number(readiness.maturity?.level)}</strong><small>${esc(readiness.maturity?.label || 'Unavailable')}</small></div><div><span>STRUCTURAL CEILING</span><strong>${number(readiness.maturity?.readiness_ceiling)}/5</strong><small>fresh E2E gate required for 5</small></div><div><span>READY DIMENSIONS</span><strong>${number(readiness.summary?.ready)}/9</strong><small>${number(readiness.summary?.partial)} partial</small></div><div><span>OPEN GAPS</span><strong>${number(readiness.summary?.gaps)}</strong><small>explicit, never inferred away</small></div></div><div class="readiness-note"><b>${noteLabel}</b><span>${esc(noteText)}</span><button class="px-owned-control" data-action="inspectReadinessReport">Human + JSON report</button></div><div class="readiness-table">${rows || empty('Readiness evidence is unavailable from this engine version.')}</div>${gaps ? `<div class="readiness-gaps"><strong>Priority gaps</strong><ol>${gaps}</ol></div>` : ''}`;
  }

  function diagnostics(context) {
    const { state, serviceGrid, catalogPanel } = requireContext(context);
    const snapshot = state.snapshot;
    const validation = snapshot.validation || { status: 'not-run', detail: 'Not run' };
    const connection = context.healthState.operational(snapshot);
    const featureIds = ['projectMap', 'canonicalMemory', 'coordination', 'turbovec', 'enterpriseCatalog'];
    const availableFeatures = featureIds.filter(id => context.healthState.feature(snapshot, id).available).length;
    const identityMatches = snapshot.extensionIdentity?.matches === true; const extensionLabel = identityMatches ? 'Exact identity' : snapshot.extensionIdentity ? 'Mismatch' : 'Unavailable';
    const extensionDetail = identityMatches ? `host/source v${snapshot.extensionIdentity?.host?.version || 'unknown'}` : (snapshot.extensionIdentity?.mismatch_reasons || ['identity unavailable']).join(', ');
    const traces = [];
    if (!identityMatches) traces.push({ id: 'host-identity', severity: 'critical', cause: extensionDetail, owner: 'VS Code extension host + installed Pacify-X assets', evidence: `host ${snapshot.extensionIdentity?.host?.version || 'unknown'} / source ${snapshot.extensionIdentity?.source?.version || snapshot.source?.version || 'unknown'}`, repair: 'refresh', repairLabel: 'Re-read identity', verify: 'Host and source version, assets, protocol, and message schema must all match.' });
    if (snapshot.project?.map?.valid !== true) traces.push({ id: 'project-map', severity: 'high', cause: (snapshot.project?.map?.errors || [snapshot.project?.map?.error || 'Project map is unavailable.']).join('; '), owner: 'runtime.project_intelligence', evidence: snapshot.project?.map?.map_revision || 'no current map revision', repair: 'buildRepositoryGraph', repairLabel: 'Rebuild map', verify: 'A new sealed map receipt must be visible and valid.' });
    if (snapshot.memory?.retrieval_ready !== true) traces.push({ id: 'canonical-memory', severity: 'high', cause: snapshot.memory?.error || 'Canonical workspace, project registration, or active lease is incomplete.', owner: 'canonical workspace memory vault', evidence: snapshot.memory?.status || 'detached', repair: 'configureCanonicalMemory', repairLabel: 'Repair memory setup', verify: 'Workspace configuration, project registration, vault, lease, and retrieval must all be current.' });
    if (Number(snapshot.runtime?.core?.counters?.failures || 0) > 0) traces.push({ id: 'runtime-failures', severity: 'high', cause: `${number(snapshot.runtime.core.counters.failures)} work-plane failures are retained.`, owner: 'runtime.work_admission', evidence: snapshot.runtime.core.last_delta?.result_sha256 || 'inspect retained operation history', surface: 'runtimeCore', repairLabel: 'Open Runtime Core', verify: 'Inspect exact failed operations; a later successful event does not erase retained failure evidence.' });
    const skillBoundary = snapshot.runtime?.skill_host_boundary || {};
    const globalSkillCount = Number(skillBoundary.codex_host?.global_skill_count || 0);
    if (globalSkillCount > 0) traces.push({ id: 'host-skill-reappearance', severity: 'high', cause: `${number(globalSkillCount)} user-global skill package${globalSkillCount === 1 ? '' : 's'} are directly visible to the Codex host outside PX broker enforcement.`, owner: 'Codex host skill discovery', evidence: skillBoundary.codex_host?.global_skill_root || 'global skill root unavailable', surface: 'skillsTools', repairLabel: 'Inspect skill boundary', verify: 'The host-visible global count is zero, or each remaining package is explicitly accepted as host-owned exposure.' });
    const inventoryFreshness = String(snapshot.environment?.freshness?.state || 'unavailable').toLowerCase();
    if (inventoryFreshness === 'stale') traces.push({ id: 'environment-inventory-stale', severity: 'high', cause: 'The retained environment/plugin inventory exceeded its declared freshness window and its records are suppressed.', owner: 'extension discoveryManager', evidence: `generation ${snapshot.environment?.freshness?.generation || 'unknown'} / expired ${snapshot.environment?.freshness?.expires_utc || 'unknown'}`, repair: 'refreshEnvironment', repairLabel: 'Refresh inventory', verify: 'A new hash-bound inventory reports fresh or memory-current and a current capture timestamp.' });
    const mcp = snapshot.observability?.mcp || {};
    if (mcp.runtime_verified !== true) traces.push({ id: 'mcp-runtime-unverified', severity: mcp.registered ? 'warning' : 'high', cause: mcp.detail || (mcp.registered ? 'The MCP definition is registered but no successful host invocation has verified its runtime.' : 'The host has not registered the Pacify-X MCP definition.'), owner: 'VS Code MCP host + Pacify-X stdio server', evidence: String(mcp.status || 'unavailable'), surface: 'settings', repairLabel: 'Inspect MCP boundary', verify: 'The host reports runtime_verified only after a successful real stdio server invocation.' });
    const punchCards = state.operationalCardsData || snapshot.completion?.operational_punch_cards || {};
    const ledgerProgress = punchCards.progress || {};
    if (Number(punchCards.open_count || 0) > 0) traces.push({ id: 'open-operational-punch-cards', severity: 'high', cause: `${number(punchCards.open_count)} operational findings are not closed.`, owner: punchCards.source || 'operational surface audit ledger', evidence: `${number(punchCards.count)} retained cards / source ${punchCards.source_created_utc || 'date unavailable'}`, surface: 'diagnostics', repairLabel: 'Review cards below', verify: 'Each card must retain direct repair evidence and a closed or accepted state; file presence alone is insufficient.' });
    const placement = snapshot.runtime?.execution_placement || {};
    if (placement.available !== true) traces.push({ id: 'execution-placement-unavailable', severity: 'warning', cause: (placement.limitations || ['No current execution-placement lifecycle artifact is available.']).join('; '), owner: 'runtime execution-placement controller', evidence: placement.artifact_root || 'placement artifact root unavailable', surface: 'runtimeCore', repairLabel: 'Open Runtime Core', verify: 'A current decision artifact exposes selected route, CPU fallback, compatibility, and benchmark/evidence boundaries.' });
    for (const item of (snapshot.attention || []).slice(0, 8)) traces.push({ id: item.title || 'attention', severity: item.severity || 'warning', cause: item.detail || 'No detail was reported.', owner: 'snapshot attention producer', evidence: item.title || 'attention record', surface: 'assurance', repairLabel: 'Open assurance', verify: 'The producing subsystem must remove the attention item from a refreshed snapshot.' });
    const traceRows = traces.slice(0, 12).map(item => `<article class="diagnostic-trace"><header><div><strong>${esc(item.id)}</strong><small>${esc(item.owner)}</small></div><span class="diagnostic-state ${esc(item.severity)}">${esc(String(item.severity).toUpperCase())}</span></header><p>${esc(item.cause)}</p><dl><div><dt>Evidence</dt><dd class="mono">${esc(item.evidence)}</dd></div><div><dt>Post-repair verification</dt><dd>${esc(item.verify)}</dd></div></dl><div class="action-grid"><button data-action="inspectDiagnosticRecord" data-diagnostic-id="${esc(item.id)}" data-cause="${esc(item.cause)}" data-owner="${esc(item.owner)}" data-evidence="${esc(item.evidence)}" data-verification="${esc(item.verify)}">Inspect trace</button>${item.repair ? `<button class="primary" data-action="${item.repair}">${esc(item.repairLabel)}</button>` : `<button class="primary" data-surface="${esc(item.surface)}">${esc(item.repairLabel)}</button>`}</div></article>`).join('');
    const stateNames = ['discovered','reproduced','scoped','approved','implementing','implemented','narrowly_verified','integrated','operationally_verified','closed','blocked','deferred','superseded','reopened'];
    const stateTiles = stateNames.map(name => `<div><span>${esc(name.replaceAll('_', ' ').toUpperCase())}</span><b>${number(ledgerProgress[name] || 0)}</b></div>`).join('');
    const punchProgress = `<div class="punch-ledger-progress"><div><span>TOTAL GAPS</span><b>${number(ledgerProgress.gaps_discovered || 0)}</b><small>${number(ledgerProgress.unassigned || 0)} unassigned</small></div><div><span>SURFACES EXAMINED</span><b>${number(ledgerProgress.surfaces_examined || 0)} / ${number(ledgerProgress.total_known_surfaces || 0)}</b><small>${number(ledgerProgress.surfaces_not_yet_examined_count ?? (ledgerProgress.surfaces_not_yet_examined || []).length)} unresolved</small></div><div><span>CONTROL DISPOSITIONS</span><b>${number(ledgerProgress.controls_with_disposition || 0)} / ${number(ledgerProgress.known_controls || 0)}</b><small>${number(ledgerProgress.controls_not_yet_disposed || 0)} unresolved</small></div><div><span>EVIDENCE GAPS</span><b>${number(ledgerProgress.cards_lacking_required_evidence_count ?? (ledgerProgress.cards_lacking_required_evidence || []).length)}</b><small>${number(ledgerProgress.cards_with_unbound_evidence_count ?? (ledgerProgress.cards_with_unbound_evidence || []).length)} unbound histories</small></div><div><span>REPORT FINDINGS</span><b>${number(ledgerProgress.report_findings_reconciled || 0)} / ${number(ledgerProgress.report_findings || 0)}</b><small>${number(ledgerProgress.unreconciled_report_findings_count ?? (ledgerProgress.unreconciled_report_findings || []).length)} unreconciled</small></div>${stateTiles}</div>`;
    const request = state.operationalCardsRequest || {};
    const punchFilters = `<div class="punch-ledger-filters"><label><span>Search</span><input data-operational-card-search value="${esc(request.query || '')}" placeholder="ID, surface, feature, action"></label><label><span>State</span><select data-operational-card-state><option value="">All states</option>${stateNames.map(name => `<option value="${name}" ${request.state === name ? 'selected' : ''}>${esc(name.replaceAll('_', ' '))}</option>`).join('')}</select></label><label><span>Severity</span><select data-operational-card-severity><option value="">All severities</option>${['blocker','critical','high','medium','low'].map(name => `<option value="${name}" ${request.severity === name ? 'selected' : ''}>${name}</option>`).join('')}</select></label><label class="policy-switch"><input type="checkbox" data-operational-card-evidence-gap ${request.evidenceGap ? 'checked' : ''}><span>Evidence gaps only</span></label><button class="primary" data-action="queryOperationalCards">Apply filters</button><button data-action="inspectOperationalInventory">Inspect surface/control inventory</button></div>`;
    const cardRows = (punchCards.cards || []).map(item => `<button class="readiness-row" data-action="inspectPunchCard" data-gap-id="${esc(item.id)}"><span><b>${esc(item.id)}</b><strong>${esc(item.area)} / ${esc(item.feature || 'unclassified')}</strong><small>${esc(item.finding)}</small></span><span>${badge(String(item.severity || 'unknown').toUpperCase(), ['blocker','critical','high'].includes(item.severity) ? 'warning' : 'info')}</span><span>${badge(String(item.status || 'discovered').toUpperCase(), item.status === 'closed' ? 'success' : 'warning')}</span><b>FULL CARD</b></button>`).join('');
    const pagination = `<div class="catalog-pagination"><button data-action="operationalCardsPrevious" ${(punchCards.offset || 0) <= 0 ? 'disabled' : ''}>Previous</button><span>${number((punchCards.offset || 0) + (punchCards.cards?.length ? 1 : 0))}-${number((punchCards.offset || 0) + (punchCards.cards?.length || 0))} of ${number(punchCards.filtered_count ?? punchCards.count)}</span><button data-action="operationalCardsNext" ${punchCards.has_more ? '' : 'disabled'}>Next</button></div>`;
    const ledgerFailureStates = new Set(['invalid', 'checkpoint_stale', 'recovery_required']);
    const ledgerFailureTitle = punchCards.source_status === 'checkpoint_stale'
      ? 'OPERATIONAL LEDGER CHECKPOINT STALE'
      : punchCards.source_status === 'recovery_required'
        ? 'OPERATIONAL LEDGER RECOVERY REQUIRED'
        : 'OPERATIONAL LEDGER INVALID';
    const recoveryAction = punchCards.recovery_action
      ? `<p><b>Bounded recovery action:</b> <code>${esc(punchCards.recovery_action)}</code></p>`
      : '';
    const ledgerFailure = ledgerFailureStates.has(punchCards.source_status) ? `<div class="validation-box failed"><span class="validation-icon">!</span><div><strong>${ledgerFailureTitle}</strong><p>${esc(punchCards.error || 'The canonical ledger could not be validated. Counts and empty states are suppressed.')}</p>${recoveryAction}<button data-action="queryOperationalCards">Retry checkpoint read</button></div></div>` : '';
    const punchRows = ledgerFailure || `${punchProgress}${punchFilters}<div class="readiness-table">${cardRows || empty('No cards match the current filter. This does not mean the ledger is empty.')}</div>${pagination}${punchCards.truncated ? '<p class="fine-print">This is a bounded page. Full-ledger counts above are calculated before paging.</p>' : ''}`;
    return `<div class="metric-grid compact">${card('CONNECTION', connection.label, snapshot.catalogSource, connection.tone === 'success' ? 'green' : 'red')}${card('HOST COMPATIBILITY', extensionLabel, extensionDetail, identityMatches ? 'green' : 'red')}${card('FEATURE AVAILABILITY', `${availableFeatures}/${featureIds.length}`, 'direct subsystem facts; not inferred health', availableFeatures === featureIds.length ? 'green' : 'blue')}${card('LIVE TRACE BLOCKERS', number(traces.length), 'cause-bound current records', traces.length ? 'red' : 'green')}</div>${section('Correlated diagnostic traces', 'CAUSE / OWNER / EVIDENCE / REPAIR / VERIFY', `<div class="diagnostic-trace-list">${traceRows || '<p class="compact-empty">No current diagnostic cause chain is reported. This is not a completion claim.</p>'}</div>`)}${section('Operational punch cards', `${number(punchCards.open_count)} OPEN / ${number(punchCards.count)} RETAINED · EXACT CARD HISTORY ON DEMAND`, punchRows)}<div class="two-col wide-left">${section('Diagnostic control-plane check', 'OPTIONAL TARGETED CHECK', `<div class="validation-box ${esc(validation.status)}"><span class="validation-icon">${validation.status === 'passed' ? 'OK' : validation.status === 'failed' ? '!' : '-'}</span><div><strong>${esc(String(validation.status).toUpperCase())}</strong><p>${esc(validation.detail)}</p></div></div><button data-action="validate">Run only when needed</button><p class="fine-print">This local check never substitutes for live operation, current inventory, a working feature, or closed punch-card evidence.</p>`)}${section('Feature and integration status', 'DIRECT FACTS', serviceGrid())}</div>${catalogPanel('enterprise-integrations', 'MS+Enterprise connector readiness', 'SEPARATE DATA MODEL - NO CONNECTION ATTEMPT')}`;
  }

  function assurance(context) {
    const { state } = requireContext(context);
    const snapshot = state.snapshot;
    const authorities = Array.isArray(snapshot.authorities) ? snapshot.authorities : [];
      return `<div class="metric-grid compact">${card('ASSURANCE RECORDS', number(snapshot.counts?.assurance), 'records present; acceptance varies')}${card('CONTRACTS', number(snapshot.counts?.contracts), 'declared schemas, not execution proof')}${card('STATE RECEIPTS', number(state.coordination?.state?.revision || 0), 'hash-linked transitions')}${card('OPERATIONAL FINDINGS', number(snapshot.completion?.current_operational_surface_audit?.pending_ids?.length ?? 'Unavailable'), 'must close before completion')}</div>${section('Agent readiness matrix', 'ADVISORY STRUCTURE · NOT OPERATIONAL CERTIFICATION', readinessMatrix(context))}${section('Canonical ownership map', 'OBSERVED TRUST BOUNDARIES', `<div class="data-table ownership"><div class="table-head"><span>Capability</span><span>Canonical owner</span><span>Observed state</span><span>UI exposure / limitation</span></div>${authorities.map(item => `<div class="table-row"><strong>${esc(item.capability)}</strong><span>${esc(item.owner)}</span>${badge(item.status, ['ready','connected','map-observed','observed'].includes(item.status) ? 'success' : String(item.status).includes('unavailable') || String(item.status).includes('detached') ? 'warning' : 'info')}<span>${esc(item.exposure)}</span></div>`).join('')}</div>`)}${section('MS+Enterprise separation', 'DATA MODEL BOUNDARY', `<dl class="detail-list"><div><dt>Catalog</dt><dd>${esc(snapshot.enterprise?.catalog_id || 'Unavailable')}</dd></div><div><dt>State schema</dt><dd>${esc(snapshot.enterprise?.separation?.state_schema || 'Unavailable')}</dd></div><div><dt>Credential storage</dt><dd>${esc(snapshot.enterprise?.separation?.credential_storage || 'Unavailable')}</dd></div><div><dt>Memory import</dt><dd>${esc(snapshot.enterprise?.separation?.canonical_memory_import || 'Unavailable')}</dd></div><div><dt>Billable services</dt><dd>${badge(snapshot.enterprise?.defaults?.billable_services || 'unknown', snapshot.enterprise?.defaults?.billable_services === 'disabled' ? 'success' : 'warning')}</dd></div></dl><button class="primary" data-action="enterpriseDoctor">Run offline readiness doctor</button>`)}`;
  }

  function settings(context) {
    const { state } = requireContext(context);
    const snapshot = state.snapshot;
    const policy = state.settings.executionPolicy || {};
    const enabled = policy.master_enabled === true;
    const mcp = snapshot.observability?.mcp || { status: 'unavailable', registered: false, runtime_verified: false, detail: 'No MCP observation is available.' };
    const mcpLabel = mcp.runtime_verified ? 'Runtime verified' : mcp.registered ? 'Registered, unverified' : String(mcp.status || 'Unavailable');
    const mcpTone = mcp.runtime_verified ? 'success' : mcp.registered ? 'info' : 'warning';
    const configRows = [
      ['Pacify-X engine root', snapshot.source?.engineRoot || 'Auto-discovery did not resolve', 'VS Code user/workspace setting', 'Reload window after changing roots'],
      ['Refresh interval', `${number(state.settings.refreshIntervalSeconds)} seconds`, 'Effective extension setting', 'Next scheduled refresh'],
      ['Advanced surfaces', state.settings.showAdvancedSurfaces ? 'Visible' : 'Hidden', 'Effective extension setting', 'Immediate after setting acknowledgement'],
      ['Context injection cap', `${number(state.settings.contextInjectionCapTokens)} tokens`, 'Effective extension setting', 'Next context snapshot'],
      ['Ollama route', state.settings.ollamaEnabled ? 'Enabled; loopback probe on explicit use' : 'Disabled', 'Effective extension setting', 'Next explicit model request'],
      ['Coordination root', state.coordination?.paths?.root || 'No workspace coordination root', 'Workspace-derived runtime state', 'Reinitialize when workspace changes']
    ].map(([name, value, source, reload]) => `<div class="settings-row"><b>${esc(name)}</b><span class="mono">${esc(value)}</span><small>${esc(source)}</small><em>${esc(reload)}</em></div>`).join('');
    return `${section('Effective configuration', 'VALUE · SOURCE · APPLICATION BOUNDARY', `<div class="settings-table"><div class="settings-head"><span>Setting</span><span>Effective value</span><span>Source / owner</span><span>When applied</span></div>${configRows}</div><div class="settings-handoff"><p>VS Code owns configuration editing and scope selection. PX consumes the acknowledged effective values shown above.</p><button class="primary" data-action="openSettings">Edit Pacify-X settings in host</button></div>`)}<div class="two-col wide-left">${section('Connections', 'OBSERVED LOCAL-FIRST STATUS', `<div class="service-grid"><div><span>Pacify-X engine</span>${badge(snapshot.connected ? 'Connected' : 'Disconnected', snapshot.connected ? 'success' : 'warning')}</div><div><span>Ollama</span>${badge(state.settings.ollamaEnabled ? 'Configured; not implicitly probed' : 'Disabled', state.settings.ollamaEnabled ? 'info' : 'neutral')}</div><div><span>Environment graph</span>${badge(snapshot.environment ? `${number(snapshot.environment.summary?.graph_nodes)} nodes` : 'Discovering', snapshot.environment ? 'success' : 'info')}</div><div><span>MCP</span>${badge(mcpLabel, mcpTone)}</div><div><span>Billable provider master</span>${badge(enabled ? 'Guarded opt-in' : 'Disabled', enabled ? 'warning' : 'success')}</div><div><span>Native session transfer</span>${badge('Unsupported; portable resume used', 'neutral')}</div></div><p class="fine-print">Status is current snapshot evidence, not a claim that an unavailable provider was tested.</p>`)}${section('Configuration authority', 'PX GOVERNANCE → HOST AUTHORITY → ENVIRONMENT', `<dl class="detail-list"><div><dt>PX</dt><dd>Defines governed scope, contracts, gates, and required evidence.</dd></div><div><dt>Codex / VS Code host</dt><dd>Retains native tools, approvals, security, configuration, and execution authority.</dd></div><div><dt>Repository</dt><dd>Receives only operations permitted by both boundaries.</dd></div></dl><button data-action="openSettings">Open authoritative editor</button>`)}</div>${section('Billable execution guardrails', enabled ? 'MASTER ON · EVERY GATE STILL APPLIES' : 'ZERO-COST DEFAULT · MASTER OFF', `<button class="policy-switch px-owned-control ${enabled ? 'on' : ''}" role="switch" aria-checked="${enabled}" data-action="toggleBillablePolicy" data-enabled="${enabled ? 'false' : 'true'}"><span><b>Cloud / billable provider policy</b><small>${enabled ? 'Permitted for evaluation only; no provider is connected.' : 'No billable provider execution can pass.'}</small></span><strong>${enabled ? 'ON' : 'OFF'}</strong></button><div class="guardrail-grid"><div><span>Cost / task</span><b>$${Number(policy.max_cost_per_task_usd || 0).toFixed(2)}</b></div><div><span>Cost / session</span><b>$${Number(policy.max_cost_per_session_usd || 0).toFixed(2)}</b></div><div><span>Cost / day</span><b>$${Number(policy.max_cost_per_day_usd || 0).toFixed(2)}</b></div><div><span>Token budget</span><b>${number(policy.token_budget)}</b></div><div><span>Local-first</span><b>${policy.local_first ? 'Required' : 'Optional'}</b></div><div><span>Providers</span><b>${number((policy.provider_allowlist || []).length)} allowlisted</b></div><div><span>GPU / CPU / RAM</span><b>${number(policy.gpu_memory_ceiling_mb)} MiB · ${number(policy.cpu_core_ceiling)} cores · ${number(policy.ram_ceiling_mb)} MiB</b></div><div><span>Escalation confidence</span><b>${Number(policy.escalation_confidence_threshold || 0).toFixed(2)}</b></div><div><span>Cache / reuse</span><b>${esc(policy.cache_reuse_aggressiveness || 'balanced')}</b></div><div><span>Billable approval</span><b>${policy.require_approval_before_billable_execution ? 'Always required' : 'Policy disabled'}</b></div></div><p class="fine-print">The master switch never stores credentials or makes a connection. A billable execution remains blocked unless every configured guardrail passes.</p>`, '<button data-action="openSettings">Edit guardrails</button>')}`;
  }

  const renderers = Object.freeze({ diagnostics, assurance, settings });
  dashboard.define('systemSurfaces', {
    ids: Object.freeze(Object.keys(renderers)),
    has(id) { return Object.hasOwn(renderers, id); },
    render(id, context) {
      if (!Object.hasOwn(renderers, id)) throw new RangeError(`Unknown system surface: ${id}`);
      return renderers[id](requireContext(context));
    }
  });
})();
