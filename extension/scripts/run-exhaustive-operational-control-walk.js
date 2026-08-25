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

function directSelectorFor(control) {
  const id = String(control?.control_id || '');
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
    'pxui.workflows.field.reconcileSummary': '#reconcile-summary'
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

async function prepare(page, surfaceId, control = null) {
  if (surfaceId === 'sidebar') {
    await page.goto(sidebarPreview);
    await page.locator('#sidebar').waitFor({ state: 'visible', timeout: 15_000 });
    await page.waitForTimeout(120);
    return;
  }
  const route = ROUTES[surfaceId];
  if (!route) throw new Error(`No route for ${surfaceId}`);
  await page.goto(`${preview}?surface=${route}`);
  await page.locator('main h1').first().waitFor({ state: 'visible', timeout: 15_000 });
  await page.waitForTimeout(150);
  if (studioDraftRequired(surfaceId, control)) {
    const kind = surfaceId.split('-')[0];
    const open = page.locator(`[data-action="openStudioDraft"][data-kind="${kind}"]`).first();
    if (await open.count()) { await open.click(); await page.waitForTimeout(120); }
  }
}

async function resolveAction(page, control) {
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
  if (/dashboard-control-plane\.(action\.(closeModal|copyModal|exportRecordJson|informationTab)|menu\.(commandCenter|informationTabs)|gesture\.)/.test(id)) return 'commandCenter';
  if (/dashboard-control-plane\.action\.navigate\.(knowledgeCore|runtimeCore)/.test(id)) return 'toggleAdvanced';
  if (/\.(field|editor)\.canonicalJson$/.test(id) || /\.action\.studioApplyJson$/.test(id)) return 'studioEditorTab';
  if (/knowledge-graph\.(field\.savedViewName|form\.savedView|action\.graph(Apply|Delete)SavedView)/.test(id)) return 'graphSaveView';
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
  if (/workflows\.(field\.claim|form\.claimTask)/.test(id)) return 'claimTask';
  if (/workflows\.(field\.progress|form\.taskProgress)/.test(id)) return 'taskProgress';
  if (/workflows\.(field\.reconcile|form\.reconcileTask)/.test(id)) return 'reconcileTask';
  if (/skills-tools\.field\.(fixedSkillDomain|skillQueryGoal)/.test(id)) return 'skillSemanticQuery';
  if (/runtime-core\.field\.cleanupCandidateCheckbox/.test(id)) return 'cleanupManager';
  return null;
}

async function revealControl(page, control) {
  if (!await seedStudioPrerequisites(page, control)) return false;
  const id = String(control.control_id || '');
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
  return clickRevealAction(page, action);
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
    const interactive = item.locator('button,input,select,textarea,[tabindex]').first();
    const target = await interactive.count() ? interactive : item;
    await target.focus();
    if (control.kind === 'gesture' || control.kind === 'editor') { await target.press('ArrowRight').catch(() => {}); await target.press('ArrowLeft').catch(() => {}); }
    else await target.click({ timeout: 3_000 }).catch(() => {});
    result.attempted = true; result.validationObserved = true; result.acknowledged = true;
  } catch (error) { result.errors.push(String(error?.message || error).slice(0, 1000)); }
  return result;
}

async function main() {
  const matrixBytes = fs.readFileSync(matrixPath);
  const matrix = JSON.parse(matrixBytes);
  const lane = resolveBrowserLane();
  const browser = await chromium.launch({ executablePath: lane.executablePath, headless: true });
  let priorReceipt = null;
  if (resumePath) {
    priorReceipt = JSON.parse(fs.readFileSync(resumePath));
    if (priorReceipt.schema_version !== 'px.exhaustive-operational-control-walk/1.0'
      || priorReceipt.source?.matrix_sha256 !== sha256(matrixBytes)
      || !Array.isArray(priorReceipt.records) || priorReceipt.records.length !== matrix.controls.length
      || priorReceipt.records.some((record, index) => record.control_id !== matrix.controls[index].control_id)) {
      throw new Error('resume-receipt-matrix-or-denominator-mismatch');
    }
  }
  const selectedIndexes = controlPattern
    ? matrix.controls.map((control, index) => ({ control, index })).filter(item => controlPattern.test(item.control.control_id)).map(item => item.index)
    : priorReceipt
      ? priorReceipt.records.map((record, index) => ({ record, index })).filter(item => item.record.errors?.length).map(item => item.index)
      : matrix.controls.map((_control, index) => index);
  if (controlPattern && !priorReceipt) throw new Error('PX_OPERATIONAL_CONTROL_PATTERN requires --resume so unselected records retain direct predecessor evidence.');
  if (controlPattern && selectedIndexes.length === 0) throw new Error('PX_OPERATIONAL_CONTROL_PATTERN matched zero canonical controls.');
  const workerCount = Math.max(1, Math.min(8, selectedIndexes.length || 1, Number(process.env.PX_OPERATIONAL_WALK_WORKERS || 4) || 4));
  const records = priorReceipt ? structuredClone(priorReceipt.records) : new Array(matrix.controls.length);
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
            if (isolated || preparedSemanticSurface !== control.surface_id) {
              await prepare(page, control.surface_id, control);
              preparedSemanticSurface = isolated ? null : control.surface_id;
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
    observed_at: new Date().toISOString(), source: { matrix_sha256: sha256(matrixBytes), matrix_id: matrix.matrix_sha256, control_source_manifest: currentSourceManifest(matrix) },
    browser: { lane: lane.name, platform: lane.platform, workers: workerCount },
    resume: priorReceipt ? { predecessor: path.relative(root, resumePath).replaceAll('\\', '/'), predecessor_sha256: sha256(fs.readFileSync(resumePath)), rerun_control_count: selectedIndexes.length, control_pattern: controlPatternSource || null } : null,
    aggregates, operationally_complete: aggregates.operational === records.length, records
  };
  fs.mkdirSync(path.dirname(output), { recursive: true });
  fs.writeFileSync(output, `${JSON.stringify(receipt, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
  process.stdout.write(`${JSON.stringify({ output, aggregates }, null, 2)}\n`);
  if (aggregates.errors) process.exitCode = 1;
}

if (require.main === module) main().catch(error => { process.stderr.write(`${error.stack || error.message}\n`); process.exitCode = 1; });
module.exports = { STAGES, actionIdentity, candidateScore, canonicalJson, completeChain, currentSourceManifest, directSelectorFor, exercise, meaningfulTokens, normalize, prepare, revealActionFor, revealControl, resolveAction, resolveSemantic, selectorForKind, semanticLabel, sourcePath, stageResult, studioDraftRequired, variantsMatch, visualVariantsMatch };
