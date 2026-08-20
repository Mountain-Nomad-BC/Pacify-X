import cp from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import activity from '../src/activityManager.js';
import mcpActivity from '../src/mcpActivityIntegration.js';
import coordination from '../src/coordinationManager.js';
import teamFabric from '../src/teamFabricManager.js';
import enterprise from '../src/enterpriseManager.js';
import discovery from '../src/discoveryManager.js';
import { McpServer } from '@modelcontextprotocol/server';
import { serveStdio } from '@modelcontextprotocol/server/stdio';
import { z } from 'zod';

const MAX_FILE_BYTES = 4 * 1024 * 1024;
const {
  readCoordination, createParallelPlan, claimTask, recordProgress, reconcileTask,
  releaseTask, captureMemory, readMemoryTelemetry, taskHandoff, renewClaim, diagnoseWorkStop, workRoom
} = coordination;
const { inventoryTeamPack, stageTeamPack, workerAdapters } = teamFabric;
const { initializeEnterprise, setPackEnabled, configureTarget, evaluateBillableExecution, enterpriseDoctor } = enterprise;
const { readEnvironmentSubject, readEnvironmentExtension } = discovery;
const { recordActivity, readActivity } = activity;
const { createMcpActivityIntegration } = mcpActivity;

function textResult(value) {
  return { content: [{ type: 'text', text: JSON.stringify(value, null, 2) }], structuredContent: value };
}
function readJsonFile(file, fallback) {
  if (!file) return fallback;
  try { const stat = fs.statSync(file); if (!stat.isFile() || stat.size > MAX_FILE_BYTES) return fallback; return JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch { return fallback; }
}
const MCP_VERSION = __PX_EXTENSION_VERSION__;
function contextEnvelope() {
  const value = readJsonFile(process.env.PX_CONTEXT_PATH, {});
  return value?.envelope || value;
}
function nonBillableEnv() {
  const denied = /^(OPENAI|AZURE_OPENAI|ANTHROPIC|GOOGLE|GEMINI|CODEX|MISTRAL|COHERE|GROQ|TOGETHER|OPENROUTER|PERPLEXITY|XAI|DEEPSEEK)_API_KEY$/i;
  return Object.fromEntries(Object.entries(process.env).filter(([key]) => !denied.test(key)));
}
function runApi(args) {
  const root = process.env.PX_ENGINE_ROOT;
  if (!root || !fs.existsSync(path.join(root, 'runtime', 'dashboard_api.py'))) return { available: false, reason: 'Pacify-X dashboard API unavailable.' };
  const result = cp.spawnSync(process.env.PX_PYTHON_PATH || 'python', ['-m', 'runtime.dashboard_api', ...args, '--source-root', root], {
    cwd: root, windowsHide: true, shell: false, encoding: 'utf8', timeout: 30_000, maxBuffer: 32 * 1024 * 1024,
    env: { ...nonBillableEnv(), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' }
  });
  if (result.status !== 0) return { available: false, reason: String(result.stderr || result.error || `dashboard API exited ${result.status}`).trim() };
  try { return JSON.parse(result.stdout); } catch (error) { return { available: false, reason: `Invalid dashboard API JSON: ${error.message}` }; }
}
function workspaceRoot() {
  const value = process.env.PX_COORDINATION_ROOT || process.env.PX_WORKSPACE_ROOT;
  if (!value) throw new Error('PX coordination workspace is unavailable.');
  return path.resolve(value);
}
function enterpriseCatalog() {
  const snapshot = runApi(['snapshot']);
  if (!snapshot?.enterprise?.catalog_id) throw new Error('The separate MS+Enterprise catalog is unavailable.');
  return snapshot.enterprise;
}
function actor(value) {
  return { actorId: value.actor_id, sessionId: value.session_id, harness: value.harness, accountableOwner: value.accountable_owner || 'local-user' };
}
function activityPolicy() {
  try { return { ...JSON.parse(process.env.PX_ACTIVITY_POLICY || '{}'), captureMcpCalls: JSON.parse(process.env.PX_ACTIVITY_POLICY || '{}').captureMcpCalls !== false }; }
  catch { return { enabled: true, paused: false, captureMcpCalls: true }; }
}
function admittedTeamPackRoot(value) {
  const candidate = path.resolve(String(value || ''));
  const roots = String(process.env.PX_TEAM_PACK_ROOTS || '').split(path.delimiter).filter(Boolean).map(root => path.resolve(root));
  const admitted = roots.some(root => candidate === root || candidate.startsWith(`${root}${path.sep}`));
  if (!admitted) throw new Error('Team package root is not below PX_TEAM_PACK_ROOTS.');
  return candidate;
}

function buildServer() {
  const server = new McpServer({ name: 'pacify-x-governed-context', version: MCP_VERSION }, { capabilities: { tools: {} } });
  const empty = z.object({}).strict();
  const readOnly = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false };
  const write = { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false };
  const actorFields = {
    actor_id: z.string().min(1).max(160), session_id: z.string().min(1).max(160),
    harness: z.string().min(1).max(120), accountable_owner: z.string().max(160).optional()
  };
  const mcpInstrumentation = createMcpActivityIntegration({
    recordActivity,
    workspaceRoot,
    projectId: () => path.basename(workspaceRoot()),
    contextEnvelope,
    policy: activityPolicy,
    processId: process.pid,
    onDrop: failure => process.stderr.write(`[pacify-x-mcp-instrumentation] ${failure.type}:${failure.tool}:${failure.lifecycle}\n`)
  });
  const registerTool = (name, definition, handler) => server.registerTool(name, definition, mcpInstrumentation.wrapTool(name, definition, handler));

  registerTool('pacify_context_snapshot', {
    title: 'Pacify-X Context Snapshot', description: 'Return the bounded portable context envelope and project-owned continuity references.', inputSchema: empty, annotations: readOnly
  }, async () => textResult(contextEnvelope() || { available: false, reason: 'No context snapshot is available.' }));

  registerTool('pacify_git_context', {
    title: 'Pacify-X Git Context', description: 'Return the read-only Git snapshot and mutation boundary.', inputSchema: empty, annotations: readOnly
  }, async () => { const snapshot = contextEnvelope() || {}; return textResult({ git: snapshot.git || null, git_policy: snapshot.git_policy || null, read_only: true }); });

  registerTool('pacify_control_plane_summary', {
    title: 'Pacify-X Control Plane Summary', description: 'Read the canonical versioned Pacify-X dashboard snapshot.', inputSchema: empty, annotations: readOnly
  }, async () => textResult(runApi(['snapshot'])));

  registerTool('pacify_capability_manifest', {
    title: 'Pacify-X AI Capability Manifest', description: 'Describe the machine-readable PX surfaces, effect boundaries, schema sources, and safe next calls available to an AI client.', inputSchema: empty, annotations: readOnly
  }, async () => textResult({
    schema_version: '1.0', product: 'Pacify-X', interface: 'MCP structuredContent',
    capabilities: [
      { id: 'catalog', tool: 'pacify_catalog_query', effects: ['read'], source: 'runtime.dashboard_api' },
      { id: 'knowledge-graph', tool: 'pacify_graph_query', effects: ['read'], source: 'registry/cognitive_map_index.json' },
      { id: 'hardware-telemetry', tool: 'pacify_hardware_telemetry', effects: ['read', 'local-process-probe'], source: 'runtime.hardware_routing' },
      { id: 'plugins', tool: 'pacify_plugin_catalog', effects: ['read'], source: 'PX registries + environment map' },
      { id: 'agent-readiness', tool: 'pacify_agent_readiness', effects: ['read'], source: 'runtime.dashboard_api + current project map' },
      { id: 'activity-observability', tool: 'pacify_activity_observability', emit_tool: 'pacify_activity_emit', effects: ['local-metadata-trace'], source: 'project-owned activity ledger' },
      { id: 'mcp-instrumentation-health', tool: 'pacify_mcp_instrumentation_status', effects: ['read'], source: 'src/mcpActivityIntegration.js' },
      { id: 'portable-memory-observability', tool: 'pacify_memory_observability', effects: ['read'], source: 'project-owned coordination ledger' },
      { id: 'parallel-planning', tool: 'pacify_parallel_plan_create', effects: ['project-coordination-write'], source: 'project-owned coordination ledger' }
    ],
    invariants: ['tool availability does not grant authority', 'unknown stays unknown', 'Git mutation is denied', 'billable execution requires separate approval']
  }));

  registerTool('pacify_graph_query', {
    title: 'Pacify-X Knowledge Graph Query', description: 'Return a bounded real node-and-edge neighborhood with typed directions and human-readable connection reasons.',
    inputSchema: z.object({ view: z.enum(['capabilities', 'repository']).optional(), node: z.string().max(500).optional(), query: z.string().max(500).optional(), relation: z.string().max(160).optional(), direction: z.enum(['incoming', 'outgoing', 'both']).optional(), depth: z.number().int().min(1).max(2).optional(), max_nodes: z.number().int().min(2).max(50).optional(), max_edges: z.number().int().min(1).max(100).optional() }).strict(), annotations: readOnly
  }, async input => textResult(runApi(['graph', '--view', input.view || 'capabilities', '--project', process.env.PX_WORKSPACE_ROOT || process.env.PX_ENGINE_ROOT || '', '--node', input.node || '', '--query', input.query || '', '--relation', input.relation || '', '--direction', input.direction || 'both', '--depth', String(input.depth || 1), '--max-nodes', String(input.max_nodes || 24), '--max-edges', String(input.max_edges || 48)])));

  registerTool('pacify_hardware_telemetry', {
    title: 'Pacify-X Hardware Telemetry', description: 'Read normalized available CPU, GPU, thermal, utilization, power, and fan sensors with source, timestamp, and explicit unavailable states.', inputSchema: empty, annotations: readOnly
  }, async () => { const snapshot = runApi(['snapshot']); return textResult(snapshot?.runtime?.hardware?.telemetry || { available: false, reason: 'Hardware telemetry unavailable.' }); });

  registerTool('pacify_agent_readiness', {
    title: 'Pacify-X Agent Readiness Matrix', description: 'Return the conservative nine-dimension structural readiness matrix, explicit gaps, safe-now tasks, and operations that still require a fresh gate.', inputSchema: empty, annotations: readOnly
  }, async () => {
    const args = ['readiness'];
    const project = process.env.PX_WORKSPACE_ROOT || process.env.PX_ENGINE_ROOT;
    if (project) args.push('--project', project);
    if (process.env.PX_COORDINATION_ROOT) args.push('--workspace-root', process.env.PX_COORDINATION_ROOT);
    return textResult(runApi(args));
  });

  registerTool('pacify_plugin_catalog', {
    title: 'Pacify-X Governed Plugin Catalog', description: 'Inspect detected VS Code extensions, PX skills/tools, MCP status, or enterprise connectors without installing, activating, disabling, or removing anything.',
    inputSchema: z.object({ kind: z.enum(['extensions', 'skills', 'tools', 'mcp', 'connectors']), query: z.string().max(300).optional(), offset: z.number().int().nonnegative().optional(), limit: z.number().int().min(1).max(100).optional() }).strict(), annotations: readOnly
  }, async input => {
    if (input.kind === 'extensions') return textResult(readEnvironmentSubject(workspaceRoot(), 'extensions', { query: input.query, offset: input.offset, limit: input.limit }));
    if (input.kind === 'mcp') return textResult({ status: 'serving_this_request', observed: true, transport: 'stdio', effects: 'tool-specific', telemetry_effects: 'local metadata-only trace ledger', server: 'pacify-x-governed-context', version: MCP_VERSION, instrumentation: mcpInstrumentation.health() });
    const kind = input.kind === 'connectors' ? 'enterprise-integrations' : input.kind;
    return textResult(runApi(['catalog', '--kind', kind, '--query', input.query || '', '--offset', String(input.offset || 0), '--limit', String(input.limit || 50), '--sort', 'label']));
  });

  registerTool('pacify_environment_inventory', {
    title: 'Pacify-X Environment Capability Map', description: 'Read the hashed semantic graph of detected VS Code extensions, contribution points, system tools, Python packages, and npm packages without activating or installing anything.',
    inputSchema: z.object({ subject: z.enum(['summary', 'graph', 'extensions', 'tools', 'python', 'npm']).optional(), query: z.string().max(300).optional(), offset: z.number().int().nonnegative().optional(), limit: z.number().int().min(1).max(500).optional() }).strict(), annotations: readOnly
  }, async input => textResult(readEnvironmentSubject(workspaceRoot(), input.subject || 'summary', { query: input.query, offset: input.offset, limit: input.limit })));

  registerTool('pacify_environment_extension_detail', {
    title: 'Pacify-X Extension Capability Contract', description: 'Lazy-load one hash-verified extension contract mapping capabilities, commands/APIs, inputs/outputs, permissions/resources, effects, conflicts, policy, and state without activating it.',
    inputSchema: z.object({ extension_id: z.string().min(1).max(200) }).strict(), annotations: readOnly
  }, async input => textResult(readEnvironmentExtension(workspaceRoot(), input.extension_id)));

  registerTool('pacify_catalog_query', {
    title: 'Pacify-X Catalog Query', description: 'Search a bounded page of core catalogs or the separately namespaced MS+Enterprise catalogs.',
    inputSchema: z.object({
      kind: z.enum(['skills', 'tools', 'agents', 'workflows', 'graph', 'enterprise-skills', 'enterprise-agents', 'enterprise-workflows', 'enterprise-integrations', 'enterprise-models']), query: z.string().max(500).optional(),
      status: z.string().max(100).optional(), offset: z.number().int().min(0).optional(), limit: z.number().int().min(1).max(100).optional(),
      sort: z.enum(['id', 'label', 'status', 'kind']).optional()
    }).strict(), annotations: readOnly
  }, async input => textResult(runApi(['catalog', '--kind', input.kind, '--query', input.query || '', '--status', input.status || '', '--offset', String(input.offset || 0), '--limit', String(input.limit || 50), '--sort', input.sort || 'label'])));

  registerTool('pacify_enterprise_status', {
    title: 'Pacify-X MS+Enterprise Status', description: 'Read the separate project enterprise state, offline defaults, pack states, targets, and last readiness receipt.', inputSchema: empty, annotations: readOnly
  }, async () => textResult(initializeEnterprise(workspaceRoot(), enterpriseCatalog())));

  registerTool('pacify_billable_guardrail_evaluate', {
    title: 'Evaluate Pacify-X Billable Guardrails', description: 'Evaluate a proposed provider execution against the separate project policy. This never executes, connects, reads credentials, or incurs cost.',
    inputSchema: z.object({
      provider: z.string().max(160), expected_cost_usd: z.number().nonnegative(), session_spend_usd: z.number().nonnegative().optional(), day_spend_usd: z.number().nonnegative().optional(),
      tokens: z.number().int().nonnegative(), local_available: z.boolean().optional(), route: z.enum(['local', 'provider']).optional(), gpu_memory_mb: z.number().int().nonnegative().optional(),
      cpu_cores: z.number().int().positive().optional(), ram_mb: z.number().int().positive().optional(), escalation_confidence: z.number().min(0).max(1), approval_granted: z.boolean().optional()
    }).strict(), annotations: readOnly
  }, async input => {
    const state = initializeEnterprise(workspaceRoot(), enterpriseCatalog()).state;
    return textResult(evaluateBillableExecution(state.execution_policy, input));
  });

  registerTool('pacify_enterprise_readiness', {
    title: 'Run Pacify-X MS+Enterprise Readiness', description: 'Run the offline readiness doctor and retain a receipt without connecting, reading credentials, mutating a tenant, or enabling billable services.', inputSchema: empty, annotations: write
  }, async () => textResult(enterpriseDoctor(workspaceRoot(), enterpriseCatalog())));

  registerTool('pacify_enterprise_pack_set', {
    title: 'Set Pacify-X Enterprise Pack Metadata State', description: 'Enable or disable only a separate offline enterprise metadata pack. Connector, egress, mutation, credential, and billing gates remain denied.',
    inputSchema: z.object({ pack_id: z.string().min(1).max(160), enabled: z.boolean() }).strict(), annotations: write
  }, async input => textResult(setPackEnabled(workspaceRoot(), enterpriseCatalog(), { packId: input.pack_id, enabled: input.enabled })));

  registerTool('pacify_enterprise_target_configure', {
    title: 'Configure Pacify-X Enterprise Target Aliases', description: 'Store non-secret tenant/environment aliases and explicit auth/billing namespaces in separate enterprise state; no connection is attempted.',
    inputSchema: z.object({ id: z.string().min(1).max(160), pack_id: z.string().min(1).max(160), target_alias: z.string().min(1).max(120), tenant_alias: z.string().min(1).max(120), environment_alias: z.string().min(1).max(120), auth_namespace: z.string().min(1).max(120).optional(), billing_namespace: z.string().min(1).max(120).optional() }).strict(), annotations: write
  }, async input => textResult(configureTarget(workspaceRoot(), enterpriseCatalog(), { id: input.id, packId: input.pack_id, targetAlias: input.target_alias, tenantAlias: input.tenant_alias, environmentAlias: input.environment_alias, authNamespace: input.auth_namespace, billingNamespace: input.billing_namespace })));

  registerTool('pacify_tool_conflict_status', {
    title: 'Pacify-X Tool Conflict Status', description: 'Report the Git and coordination claim conflict boundaries.', inputSchema: empty, annotations: readOnly
  }, async () => {
    const snapshot = contextEnvelope() || {}; const git = snapshot.git || {}; let coord = null;
    try { coord = readCoordination(workspaceRoot()); } catch { coord = null; }
    const blocked = !git.available || (git.operation && git.operation !== 'none') || Number(git.conflicts || 0) > 0;
    return textResult({ blocked, operation: git.operation || 'unknown', conflicts: Number(git.conflicts || 0), authority: 'Git / VS Code Source Control', bridge_git_mutation_allowed: false, active_file_claims: coord?.state?.claims || [], policy: snapshot.git_policy || null });
  });

  registerTool('pacify_coordination_status', {
    title: 'Pacify-X Coordination Status', description: 'Read the project task graph, sessions, leases, claims, state hash, rolling events, and resume paths.', inputSchema: empty, annotations: readOnly
  }, async () => { const value = readCoordination(workspaceRoot(), { eventLimit: 100 }); value.activity = readActivity(workspaceRoot(), { limit: 100, policy: activityPolicy() }); return textResult(value); });

  registerTool('pacify_activity_observability', {
    title: 'Pacify-X Agent Activity Observatory', description: 'Read the local metadata-only trace ledger, active operations, agent presence, correlations, privacy policy, and explicit limitations.',
    inputSchema: z.object({ query: z.string().max(300).optional(), category: z.string().max(80).optional(), status: z.string().max(40).optional(), limit: z.number().int().min(1).max(500).optional() }).strict(), annotations: readOnly
  }, async input => textResult(readActivity(workspaceRoot(), { ...input, policy: activityPolicy() })));

  registerTool('pacify_mcp_instrumentation_status', {
    title: 'Pacify-X MCP Instrumentation Status', description: 'Report registered tool coverage, event drops, identity-attestation classes, and canonical-bus limitations.', inputSchema: empty, annotations: readOnly
  }, async () => textResult(mcpInstrumentation.health()));

  registerTool('pacify_activity_emit', {
    title: 'Emit Pacify-X Agent Activity', description: 'Append one metadata-only correlated activity event. Prompts, file contents, terminal output, credentials, and private reasoning are rejected or redacted.',
    inputSchema: z.object({
      ...actorFields, correlation_id: z.string().min(1).max(200), parent_correlation_id: z.string().max(200).optional(),
      task_id: z.string().max(160).optional(), claim_id: z.string().max(200).optional(),
      category: z.enum(['agent', 'editor', 'filesystem', 'terminal', 'task', 'test', 'debug', 'scm', 'mcp', 'tool', 'retrieval', 'approval', 'verification', 'environment', 'policy', 'system']),
      operation: z.string().min(1).max(200), status: z.enum(['started', 'running', 'succeeded', 'failed', 'cancelled', 'observed', 'blocked', 'idle']),
      effect: z.string().max(120).optional(), scope_refs: z.array(z.string().max(1000)).max(50).optional(), duration_ms: z.number().nonnegative().optional(),
      input_sha256: z.string().regex(/^[a-f0-9]{64}$/i).optional(), output_sha256: z.string().regex(/^[a-f0-9]{64}$/i).optional(),
      metadata: z.record(z.string(), z.union([z.string().max(1000), z.number(), z.boolean(), z.null()])).optional()
    }).strict(), annotations: write
  }, async input => textResult(recordActivity(workspaceRoot(), actor(input), input, activityPolicy())));

  registerTool('pacify_memory_observability', {
    title: 'Pacify-X Portable Memory Observability',
    description: 'Read bounded, project-scoped coordination-memory telemetry and records. This source is non-canonical; proposed and candidate records never override certified vault memory.',
    inputSchema: z.object({ query: z.string().max(500).optional(), limit: z.number().int().min(1).max(100).optional(), include_content: z.boolean().optional() }).strict(),
    annotations: readOnly
  }, async input => textResult(readMemoryTelemetry(workspaceRoot(), { query: input.query, limit: input.limit, includeContent: input.include_content === true })));

  registerTool('pacify_resume_handoff', {
    title: 'Pacify-X Resume Handoff', description: 'Return the verified cross-IDE resume packet produced from the project-owned rolling ledger.', inputSchema: empty, annotations: readOnly
  }, async () => {
    const data = readCoordination(workspaceRoot(), { eventLimit: 20 });
    return textResult(readJsonFile(data.paths.handoff_json, { available: false, reason: 'No handoff packet exists yet.', coordination: data.state }));
  });

  registerTool('pacify_task_handoff', {
    title: 'Pacify-X Task Handoff', description: 'Return one task, its dependencies, claims, state hash, and execution rules for dispatch to another IDE or agent.',
    inputSchema: z.object({ task_id: z.string().min(1).max(160) }).strict(), annotations: readOnly
  }, async input => textResult(taskHandoff(workspaceRoot(), input.task_id)));

  registerTool('pacify_parallel_plan_create', {
    title: 'Create Pacify-X Parallel Plan', description: 'Write a dependency DAG only after rejecting unordered overlapping file/area claims.',
    inputSchema: z.object({
      ...actorFields, objective: z.string().min(1).max(4000),
      tasks: z.array(z.object({
        id: z.string().min(1).max(160), title: z.string().min(1).max(300), description: z.string().max(4000).optional(),
        depends_on: z.array(z.string().max(160)).optional(), claims: z.array(z.string().max(512)).min(1),
        read_scopes: z.array(z.string().max(512)).optional(), write_scopes: z.array(z.string().max(512)).optional(), effect_scopes: z.array(z.string().max(120)).optional(),
        goal_context: z.array(z.string().max(1000)).optional(), budget: z.object({ max_minutes: z.number().nonnegative().optional(), max_tokens: z.number().nonnegative().optional(), max_cost_usd: z.number().nonnegative().optional(), hard_stop: z.boolean().optional() }).strict().optional(),
        harness: z.string().max(120).optional(), agent: z.string().max(200).optional(), acceptance: z.array(z.string().max(1000)).optional()
      }).strict()).min(1).max(250)
    }).strict(), annotations: write
  }, async input => textResult(createParallelPlan(workspaceRoot(), actor(input), { objective: input.objective, tasks: input.tasks })));

  registerTool('pacify_task_claim', {
    title: 'Claim Pacify-X Task', description: 'Atomically claim one dependency-ready task and its non-overlapping file/area scope with a bounded lease.',
    inputSchema: z.object({ ...actorFields, task_id: z.string().min(1).max(160), claim_targets: z.array(z.string().max(512)).optional(), ttl_minutes: z.number().int().min(5).max(1440).optional(), mode: z.enum(['exclusive', 'shared', 'informational']).optional(), authority: z.enum(['local', 'speculative']).optional() }).strict(), annotations: write
  }, async input => textResult(claimTask(workspaceRoot(), actor(input), input)));

  registerTool('pacify_claim_renew', {
    title: 'Renew Pacify-X Claim', description: 'Renew an owned active lease only when the supplied target fencing tokens are current.',
    inputSchema: z.object({ ...actorFields, claim_id: z.string().min(1).max(200), fencing_tokens: z.record(z.string(), z.number().int().positive()), ttl_minutes: z.number().int().min(5).max(1440).optional() }).strict(), annotations: write
  }, async input => textResult(renewClaim(workspaceRoot(), actor(input), input)));

  registerTool('pacify_task_progress', {
    title: 'Record Pacify-X Task Progress', description: 'Append a progress receipt for the owning task actor.',
    inputSchema: z.object({ ...actorFields, task_id: z.string().min(1).max(160), status: z.enum(['claimed', 'in_progress', 'waiting', 'blocked', 'completed']), summary: z.string().max(4000), files_changed: z.array(z.string().max(512)).optional(), evidence: z.array(z.string().max(1000)).optional(), next_action: z.string().max(2000).optional(), fencing_tokens: z.record(z.string(), z.number().int().positive()).optional(), usage: z.object({ minutes: z.number().nonnegative().optional(), tokens: z.number().nonnegative().optional(), cost_usd: z.number().nonnegative().optional() }).strict().optional() }).strict(), annotations: write
  }, async input => textResult(recordProgress(workspaceRoot(), actor(input), input)));

  registerTool('pacify_task_reconcile', {
    title: 'Reconcile Pacify-X Task', description: 'Finalize a completed task, append its merge/conflict receipt, and release its active claim.',
    inputSchema: z.object({ ...actorFields, task_id: z.string().min(1).max(160), summary: z.string().max(4000), evidence: z.array(z.string().max(1000)).optional(), conflicts_resolved: z.boolean(), merge_owner: z.string().max(200).optional() }).strict(), annotations: write
  }, async input => textResult(reconcileTask(workspaceRoot(), actor(input), input)));

  registerTool('pacify_task_release', {
    title: 'Release Pacify-X Task', description: 'Explicitly release a task lease and its claims without deleting its evidence history.',
    inputSchema: z.object({ ...actorFields, task_id: z.string().min(1).max(160), reason: z.string().max(1000).optional() }).strict(), annotations: write
  }, async input => textResult(releaseTask(workspaceRoot(), actor(input), input)));

  registerTool('pacify_memory_capture', {
    title: 'Capture Pacify-X Layered Memory', description: 'Append a concise project-scoped memory record. System entries are always candidates, never auto-promoted.',
    inputSchema: z.object({
      ...actorFields, layer: z.enum(['session', 'project', 'state', 'system_candidate']), kind: z.string().max(80),
      content: z.string().min(1).max(6000), epistemic_status: z.enum(['observation', 'inference']).optional(),
      confidence: z.number().min(0).max(1).optional(), confidence_method: z.string().max(160).optional(),
      source_artifact: z.string().max(1000).optional(), source_hash: z.string().regex(/^[a-f0-9]{64}$/i).optional(), evidence_locator: z.string().max(1000).optional()
    }).strict(), annotations: write
  }, async input => textResult(captureMemory(workspaceRoot(), actor(input), input)));

  registerTool('pacify_work_stop_diagnostics', {
    title: 'Diagnose Stopped Pacify-X Work', description: 'Classify task, dependency, worker, lease, and budget stop boundaries before retry.',
    inputSchema: z.object({ task_id: z.string().min(1).max(160) }).strict(), annotations: readOnly
  }, async input => textResult(diagnoseWorkStop(workspaceRoot(), input.task_id)));

  registerTool('pacify_work_room', {
    title: 'Pacify-X Derived Work Room', description: 'Return a non-authoritative task/project/branch collaboration view over canonical coordination events.',
    inputSchema: z.object({ task_id: z.string().min(1).max(160) }).strict(), annotations: readOnly
  }, async input => textResult(workRoom(workspaceRoot(), input.task_id)));

  registerTool('pacify_worker_adapter_doctor', {
    title: 'Pacify-X Worker Adapter Doctor', description: 'Report local worker adapter readiness while keeping executor, authentication, billing, and native sessions separate.',
    inputSchema: empty, annotations: readOnly
  }, async () => textResult(workerAdapters({ workspaceRoot: workspaceRoot(), extensionRoot: process.cwd(), appName: process.env.PX_HOST_NAME || 'stdio MCP', codexAuthenticated: false, ollamaEnabled: false })));

  registerTool('pacify_team_pack_preview', {
    title: 'Preview Pacify-X Team Package', description: 'Inventory and hash an admitted Agent Companies/Team Fabric package without changing canonical state.',
    inputSchema: z.object({ source_root: z.string().min(1).max(2000), existing_ids: z.array(z.string().max(160)).optional() }).strict(), annotations: readOnly
  }, async input => textResult(inventoryTeamPack(admittedTeamPackRoot(input.source_root), input.existing_ids || [])));

  registerTool('pacify_team_pack_stage', {
    title: 'Stage Pacify-X Team Package Candidates', description: 'Re-inventory an admitted package and stage selected metadata as non-canonical candidates with a receipt.',
    inputSchema: z.object({ source_root: z.string().min(1).max(2000), existing_ids: z.array(z.string().max(160)).optional(), selection: z.array(z.string().max(340)).optional(), collision_mode: z.enum(['skip', 'rename', 'replace-candidate-only']).optional() }).strict(), annotations: write
  }, async input => {
    const preview = inventoryTeamPack(admittedTeamPackRoot(input.source_root), input.existing_ids || []);
    return textResult(stageTeamPack(workspaceRoot(), preview, { selection: input.selection, collisionMode: input.collision_mode }));
  });

  return server;
}

serveStdio(buildServer, { onerror: error => process.stderr.write(`[pacify-x-mcp] ${error.message}\n`) });
