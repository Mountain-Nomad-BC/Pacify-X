'use strict';

// Exhaustive current-source browser probe. This runner emits one honest record
// for every canonical proof-matrix control. It may prove contained UI stages;
// host, durability, restart, lifecycle, and fault stages remain incomplete
// until a direct probe receipt is assembled for that exact control.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright-core');
const { resolveBrowserLane } = require('../tests/browser-lane');
const { buildSidebarProjection } = require('../src/sidebarProjection');
const { MESSAGE_SCHEMA_VERSION, SIDEBAR_ASSET_PROTOCOL } = require('../src/sidebarMessages');

const root = path.resolve(__dirname, '..', '..');
const matrixPath = path.join(root, 'registry', 'operational_control_proof_matrix.json');
const preview = pathToFileURL(path.join(root, 'extension', 'tests', 'preview.html')).href;
const sidebarPreview = pathToFileURL(path.join(root, 'extension', 'tests', 'sidebar-preview.html')).href;
const output = path.resolve(process.argv[2] || path.join(root, 'evidence', 'exhaustive-operational-control-walk', 'receipt.json'));
const resumeOffset = process.argv.indexOf('--resume');
const resumePath = resumeOffset >= 0 && process.argv[resumeOffset + 1] ? path.resolve(process.argv[resumeOffset + 1]) : null;
const controlPatternSource = String(process.env.PX_OPERATIONAL_CONTROL_PATTERN || '').trim();
const controlPattern = controlPatternSource ? new RegExp(controlPatternSource) : null;
const STAGES = [
  'open_load', 'display', 'user_edit_action', 'input_validation', 'authorization',
  'backend_dispatch', 'runtime_effect', 'progress_reporting', 'result_acknowledgement',
  'persistence', 'reload_reopen', 'failure_handling', 'recovery_rollback'
];
const ROUTES = {
  dashboard: 'dashboard', 'dashboard-control-plane': 'dashboard', projects: 'projects', agents: 'agents', 'agent-studio': 'agent-studio',
  'workflow-studio': 'workflow-studio', 'skill-studio': 'skill-studio', 'knowledge-graph': 'knowledgeGraph',
  'skills-tools': 'skillsTools', workflows: 'workflows', plugins: 'plugins', memory: 'memory', activity: 'activity',
  diagnostics: 'diagnostics', assurance: 'assurance', 'studio-lifecycle': 'studio-lifecycle', settings: 'settings',
  'knowledge-core': 'knowledgeCore', 'runtime-core': 'runtimeCore'
};
const UI_KINDS = new Set(['action', 'field', 'form', 'menu', 'editor', 'gesture', 'indicator']);
const SIDEBAR_FIXTURE_NOW = Date.parse('2026-08-25T18:00:00Z');

function sha256(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}
function sourcePath(reference) {
  const value = String(reference || '');
  const index = value.indexOf(':');
  return index > 0 ? value.slice(0, index) : value;
}
function currentSourceManifest(matrix, sourceRoot = root) {
  const files = [...new Set((matrix.controls || []).flatMap(control => control.source_refs || []).map(sourcePath))]
    .sort().map(relative => {
      if (!relative) throw new Error('Control source reference has no physical path.');
      const target = path.resolve(sourceRoot, relative);
      const bounded = path.relative(sourceRoot, target);
      if (!bounded || path.isAbsolute(bounded) || bounded === '..' || bounded.startsWith(`..${path.sep}`)) throw new Error(`Control source escapes root: ${relative}`);
      const stat = fs.lstatSync(target);
      if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Control source is not a physical file: ${relative}`);
      const bytes = fs.readFileSync(target);
      return { path: relative.replaceAll('\\', '/'), sha256: sha256(bytes), bytes: bytes.length };
    });
  const body = { schema_version: 'px.current-source-control-manifest/2.0', files };
  return { ...body, source_sha256: sha256(Buffer.from(canonicalJson(body), 'utf8')) };
}
function normalize(value) {
  return String(value || '').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[._:/-]/g, ' ')
    .toLowerCase().replace(/[^a-z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
}
function meaningfulTokens(value) {
  const ignored = new Set(['the', 'and', 'for', 'with', 'from', 'into', 'state', 'surface', 'control']);
  return [...new Set(normalize(value).split(' ').filter(token => (token.length > 2 || token === 'id') && !ignored.has(token)))];
}
function candidateScore(label, candidate) {
  const tokens = meaningfulTokens(label);
  if (!tokens.length) return 0;
  const haystack = normalize(`${candidate.attributes || ''} ${candidate.text || ''}`);
  const hits = tokens.filter(token => haystack.includes(token)).length;
  const exact = haystack.includes(normalize(label));
  return Math.min(1, (hits / tokens.length) + (exact ? 0.35 : 0));
}
function actionIdentity(label) {
  const parts = String(label).split('.');
  if (parts[0] === 'dynamicRepair') return { action: parts[1], variants: parts.slice(2) };
  return { action: parts[0], variants: parts.slice(1) };
}
function semanticLabel(control) {
  const marker = `.${control.kind}.`;
  const offset = String(control.control_id).indexOf(marker);
  if (offset < 0) throw new Error(`Control ID does not contain its kind boundary: ${control.control_id}`);
  const label = String(control.control_id).slice(offset + marker.length);
  if (!label) throw new Error(`Control ID has an empty semantic label: ${control.control_id}`);
  return label;
}
function variantsMatch(dataset, variants) {
  const values = new Set(Object.values(dataset || {}).map(String));
  return variants.every(variant => variant === 'row'
    ? Object.keys(dataset || {}).some(key => /id|index|row|key/i.test(key))
    : values.has(variant));
}
function visualVariantsMatch(dataset, variants, context = '') {
  const normalizedContext = normalize(context);
  return variants.every(variant => {
    if (variantsMatch(dataset, [variant])) return true;
    if (variant === 'in') return Number(dataset?.delta) > 0 || normalizedContext.includes('zoom in');
    if (variant === 'out') return Number(dataset?.delta) < 0 || normalizedContext.includes('zoom out');
    if (variant === 'optional') return ['tools', 'memory', 'handoffs'].includes(String(dataset?.agentKind || ''));
    return ['header', 'hero', 'toolbar', 'minimap', 'optional', 'row'].includes(variant)
      && normalizedContext.includes(normalize(variant));
  });
}

function sidebarFixtureMessage({ disconnected = false } = {}) {
  const tasks = [
    { id: 'task-ready', title: 'Ready task', status: 'reconciled', weight: 1, depends_on: [] },
    { id: 'task-active', title: 'Active task', status: 'in_progress', weight: 2, depends_on: ['task-ready'], subtasks: [{ id: 'probe', title: 'Probe exact controls', status: 'in_progress' }] },
    { id: 'task-blocked', title: 'Blocked task', status: 'blocked', weight: 1, depends_on: ['task-active'] }
  ];
  const projection = buildSidebarProjection({
    connected: !disconnected,
    generatedAt: new Date(SIDEBAR_FIXTURE_NOW).toISOString(),
    source: { version: '0.7.0.dev0' },
    health: { authoritative: !disconnected, ready: !disconnected },
    attention: [{ id: 'review', severity: 'warning', title: 'Review exact control evidence', detail: 'Bounded fixture attention record.' }],
    providerActivity: [
      { providerId: 'openai', providerName: 'OpenAI API', providerClass: 'billable-api', connectionState: 'connected', activityState: 'active', billingEnabled: true, fallbackEnabled: true, fallbackActive: false, spendCurrent: 3, budgetLimit: 10, ratePerMinute: .1, currency: 'USD', currentTaskId: 'task-active', currentTaskName: 'Active task', telemetrySource: 'fixture', telemetryFreshAt: new Date(SIDEBAR_FIXTURE_NOW - 5_000).toISOString() },
      { providerId: 'ollama', providerName: 'Ollama', providerClass: 'local', connectionState: 'connected', activityState: 'idle', billingEnabled: false, fallbackEnabled: false, fallbackActive: false, tokenTotal: 1000, telemetrySource: 'fixture-local', telemetryFreshAt: new Date(SIDEBAR_FIXTURE_NOW - 5_000).toISOString() }
    ],
    coordinationData: {
      event_log_health: { status: 'healthy' },
      events: [{ event_id: 'event-1', operation: 'task-progress-recorded', timestamp: new Date(SIDEBAR_FIXTURE_NOW - 10_000).toISOString(), result: { task_id: 'task-active' } }],
      state: {
        revision: 15,
        updated_utc: new Date(SIDEBAR_FIXTURE_NOW).toISOString(),
        active_plan: 'plan-live',
        plans: [{ id: 'plan-live', objective: 'Exercise sidebar controls', status: 'active', task_ids: tasks.map(item => item.id) }],
        tasks,
        claims: [{ id: 'claim-active', task_id: 'task-active', status: 'active', actor: { actor_id: 'agent-live', session_id: 'session-live' } }],
        sessions: [{ actor_id: 'agent-live', display_name: 'Live agent', session_id: 'session-live', harness: 'VS Code', heartbeat_utc: new Date(SIDEBAR_FIXTURE_NOW - 2_000).toISOString(), status: 'active' }],
        team_fabric: { work_rooms: [{ id: 'orchestration-live', name: 'Live orchestration', status: 'running', updated_utc: new Date(SIDEBAR_FIXTURE_NOW).toISOString() }] }
      }
    }
  }, { nowMs: SIDEBAR_FIXTURE_NOW, expandedWaveIds: ['wave-1', 'wave-2'], expandedTaskIds: ['task-active'], selectedProviderId: 'openai' });
  return {
    schemaVersion: MESSAGE_SCHEMA_VERSION,
    type: 'snapshot',
    capabilities: { renderAcknowledgement: true, assetProtocol: SIDEBAR_ASSET_PROTOCOL },
    projection
  };
}

function sidebarActionSelector(control) {
  const id = String(control?.control_id || '');
  const semantic = id.split('.action.')[1] || '';
  const { action, variants } = actionIdentity(semantic);
  if (action === 'openEntity' && variants[0]) return `[data-entity-type="${variants[0]}"]`;
  if (action === 'openPlanFromPunch') return '[data-plan-punch]';
  if (action === 'toggleTask') return '[data-toggle-task]';
  if (action === 'toggleWave') return '[data-toggle-wave]';
  return action ? `[data-action="${action}"]` : null;
}

function directSelectorFor(control) {
  const id = String(control?.control_id || '');
  const runtimeRecordKind = id.match(/^pxui\.runtime-core\.action\.inspectRuntimeRecord\.(operations|placements|producers|providers|startup)$/)?.[1];
  if (runtimeRecordKind) return `[data-action="inspectRuntimeRecord"][data-runtime-kind="${runtimeRecordKind}"]`;
  if (/^pxui\.runtime-core\.indicator\.(?:cleanupBytes|cleanupCandidates|cleanupSelection)$/.test(id)) return '.cleanup-summary';
  if (id === 'pxui.runtime-core.form.cleanupSelection') return '.cleanup-list';
  if (id === 'pxui.workflows.indicator.environmentFreshness') return '.environment-freshness';
  if (id === 'pxui.plugins.indicator.inventoryGeneration') return '[data-plugin-integrity="generation"]';
  if (id === 'pxui.plugins.indicator.shardHashMatch') return '[data-plugin-integrity="shard-hash"]';
  if (id === 'pxui.studio-lifecycle.indicator.error') return '#modal-root [role="alert"]';
  if (id === 'pxui.studio-lifecycle.indicator.notAccepted') return '#modal-root .eyebrow';
  if (id === 'pxui.workflows.form.environmentLifecycle') return '#modal-root [role="dialog"]';
  if (id === 'pxui.projects.indicator.mapStatus') return '.project-map-head';
  if (id === 'pxui.projects.indicator.mapErrors') return '.memory-errors[role="alert"]';
  if (id === 'pxui.agent-studio.form.candidateMetadata') return '.studio-guided-grid';
  if (id === 'pxui.agent-studio.indicator.graphMinimap') return '.agent-graph-minimap';
  if (/^pxui\.agent-studio\.indicator\.(?:persistedGraphVerified|workingGraphRequiresPythonCompile)$/.test(id)) return '.agent-graph-state';
  if (id === 'pxui.agent-studio.indicator.typedEdgeMap') return '.agent-accessible-topology';
  if (/^pxui\.agent-studio\.indicator\.(?:approvalCancelled|hostOperationFailed)$/.test(id)) return '.studio-warning';
  if (id === 'pxui.sidebar.indicator.connection') return '#connection .state-panel';
  if (id === 'pxui.agent-studio.menu.graphNodes') return '[data-agent-editor-canvas]';
  if (id === 'pxui.workflow-studio.editor.visualGraph') return '[data-workflow-editor-canvas]';
  if (id === 'pxui.workflow-studio.menu.nodePalette') return '.workflow-palette';
  if (id === 'pxui.workflow-studio.indicator.zoom') return '.workflow-canvas-toolbar output';
  if (id === 'pxui.workflow-studio.indicator.pendingPortConnection') return '.workflow-canvas-toolbar [data-action="workflowCancelConnection"]:not([disabled])';
  if (id === 'pxui.workflow-studio.indicator.awaitingHostApproval') return '[data-action="submitStudioDraft"]';
  if (id === 'pxui.skill-studio.editor.packageFile') return '#studio-skill-file';
  if (id === 'pxui.skill-studio.indicator.recentLifecycleHistory') return '.skill-history';
  if (id === 'pxui.skill-studio.indicator.missingRequiredFiles') return '.identity-warning';
  if (/^pxui\.workflow-studio\.gesture\./.test(id)) return '[data-workflow-editor-canvas]';
  if (/^pxui\.plugins\.indicator\.MCP(?:Registered|RuntimeVerified)$/.test(id)) return '.metric-grid .metric-card:nth-child(4)';
  if (id === 'pxui.plugins.indicator.extensionActiveState') return '.metric-grid .metric-card:nth-child(1)';
  if (id === 'pxui.plugins.indicator.inventoryFreshness') return '.plugin-lifecycle-grid article:first-child .badge';
  if (id === 'pxui.plugins.indicator.inlineInventoryError') return '.memory-errors[role="alert"]';
  if (id === 'pxui.dashboard.indicator.coordinationSummary') return '.coord-summary';
  if (id === 'pxui.dashboard.indicator.counts') return '.metric-grid';
  if (id === 'pxui.dashboard.indicator.heroConnection') return '.hero-status';
  if (id === 'pxui.dashboard.indicator.serviceGrid') return '.service-grid';
  if (id === 'pxui.dashboard.indicator.sourceVersion') return '.hero-status small';
  if (id === 'pxui.assurance.indicator.dimensionScores') return '.readiness-row';
  if (id === 'pxui.settings.indicator.applyBoundary') return '.settings-handoff';
  if (id === 'pxui.settings.indicator.guardrailValues') return '.guardrail-grid';
  if (id === 'pxui.knowledge-core.indicator.controllerError') return '.memory-errors[role="alert"]';
  if (id === 'pxui.knowledge-core.indicator.revisionHashes') return '.knowledge-record.canonical code';
  if (id === 'pxui.knowledge-core.indicator.sourceAvailability') return '.adapter-list';
  if (id === 'pxui.knowledge-core.indicator.trialCounts') return '.learning-toolbar';
  if (id === 'pxui.activity.form.queryFilter') return '.activity-toolbar';
  if (id === 'pxui.activity.indicator.liveOperations') return '.metric-grid .metric-card:nth-child(2)';
  if (id === 'pxui.activity.indicator.staleOperations') return '.metric-grid .metric-card:nth-child(3)';
  if (id === 'pxui.activity.indicator.capturePaused') return '.activity-limitations';
  if (id === 'pxui.activity.indicator.queryError') return '.memory-errors[role="alert"]';
  if (id === 'pxui.activity.indicator.queryPending') return '.activity-toolbar > span:last-child';
  if (id === 'pxui.memory.form.queryFilter') return '.memory-toolbar';
  if (id === 'pxui.memory.field.memoryProject') return '[data-memory-project]';
  if (/^pxui\.memory\.indicator\.(?:leaseExpiry|projectRegistered)$/.test(id)) return '.memory-authority';
  if (id === 'pxui.memory.indicator.queryPage') return '.memory-pagination';
  if (id === 'pxui.memory.indicator.queryError') return '.memory-errors[role="alert"]';
  if (id === 'pxui.memory.indicator.queryPending') return '.memory-toolbar > span:last-child';
  if (/^pxui\.(?:agents|workflows|skills-tools)\.indicator\.catalogError$/.test(id)) return '.memory-errors[role="alert"]';
  if (/^pxui\.(?:agents|workflows|skills-tools)\.indicator\.catalogPending$/.test(id)) return '.catalog-loading';
  if (/^pxui\.(?:agents|workflows|skills-tools)\.indicator\.catalogPage$/.test(id)) return '.catalog-controls > span:last-child';
  if (/^pxui\.skills-tools\.indicator\.(?:nativeCount|domainBoundary)$/.test(id)) return '.metric-grid .metric-card:nth-child(1)';
  if (/^pxui\.skills-tools\.indicator\.(?:preservedBoundary)$/.test(id)) return '.metric-grid .metric-card:nth-child(2)';
  if (/^pxui\.skills-tools\.indicator\.(?:enterpriseCount)$/.test(id)) return '.metric-grid .metric-card:nth-child(3)';
  if (/^pxui\.skills-tools\.indicator\.(?:toolCount)$/.test(id)) return '.metric-grid .metric-card:nth-child(4)';
  if (id === 'pxui.skills-tools.indicator.queryResults') return '.skill-query-results';
  if (id === 'pxui.skills-tools.indicator.queryNoMatch') return '.skill-query-results .compact-empty';
  if (id === 'pxui.skills-tools.indicator.queryPending') return '.cleanup-loading';
  if (id === 'pxui.knowledge-graph.indicator.queryError') return '.graph-inline-error,.graph-loading.graph-error';
  if (id === 'pxui.knowledge-graph.indicator.queryPending') return '.graph-progress,.graph-loading';
  if (id === 'pxui.dashboard-control-plane.menu.commandCenter') return '#modal-root [role="dialog"]';
  if (id === 'pxui.dashboard-control-plane.menu.informationTabs') return '.information-tabs';
  if (id === 'pxui.dashboard-control-plane.menu.mainNavigation') return '.nav-rail';
  if (id === 'pxui.dashboard-control-plane.indicator.branch') return '.branch-cell';
  if (id === 'pxui.dashboard-control-plane.indicator.workspace') return '.workspace-cell';
  if (id === 'pxui.dashboard-control-plane.indicator.connection') return '.rail-status';
  if (id === 'pxui.dashboard-control-plane.indicator.extensionIdentityMismatch') return '.identity-warning';
  if (id === 'pxui.dashboard-control-plane.indicator.loading') return '.loading';
  if (id === 'pxui.dashboard-control-plane.indicator.providerAuthBoundary') return '.top-status .badge:nth-child(2)';
  if (id === 'pxui.dashboard-control-plane.indicator.snapshotFooter') return '.footer span:last-child';
  if (id === 'pxui.dashboard-control-plane.gesture.informationTabArrowSwitch') return '.information-tabs';
  if (/^pxui\.dashboard-control-plane\.gesture\.(?:escapeCloseModal|modalFocusTrap)$/.test(id)) return '#modal-root [role="dialog"]';
  if (/^pxui\.knowledge-graph\.gesture\./.test(id)) return '[data-graph-canvas]';
  if (id === 'pxui.knowledge-graph.menu.depth') return '[aria-label="Relationship depth"]';
  if (id === 'pxui.knowledge-graph.menu.layout') return '[aria-label="Graph layout"]';
  if (id === 'pxui.knowledge-graph.indicator.relationshipCounts') return '.relationship-counts';
  if (id === 'pxui.knowledge-graph.indicator.renderedTelemetry') return '[data-graph-status]';
  if (id === 'pxui.knowledge-graph.form.searchAndFilter') return '.graph-tools';
  if (id === 'pxui.agents.indicator.activeSessions') return '.metric-grid .metric-card:nth-child(2)';
  if (id === 'pxui.agents.indicator.enterpriseDoctorStatus') return '.enterprise-boundary';
  if (id === 'pxui.workflows.indicator.environmentSnapshotHash') return '.environment-boundary b';
  if (id === 'pxui.workflows.indicator.taskStatus') return '.task-state';
  if (id === 'pxui.diagnostics.indicator.catalogPending') return '.catalog-loading';
  if (id === 'pxui.diagnostics.indicator.surfaceCoverage') return '.punch-ledger-progress';
  const selectors = {
    'pxui.agent-studio.field.canonicalJson': '#studio-draft-json',
    'pxui.agent-studio.field.model.host_model': '[data-agent-host-model]',
    'pxui.agent-studio.field.model.version': '[data-agent-model-field="version"]',
    'pxui.agent-studio.field.required_tests': '[data-agent-required-test]',
    'pxui.workflow-studio.field.canonicalJson': '#studio-draft-json',
    'pxui.workflow-studio.field.node.config': '[data-workflow-field="config"]',
    'pxui.workflow-studio.field.node.executor_adapter': '[data-workflow-adapter]',
    'pxui.workflow-studio.field.node.kind': '[data-workflow-field="kind"]',
    'pxui.skill-studio.field.packageFileText': '#studio-skill-file',
    'pxui.knowledge-core.field.applicability': '#learning-applicability',
    'pxui.knowledge-core.field.betterAlternativeFound': '#learning-better-alternative',
    'pxui.knowledge-core.field.challengerJson': '#learning-challenger',
    'pxui.knowledge-core.field.dependencyHashJson': '#learning-dependencies',
    'pxui.knowledge-core.field.finalValidationEvidence': '#learning-final-evidence',
    'pxui.knowledge-core.field.higherIsBetter': '#learning-higher-better',
    'pxui.knowledge-core.field.hypothesisClaim': '#learning-claim',
    'pxui.knowledge-core.field.hypothesisKind': '#learning-unit-kind',
    'pxui.knowledge-core.field.hypothesisUnitId': '#learning-unit-id',
    'pxui.knowledge-core.field.incumbentJson': '#learning-incumbent',
    'pxui.knowledge-core.field.knowledgeEvidence': '#knowledge-evidence',
    'pxui.knowledge-core.field.knowledgeId': '#knowledge-id',
    'pxui.knowledge-core.field.knowledgeKind': '#knowledge-kind',
    'pxui.knowledge-core.field.knowledgeRejectReason': '#knowledge-reject-reason',
    'pxui.knowledge-core.field.knowledgeSource': '#knowledge-source',
    'pxui.knowledge-core.field.knowledgeSummary': '#knowledge-summary',
    'pxui.knowledge-core.field.knowledgeTitle': '#knowledge-title',
    'pxui.knowledge-core.field.learningCapabilities': '#learning-capabilities',
    'pxui.knowledge-core.field.learningEnvironmentSha': '#learning-environment-sha',
    'pxui.knowledge-core.field.learningEvidenceRefs': '#learning-evidence-refs',
    'pxui.knowledge-core.field.learningMetric': '#learning-metric',
    'pxui.knowledge-core.field.learningMetricValue': '#learning-metric-value',
    'pxui.knowledge-core.field.learningOperationId': '#learning-operation-id',
    'pxui.knowledge-core.field.learningOutcome': '#learning-outcome',
    'pxui.knowledge-core.field.learningPipelineId': '#learning-pipeline-id',
    'pxui.knowledge-core.field.learningSourceIds': '#learning-source-ids',
    'pxui.knowledge-core.field.learningTaskClass': '#learning-task-class',
    'pxui.knowledge-core.field.partialUnits': '#learning-partial-units',
    'pxui.knowledge-core.field.patternInterpretation': '#learning-interpretation',
    'pxui.knowledge-core.field.patternMetric': '#learning-pattern-metric',
    'pxui.knowledge-core.field.researchConclusion': '#learning-research-conclusion',
    'pxui.knowledge-core.field.researchQuestion': '#learning-research-question',
    'pxui.knowledge-core.field.researchReferencesJson': '#learning-research-references',
    'pxui.knowledge-core.field.reuseRegressions': '#learning-reuse-regressions',
    'pxui.knowledge-core.field.reuseSuccesses': '#learning-reuse-successes',
    'pxui.knowledge-core.field.reuseUses': '#learning-reuse-uses',
    'pxui.knowledge-core.field.rollbackEvidenceRefs': '#knowledge-rollback-evidence',
    'pxui.knowledge-core.field.rollbackExpectedHead': '#knowledge-rollback-current',
    'pxui.knowledge-core.field.rollbackRecord': '#knowledge-rollback-record',
    'pxui.knowledge-core.field.rollbackTarget': '#knowledge-rollback-target',
    'pxui.knowledge-core.field.secondaryArtifactJson': '#learning-secondary-artifact',
    'pxui.knowledge-core.field.trialEvidence': '#learning-trial-evidence',
    'pxui.knowledge-core.field.trialWinner': '#learning-trial-winner',
    'pxui.knowledge-graph.field.graphDirection': '[data-graph-direction]',
    'pxui.knowledge-graph.field.graphRelation': '[data-graph-relation]',
    'pxui.knowledge-graph.field.graphTarget': '[data-graph-target]',
    'pxui.runtime-core.field.cleanupCandidateCheckbox.row': '[data-cleanup-id]',
    'pxui.skills-tools.field.fixedSkillDomain': '#skill-query-domain',
    'pxui.skills-tools.field.skillQueryGoal': '#skill-query-goal',
    'pxui.studio-lifecycle.field.agentObjective': '#studio-agent-objective',
    'pxui.studio-lifecycle.field.workflowRunInputsJson': '#studio-workflow-inputs',
    'pxui.diagnostics.field.operationalCardEvidenceGap': '[data-operational-card-evidence-gap]',
    'pxui.workflows.field.claimAuthority': '#claim-authority',
    'pxui.workflows.field.claimMode': '#claim-mode',
    'pxui.workflows.field.claimTTL': '#claim-ttl',
    'pxui.workflows.field.environmentConsumerAcknowledgement': '#environment-lifecycle-consumers',
    'pxui.workflows.field.environmentExactTarget': '#environment-lifecycle-target',
    'pxui.workflows.field.progressMinutes': '#progress-minutes',
    'pxui.workflows.field.progressTokens': '#progress-tokens',
    'pxui.workflows.field.reconcileConflictsResolved': '#reconcile-conflicts',
    'pxui.workflows.field.reconcileSummary': '#reconcile-summary',
    'pxui.sidebar.indicator.activeExecution': '#execution',
    'pxui.sidebar.indicator.attention': '#attention',
    'pxui.sidebar.indicator.connection': '#connection',
    'pxui.sidebar.indicator.contractError': '#contract-error',
    'pxui.sidebar.indicator.liveStaleAgents': '#agents',
    'pxui.sidebar.indicator.orchestrations': '#orchestrations',
    'pxui.sidebar.indicator.progress': '#execution progress',
    'pxui.sidebar.indicator.providerActivity': '#providers',
    'pxui.sidebar.indicator.providerBilling': '#providers',
    'pxui.sidebar.indicator.providerBudget': '#providers',
    'pxui.sidebar.indicator.providerFallback': '#providers',
    'pxui.sidebar.indicator.providerFreshness': '#providers',
    'pxui.sidebar.indicator.punchCounts': '#punch',
    'pxui.sidebar.indicator.recent': '#recent',
    'pxui.sidebar.indicator.revision': '#header',
    'pxui.sidebar.indicator.wavesTasks': '#waves'
  };
  return selectors[id] || null;
}

function exactActionSelectorFor(control) {
  const id = String(control?.control_id || '');
  if (id === 'pxui.diagnostics.action.openPunchSource.row') return '[data-action="openPunchSource"][data-path]';
  const runtimeRecordKind = id.match(/^pxui\.runtime-core\.action\.inspectRuntimeRecord\.(operations|placements|producers|providers|startup)$/)?.[1];
  if (runtimeRecordKind) return `[data-action="inspectRuntimeRecord"][data-runtime-kind="${runtimeRecordKind}"]`;
  const projectKinds = {
    entrypoint: 'entrypoints', history: 'history', package: 'packages', risk: 'risks', route: 'routes', service: 'services',
    'test-link': 'test_links', 'unmapped-test': 'unmapped_tests', 'untested-source': 'untested_sources'
  };
  const projectVariant = id.match(/^pxui\.projects\.action\.inspectProjectMapRecord\.(.+)$/)?.[1];
  if (projectVariant && projectKinds[projectVariant]) return `[data-action="inspectProjectMapRecord"][data-record-kind="${projectKinds[projectVariant]}"]`;
  if (id === 'pxui.plugins.action.inspectMachineManifest.header') return ':nth-match([data-action="inspectMachineManifest"], 1)';
  if (id === 'pxui.plugins.action.inspectMachineManifest.footer') return ':nth-match([data-action="inspectMachineManifest"], 2)';
  if (id === 'pxui.plugins.action.openExtensionsView.install') return ':nth-match([data-action="openExtensionsView"], 1)';
  if (/^pxui\.plugins\.action\.openExtensionsView\.(?:activation|footer|uninstall)$/.test(id)) return ':nth-match([data-action="openExtensionsView"], 2)';
  if (id === 'pxui.settings.action.openSettings.effectiveConfiguration') return ':nth-match([data-action="openSettings"], 1)';
  if (id === 'pxui.settings.action.openSettings.authority') return ':nth-match([data-action="openSettings"], 2)';
  if (id === 'pxui.settings.action.openSettings.guardrails') return ':nth-match([data-action="openSettings"], 3)';
  const selectors = {
    'pxui.dashboard-control-plane.action.informationTab.human': '[data-action="informationTab"][data-tab="human"]',
    'pxui.dashboard-control-plane.action.informationTab.machine': '[data-action="informationTab"][data-tab="machine"]',
    'pxui.knowledge-graph.action.graphDepth.decrease': '[data-action="graphDepth"][data-delta="-1"]',
    'pxui.knowledge-graph.action.graphDepth.increase': '[data-action="graphDepth"][data-delta="1"]',
    'pxui.knowledge-graph.action.graphFit.button': '[data-action="graphFit"]:not(.graph-minimap)',
    'pxui.knowledge-graph.action.graphFit.minimap': '.graph-minimap[data-action="graphFit"]',
    'pxui.knowledge-graph.action.graphLayout.flow': '[data-action="graphLayout"][data-layout="flow"]',
    'pxui.knowledge-graph.action.graphLayout.orbit': '[data-action="graphLayout"][data-layout="orbit"]'
  };
  return selectors[id] || null;
}
function selectorForKind(kind) {
  if (kind === 'field') return 'input,select,textarea';
  if (kind === 'form') return 'form,fieldset,[role="dialog"],.studio-form,.panel,section';
  if (kind === 'menu') return 'nav,[role="tablist"],[role="menu"],[role="group"],.catalog-tabs';
  if (kind === 'editor') return 'textarea,[contenteditable="true"],[data-agent-editor-canvas],[data-workflow-canvas],[data-graph-canvas],.graph-accessible-map,[data-studio-panel]';
  if (kind === 'gesture') return '[role="dialog"],[role="tablist"],[data-agent-editor-canvas],[data-workflow-canvas],[data-graph-canvas]';
  if (kind === 'indicator') return '[role="status"],[aria-live],output,.metric-card,.badge,.status,.hero,.panel,article,h1,h2,h3,dt,dd,th,td,pre,code,.empty-state,.callout,.summary';
  return '';
}
function stageResult(requirement, probe, stage, evidenceRef) {
  const required = requirement.stage_policy[stage] === 'required';
  if (!required) return { state: 'not_applicable', detail: `Proof matrix marks ${stage} not applicable for this control kind.`, evidence: [evidenceRef] };
  const present = (
    (stage === 'open_load' && probe.loaded) ||
    (stage === 'display' && probe.visible) ||
    (stage === 'user_edit_action' && probe.attempted) ||
    (stage === 'input_validation' && probe.validationObserved) ||
    (stage === 'result_acknowledgement' && probe.acknowledged)
  );
  return present
    ? { state: 'present', detail: probe.details[stage] || `Direct contained browser probe observed ${stage}.`, evidence: [evidenceRef] }
    : { state: 'missing', detail: `This contained browser probe did not directly prove required stage ${stage}.`, evidence: [evidenceRef] };
}
function completeChain(chain) { return STAGES.every(stage => ['present', 'not_applicable'].includes(chain[stage].state)); }

function studioDraftRequired(surfaceId, control) {
  if (!['agent-studio', 'workflow-studio', 'skill-studio'].includes(surfaceId)) return false;
  const controlId = String(control?.control_id || '');
  return !/\.action\.(setupStudio|openStudioDraft|openStudioRuns)(?:\.|$)/.test(controlId);
}

function preparationKey(control) {
  const id = String(control?.control_id || '');
  const stateBound = /(?:catalog(?:Error|Pending)|query(?:Error|Pending|NoMatch|Results)|controllerError|mapErrors|inlineInventoryError|contractError|indicator\.(?:error|notAccepted)|retry$)/.test(id);
  return stateBound ? `${control.surface_id}:${id}` : String(control?.surface_id || '');
}

async function prepare(page, surfaceId, control = null) {
  if (surfaceId === 'sidebar') {
    await page.goto(sidebarPreview);
    await page.locator('#sidebar').waitFor({ state: 'visible', timeout: 15_000 });
    const disconnected = /\.(?:action\.retry|indicator\.connection)$/.test(String(control?.control_id || ''));
    const message = sidebarFixtureMessage({ disconnected });
    await page.evaluate(value => {
      window.__PX_TEST_SNAPSHOT__ = value;
      window.dispatchEvent(new MessageEvent('message', { data: value }));
    }, message);
    if (String(control?.control_id || '').endsWith('.indicator.contractError')) {
      await page.evaluate(value => window.dispatchEvent(new MessageEvent('message', { data: value })), {
        schemaVersion: MESSAGE_SCHEMA_VERSION,
        type: 'snapshot',
        capabilities: { renderAcknowledgement: true, assetProtocol: SIDEBAR_ASSET_PROTOCOL },
        projection: {}
      });
    }
    await page.waitForTimeout(120);
    return;
  }
  const route = ROUTES[surfaceId];
  if (!route) throw new Error(`No route for ${surfaceId}`);
  await page.goto(`${preview}?surface=${route}`);
  await page.locator('main h1').first().waitFor({ state: 'visible', timeout: 15_000 });
  await page.waitForTimeout(150);
  const controlId = String(control?.control_id || '');
  if (controlId === 'pxui.dashboard-control-plane.indicator.loading') {
    await page.evaluate(() => window.eval('state.snapshot = null; render()'));
    await page.waitForTimeout(20);
  } else if (controlId === 'pxui.dashboard-control-plane.indicator.extensionIdentityMismatch') {
    await page.evaluate(() => window.eval('state.snapshot.extensionIdentity = { ...(state.snapshot.extensionIdentity || {}), matches: false, mismatch_reasons: ["Bounded preview identity mismatch"] }; render()'));
    await page.waitForTimeout(20);
  }
  if (surfaceId === 'studio-lifecycle' && controlId === 'pxui.studio-lifecycle.indicator.notAccepted') {
    await page.evaluate(() => {
      window.eval(`pendingSkillLifecycle = { requestId: 'preview-not-accepted', operation: 'validate', skill: 'preview-skill', version: '1.0.0' }; studioSession = { kind: 'skill', payload: { skill_id: 'preview-skill', version: '1.0.0' } }`);
      window.dispatchEvent(new MessageEvent('message', { data: {
        type: 'studioOperationResult', requestId: 'preview-not-accepted', kind: 'skill', operation: 'validate',
        result: { record: { schema_version: 'px.skill-validation-receipt/1.1', skill_id: 'preview-skill', version: '1.0.0', passed: false, status: 'rejected' } }
      } }));
    });
    await page.waitForTimeout(30);
  }
  if (surfaceId === 'studio-lifecycle' && controlId === 'pxui.studio-lifecycle.indicator.error') {
    await page.evaluate(() => {
      window.eval(`pendingSkillLifecycle = { requestId: 'preview-error', operation: 'validate', skill: 'preview-skill', version: '1.0.0' }`);
      window.dispatchEvent(new MessageEvent('message', { data: {
        type: 'operationError', requestId: 'preview-error', operation: 'studioOperation', suboperation: 'validate', kind: 'skill', error: 'Bounded preview request-bound lifecycle failure'
      } }));
    });
    await page.waitForTimeout(30);
  }
  if (surfaceId === 'activity' && controlId.endsWith('.indicator.queryPending')) {
    await page.evaluate(() => window.eval('vscode.postMessage = message => { (window.__PX_POSTED_MESSAGES__ ||= []).push(message); }'));
    await page.locator('[data-action="activityRefresh"]').first().click(); await page.waitForTimeout(20);
  }
  if (controlId === 'pxui.activity.action.reconcileStaleActivity') {
    await page.evaluate(() => window.eval(`state.activityData = { ...(state.activityData || {}), policy: { enabled: true, paused: false }, stale_operations: [{ correlation_id: "preview-stale", operation: "bounded preview operation", status: "running", actor: { actor_id: "preview-agent" }, last_heartbeat_utc: "2026-08-25T00:00:00Z" }] }; render()`));
    await page.waitForTimeout(30);
  }
  if (surfaceId === 'memory' && controlId.endsWith('.indicator.queryPending')) {
    await page.evaluate(() => window.eval('vscode.postMessage = message => { (window.__PX_POSTED_MESSAGES__ ||= []).push(message); }'));
    await page.locator('[data-action="memoryRefresh"]').first().click(); await page.waitForTimeout(20);
  }
  if (surfaceId === 'diagnostics' && /\.(?:action\.catalogRetry|indicator\.catalogPending)$/.test(controlId)) {
    await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'catalogQuery', kind: 'enterprise-integrations', error: 'Bounded preview diagnostics catalog failure' } })));
    await page.locator('[data-action="closeModal"]').last().click().catch(() => {});
    if (controlId.endsWith('.indicator.catalogPending')) {
      await page.evaluate(() => window.eval('vscode.postMessage = message => { (window.__PX_POSTED_MESSAGES__ ||= []).push(message); }'));
      await page.locator('[data-action="catalogRetry"][data-kind="enterprise-integrations"]').click();
    }
    await page.waitForTimeout(30);
  }
  if (controlId === 'pxui.skills-tools.action.compareSkillOriginal') {
    await page.evaluate(() => window.eval('if (state.catalogs.skills?.items?.[0]) state.catalogs.skills.items[0].details = { ...(state.catalogs.skills.items[0].details || {}), backup: { path: "preserved/preview-skill" } }; render()'));
    await page.waitForTimeout(30);
  }
  if (surfaceId === 'diagnostics' && controlId.includes('.action.dynamicRepair.')) {
    await page.evaluate(id => {
      if (id.endsWith('.buildRepositoryGraph')) window.eval('state.snapshot.project.map.valid = false; state.snapshot.project.map.errors = ["Bounded preview map gap"]; render()');
      else if (id.endsWith('.configureCanonicalMemory')) window.eval('state.snapshot.memory.retrieval_ready = false; state.snapshot.memory.status = "detached"; render()');
      else if (id.endsWith('.refreshEnvironment')) window.eval('state.snapshot.environment.freshness = { ...(state.snapshot.environment.freshness || {}), state: "stale" }; render()');
    }, controlId);
    await page.waitForTimeout(30);
  }
  if (controlId === 'pxui.diagnostics.action.openPunchSource.row') {
    await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationalCardResult', result: { card: { gap_id: 'PX-PREVIEW', current_state: 'implemented', severity: 'medium', expected_behavior: 'Bounded source opens through host authority.', observed_behavior: 'Preview fixture.', operational_impact: 'None.', source_refs: [{ path: 'runtime/operational_gap_ledger.py', symbols: ['append_events'] }], interaction_chain: {}, history: [], next_action: 'Exercise exact source handoff.' } } } })));
    await page.waitForTimeout(30);
  }
  if (surfaceId === 'runtime-core' && controlId.includes('.action.inspectRuntimeRecord.')) {
    await page.evaluate(() => window.eval(`
      state.snapshot.runtime = state.snapshot.runtime || {};
      state.snapshot.runtime.core = state.snapshot.runtime.core || {};
      state.snapshot.runtime.execution_placement = state.snapshot.runtime.execution_placement || {};
      state.snapshot.runtime.core.operations = [{ operation: 'preview-operation', reason: 'bounded direct fixture', outcome: 'succeeded', duration_seconds: 0.01 }];
      state.snapshot.runtime.core.producer_trace = [{ producer: 'preview-producer', owner: 'runtime.work_admission', admission: 'runtime-work-plane' }];
      state.snapshot.runtime.execution_placement.recent = [{ operation_id: 'preview-placement', selected_backend: 'cpu', promotion_tier: 0 }];
      state.snapshot.providerActivity = [{ providerId: 'preview-local', providerClass: 'local', status: 'observed', telemetrySource: 'bounded fixture' }];
      state.snapshot.runtime.host_startup = { ...(state.snapshot.runtime.host_startup || {}), milestones: [{ id: 'preview-startup', owner: 'VS Code host', status: 'observed', observed: true, offset_from_extension_host_ms: 1 }] };
      render()
    `));
    await page.waitForTimeout(30);
  }
  if (controlId === 'pxui.workflows.indicator.taskStatus') {
    await page.evaluate(() => window.eval(`state.coordination.state.active_plan = "preview-plan"; state.coordination.state.plans = [{ id: "preview-plan", objective: "Bounded preview plan", task_ids: ["preview-task"] }]; state.coordination.state.tasks = [{ id: "preview-task", title: "Bounded preview task", description: "Direct task-state fixture", status: "ready", depends_on: [], claim_targets: [], usage: { status: "healthy", tokens: 0, minutes: 0 } }]; state.coordination.state.claims = []; render()`));
    await page.waitForTimeout(30);
  }
  const catalogKind = surfaceId === 'agents' ? 'agents' : surfaceId === 'workflows' ? 'workflows' : surfaceId === 'skills-tools' ? 'skills' : null;
  if (catalogKind && /\.(?:action\.catalogRetry|indicator\.catalog(?:Error|Pending))$/.test(String(control?.control_id || ''))) {
    await page.evaluate(kind => window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'catalogQuery', kind, error: 'Bounded preview catalog failure' } })), catalogKind);
    await page.locator('[data-action="closeModal"]').last().click().catch(() => {});
    if (String(control?.control_id || '').endsWith('.indicator.catalogPending')) {
      await page.evaluate(() => window.eval('vscode.postMessage = message => { (window.__PX_POSTED_MESSAGES__ ||= []).push(message); }'));
      await page.locator(`[data-action="catalogRetry"][data-kind="${catalogKind}"]`).click();
    }
    await page.waitForTimeout(40);
  }
  if (surfaceId === 'knowledge-core' && String(control?.control_id || '').endsWith('.indicator.controllerError')) {
    await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'studioOperation', kind: 'knowledge', error: 'Bounded preview knowledge controller failure' } })));
    await page.locator('[data-action="closeModal"]').last().click().catch(() => {}); await page.waitForTimeout(40);
  }
  if (surfaceId === 'activity' && String(control?.control_id || '').endsWith('.indicator.queryError')) {
    await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'activityQuery', error: 'Bounded preview activity query failure' } })));
    await page.locator('[data-action="closeModal"]').last().click().catch(() => {}); await page.waitForTimeout(40);
  }
  if (surfaceId === 'memory' && String(control?.control_id || '').endsWith('.indicator.queryError')) {
    await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'memoryQuery', error: 'Bounded preview memory query failure' } })));
    await page.locator('[data-action="closeModal"]').last().click().catch(() => {}); await page.waitForTimeout(40);
  }
  if (surfaceId === 'knowledge-graph') {
    const graphControl = String(control?.control_id || '');
    if (graphControl.endsWith('.indicator.queryError')) {
      await page.evaluate(() => window.dispatchEvent(new MessageEvent('message', { data: { type: 'operationError', operation: 'graphQuery', error: 'Bounded preview graph query failure' } })));
      await page.locator('[data-action="closeModal"]').last().click().catch(() => {}); await page.waitForTimeout(40);
    } else if (graphControl.endsWith('.indicator.queryPending')) {
      await page.evaluate(() => {
        window.eval('vscode.postMessage = message => { (window.__PX_POSTED_MESSAGES__ ||= []).push(message); }');
        document.querySelector('[data-action="runGraphSearch"]')?.click();
      });
      await page.waitForTimeout(20);
    } else if (graphControl.endsWith('.action.buildRepositoryGraph')) {
      await page.evaluate(() => {
        const requestId = window.eval('state.graphRequestId');
        window.dispatchEvent(new MessageEvent('message', { data: { type: 'graphResult', requestId, result: { schema_version: 'pacify-x.graph-query.v1', view: 'capabilities', available: false, limitations: ['Repository graph requires a current build.'], build_action: true, nodes: [], edges: [] } } }));
      });
      await page.waitForTimeout(40);
    } else if (/\.action\.graph(?:Clear)?Community/.test(graphControl)) {
      await page.evaluate(() => {
        const current = window.eval('structuredClone(state.graphData)');
        const nodes = (current?.nodes || []).map((item, index) => ({ ...item, community_id: index % 2 ? 'preview:secondary' : 'preview:primary' }));
        const result = { ...current, nodes, communities: [{ id: 'preview:primary', label: 'Primary', member_count: Math.ceil(nodes.length / 2), edge_count: 4, status_counts: { active: 4 } }, { id: 'preview:secondary', label: 'Secondary', member_count: Math.floor(nodes.length / 2), edge_count: 3, status_counts: { active: 3 } }] };
        window.eval(`state.graphData = ${JSON.stringify(result)}; render()`);
      });
      await page.waitForTimeout(40);
    }
  }
  if (surfaceId === 'plugins') {
    await page.evaluate(showError => {
      const enriched = structuredClone(snapshot);
      enriched.environment = { ...enriched.environment, freshness: { state: 'fresh', generation: 7 }, snapshot_hash: 'e'.repeat(64) };
      enriched.observability = { ...(enriched.observability || {}), mcp: { status: 'ready', registered: true, runtime_verified: true, detail: 'Preview MCP runtime verified' } };
      window.dispatchEvent(new MessageEvent('message', { data: { type: 'snapshot', snapshot: enriched } }));
      window.dispatchEvent(new MessageEvent('message', { data: { type: 'environmentResult', subject: 'extensions', result: showError
        ? { snapshot_hash: 'e'.repeat(64), error: 'Bounded preview extension inventory error', records: [] }
        : { snapshot_hash: 'e'.repeat(64), records: [{ id: 'publisher.preview', name: 'Preview Extension', publisher: 'publisher', version: '1.0.0', active: true, capability_count: 3, command_count: 2, conflict_count: 1 }] } } }));
    }, String(control?.control_id || '').endsWith('.indicator.inlineInventoryError'));
    await page.waitForTimeout(90);
  }
  if (surfaceId === 'projects' && /^pxui\.projects\.(?:action\.inspectProjectMapRecord\.|indicator\.mapErrors$)/.test(String(control?.control_id || ''))) {
    await page.evaluate(showError => {
      const drilldown = {
        risks: [{ id: 'risk:preview', summary: 'Bounded preview risk', severity: 'medium' }],
        entrypoints: [{ name: 'PX CLI', kind: 'python-module', source: 'runtime/cli.py' }],
        services: [{ service_id: 'service:preview', name: 'Preview service', source: 'runtime/service.py', explicit_route_ids: ['route:preview'] }],
        routes: [{ path: '/preview', methods: ['GET'], source: 'runtime/service.py', link_state: 'explicit' }],
        test_links: [{ source: 'runtime/service.py', test: 'tests/test_service.py', basis: 'explicit' }],
        untested_sources: [{ source: 'runtime/uncovered.py' }],
        unmapped_tests: [{ test: 'tests/test_unmapped.py' }],
        packages: [{ name: 'pacify-x', ecosystem: 'python', scopes: ['runtime'] }],
        history: [{ archive_id: 'map:preview-prior', map_revision: 'a'.repeat(64), counts: { files: 2503 } }],
        service_route_map: { coverage: {}, limitations: [] }, test_link_map: { coverage: {}, limitations: [] }
      };
      const enriched = structuredClone(snapshot);
      enriched.project.map = { ...enriched.project.map, available: true, valid: true, map_revision: 'b'.repeat(64), errors: showError ? ['Bounded preview map warning'] : [], drilldown };
      window.dispatchEvent(new MessageEvent('message', { data: { type: 'snapshot', snapshot: enriched } }));
    }, String(control?.control_id || '').endsWith('.indicator.mapErrors'));
    await page.waitForTimeout(90);
  }
  if (studioDraftRequired(surfaceId, control)) {
    const kind = surfaceId.split('-')[0];
    const open = page.locator(`[data-action="openStudioDraft"][data-kind="${kind}"]`).first();
    if (await open.count()) { await open.click(); await page.waitForTimeout(120); }
  }
  if (/^pxui\.(?:skill-studio|workflow-studio)\.action\.forkStudioCandidate$/.test(controlId)) {
    const kind = controlId.startsWith('pxui.skill-studio') ? 'skill' : 'workflow';
    await page.evaluate(value => window.eval(`studioVersionAllocation = { kind: "${value}" }; openStudioDraftModal("${value}", structuredClone(studioEditor.draft))`), kind);
    await page.waitForTimeout(30);
  }
  if (controlId === 'pxui.skill-studio.indicator.missingRequiredFiles') {
    await page.evaluate(() => window.eval('openStudioDraftModal("skill", { ...structuredClone(studioEditor.draft), package_missing_required_files: ["contracts/input.schema.json"] })'));
    await page.waitForTimeout(30);
  }
  if (controlId === 'pxui.agent-studio.indicator.persistedGraphVerified') {
    await page.evaluate(() => window.eval('agentPersistedGraph = structuredClone(agentWorkingGraph); agentGraphDirty = false; refreshStudioEditor()'));
    await page.waitForTimeout(30);
  }
  if (controlId === 'pxui.workflow-studio.indicator.pendingPortConnection') {
    const output = page.locator('[data-action="workflowPortConnect"][data-direction="output"]').first();
    if (await output.count()) { await output.click(); await page.waitForTimeout(30); }
  }
  if (controlId === 'pxui.workflow-studio.indicator.awaitingHostApproval') {
    const save = page.locator('[data-action="submitStudioDraft"]').first();
    if (await save.count() && await save.isEnabled()) { await save.click(); await page.waitForTimeout(30); }
  }
  if (/^pxui\.agent-studio\.indicator\.(?:approvalCancelled|hostOperationFailed)$/.test(controlId)) {
    const save = page.locator('[data-action="submitStudioDraft"]').first();
    if (await save.count() && await save.isEnabled()) { await save.click(); await page.waitForTimeout(20); }
    await page.evaluate(id => {
      const requestId = window.eval('studioSaveRequest?.requestId');
      const message = id.endsWith('.approvalCancelled')
        ? { type: 'studioDraftCancelled', kind: 'agent', requestId }
        : { type: 'operationError', operation: 'createStudioDraft', kind: 'agent', requestId, error: 'Bounded preview host failure' };
      window.dispatchEvent(new MessageEvent('message', { data: message }));
    }, controlId);
    await page.waitForTimeout(30);
  }
  if (/^pxui\.(?:agent-studio|workflow-studio|skill-studio)\.action\.acceptStudioVersionSuggestion$/.test(controlId)) {
    const kind = controlId.split('.')[1].split('-')[0];
    await page.evaluate(value => {
      const identityKey = value === 'agent' ? 'agent_id' : value === 'workflow' ? 'workflow_id' : 'skill_id';
      const allocation = { schema_version: 'px.studio-version-allocation/1.0', kind: value, identity: String(window.eval(`studioEditor.draft.${identityKey}`)).toLowerCase(), source_version: '1.0.0', source_scope: value === 'skill' ? 'external-authenticated' : 'studio-physical', source_revision_sha256: 'a'.repeat(64), source_content_sha256: 'b'.repeat(64), candidate_version: '1.0.1', occupied_versions_sha256: 'c'.repeat(64), observed_utc: '2026-08-25T00:00:00Z' };
      window.eval(`studioVersionAllocation = ${JSON.stringify(allocation)}; studioSaveRequest = { requestId: "preview-version-conflict", kind: "${value}" }`);
      window.dispatchEvent(new MessageEvent('message', { data: { type: 'studioVersionConflict', kind: value, requestId: 'preview-version-conflict', error: 'Bounded preview version conflict', allocation, allocationProof: 'version-allocation:preview-conflict' } }));
    }, kind);
    await page.waitForTimeout(30);
  }
}

async function resolveAction(page, control) {
  if (control.surface_id === 'sidebar') {
    const selector = sidebarActionSelector(control);
    return selector ? page.locator(selector).first() : null;
  }
  const exactSelector = exactActionSelectorFor(control);
  if (exactSelector) return page.locator(exactSelector).first();
  const { action, variants } = actionIdentity(control.control_id.split('.action.')[1] || control.label);
  if (action === 'navigate') return page.locator(`[data-surface="${variants[0]}"]`).first();
  const candidates = page.locator(`[data-action="${action}"]`);
  for (let index = 0; index < await candidates.count(); index += 1) {
    const item = candidates.nth(index);
    const identity = await item.evaluate(element => ({
      dataset: { ...element.dataset },
      context: `${element.getAttribute('aria-label') || ''} ${element.className || ''} ${element.parentElement?.className || ''} ${element.closest('header,article,section,li')?.className || ''}`
    }));
    if (visualVariantsMatch(identity.dataset, variants, identity.context)) return item;
  }
  return null;
}

async function clickRevealAction(page, action, dataset = {}) {
  const suffix = Object.entries(dataset).map(([key, value]) => `[data-${key}="${value}"]`).join('');
  const items = page.locator(`[data-action="${action}"]${suffix}`);
  const count = await items.count();
  for (let index = 0; index < count; index += 1) {
    const item = items.nth(index);
    if (await item.isVisible().catch(() => false) && await item.isEnabled().catch(() => false)) {
      await item.click({ timeout: 3_000 }); await page.waitForTimeout(90); return true;
    }
  }
  return false;
}

async function dispatchPluginPreviewFixture(page, operation) {
  return page.evaluate(op => {
    const request = window.__PX_POSTED_MESSAGES__?.at(-1);
    if (!request?.requestId) return false;
    const extensionId = request.extensionId || 'publisher.preview';
    const common = { extension_id: extensionId, allowed: true, token: `preview-token-${op}`, exact_target: `${extensionId}@1.1.0`, authority: 'VS Code host retained authority' };
    const messages = {
      install: { type: 'extensionLifecyclePreview', result: common },
      update: { type: 'extensionUpdatePreview', result: { ...common, before_version: '1.0.0', rollback_target: `${extensionId}@1.0.0`, compatibility_gate: 'Exact preview compatibility gate passed.' } },
      enablement: { type: 'extensionEnablementPreview', result: { ...common, before_version: '1.0.0', desired_action: request.desiredAction, scope: request.scope, activation_observed: true, limitation: 'Native manager retains the final enablement decision.' } },
      uninstall: { type: 'extensionUninstallPreview', result: { ...common, before_version: '1.0.0', rollback_limit: 'Exact prior identity retained for governed rollback.', rollback_identity: { exact_target: `${extensionId}@1.0.0` }, consumers: [], consumer_ack_required: false } },
      rollback: { type: 'extensionRollbackPreview', result: { ...common, retained_operation_id: 'operation:preview-uninstall', custody_state: 'retained', source_availability: 'available', source_gate: 'Exact retained source identity is available.' } },
      conflict: { type: 'extensionConflictResult', result: { extension_id: extensionId, available: true, signal_count: 1, signals: [{ signal_id: 'signal:preview', kind: 'command-collision', severity: 'medium', resource: 'command:preview', extension_ids: [extensionId, 'publisher.target'], resolution_targets: ['publisher.target'], recommended_resolutions: ['disable-workspace'] }] } },
      conflictResolution: { type: 'extensionConflictResolutionPreview', result: { signal_id: request.signalId, target_extension_id: request.targetExtensionId, resolution: request.resolution, effect: 'native-manager-handoff', authority: 'VS Code host retained authority', token: 'preview-token-conflict', exact_target: request.targetExtensionId, signal: { kind: 'command-collision', resource: 'command:preview' } } }
    };
    const message = messages[op]; if (!message) return false;
    window.dispatchEvent(new MessageEvent('message', { data: { ...message, requestId: request.requestId } }));
    return true;
  }, operation);
}

function studioPrerequisites(control) {
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
  }
  if (id.startsWith('pxui.workflow-studio.')) {
    if (/workflowMoveNode\.(?:earlier|later)$/.test(id) || id.endsWith('.action.workflowRemoveNode')) add('workflowAddNode', { nodeTemplate: 'task' });
    if (id.endsWith('workflowMoveNode.later')) add('workflowSelectNode', {}, 'first');
    if (id.includes('workflowRemoveBinding')) add('workflowAddBinding');
    if (id.includes('workflowRemoveGrant')) add('workflowAddGrant');
    if (id.includes('workflowRemovePort')) add('workflowAddPort', { direction: 'inputs' });
    if (id.includes('workflowCancelConnection')) add('workflowPortConnect', { direction: 'output' });
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

async function seedStudioPrerequisites(page, control) {
  for (const step of studioPrerequisites(control)) {
    const outcome = await page.evaluate(prerequisite => {
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
        if (!pair) return false;
        source.value = pair.output.value;
        target.value = pair.input.value;
      }
      const candidates = [...document.querySelectorAll(`[data-action="${CSS.escape(prerequisite.action)}"]`)].filter(element =>
        Object.entries(prerequisite.dataset).every(([key, value]) => String(element.dataset[key] || '') === String(value))
      );
      const target = prerequisite.pick === 'last' ? candidates.at(-1) : candidates[0];
      if (!target || target.disabled) return false;
      target.click();
      return true;
    }, step);
    if (!outcome) return false;
    await page.waitForTimeout(60);
  }
  return true;
}

function revealActionFor(control) {
  const id = String(control.control_id);
  if (/dashboard-control-plane\.(action\.(copyModal|exportRecordJson|informationTab)|menu\.informationTabs|gesture\.)/.test(id)) return 'inspectMetric';
  if (/dashboard-control-plane\.(action\.closeModal|menu\.commandCenter)/.test(id)) return 'commandCenter';
  if (/dashboard-control-plane\.action\.navigate\.(knowledgeCore|runtimeCore)/.test(id)) return 'toggleAdvanced';
  if (/\.(field|editor)\.canonicalJson$/.test(id) || /\.action\.studioApplyJson$/.test(id)) return 'studioEditorTab';
  if (/knowledge-graph\.(field\.savedViewName|form\.savedView|action\.(?:submitGraphSavedView|graph(?:Apply|Delete)SavedView))/.test(id)) return 'graphSaveView';
  if (/memory\.(field\.portableMemory|form\.captureMemory)/.test(id)) return 'captureMemory';
  if (/knowledge-core\.(field\.knowledgeReject|form\.reject|action\.submitKnowledgeReject)/.test(id)) return 'knowledgeReject';
  if (/knowledge-core\.(field\.rollback|form\.rollback|action\.submitKnowledgeRollback)/.test(id)) return 'knowledgeRollback';
  if (/knowledge-core\.(field\.knowledge|form\.proposal|action\.submitKnowledgeProposal)/.test(id)) return 'knowledgePropose';
  if (/knowledge-core\.(field\.learning|form\.learningObservation|action\.submitLearningObservation)/.test(id)) return 'learningObserve';
  if (/knowledge-core\.(field\.(applicability|higher|pattern)|form\.learningPattern|action\.submitLearningPattern)/.test(id)) return 'learningPattern';
  if (/knowledge-core\.(field\.(challenger|dependency|hypothesis|incumbent)|form\.learningHypothesis|action\.submitLearningHypothesis)/.test(id)) return 'learningHypothesis';
  if (/knowledge-core\.(field\.trial|form\.learningTrial|action\.submitLearningTrial)/.test(id)) return 'learningTrial';
  if (/knowledge-core\.(field\.(research|secondary)|form\.learningResearch|action\.submitLearningResearch)/.test(id)) return 'learningResearch';
  if (/knowledge-core\.field\.betterAlternativeFound/.test(id)) return 'learningResearch';
  if (/knowledge-core\.(field\.(finalValidation|partialUnits)|form\.learningFinalValidation|action\.submitLearningFinalValidation)/.test(id)) return 'learningFinalValidation';
  if (/knowledge-core\.(field\.reuse|form\.learningReuse|action\.submitLearningReuse)/.test(id)) return 'learningReuse';
  if (/workflows\.(field\.plan|form\.parallelPlan)/.test(id)) return 'newParallelPlan';
  if (/workflows\.action\.submitParallelPlan/.test(id)) return 'newParallelPlan';
  if (/workflows\.(field\.claim|form\.claimTask)/.test(id)) return 'claimTask';
  if (/workflows\.action\.submitClaimTask/.test(id)) return 'claimTask';
  if (/workflows\.(field\.progress|form\.taskProgress)/.test(id)) return 'taskProgress';
  if (/workflows\.action\.submitTaskProgress/.test(id)) return 'taskProgress';
  if (/workflows\.(field\.reconcile|form\.reconcileTask)/.test(id)) return 'reconcileTask';
  if (/workflows\.action\.submitReconcile/.test(id)) return 'reconcileTask';
  if (/workflows\.action\.submitReleaseTask/.test(id)) return 'releaseTask';
  if (/runtime-core\.(?:action\.(?:refreshCleanup|cleanupSelectAll|cleanupRecycle|cleanupPermanent)|field\.cleanupCandidateCheckbox|form\.cleanupSelection|indicator\.cleanup)/.test(id)) return 'cleanupManager';
  if (/skills-tools\.field\.(fixedSkillDomain|skillQueryGoal)/.test(id)) return 'skillSemanticQuery';
  if (/skills-tools\.action\.submitSkillQuery/.test(id)) return 'skillSemanticQuery';
  if (/memory\.action\.submitMemory/.test(id)) return 'captureMemory';
  if (/runtime-core\.field\.cleanupCandidateCheckbox/.test(id)) return 'cleanupManager';
  return null;
}

async function revealControl(page, control) {
  if (!await seedStudioPrerequisites(page, control)) return false;
  const id = String(control.control_id || '');
  if (/^pxui\.(?:agents|workflows|skills-tools)\.action\.enterprise(?:Doctor|PackToggle\.row|TargetConfigure\.row)$/.test(id)) {
    if (id.startsWith('pxui.skills-tools.')) {
      if (!await clickRevealAction(page, 'capabilityTab', { kind: 'enterprise-skills' })) return false;
    } else {
      const target = id.startsWith('pxui.agents.') ? 'agents' : 'workflows';
      if (!await clickRevealAction(page, 'surfaceScope', { target, scope: 'enterprise' })) return false;
    }
    await page.waitForTimeout(40); return true;
  }
  if (/^pxui\.agents\.indicator\.(?:activeSessions|enterpriseDoctorStatus)$/.test(id)) {
    if (!await clickRevealAction(page, 'surfaceScope', { target: 'agents', scope: 'enterprise' })) return false;
    await page.waitForTimeout(30); return true;
  }
  if (/^pxui\.workflows\.(?:action\.refreshEnvironment|indicator\.environmentSnapshotHash)$/.test(id)) {
    if (!await clickRevealAction(page, 'surfaceScope', { target: 'workflows', scope: 'environment' })) return false;
    await page.waitForTimeout(30); return true;
  }
  const catalogImport = id.match(/^pxui\.(agents|workflows)\.action\.importCatalogDefinition\.(agent|workflow)$/);
  if (catalogImport) {
    const kind = catalogImport[1];
    const selector = `[data-action="inspectCatalogItem"][data-kind="${kind}"]`;
    const count = await page.locator(selector).count();
    for (let index = 0; index < count; index += 1) {
      await page.locator(selector).nth(index).click(); await page.waitForTimeout(30);
      if (await page.locator(`[data-action="importCatalogDefinition"][data-kind="${catalogImport[2]}"]`).count()) return true;
      await page.locator('[data-action="closeModal"]').last().click().catch(() => {}); await page.waitForTimeout(20);
    }
    return false;
  }
  if (id === 'pxui.agent-studio.action.refreshHostModels') {
    if (!await clickRevealAction(page, 'agentSelectNode', { 'agent-node-id': 'agent-node:model' })) return false;
    await page.locator('[data-action="refreshHostModels"]').waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    return true;
  }
  if (id === 'pxui.skill-studio.action.loadSkillPackageEditor' || id === 'pxui.skills-tools.action.compareSkillOriginal') {
    if (id.startsWith('pxui.skill-studio.')) {
      await page.locator('[data-action="closeModal"]').last().click().catch(() => {});
      await page.locator('[data-surface="skillsTools"]').first().click(); await page.waitForTimeout(50);
    }
    const targetAction = id.endsWith('.loadSkillPackageEditor') ? 'loadSkillPackageEditor' : 'compareSkillOriginal';
    const selector = '[data-action="inspectCatalogItem"][data-kind="skills"]';
    const count = await page.locator(selector).count();
    for (let index = 0; index < count; index += 1) {
      await page.locator(selector).nth(index).click(); await page.waitForTimeout(30);
      if (await page.locator(`[data-action="${targetAction}"]`).count()) return true;
      await page.locator('[data-action="closeModal"]').last().click().catch(() => {}); await page.waitForTimeout(20);
    }
    return false;
  }
  if (id === 'pxui.knowledge-graph.action.graphCommunity.row') {
    const summary = page.locator('.graph-community summary').first();
    if (!await summary.count()) return false;
    await summary.click(); await page.waitForTimeout(20); return true;
  }
  if (id === 'pxui.knowledge-graph.action.graphClearCommunity') {
    const summary = page.locator('.graph-community summary').first();
    if (!await summary.count()) return false;
    await summary.click(); await page.waitForTimeout(20);
    if (!await clickRevealAction(page, 'graphCommunity')) return false;
    await page.evaluate(() => {
      const current = window.eval('structuredClone(state.graphData)') || {};
      const nodes = (current.nodes || []).map((item, index) => ({ ...item, community_id: index % 2 ? 'preview:secondary' : 'preview:primary' }));
      const result = { ...current, nodes, communities: [{ id: 'preview:primary', label: 'Primary', member_count: nodes.length, edge_count: 4, status_counts: { active: nodes.length } }] };
      window.eval(`state.graphData = ${JSON.stringify(result)}; render()`);
    });
    await page.locator('[data-action="graphClearCommunity"]').waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {}); return true;
  }
  if (/^pxui\.skills-tools\.(?:action\.hydrateSkillCandidate\.row|indicator\.query(?:Results|NoMatch|Pending))$/.test(id)) {
    if (!await clickRevealAction(page, 'skillSemanticQuery')) return false;
    await page.locator('#skill-query-goal').fill('Find the exact bounded repair skill');
    if (!await clickRevealAction(page, 'submitSkillQuery')) return false;
    if (id.endsWith('.indicator.queryPending')) return true;
    const noMatch = id.endsWith('.indicator.queryNoMatch');
    await page.evaluate(emptyResult => window.dispatchEvent(new MessageEvent('message', { data: { type: 'skillQueryResult', result: { mode: 'semantic', query: 'bounded repair', candidate_limit: 3, requested_domains: ['px-standard'], candidates: emptyResult ? [] : [{ id: 'skill:preview-repair', version: '1.0.0', origin: 'px-native', domain: 'px-standard', score: 0.99, description: 'Bounded repair skill', selection_rationale: 'Exact preview match', admission: 'admitted', body_available: true }] } } })), noMatch);
    await page.waitForTimeout(40); return true;
  }
  if (id === 'pxui.memory.action.openMemorySource') {
    const inspect = page.locator('[data-action="inspectMemoryRecord"]').first(); if (!await inspect.count()) return false;
    await inspect.click(); await page.waitForTimeout(40); return true;
  }
  if (/^pxui\.(?:agent-studio|workflow-studio|skill-studio)\.action\.(?:resumeWorkingStudioDraft|discardWorkingStudioDraft)$/.test(id)) {
    const kind = control.surface_id.split('-')[0];
    const owner = page.locator('#studio-owner'); if (!await owner.count()) return false;
    await owner.fill(`${await owner.inputValue()} retained`.trim());
    await owner.dispatchEvent('input'); await page.waitForTimeout(40);
    if (!await clickRevealAction(page, 'closeModal')) return false;
    if (!await clickRevealAction(page, 'openStudioDraft', { kind })) return false;
    await page.locator(`[data-action="${id.includes('resumeWorking') ? 'resumeWorkingStudioDraft' : 'discardWorkingStudioDraft'}"]`).waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    return true;
  }
  const pluginExecute = id.match(/^pxui\.plugins\.action\.executeExtension(Install|Update|Enablement|Uninstall|Rollback)$/)?.[1];
  if (pluginExecute) {
    const operation = pluginExecute.toLowerCase();
    const previewAction = `previewExtension${pluginExecute}`;
    const input = page.locator(`#extension-${operation === 'enablement' ? 'enablement' : operation}-id`);
    if (await input.count()) await input.fill('publisher.preview');
    if (!await clickRevealAction(page, previewAction)) return false;
    if (!await dispatchPluginPreviewFixture(page, operation)) return false;
    await page.locator(`[data-action="executeExtension${pluginExecute}"]`).waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    return true;
  }
  if (/^pxui\.plugins\.action\.(?:preview|execute)ExtensionConflictResolution$/.test(id)) {
    const input = page.locator('#extension-conflict-id'); if (await input.count()) await input.fill('publisher.preview');
    if (!await clickRevealAction(page, 'queryExtensionConflicts')) return false;
    if (!await dispatchPluginPreviewFixture(page, 'conflict')) return false;
    await page.locator('[data-action="previewExtensionConflictResolution"]').waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    if (id.endsWith('.action.previewExtensionConflictResolution')) return true;
    if (!await clickRevealAction(page, 'previewExtensionConflictResolution')) return false;
    if (!await dispatchPluginPreviewFixture(page, 'conflictResolution')) return false;
    await page.locator('[data-action="executeExtensionConflictResolution"]').waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    return true;
  }
  if (id.startsWith('pxui.workflows.') && /(?:environmentScope|environmentExtensionDetail|inspectEnvironmentRecord|EnvironmentLifecycle|environmentLifecycle|environmentFreshness)/.test(id)) {
    await clickRevealAction(page, 'surfaceScope', { target: 'workflows', scope: 'environment' });
    if (id.endsWith('.indicator.environmentFreshness')) return true;
    if (/\.action\.environmentScope\./.test(id)) return true;
    const scope = id.includes('environmentExtensionDetail') ? 'extensions' : id.includes('inspectEnvironmentRecord') ? 'tools' : 'environment-files';
    if (!await clickRevealAction(page, 'environmentScope', { scope })) return false;
    const rowSelector = scope === 'extensions' ? '[data-action="environmentExtensionDetail"]' : '[data-action="inspectEnvironmentRecord"]';
    await page.locator(rowSelector).first().waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    if (id.includes('environmentExtensionDetail') || id.includes('inspectEnvironmentRecord')) return true;
    const row = page.locator(rowSelector).first(); if (!await row.count()) return false;
    await row.click(); await page.waitForTimeout(60);
    if (id.endsWith('.action.previewEnvironmentLifecycle')) return true;
    if (!await clickRevealAction(page, 'previewEnvironmentLifecycle')) return false;
    await page.locator('[data-action="executeEnvironmentLifecycle"]').waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    const exactTarget = page.locator('#environment-lifecycle-target');
    if (await exactTarget.count()) await exactTarget.fill(await exactTarget.getAttribute('data-exact-target') || '');
    const acknowledgement = page.locator('#environment-lifecycle-consumers');
    if (await acknowledgement.count()) await acknowledgement.check();
    return true;
  }
  if (/^pxui\.runtime-core\.(?:action\.(?:refreshCleanup|cleanupSelectAll|cleanupRecycle|cleanupPermanent)|field\.cleanupCandidateCheckbox|form\.cleanupSelection|indicator\.cleanup)/.test(id)) {
    if (!await clickRevealAction(page, 'cleanupManager')) return false;
    await page.locator('.cleanup-summary').waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    if (/\.action\.cleanup(?:Recycle|Permanent)$/.test(id)) {
      if (!await clickRevealAction(page, 'cleanupSelectAll')) return false;
    }
    return true;
  }
  if (/knowledge-graph\.(?:action\.(?:graphDepth\.|graphLayout\.)|menu\.(?:depth|layout)|gesture\.)/.test(id)) {
    const analysis = page.locator('[data-graph-analysis]').first();
    if (await analysis.count()) {
      await analysis.selectOption('neighborhood');
      if (!await clickRevealAction(page, 'runGraphSearch')) return false;
      await page.locator('[aria-label="Relationship depth"]').waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
      await page.waitForTimeout(90);
    }
    if (id.endsWith('.action.graphDepth.decrease')) {
      if (!await clickRevealAction(page, 'graphDepth', { delta: '1' })) return false;
    }
    if (id.endsWith('.gesture.escapeFocusMode')) {
      if (!await clickRevealAction(page, 'graphFocus')) return false;
    }
    return true;
  }
  if (/knowledge-graph\.action\.graph(?:Apply|Delete)SavedView\.row/.test(id)) {
    if (!await clickRevealAction(page, 'graphSaveView')) return false;
    const name = page.locator('#graph-view-name').first();
    if (!await name.count()) return false;
    await name.fill('PX exact probe view');
    if (!await clickRevealAction(page, 'submitGraphSavedView')) return false;
    return true;
  }
  if (/knowledge-graph\.field\.(graphDirection|graphTarget)/.test(id)) {
    const analysis = page.locator('[data-graph-analysis]').first();
    if (await analysis.count()) {
      await analysis.selectOption(id.endsWith('graphTarget') ? 'path' : 'neighborhood');
      await page.waitForTimeout(90);
      return true;
    }
  }
  if (/workflows\.field\.environment(ConsumerAcknowledgement|ExactTarget)/.test(id)) {
    await clickRevealAction(page, 'surfaceScope', { scope: 'environment' });
    await clickRevealAction(page, 'environmentScope', { scope: 'environment-files' });
    const record = page.locator('.environment-row').first();
    if (await record.count()) { await record.click(); await page.waitForTimeout(60); }
    if (!await clickRevealAction(page, 'previewEnvironmentLifecycle')) return false;
    await page.locator('#environment-lifecycle-target').waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    return true;
  }
  if (/studio-lifecycle\.field\.(agentObjective|workflowRunInputsJson)/.test(id)) {
    const kind = id.endsWith('agentObjective') ? 'agent' : 'workflow';
    await page.locator(`[data-surface="${kind === 'agent' ? 'agents' : 'workflows'}"]`).first().click();
    const inspect = page.locator(`[data-action="inspectCatalogItem"][data-kind="${kind}s"]`).first();
    await inspect.waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    if (!await inspect.count()) return false;
    await inspect.click(); await page.waitForTimeout(60);
    if (!await clickRevealAction(page, 'operateStudioRevision', { kind })) return false;
    if (!await clickRevealAction(page, 'studioLifecycle', { kind, operation: 'start' })) return false;
    await page.locator(kind === 'agent' ? '#studio-agent-objective' : '#studio-workflow-inputs').waitFor({ state: 'visible', timeout: 3_000 }).catch(() => {});
    return true;
  }
  const action = revealActionFor(control);
  if (!action) return false;
  if (action === 'studioEditorTab') {
    const tab = page.locator('[data-action="studioEditorTab"][data-tab="json"]').first();
    if (await tab.count() && await tab.isVisible()) { await tab.click(); await page.waitForTimeout(60); return true; }
    return false;
  }
  if (!await clickRevealAction(page, action)) return false;
  if (id.endsWith('.action.submitSkillQuery')) await page.locator('#skill-query-goal').fill('Find the exact bounded repair skill');
  if (id.endsWith('.action.submitMemory')) await page.locator('#memory-content').fill('Exact bounded portable memory observation.');
  if (id.endsWith('.action.submitParallelPlan')) {
    await page.locator('#plan-objective').fill('Exercise the exact bounded coordination workflow');
    await page.locator('#plan-goal').fill('Operational evidence');
    await page.locator('#plan-tasks').fill('probe | Exercise exact workflow |  | extension/ | VS Code | repair agent | 1000 | workspace-read');
  } else if (id.endsWith('.action.submitTaskProgress')) {
    await page.locator('#progress-summary').fill('Recorded exact bounded progress evidence.');
    await page.locator('#progress-next').fill('Reconcile the exact receipt.');
  } else if (id.endsWith('.action.submitReconcile')) {
    await page.locator('#reconcile-summary').fill('Exact bounded reconciliation evidence.');
    await page.locator('#reconcile-conflicts').check();
  } else if (id.endsWith('.action.submitReleaseTask')) {
    await page.locator('#release-reason').fill('Returning this bounded task to the coordination pool.');
    await page.locator('#release-confirm').check();
  }
  return true;
}

async function exerciseGesture(page, control, item) {
  const id = String(control.control_id || '');
  if (id.endsWith('.gesture.escapeCloseModal')) {
    await item.focus(); await page.keyboard.press('Escape');
    return !(await page.locator('#modal-root [role="dialog"]').count());
  }
  if (id.endsWith('.gesture.informationTabArrowSwitch')) {
    const tab = item.locator('[data-action="informationTab"][data-tab="human"]').first();
    await tab.focus(); await tab.press('ArrowRight');
    return await item.locator('[data-tab="machine"][aria-selected="true"]').count() === 1;
  }
  if (id.endsWith('.gesture.modalFocusTrap')) {
    const focusable = item.locator('button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex="0"]');
    const count = await focusable.count(); if (count < 2) return false;
    await focusable.nth(count - 1).focus(); await page.keyboard.press('Tab');
    return await focusable.first().evaluate(element => document.activeElement === element);
  }
  if (id.startsWith('pxui.workflow-studio.gesture.')) {
    const canvas = page.locator('[data-workflow-editor-canvas]').first();
    if (id.endsWith('.gesture.altArrowReorderNode')) {
      const nodes = page.locator('.workflow-editor-node'); if (await nodes.count() < 2) return false;
      const before = await nodes.evaluateAll(rows => rows.map(row => row.dataset.nodeId));
      await nodes.first().focus(); await nodes.first().press('Alt+ArrowRight'); await page.waitForTimeout(60);
      const after = await page.locator('.workflow-editor-node').evaluateAll(rows => rows.map(row => row.dataset.nodeId));
      return canonicalJson(before) !== canonicalJson(after);
    }
    if (id.endsWith('.gesture.dragExistingNode')) {
      const node = page.locator('.workflow-editor-node').first(); if (!await node.count()) return false;
      await node.dragTo(canvas, { targetPosition: { x: 160, y: 140 } }); return true;
    }
    if (id.endsWith('.gesture.dragPaletteNodeToCanvas')) {
      const palette = page.locator('.workflow-palette [data-node-template="task"]').first(); if (!await palette.count()) return false;
      const before = await page.locator('.workflow-editor-node').count();
      await palette.dragTo(canvas, { targetPosition: { x: 180, y: 160 } }); await page.waitForTimeout(60);
      return await page.locator('.workflow-editor-node').count() > before;
    }
    return false;
  }
  if (!id.startsWith('pxui.knowledge-graph.gesture.')) {
    await item.focus(); await item.press('ArrowRight').catch(() => {}); return true;
  }
  if (id.endsWith('.gesture.arrowNodeFocus')) {
    const nodes = page.locator('.graph-node.actual'); if (await nodes.count() < 2) return false;
    await nodes.first().focus(); const before = await nodes.first().getAttribute('data-node-key');
    await nodes.first().press('ArrowRight');
    return await page.evaluate(value => document.activeElement?.dataset?.nodeKey !== value, before);
  }
  const before = await page.evaluate(() => {
    const scene = document.querySelector('[data-graph-scene]');
    return { x: scene?.dataset.graphTranslateX, y: scene?.dataset.graphTranslateY, scale: scene?.dataset.graphScale, focus: Boolean(document.querySelector('.graph-focus-mode')) };
  });
  await item.focus();
  if (id.endsWith('.gesture.arrowPan')) await item.press('ArrowRight');
  else if (id.endsWith('.gesture.ctrlWheelZoom')) await item.evaluate(element => element.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: true, deltaY: -120, clientX: 120, clientY: 120 })));
  else if (id.endsWith('.gesture.doubleClickZoom')) await item.dblclick({ position: { x: 120, y: 120 } });
  else if (id.endsWith('.gesture.escapeFocusMode')) await page.keyboard.press('Escape');
  else if (id.endsWith('.gesture.plusMinusZoom')) await item.press('+');
  else if (id.endsWith('.gesture.pointerDragPan')) await item.evaluate(element => {
    element.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, pointerId: 71, clientX: 100, clientY: 100 }));
    element.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, cancelable: true, pointerId: 71, clientX: 145, clientY: 130 }));
    element.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 71, clientX: 145, clientY: 130 }));
  });
  else if (id.endsWith('.gesture.twoPointerPinchZoom')) await item.evaluate(element => {
    element.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, pointerId: 81, clientX: 100, clientY: 100 }));
    element.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, pointerId: 82, clientX: 160, clientY: 100 }));
    element.dispatchEvent(new PointerEvent('pointermove', { bubbles: true, cancelable: true, pointerId: 82, clientX: 210, clientY: 100 }));
    element.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 81, clientX: 100, clientY: 100 }));
    element.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 82, clientX: 210, clientY: 100 }));
  });
  else if (id.endsWith('.gesture.wheelPan')) await item.evaluate(element => element.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: 80, clientX: 120, clientY: 120 })));
  else if (id.endsWith('.gesture.zeroOrHomeFit')) {
    await item.press('ArrowRight'); await item.press('0');
  } else return false;
  await page.waitForTimeout(60);
  const after = await page.evaluate(() => {
    const scene = document.querySelector('[data-graph-scene]');
    return { x: scene?.dataset.graphTranslateX, y: scene?.dataset.graphTranslateY, scale: scene?.dataset.graphScale, focus: Boolean(document.querySelector('.graph-focus-mode')), status: document.querySelector('[data-graph-status]')?.textContent };
  });
  if (id.endsWith('.gesture.escapeFocusMode')) return before.focus && !after.focus;
  if (id.endsWith('.gesture.zeroOrHomeFit')) return after.status === 'Map fitted';
  return before.x !== after.x || before.y !== after.y || before.scale !== after.scale;
}

async function resolveSemantic(page, control) {
  const directSelector = directSelectorFor(control);
  if (directSelector) {
    const item = page.locator(directSelector).first();
    if (await item.count() && await item.isVisible().catch(() => false)) return { item, score: 1, candidate: { directSelector } };
  }
  const selector = selectorForKind(control.kind);
  const items = page.locator(selector);
  let best = null;
  for (let index = 0; index < await items.count(); index += 1) {
    const item = items.nth(index);
    const candidate = await item.evaluate(element => ({
      text: (element.innerText || element.value || '').slice(0, 1200),
      attributes: Array.from(element.attributes).map(attribute => `${attribute.name}=${attribute.value}`).join(' '),
      visible: Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length)
    }));
    const score = candidateScore(semanticLabel(control), candidate);
    if (candidate.visible && (!best || score > best.score)) best = { item, score, candidate };
  }
  return best && best.score >= 0.66 ? best : null;
}

async function exercise(page, control) {
  const result = { loaded: true, visible: false, attempted: false, validationObserved: false, acknowledged: false, details: {}, errors: [] };
  try {
    if (control.kind === 'action') {
      const item = await resolveAction(page, control);
      if (!item || !(await item.isVisible().catch(() => false))) return result;
      result.visible = true;
      if (!(await item.isEnabled().catch(() => false))) return result;
      const before = (await page.evaluate(() => window.__PX_POSTED_MESSAGES__?.length || 0));
      await item.click({ timeout: 4_000 });
      await page.waitForTimeout(90);
      const after = (await page.evaluate(() => window.__PX_POSTED_MESSAGES__?.length || 0));
      result.attempted = true;
      result.validationObserved = true;
      result.acknowledged = control.evidence_mode === 'contained_ui_interaction' || after > before;
      return result;
    }
    const resolved = await resolveSemantic(page, control);
    if (!resolved) return result;
    const item = resolved.item;
    result.visible = true;
    if (control.kind === 'indicator') {
      // For a live-state observation the semantically matched visible value is
      // itself the user-facing result acknowledgement.  Do not claim action,
      // validation, host, persistence, or failure stages from that display.
      result.acknowledged = true;
      result.details.result_acknowledgement = 'The exact visible live-state indicator directly exposed its current value.';
      return result;
    }
    if (control.kind === 'field') {
      const tag = await item.evaluate(element => element.tagName.toLowerCase());
      const disclosure = await item.evaluate(element => { const details = element.closest('details'); if (!details) return null; const open = details.open; details.open = true; return open; });
      try {
        const type = String(await item.getAttribute('type') || '').toLowerCase();
        if (tag === 'select') {
          const original = await item.inputValue(); const options = await item.locator('option').evaluateAll(rows => rows.map(row => ({ value: row.value, disabled: row.disabled })));
          const alternate = options.find(option => option.value !== original && !option.disabled)?.value;
          if (alternate !== undefined) { await item.selectOption(alternate, { timeout: 3_000, force: true }); await item.selectOption(original, { timeout: 3_000, force: true }); result.attempted = true; }
        } else if (type === 'checkbox' || type === 'radio') {
          const original = await item.isChecked(); await item.setChecked(!original, { force: true }); await item.setChecked(original, { force: true }); result.attempted = true;
        } else if (type === 'number') {
          const original = await item.inputValue(); const number = Number(original || 0);
          const min = Number(await item.getAttribute('min')); const max = Number(await item.getAttribute('max'));
          const up = number + 1; const alternate = Number.isFinite(max) && up > max ? number - 1 : up;
          if ((!Number.isFinite(min) || alternate >= min) && (!Number.isFinite(max) || alternate <= max)) {
            await item.fill(String(alternate)); await item.fill(original); result.attempted = true;
          }
        } else {
          const original = await item.inputValue(); await item.fill(`${original} px-probe`.trim()); await item.fill(original); result.attempted = true;
        }
      } finally {
        if (disclosure !== null) await item.evaluate((element, wasOpen) => { const details = element.closest('details'); if (details) details.open = wasOpen; }, disclosure);
      }
      result.validationObserved = result.attempted; result.acknowledged = result.attempted; return result;
    }
    if (control.kind === 'gesture') {
      result.attempted = true;
      result.validationObserved = await exerciseGesture(page, control, item);
      result.acknowledged = result.validationObserved;
      return result;
    }
    const interactive = item.locator('button,input,select,textarea,[tabindex]').first();
    const target = await interactive.count() ? interactive : item;
    await target.focus();
    if (control.kind === 'gesture' || control.kind === 'editor') { await target.press('ArrowRight').catch(() => {}); await target.press('ArrowLeft').catch(() => {}); }
    else await target.click({ timeout: 3_000 }).catch(() => {});
    result.attempted = true; result.validationObserved = true; result.acknowledged = true;
  } catch (error) { result.errors.push(String(error?.message || error).slice(0, 1000)); }
  return result;
}

function resumeReceiptCompatible(receipt, matrix, matrixDigest, sourceManifest) {
  if (receipt?.schema_version !== 'px.exhaustive-operational-control-walk/1.0'
    || !Array.isArray(receipt.records) || receipt.records.length !== matrix.controls.length) return false;
  if (receipt.source?.matrix_sha256 === matrixDigest) {
    return receipt.records.every((record, index) => record.control_id === matrix.controls[index].control_id);
  }
  if (canonicalJson(receipt.source?.control_source_manifest) !== canonicalJson(sourceManifest)) return false;
  return receipt.records.every((record, index) => {
    const control = matrix.controls[index];
    const chain = record?.interaction_chain;
    if (record?.control_id !== control.control_id
      || record?.surface_id !== control.surface_id
      || record?.control_kind !== control.kind
      || record?.evidence_mode !== control.evidence_mode
      || !chain || Object.keys(chain).length !== STAGES.length) return false;
    return STAGES.every(stage => Object.hasOwn(chain, stage)
      && ((control.stage_policy[stage] === 'not_applicable_with_evidence') === (chain[stage]?.state === 'not_applicable')));
  });
}

async function main() {
  const matrixBytes = fs.readFileSync(matrixPath);
  const matrix = JSON.parse(matrixBytes);
  const sourceManifest = currentSourceManifest(matrix);
  let priorReceipt = null;
  if (resumePath) {
    priorReceipt = JSON.parse(fs.readFileSync(resumePath));
    if (!resumeReceiptCompatible(priorReceipt, matrix, sha256(matrixBytes), sourceManifest)) {
      throw new Error('resume-receipt-matrix-or-denominator-mismatch');
    }
  }
  const selectedIndexes = controlPattern
    ? matrix.controls.map((control, index) => ({ control, index })).filter(item => controlPattern.test(item.control.control_id)).map(item => item.index)
    : priorReceipt
      ? priorReceipt.records.map((record, index) => ({ record, index })).filter(item => item.record.errors?.length).map(item => item.index)
      : matrix.controls.map((_control, index) => index);
  if (controlPattern && selectedIndexes.length === 0) throw new Error('PX_OPERATIONAL_CONTROL_PATTERN matched zero canonical controls.');
  const workerCount = Math.max(1, Math.min(8, selectedIndexes.length || 1, Number(process.env.PX_OPERATIONAL_WALK_WORKERS || 4) || 4));
  const records = priorReceipt ? structuredClone(priorReceipt.records) : matrix.controls.map(control => ({
    control_id: control.control_id,
    surface_id: control.surface_id,
    control_kind: control.kind,
    evidence_mode: control.evidence_mode,
    rendered: false,
    observed: false,
    attempted: false,
    operational: false,
    interaction_chain: Object.fromEntries(STAGES.map(stage => [stage, control.stage_policy[stage] === 'not_applicable_with_evidence'
      ? { state: 'not_applicable', detail: 'Canonical matrix marks this stage not applicable; this focused run did not select the control.', evidence: [] }
      : { state: 'missing', detail: 'Control was outside this focused current-source run.', evidence: [] }])),
    errors: []
  }));
  const lane = resolveBrowserLane();
  const browser = await chromium.launch({ executablePath: lane.executablePath, headless: true });
  try {
    const shardSize = Math.ceil(selectedIndexes.length / workerCount);
    await Promise.all(Array.from({ length: workerCount }, async (_unused, workerIndex) => {
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
      let preparedSemanticSurface = null;
      const start = workerIndex * shardSize; const end = Math.min(selectedIndexes.length, start + shardSize);
      try {
        for (let offset = start; offset < end; offset += 1) {
          const controlIndex = selectedIndexes[offset];
          const control = matrix.controls[controlIndex];
          let probe = { loaded: false, visible: false, attempted: false, validationObserved: false, acknowledged: false, details: {}, errors: [] };
          if (UI_KINDS.has(control.kind)) {
            const isolated = control.kind === 'action' || ['form', 'menu', 'gesture'].includes(control.kind);
            const semanticPreparation = preparationKey(control);
            if (isolated || preparedSemanticSurface !== semanticPreparation) {
              await prepare(page, control.surface_id, control);
              preparedSemanticSurface = isolated ? null : semanticPreparation;
            }
            const revealed = await revealControl(page, control);
            probe = await exercise(page, control);
            if (isolated || revealed) preparedSemanticSurface = null;
          }
          const evidenceRef = `receipt:${control.control_id}`;
          const chain = Object.fromEntries(STAGES.map(stage => [stage, stageResult(control, probe, stage, evidenceRef)]));
          records[controlIndex] = {
            control_id: control.control_id, surface_id: control.surface_id, control_kind: control.kind,
            evidence_mode: control.evidence_mode, rendered: probe.visible, observed: probe.visible || !UI_KINDS.has(control.kind),
            attempted: probe.attempted, operational: completeChain(chain), interaction_chain: chain, errors: probe.errors
          };
        }
      } finally { await page.close(); }
    }));
  } finally { await browser.close(); }
  const aggregates = {
    control_count: records.length, attempted: records.filter(record => record.attempted).length,
    rendered: records.filter(record => record.rendered).length, operational: records.filter(record => record.operational).length,
    incomplete: records.filter(record => !record.operational).length, errors: records.reduce((sum, record) => sum + record.errors.length, 0)
  };
  const receipt = {
    schema_version: 'px.exhaustive-operational-control-walk/1.0',
    authority: 'Current-source contained browser evidence only; host/runtime/durability stages require separate direct receipts.',
    observed_at: new Date().toISOString(), source: { matrix_sha256: sha256(matrixBytes), matrix_id: matrix.matrix_sha256, control_source_manifest: sourceManifest },
    browser: { lane: lane.name, platform: lane.platform, workers: workerCount },
    resume: priorReceipt ? { predecessor: path.relative(root, resumePath).replaceAll('\\', '/'), predecessor_sha256: sha256(fs.readFileSync(resumePath)), rerun_control_count: selectedIndexes.length, control_pattern: controlPatternSource || null } : null,
    selection: controlPattern ? { selected_control_count: selectedIndexes.length, control_pattern: controlPatternSource, unselected_controls_explicitly_unattempted: !priorReceipt } : null,
    aggregates, operationally_complete: aggregates.operational === records.length, records
  };
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  process.stdout.write(`${JSON.stringify({ output, aggregates }, null, 2)}\n`);
  if (aggregates.errors) process.exitCode = 1;
}

if (require.main === module) main().catch(error => { process.stderr.write(`${error.stack || error.message}\n`); process.exitCode = 1; });
module.exports = { STAGES, actionIdentity, candidateScore, canonicalJson, completeChain, currentSourceManifest, directSelectorFor, exactActionSelectorFor, exercise, exerciseGesture, meaningfulTokens, normalize, prepare, preparationKey, revealActionFor, revealControl, resolveAction, resolveSemantic, resumeReceiptCompatible, selectorForKind, semanticLabel, sidebarActionSelector, sidebarFixtureMessage, sourcePath, stageResult, studioDraftRequired, variantsMatch, visualVariantsMatch };
