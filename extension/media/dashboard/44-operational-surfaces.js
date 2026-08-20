'use strict';

(() => {
  const dashboard = globalThis.PXDashboard;
  if (!dashboard) throw new Error('PXDashboard foundation must load before operational surfaces.');
  const { escapeHtml: esc, number, badge, card, section, empty, unavailable } = dashboard.require('components');

  function requireContext(context) {
    if (!context || typeof context !== 'object' || !context.state?.snapshot) {
      throw new TypeError('Operational surfaces require a canonical snapshot context.');
    }
    for (const helper of ['catalogPanel', 'environmentMap', 'coordinationBoard']) {
      if (typeof context[helper] !== 'function') throw new TypeError(`Operational surfaces require ${helper}.`);
    }
    return context;
  }

  function workflows(context) {
    const { state, catalogPanel, environmentMap, coordinationBoard } = requireContext(context);
    const enterprise = state.workflowScope === 'enterprise';
    const environment = state.workflowScope === 'environment';
    const counts = state.snapshot.counts || {};
    const metrics = `<div class="metric-grid compact">${card('DEFINITIONS', number(counts.workflow_definitions), 'project + skill definitions')}${card('VALIDATOR BINDINGS', number(counts.workflow_validator_bindings), 'non-runtime validation')}${card('RUNTIME BINDINGS', number(counts.workflow_runtime_bindings), 'explicit executor bindings')}${card('RUNNABLE / RUNS', `${number(counts.workflow_runnable_revisions)} / ${number(counts.workflow_runs)}`, 'admitted revisions / durable runs')}</div>`;
    const setup = Number(counts.workflow_runnable_revisions || 0) < 1 ? '<button class="primary" data-action="setupStudio">Set up runnable Agent + Workflow</button>' : '';
    return `${metrics}<div class="catalog-tabs" role="group" aria-label="Workflow scope"><button data-action="surfaceScope" data-target="workflows" data-scope="core" aria-pressed="${!enterprise && !environment}" class="${!enterprise && !environment ? 'active' : ''}">Local + Team Fabric</button><button data-action="surfaceScope" data-target="workflows" data-scope="enterprise" aria-pressed="${enterprise}" class="${enterprise ? 'active' : ''}">MS+Enterprise</button><button data-action="surfaceScope" data-target="workflows" data-scope="environment" aria-pressed="${environment}" class="${environment ? 'active' : ''}">Environment Map</button></div>${environment ? environmentMap() : enterprise ? `${section('Enterprise workflow boundary', 'DETERMINISTIC · DISABLED CONNECTORS', `<div class="gate-stack"><span>Target</span><i>→</i><span>Auth namespace</span><i>→</i><span>Cost / egress</span><i>→</i><span>Human gate</span><i>→</i><span>Receipt</span></div><button class="primary" data-action="enterpriseDoctor">Run readiness doctor</button>`)}${catalogPanel('enterprise-workflows', 'MS+Enterprise orchestrations', 'SEPARATE WORKFLOW CATALOG')}` : `${section('Workflow Studio', 'VERSIONED TYPED DAG · IMMUTABLE REVISION', `<p>Author and edit typed workflow revisions with explicit executor bindings. Source definitions are not runnable until a Studio revision is validated.</p><div class="action-grid">${setup}<button class="primary" data-action="openStudioDraft" data-kind="workflow">New workflow definition</button><button data-action="openStudioRuns" data-kind="workflow">Open durable runs</button></div>`)}${section('Parallel planning', 'CROSS-IDE COORDINATION PLANE', coordinationBoard(), '<button class="primary small" data-action="newParallelPlan">New plan</button><button class="secondary small" data-action="openCoordinationHandoff">Open handoff</button>')}${catalogPanel('workflows', 'Workflow definitions and bindings', 'DEFINITIONS · VALIDATORS · RUNTIME BINDINGS · RUNS')}`}`;
  }

  function studioCount(state, kind) {
    const counts = state.snapshot?.counts || {};
    if (kind === 'agent') return number(counts.agents || 0);
    if (kind === 'workflow') return number(counts.workflows || 0);
    return number(counts.skills || 0);
  }

  function agentStudio(context) {
    const { state, catalogPanel } = requireContext(context);
    const counts = state.snapshot.counts || {};
    const metrics = `<div class="metric-grid compact">${card('AGENT CATALOG', studioCount(state, 'agent'), 'source definitions + Studio revisions')}${card('RUNNABLE REVISIONS', number(counts.agents_runnable_revisions || 0), 'current admitted Studio revisions')}</div>`;
    const setup = Number(counts.agents_runnable_revisions || 0) < 1 ? '<button class="primary" data-action="setupStudio">Set up runnable Agent + Workflow</button>' : '';
    return `${metrics}${section('Agent Studio', 'TYPED AGENT SPECIFICATION', `<p>Author a typed agent revision in-browser, or initialize a verified editable starter. Admission and execution remain explicit lifecycle states.</p><div class="action-grid">${setup}<button class="primary" data-action="openStudioDraft" data-kind="agent">New agent definition</button><button data-action="openStudioRuns" data-kind="agent">Open durable runs</button></div>`, '<span class="count-chip">Local + Team catalog</span>')}${catalogPanel('agents', 'Agent catalog', 'AGENT · CAPABILITY · GRANTS')}`;
  }

  function workflowStudio(context) {
    return workflows(context);
  }

  function skillStudio(context) {
    const { state, catalogPanel } = requireContext(context);
    const counts = state.snapshot.counts || {};
    const metrics = `<div class="metric-grid compact">${card('SKILL REVISION', studioCount(state, 'skill'), 'candidate packages')}${card('RUNNABLE REVISION', number(counts.skill_runnable_revisions || 0), 'admitted candidate heads')}</div>`;
    return `${metrics}${section('Skill Studio', 'PACKAGE-BASED SKILL AUTHORING', `<p>Draft a package-bound skill candidate with manifest, contracts, tests, resources, and revision evidence in one session.</p><div class="action-grid"><button class="primary" data-action="openStudioDraft" data-kind="skill">New skill definition</button><button data-action="openStudioRuns" data-kind="skill">Open durable runs</button></div>`, '<span class="count-chip">Packages</span>')}${catalogPanel('skills', 'Skill catalog', 'SKILL REVISION · PERMISSIONS · EFFECTS · CONTRACTS')}`;
  }

  function studioLifecycle(context) {
    const { state } = requireContext(context);
    const history = (state.studioHistory || []).slice(0, 12).map(item => `<article class="catalog-row"><strong>${esc(item.kind || 'studio')}</strong><small>${esc(item.operation || item.outcome || 'lifecycle')}</small><span>${esc(item.version || '')}</span><span>${badge('SESSION', 'info')}</span><b>Recent</b></article>`).join('');
    return `<div class="metric-grid compact">${card('AGENT RUNS', number((state.snapshot?.counts || {}).agent_runs || 0), 'durable agent execution history')}${card('WORKFLOW RUNS', number((state.snapshot?.counts || {}).workflow_runs || 0), 'durable workflow execution history')}${card('SKILL CANDIDATES', number((state.snapshot?.counts || {}).skills || 0), 'draft and promoted revisions')}${card('HISTORY', number((state.studioHistory || []).length), 'recent local lifecycle events')}</div>${section('Studio lifecycle', 'OPERATIONS, RECEIPTS, AND EXACT TARGET ACTIONS', `<div class="action-grid"><button data-action="openStudioRuns" data-kind="agent">Agent runs</button><button data-action="openStudioRuns" data-kind="workflow">Workflow runs</button><button data-action="openStudioRuns" data-kind="skill">Skill runs</button></div><p>Lifecycle actions are exposed on selected records and in draft headers after exact context is loaded.</p>`, '<span class="count-chip">run / lifecycle surface</span>')}${section('Recent lifecycle ledger', 'RECENT CONTEXTUAL HISTORY', history || empty('No local Studio lifecycle events were recorded in this webview session.'), `<span class="count-chip">${number((state.studioHistory || []).length)}</span>`)}${section('Lifecycle notes', 'SURFACE IS A CONTROL HUB', 'Open catalog records to start exact revision lifecycle actions such as admit, validate, start, approve, promote, rollback, and compare. No host action is executed until a matching catalog context is selected.', '<span class="count-chip">control-aware</span>')}`;
  }

  function plugins(context) {
    const { state } = requireContext(context);
    const inventory = state.snapshot.environment || null;
    const freshness = String(inventory?.freshness?.state || 'unavailable').toLowerCase();
    const shardIdentityMatches = Boolean(inventory?.snapshot_hash && state.environmentData.extensions?.snapshot_hash === inventory.snapshot_hash);
    const inventoryCurrent = ['fresh', 'memory-current'].includes(freshness) && shardIdentityMatches;
    const persistedExtensions = state.environmentData.extensions?.records || [];
    // Never project a retained shard as current host state unless its compact,
    // hash-bound inventory is still within the declared freshness window.
    const extensions = inventoryCurrent ? persistedExtensions : [];
    const connectors = state.snapshot.enterprise?.connectors || [];
    const mcp = state.snapshot.observability?.mcp || { status: 'unavailable', registered: false, runtime_verified: false };
    const mcpLabel = mcp.runtime_verified ? 'VERIFIED' : mcp.registered ? 'REGISTERED' : 'UNAVAILABLE';
    const extensionError = state.environmentData.extensions?.error ? `<div class="memory-errors" role="alert"><p>${esc(state.environmentData.extensions.error)}</p><button data-action="refreshEnvironment">Refresh the capability inventory</button></div>` : !inventoryCurrent && persistedExtensions.length ? `<div class="memory-errors" role="alert"><p>Installed-extension inventory suppressed: ${esc(freshness)} evidence is stale or its shard hash does not match the current compact inventory.</p><p>Captured ${esc(inventory?.discovery?.captured_utc || inventory?.generated_utc || 'time unavailable')} · expires ${esc(inventory?.freshness?.expires_utc || 'unavailable')} · generation ${number(inventory?.freshness?.generation)}</p><button data-action="refreshEnvironment">Refresh the capability inventory</button></div>` : '';
    const rows = extensions.slice(0, 120).map(item => `<button class="plugin-row" data-action="environmentExtensionDetail" data-extension-id="${esc(item.id)}"><div><strong>${esc(item.name || item.id)}</strong><small>${esc(item.id)} · v${esc(item.version || 'unknown')} · ${esc(item.publisher || 'publisher unknown')}</small></div><span>${badge(item.active ? 'ACTIVE' : 'DETECTED', item.active ? 'success' : 'info')}</span><span>${number(item.capability_count)} capabilities · ${number(item.command_count)} commands</span><span>${number(item.conflict_count)} conflicts</span><b>INSPECT</b></button>`).join('');
    const connectorRows = connectors.map(item => `<article class="plugin-connector"><div><strong>${esc(item.name)}</strong><small>${esc(item.id)}</small></div>${badge(item.status || 'disabled', item.status === 'active' ? 'success' : 'neutral')}<span>${esc(item.requirements || item.description || 'Explicit adapter approval required')}</span></article>`).join('');
    const active = extensions.filter(item => item.active).length;
    const conflicts = extensions.reduce((total, item) => total + Number(item.conflict_count || 0), 0);
    const capabilities = extensions.reduce((total, item) => total + Number(item.capability_count || 0), 0);
    const conflictLifecycle = section('Conflict analysis + governed resolution', 'LIVE MANIFEST ANALYSIS · EXACT SIGNAL · PROVEN LIFECYCLE ROUTES', `<div class="plugin-lifecycle-grid"><article><b>Analyze extension conflicts</b>${badge('LIVE HOST EVIDENCE', 'info')}<span>Drill into duplicate contributions, keybindings, provider overlaps, missing dependencies, and reverse consumers. Resolution routes re-enter install, enablement, or uninstall gates.</span><label>Installed publisher.extension ID<input id="extension-conflict-id" placeholder="publisher.extension" autocomplete="off"></label><button class="primary" data-action="queryExtensionConflicts">Analyze + plan</button></article></div>`);
    const rollbackLifecycle = section('Rollback retained uninstall', 'EXACT VERSION REINSTALL · CUSTODY CONSUMED ONLY AFTER VERIFICATION', `<div class="plugin-lifecycle-grid"><article><b>Rollback retained uninstall</b>${badge('EXACT VERSION REINSTALL', 'warning')}<span>PX selects the latest unconsumed retained identity for an absent extension. VS Code must accept and expose the exact historical version before custody is consumed.</span><label>Absent publisher.extension ID<input id="extension-rollback-id" placeholder="publisher.extension" autocomplete="off"></label><button class="primary" data-action="previewExtensionRollback">Preview rollback</button></article></div>`);
    const lifecycle = `<div class="plugin-lifecycle-grid"><article><b>Discover + inspect</b>${badge(inventoryCurrent ? 'PX CURRENT' : 'REFRESH REQUIRED', inventoryCurrent ? 'success' : 'warning')}<span>Bounded installed-extension metadata, commands, contributions, capability counts, and conflicts.</span><button data-action="refreshEnvironment">Refresh evidence</button></article><article><b>Install exact extension</b>${badge('GOVERNED HOST ACTION', 'info')}<span>PX binds the exact target and result; VS Code retains Marketplace, trust, signature, security, and install authority.</span><label>Publisher.extension ID<input id="extension-install-id" placeholder="publisher.extension" autocomplete="off"></label><label>Version (optional)<input id="extension-install-version" placeholder="1.2.3" autocomplete="off"></label><div class="action-grid"><button class="primary" data-action="previewExtensionInstall">Preview install</button><button data-action="openExtensionsView">Browse host manager</button></div></article><article><b>Update installed extension</b>${badge('GOVERNED HOST ACTION', 'info')}<span>PX binds the current denominator, optional exact target, rollback identity, and result. VS Code enforces target compatibility.</span><label>Installed publisher.extension ID<input id="extension-update-id" placeholder="publisher.extension" autocomplete="off"></label><label>Target version (optional/latest)<input id="extension-update-version" placeholder="2.0.0" autocomplete="off"></label><button class="primary" data-action="previewExtensionUpdate">Preview update</button></article><article><b>Enable + disable</b>${badge('NATIVE MANAGER BOUNDARY', 'info')}<span>PX binds exact intent and scope, then focuses the native record. Activation is displayed separately and is never treated as enablement.</span><label>Installed publisher.extension ID<input id="extension-enablement-id" placeholder="publisher.extension" autocomplete="off"></label><label>Desired action<select id="extension-enablement-action"><option value="disable">Disable</option><option value="enable">Enable</option></select></label><label>Scope<select id="extension-enablement-scope"><option value="workspace">Workspace</option><option value="global">Global</option></select></label><button class="primary" data-action="previewExtensionEnablement">Preview native handoff</button></article><article><b>Uninstall exact extension</b>${badge('GOVERNED HOST ACTION', 'warning')}<span>PX discloses reverse consumers and retains exact prior identity before native uninstall. Source availability for rollback is verified separately.</span><label>Installed publisher.extension ID<input id="extension-uninstall-id" placeholder="publisher.extension" autocomplete="off"></label><button class="danger" data-action="previewExtensionUninstall">Preview uninstall</button></article></div>`;
    return `<div class="metric-grid compact">${card('DETECTED / ACTIVE', inventoryCurrent ? `${number(extensions.length)} / ${number(active)}` : 'Unavailable', inventoryCurrent ? `current generation ${number(inventory?.freshness?.generation)}` : `${freshness}; records suppressed`)}${card('CAPABILITIES', inventoryCurrent ? number(capabilities) : 'Unavailable', 'declared extension contributions')}${card('CONFLICT SIGNALS', inventoryCurrent ? number(conflicts) : 'Unavailable', inventoryCurrent ? (conflicts ? 'inspect affected extensions' : 'none reported') : 'refresh required')}${card('MCP SERVER', mcpLabel, esc(mcp.detail || mcp.status))}</div>${conflictLifecycle}${rollbackLifecycle}
    ${section('Capability catalog contract', 'BOUNDED SEARCH · TYPED MANIFEST · ADMISSION BEFORE ACTIVATION', `<div class="catalog-admission-flow"><span>Discover</span><i>→</i><span>Schema + identity</span><i>→</i><span>License + provenance</span><i>→</i><span>Effects + compatibility</span><i>→</i><span>Quarantine / admit</span><i>→</i><span>Host activation</span></div><div class="catalog-contract-grid"><article><b>Human discovery</b><span>Searchable, paged catalogs with readable purpose, lifecycle, owner, risk, and fit.</span></article><article><b>AI discovery</b><span>Stable IDs, structured content, bounded top results, explicit schemas, and safe next calls.</span></article><article><b>Supply-chain fields</b><span>Version, license, source, digest, signature/SBOM hints, compatibility, effects, and rollback.</span></article><article><b>Authority boundary</b><span>Catalog presence never means installed, admitted, enabled, authenticated, or authorized.</span></article></div>`, '<button data-action="inspectMachineManifest">Inspect machine contract</button>')}
    ${section('Governed plugin lifecycle', 'REAL OWNER PER OPERATION · NO IMPLIED PX AUTHORITY', `${lifecycle}<div class="plugin-boundary"><b>PX observes and governs the PX-controlled boundary; the Codex/VS Code host retains native execution authority.</b><span>Discovery never grants installation, activation, credentials, network, or billable effects.</span></div><div class="plugin-actions"><button class="primary" data-action="refreshEnvironment">Refresh capability inventory</button><button data-action="openExtensionsView">Open host extension manager</button><button data-action="inspectMachineManifest">AI capability manifest</button></div>`)}
    ${section('Installed extension evidence', `${inventoryCurrent ? number(extensions.length) : 0} CURRENT RECORDS · ${esc(freshness.toUpperCase())}`, `${extensionError}<div class="plugin-list">${rows || empty(state.environmentData.extensions?.error ? 'Extension inventory is unavailable.' : inventoryCurrent ? 'Extension inventory is loading; refresh to request current host evidence.' : 'Stale or unidentified inventory is intentionally not rendered.')}</div>`)}
    ${section('Connector and pack readiness', 'OFFLINE STATUS · NO IMPLICIT CONNECTION', `<div class="plugin-connectors">${connectorRows || unavailable('No connector metadata available.')}</div>`)}`;
  }

  const renderers = Object.freeze({
    workflows,
    'agent-studio': agentStudio,
    'workflow-studio': workflowStudio,
    'skill-studio': skillStudio,
    'studio-lifecycle': studioLifecycle,
    plugins
  });
  dashboard.define('operationalSurfaces', {
    ids: Object.freeze(Object.keys(renderers)),
    has(id) { return Object.hasOwn(renderers, id); },
    render(id, context) {
      if (!Object.hasOwn(renderers, id)) throw new RangeError(`Unknown operational surface: ${id}`);
      return renderers[id](requireContext(context));
    }
  });
})();
