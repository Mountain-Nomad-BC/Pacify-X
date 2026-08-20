'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { revisionTreeSha256, validVersion } = require('./studioDashboardHost');

const MAX_REVISIONS = 1000;
const MAX_RECORD_BYTES = 1024 * 1024;
const STUDIO_IDENTITY = /^[a-z0-9][a-z0-9._:-]{1,127}$/;

const KIND_LAYOUT = Object.freeze({
  agents: Object.freeze({ directory: 'agents', record: 'record.json', identity: 'agent_id', kind: 'studio-agent-revision' }),
  workflows: Object.freeze({ directory: 'workflows', record: 'record.json', identity: 'workflow_id', kind: 'studio-workflow-revision' }),
  skills: Object.freeze({ directory: 'skills', record: 'package-record.json', identity: 'skill_id', kind: 'studio-skill-revision' })
});

function physicalDirectoryEntries(directory) {
  try {
    const stat = fs.lstatSync(directory);
    if (!stat.isDirectory() || stat.isSymbolicLink()) return [];
    const handle = fs.opendirSync(directory); const entries = []; let observed = 0;
    try {
      for (;;) {
        const entry = handle.readSync(); if (!entry) break;
        observed += 1;
        if (observed > MAX_REVISIONS) throw new Error('studio-catalog-directory-bound-exceeded');
        if (entry.isDirectory() && !entry.isSymbolicLink()) entries.push(entry);
      }
    } finally { handle.closeSync(); }
    return entries.sort((left, right) => Buffer.compare(Buffer.from(left.name, 'utf8'), Buffer.from(right.name, 'utf8')));
  } catch (error) {
    if (['ENOENT', 'ENOTDIR'].includes(error?.code)) return [];
    throw error;
  }
}

function readBoundedJson(file) {
  const before = fs.lstatSync(file);
  if (!before.isFile() || before.isSymbolicLink() || before.size > MAX_RECORD_BYTES) throw new Error('studio-catalog-record-refused');
  const descriptor = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0)); let stat; let bytes;
  try {
    stat = fs.fstatSync(descriptor);
    if (!stat.isFile() || stat.size > MAX_RECORD_BYTES || stat.dev !== before.dev || stat.ino !== before.ino) throw new Error('studio-catalog-record-refused');
    const buffer = Buffer.alloc(stat.size + 1); let offset = 0;
    while (offset < buffer.length) { const count = fs.readSync(descriptor, buffer, offset, buffer.length - offset, null); if (!count) break; offset += count; }
    if (offset !== stat.size) throw new Error('studio-catalog-record-changed');
    bytes = buffer.subarray(0, offset);
  } finally { fs.closeSync(descriptor); }
  const raw = bytes.toString('utf8');
  if (!Buffer.from(raw, 'utf8').equals(bytes)) throw new Error('studio-catalog-record-encoding-invalid');
  const value = JSON.parse(raw);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('studio-catalog-record-invalid');
  return { value, stat, raw };
}

function readBoundedText(file) {
  const before = fs.lstatSync(file);
  if (!before.isFile() || before.isSymbolicLink() || before.size > MAX_RECORD_BYTES) throw new Error('studio-catalog-text-refused');
  const descriptor = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0)); let bytes;
  try {
    const stat = fs.fstatSync(descriptor);
    if (!stat.isFile() || stat.size > MAX_RECORD_BYTES || stat.dev !== before.dev || stat.ino !== before.ino) throw new Error('studio-catalog-text-refused');
    const buffer = Buffer.alloc(stat.size + 1); let offset = 0;
    while (offset < buffer.length) { const count = fs.readSync(descriptor, buffer, offset, buffer.length - offset, null); if (!count) break; offset += count; }
    if (offset !== stat.size) throw new Error('studio-catalog-text-changed');
    bytes = buffer.subarray(0, offset);
  } finally { fs.closeSync(descriptor); }
  const text = bytes.toString('utf8');
  if (!Buffer.from(text, 'utf8').equals(bytes)) throw new Error('studio-catalog-text-encoding-invalid');
  return text;
}

function relativePath(root, target) {
  const relative = path.relative(root, target);
  if (!relative || path.isAbsolute(relative) || relative === '..' || relative.startsWith(`..${path.sep}`)) throw new Error('studio-catalog-path-outside-project');
  return relative.replaceAll('\\', '/');
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}

function authorityDefinition(revision, kind, identity, version) {
  const file = path.join(revision, 'authority-definition.json');
  if (!fs.existsSync(file)) return null;
  const { value: envelope } = readBoundedJson(file); const record = envelope.record;
  const recordKeys = ['schema_version', 'kind', 'subject_id', 'version', 'builder_domain', 'bindings', 'grants', 'executor_adapters', 'run_input_contract', 'runtime_input_values_stored'];
  const bindingKeys = ['binding_id', 'subject_kind', 'subject_id', 'capability_id', 'capability_version', 'effect_grant_ids', 'credential_namespace', 'cost_policy', 'egress_policy', 'state', 'evidence_refs'];
  const grantKeys = ['grant_id', 'subject_id', 'effects', 'scope_roots', 'approved_by', 'evidence_refs', 'expires_utc', 'state'];
  if (!sameKeys(envelope, ['record', 'sha256']) || !record || typeof record !== 'object' || Array.isArray(record) || !sameKeys(record, recordKeys)) throw new Error('studio-authority-definition-invalid');
  const actual = crypto.createHash('sha256').update(Buffer.from(canonicalJson(record), 'utf8')).digest('hex');
  if (actual !== envelope.sha256 || record.schema_version !== 'px.studio-authority-definition/1.0' || record.kind !== kind || record.subject_id !== identity || record.version !== version || record.builder_domain !== 'px-standard' || record.runtime_input_values_stored !== false || !Array.isArray(record.bindings) || !Array.isArray(record.grants) || !record.executor_adapters || typeof record.executor_adapters !== 'object' || Array.isArray(record.executor_adapters) || !Array.isArray(record.run_input_contract)) throw new Error('studio-authority-definition-identity-mismatch');
  for (const binding of record.bindings) if (!binding || typeof binding !== 'object' || Array.isArray(binding) || !sameKeys(binding, bindingKeys) || binding.subject_kind !== kind || binding.subject_id !== identity || !Array.isArray(binding.effect_grant_ids) || !Array.isArray(binding.evidence_refs)) throw new Error('studio-authority-binding-invalid');
  for (const grant of record.grants) if (!grant || typeof grant !== 'object' || Array.isArray(grant) || !sameKeys(grant, grantKeys) || grant.subject_id !== identity || !Array.isArray(grant.effects) || !Array.isArray(grant.scope_roots) || !Array.isArray(grant.evidence_refs)) throw new Error('studio-authority-grant-invalid');
  for (const item of record.run_input_contract) if (!item || typeof item !== 'object' || Array.isArray(item) || !sameKeys(item, ['key', 'value_type', 'required']) || typeof item.key !== 'string' || !item.key || typeof item.value_type !== 'string' || typeof item.required !== 'boolean') throw new Error('studio-authority-input-contract-invalid');
  if (kind === 'agent' && (Object.keys(record.executor_adapters).length || record.run_input_contract.length)) throw new Error('studio-agent-authority-workflow-fields-invalid');
  return record;
}

function sameKeys(value, expected) {
  return Object.keys(value).sort().join('\n') === [...expected].sort().join('\n');
}

const AGENT_NODE_ORDER = Object.freeze([
  'identity', 'behavior', 'model', 'harness', 'capabilities', 'tools',
  'handoffs', 'memory', 'contracts', 'authority', 'tests', 'candidate'
]);
const AGENT_OPTIONAL_NODES = new Set(['tools', 'handoffs', 'memory']);
const AGENT_PORTS = Object.freeze({
  identity: [['out:definition', 'output', 'definition']],
  behavior: [['in:definition', 'input', 'definition'], ['out:definition', 'output', 'definition']],
  model: [['in:definition', 'input', 'definition'], ['out:model-route', 'output', 'model-route']],
  harness: [['in:model-route', 'input', 'model-route'], ['out:capability', 'output', 'capability']],
  capabilities: [['in:capability', 'input', 'capability'], ['out:capability', 'output', 'capability'], ['out:authority', 'output', 'authority']],
  tools: [['in:capability', 'input', 'capability'], ['out:authority', 'output', 'authority']],
  handoffs: [['in:capability', 'input', 'capability'], ['out:authority', 'output', 'authority']],
  memory: [['in:definition', 'input', 'definition'], ['out:authority', 'output', 'authority']],
  contracts: [['in:definition', 'input', 'definition'], ['out:contract', 'output', 'contract']],
  authority: [['in:authority', 'input', 'authority'], ['out:validation', 'output', 'validation']],
  tests: [['in:validation', 'input', 'validation'], ['in:contract', 'input', 'contract'], ['out:candidate', 'output', 'candidate']],
  candidate: [['in:candidate', 'input', 'candidate']]
});

function scanJsonString(raw, start) {
  let escaped = false;
  for (let index = start + 1; index < raw.length; index += 1) {
    if (escaped) escaped = false;
    else if (raw[index] === '\\') escaped = true;
    else if (raw[index] === '"') return index + 1;
  }
  throw new Error('studio-catalog-json-string-invalid');
}

function scanJsonValue(raw, start) {
  if (raw[start] === '"') return scanJsonString(raw, start);
  if (['{', '['].includes(raw[start])) {
    const stack = []; let inString = false; let escaped = false;
    for (let index = start; index < raw.length; index += 1) {
      const token = raw[index];
      if (inString) {
        if (escaped) escaped = false;
        else if (token === '\\') escaped = true;
        else if (token === '"') inString = false;
      } else if (token === '"') inString = true;
      else if (token === '{') stack.push('}');
      else if (token === '[') stack.push(']');
      else if (token === stack.at(-1)) {
        stack.pop();
        if (stack.length === 0) return index + 1;
      }
    }
    throw new Error('studio-catalog-json-value-invalid');
  }
  let index = start;
  while (index < raw.length && ![',', '}'].includes(raw[index])) index += 1;
  return index;
}

function compactStoredJson(raw) {
  let compact = ''; let inString = false; let escaped = false;
  for (const token of raw) {
    if (inString) {
      compact += token;
      if (escaped) escaped = false;
      else if (token === '\\') escaped = true;
      else if (token === '"') inString = false;
    } else if (token === '"') { inString = true; compact += token; }
    else if (!/\s/.test(token)) compact += token;
  }
  if (inString) throw new Error('studio-catalog-json-string-invalid');
  return compact;
}

function storedJsonMember(raw, member) {
  let index = 0;
  const whitespace = /\s/;
  while (whitespace.test(raw[index] || '')) index += 1;
  if (raw[index] !== '{') throw new Error('studio-catalog-json-object-invalid');
  index += 1;
  while (index < raw.length) {
    while (whitespace.test(raw[index] || '')) index += 1;
    if (raw[index] === '}') break;
    if (raw[index] !== '"') throw new Error('studio-catalog-json-key-invalid');
    const keyEnd = scanJsonString(raw, index); const key = JSON.parse(raw.slice(index, keyEnd));
    index = keyEnd;
    while (whitespace.test(raw[index] || '')) index += 1;
    if (raw[index] !== ':') throw new Error('studio-catalog-json-colon-invalid');
    index += 1;
    while (whitespace.test(raw[index] || '')) index += 1;
    const valueStart = index; const valueEnd = scanJsonValue(raw, valueStart);
    if (key === member) return compactStoredJson(raw.slice(valueStart, valueEnd));
    index = valueEnd;
    while (whitespace.test(raw[index] || '')) index += 1;
    if (raw[index] === ',') index += 1;
    else if (raw[index] !== '}') throw new Error('studio-catalog-json-separator-invalid');
  }
  throw new Error('studio-catalog-json-member-missing');
}

function storedMemberSha256(raw, member) {
  return crypto.createHash('sha256').update(Buffer.from(storedJsonMember(raw, member), 'utf8')).digest('hex');
}

function expectedAgentEdges(kinds) {
  const rows = [
    ['identity', 'out:definition', 'behavior', 'in:definition', 'owns'],
    ['behavior', 'out:definition', 'model', 'in:definition', 'prompts'],
    ['model', 'out:model-route', 'harness', 'in:model-route', 'routes'],
    ['harness', 'out:capability', 'capabilities', 'in:capability', 'requests'],
    ['behavior', 'out:definition', 'contracts', 'in:definition', 'defines'],
    ['capabilities', 'out:authority', 'authority', 'in:authority', 'authorizes'],
    ['contracts', 'out:contract', 'tests', 'in:contract', 'constrains'],
    ['authority', 'out:validation', 'tests', 'in:validation', 'validates'],
    ['tests', 'out:candidate', 'candidate', 'in:candidate', 'produces']
  ];
  if (kinds.has('tools')) rows.push(
    ['capabilities', 'out:capability', 'tools', 'in:capability', 'binds'],
    ['tools', 'out:authority', 'authority', 'in:authority', 'authorizes']
  );
  if (kinds.has('handoffs')) rows.push(
    ['capabilities', 'out:capability', 'handoffs', 'in:capability', 'hands-off'],
    ['handoffs', 'out:authority', 'authority', 'in:authority', 'authorizes']
  );
  if (kinds.has('memory')) rows.push(
    ['behavior', 'out:definition', 'memory', 'in:definition', 'retrieves'],
    ['memory', 'out:authority', 'authority', 'in:authority', 'authorizes']
  );
  return rows.map(([sourceKind, sourcePort, targetKind, targetPort, relation]) => {
    const source_node = `agent-node:${sourceKind}`; const target_node = `agent-node:${targetKind}`;
    const material = `${source_node}|${sourcePort}|${target_node}|${targetPort}|${relation}`;
    return {
      edge_id: `agent-edge:${crypto.createHash('sha256').update(material).digest('hex').slice(0, 20)}`,
      source_node, source_port: sourcePort, target_node, target_port: targetPort, relation
    };
  }).sort((left, right) => left.edge_id.localeCompare(right.edge_id));
}

function expectedAgentConfigs(spec) {
  return {
    identity: { agent_id: spec.agent_id, version: spec.version, project_id: spec.project_id, owner: spec.owner },
    behavior: { instruction_sha256: spec.instruction_sha256 },
    model: { model: spec.model },
    harness: { harness_id: spec.harness_id },
    capabilities: { binding_ids: spec.capability_binding_ids },
    tools: { binding_ids: spec.tool_binding_ids },
    handoffs: { agent_ids: spec.handoff_agent_ids },
    memory: { binding_ids: spec.memory_binding_ids },
    contracts: { input_schema: spec.input_schema, output_schema: spec.output_schema },
    authority: { grant_ids: spec.effect_grant_ids },
    tests: { test_ids: spec.required_tests },
    candidate: { lifecycle: spec.lifecycle }
  };
}

function validateAgentBuilderGraph(graph, spec) {
  if (!sameKeys(graph, ['schema_version', 'agent_id', 'nodes', 'edges']) || graph.schema_version !== 'px.agent-builder-graph/1.0' || graph.agent_id !== spec.agent_id || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
    throw new Error('studio-agent-builder-graph-contract-invalid');
  }
  const optionalPresence = {
    tools: Array.isArray(spec.tool_binding_ids) && spec.tool_binding_ids.length > 0,
    handoffs: Array.isArray(spec.handoff_agent_ids) && spec.handoff_agent_ids.length > 0,
    memory: Array.isArray(spec.memory_binding_ids) && spec.memory_binding_ids.length > 0
  };
  const actualKinds = graph.nodes.map(node => String(node?.kind || ''));
  const actualKindSet = new Set(actualKinds);
  const requiredKinds = AGENT_NODE_ORDER.filter(kind => !AGENT_OPTIONAL_NODES.has(kind));
  const canonicalKinds = AGENT_NODE_ORDER.filter(kind => actualKindSet.has(kind));
  if (
    actualKindSet.size !== actualKinds.length ||
    actualKinds.some(kind => !AGENT_NODE_ORDER.includes(kind)) ||
    requiredKinds.some(kind => !actualKindSet.has(kind)) ||
    Object.entries(optionalPresence).some(([kind, required]) => required && !actualKindSet.has(kind)) ||
    canonicalJson(actualKinds) !== canonicalJson(canonicalKinds)
  ) throw new Error('studio-agent-builder-node-set-invalid');
  const expectedKinds = actualKinds;
  const configs = expectedAgentConfigs(spec);
  graph.nodes.forEach((node, index) => {
    const kind = expectedKinds[index]; const expectedPorts = AGENT_PORTS[kind];
    if (!node || typeof node !== 'object' || Array.isArray(node) || !sameKeys(node, ['node_id', 'kind', 'ports', 'config']) || node.node_id !== `agent-node:${kind}` || node.kind !== kind || !Array.isArray(node.ports) || node.ports.length !== expectedPorts.length) {
      throw new Error('studio-agent-builder-node-contract-invalid');
    }
    node.ports.forEach((port, portIndex) => {
      const [port_id, direction, data_type] = expectedPorts[portIndex];
      if (!port || typeof port !== 'object' || Array.isArray(port) || !sameKeys(port, ['port_id', 'direction', 'data_type']) || port.port_id !== port_id || port.direction !== direction || port.data_type !== data_type) {
        throw new Error('studio-agent-builder-port-contract-invalid');
      }
    });
    if (canonicalJson(node.config) !== canonicalJson(configs[kind])) throw new Error('studio-agent-builder-graph-spec-mismatch');
  });
  const expectedEdges = expectedAgentEdges(new Set(expectedKinds));
  if (canonicalJson(graph.edges) !== canonicalJson(expectedEdges)) throw new Error('studio-agent-builder-edge-contract-invalid');
}

function validateAgentBuilderLayout(layout, graph) {
  const nodeIds = graph.nodes.map(node => node.node_id);
  if (!sameKeys(layout, nodeIds)) throw new Error('studio-agent-builder-layout-node-set-invalid');
  nodeIds.forEach(nodeId => {
    const position = layout[nodeId];
    if (!position || typeof position !== 'object' || Array.isArray(position) || !sameKeys(position, ['x', 'y']) || !Number.isFinite(position.x) || !Number.isFinite(position.y) || Math.abs(position.x) > 100000 || Math.abs(position.y) > 100000) {
      throw new Error('studio-agent-builder-layout-position-invalid');
    }
  });
}

function validateWorkflowEditorLayout(layout, workflow) {
  const nodeIds = workflow.nodes.map(node => String(node.node_id || ''));
  if (nodeIds.some(nodeId => !nodeId) || !sameKeys(layout, nodeIds)) throw new Error('studio-workflow-layout-node-set-invalid');
  nodeIds.forEach(nodeId => {
    const position = layout[nodeId];
    if (!position || typeof position !== 'object' || Array.isArray(position) || !sameKeys(position, ['x', 'y']) || !Number.isFinite(position.x) || !Number.isFinite(position.y) || Math.abs(position.x) > 20000 || Math.abs(position.y) > 20000) {
      throw new Error('studio-workflow-layout-position-invalid');
    }
  });
}

function workflowLayoutArtifact(projectRoot, revision, workflow, recordSha256, definitionSha256) {
  const layoutFile = path.join(revision, 'editor-layout.json');
  const creationFile = path.join(revision, 'creation-receipt.json');
  if (!fs.existsSync(layoutFile)) {
    if (fs.existsSync(creationFile)) {
      const { value: creation } = readBoundedJson(creationFile);
      if (creation.schema_version === 'px.workflow-revision-receipt/1.2' || creation.editor_layout_state === 'content-bound') {
        throw new Error('studio-workflow-layout-missing');
      }
    }
    return { editor_layout_state: 'legacy-unavailable' };
  }
  if (!fs.existsSync(creationFile)) throw new Error('studio-workflow-creation-receipt-missing');
  const { value: envelope, raw } = readBoundedJson(layoutFile);
  if (!sameKeys(envelope, ['schema_version', 'workflow_id', 'version', 'revision_sha256', 'layout', 'layout_sha256']) || envelope.schema_version !== 'px.workflow-editor-layout/1.0' || envelope.workflow_id !== workflow.workflow_id || envelope.version !== workflow.version || envelope.revision_sha256 !== recordSha256 || !envelope.layout || typeof envelope.layout !== 'object' || Array.isArray(envelope.layout) || storedMemberSha256(raw, 'layout') !== envelope.layout_sha256) {
    throw new Error('studio-workflow-layout-envelope-invalid');
  }
  validateWorkflowEditorLayout(envelope.layout, workflow);
  const { value: creation } = readBoundedJson(creationFile);
  const expectedLayoutPath = relativePath(projectRoot, layoutFile);
  const expectedRecordPath = relativePath(projectRoot, path.join(revision, 'record.json'));
  const authorityFile = path.join(revision, 'authority-definition.json');
  const authorityPresent = fs.existsSync(authorityFile);
  const expectedAuthorityPath = authorityPresent ? relativePath(projectRoot, authorityFile) : null;
  const receiptKeys = [
    'schema_version', 'operation', 'created_utc', 'workflow_id', 'version',
    'revision_sha256', 'definition_sha256', 'definition_state', 'runnable_state',
    'run_state', 'path', 'created', 'authority_state',
    'authority_definition_path', 'editor_layout_state', 'editor_layout_path',
    'editor_layout_sha256', 'host_authority_retained'
  ];
  if (!sameKeys(creation, receiptKeys) || creation.schema_version !== 'px.workflow-revision-receipt/1.2' || creation.operation !== 'workflow.save_revision' || typeof creation.created_utc !== 'string' || !creation.created_utc || creation.workflow_id !== workflow.workflow_id || creation.version !== workflow.version || creation.revision_sha256 !== recordSha256 || creation.definition_sha256 !== definitionSha256 || creation.definition_state !== 'saved' || creation.runnable_state !== 'unvalidated' || creation.run_state !== 'never_run' || creation.path !== expectedRecordPath || creation.created !== true || creation.authority_state !== (authorityPresent ? 'defined' : 'none') || creation.authority_definition_path !== expectedAuthorityPath || creation.editor_layout_state !== 'content-bound' || creation.editor_layout_path !== expectedLayoutPath || creation.editor_layout_sha256 !== envelope.layout_sha256 || creation.host_authority_retained !== true) {
    throw new Error('studio-workflow-creation-receipt-mismatch');
  }
  return {
    editor_layout_state: 'content-bound',
    editor_layout: envelope.layout,
    editor_layout_sha256: envelope.layout_sha256
  };
}

function builderArtifacts(revision, spec, specSha256) {
  const files = {
    graph: path.join(revision, 'builder-graph.json'),
    layout: path.join(revision, 'editor-layout.json'),
    compiler: path.join(revision, 'builder-compiler-receipt.json')
  };
  const present = Object.values(files).map(file => fs.existsSync(file));
  if (!present.some(Boolean)) {
    const creationFile = path.join(revision, 'creation-receipt.json');
    if (fs.existsSync(creationFile)) {
      const { value: creation } = readBoundedJson(creationFile);
      if (creation.schema_version === 'px.agent-creation-receipt/1.1' || creation.builder_graph_state === 'content-bound') {
        throw new Error('studio-agent-builder-artifacts-missing');
      }
    }
    return { builder_graph_state: 'legacy-unavailable' };
  }
  if (!present.every(Boolean)) throw new Error('studio-agent-builder-artifacts-incomplete');

  const { value: graphEnvelope, raw: graphRaw } = readBoundedJson(files.graph);
  if (!sameKeys(graphEnvelope, ['schema_version', 'record', 'sha256']) || graphEnvelope.schema_version !== 'px.agent-builder-graph/1.0') {
    throw new Error('studio-agent-builder-graph-envelope-invalid');
  }
  const graph = graphEnvelope.record;
  if (!graph || typeof graph !== 'object' || Array.isArray(graph) || graph.schema_version !== graphEnvelope.schema_version || graph.agent_id !== spec.agent_id || storedMemberSha256(graphRaw, 'record') !== graphEnvelope.sha256) {
    throw new Error('studio-agent-builder-graph-identity-mismatch');
  }
  validateAgentBuilderGraph(graph, spec);

  const { value: layoutEnvelope, raw: layoutRaw } = readBoundedJson(files.layout);
  const layout = layoutEnvelope.layout;
  if (!sameKeys(layoutEnvelope, ['schema_version', 'graph_sha256', 'layout', 'layout_sha256']) || layoutEnvelope.schema_version !== 'px.agent-builder-layout/1.0' || layoutEnvelope.graph_sha256 !== graphEnvelope.sha256 || !layout || typeof layout !== 'object' || Array.isArray(layout) || storedMemberSha256(layoutRaw, 'layout') !== layoutEnvelope.layout_sha256) {
    throw new Error('studio-agent-builder-layout-invalid');
  }
  validateAgentBuilderLayout(layout, graph);

  const { value: compiler } = readBoundedJson(files.compiler);
  if (!sameKeys(compiler, ['schema_version', 'compiler', 'graph_sha256', 'layout_sha256', 'agent_spec_sha256', 'deterministic', 'authority_granted', 'host_authority_retained', 'receipt_sha256'])) {
    throw new Error('studio-agent-builder-compiler-receipt-invalid');
  }
  const receiptBody = { ...compiler }; delete receiptBody.receipt_sha256;
  if (compiler.schema_version !== 'px.agent-builder-compiler-receipt/1.0' || compiler.compiler !== 'runtime.agent_builder.compile_agent_builder_graph' || compiler.graph_sha256 !== graphEnvelope.sha256 || compiler.layout_sha256 !== layoutEnvelope.layout_sha256 || compiler.agent_spec_sha256 !== specSha256 || compiler.deterministic !== true || compiler.authority_granted !== false || compiler.host_authority_retained !== true || compiler.receipt_sha256 !== crypto.createHash('sha256').update(Buffer.from(canonicalJson(receiptBody), 'utf8')).digest('hex')) {
    throw new Error('studio-agent-builder-compiler-receipt-mismatch');
  }
  return {
    builder_graph_state: 'content-bound',
    builder_graph: graph,
    editor_layout: layout,
    builder_compiler_receipt: compiler
  };
}

function studioRecord(projectRoot, catalogKind, revision, recordFile, layout, authenticatedStatus) {
  const { value: envelope, stat, raw: recordRaw } = readBoundedJson(recordFile);
  const record = catalogKind === 'skills' ? envelope.manifest : envelope.record;
  if (!record || typeof record !== 'object' || Array.isArray(record)) throw new Error('studio-catalog-payload-invalid');
  const rawIdentity = record[layout.identity]; const rawVersion = record.version;
  const identity = String(rawIdentity || '').trim(); const version = String(rawVersion || '').trim();
  if (rawIdentity !== identity || rawVersion !== version || !STUDIO_IDENTITY.test(identity) || !validVersion(version) || path.basename(revision) !== version) throw new Error('studio-catalog-identity-invalid');
  const recordPath = relativePath(projectRoot, recordFile);
  const recordFileSha256 = crypto.createHash('sha256').update(Buffer.from(recordRaw, 'utf8')).digest('hex');
  const definitionSha256 = catalogKind === 'skills' ? String(envelope.manifest_sha256 || '') : storedMemberSha256(recordRaw, 'record');
  if (catalogKind !== 'skills' && envelope.sha256 !== definitionSha256) throw new Error('studio-record-hash-mismatch');
  const details = {
    ...record,
    catalog_kind: layout.kind,
    studio_revision: true,
    studio_record_path: recordPath,
    revision_sha256: catalogKind === 'skills' ? definitionSha256 : recordFileSha256,
    definition_sha256: definitionSha256,
    source_content_sha256: revisionTreeSha256(revision, projectRoot)
  };
  if (['agents', 'workflows'].includes(catalogKind)) {
    const authority = authorityDefinition(revision, catalogKind === 'agents' ? 'agent' : 'workflow', identity, version);
    if (authority) Object.assign(details, {
      bindings: authority.bindings || [], grants: authority.grants || [], executor_adapters: authority.executor_adapters || {},
      run_inputs: {}, run_input_contract: authority.run_input_contract || [], builder_domain: authority.builder_domain || 'px-standard',
      authority_definition_state: 'stored-with-revision', runtime_input_values_state: 'not-stored-by-design'
    });
    else details.authority_definition_state = 'not-stored-with-revision';
  }
  if (catalogKind === 'agents') {
    const specSha256 = definitionSha256;
    if (envelope.sha256 !== specSha256) throw new Error('studio-agent-record-hash-mismatch');
    Object.assign(details, builderArtifacts(revision, record, specSha256));
    const instructions = path.join(revision, 'instructions.md');
    try { details.instructions = readBoundedText(instructions); }
    catch (error) { if (error?.code !== 'ENOENT') throw error; }
  }
  if (catalogKind === 'workflows') {
    Object.assign(details, workflowLayoutArtifact(
      projectRoot, revision, record, recordFileSha256, definitionSha256
    ));
  }
  if (catalogKind === 'skills') {
    const payload = path.join(revision, String(envelope.payload_root || 'payload'));
    details.package_root = relativePath(projectRoot, payload);
    details.package_path = details.package_root;
    details.package_scope = 'project-studio';
    details.source_tree_sha256 = String(envelope.source_tree_sha256 || '');
  }
  const status = authenticatedStatus?.authenticated === true ? String(authenticatedStatus.status || 'candidate') : 'candidate';
  details.lifecycle_authentication = authenticatedStatus || { authenticated: false, reason: 'not verified by Python authority' };
  return {
    id: `studio:${identity}@${version}`,
    label: `${identity} @ ${version}`,
    kind: layout.kind,
    status,
    owner: record.owner || null,
    path: recordPath,
    summary: `Project Studio ${catalogKind.slice(0, -1)} revision; ${status}.`,
    effects: Array.isArray(record.effects) ? record.effects : [],
    tags: ['project-studio', 'immutable-revision'],
    risk: null,
    details,
    observed_mtime_ms: Number(stat.mtimeMs || 0)
  };
}

function collectStudioCatalog(projectRoot, catalogKind, authenticatedStatuses = {}) {
  const layout = KIND_LAYOUT[catalogKind];
  if (!layout || !projectRoot) return { items: [], fingerprint: 'none', refused: 0 };
  let root;
  try {
    root = fs.realpathSync.native(path.resolve(projectRoot));
  } catch {
    return { items: [], fingerprint: 'missing-project', refused: 0 };
  }
  const studios = path.join(root, '.engineering-bootstrap', 'studios', layout.directory);
  const items = []; const fingerprints = []; let refused = 0; let visited = 0; let truncated = false;
  for (const component of physicalDirectoryEntries(studios)) {
    const revisions = path.join(studios, component.name, 'revisions');
    for (const revisionEntry of physicalDirectoryEntries(revisions)) {
      visited += 1;
      if (visited > MAX_REVISIONS) { truncated = true; break; }
      const revision = path.join(revisions, revisionEntry.name); const recordFile = path.join(revision, layout.record);
      try {
        const relative = relativePath(root, recordFile);
        const item = studioRecord(root, catalogKind, revision, recordFile, layout, authenticatedStatuses[relative]);
        items.push(item); fingerprints.push([item.path, item.observed_mtime_ms, item.details.revision_sha256]);
      } catch {
        refused += 1;
      }
    }
    if (truncated) break;
  }
  items.sort((left, right) => right.observed_mtime_ms - left.observed_mtime_ms || left.id.localeCompare(right.id));
  return { items, fingerprint: crypto.createHash('sha256').update(JSON.stringify(fingerprints)).digest('hex'), refused, visited: Math.min(visited, MAX_REVISIONS), truncated };
}

function filterStudioItems(items, input = {}) {
  const query = String(input.query || '').trim().toLowerCase(); const status = String(input.status || '').trim().toLowerCase();
  const filtered = items.filter(item => {
    if (status && String(item.status).toLowerCase() !== status) return false;
    if (!query) return true;
    return [item.id, item.label, item.kind, item.status, item.owner, item.summary, item.details?.[item.kind === 'studio-agent-revision' ? 'agent_id' : item.kind === 'studio-workflow-revision' ? 'workflow_id' : 'skill_id'], item.details?.version]
      .some(value => String(value || '').toLowerCase().includes(query));
  });
  const key = ['id', 'label', 'status', 'kind'].includes(input.sort) ? input.sort : 'label';
  return filtered.sort((left, right) => String(left[key] || '').localeCompare(String(right[key] || '')) || left.id.localeCompare(right.id));
}

function normalizeSkillCatalogPage(page, kind) {
  if (!['skills', 'preserved-skills', 'microsoft-skills'].includes(kind)) return page;
  return { ...page, items: (page.items || []).map(item => {
    const details = { ...(item.details || {}) };
    const packagePath = kind === 'preserved-skills' ? details.backup : details.package_root;
    if (packagePath) details.package_path = packagePath;
    const bodyName = path.posix.basename(String(details.body || item.path || 'SKILL.md').replaceAll('\\', '/')) || 'SKILL.md';
    return { ...item, path: packagePath ? `${String(packagePath).replaceAll('\\', '/').replace(/\/$/, '')}/${bodyName}` : item.path, details };
  }) };
}

module.exports = { MAX_REVISIONS, collectStudioCatalog, filterStudioItems, normalizeSkillCatalogPage };
