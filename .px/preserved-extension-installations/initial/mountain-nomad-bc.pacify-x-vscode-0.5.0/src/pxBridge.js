'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const { nonBillableEnvironment } = require('./contextBridge');

const MAX_OUTPUT_BYTES = 32 * 1024 * 1024;

function isEngineRoot(candidate) {
  return Boolean(candidate && fs.existsSync(path.join(candidate, 'runtime', 'dashboard_api.py')) && fs.existsSync(path.join(candidate, 'registry')));
}

function findEngineRoot(configured, workspaceFolders = []) {
  for (const candidate of [configured, ...workspaceFolders].filter(Boolean)) {
    let cursor = path.resolve(candidate);
    try { if (fs.statSync(cursor).isFile()) cursor = path.dirname(cursor); } catch { continue; }
    for (let depth = 0; depth < 12; depth += 1) {
      if (isEngineRoot(cursor)) return cursor;
      const parent = path.dirname(cursor); if (parent === cursor) break; cursor = parent;
    }
  }
  return undefined;
}

function captureJson(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = cp.spawn(command, args, {
      cwd: options.cwd, shell: false, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...nonBillableEnvironment(), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' }
    });
    let stdout = ''; let stderr = ''; let settled = false;
    const finish = (error, value) => {
      if (settled) return; settled = true; clearTimeout(timer);
      if (error) reject(error); else resolve(value);
    };
    const timer = setTimeout(() => { child.kill(); finish(new Error('Pacify-X dashboard API timed out.')); }, options.timeoutMs || 30_000);
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      stdout += chunk;
      if (Buffer.byteLength(stdout, 'utf8') > MAX_OUTPUT_BYTES) { child.kill(); finish(new Error('Pacify-X dashboard API exceeded its bounded output limit.')); }
    });
    child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-200_000); });
    child.on('error', error => finish(error));
    child.on('close', code => {
      if (settled) return;
      if (code !== 0) { finish(new Error(stderr.trim() || `Pacify-X dashboard API exited ${code}.`)); return; }
      try { finish(null, JSON.parse(stdout)); } catch (error) { finish(new Error(`Pacify-X returned invalid dashboard JSON: ${error.message}`)); }
    });
  });
}

function authorityMap(connected) {
  const core = connected ? 'implemented' : 'unavailable';
  return [
    { capability: 'Dashboard normalization', owner: 'runtime.dashboard_api', status: core, exposure: 'versioned snapshot + lazy catalogs' },
    { capability: 'Project/control-plane state', owner: 'Pacify-X Python runtime', status: core, exposure: 'first-class typed client' },
    { capability: 'Skills and tool admission', owner: 'Pacify-X registries + admission controller', status: core, exposure: 'complete paged catalog' },
    { capability: 'Agent fleet inventory', owner: 'runtime.agent_provider', status: core, exposure: 'complete paged catalog' },
    { capability: 'Workflow orchestration', owner: 'Pacify-X workflow authorities', status: core, exposure: 'orchestrations + bindings' },
    { capability: 'Cross-IDE coordination', owner: 'Pacify-X extension coordination controller', status: connected ? 'implemented' : 'unavailable', exposure: 'project ledger + MCP' },
    { capability: 'Canonical memory', owner: 'memory fabric/vault/intelligence', status: core, exposure: 'telemetry + references only' },
    { capability: 'TurboVec retrieval', owner: 'Optional derived accelerator', status: 'candidate-not-wired', exposure: 'deterministic fallback active' },
    { capability: 'Git repository state', owner: 'Git / VS Code Source Control', status: 'implemented', exposure: 'read-only conflict boundary' },
    { capability: 'Cleanup', owner: 'Extension safe cleanup + resource lifecycle', status: 'implemented', exposure: 'preview + confirm + receipt' }
  ];
}

function disconnected(reason) {
  return {
    generatedAt: new Date().toISOString(), connected: false, reason,
    source: { version: 'unavailable', engineRoot: null, mode: 'disconnected' },
    project: { name: 'No Pacify-X root detected', path: null, branch: 'unavailable' },
    counts: {}, registries: {}, attention: [{ severity: 'warning', title: 'Engine root unavailable', detail: reason }],
    authorities: authorityMap(false), storage: { instrumented: false }, validation: { status: 'not-run', detail: 'Connect an engine root before validation.' },
    runtime: {}, memory: {}, coordination: { instrumented: false }, readiness: { assessment: 'unavailable', dimensions: [], summary: {}, maturity: { level: 0, label: 'Unavailable', readiness_ceiling: 0 } }, catalogSource: 'unavailable'
  };
}

function normalizeSnapshot(raw) {
  const counts = raw.counts || {};
  return {
    schemaVersion: raw.schema_version, generatedAt: raw.generated_at, connected: Boolean(raw.connected),
    source: { version: raw.source?.version || 'unknown', engineRoot: raw.source?.root || null, mode: raw.mode || 'canonical-dashboard-api', commit: raw.source?.commit || null },
    project: { ...(raw.project || {}), branch: raw.project?.branch || raw.source?.branch || 'unknown' },
    counts: {
      ...counts, workflows: counts.orchestrations_total || 0, knowledgeSources: counts.knowledge_sources || 0,
      graphRecords: counts.graph_records || 0, graphEdges: counts.graph_edges || 0
    },
    registries: {
      skills: { count: counts.skills || 0, available: true }, tools: { count: counts.tools || 0, available: true },
      agents: { count: counts.agents || 0, available: true }, workflows: { count: counts.orchestrations_total || 0, available: true },
      knowledge: { count: counts.knowledge_sources || 0, available: true }, models: { count: counts.models || 0, available: true },
      assurance: { count: counts.assurance || 0, available: true }, effects: { count: counts.effects || 0, available: true },
      graph: { count: counts.graph_records || 0, edges: counts.graph_edges || 0, available: true, modified: raw.generated_at }
    },
    attention: raw.attention || [], authorities: authorityMap(Boolean(raw.connected)), memory: raw.memory || {},
    coordination: raw.coordination || { instrumented: false }, runtime: raw.runtime || {},
    readiness: raw.readiness || { assessment: 'unavailable', dimensions: [], summary: {}, maturity: { level: 0, label: 'Unavailable', readiness_ceiling: 0 } },
    enterprise: raw.enterprise || { catalog_id: null, packs: [], connectors: [], models: [], defaults: {}, separation: {} },
    storage: { instrumented: Boolean(raw.memory?.instrumented), bytes: raw.memory?.bytes, files: null, bounded: false },
    validation: { status: 'not-run', detail: 'Validation is explicit and runs through the Pacify-X CLI.' },
    catalogSource: 'runtime.dashboard_api', provenance: raw.provenance || {}
  };
}

class PxBridge {
  constructor({ pythonPath = 'python', engineRoot, projectRoot, workspaceRoot }) {
    this.pythonPath = pythonPath; this.engineRoot = engineRoot; this.projectRoot = projectRoot; this.workspaceRoot = workspaceRoot;
    this.snapshotPromise = null; this.lastSnapshot = null; this.lastSnapshotAt = 0;
  }

  update(options) { Object.assign(this, options); }

  async snapshot({ force = false } = {}) {
    if (!isEngineRoot(this.engineRoot)) return disconnected('Set pacifyX.engineRoot to a Pacify-X source tree containing runtime/dashboard_api.py.');
    if (!force && this.lastSnapshot && Date.now() - this.lastSnapshotAt < 3000) return this.lastSnapshot;
    if (this.snapshotPromise) return this.snapshotPromise;
    const args = ['-m', 'runtime.dashboard_api', 'snapshot', '--source-root', this.engineRoot];
    if (this.projectRoot) args.push('--project', this.projectRoot);
    if (this.workspaceRoot) args.push('--workspace-root', this.workspaceRoot);
    this.snapshotPromise = captureJson(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 30_000 })
      .then(raw => { this.lastSnapshot = normalizeSnapshot(raw); this.lastSnapshotAt = Date.now(); return this.lastSnapshot; })
      .finally(() => { this.snapshotPromise = null; });
    return this.snapshotPromise;
  }

  async catalog(input) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const kind = String(input.kind || '');
    if (!['skills', 'tools', 'agents', 'workflows', 'graph', 'enterprise-skills', 'enterprise-agents', 'enterprise-workflows', 'enterprise-integrations', 'enterprise-models'].includes(kind)) throw new Error('Unsupported catalog kind.');
    const args = ['-m', 'runtime.dashboard_api', 'catalog', '--source-root', this.engineRoot, '--kind', kind,
      '--query', String(input.query || '').slice(0, 500), '--status', String(input.status || '').slice(0, 100),
      '--offset', String(Math.max(0, Number(input.offset || 0))), '--limit', String(Math.max(1, Math.min(100, Number(input.limit || 50)))),
      '--sort', ['id', 'label', 'status', 'kind'].includes(input.sort) ? input.sort : 'label'];
    return captureJson(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 30_000 });
  }

  async graph(input = {}) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const direction = ['incoming', 'outgoing', 'both'].includes(input.direction) ? input.direction : 'both';
    const args = ['-m', 'runtime.dashboard_api', 'graph', '--source-root', this.engineRoot,
      '--view', input.view === 'repository' ? 'repository' : 'capabilities',
      '--node', String(input.node || '').slice(0, 500), '--query', String(input.query || '').slice(0, 500),
      '--relation', String(input.relation || '').slice(0, 160), '--direction', direction,
      '--depth', String(Math.max(1, Math.min(2, Number(input.depth || 1)))),
      '--max-nodes', String(Math.max(2, Math.min(50, Number(input.maxNodes || 24)))),
      '--max-edges', String(Math.max(1, Math.min(100, Number(input.maxEdges || 48))))];
    if (this.projectRoot) args.push('--project', this.projectRoot);
    return captureJson(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 30_000 });
  }
}

module.exports = { isEngineRoot, findEngineRoot, captureJson, normalizeSnapshot, disconnected, authorityMap, PxBridge };
