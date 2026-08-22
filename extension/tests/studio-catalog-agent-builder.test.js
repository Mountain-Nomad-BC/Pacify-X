'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { collectStudioCatalog } = require('../src/studioCatalog');

function loadStudioEditors() {
  const priorDashboard = globalThis.PXDashboard;
  let editors = null;
  globalThis.PXDashboard = {
    define(name, value) {
      if (name === 'studioEditors') editors = value;
    }
  };
  try {
    const source = require.resolve('../media/dashboard/49-studio-editors');
    delete require.cache[source];
    require(source);
  } finally {
    if (priorDashboard === undefined) delete globalThis.PXDashboard;
    else globalThis.PXDashboard = priorDashboard;
  }
  assert.ok(editors, 'Studio editor module did not register');
  return editors;
}

const studioEditors = loadStudioEditors();

test('Agent Studio exposes only runtime-owned structural checks and rejects unknown imported IDs', () => {
  assert.deepEqual(studioEditors.agentStructuralChecks.map(check => check.id), [
    'identity', 'sandbox', 'model-route', 'input-contract', 'output-contract',
    'authority-bindings', 'tool-bindings', 'handoff-topology'
  ]);
  const draft = studioEditors.normalizeAgent({ required_tests: ['identity', 'not-a-runtime-check'] });
  const validation = studioEditors.validateAgent(draft);
  assert.equal(validation.valid, false);
  assert.ok(validation.issues.includes('Unknown structural preflight check not-a-runtime-check. Select a check implemented by the current runtime.'));
});

const NODE_ORDER = [
  'identity', 'behavior', 'model', 'harness', 'capabilities', 'tools', 'contracts',
  'authority', 'tests', 'candidate'
];
const PORTS = {
  identity: [['out:definition', 'output', 'definition']],
  behavior: [['in:definition', 'input', 'definition'], ['out:definition', 'output', 'definition']],
  model: [['in:definition', 'input', 'definition'], ['out:model-route', 'output', 'model-route']],
  harness: [['in:model-route', 'input', 'model-route'], ['out:capability', 'output', 'capability']],
  capabilities: [['in:capability', 'input', 'capability'], ['out:capability', 'output', 'capability'], ['out:authority', 'output', 'authority']],
  tools: [['in:capability', 'input', 'capability'], ['out:authority', 'output', 'authority']],
  contracts: [['in:definition', 'input', 'definition'], ['out:contract', 'output', 'contract']],
  authority: [['in:authority', 'input', 'authority'], ['out:validation', 'output', 'validation']],
  tests: [['in:validation', 'input', 'validation'], ['in:contract', 'input', 'contract'], ['out:candidate', 'output', 'candidate']],
  candidate: [['in:candidate', 'input', 'candidate']]
};

function pythonCanonicalJson(value, forceFloat, parts = []) {
  if (Array.isArray(value)) return `[${value.map((item, index) => pythonCanonicalJson(item, forceFloat, [...parts, index])).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${pythonCanonicalJson(value[key], forceFloat, [...parts, key])}`).join(',')}}`;
  if (typeof value === 'number' && Number.isInteger(value) && forceFloat(parts)) return `${value}.0`;
  return JSON.stringify(value);
}

function digest(value, forceFloat = () => false) {
  return crypto.createHash('sha256').update(pythonCanonicalJson(value, forceFloat)).digest('hex');
}

const graphFloat = parts => parts.length >= 3 && parts.at(-3) === 'config' && parts.at(-2) === 'model' && parts.at(-1) === 'temperature';
const specFloat = parts => parts.length === 2 && parts[0] === 'model' && parts[1] === 'temperature';
const layoutFloat = parts => parts.length === 2 && ['x', 'y'].includes(parts[1]);

function edge(sourceKind, sourcePort, targetKind, targetPort, relation) {
  const source_node = `agent-node:${sourceKind}`; const target_node = `agent-node:${targetKind}`;
  const material = `${source_node}|${sourcePort}|${target_node}|${targetPort}|${relation}`;
  return {
    edge_id: `agent-edge:${crypto.createHash('sha256').update(material).digest('hex').slice(0, 20)}`,
    source_node,
    source_port: sourcePort,
    target_node,
    target_port: targetPort,
    relation
  };
}

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'px-agent-builder-catalog-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const revision = path.join(
    root, '.engineering-bootstrap', 'studios', 'agents',
    'agent-builder-demo-deadbeef', 'revisions', '1.0.0'
  );
  fs.mkdirSync(revision, { recursive: true });
  const spec = {
    agent_id: 'agent:builder-demo',
    version: '1.0.0',
    project_id: 'project:demo',
    owner: 'human:owner',
    harness_id: 'harness:px',
    instruction_sha256: 'a'.repeat(64),
    capability_binding_ids: ['binding:capability'],
    effect_grant_ids: ['grant:read'],
    required_tests: ['identity', 'sandbox'],
    lifecycle: 'draft',
    model: {
      provider: 'deterministic', vendor: '', family: 'px-bounded-worker',
      model_id: 'px-bounded-worker', version: '', max_output_tokens: 1024,
      temperature: 0.5
    },
    tool_binding_ids: [],
    memory_binding_ids: [],
    handoff_agent_ids: [],
    input_schema: { type: 'object', additionalProperties: true },
    output_schema: { type: 'object', additionalProperties: true }
  };
  const configs = {
    identity: { agent_id: spec.agent_id, version: spec.version, project_id: spec.project_id, owner: spec.owner },
    behavior: { instruction_sha256: spec.instruction_sha256 },
    model: { model: spec.model },
    harness: { harness_id: spec.harness_id },
    capabilities: { binding_ids: spec.capability_binding_ids },
    tools: { binding_ids: spec.tool_binding_ids },
    contracts: { input_schema: spec.input_schema, output_schema: spec.output_schema },
    authority: { grant_ids: spec.effect_grant_ids },
    tests: { test_ids: spec.required_tests },
    candidate: { lifecycle: spec.lifecycle }
  };
  const graph = {
    schema_version: 'px.agent-builder-graph/1.0',
    agent_id: spec.agent_id,
    nodes: NODE_ORDER.map(kind => ({
      node_id: `agent-node:${kind}`,
      kind,
      ports: PORTS[kind].map(([port_id, direction, data_type]) => ({ port_id, direction, data_type })),
      config: configs[kind]
    })),
    edges: [
      edge('identity', 'out:definition', 'behavior', 'in:definition', 'owns'),
      edge('behavior', 'out:definition', 'model', 'in:definition', 'prompts'),
      edge('model', 'out:model-route', 'harness', 'in:model-route', 'routes'),
      edge('harness', 'out:capability', 'capabilities', 'in:capability', 'requests'),
      edge('behavior', 'out:definition', 'contracts', 'in:definition', 'defines'),
      edge('capabilities', 'out:authority', 'authority', 'in:authority', 'authorizes'),
      edge('capabilities', 'out:capability', 'tools', 'in:capability', 'binds'),
      edge('tools', 'out:authority', 'authority', 'in:authority', 'authorizes'),
      edge('contracts', 'out:contract', 'tests', 'in:contract', 'constrains'),
      edge('authority', 'out:validation', 'tests', 'in:validation', 'validates'),
      edge('tests', 'out:candidate', 'candidate', 'in:candidate', 'produces')
    ].sort((left, right) => left.edge_id.localeCompare(right.edge_id))
  };
  const layout = Object.fromEntries(NODE_ORDER.map((kind, index) => [
    `agent-node:${kind}`,
    { x: 48.5 + (index % 4) * 260, y: 48.5 + Math.floor(index / 4) * 150 }
  ]));
  const graphEnvelope = {
    schema_version: graph.schema_version,
    record: graph,
    sha256: digest(graph, graphFloat)
  };
  const layoutEnvelope = {
    schema_version: 'px.agent-builder-layout/1.0',
    graph_sha256: graphEnvelope.sha256,
    layout,
    layout_sha256: digest(layout, layoutFloat)
  };
  const compiler = {
    schema_version: 'px.agent-builder-compiler-receipt/1.0',
    compiler: 'runtime.agent_builder.compile_agent_builder_graph',
    graph_sha256: graphEnvelope.sha256,
    layout_sha256: layoutEnvelope.layout_sha256,
    agent_spec_sha256: digest(spec, specFloat),
    deterministic: true,
    authority_granted: false,
    host_authority_retained: true
  };
  compiler.receipt_sha256 = digest(compiler);
  const files = {
    record: path.join(revision, 'record.json'),
    graph: path.join(revision, 'builder-graph.json'),
    layout: path.join(revision, 'editor-layout.json'),
    compiler: path.join(revision, 'builder-compiler-receipt.json'),
    creation: path.join(revision, 'creation-receipt.json')
  };
  write(files.record, { schema_version: 'px.agentspec/1.0', record: spec, sha256: digest(spec, specFloat) });
  write(files.graph, graphEnvelope);
  write(files.layout, layoutEnvelope);
  write(files.compiler, compiler);
  write(files.creation, { schema_version: 'px.agent-creation-receipt/1.1', builder_graph_state: 'content-bound' });
  return { root, revision, spec, graphEnvelope, layoutEnvelope, compiler, files };
}

function write(file, value) {
  fs.writeFileSync(file, `${JSON.stringify(sortJson(value), null, 2)}\n`, 'utf8');
}

function sortJson(value) {
  if (Array.isArray(value)) return value.map(sortJson);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.keys(value).sort().map(key => [key, sortJson(value[key])])
  );
}

function snapshot(directory) {
  return fs.readdirSync(directory, { withFileTypes: true })
    .sort((left, right) => left.name.localeCompare(right.name))
    .map(entry => entry.isDirectory()
      ? [entry.name, snapshot(path.join(directory, entry.name))]
      : [entry.name, fs.readFileSync(path.join(directory, entry.name), 'base64')]);
}

test('catalog reopens an exact hash-bound graph that compiles to AgentSpec', t => {
  const data = fixture(t);
  const page = collectStudioCatalog(data.root, 'agents');
  assert.equal(page.refused, 0);
  assert.equal(page.items.length, 1);
  assert.equal(page.items[0].details.builder_graph_state, 'content-bound');
  assert.deepEqual(page.items[0].details.builder_graph, data.graphEnvelope.record);
  assert.deepEqual(page.items[0].details.builder_graph.nodes.find(node => node.kind === 'tools').config.binding_ids, []);
  assert.deepEqual(page.items[0].details.editor_layout, data.layoutEnvelope.layout);
  assert.equal(page.items[0].details.builder_compiler_receipt.authority_granted, false);
  assert.equal(page.items[0].details.builder_compiler_receipt.host_authority_retained, true);
});

test('typed AgentSpec connection edits preserve an incomplete draft and only admit canonical reconnection', () => {
  const draft = studioEditors.normalizeAgent({ agent_id: 'agent:typed-edge-test' });
  const canonical = studioEditors.projectAgentBuilderGraph(draft);
  const removedEdge = canonical.edges.find(item => item.relation === 'owns');
  assert.ok(removedEdge, 'canonical AgentSpec graph must include the identity ownership edge');

  const disconnected = studioEditors.editAgentBuilderEdge(draft, canonical, {
    type: 'remove', edge_id: removedEdge.edge_id
  });
  assert.equal(disconnected.edges.length, canonical.edges.length - 1);
  assert.equal(studioEditors.validateAgentBuilderGraph(disconnected).valid, false);
  assert.match(
    studioEditors.validateAgentBuilderGraph(disconnected).issues.join('\n'),
    /closed executable topology/
  );

  const synchronized = studioEditors.synchronizeAgentBuilderGraph(draft, disconnected);
  assert.deepEqual(synchronized.edges, disconnected.edges, 'synchronization must not silently restore a removed edge');
  const payload = studioEditors.agentCandidatePayload(draft, {}, disconnected);
  assert.deepEqual(payload.builder_graph.edges, disconnected.edges, 'candidate projection must retain the incomplete working graph for validation');

  assert.throws(
    () => studioEditors.editAgentBuilderEdge(draft, disconnected, {
      type: 'add',
      source_node: removedEdge.source_node,
      source_port: removedEdge.source_port,
      target_node: 'agent-node:model',
      target_port: 'in:definition'
    }),
    /do not form an admitted AgentSpec connection/
  );

  const restored = studioEditors.editAgentBuilderEdge(draft, synchronized, {
    type: 'add',
    source_node: removedEdge.source_node,
    source_port: removedEdge.source_port,
    target_node: removedEdge.target_node,
    target_port: removedEdge.target_port
  });
  assert.deepEqual(restored, canonical);
  assert.equal(studioEditors.validateAgentBuilderGraph(restored).valid, true);
});

test('catalog rejects a rehashed semantic graph substitution', t => {
  const data = fixture(t);
  data.graphEnvelope.record.nodes.find(node => node.kind === 'candidate').config.lifecycle = 'admitted';
  data.graphEnvelope.sha256 = digest(data.graphEnvelope.record, graphFloat);
  data.layoutEnvelope.graph_sha256 = data.graphEnvelope.sha256;
  data.compiler.graph_sha256 = data.graphEnvelope.sha256;
  delete data.compiler.receipt_sha256;
  data.compiler.receipt_sha256 = digest(data.compiler);
  write(data.files.graph, data.graphEnvelope);
  write(data.files.layout, data.layoutEnvelope);
  write(data.files.compiler, data.compiler);
  const page = collectStudioCatalog(data.root, 'agents');
  assert.equal(page.items.length, 0);
  assert.equal(page.refused, 1);
});

test('catalog rejects partial and missing modern builder artifacts', t => {
  const partial = fixture(t);
  fs.unlinkSync(partial.files.compiler);
  let page = collectStudioCatalog(partial.root, 'agents');
  assert.equal(page.items.length, 0);
  assert.equal(page.refused, 1);

  const missing = fixture(t);
  [missing.files.graph, missing.files.layout, missing.files.compiler].forEach(file => fs.unlinkSync(file));
  page = collectStudioCatalog(missing.root, 'agents');
  assert.equal(page.items.length, 0);
  assert.equal(page.refused, 1);
});

test('catalog reports legacy-unavailable without writing or backfilling', t => {
  const data = fixture(t);
  [data.files.graph, data.files.layout, data.files.compiler].forEach(file => fs.unlinkSync(file));
  write(data.files.creation, { schema_version: 'px.agent-creation-receipt/1.0' });
  const before = snapshot(data.root);
  const page = collectStudioCatalog(data.root, 'agents');
  assert.equal(page.refused, 0);
  assert.equal(page.items.length, 1);
  assert.equal(page.items[0].details.builder_graph_state, 'legacy-unavailable');
  assert.deepEqual(snapshot(data.root), before);
});
