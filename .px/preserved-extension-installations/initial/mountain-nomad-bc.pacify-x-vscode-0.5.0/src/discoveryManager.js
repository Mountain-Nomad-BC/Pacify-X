'use strict';

const cp = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const SCHEMA = 'px.environment-capability-map/1.0';
const MAX_OUTPUT = 8 * 1024 * 1024;
const TOOL_PROBES = [
  ['python', ['--version']], ['node', ['--version']], ['npm', ['--version']], ['git', ['--version']],
  ['docker', ['--version']], ['ollama', ['--version']], ['uv', ['--version']], ['code', ['--version']]
];

function sha(value) { return crypto.createHash('sha256').update(typeof value === 'string' ? value : JSON.stringify(value)).digest('hex'); }
function cleanText(value, maximum = 500) { return String(value || '').replace(/[\r\n\0]+/g, ' ').trim().slice(0, maximum); }
function nonBillableEnv() {
  const denied = /^(OPENAI|AZURE_OPENAI|ANTHROPIC|GOOGLE|GEMINI|CODEX|MISTRAL|COHERE|GROQ|TOGETHER|OPENROUTER|PERPLEXITY|XAI|DEEPSEEK)_API_KEY$/i;
  return Object.fromEntries(Object.entries(process.env).filter(([key]) => !denied.test(key)));
}
function runBounded(command, args, options = {}) {
  return new Promise(resolve => {
    let stdout = ''; let stderr = ''; let settled = false;
    let child;
    try {
      child = cp.spawn(command, args, {
        cwd: options.cwd, windowsHide: true, shell: false,
        env: { ...nonBillableEnv(), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1', NO_COLOR: '1' }
      });
    } catch (error) { resolve({ status: null, stdout, stderr: error.message }); return; }
    const finish = result => { if (!settled) { settled = true; clearTimeout(timer); resolve(result); } };
    const capture = (target, chunk) => {
      const next = target + chunk.toString('utf8');
      if (next.length > MAX_OUTPUT) { child.kill(); return next.slice(0, MAX_OUTPUT); }
      return next;
    };
    child.stdout?.on('data', chunk => { stdout = capture(stdout, chunk); });
    child.stderr?.on('data', chunk => { stderr = capture(stderr, chunk); });
    child.on('error', error => finish({ status: null, stdout, stderr: `${stderr}${error.message}` }));
    child.on('close', code => finish({ status: code, stdout, stderr }));
    const timer = setTimeout(() => { child.kill(); finish({ status: null, stdout, stderr: `${stderr}probe-timeout` }); }, options.timeout || 10000);
  });
}
function parseJson(result, fallback) {
  if (!result || result.status !== 0) return fallback;
  try { return JSON.parse(result.stdout); } catch { return fallback; }
}
function normalizeExtensions(extensions = []) {
  const records = extensions.map(extension => {
    const manifest = extension.packageJSON || {};
    const contributes = manifest.contributes && typeof manifest.contributes === 'object' ? manifest.contributes : {};
    const commands = (Array.isArray(contributes.commands) ? contributes.commands : []).map(item => ({
      id: cleanText(item?.command, 240), invocation: `vscode.commands.executeCommand('${cleanText(item?.command, 240)}', ...args)`,
      title: cleanText(item?.title, 240), expected_inputs: 'Arguments are not declared by the extension manifest; inspect provider documentation before invocation.',
      expected_outputs: 'Return contract is not declared by the extension manifest.', enablement: cleanText(item?.enablement, 500) || null
    })).filter(item => item.id).sort((a, b) => a.id.localeCompare(b.id));
    const capabilityFlags = manifest.capabilities && typeof manifest.capabilities === 'object' ? manifest.capabilities : {};
    return {
      id: cleanText(extension.id || manifest.name, 200), name: cleanText(manifest.displayName || manifest.name || extension.id, 240),
      version: cleanText(manifest.version, 80), publisher: cleanText(manifest.publisher, 160), active: Boolean(extension.isActive),
      builtin: Boolean(manifest.isBuiltin), extension_kind: Array.isArray(manifest.extensionKind) ? manifest.extensionKind.map(String) : [],
      contribution_points: Object.keys(contributes).sort(),
      capabilities: Object.keys(contributes).sort().map(point => ({ id: `contribution:${point}`, kind: point, provider: cleanText(extension.id || manifest.name, 200), invocation: point === 'commands' ? 'See commands[]' : 'VS Code contribution-point contract', expected_inputs: 'Defined by the VS Code contribution point and provider manifest.', expected_outputs: 'Defined by the VS Code host contract; provider-specific output is not inferred.' })),
      commands,
      api_contract: { exported_api_detected: false, activation_attempted: false, invocation: 'vscode.extensions.getExtension(id)?.exports only after separately approved activation', expected_inputs: 'Provider-defined; not inferred', expected_outputs: 'Provider-defined; not inferred' },
      dependencies: (Array.isArray(manifest.extensionDependencies) ? manifest.extensionDependencies : []).map(item => cleanText(item, 200)).filter(Boolean).sort(),
      activation_events: (Array.isArray(manifest.activationEvents) ? manifest.activationEvents : []).map(item => cleanText(item, 300)).filter(Boolean).sort(),
      permissions_resources: {
        extension_kind: Array.isArray(manifest.extensionKind) ? manifest.extensionKind.map(String) : [],
        workspace_trust: capabilityFlags.untrustedWorkspaces || { supported: 'not-declared' },
        virtual_workspaces: capabilityFlags.virtualWorkspaces || { supported: 'not-declared' },
        resource_roots: ['VS Code extension host', 'declared contribution points'], credential_access_inferred: false
      },
      constraints: ['Metadata detection does not activate the extension.', 'Command arguments and return types are unknown unless the provider declares them.'],
      known_conflicts: [],
      integration_status: 'detected-metadata-only'
    };
  }).filter(item => item.id).sort((a, b) => a.id.localeCompare(b.id));
  const owners = new Map();
  for (const record of records) for (const command of record.commands) {
    if (!owners.has(command.id)) owners.set(command.id, []); owners.get(command.id).push(record.id);
  }
  for (const record of records) for (const command of record.commands) {
    const commandOwners = owners.get(command.id) || [];
    if (commandOwners.length > 1) record.known_conflicts.push({ kind: 'duplicate-command-provider', resource: command.id, providers: commandOwners });
  }
  return records;
}
async function toolInventory(run = runBounded, pythonPath = 'python') {
  return Promise.all(TOOL_PROBES.map(async ([tool, args]) => {
    const command = tool === 'python' ? pythonPath : tool;
    const result = await run(command, args, { timeout: 5000 });
    return { id: tool, command: cleanText(command, 500), available: result.status === 0, version: cleanText(result.stdout || result.stderr, 300), probe: args.join(' ') };
  }));
}
async function packageInventory(run = runBounded, pythonPath = 'python', projectRoot = '') {
  const [pythonResult, npmGlobalResult] = await Promise.all([
    run(pythonPath, ['-m', 'pip', 'list', '--format=json', '--disable-pip-version-check'], { timeout: 20000, cwd: projectRoot || undefined }),
    run('npm', ['ls', '-g', '--depth=0', '--json'], { timeout: 20000, cwd: projectRoot || undefined })
  ]);
  const python = parseJson(pythonResult, []).map(item => ({ name: cleanText(item.name, 240), version: cleanText(item.version, 120), manager: 'python-pip', scope: 'interpreter' })).filter(item => item.name).sort((a, b) => a.name.localeCompare(b.name));
  const npmGlobalJson = parseJson(npmGlobalResult, {});
  const npmGlobal = Object.entries(npmGlobalJson.dependencies || {}).map(([name, item]) => ({ name: cleanText(name, 240), version: cleanText(item?.version, 120), manager: 'npm', scope: 'global' })).sort((a, b) => a.name.localeCompare(b.name));
  let npmProject = [];
  if (projectRoot && fs.existsSync(path.join(projectRoot, 'package.json'))) {
    const projectResult = await run('npm', ['ls', '--depth=0', '--json'], { timeout: 20000, cwd: projectRoot });
    const projectJson = parseJson(projectResult, {});
    npmProject = Object.entries(projectJson.dependencies || {}).map(([name, item]) => ({ name: cleanText(name, 240), version: cleanText(item?.version, 120), manager: 'npm', scope: 'project' })).sort((a, b) => a.name.localeCompare(b.name));
  }
  return { python, npm_global: npmGlobal, npm_project: npmProject, probes: { python: pythonResult.status === 0, npm_global: npmGlobalResult.status === 0 } };
}
function semanticGraph(subjects) {
  const nodes = [];
  const edges = [];
  const nodeIds = new Set();
  const addNode = (id, type, label, properties = {}) => { if (!nodeIds.has(id)) { nodeIds.add(id); nodes.push({ id, type, label, properties }); } };
  const addEdge = (from, predicate, to, properties = {}) => edges.push({ id: sha(`${from}\0${predicate}\0${to}`).slice(0, 24), from, predicate, to, properties });
  const addContract = (resourceId, contract = {}) => {
    for (const capability of contract.capabilities || []) { const id = `capability:${sha(String(capability)).slice(0, 20)}`; addNode(id, 'capability', String(capability)); addEdge(resourceId, 'has-capability', id); }
    for (const interfaceItem of Array.isArray(contract.interface) ? contract.interface : [contract.interface].filter(Boolean)) { const id = `interface:${sha(String(interfaceItem)).slice(0, 20)}`; addNode(id, 'interface', String(interfaceItem)); addEdge(resourceId, 'has-interface', id); }
    const requirements = typeof contract.requirements === 'string' ? [contract.requirements] : Array.isArray(contract.requirements) ? contract.requirements : Object.entries(contract.requirements || {}).map(([key, value]) => `${key}:${JSON.stringify(value)}`);
    for (const requirement of requirements) { const id = `requirement:${sha(String(requirement)).slice(0, 20)}`; addNode(id, 'requirement', String(requirement)); addEdge(resourceId, 'requires', id); }
    for (const effect of contract.effects || []) { const id = `effect:${sha(String(effect)).slice(0, 20)}`; addNode(id, 'effect', String(effect)); addEdge(resourceId, 'may-effect', id); }
    for (const conflict of contract.conflicts || []) { const label = typeof conflict === 'string' ? conflict : JSON.stringify(conflict); const id = `conflict:${sha(label).slice(0, 20)}`; addNode(id, 'conflict', label); addEdge(resourceId, 'conflicts-with', id); }
    if (contract.policy) { const id = `policy:${sha(String(contract.policy)).slice(0, 20)}`; addNode(id, 'policy', String(contract.policy)); addEdge(resourceId, 'governed-by', id); }
    if (contract.state) { const id = `state:${sha(String(contract.state)).slice(0, 20)}`; addNode(id, 'resource-state', String(contract.state)); addEdge(resourceId, 'has-state', id); }
  };
  addNode('px:orchestration-plane', 'orchestration-plane', 'Pacify-X orchestration plane', { authority: 'project-owned capability map' });
  for (const extension of subjects.extensions) {
    const extensionId = `vscode-extension:${extension.id}`; addNode(extensionId, 'vscode-extension', extension.name, { version: extension.version, active: extension.active, integration_status: extension.integration_status });
    addEdge(extensionId, 'available-to', 'px:orchestration-plane');
    for (const point of extension.contribution_points) { const pointId = `vscode-contribution:${point}`; addNode(pointId, 'vscode-contribution-point', point); addEdge(extensionId, 'contributes', pointId); }
    for (const command of extension.commands) { const commandId = `vscode-command:${command.id}`; addNode(commandId, 'vscode-command', command.id, { invocation: command.invocation, expected_inputs: command.expected_inputs, expected_outputs: command.expected_outputs }); addEdge(extensionId, 'contributes-command', commandId); addEdge(commandId, 'available-to', 'px:orchestration-plane'); }
    for (const dependency of extension.dependencies) { const dependencyId = `vscode-extension:${dependency}`; addNode(dependencyId, 'vscode-extension-reference', dependency); addEdge(extensionId, 'depends-on', dependencyId); }
    addContract(extensionId, extension.resource_contract);
  }
  for (const tool of subjects.system_tools) {
    const toolId = `system-tool:${tool.id}`; addNode(toolId, 'system-tool', tool.id, { available: tool.available, version: tool.version });
    if (tool.available) addEdge(toolId, 'available-to', 'px:orchestration-plane');
    addContract(toolId, tool.resource_contract);
  }
  for (const packageItem of [...subjects.python_packages, ...subjects.npm_global_packages, ...subjects.npm_project_packages]) {
    const packageId = `package:${packageItem.manager}:${packageItem.scope}:${packageItem.name}`;
    const managerId = packageItem.manager === 'python-pip' ? 'system-tool:python' : 'system-tool:npm';
    addNode(packageId, 'installed-package', packageItem.name, { version: packageItem.version, manager: packageItem.manager, scope: packageItem.scope });
    addEdge(packageId, 'installed-by', managerId); addEdge(packageId, 'available-to', 'px:orchestration-plane');
    addContract(packageId, packageItem.resource_contract);
  }
  nodes.sort((a, b) => a.id.localeCompare(b.id)); edges.sort((a, b) => a.id.localeCompare(b.id));
  return { nodes, edges };
}
function buildInventory({ extensions = [], tools = [], packages = {}, generatedUtc = new Date().toISOString() }) {
  const packageContract = item => ({
    ...item,
    resource_contract: { resource: `${item.manager}:${item.scope}:${item.name}`, capabilities: ['installed-package'], interface: item.manager, requirements: [`${item.manager} package environment`], effects: ['available-for-separately-governed-invocation'], conflicts: [], policy: 'detected-read-only-not-admitted-for-automatic-execution', state: 'installed' }
  });
  const subjects = {
    extensions: normalizeExtensions(extensions).map(item => ({ ...item, resource_contract: { resource: item.id, capabilities: item.capabilities.map(capability => capability.id), interface: item.commands.map(command => command.id), requirements: item.permissions_resources, effects: ['metadata-read-only; invocation effects remain provider-owned'], conflicts: item.known_conflicts, policy: 'detect-without-activation; invoke-only-through-separate-governed action', state: item.active ? 'active-in-host' : 'installed-not-active' } })),
    system_tools: tools.map(item => ({ ...item, resource_contract: { resource: item.id, capabilities: item.available ? ['version-probed', 'callable-after-separate-policy-gate'] : [], interface: `${item.command} ${item.probe}`, requirements: ['local process execution'], effects: ['probe-read-only'], conflicts: [], policy: 'no shell; fixed argument probe; provider keys stripped', state: item.available ? 'available' : 'absent' } })),
    python_packages: (packages.python || []).map(packageContract), npm_global_packages: (packages.npm_global || []).map(packageContract), npm_project_packages: (packages.npm_project || []).map(packageContract)
  };
  const graph = semanticGraph(subjects);
  const stable = {
    schema_version: SCHEMA, authority: 'Pacify-X extension read-only environment discovery',
    boundaries: { arbitrary_extension_activation: false, credential_reads: false, network_installs: false, billable_calls: false, mutation: false },
    ontology: {
      canonical_chain: ['resource', 'capabilities', 'interface', 'requirements', 'effects', 'conflicts', 'policy', 'state'],
      node_types: ['orchestration-plane', 'vscode-extension', 'vscode-extension-reference', 'vscode-contribution-point', 'vscode-command', 'system-tool', 'installed-package', 'capability', 'interface', 'requirement', 'effect', 'conflict', 'policy', 'resource-state'],
      predicates: ['has-capability', 'has-interface', 'requires', 'may-effect', 'conflicts-with', 'governed-by', 'has-state', 'available-to', 'contributes', 'contributes-command', 'depends-on', 'installed-by']
    }, subjects, graph,
    summary: {
      extensions: subjects.extensions.length, active_extensions: subjects.extensions.filter(item => item.active).length,
      system_tools: subjects.system_tools.length, available_tools: subjects.system_tools.filter(item => item.available).length,
      python_packages: subjects.python_packages.length, npm_global_packages: subjects.npm_global_packages.length, npm_project_packages: subjects.npm_project_packages.length,
      graph_nodes: graph.nodes.length, graph_edges: graph.edges.length
    }
  };
  return { ...stable, generated_utc: generatedUtc, snapshot_hash: sha(stable) };
}
function pathsFor(projectRoot) {
  const root = path.join(path.resolve(projectRoot), '.engineering-bootstrap', 'environment');
  return { root, current: path.join(root, 'current.json'), events: path.join(root, 'events.jsonl'), snapshots: path.join(root, 'snapshots') };
}
function atomicWrite(target, value) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.${crypto.randomUUID()}.tmp`;
  try { fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' }); fs.renameSync(temporary, target); }
  finally { try { if (fs.existsSync(temporary)) fs.unlinkSync(temporary); } catch {} }
}
function readEnvironmentInventory(projectRoot) {
  const paths = pathsFor(projectRoot);
  try {
    const inventory = JSON.parse(fs.readFileSync(paths.current, 'utf8'));
    const stable = { schema_version: inventory.schema_version, authority: inventory.authority, boundaries: inventory.boundaries, ontology: inventory.ontology, summary: inventory.summary, storage: inventory.storage, datasets: inventory.datasets, content_hash: inventory.content_hash };
    if (inventory.schema_version !== SCHEMA || inventory.snapshot_hash !== sha(stable)) throw new Error('Environment inventory integrity failed.');
    return { paths, inventory };
  } catch { return { paths, inventory: null }; }
}
function writeDataset(paths, snapshotDirectory, name, value) {
  const target = path.join(snapshotDirectory, `${name}.json`); const serialized = `${JSON.stringify(value, null, 2)}\n`; const digest = sha(serialized);
  if (!fs.existsSync(target)) atomicWrite(target, value);
  const relative = path.relative(paths.root, target).split(path.sep).join('/');
  return { path: relative, sha256: digest, records: Array.isArray(value) ? value.length : undefined };
}
function readDataset(paths, descriptor) {
  if (!descriptor?.path || !descriptor.sha256) throw new Error('Environment dataset descriptor is incomplete.');
  const target = path.resolve(paths.root, descriptor.path); const relative = path.relative(paths.root, target);
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Environment dataset path escaped its root.');
  const stat = fs.statSync(target); if (!stat.isFile() || stat.size > MAX_OUTPUT) throw new Error('Environment dataset is unavailable or oversized.');
  const serialized = fs.readFileSync(target, 'utf8'); if (sha(serialized) !== descriptor.sha256) throw new Error('Environment dataset integrity failed.');
  return JSON.parse(serialized);
}
function readEnvironmentSubject(projectRoot, subject = 'summary', options = {}) {
  const loaded = readEnvironmentInventory(projectRoot); if (!loaded.inventory) return { available: false, reason: 'Environment capability map is unavailable.' };
  const inventory = loaded.inventory; if (subject === 'summary') return { available: true, inventory };
  if (!['extensions', 'tools', 'python', 'npm', 'graph'].includes(subject)) throw new Error('Unknown environment subject.');
  if (subject === 'graph') return { available: true, subject, snapshot_hash: inventory.snapshot_hash, ontology: inventory.ontology, nodes: readDataset(loaded.paths, inventory.datasets.graph_nodes), edges: readDataset(loaded.paths, inventory.datasets.graph_edges) };
  let records;
  if (subject === 'npm') records = [...readDataset(loaded.paths, inventory.datasets.npm_global), ...readDataset(loaded.paths, inventory.datasets.npm_project)];
  else records = readDataset(loaded.paths, inventory.datasets[subject]);
  const query = String(options.query || '').toLowerCase(); if (query) records = records.filter(item => JSON.stringify(item).toLowerCase().includes(query));
  const total = records.length; const offset = Math.max(0, Number(options.offset || 0)); const limit = Math.min(500, Math.max(1, Number(options.limit || 100)));
  return { available: true, subject, snapshot_hash: inventory.snapshot_hash, total, offset, limit, records: records.slice(offset, offset + limit) };
}
function readEnvironmentExtension(projectRoot, extensionId) {
  const loaded = readEnvironmentInventory(projectRoot); if (!loaded.inventory) throw new Error('Environment capability map is unavailable.');
  const records = readDataset(loaded.paths, loaded.inventory.datasets.extensions);
  const record = records.find(item => item.id === extensionId); if (!record) throw new Error('Unknown environment extension.');
  return { available: true, snapshot_hash: loaded.inventory.snapshot_hash, extension: readDataset(loaded.paths, record.detail_ref) };
}
function persistEnvironmentInventory(projectRoot, inventory, reason = 'refresh') {
  const prior = readEnvironmentInventory(projectRoot);
  let priorNodeRecords = [];
  try { priorNodeRecords = prior.inventory ? readDataset(prior.paths, prior.inventory.datasets.graph_nodes) : []; } catch { priorNodeRecords = []; }
  const priorNodes = new Set(priorNodeRecords.map(item => item.id));
  const nextNodes = new Set(inventory.graph.nodes.map(item => item.id));
  const added = [...nextNodes].filter(id => !priorNodes.has(id)); const removed = [...priorNodes].filter(id => !nextNodes.has(id));
  const snapshotDirectory = path.join(prior.paths.snapshots, inventory.snapshot_hash);
  const extensionIndex = inventory.subjects.extensions.map(item => {
    const detail = writeDataset(prior.paths, path.join(snapshotDirectory, 'extensions'), sha(item.id), item);
    return { id: item.id, name: item.name, version: item.version, publisher: item.publisher, active: item.active, builtin: item.builtin, integration_status: item.integration_status, capability_count: item.capabilities.length, command_count: item.commands.length, conflict_count: item.known_conflicts.length, contribution_points: item.contribution_points, detail_ref: detail };
  });
  const datasets = {
    extensions: writeDataset(prior.paths, snapshotDirectory, 'extensions-index', extensionIndex),
    tools: writeDataset(prior.paths, snapshotDirectory, 'system-tools', inventory.subjects.system_tools),
    python: writeDataset(prior.paths, snapshotDirectory, 'python-packages', inventory.subjects.python_packages),
    npm_global: writeDataset(prior.paths, snapshotDirectory, 'npm-global-packages', inventory.subjects.npm_global_packages),
    npm_project: writeDataset(prior.paths, snapshotDirectory, 'npm-project-packages', inventory.subjects.npm_project_packages),
    graph_nodes: writeDataset(prior.paths, snapshotDirectory, 'graph-nodes', inventory.graph.nodes),
    graph_edges: writeDataset(prior.paths, snapshotDirectory, 'graph-edges', inventory.graph.edges)
  };
  const stable = {
    schema_version: SCHEMA, authority: inventory.authority, boundaries: inventory.boundaries, ontology: inventory.ontology, summary: inventory.summary,
    storage: { mode: 'compact-index-with-hash-verified-lazy-shards', snapshot_directory: path.relative(prior.paths.root, snapshotDirectory).split(path.sep).join('/'), per_extension_contracts: true },
    datasets, content_hash: inventory.snapshot_hash
  };
  const compact = { ...stable, generated_utc: inventory.generated_utc, snapshot_hash: sha(stable) };
  atomicWrite(prior.paths.current, compact);
  const event = {
    schema_version: 'px.environment-capability-event/1.0', event_id: `env-${crypto.randomUUID()}`, timestamp: new Date().toISOString(), reason,
    previous_hash: prior.inventory?.snapshot_hash || null, snapshot_hash: compact.snapshot_hash, added_node_ids: added.slice(0, 5000), removed_node_ids: removed.slice(0, 5000),
    changed: prior.inventory?.content_hash !== inventory.snapshot_hash
  };
  fs.mkdirSync(prior.paths.root, { recursive: true }); fs.appendFileSync(prior.paths.events, `${JSON.stringify(event)}\n`, 'utf8');
  return { paths: prior.paths, inventory: compact, event };
}
async function discoverEnvironment({ extensions = [], projectRoot, pythonPath = 'python', run = runBounded, reason = 'refresh' }) {
  const [tools, packages] = await Promise.all([toolInventory(run, pythonPath), packageInventory(run, pythonPath, projectRoot)]);
  return persistEnvironmentInventory(projectRoot, buildInventory({ extensions, tools, packages }), reason);
}

module.exports = {
  SCHEMA, TOOL_PROBES, runBounded, normalizeExtensions, toolInventory, packageInventory, semanticGraph,
  buildInventory, pathsFor, readEnvironmentInventory, readEnvironmentSubject, readEnvironmentExtension, persistEnvironmentInventory, discoverEnvironment
};
