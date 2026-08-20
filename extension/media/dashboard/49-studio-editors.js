'use strict';

(() => {
  const dashboard = globalThis.PXDashboard;
  if (!dashboard) throw new Error('PXDashboard foundation must load before Studio editors.');

  const clone = value => JSON.parse(JSON.stringify(value));
  const safeToken = value => String(value || '').trim().replace(/[^A-Za-z0-9_.:-]+/g, '-').replace(/^-+|-+$/g, '') || 'item';
  const tokens = value => String(value || '').toLowerCase().match(/[a-z0-9]+/g) || [];

  function editDistance(left, right) {
    const a = String(left || '').toLowerCase(); const b = String(right || '').toLowerCase();
    if (!a.length) return b.length;
    const row = Array.from({ length: b.length + 1 }, (_, index) => index);
    for (let i = 1; i <= a.length; i += 1) {
      let diagonal = row[0]; row[0] = i;
      for (let j = 1; j <= b.length; j += 1) {
        const above = row[j];
        row[j] = Math.min(row[j] + 1, row[j - 1] + 1, diagonal + (a[i - 1] === b[j - 1] ? 0 : 1));
        diagonal = above;
      }
    }
    return row[b.length];
  }

  function fuzzyScore(query, record) {
    const queryTokens = tokens(query);
    if (!queryTokens.length) return 0;
    const fields = [record?.title, record?.key, record?.id, record?.summary, record?.kind, record?.status, record?.domain, record?.provenance].filter(Boolean).map(value => String(value).toLowerCase());
    const fieldTokens = fields.flatMap(tokens);
    let score = 0;
    for (const queryToken of queryTokens) {
      let best = -20;
      for (const field of fields) {
        if (field === queryToken) best = Math.max(best, 120);
        else if (field.startsWith(queryToken)) best = Math.max(best, 80);
        else if (field.includes(queryToken)) best = Math.max(best, 55);
      }
      for (const candidate of fieldTokens) {
        const distance = editDistance(queryToken, candidate);
        const tolerance = queryToken.length >= 8 ? 2 : queryToken.length >= 4 ? 1 : 0;
        if (distance <= tolerance) best = Math.max(best, 38 - distance * 8);
      }
      score += best;
    }
    return score;
  }

  function rankGraph(query, records, limit = 8) {
    return (Array.isArray(records) ? records : []).map(record => ({ record, score: fuzzyScore(query, record) }))
      .filter(item => item.score > 0)
      .sort((left, right) => right.score - left.score || String(left.record?.title || left.record?.key).localeCompare(String(right.record?.title || right.record?.key)))
      .slice(0, Math.max(1, Math.min(20, Number(limit) || 8)));
  }

  function normalizePort(port, index, fallback = 'value') {
    return { name: safeToken(port?.name || `${fallback}-${index + 1}`), data_type: safeToken(port?.data_type || 'string'), required: port?.required !== false };
  }

  function finiteCoordinate(value, fallback) {
    const supplied = typeof value === 'number' || (typeof value === 'string' && value.trim() !== '');
    const coordinate = supplied ? Number(value) : Number.NaN;
    return Number.isFinite(coordinate) ? coordinate : fallback;
  }

  function normalizeNode(node, index, fallbackBindingId, fallbackGrantId) {
    const nodeId = safeToken(node?.node_id || `step:${index + 1}`);
    const kind = ['task', 'validation', 'approval', 'branch', 'join'].includes(node?.kind) ? node.kind : 'task';
    const inputs = (Array.isArray(node?.inputs) ? node.inputs : [{ name: 'value', data_type: 'string' }]).map((port, portIndex) => normalizePort(port, portIndex, 'input'));
    const outputs = (Array.isArray(node?.outputs) ? node.outputs : [{ name: 'value', data_type: 'string' }]).map((port, portIndex) => normalizePort(port, portIndex, 'output'));
    let config = node?.config && typeof node.config === 'object' && !Array.isArray(node.config) ? clone(node.config) : {};
    if (kind === 'validation' && (!Array.isArray(config.checks) || !config.checks.length)) config = { checks: [{ id: 'check:input-exists', source: 'inputs', port: inputs[0]?.name || 'value', operator: 'exists' }] };
    if (kind !== 'validation') config = {};
    return {
      node_id: nodeId,
      kind,
      config,
      executor_binding_id: safeToken(node?.executor_binding_id || fallbackBindingId),
      inputs,
      outputs,
      effect_grant_ids: (Array.isArray(node?.effect_grant_ids) ? node.effect_grant_ids : [fallbackGrantId]).filter(Boolean).map(safeToken),
      failure_policy: ['fail-closed', 'continue'].includes(node?.failure_policy) ? node.failure_policy : 'fail-closed',
      timeout_seconds: Math.max(1, Math.min(3600, Number(node?.timeout_seconds) || 30)),
      retry_limit: Math.max(0, Math.min(10, Number(node?.retry_limit) || 0)),
      approval_required: Boolean(node?.approval_required),
      position: {
        x: finiteCoordinate(node?.position?.x, 40 + (index % 3) * 250),
        y: finiteCoordinate(node?.position?.y, 40 + Math.floor(index / 3) * 150)
      }
    };
  }

  function normalizeWorkflowGrant(grant, index, workflowId) {
    return {
      ...clone(grant || {}),
      grant_id: safeToken(grant?.grant_id || `grant:${workflowId.replace(/^workflow:/, '') || index + 1}`),
      subject_id: workflowId,
      effects: (Array.isArray(grant?.effects) ? grant.effects : ['read']).map(safeToken),
      scope_roots: (Array.isArray(grant?.scope_roots) ? grant.scope_roots : ['workspace:current']).map(item => String(item).trim()).filter(Boolean),
      approved_by: String(grant?.approved_by || 'human:owner').trim(),
      evidence_refs: (Array.isArray(grant?.evidence_refs) ? grant.evidence_refs : ['receipt:human-approval']).map(item => String(item).trim()).filter(Boolean),
      expires_utc: grant?.expires_utc ? String(grant.expires_utc).trim() : null,
      state: String(grant?.state || 'admitted').trim().toLowerCase()
    };
  }

  function normalizeWorkflowBinding(binding, index, workflowId, fallbackGrantId) {
    return {
      ...clone(binding || {}),
      binding_id: safeToken(binding?.binding_id || `binding:${workflowId.replace(/^workflow:/, '') || index + 1}`),
      subject_kind: 'workflow', subject_id: workflowId,
      capability_id: safeToken(binding?.capability_id || 'capability:identity'),
      capability_version: String(binding?.capability_version || '1.0.0').trim().toLowerCase(),
      effect_grant_ids: (Array.isArray(binding?.effect_grant_ids) ? binding.effect_grant_ids : [fallbackGrantId]).filter(Boolean).map(safeToken),
      credential_namespace: binding?.credential_namespace ? String(binding.credential_namespace).trim() : null,
      cost_policy: String(binding?.cost_policy || 'non-billable').trim(),
      egress_policy: String(binding?.egress_policy || 'deny').trim(),
      state: String(binding?.state || 'admitted').trim().toLowerCase(),
      evidence_refs: (Array.isArray(binding?.evidence_refs) ? binding.evidence_refs : ['receipt:human-approval']).map(item => String(item).trim()).filter(Boolean)
    };
  }

  function normalizeWorkflow(seed = {}) {
    const workflowId = safeToken(seed.workflow_id || 'workflow:my-workflow').toLowerCase();
    const defaultGrantId = safeToken(`grant:${workflowId.replace(/^workflow:/, '')}`);
    const defaultBindingId = safeToken(`binding:${workflowId.replace(/^workflow:/, '')}`);
    const layout = seed.editor_layout && typeof seed.editor_layout === 'object' && !Array.isArray(seed.editor_layout) ? seed.editor_layout : {};
    const nodes = (Array.isArray(seed.nodes) && seed.nodes.length ? seed.nodes : [{ node_id: 'step:one' }]).map((node, index) => normalizeNode({ ...node, position: node?.position || layout[node?.node_id] }, index, defaultBindingId, defaultGrantId));
    const ids = new Set(nodes.map(node => node.node_id));
    const edges = (Array.isArray(seed.edges) ? seed.edges : []).map(edge => ({ ...edge,
      source_node: edge?.source_node || edge?.source_node_id,
      target_node: edge?.target_node || edge?.target_node_id
    })).filter(edge => ids.has(edge.source_node) && ids.has(edge.target_node)).map(edge => ({
      source_node: edge.source_node,
      source_port: safeToken(edge.source_port || 'value'),
      target_node: edge.target_node,
      target_port: safeToken(edge.target_port || 'value'),
      condition: String(edge.condition || 'always').trim() || 'always'
    }));
    const driven = new Set(edges.map(edge => `${edge.target_node}.${edge.target_port}`));
    const derivedContract = nodes.flatMap(node => node.inputs
      .filter(port => !driven.has(`${node.node_id}.${port.name}`))
      .map(port => ({ key: `${node.node_id}.${port.name}`, value_type: port.data_type, required: port.required !== false })));
    const suppliedContract = Array.isArray(seed.run_input_contract) ? seed.run_input_contract : [];
    const runInputContract = derivedContract.map(item => {
      const supplied = suppliedContract.find(row => row?.key === item.key);
      return supplied ? { ...item, required: supplied.required !== false } : item;
    });
    const runInputs = seed.run_inputs && typeof seed.run_inputs === 'object' && !Array.isArray(seed.run_inputs) ? clone(seed.run_inputs) : {};
    const authorityUnavailable = seed.authority_definition_state === 'not-stored-with-revision';
    const suppliedGrants = Array.isArray(seed.grants) && seed.grants.length ? seed.grants : authorityUnavailable ? [] : [{}];
    const grants = suppliedGrants.map((grant, index) => normalizeWorkflowGrant(grant, index, workflowId));
    const suppliedBindings = Array.isArray(seed.bindings) && seed.bindings.length ? seed.bindings : authorityUnavailable ? [] : [{}];
    const bindings = suppliedBindings.map((binding, index) => normalizeWorkflowBinding(binding, index, workflowId, grants[0]?.grant_id));
    const adaptersSupplied = seed.executor_adapters && typeof seed.executor_adapters === 'object' && !Array.isArray(seed.executor_adapters);
    const executorAdapters = adaptersSupplied ? clone(seed.executor_adapters) : Object.fromEntries(bindings.map(binding => [binding.binding_id, 'identity']));
    const editorLayout = Object.fromEntries(nodes.map(node => [node.node_id, { x: node.position.x, y: node.position.y }]));
    return { ...clone(seed), workflow_id: workflowId, version: String(seed.version || '1.0.0').trim().toLowerCase(), owner: String(seed.owner || 'human:owner'), nodes, edges, grants, bindings, executor_adapters: executorAdapters, run_inputs: runInputs, run_input_contract: runInputContract, editor_layout: editorLayout, lifecycle: 'draft' };
  }

  function validateWorkflow(draft) {
    const issues = []; const ids = new Set(); const allowedTypes = new Set(['json', 'string', 'integer', 'number', 'boolean', 'object', 'array']);
    const allowedAdapters = new Set(['identity', 'increment', 'double', 'sleep', 'fail']);
    if (!IDENTITY_PATTERN.test(String(draft?.workflow_id || ''))) issues.push('Workflow ID must be a lowercase PX identity.');
    if (!validStudioVersion(draft?.version)) issues.push('Version must be a bounded semantic PX version.');
    if (draft?.authority_definition_state === 'not-stored-with-revision') issues.push('The persisted revision does not contain its original grants, bindings, executor adapters, or run inputs. Supply explicit governed definitions before saving a new revision.');
    const grants = Array.isArray(draft?.grants) ? draft.grants : []; const bindings = Array.isArray(draft?.bindings) ? draft.bindings : [];
    const grantIdentityList = grants.map(grant => grant?.grant_id).filter(Boolean); const bindingIdentityList = bindings.map(binding => binding?.binding_id).filter(Boolean);
    const grantIds = new Set(grantIdentityList); const bindingIds = new Set(bindingIdentityList);
    if (!grants.length) issues.push('Workflow authority requires at least one effect grant definition.');
    if (!bindings.length) issues.push('Workflow authority requires at least one capability binding definition.');
    if (grantIds.size !== grants.length) issues.push('Workflow effect grant IDs must be present and unique.');
    if (bindingIds.size !== bindings.length) issues.push('Workflow binding IDs must be present and unique.');
    for (const grant of grants) {
      if (grant?.subject_id !== draft?.workflow_id) issues.push(`${grant?.grant_id || 'Grant'} subject must match the workflow ID.`);
      if (!Array.isArray(grant?.effects) || !grant.effects.length || !Array.isArray(grant?.scope_roots) || !grant.scope_roots.length) issues.push(`${grant?.grant_id || 'Grant'} requires effects and bounded scope roots.`);
      if (!String(grant?.approved_by || '').trim() || !Array.isArray(grant?.evidence_refs) || !grant.evidence_refs.length) issues.push(`${grant?.grant_id || 'Grant'} requires an approver and evidence references.`);
      if (grant?.state !== 'admitted') issues.push(`${grant?.grant_id || 'Grant'} must be admitted before authority registration.`);
    }
    for (const binding of bindings) {
      if (binding?.subject_kind !== 'workflow' || binding?.subject_id !== draft?.workflow_id) issues.push(`${binding?.binding_id || 'Binding'} must target this workflow.`);
      if (!Array.isArray(binding?.effect_grant_ids) || !binding.effect_grant_ids.length || binding.effect_grant_ids.some(id => !grantIds.has(id))) issues.push(`${binding?.binding_id || 'Binding'} references an undeclared grant.`);
      if (!String(binding?.cost_policy || '').trim() || !String(binding?.egress_policy || '').trim() || !Array.isArray(binding?.evidence_refs) || !binding.evidence_refs.length) issues.push(`${binding?.binding_id || 'Binding'} requires cost, egress, and evidence policy.`);
      if (binding?.state !== 'admitted') issues.push(`${binding?.binding_id || 'Binding'} must be admitted before authority registration.`);
    }
    const referencedGrantIds = new Set(bindings.flatMap(binding => Array.isArray(binding?.effect_grant_ids) ? binding.effect_grant_ids : []));
    for (const grantId of grantIds) if (!referencedGrantIds.has(grantId)) issues.push(`${grantId} is not referenced by any workflow binding.`);
    const adapters = draft?.executor_adapters && typeof draft.executor_adapters === 'object' && !Array.isArray(draft.executor_adapters) ? draft.executor_adapters : null;
    if (!adapters) issues.push('Workflow executor adapters must be an object.');
    else {
      for (const bindingId of bindingIds) if (!allowedAdapters.has(adapters[bindingId])) issues.push(`${bindingId} requires one closed executor adapter.`);
      for (const adapterBindingId of Object.keys(adapters)) if (!bindingIds.has(adapterBindingId)) issues.push(`Executor adapter references unknown binding ${adapterBindingId}.`);
    }
    if (!draft?.run_inputs || typeof draft.run_inputs !== 'object' || Array.isArray(draft.run_inputs)) issues.push('Workflow run inputs must be an object. Values are supplied per run and are not retained with the revision.');
    for (const node of draft?.nodes || []) {
      if (!node.node_id || ids.has(node.node_id)) issues.push(`Node identity must be present and unique: ${node.node_id || '(blank)'}.`);
      ids.add(node.node_id);
      for (const direction of ['inputs', 'outputs']) {
        const names = new Set();
        for (const port of node[direction] || []) {
          if (!port.name || names.has(port.name)) issues.push(`${node.node_id} has a blank or duplicate ${direction} port.`);
          if (!allowedTypes.has(port.data_type)) issues.push(`${node.node_id}.${port.name || '(blank)'} has unsupported type ${port.data_type || '(blank)'}.`);
          names.add(port.name);
        }
        if (!names.size) issues.push(`${node.node_id} requires at least one ${direction} port.`);
      }
      if (!node.executor_binding_id) issues.push(`${node.node_id} requires an executor binding.`);
      else if (!bindingIds.has(node.executor_binding_id)) issues.push(`${node.node_id} references undeclared binding ${node.executor_binding_id}.`);
      else if (!adapters?.[node.executor_binding_id]) issues.push(`${node.node_id} binding ${node.executor_binding_id} has no executor adapter.`);
      if (!['task', 'validation', 'approval', 'branch', 'join'].includes(node.kind)) issues.push(`${node.node_id} has an unsupported node kind.`);
      if (node.kind === 'approval' && !node.approval_required) issues.push(`${node.node_id} is an approval node and must require governed approval.`);
      if (node.kind !== 'validation' && Object.keys(node.config || {}).length) issues.push(`${node.node_id} ${node.kind} configuration is closed and must be empty.`);
      if (node.kind === 'validation') {
        const checks = node.config?.checks;
        if (!Array.isArray(checks) || !checks.length || checks.length > 64) issues.push(`${node.node_id} validation configuration requires 1–64 checks.`);
        else for (const check of checks) {
          if (!check?.id || !['inputs', 'outputs'].includes(check.source) || !check.port || !['exists', 'truthy', 'falsy', 'equals', 'not-equals', 'type', 'greater-than-or-equal', 'less-than-or-equal', 'contains'].includes(check.operator)) issues.push(`${node.node_id} contains an invalid validation check.`);
          const ports = check?.source === 'outputs' ? node.outputs : node.inputs;
          if (check?.port && !ports.some(port => port.name === check.port)) issues.push(`${node.node_id} validation check ${check.id || '(unnamed)'} references missing ${check.source || 'unknown'} port ${check.port}.`);
        }
        if (node.failure_policy !== 'fail-closed') issues.push(`${node.node_id} validation nodes must fail closed.`);
      }
      try { if (JSON.stringify(node.config || {}).length > 16384) issues.push(`${node.node_id} configuration exceeds 16384 bytes.`); } catch { issues.push(`${node.node_id} configuration must be canonical JSON.`); }
    }
    for (const edge of draft?.edges || []) if (!ids.has(edge.source_node) || !ids.has(edge.target_node)) issues.push('An edge refers to a missing node.');
    const edgeKeys = new Set();
    for (const edge of draft?.edges || []) {
      const source = (draft.nodes || []).find(node => node.node_id === edge.source_node); const target = (draft.nodes || []).find(node => node.node_id === edge.target_node);
      const sourcePort = source?.outputs?.find(port => port.name === edge.source_port); const targetPort = target?.inputs?.find(port => port.name === edge.target_port);
      if (!sourcePort || !targetPort) issues.push(`${edge.source_node}.${edge.source_port} → ${edge.target_node}.${edge.target_port} must reference existing output and input ports.`);
      else if (sourcePort.data_type !== targetPort.data_type) issues.push(`${edge.source_node}.${edge.source_port} (${sourcePort.data_type}) is incompatible with ${edge.target_node}.${edge.target_port} (${targetPort.data_type}).`);
      const edgeKey = `${edge.source_node}:${edge.source_port}>${edge.target_node}:${edge.target_port}`;
      if (edgeKeys.has(edgeKey)) issues.push(`Duplicate edge: ${edgeKey}.`); edgeKeys.add(edgeKey);
      if (!['always', 'never', 'source-present', 'source-truthy', 'source-falsy'].includes(edge.condition)) issues.push(`${edgeKey} has an unsupported condition.`);
    }
    for (const node of draft?.nodes || []) {
      const outgoing = (draft.edges || []).filter(edge => edge.source_node === node.node_id);
      const incoming = (draft.edges || []).filter(edge => edge.target_node === node.node_id);
      if (node.kind === 'branch') {
        const binary = node.outputs.some(port => port.data_type === 'boolean' && ['source-truthy', 'source-falsy'].every(condition => outgoing.some(edge => edge.source_port === port.name && edge.condition === condition)));
        if (!binary) issues.push(`${node.node_id} branch requires source-truthy and source-falsy edges from one boolean output.`);
      }
      if (node.kind === 'join' && incoming.length < 2) issues.push(`${node.node_id} join requires at least two incoming edges.`);
    }
    const drivenInputs = new Set();
    for (const edge of draft?.edges || []) { const key = `${edge.target_node}:${edge.target_port}`; if (drivenInputs.has(key)) issues.push(`Multiple edges drive ${key}.`); drivenInputs.add(key); }
    const adjacency = new Map([...(draft?.nodes || [])].map(node => [node.node_id, []])); const indegree = new Map([...(draft?.nodes || [])].map(node => [node.node_id, 0]));
    for (const edge of draft?.edges || []) if (adjacency.has(edge.source_node) && indegree.has(edge.target_node)) { adjacency.get(edge.source_node).push(edge.target_node); indegree.set(edge.target_node, indegree.get(edge.target_node) + 1); }
    const ready = [...indegree].filter(([, count]) => count === 0).map(([id]) => id); let visited = 0;
    while (ready.length) { const current = ready.pop(); visited += 1; for (const target of adjacency.get(current) || []) { indegree.set(target, indegree.get(target) - 1); if (indegree.get(target) === 0) ready.push(target); } }
    if (visited !== (draft?.nodes || []).length) issues.push('Workflow graph contains a cycle.');
    for (const node of draft?.nodes || []) {
      if (!(node.timeout_seconds > 0 && node.timeout_seconds <= 3600)) issues.push(`${node.node_id} timeout must be between 1 and 3600 seconds.`);
      if (!['fail-closed', 'continue'].includes(node.failure_policy)) issues.push(`${node.node_id} has an unsupported failure policy.`);
      if (!Array.isArray(node.effect_grant_ids) || !node.effect_grant_ids.length) issues.push(`${node.node_id} requires at least one effect grant.`);
      else if (node.effect_grant_ids.some(id => !grantIds.has(id))) issues.push(`${node.node_id} references an undeclared effect grant.`);
    }
    return { valid: issues.length === 0, issues };
  }

  const IDENTITY_PATTERN = /^[a-z0-9][a-z0-9._:-]{1,127}$/;
  // Identical to runtime.studio_models.CANONICAL_VERSION: trim + lowercase,
  // bounded core integers, and a <=64 character dot-delimited suffix whose
  // identifiers begin and end with ASCII alphanumerics.
  const VERSION_PATTERN = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:[-.]([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*))?$/;
  const CANONICAL_UTC_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/;
  const MAX_VERSION_COMPONENT = 2147483647n;
  function validStudioVersion(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (!normalized || value !== normalized || normalized.length > 96) return false;
    const match = VERSION_PATTERN.exec(normalized);
    if (!match) return false;
    if (match[4]?.length > 64) return false;
    if (match[4]?.split('.').some(part => /^0[0-9]+$/.test(part))) return false;
    try { return [match[1], match[2], match[3]].every(item => BigInt(item) <= MAX_VERSION_COMPONENT); }
    catch { return false; }
  }
  function validCanonicalUtc(value) {
    if (typeof value !== 'string' || !CANONICAL_UTC_PATTERN.test(value) || value.startsWith('0000-')) return false;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return false;
    const canonical = parsed.toISOString();
    return value === canonical || value === canonical.replace('.000Z', 'Z');
  }
  const LIFECYCLE_STATES = new Set(['draft', 'candidate', 'tested', 'admitted', 'deprecated', 'retired', 'rejected']);
  const RESTRICTED_CAPABILITY_PREFIX = /^(?:enterprise|microsoft|ms|azure|m365|dynamics)[.:/-]/i;
  const stringList = (value, fallback = []) => (Array.isArray(value) ? value : fallback).map(item => String(item).trim()).filter(Boolean);
  const identity = (value, fallback) => String(value || fallback).trim().toLowerCase();
  const AGENT_GRAPH_SCHEMA = 'px.agent-builder-graph/1.0';
  const AGENT_NODE_ORDER = ['identity', 'behavior', 'model', 'harness', 'capabilities', 'tools', 'handoffs', 'memory', 'contracts', 'authority', 'tests', 'candidate'];
  const AGENT_OPTIONAL_NODES = new Set(['tools', 'handoffs', 'memory']);
  const AGENT_OPTIONAL_NODE_FIELDS = Object.freeze({ tools: 'tool_binding_ids', handoffs: 'handoff_agent_ids', memory: 'memory_binding_ids' });
  const AGENT_CONFIG_KEYS = Object.freeze({
    identity: ['agent_id', 'version', 'project_id', 'owner'], behavior: ['instruction_sha256'], model: ['model'], harness: ['harness_id'],
    capabilities: ['binding_ids'], tools: ['binding_ids'], handoffs: ['agent_ids'], memory: ['binding_ids'],
    contracts: ['input_schema', 'output_schema'], authority: ['grant_ids'], tests: ['test_ids'], candidate: ['lifecycle']
  });
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
  const AGENT_EDGES = Object.freeze([
    ['agent-edge:b1e49b51df89541fc360', 'identity', 'out:definition', 'behavior', 'in:definition', 'owns'],
    ['agent-edge:70af5a1a109ee4100b51', 'behavior', 'out:definition', 'model', 'in:definition', 'prompts'],
    ['agent-edge:fd953ff0c30450ab77a3', 'model', 'out:model-route', 'harness', 'in:model-route', 'routes'],
    ['agent-edge:58e8d2a708f837f177d4', 'harness', 'out:capability', 'capabilities', 'in:capability', 'requests'],
    ['agent-edge:61a5c94f6cdf9e0120b3', 'behavior', 'out:definition', 'contracts', 'in:definition', 'defines'],
    ['agent-edge:a85e3c5b355ed3abf207', 'capabilities', 'out:authority', 'authority', 'in:authority', 'authorizes'],
    ['agent-edge:bbe2a3cb69e9a24b6465', 'contracts', 'out:contract', 'tests', 'in:contract', 'constrains'],
    ['agent-edge:e2e20836297afb1f31b5', 'authority', 'out:validation', 'tests', 'in:validation', 'validates'],
    ['agent-edge:aa58aec0563f64626f3d', 'tests', 'out:candidate', 'candidate', 'in:candidate', 'produces'],
    ['agent-edge:4151bf6f83dfc2fdbfad', 'capabilities', 'out:capability', 'tools', 'in:capability', 'binds'],
    ['agent-edge:270c8659b5d2b128b1c4', 'tools', 'out:authority', 'authority', 'in:authority', 'authorizes'],
    ['agent-edge:784edb7ae0afab32337b', 'capabilities', 'out:capability', 'handoffs', 'in:capability', 'hands-off'],
    ['agent-edge:4c68b4f7645f7d27a338', 'handoffs', 'out:authority', 'authority', 'in:authority', 'authorizes'],
    ['agent-edge:a1456d577d81eb739e1a', 'behavior', 'out:definition', 'memory', 'in:definition', 'retrieves'],
    ['agent-edge:c9b8ed9f26d1356498c1', 'memory', 'out:authority', 'authority', 'in:authority', 'authorizes']
  ]);
  const agentPorts = kind => AGENT_PORTS[kind].map(([port_id, direction, data_type]) => ({ port_id, direction, data_type }));

  function sha256Utf8(value) {
    const bytes = [];
    for (const character of String(value ?? '')) {
      const point = character.codePointAt(0);
      if (point < 0x80) bytes.push(point);
      else if (point < 0x800) bytes.push(0xc0 | (point >>> 6), 0x80 | (point & 0x3f));
      else if (point < 0x10000) bytes.push(0xe0 | (point >>> 12), 0x80 | ((point >>> 6) & 0x3f), 0x80 | (point & 0x3f));
      else bytes.push(0xf0 | (point >>> 18), 0x80 | ((point >>> 12) & 0x3f), 0x80 | ((point >>> 6) & 0x3f), 0x80 | (point & 0x3f));
    }
    const bitLength = bytes.length * 8;
    bytes.push(0x80);
    while (bytes.length % 64 !== 56) bytes.push(0);
    const high = Math.floor(bitLength / 0x100000000); const low = bitLength >>> 0;
    for (let shift = 24; shift >= 0; shift -= 8) bytes.push((high >>> shift) & 0xff);
    for (let shift = 24; shift >= 0; shift -= 8) bytes.push((low >>> shift) & 0xff);
    const words = new Uint32Array(64);
    const state = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    const constants = new Uint32Array([0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
    const rotate = (word, count) => (word >>> count) | (word << (32 - count));
    for (let offset = 0; offset < bytes.length; offset += 64) {
      for (let index = 0; index < 16; index += 1) words[index] = ((bytes[offset + index * 4] << 24) | (bytes[offset + index * 4 + 1] << 16) | (bytes[offset + index * 4 + 2] << 8) | bytes[offset + index * 4 + 3]) >>> 0;
      for (let index = 16; index < 64; index += 1) { const a = words[index - 15]; const b = words[index - 2]; const s0 = rotate(a, 7) ^ rotate(a, 18) ^ (a >>> 3); const s1 = rotate(b, 17) ^ rotate(b, 19) ^ (b >>> 10); words[index] = (words[index - 16] + s0 + words[index - 7] + s1) >>> 0; }
      let [a, b, c, d, e, f, g, h] = state;
      for (let index = 0; index < 64; index += 1) { const s1 = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25); const choice = (e & f) ^ (~e & g); const t1 = (h + s1 + choice + constants[index] + words[index]) >>> 0; const s0 = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22); const majority = (a & b) ^ (a & c) ^ (b & c); const t2 = (s0 + majority) >>> 0; h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0; }
      state[0] = (state[0] + a) >>> 0; state[1] = (state[1] + b) >>> 0; state[2] = (state[2] + c) >>> 0; state[3] = (state[3] + d) >>> 0; state[4] = (state[4] + e) >>> 0; state[5] = (state[5] + f) >>> 0; state[6] = (state[6] + g) >>> 0; state[7] = (state[7] + h) >>> 0;
    }
    return [...state].map(word => word.toString(16).padStart(8, '0')).join('');
  }

  function agentSpecProjection(draft = {}) {
    return {
      agent_id: draft.agent_id, version: draft.version, project_id: draft.project_id, owner: draft.owner,
      harness_id: draft.harness_id, instructions: draft.instructions, capability_binding_ids: stringList(draft.capability_binding_ids),
      effect_grant_ids: stringList(draft.effect_grant_ids), required_tests: stringList(draft.required_tests), model: clone(draft.model || {}),
      tool_binding_ids: stringList(draft.tool_binding_ids), memory_binding_ids: stringList(draft.memory_binding_ids), handoff_agent_ids: stringList(draft.handoff_agent_ids),
      input_schema: clone(draft.input_schema || {}), output_schema: clone(draft.output_schema || {}), lifecycle: draft.lifecycle
    };
  }

  function projectAgentBuilderGraph(draft, instructionSha256 = sha256Utf8(draft?.instructions || ''), requestedKinds = null) {
    const configs = {
      identity: { agent_id: draft.agent_id, version: draft.version, project_id: draft.project_id, owner: draft.owner },
      behavior: { instruction_sha256: instructionSha256 }, model: { model: clone(draft.model || {}) }, harness: { harness_id: draft.harness_id },
      capabilities: { binding_ids: stringList(draft.capability_binding_ids) }, tools: { binding_ids: stringList(draft.tool_binding_ids) },
      handoffs: { agent_ids: stringList(draft.handoff_agent_ids) }, memory: { binding_ids: stringList(draft.memory_binding_ids) },
      contracts: { input_schema: clone(draft.input_schema || {}), output_schema: clone(draft.output_schema || {}) }, authority: { grant_ids: stringList(draft.effect_grant_ids) },
      tests: { test_ids: stringList(draft.required_tests) }, candidate: { lifecycle: draft.lifecycle }
    };
    const requested = new Set(Array.isArray(requestedKinds) ? requestedKinds : []);
    const kinds = AGENT_NODE_ORDER.filter(kind => !AGENT_OPTIONAL_NODES.has(kind) || requested.has(kind) || Object.values(configs[kind])[0].length);
    const kindSet = new Set(kinds);
    const nodes = kinds.map(kind => ({ node_id: `agent-node:${kind}`, kind, ports: agentPorts(kind), config: configs[kind] }));
    const edges = AGENT_EDGES.filter(([, source, , target]) => kindSet.has(source) && kindSet.has(target)).map(([edge_id, source, source_port, target, target_port, relation]) => ({ edge_id, source_node: `agent-node:${source}`, source_port, target_node: `agent-node:${target}`, target_port, relation })).sort((left, right) => left.edge_id.localeCompare(right.edge_id));
    return { schema_version: AGENT_GRAPH_SCHEMA, agent_id: draft.agent_id, nodes, edges };
  }

  function validateAgentBuilderGraph(graph) {
    const issues = [];
    if (!graph || typeof graph !== 'object' || Array.isArray(graph)) return { valid: false, issues: ['Builder graph is unavailable.'] };
    if (graph.schema_version !== AGENT_GRAPH_SCHEMA) issues.push('Builder graph schema is unsupported.');
    const nodes = Array.isArray(graph.nodes) ? graph.nodes : []; const kinds = nodes.map(node => node?.kind);
    if (nodes.some((node, index) => node?.node_id !== `agent-node:${node?.kind}` || node?.kind !== AGENT_NODE_ORDER.filter(kind => kinds.includes(kind))[index])) issues.push('Builder nodes do not use canonical identities and order.');
    for (const kind of AGENT_NODE_ORDER.filter(item => !AGENT_OPTIONAL_NODES.has(item))) if (!kinds.includes(kind)) issues.push(`Builder graph is missing ${kind}.`);
    for (const node of nodes) {
      if (!AGENT_PORTS[node?.kind] || JSON.stringify(node.ports) !== JSON.stringify(agentPorts(node.kind))) issues.push(`${node?.node_id || 'Builder node'} ports do not match the closed contract.`);
      if (!node?.config || Array.isArray(node.config) || JSON.stringify(Object.keys(node.config).sort()) !== JSON.stringify([...(AGENT_CONFIG_KEYS[node?.kind] || [])].sort())) issues.push(`${node?.node_id || 'Builder node'} config does not match the closed contract.`);
    }
    const projectedEdges = AGENT_EDGES.filter(([, source, , target]) => kinds.includes(source) && kinds.includes(target)).map(([edge_id, source, source_port, target, target_port, relation]) => ({ edge_id, source_node: `agent-node:${source}`, source_port, target_node: `agent-node:${target}`, target_port, relation })).sort((left, right) => left.edge_id.localeCompare(right.edge_id));
    if (JSON.stringify(graph.edges || []) !== JSON.stringify(projectedEdges)) issues.push('Builder edges do not match the closed executable topology.');
    if (graph.agent_id !== nodes.find(node => node.kind === 'identity')?.config?.agent_id) issues.push('Builder graph identity is inconsistent.');
    return { valid: issues.length === 0, issues };
  }

  function normalizeAgentBuilderWorkingGraph(draft, graph = null) {
    if (!graph || typeof graph !== 'object' || Array.isArray(graph)) return projectAgentBuilderGraph(draft);
    const rawNodes = Array.isArray(graph.nodes) ? graph.nodes : [];
    const rawKinds = rawNodes.map(node => String(node?.kind || '').trim().toLowerCase());
    const requiredKinds = AGENT_NODE_ORDER.filter(kind => !AGENT_OPTIONAL_NODES.has(kind));
    const kindsAreUsable = rawKinds.length === new Set(rawKinds).size
      && rawKinds.every(kind => AGENT_NODE_ORDER.includes(kind))
      && requiredKinds.every(kind => rawKinds.includes(kind));
    const projected = projectAgentBuilderGraph(
      draft,
      sha256Utf8(draft?.instructions || ''),
      kindsAreUsable ? rawKinds : null
    );
    if (!Array.isArray(graph.edges)) return { ...projected, edges: [] };
    const edges = graph.edges.map(edge => ({
      edge_id: String(edge?.edge_id || '').trim().toLowerCase(),
      source_node: String(edge?.source_node || '').trim().toLowerCase(),
      source_port: String(edge?.source_port || '').trim().toLowerCase(),
      target_node: String(edge?.target_node || '').trim().toLowerCase(),
      target_port: String(edge?.target_port || '').trim().toLowerCase(),
      relation: String(edge?.relation || '').trim().toLowerCase()
    })).sort((left, right) => left.edge_id.localeCompare(right.edge_id));
    return { ...projected, edges };
  }

  function synchronizeAgentBuilderGraph(draft, graph = null) {
    return normalizeAgentBuilderWorkingGraph(draft, graph);
  }

  function editAgentBuilderEdge(draft, graph, operation = {}) {
    const current = normalizeAgentBuilderWorkingGraph(draft, graph);
    const expected = projectAgentBuilderGraph(
      draft,
      sha256Utf8(draft?.instructions || ''),
      current.nodes.map(node => node.kind)
    );
    const nextEdges = current.edges.map(edge => clone(edge));
    if (operation.type === 'remove') {
      const index = nextEdges.findIndex(edge => edge.edge_id === operation.edge_id);
      if (index < 0) throw new Error('The selected AgentSpec connection is no longer present.');
      nextEdges.splice(index, 1);
    } else if (operation.type === 'add') {
      const candidate = expected.edges.find(edge =>
        edge.source_node === operation.source_node
        && edge.source_port === operation.source_port
        && edge.target_node === operation.target_node
        && edge.target_port === operation.target_port
      );
      if (!candidate) throw new Error('The selected ports do not form an admitted AgentSpec connection.');
      if (nextEdges.some(edge => edge.edge_id === candidate.edge_id)) throw new Error('The selected AgentSpec connection already exists.');
      nextEdges.push(clone(candidate));
    } else throw new Error('Unsupported AgentSpec connection edit.');
    nextEdges.sort((left, right) => left.edge_id.localeCompare(right.edge_id));
    return { ...current, edges: nextEdges };
  }

  function editAgentBuilderNode(draft, graph, operation = {}) {
    const nextDraft = clone(draft || {}); const current = synchronizeAgentBuilderGraph(nextDraft, graph);
    const kinds = new Set(current.nodes.map(node => node.kind));
    const source = current.nodes.find(node => node.node_id === operation.node_id); const targetKind = String(operation.kind || '').trim().toLowerCase();
    if (operation.type === 'add') {
      if (!AGENT_OPTIONAL_NODES.has(targetKind) || kinds.has(targetKind)) throw new Error('Only one missing optional AgentSpec node can be added.');
      kinds.add(targetKind);
    } else if (operation.type === 'remove') {
      if (!source || !AGENT_OPTIONAL_NODES.has(source.kind)) throw new Error('Required AgentSpec nodes cannot be removed.');
      nextDraft[AGENT_OPTIONAL_NODE_FIELDS[source.kind]] = []; kinds.delete(source.kind);
    } else if (operation.type === 'retype') {
      if (!source || !AGENT_OPTIONAL_NODES.has(source.kind)) throw new Error('Only optional AgentSpec nodes can be retyped.');
      if (!AGENT_OPTIONAL_NODES.has(targetKind) || (kinds.has(targetKind) && targetKind !== source.kind)) throw new Error('The replacement AgentSpec node kind is unavailable.');
      if (targetKind === source.kind) return { draft: nextDraft, graph: current, selected_node_id: source.node_id };
      nextDraft[AGENT_OPTIONAL_NODE_FIELDS[source.kind]] = []; kinds.delete(source.kind); kinds.add(targetKind);
    } else throw new Error('Unsupported AgentSpec node edit.');
    const nextGraph = projectAgentBuilderGraph(nextDraft, sha256Utf8(nextDraft.instructions || ''), [...kinds]);
    const selectedKind = operation.type === 'remove' ? 'capabilities' : targetKind; const selectedNodeId = `agent-node:${selectedKind}`;
    const layout = nextDraft.editor_layout?.layout && typeof nextDraft.editor_layout.layout === 'object' ? nextDraft.editor_layout.layout : nextDraft.editor_layout;
    const nextLayout = layout && typeof layout === 'object' && !Array.isArray(layout) ? clone(layout) : {};
    if (source && operation.type === 'retype' && nextLayout[source.node_id]) nextLayout[selectedNodeId] = nextLayout[source.node_id];
    if (source && operation.type !== 'add') delete nextLayout[source.node_id];
    nextDraft.editor_layout = Object.fromEntries(nextGraph.nodes.map(node => [node.node_id, clone(nextLayout[node.node_id] || {})]));
    nextDraft.builder_graph = clone(nextGraph);
    return { draft: nextDraft, graph: nextGraph, selected_node_id: selectedNodeId };
  }

  function agentCandidatePayload(draft, layout, graph = null) {
    const spec = agentSpecProjection(draft);
    const synchronized = synchronizeAgentBuilderGraph(spec, graph || draft?.builder_graph);
    return { ...spec, grants: clone(draft.grants || []), bindings: clone(draft.bindings || []), builder_domain: 'px-standard', builder_graph: clone(synchronized), editor_layout: clone(layout || {}) };
  }

  function normalizeGrant(grant, index, agentId) {
    const grantId = identity(grant?.grant_id, `grant:${agentId.replace(/^agent:/, '') || index + 1}`);
    return {
      ...clone(grant || {}), grant_id: grantId, subject_id: agentId,
      effects: stringList(grant?.effects, ['read']), scope_roots: stringList(grant?.scope_roots, ['workspace:current']),
      approved_by: String(grant?.approved_by || 'human:owner').trim(), evidence_refs: stringList(grant?.evidence_refs, ['receipt:human-approval']),
      expires_utc: grant?.expires_utc ? String(grant.expires_utc).trim() : null,
      state: LIFECYCLE_STATES.has(grant?.state) ? grant.state : 'candidate'
    };
  }

  function normalizeBinding(binding, index, agentId, fallbackGrantId) {
    const bindingId = identity(binding?.binding_id, `binding:${agentId.replace(/^agent:/, '') || index + 1}`);
    return {
      ...clone(binding || {}), binding_id: bindingId, subject_kind: 'agent', subject_id: agentId,
      capability_id: identity(binding?.capability_id, 'capability:local-worker'), capability_version: String(binding?.capability_version || '1.0.0').trim().toLowerCase(),
      effect_grant_ids: stringList(binding?.effect_grant_ids, fallbackGrantId ? [fallbackGrantId] : []),
      credential_namespace: binding?.credential_namespace ? String(binding.credential_namespace).trim() : null,
      cost_policy: String(binding?.cost_policy || 'non-billable').trim(), egress_policy: String(binding?.egress_policy || 'deny').trim(),
      state: LIFECYCLE_STATES.has(binding?.state) ? binding.state : 'candidate', evidence_refs: stringList(binding?.evidence_refs, ['receipt:human-approval'])
    };
  }

  function normalizeAgent(seed = {}) {
    const agentId = identity(seed.agent_id, 'agent:my-agent');
    const authorityUnavailable = seed.authority_definition_state === 'not-stored-with-revision';
    const suppliedGrants = Array.isArray(seed.grants) && seed.grants.length ? seed.grants : authorityUnavailable ? [] : [{}];
    const grants = suppliedGrants.map((grant, index) => normalizeGrant(grant, index, agentId));
    const suppliedBindings = Array.isArray(seed.bindings) && seed.bindings.length ? seed.bindings : authorityUnavailable ? [] : [{}];
    const bindings = suppliedBindings.map((binding, index) => normalizeBinding(binding, index, agentId, grants[0]?.grant_id));
    const model = seed.model && typeof seed.model === 'object' && !Array.isArray(seed.model) ? clone(seed.model) : {};
    const provider = ['deterministic', 'vscode-lm', 'pacify-local'].includes(model.provider) ? model.provider : seed.harness_id === 'harness:vscode-lm' ? 'vscode-lm' : 'deterministic';
    return {
      ...clone(seed), agent_id: agentId, version: String(seed.version || '1.0.0').trim().toLowerCase(),
      project_id: identity(seed.project_id, 'project:current'), owner: String(seed.owner || 'human:owner').trim(),
      harness_id: ['vscode-lm', 'pacify-local'].includes(provider) ? 'harness:vscode-lm' : identity(seed.harness_id, 'harness:px'), instructions: String(seed.instructions || 'Operate only inside the supplied task and effect grants.\n'),
      capability_binding_ids: stringList(seed.capability_binding_ids, bindings.map(binding => binding.binding_id)),
      effect_grant_ids: stringList(seed.effect_grant_ids, grants.map(grant => grant.grant_id)),
      required_tests: stringList(seed.required_tests, ['identity', 'sandbox', 'model-route', 'input-contract', 'output-contract', 'authority-bindings', 'tool-bindings', 'handoff-topology']),
      model: {
        provider,
        vendor: String(model.vendor || (provider === 'pacify-local' ? 'pacify-local' : '')).trim(),
        family: String(model.family || (provider === 'deterministic' ? 'px-bounded-worker' : 'auto')).trim(),
        model_id: String(model.model_id || (provider === 'deterministic' ? 'px-bounded-worker' : 'auto')).trim(),
        version: String(model.version || (provider === 'deterministic' ? '1.0.0' : 'auto')).trim(),
        max_output_tokens: Math.max(1, Math.min(32768, Number(model.max_output_tokens) || 4096)),
        temperature: Math.max(0, Math.min(2, Number(model.temperature) || 0))
      },
      tool_binding_ids: stringList(seed.tool_binding_ids), memory_binding_ids: stringList(seed.memory_binding_ids), handoff_agent_ids: stringList(seed.handoff_agent_ids),
      input_schema: seed.input_schema && typeof seed.input_schema === 'object' && !Array.isArray(seed.input_schema) ? clone(seed.input_schema) : { type: 'object', additionalProperties: true, properties: { objective: { type: 'string' } }, required: ['objective'] },
      output_schema: seed.output_schema && typeof seed.output_schema === 'object' && !Array.isArray(seed.output_schema) ? clone(seed.output_schema) : { type: 'object', additionalProperties: true, properties: { text: { type: 'string' } } },
      grants, bindings,
      builder_domain: 'px-standard', lifecycle: LIFECYCLE_STATES.has(seed.lifecycle) ? seed.lifecycle : 'draft'
    };
  }

  function validateAgent(draft) {
    const issues = []; const warnings = [];
    const requireIdentity = (value, label) => { if (!IDENTITY_PATTERN.test(String(value || ''))) issues.push(`${label} must be a lowercase PX identity.`); };
    requireIdentity(draft?.agent_id, 'Agent ID'); requireIdentity(draft?.project_id, 'Project ID'); requireIdentity(draft?.harness_id, 'Harness ID');
    if (!validStudioVersion(draft?.version)) issues.push('Version must be a bounded semantic PX version.');
    if (!String(draft?.owner || '').trim()) issues.push('An accountable owner is required.');
    if (!String(draft?.instructions || '').trim()) issues.push('Bounded agent instructions are required.');
    if (!Array.isArray(draft?.required_tests) || !draft.required_tests.length) issues.push('At least one required test is required.');
    const model = draft?.model;
    if (!model || typeof model !== 'object' || Array.isArray(model)) issues.push('A model route is required.');
    else {
      if (!['deterministic', 'vscode-lm', 'pacify-local'].includes(model.provider)) issues.push('Model provider is not admitted.');
      if (!String(model.family || '').trim() || !String(model.model_id || '').trim()) issues.push('Model family and model ID are required.');
      if (['vscode-lm', 'pacify-local'].includes(model.provider) && [model.vendor, model.family, model.model_id, model.version].some(value => !String(value || '').trim() || value === 'auto')) issues.push('Host model routes require an exact vendor, family, model ID, and version selected from the live host catalog.');
      if (model.provider === 'pacify-local' && model.vendor !== 'pacify-local') issues.push('Pacify local model routes require vendor pacify-local.');
      if (!(Number(model.max_output_tokens) >= 1 && Number(model.max_output_tokens) <= 32768)) issues.push('Model output tokens must be between 1 and 32768.');
      if (!(Number(model.temperature) >= 0 && Number(model.temperature) <= 2)) issues.push('Model temperature must be between 0 and 2.');
      if ((['vscode-lm', 'pacify-local'].includes(model.provider)) !== (draft.harness_id === 'harness:vscode-lm')) issues.push('Host-visible model providers and the VS Code LM harness must be selected together.');
    }
    for (const [name, schema] of [['Input', draft?.input_schema], ['Output', draft?.output_schema]]) if (!schema || typeof schema !== 'object' || Array.isArray(schema) || schema.type !== 'object') issues.push(`${name} schema must be a JSON object schema with root type object.`);
    if (stringList(draft?.tool_binding_ids).some(id => !stringList(draft?.capability_binding_ids).includes(id))) issues.push('Every tool binding must reference a declared capability binding.');
    if (model?.provider === 'pacify-local' && stringList(draft?.tool_binding_ids).length) issues.push('The local Ollama route does not advertise tool calling; use a compatible VS Code model or remove tool bindings.');
    if (stringList(draft?.memory_binding_ids).length) issues.push('Memory bindings are preserved in the candidate schema but runtime retrieval is not yet resolved; remove them before admission.');
    if (stringList(draft?.handoff_agent_ids).length) issues.push('Handoff bindings are preserved in the candidate schema but runtime dispatch is not yet resolved; remove them before admission.');
    if (stringList(draft?.handoff_agent_ids).includes(draft?.agent_id)) issues.push('An agent cannot hand off to itself.');
    const grants = Array.isArray(draft?.grants) ? draft.grants : []; const bindings = Array.isArray(draft?.bindings) ? draft.bindings : [];
    if (!grants.length) issues.push('At least one effect grant declaration is required.');
    if (!bindings.length) issues.push('At least one capability binding declaration is required.');
    const grantIds = new Set();
    for (const grant of grants) {
      requireIdentity(grant?.grant_id, 'Grant ID');
      if (grantIds.has(grant?.grant_id)) issues.push(`Duplicate grant ID: ${grant?.grant_id}.`); grantIds.add(grant?.grant_id);
      if (grant?.subject_id !== draft?.agent_id) issues.push(`${grant?.grant_id || 'Grant'} subject must match the agent ID.`);
      if (!stringList(grant?.effects).length || !stringList(grant?.scope_roots).length) issues.push(`${grant?.grant_id || 'Grant'} requires effects and bounded scope roots.`);
      if (!String(grant?.approved_by || '').trim() || !stringList(grant?.evidence_refs).length) issues.push(`${grant?.grant_id || 'Grant'} requires an approver and evidence references.`);
      if (!LIFECYCLE_STATES.has(grant?.state)) issues.push(`${grant?.grant_id || 'Grant'} has an invalid lifecycle state.`);
      if (grant?.expires_utc && Number.isNaN(Date.parse(grant.expires_utc))) issues.push(`${grant?.grant_id || 'Grant'} has an invalid expiry.`);
    }
    const bindingIds = new Set();
    for (const binding of bindings) {
      requireIdentity(binding?.binding_id, 'Binding ID'); requireIdentity(binding?.capability_id, 'Capability ID');
      if (bindingIds.has(binding?.binding_id)) issues.push(`Duplicate binding ID: ${binding?.binding_id}.`); bindingIds.add(binding?.binding_id);
      if (binding?.subject_kind !== 'agent' || binding?.subject_id !== draft?.agent_id) issues.push(`${binding?.binding_id || 'Binding'} must target this agent.`);
      if (!validStudioVersion(binding?.capability_version)) issues.push(`${binding?.binding_id || 'Binding'} requires a bounded semantic capability version.`);
      if (!stringList(binding?.effect_grant_ids).length || stringList(binding?.effect_grant_ids).some(id => !grantIds.has(id))) issues.push(`${binding?.binding_id || 'Binding'} must reference declared effect grants.`);
      if (!String(binding?.cost_policy || '').trim() || !String(binding?.egress_policy || '').trim() || !stringList(binding?.evidence_refs).length) issues.push(`${binding?.binding_id || 'Binding'} requires cost, egress, and evidence policy.`);
      if (!LIFECYCLE_STATES.has(binding?.state)) issues.push(`${binding?.binding_id || 'Binding'} has an invalid lifecycle state.`);
      if (RESTRICTED_CAPABILITY_PREFIX.test(String(binding?.capability_id || '')) || RESTRICTED_CAPABILITY_PREFIX.test(String(binding?.credential_namespace || ''))) issues.push(`${binding?.binding_id || 'Binding'} crosses the px-standard domain boundary; use the separately governed MS+Enterprise flow.`);
      if (binding?.credential_namespace) warnings.push(`${binding.binding_id} declares a credential namespace; no credential value is stored or granted here.`);
    }
    for (const id of stringList(draft?.capability_binding_ids)) if (!bindingIds.has(id)) issues.push(`Agent references undeclared binding ${id}.`);
    for (const id of stringList(draft?.effect_grant_ids)) if (!grantIds.has(id)) issues.push(`Agent references undeclared grant ${id}.`);
    if (draft?.builder_domain !== 'px-standard') issues.push('Standard Agent Builder domain must remain px-standard.');
    return { valid: issues.length === 0, issues, warnings, counts: { bindings: bindings.length, grants: grants.length, tests: stringList(draft?.required_tests).length } };
  }

  function defaultSkillFiles(skillId, version = '1.0.0') {
    const title = String(skillId || 'my-skill').replace(/[-_:]+/g, ' ').replace(/\b\w/g, value => value.toUpperCase());
    return {
      'SKILL.md': `---\nname: ${skillId}\ndescription: Describe when this skill should and should not be used.\n---\n\n# ${title}\n\n1. Establish bounded inputs and authority.\n2. Perform the admitted operation.\n3. Retain validation evidence.\n`,
      'capability.json': `${JSON.stringify({ schema_version: 'px.skill-capability/1.0', id: skillId, version, domain: 'px-standard', effects: ['read'], permissions: ['read_local'], triggers: ['explicit matching task'], non_triggers: ['unrelated task'] }, null, 2)}\n`,
      'skill.yaml': `schema_version: px.skill-manifest/1.0\nid: ${skillId}\nversion: ${version}\nentrypoint: SKILL.md\ndomain: px-standard\n`,
      'contracts/input.schema.json': `${JSON.stringify({ $schema: 'https://json-schema.org/draft/2020-12/schema', type: 'object', additionalProperties: false, properties: {} }, null, 2)}\n`,
      'tests/contract.json': `${JSON.stringify({ schema_version: 'px.skill-test/1.1', cases: [{ name: 'required-package-files', assertion: { kind: 'required-files', paths: ['SKILL.md', 'capability.json', 'skill.yaml'] } }] }, null, 2)}\n`,
      'resources/README.md': '# Resources\n\nPlace bounded, source-attributed supporting material here.\n'
    };
  }

  function normalizeSkill(seed = {}) {
    const skillId = safeToken(seed.skill_id || seed.id || 'my-skill').toLowerCase();
    const version = String(seed.version || '1.0.0').trim().toLowerCase();
    const supplied = seed.editor_files && typeof seed.editor_files === 'object' && !Array.isArray(seed.editor_files) ? seed.editor_files : null;
    return {
      ...clone(seed), skill_id: skillId, version, owner: String(seed.owner || 'human:owner'), builder_domain: 'px-standard',
      triggers: Array.isArray(seed.triggers) ? seed.triggers : ['explicit matching task'],
      non_triggers: Array.isArray(seed.non_triggers) ? seed.non_triggers : ['unrelated task'],
      permissions: Array.isArray(seed.permissions) ? seed.permissions : ['read_local'], effects: Array.isArray(seed.effects) ? seed.effects : ['read'],
      resources: Array.isArray(seed.resources) ? seed.resources : ['resources/README.md'], contracts: Array.isArray(seed.contracts) ? seed.contracts : ['contracts/input.schema.json'],
      tests: Array.isArray(seed.tests) ? seed.tests : ['tests/contract.json'], provenance: seed.provenance || { source: 'studio-guided-editor' },
      editor_files: supplied ? Object.fromEntries(Object.entries(supplied).map(([path, content]) => [String(path), String(content)])) : defaultSkillFiles(skillId, version), lifecycle: 'draft'
    };
  }

  function synchronizeSkillIdentityFiles(draft) {
    const next = clone(draft); const files = next.editor_files || {}; const skillId = safeToken(next.skill_id).toLowerCase(); const version = String(next.version || '').trim();
    const capability = JSON.parse(files['capability.json'] || '{}');
    if (!capability || typeof capability !== 'object' || Array.isArray(capability)) throw new Error('capability.json must contain an object.');
    capability.id = skillId; capability.version = version; capability.domain = 'px-standard'; files['capability.json'] = `${JSON.stringify(capability, null, 2)}\n`;
    const yamlText = String(files['skill.yaml'] || '');
    try {
      const manifest = JSON.parse(yamlText); if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) throw new Error('not an object');
      manifest.id = skillId; manifest.version = version; manifest.domain = 'px-standard'; files['skill.yaml'] = `${JSON.stringify(manifest, null, 2)}\n`;
    } catch {
      let lines = yamlText.replace(/\r\n/g, '\n').split('\n');
      const setRoot = (key, value) => { const index = lines.findIndex(line => new RegExp(`^${key}\\s*:`).test(line)); if (index >= 0) lines[index] = `${key}: ${value}`; else lines.unshift(`${key}: ${value}`); };
      setRoot('domain', 'px-standard'); setRoot('version', version); setRoot('id', skillId); files['skill.yaml'] = `${lines.join('\n').replace(/\n+$/, '')}\n`;
    }
    const body = String(files['SKILL.md'] || ''); const boundary = body.indexOf('\n---', 3);
    if (body.startsWith('---\n') && boundary > 0) { const head = body.slice(0, boundary); const updated = /^name\s*:/m.test(head) ? head.replace(/^name\s*:.*$/m, `name: ${skillId}`) : `${head}\nname: ${skillId}`; files['SKILL.md'] = `${updated}${body.slice(boundary)}`; }
    next.skill_id = skillId; next.editor_files = files; return next;
  }

  function prepareSkillCandidate(seed = {}) {
    const draft = normalizeSkill(seed);
    try { return synchronizeSkillIdentityFiles(draft); }
    catch { return draft; }
  }

  function validateSkill(draft) {
    const issues = []; const files = draft?.editor_files || {};
    if (!IDENTITY_PATTERN.test(String(draft?.skill_id || ''))) issues.push('Skill ID must be a lowercase PX identity.');
    if (!validStudioVersion(draft?.version)) issues.push('Version must be a bounded semantic PX version.');
    for (const required of ['SKILL.md', 'capability.json', 'skill.yaml']) if (!String(files[required] || '').trim()) issues.push(`${required} is required.`);
    for (const path of Object.keys(files)) {
      if (!path || path.startsWith('/') || /^[A-Za-z]:/.test(path) || path.split(/[\\/]/).includes('..')) issues.push(`Unsafe package path: ${path || '(blank)'}.`);
      if (!String(files[path]).trim()) issues.push(`${path} is empty.`);
    }
    try { const capability = JSON.parse(files['capability.json'] || ''); if (!capability || Array.isArray(capability) || capability.id !== draft.skill_id || capability.version !== draft.version) issues.push('capability.json ID and version must match the Studio revision.'); if (capability?.domain !== 'px-standard') issues.push('capability.json must remain in the px-standard domain.'); } catch { issues.push('capability.json must contain valid JSON.'); }
    const yamlText = String(files['skill.yaml'] || '');
    try { const manifest = JSON.parse(yamlText); if (!manifest || Array.isArray(manifest) || manifest.id !== draft.skill_id || manifest.version !== draft.version) issues.push('skill.yaml ID and version must match the Studio revision.'); if (manifest?.domain !== 'px-standard') issues.push('skill.yaml must remain in the px-standard domain.'); }
    catch { const id = /^id\s*:\s*([^#\r\n]+)/m.exec(yamlText)?.[1]?.trim(); const version = /^version\s*:\s*([^#\r\n]+)/m.exec(yamlText)?.[1]?.trim(); const domain = /^domain\s*:\s*([^#\r\n]+)/m.exec(yamlText)?.[1]?.trim(); if (id !== draft.skill_id || version !== draft.version) issues.push('skill.yaml ID and version must match the Studio revision.'); if (domain !== 'px-standard') issues.push('skill.yaml must remain in the px-standard domain.'); }
    const frontmatterName = /^---\s*\n[\s\S]*?^name\s*:\s*([^\r\n#]+)/m.exec(String(files['SKILL.md'] || ''))?.[1]?.trim();
    if (frontmatterName !== draft.skill_id) issues.push('SKILL.md frontmatter name must match the Studio skill ID.');
    if (draft?.builder_domain !== 'px-standard') issues.push('Standard Skill Studio domain must remain px-standard.');
    return { valid: issues.length === 0, issues, file_count: Object.keys(files).length };
  }

  function historyEntry(kind, operation, result, at = new Date().toISOString()) {
    return { kind, operation, at, revision: result?.revision || result?.revision_id || result?.version || null, status: result?.status || result?.state || (result?.valid === false ? 'failed' : 'recorded'), receipt: result?.receipt_sha256 || result?.sha256 || result?.revision_sha256 || null };
  }

  dashboard.define('studioEditors', Object.freeze({
    editDistance, fuzzyScore, rankGraph, normalizeAgent, validateAgent, agentSpecProjection, projectAgentBuilderGraph, validateAgentBuilderGraph, synchronizeAgentBuilderGraph, editAgentBuilderNode, editAgentBuilderEdge, agentCandidatePayload,
    normalizeWorkflow, validateWorkflow, normalizeSkill, prepareSkillCandidate, synchronizeSkillIdentityFiles, validateSkill, historyEntry, safeToken, validCanonicalUtc, validStudioVersion
  }));
})();
