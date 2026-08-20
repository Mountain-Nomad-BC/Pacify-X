'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { audit, contrastChecks, selectorsFromCss } = require('../scripts/audit-dashboard-css');

const root = path.resolve(__dirname, '..');
const moduleFiles = ['00-foundation.js', '10-state.js', '20-bridge.js', '25-health-state.js', '30-components.js', '40-surfaces.js', '42-core-surfaces.js', '43-catalog-surfaces.js', '44-operational-surfaces.js', '45-system-surfaces.js', '46-observability-surfaces.js', '47-advanced-surfaces.js', '49-studio-editors.js', '48-graph-surface.js'];
const styleFiles = ['00-layer-order.css', '01-tokens.css', '10-primitives.css', '20-layout.css', '30-components.css', '40-surfaces.css', '50-responsive.css', '60-accessibility.css'];

function loadScaffold(extra = {}) {
  const context = vm.createContext({ ...extra });
  context.globalThis = context;
  for (const file of moduleFiles) vm.runInContext(fs.readFileSync(path.join(root, 'media', 'dashboard', file), 'utf8'), context, { filename: file });
  return context.PXDashboard;
}

test('U01/U02 scaffold exposes bounded state, bridge, component, and surface modules', () => {
  const dashboard = loadScaffold();
  assert.deepEqual([...dashboard.list()], ['state', 'bridge', 'healthState', 'components', 'surfaces', 'coreSurfaces', 'catalogSurfaces', 'operationalSurfaces', 'systemSurfaces', 'observabilitySurfaces', 'advancedSurfaces', 'studioEditors', 'graphSurface']);
  assert.equal(Object.isFrozen(dashboard), true);
  assert.equal(dashboard.require('surfaces').visible.length, 16);
  assert.equal(dashboard.require('surfaces').advanced.length, 2);
  assert.equal(dashboard.require('surfaces').find('knowledgeGraph')[1], 'Knowledge Graph');
  assert.deepEqual([...dashboard.require('systemSurfaces').ids], ['diagnostics', 'assurance', 'settings']);
});

test('U02 core surfaces own Dashboard and Projects behind a bounded context', () => {
  const core = loadScaffold().require('coreSurfaces');
  assert.deepEqual([...core.ids], ['dashboard', 'projects']);
  assert.throws(() => core.render('dashboard', {}), /canonical snapshot context/);
  assert.throws(() => core.render('unknown', { state: { snapshot: {} } }), /Unknown core surface/);
});

test('U02 catalog surfaces own Agents and Skills & Tools behind a bounded context', () => {
  const catalog = loadScaffold().require('catalogSurfaces');
  assert.deepEqual([...catalog.ids], ['agents', 'skillsTools']);
  assert.throws(() => catalog.render('agents', {}), /canonical snapshot context/);
  assert.throws(() => catalog.render('unknown', { state: { snapshot: {} } }), /Unknown catalog surface/);
  const legacy = fs.readFileSync(path.join(root, 'media', 'dashboard', '90-controller.js'), 'utf8');
  assert.doesNotMatch(legacy, /function agents\s*\(/);
  assert.doesNotMatch(legacy, /function skillsTools\s*\(/);
});

test('U02 operational surfaces own Workflows, Studio surfaces, and Plugin Manager behind a bounded context', () => {
  const operational = loadScaffold().require('operationalSurfaces');
  assert.deepEqual([...operational.ids], ['workflows', 'agent-studio', 'workflow-studio', 'skill-studio', 'studio-lifecycle', 'plugins']);
  assert.throws(() => operational.render('workflows', {}), /canonical snapshot context/);
  assert.throws(() => operational.render('unknown', { state: { snapshot: {} } }), /Unknown operational surface/);
  const legacy = fs.readFileSync(path.join(root, 'media', 'dashboard', '90-controller.js'), 'utf8');
  assert.doesNotMatch(legacy, /function workflows\s*\(/);
  assert.doesNotMatch(legacy, /function plugins\s*\(/);
});

test('U02 observability surfaces own Memory and Activity behind a bounded context', () => {
  const observability = loadScaffold().require('observabilitySurfaces');
  assert.deepEqual([...observability.ids], ['memory', 'activity']);
  assert.throws(() => observability.render('memory', {}), /canonical snapshot context/);
  assert.throws(() => observability.render('unknown', { state: { snapshot: {} } }), /Unknown observability surface/);
  const legacy = fs.readFileSync(path.join(root, 'media', 'dashboard', '90-controller.js'), 'utf8');
  assert.doesNotMatch(legacy, /function memory\s*\(/);
  assert.doesNotMatch(legacy, /function activity\s*\(/);
});

test('U02 advanced surfaces own Knowledge Core and Runtime Core behind a bounded context', () => {
  const advanced = loadScaffold().require('advancedSurfaces');
  assert.deepEqual([...advanced.ids], ['knowledgeCore', 'runtimeCore']);
  assert.throws(() => advanced.render('knowledgeCore', {}), /canonical snapshot context/);
  assert.throws(() => advanced.render('unknown', { state: { snapshot: {} } }), /Unknown advanced surface/);
  const legacy = fs.readFileSync(path.join(root, 'media', 'dashboard', '90-controller.js'), 'utf8');
  assert.doesNotMatch(legacy, /function knowledgeCore\s*\(/);
  assert.doesNotMatch(legacy, /function runtimeCore\s*\(/);
});

test('U02 graph surface owns Knowledge Graph while interaction geometry stays with the single controller', () => {
  const graph = loadScaffold().require('graphSurface');
  assert.deepEqual([...graph.ids], ['knowledgeGraph']);
  assert.throws(() => graph.render({}), /canonical snapshot context/);
  const legacy = fs.readFileSync(path.join(root, 'media', 'dashboard', '90-controller.js'), 'utf8');
  assert.doesNotMatch(legacy, /function knowledgeGraph\s*\(/);
  assert.doesNotMatch(legacy, /function graphProjection\s*\(/);
  assert.match(legacy, /function graphPositions\s*\(/);
  assert.match(legacy, /graphSurface\.render\(/);
});

test('detached canonical memory never dispatches a backend query', () => {
  const controller = fs.readFileSync(path.join(root, 'media', 'dashboard', '90-controller.js'), 'utf8');
  assert.match(controller, /function canonicalMemoryReady\(\) \{\s*return state\.snapshot\?\.memory\?\.retrieval_ready === true;\s*\}/);
  assert.match(controller, /function requestMemory\([^)]*\) \{\s*if \(!canonicalMemoryReady\(\)\) \{\s*state\.memoryPending = false; state\.memoryRequestId = null; state\.memoryData = null;\s*return false;/);
  assert.match(controller, /state\.active === 'memory' && canonicalMemoryReady\(\)/);
  assert.match(controller, /message\.type === 'snapshot'.*!canonicalMemoryReady\(\).*state\.memoryRequestId = null;/);
});

test('W001/S001/G004 Studio editors normalize typed drafts and rank typo-tolerant graph results', () => {
  const editors = loadScaffold().require('studioEditors');
  const agent = editors.normalizeAgent({ agent_id: 'agent:builder-test', extension_note: 'preserved' });
  assert.equal(agent.builder_domain, 'px-standard');
  assert.equal(agent.extension_note, 'preserved');
  assert.equal(agent.grants[0].subject_id, agent.agent_id);
  assert.equal(agent.bindings[0].effect_grant_ids[0], agent.grants[0].grant_id);
  assert.equal(editors.validateAgent(agent).valid, true);
  assert.equal(editors.validStudioVersion('2.4.8-rc.1'), true);
  assert.equal(editors.validStudioVersion(' 2.4.8-RC.1 '), false);
  assert.equal(editors.validStudioVersion('01.0.0'), false);
  assert.equal(editors.validStudioVersion('2147483648.0.0'), false);
  assert.equal(editors.validStudioVersion(`1.0.0-${'a'.repeat(64)}`), true);
  assert.equal(editors.validStudioVersion(`1.0.0-${'a'.repeat(65)}`), false);
  for (const invalid of ['1.0.0--candidate', '1.0.0-candidate-', '1.0.0-a..b', '1.0.0-a.']) {
    assert.equal(editors.validStudioVersion(invalid), false);
  }
  assert.equal(editors.validCanonicalUtc('2026-08-16T12:34:56Z'), true);
  assert.equal(editors.validCanonicalUtc('2026-08-16T12:34:56.123Z'), true);
  for (const invalid of ['2026-02-31T00:00:00Z', '2026-08-16T12:34:56+00:00', '2026-08-16T12:34:56.12Z', '0000-01-01T00:00:00Z']) {
    assert.equal(editors.validCanonicalUtc(invalid), false);
  }
  const graph = editors.projectAgentBuilderGraph(agent);
  assert.equal(graph.schema_version, 'px.agent-builder-graph/1.0');
  assert.equal(graph.nodes.find(node => node.kind === 'behavior').config.instruction_sha256, crypto.createHash('sha256').update(agent.instructions).digest('hex'));
  assert.deepEqual(JSON.parse(JSON.stringify(graph.nodes.map(node => node.node_id))), ['agent-node:identity', 'agent-node:behavior', 'agent-node:model', 'agent-node:harness', 'agent-node:capabilities', 'agent-node:contracts', 'agent-node:authority', 'agent-node:tests', 'agent-node:candidate']);
  assert.equal(editors.validateAgentBuilderGraph(graph).valid, true);
  assert.equal(graph.edges.find(edge => edge.relation === 'owns').edge_id, 'agent-edge:b1e49b51df89541fc360');
  const graphWithTools = editors.projectAgentBuilderGraph({ ...agent, tool_binding_ids: [agent.capability_binding_ids[0]] });
  assert.equal(graphWithTools.nodes.some(node => node.node_id === 'agent-node:tools'), true);
  assert.equal(graphWithTools.edges.some(edge => edge.edge_id === 'agent-edge:4151bf6f83dfc2fdbfad'), true);
  const added = editors.editAgentBuilderNode(agent, graph, { type: 'add', kind: 'tools' });
  assert.equal(added.graph.nodes.some(node => node.node_id === 'agent-node:tools'), true);
  assert.deepEqual(JSON.parse(JSON.stringify(added.draft.tool_binding_ids)), []);
  const retyped = editors.editAgentBuilderNode(added.draft, added.graph, { type: 'retype', node_id: 'agent-node:tools', kind: 'memory' });
  assert.equal(retyped.graph.nodes.some(node => node.node_id === 'agent-node:tools'), false);
  assert.equal(retyped.graph.nodes.some(node => node.node_id === 'agent-node:memory'), true);
  const removed = editors.editAgentBuilderNode(retyped.draft, retyped.graph, { type: 'remove', node_id: 'agent-node:memory' });
  assert.equal(removed.graph.nodes.some(node => node.node_id === 'agent-node:memory'), false);
  assert.throws(() => editors.editAgentBuilderNode(agent, graph, { type: 'remove', node_id: 'agent-node:identity' }), /cannot be removed/);
  const candidate = editors.agentCandidatePayload({ ...agent, builder_graph: { stale: true }, builder_compiler_receipt: { stale: true } }, Object.fromEntries(added.graph.nodes.map(node => [node.node_id, { x: 0, y: 0 }])), added.graph);
  assert.equal(Object.hasOwn(candidate, 'builder_graph'), true);
  assert.equal(candidate.builder_graph.nodes.some(node => node.node_id === 'agent-node:tools'), true);
  assert.equal(Object.hasOwn(candidate, 'builder_compiler_receipt'), false);
  assert.deepEqual(JSON.parse(JSON.stringify(Object.keys(candidate.editor_layout))), JSON.parse(JSON.stringify(added.graph.nodes.map(node => node.node_id))));
  const enterpriseAgent = editors.normalizeAgent({ agent_id: 'agent:restricted-test', bindings: [{ capability_id: 'enterprise:restricted-worker' }] });
  assert.equal(editors.validateAgent(enterpriseAgent).valid, false);
  assert.match(editors.validateAgent(enterpriseAgent).issues.join(' '), /px-standard domain boundary/);
  agent.grants[0].subject_id = 'agent:someone-else';
  assert.match(editors.validateAgent(agent).issues.join(' '), /subject must match/);
  const defaultWorkflow = editors.normalizeWorkflow();
  assert.equal(editors.validateWorkflow(defaultWorkflow).valid, true);
  assert.equal(editors.normalizeWorkflow({ workflow_id: ' Workflow:Mixed-Case ' }).workflow_id, 'workflow:mixed-case');
  assert.equal(editors.normalizeWorkflow({ version: ' 2.4.8-RC.1 ' }).version, '2.4.8-rc.1');
  assert.equal(defaultWorkflow.bindings[0].state, 'admitted');
  assert.equal(defaultWorkflow.grants[0].state, 'admitted');
  const candidateAuthority = JSON.parse(JSON.stringify(defaultWorkflow));
  candidateAuthority.bindings[0].state = 'candidate';
  candidateAuthority.grants[0].state = 'candidate';
  assert.match(editors.validateWorkflow(candidateAuthority).issues.join(' '), /must be admitted/);
  const duplicateAuthority = JSON.parse(JSON.stringify(defaultWorkflow));
  duplicateAuthority.bindings.push(JSON.parse(JSON.stringify(duplicateAuthority.bindings[0])));
  duplicateAuthority.grants.push(JSON.parse(JSON.stringify(duplicateAuthority.grants[0])));
  assert.match(editors.validateWorkflow(duplicateAuthority).issues.join(' '), /binding IDs must be present and unique/);
  assert.match(editors.validateWorkflow(duplicateAuthority).issues.join(' '), /grant IDs must be present and unique/);
  const missingAdapter = JSON.parse(JSON.stringify(defaultWorkflow));
  missingAdapter.executor_adapters = {};
  assert.match(editors.validateWorkflow(missingAdapter).issues.join(' '), /requires one closed executor adapter/);
  const unknownAdapter = JSON.parse(JSON.stringify(defaultWorkflow));
  unknownAdapter.executor_adapters['binding:unknown'] = 'identity';
  assert.match(editors.validateWorkflow(unknownAdapter).issues.join(' '), /unknown binding/);
  const retainedAuthority = editors.normalizeWorkflow({
    nodes: [{ node_id: 'step:authority', executor_binding_id: 'binding:authority', effect_grant_ids: ['grant:authority'] }],
    bindings: [{ binding_id: 'binding:authority', subject_kind: 'workflow', subject_id: 'workflow:my-workflow', capability_id: 'capability:identity', capability_version: '1.0.0', effect_grant_ids: ['grant:authority'], credential_namespace: 'credential:reference-only', cost_policy: 'bounded-local', egress_policy: 'loopback-only', state: 'admitted', evidence_refs: ['receipt:binding'] }],
    grants: [{ grant_id: 'grant:authority', subject_id: 'workflow:my-workflow', effects: ['read'], scope_roots: ['workspace:current'], approved_by: 'human:owner', evidence_refs: ['receipt:grant'], expires_utc: null, state: 'admitted' }],
    executor_adapters: { 'binding:authority': 'identity' }
  });
  assert.deepEqual(JSON.parse(JSON.stringify(retainedAuthority.bindings[0])), { binding_id: 'binding:authority', subject_kind: 'workflow', subject_id: 'workflow:my-workflow', capability_id: 'capability:identity', capability_version: '1.0.0', effect_grant_ids: ['grant:authority'], credential_namespace: 'credential:reference-only', cost_policy: 'bounded-local', egress_policy: 'loopback-only', state: 'admitted', evidence_refs: ['receipt:binding'] });
  assert.equal(editors.validateWorkflow(retainedAuthority).valid, true);
  const workflow = editors.normalizeWorkflow({ nodes: [{ node_id: 'step:one', position: { x: 0, y: -125.5 }, inputs: [{ name: 'input', data_type: 'string' }], outputs: [{ name: 'output', data_type: 'string' }] }, { node_id: 'step:two', position: { x: 420.25, y: 0 }, failure_policy: 'compensate', timeout_seconds: 86400 }], edges: [{ source_node_id: 'step:one', source_port: 'output', target_node_id: 'step:two', target_port: 'value', condition: 'always' }] });
  assert.deepEqual(JSON.parse(JSON.stringify(workflow.edges[0])), { source_node: 'step:one', source_port: 'output', target_node: 'step:two', target_port: 'value', condition: 'always' });
  assert.deepEqual(JSON.parse(JSON.stringify(workflow.editor_layout)), { 'step:one': { x: 0, y: -125.5 }, 'step:two': { x: 420.25, y: 0 } });
  assert.deepEqual(JSON.parse(JSON.stringify(workflow.nodes.map(node => node.position))), [{ x: 0, y: -125.5 }, { x: 420.25, y: 0 }]);
  assert.equal(workflow.nodes[1].failure_policy, 'fail-closed');
  assert.equal(workflow.nodes[1].timeout_seconds, 3600);
  assert.equal(editors.validateWorkflow(workflow).valid, true);
  workflow.nodes[1].node_id = 'step:one';
  assert.equal(editors.validateWorkflow(workflow).valid, false);
  const skill = editors.normalizeSkill({ skill_id: 'bounded-repair' });
  assert.equal(editors.normalizeSkill({ skill_id: ' Bounded-Mixed-Case ' }).skill_id, 'bounded-mixed-case');
  assert.equal(editors.normalizeSkill({ skill_id: 'bounded-repair', version: ' 2.4.8-RC.1 ' }).version, '2.4.8-rc.1');
  assert.deepEqual(Object.keys(skill.editor_files).sort(), ['SKILL.md', 'capability.json', 'contracts/input.schema.json', 'resources/README.md', 'skill.yaml', 'tests/contract.json']);
  const skillTest = JSON.parse(skill.editor_files['tests/contract.json']);
  assert.equal(skillTest.schema_version, 'px.skill-test/1.1');
  assert.deepEqual(skillTest.cases[0].assertion, { kind: 'required-files', paths: ['SKILL.md', 'capability.json', 'skill.yaml'] });
  assert.equal(JSON.parse(skill.editor_files['capability.json']).version, '1.0.0');
  assert.equal(editors.validateSkill(skill).valid, true);
  const revisedSkill = editors.prepareSkillCandidate({ ...skill, skill_id: 'bounded-repair-next', version: '1.0.1' });
  assert.equal(JSON.parse(revisedSkill.editor_files['capability.json']).id, 'bounded-repair-next');
  assert.equal(JSON.parse(revisedSkill.editor_files['capability.json']).version, '1.0.1');
  assert.match(revisedSkill.editor_files['skill.yaml'], /^id:\s*bounded-repair-next$/m);
  assert.match(revisedSkill.editor_files['skill.yaml'], /^version:\s*1\.0\.1$/m);
  assert.match(revisedSkill.editor_files['SKILL.md'], /^name:\s*bounded-repair-next$/m);
  assert.equal(editors.validateSkill(revisedSkill).valid, true);
  const malformedSkill = editors.prepareSkillCandidate({ ...skill, version: '1.0.2', editor_files: { ...skill.editor_files, 'capability.json': '{' } });
  assert.match(editors.validateSkill(malformedSkill).issues.join(' '), /valid JSON/);
  skill.editor_files['capability.json'] = '{';
  assert.match(editors.validateSkill(skill).issues.join(' '), /valid JSON/);
  const ranked = editors.rankGraph('contradction polcy', [{ key: 'policy:contradiction', title: 'Contradiction Policy', kind: 'policy' }, { key: 'skill:unrelated', title: 'Release Packager', kind: 'skill' }]);
  assert.equal(ranked[0].record.key, 'policy:contradiction');
  assert.ok(ranked[0].score > 0);
});

test('H06 browser health contract preserves configured/detected/connected/authoritative/ready as separate dimensions', () => {
  const health = loadScaffold().require('healthState');
  assert.deepEqual([...health.dimensions], ['configured', 'detected', 'connected', 'authoritative', 'ready']);
  const connected = health.normalize({ configured: true, detected: true, connected: true, authoritative: false, ready: false });
  assert.equal(health.label(connected), 'CONNECTED');
  assert.match(health.summary(connected), /connected yes/);
  assert.match(health.summary(connected), /authoritative no/);
  assert.match(health.summary(connected), /ready no/);
});

test('state scaffold preserves current defaults without sharing mutable containers', () => {
  const stateModule = loadScaffold().require('state');
  const first = stateModule.createInitial({ active: 'memory', graphInspectorOpen: false }, true);
  const second = stateModule.createInitial();
  assert.equal(first.active, 'memory');
  assert.equal(first.graphInspectorOpen, false);
  assert.equal(first.settings.showAdvancedSurfaces, true);
  first.catalogs.changed = true;
  assert.equal(second.catalogs.changed, undefined);
  assert.deepEqual(JSON.parse(JSON.stringify(stateModule.persistedView(first))), {
    active: 'memory', advancedOpen: true, capabilityKind: 'skills', agentScope: 'core', workflowScope: 'core',
    environmentScope: 'graph', graphView: 'capabilities', graphMode: 'full', graphTarget: '', graphLayout: 'community', graphInspectorOpen: false,
    graphDepth: 1, graphKind: '', graphStatus: '', graphCommunity: '', graphSavedViews: [], studioHistory: [], workingStudioDrafts: {}
  });
});

test('bridge scaffold owns post/subscribe and returns a working unsubscribe', () => {
  const posted = [];
  const listeners = new Set();
  const eventTarget = {
    addEventListener(type, listener) { assert.equal(type, 'message'); listeners.add(listener); },
    removeEventListener(type, listener) { assert.equal(type, 'message'); listeners.delete(listener); }
  };
  const bridge = loadScaffold().require('bridge').create({ postMessage: message => posted.push(message), getState: () => ({ active: 'dashboard' }) }, eventTarget);
  let received;
  const unsubscribe = bridge.subscribe(message => { received = message; });
  bridge.post('refresh', { reason: 'test' });
  [...listeners][0]({ data: { type: 'snapshot' } });
  assert.equal(JSON.stringify(posted), JSON.stringify([{ type: 'refresh', reason: 'test' }]));
  assert.equal(JSON.stringify(received), JSON.stringify({ type: 'snapshot' }));
  unsubscribe();
  assert.equal(listeners.size, 0);
});

test('component scaffold escapes untrusted values and formats bounded values', () => {
  const components = loadScaffold().require('components');
  assert.equal(components.escapeHtml('<script>"x"</script>'), '&lt;script&gt;&quot;x&quot;&lt;/script&gt;');
  assert.equal(components.bytes(1024), '1.0 KB');
  assert.match(components.badge('<unsafe>'), /&lt;unsafe&gt;/);
  assert.match(components.card('<unsafe>', '1'), /data-metric-label="&lt;unsafe&gt;"/);
  assert.match(components.section('<unsafe>', 'test', 'body'), /<h2>&lt;unsafe&gt;<\/h2>/);
});

test('U04 stylesheet layers load in admitted order before the legacy compatibility sheet', () => {
  const extension = fs.readFileSync(path.join(root, 'src', 'extension.js'), 'utf8');
  const preview = fs.readFileSync(path.join(root, 'tests', 'preview.html'), 'utf8');
  for (const source of [extension, preview]) {
    const positions = [...styleFiles.map(file => source.indexOf(file)), source.indexOf('dashboard.css')];
    assert.equal(positions.every(position => position >= 0), true);
    assert.deepEqual(positions, [...positions].sort((left, right) => left - right));
  }
  assert.equal(fs.readFileSync(path.join(root, 'media', 'styles', styleFiles[0]), 'utf8').trim(), '@layer px.legacy, px.tokens, px.primitives, px.layout, px.components, px.surfaces, px.responsive, px.accessibility;');
});

test('U05 compatibility CSS is lowest priority and the modular header owns non-overlapping action tracks', () => {
  const legacy = fs.readFileSync(path.join(root, 'media', 'dashboard.css'), 'utf8').trim();
  const layout = fs.readFileSync(path.join(root, 'media', 'styles', '20-layout.css'), 'utf8');
  const responsive = fs.readFileSync(path.join(root, 'media', 'styles', '50-responsive.css'), 'utf8');
  assert.match(legacy, /^@layer\s+px\.legacy\s*\{/);
  assert.equal(legacy.endsWith('}'), true);
  assert.match(layout, /\.cockpit-header[\s\S]*grid-template-columns:[\s\S]*\.cockpit-actions[\s\S]*grid-template-columns/);
  for (const width of ['1320px', '1040px', '760px', '520px']) assert.match(responsive, new RegExp(`max-width: ${width}`));
});

test('U01/U02 browser modules load in admitted order before the legacy renderer', () => {
  const extension = fs.readFileSync(path.join(root, 'src', 'extension.js'), 'utf8');
  const preview = fs.readFileSync(path.join(root, 'tests', 'preview.html'), 'utf8');
  for (const source of [extension, preview]) {
    const positions = [...moduleFiles.map(file => source.indexOf(file)), source.lastIndexOf('90-controller.js')];
    assert.equal(positions.every(position => position >= 0), true);
    assert.deepEqual(positions, [...positions].sort((left, right) => left - right));
  }
});

test('scaffold selectors are parseable and the full duplicate-selector report stays within baseline', () => {
  for (const file of styleFiles.slice(1)) {
    const source = fs.readFileSync(path.join(root, 'media', 'styles', file), 'utf8');
    assert.ok(Array.isArray(selectorsFromCss(source)));
  }
  const report = audit();
  assert.ok(report.selector_occurrences > report.unique_selectors);
  assert.ok(report.duplicates.every(item => item.selector && item.occurrences > 1));
  assert.ok(report.duplicate_selector_count <= 263);
  assert.ok(report.duplicate_occurrences <= 494);
  assert.equal(report.cross_file_duplicate_selector_count, 0);
  assert.equal(report.cross_file_duplicate_occurrences, 0);
});

test('active muted and faint text tokens meet normal-text AA contrast', () => {
  const checks = contrastChecks();
  assert.ok(checks.length > 0);
  assert.ok(checks.every(item => item.ratio >= item.required), JSON.stringify(checks));
});

test('U05 system-surface selectors have no legacy compatibility owner', () => {
  const legacy = fs.readFileSync(path.join(root, 'media', 'dashboard.css'), 'utf8');
  const surfaces = fs.readFileSync(path.join(root, 'media', 'styles', '40-surfaces.css'), 'utf8');
  for (const selector of ['validation-box', 'readiness-summary', 'readiness-row', 'policy-switch', 'guardrail-grid', 'cleanup-summary', 'cleanup-pipeline', 'cleanup-toolbar', 'cleanup-list', 'cleanup-row', 'cleanup-receipt', 'cleanup-loading', 'danger-action', 'sensor-summary', 'sensor-list', 'sensor-row', 'sensor-providers', 'plugin-boundary', 'plugin-actions', 'plugin-list', 'plugin-row', 'plugin-connectors']) {
    assert.equal(selectorsFromCss(legacy).some(value => value === `.${selector}` || value.startsWith(`.${selector}:`) || value.startsWith(`.${selector} `) || value.startsWith(`.${selector}>`)), false, selector);
    assert.match(surfaces, new RegExp(`\\.${selector}\\b`), selector);
  }
});
