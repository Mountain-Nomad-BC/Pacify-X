'use strict';

const cp = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const STUDIO_PROTOCOL = require('../resources/studio-operations.json');
const { nonBillableEnvironment } = require('./contextBridge');
const { processTreeSpawnOptions, terminateProcessTree } = require('./processTree');
const { createHealthState } = require('./healthState');
const { WorkGovernor } = require('./workGovernor');
const { RevisionStore, MetadataCache } = require('./runtimeRevisions');
const { approvalPayloadJson, signClaim, validMaterial } = require('./studioApprovalHost');
const { collectStudioCatalog, filterStudioItems, normalizeSkillCatalogPage } = require('./studioCatalog');

const MAX_OUTPUT_BYTES = 32 * 1024 * 1024;
const MAX_INLINE_FINGERPRINT_BYTES = 1024 * 1024;
const MAX_WATCH_SENTINEL_BYTES = 4 * 1024 * 1024;
const DEFAULT_SNAPSHOT_TTL_MS = 60_000;
const SNAPSHOT_FINGERPRINT_PATHS = Object.freeze([
  'pyproject.toml',
  'runtime/dashboard_api.py',
  'runtime/knowledge_core_controller.py',
  'runtime/learning_promotion.py',
  'runtime/studio_api.py',
  'policies/learning-promotion.json',
  'registry/skill_packages',
  'registry/tools.json',
  'registry/agency_agent_registry.json',
  'registry/project_stream_orchestrations.json',
  'registry/skill_orchestrations.json',
  'registry/workflow_execution_bindings.json',
  'registry/cognitive_map_index.json',
  'registry/knowledge_sources.json',
  'registry/models.json',
  'registry/integrations.json',
  'registry/assurance_capabilities.json',
  'registry/effect_surface_ownership.json',
  'registry/ms_enterprise_catalog.json',
  'registry/provider_budget_policy.json',
  'registry/provider_adapters.json',
  'registry/completion_status.json',
  'registry/operational_surface_audit_20260816.json',
  'extension/package.json',
  'extension/src',
  'extension/media/dashboard',
  'extension/media/styles',
  '.engineering-bootstrap/provider-budget/ledger.json',
  '.engineering-bootstrap/project-map/architecture-graph.json'
]);
const STUDIO_READ_ONLY_OPERATIONS = new Set([
  'agent:identity-absence', 'agent:next-version', 'agent:preview', 'agent:runs', 'agent:status',
  'workflow:identity-absence', 'workflow:next-version', 'workflow:dry-run', 'workflow:runs', 'workflow:status',
  'skill:identity-absence', 'skill:next-version', 'knowledge:browse'
]);

function clone(value) { return typeof structuredClone === 'function' ? structuredClone(value) : JSON.parse(JSON.stringify(value)); }

function pathWithin(candidate, root) {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative === '' || (!path.isAbsolute(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`));
}

function snapshotSourceRevision(engineRoot, projectRoot, workspaceRoot, contentMode) {
  const records = [];
  const includeContent = contentMode === true || contentMode === 'complete';
  const includeDirectSentinel = contentMode === 'sentinel';
  let sentinelBytes = 0;
  const sentinelContentLimit = includeDirectSentinel ? BigInt(MAX_WATCH_SENTINEL_BYTES) : BigInt(MAX_INLINE_FINGERPRINT_BYTES);
  const contentSentinelLimit = includeDirectSentinel ? BigInt(MAX_WATCH_SENTINEL_BYTES) : BigInt(MAX_INLINE_FINGERPRINT_BYTES);
  const inspect = (root, relative) => {
    if (!root) return;
    const target = path.join(root, relative);
    try {
      const stat = fs.lstatSync(target, { bigint: true });
      let contentRevision = null;
      const directBytes = Number(stat.size);
      const directContentAllowed = stat.isFile()
        && stat.size <= sentinelContentLimit
        && (includeContent || (includeDirectSentinel && sentinelBytes + directBytes <= MAX_WATCH_SENTINEL_BYTES));
      if (directContentAllowed) {
        contentRevision = crypto.createHash('sha256').update(fs.readFileSync(target)).digest('hex');
        if (includeDirectSentinel) sentinelBytes += directBytes;
      }
      records.push([
        path.resolve(root), relative, stat.isDirectory() ? 'directory' : 'file',
        stat.size.toString(), stat.mtimeNs.toString(), stat.ctimeNs.toString(), contentRevision
      ]);
      if (stat.isDirectory() && !stat.isSymbolicLink()) {
        const pending = [[target, relative]]; let visited = 0; let inlineBytes = 0;
        while (pending.length && visited < 10_000) {
          const [directory, directoryRelative] = pending.shift();
          let children;
          try { children = fs.readdirSync(directory, { withFileTypes: true }).sort((left, right) => left.name.localeCompare(right.name)); }
          catch (error) { records.push([path.resolve(root), directoryRelative, 'unreadable', error?.code || 'unavailable']); continue; }
          for (const child of children) {
            if (visited++ >= 10_000) break;
            const childTarget = path.join(directory, child.name); const childRelative = path.join(directoryRelative, child.name).replaceAll('\\', '/');
            try {
              const childStat = fs.lstatSync(childTarget, { bigint: true });
              if (childStat.isSymbolicLink()) { records.push([path.resolve(root), childRelative, 'link-refused']); continue; }
              let childRevision = null;
              if ((includeContent || includeDirectSentinel) && childStat.isFile() && childStat.size <= contentSentinelLimit && inlineBytes + Number(childStat.size) <= 4 * MAX_INLINE_FINGERPRINT_BYTES) {
                childRevision = crypto.createHash('sha256').update(fs.readFileSync(childTarget)).digest('hex'); inlineBytes += Number(childStat.size);
                if (includeDirectSentinel) sentinelBytes += Number(childStat.size);
              }
              records.push([path.resolve(root), childRelative, childStat.isDirectory() ? 'directory' : childStat.isFile() ? 'file' : 'other', childStat.size.toString(), childStat.mtimeNs.toString(), childStat.ctimeNs.toString(), childRevision]);
              if (childStat.isDirectory()) pending.push([childTarget, childRelative]);
            } catch (error) { records.push([path.resolve(root), childRelative, 'unavailable', error?.code || 'unavailable']); }
          }
        }
        if (pending.length) records.push([path.resolve(root), relative, 'directory-fingerprint-truncated', String(visited)]);
      }
    } catch (error) {
      records.push([path.resolve(root), relative, 'missing', error?.code || 'unavailable']);
    }
  };
  for (const relative of SNAPSHOT_FINGERPRINT_PATHS) inspect(engineRoot, relative);
  inspect(projectRoot, '.engineering-bootstrap/project-map/architecture-graph.json');
  inspect(projectRoot, '.engineering-bootstrap/studios');
  inspect(projectRoot, '.px/skill-index.json');
  inspect(projectRoot, '.px/skills');
  inspect(workspaceRoot, 'projects_tracking/project-registry.json');
  inspect(workspaceRoot, 'projects_tracking/events/events.jsonl');
  return crypto.createHash('sha256').update(JSON.stringify(records)).digest('hex');
}

function snapshotSourceFingerprint(engineRoot, projectRoot, workspaceRoot) {
  return snapshotSourceRevision(engineRoot, projectRoot, workspaceRoot, true);
}

function snapshotSourceWatchStamp(engineRoot, projectRoot, workspaceRoot) {
  // The stamp walks the exact same bounded roots and entry cap as the complete
  // fingerprint. Directory children remain metadata-only; direct watched files
  // receive at most 4 MiB of deterministic content sentinels so same-size writes
  // cannot hide inside filesystem timestamp granularity. It is rebuilt for every
  // refresh request and is a change guard, never a timed blind memo.
  return snapshotSourceRevision(engineRoot, projectRoot, workspaceRoot, 'sentinel');
}

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

const STUDIO_VERSION_CONFLICT_REASONS = Object.freeze([
  'allocation-binding-mismatch',
  'allocation-envelope-invalid',
  'allocation-exhausted',
  'allocation-probe-bound-exhausted',
  'allocation-source-invalid',
  'allocation-stale',
  'external-source-invalid',
  'external-source-not-allowed',
  'immutable-agent-receipt-missing',
  'immutable-agent-revision-differs',
  'immutable-revision-differs',
  'immutable-skill-revision-differs',
  'immutable-workflow-revision-differs',
  'initial-identity-occupied',
  'initial-version-invalid',
  'occupancy-bound-exceeded',
  'publication-collision',
  'revision-already-occupied',
  'source-content-bound-exceeded',
  'source-revision-invalid',
  'source-revision-mismatch',
  'source-revision-missing'
]);
const STUDIO_VERSION_CONFLICT_REASON_SET = new Set(STUDIO_VERSION_CONFLICT_REASONS);

function exactStudioVersionConflictEnvelope(value) {
  const keys = Object.keys(value || {}).sort();
  return keys.join('\0') === ['code', 'reason', 'schema_version'].sort().join('\0')
    && value.schema_version === 'px.studio-operation-error/1.0'
    && value.code === 'STUDIO_VERSION_CONFLICT'
    && typeof value.reason === 'string'
    && STUDIO_VERSION_CONFLICT_REASON_SET.has(value.reason);
}

function exactStudioVersionConflictError(error) {
  return error instanceof Error
    && exactStudioVersionConflictEnvelope(error.studioError)
    && error.code === error.studioError.code
    && error.reason === error.studioError.reason
    && error.message === `studio-version-conflict:${error.studioError.reason}`;
}

function studioProcessError(stderr, exitCode) {
  const text = String(stderr || '').trim();
  try {
    const envelope = JSON.parse(text);
    if (exitCode === 2 && exactStudioVersionConflictEnvelope(envelope)) {
      return Object.assign(new Error(`studio-version-conflict:${envelope.reason}`), { code: envelope.code, reason: envelope.reason, studioError: envelope });
    }
  } catch { /* Non-Studio failures retain their bounded stderr diagnostic. */ }
  return new Error(text || `Pacify-X dashboard API exited ${exitCode}.`);
}

function captureJson(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = cp.spawn(command, args, {
      cwd: options.cwd, shell: false, windowsHide: true, stdio: [options.input === undefined ? 'ignore' : 'pipe', 'pipe', 'pipe'],
      ...processTreeSpawnOptions(),
      env: { ...nonBillableEnvironment(), ...(options.environment || {}), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' }
    });
    let stdout = ''; let stderr = ''; let settled = false;
    const onAbort = () => { terminateProcessTree(child); finish(Object.assign(new Error('Pacify-X dashboard API request was superseded.'), { name: 'AbortError' })); };
    const finish = (error, value) => {
      if (settled) return; settled = true; clearTimeout(timer);
      options.signal?.removeEventListener?.('abort', onAbort);
      if (error) reject(error); else resolve(value);
    };
    const timer = setTimeout(() => { terminateProcessTree(child); finish(new Error('Pacify-X dashboard API timed out.')); }, options.timeoutMs || 30_000);
    if (options.signal?.aborted) { onAbort(); return; }
    options.signal?.addEventListener?.('abort', onAbort, { once: true });
    if (options.input !== undefined) child.stdin.end(options.input);
    child.stdout.setEncoding('utf8'); child.stderr.setEncoding('utf8');
    child.stdout.on('data', chunk => {
      stdout += chunk;
      if (Buffer.byteLength(stdout, 'utf8') > MAX_OUTPUT_BYTES) { terminateProcessTree(child); finish(new Error('Pacify-X dashboard API exceeded its bounded output limit.')); }
    });
    child.stderr.on('data', chunk => { stderr = (stderr + chunk).slice(-200_000); });
    child.on('error', error => finish(error));
    child.on('close', code => {
      if (settled) return;
      if (code !== 0) { finish(studioProcessError(stderr, code)); return; }
      try { finish(null, JSON.parse(stdout)); } catch (error) { finish(new Error(`Pacify-X returned invalid dashboard JSON: ${error.message}`)); }
    });
  });
}

function authorityMap(connected, snapshot = {}) {
  const counts = snapshot.counts || {}; const memory = snapshot.memory || {};
  const mapReady = snapshot.project?.map?.valid === true;
  const memoryState = memory.retrieval_ready === true ? 'ready' : memory.status === 'detached' ? 'detached' : memory.instrumented ? 'observed' : 'unconfigured';
  return [
    { capability: 'Dashboard normalization', owner: 'runtime.dashboard_api', status: connected ? 'connected' : 'unavailable', exposure: 'versioned snapshot + lazy catalogs' },
    { capability: 'Project/control-plane state', owner: 'Pacify-X Python runtime', status: mapReady ? 'map-observed' : 'map-unavailable', exposure: 'active project only; project management remains incomplete' },
    { capability: 'Skills and tool admission', owner: 'Pacify-X registries + admission controller', status: counts.skills ? 'catalog-observed' : 'unavailable', exposure: 'paged catalog; lifecycle state varies per record' },
    { capability: 'Agent fleet inventory', owner: 'runtime.agent_provider', status: counts.agents_runnable_revisions > 0 ? 'runnable-revisions-present' : 'catalog-only', exposure: `${Number(counts.agents_runnable_revisions || 0)} runnable revisions; ${Number(counts.agents_running || 0)} running` },
    { capability: 'Workflow orchestration', owner: 'Pacify-X workflow authorities', status: counts.workflow_runnable_revisions > 0 ? 'runnable-revisions-present' : 'definitions-only', exposure: `${Number(counts.workflow_runnable_revisions || 0)} runnable revisions; ${Number(counts.workflow_runs || 0)} runs` },
    { capability: 'Cross-IDE coordination', owner: 'Pacify-X extension coordination controller', status: connected ? 'controller-present' : 'unavailable', exposure: 'project ledger availability is reported separately' },
    { capability: 'Canonical memory', owner: 'memory fabric/vault/intelligence', status: memoryState, exposure: memory.error || 'lease-bound retrieval telemetry' },
    { capability: 'TurboVec retrieval', owner: 'Optional derived accelerator', status: 'candidate-not-wired', exposure: 'deterministic fallback active' },
    { capability: 'Git repository state', owner: 'Git / VS Code Source Control', status: 'observed', exposure: 'read-only conflict boundary' },
    { capability: 'Cleanup', owner: 'Extension safe cleanup + resource lifecycle', status: 'controller-present', exposure: 'preview + confirm + receipt; no completion inferred' }
  ];
}

function disconnected(reason) {
  return {
    generatedAt: new Date().toISOString(), connected: false, reason,
    health: createHealthState({ configured: false, detected: false, connected: false, authoritative: false, ready: false, reason }),
    source: { version: 'unavailable', engineRoot: null, mode: 'disconnected' },
    project: { name: 'No Pacify-X root detected', path: null, branch: 'unavailable' },
    counts: {}, registries: {}, attention: [{ severity: 'warning', title: 'Engine root unavailable', detail: reason }],
    authorities: authorityMap(false), storage: { instrumented: false }, validation: { status: 'not-run', detail: 'Connect an engine root before validation.' },
    runtime: {}, memory: {}, coordination: { instrumented: false }, readiness: { assessment: 'unavailable', dimensions: [], summary: {}, maturity: { level: 0, label: 'Unavailable', readiness_ceiling: 0 } }, catalogSource: 'unavailable'
  };
}

function normalizeSnapshot(raw) {
  const counts = raw.counts || {};
  const connected = Boolean(raw.connected);
  const authoritative = connected && (raw.mode === 'canonical-dashboard-api' || raw.mode === 'canonical');
  return {
    schemaVersion: raw.schema_version, generatedAt: raw.generated_at, connected,
    health: createHealthState({ configured: true, detected: true, connected, authoritative, ready: false, reason: raw.reason, observed_at: raw.generated_at }),
    source: { version: raw.source?.version || 'unknown', engineRoot: raw.source?.root || null, mode: raw.mode || 'canonical-dashboard-api', commit: raw.source?.commit || null },
    project: { ...(raw.project || {}), branch: raw.project?.branch || raw.source?.branch || 'unknown' },
    counts: {
      ...counts, workflows: counts.workflow_definitions || 0, workflowArtifacts: counts.orchestrations_total || 0, knowledgeSources: counts.knowledge_sources || 0,
      graphRecords: counts.graph_records || 0, graphEdges: counts.graph_edges || 0
    },
    registries: {
      skills: { count: counts.skills || 0, available: true }, tools: { count: counts.tools || 0, available: true },
      agents: { count: counts.agents || 0, available: true }, workflows: { count: counts.workflow_definitions || 0, available: true },
      knowledge: { count: counts.knowledge_sources || 0, available: true }, models: { count: counts.models || 0, available: true },
      assurance: { count: counts.assurance || 0, available: true }, effects: { count: counts.effects || 0, available: true },
      graph: { count: counts.graph_records || 0, edges: counts.graph_edges || 0, available: true, modified: raw.generated_at }
    },
    attention: raw.attention || [], authorities: authorityMap(connected, raw), memory: raw.memory || {}, knowledgeCore: raw.knowledge_core || {}, extensionSourceIdentity: raw.extension_identity || {},
    completion: raw.completion || {},
    providerActivity: Array.isArray(raw.providerActivity) ? raw.providerActivity : [],
    coordination: raw.coordination || { instrumented: false }, runtime: raw.runtime || {},
    readiness: raw.readiness || { assessment: 'unavailable', dimensions: [], summary: {}, maturity: { level: 0, label: 'Unavailable', readiness_ceiling: 0 } },
    enterprise: raw.enterprise || { catalog_id: null, packs: [], connectors: [], models: [], defaults: {}, separation: {} },
    storage: { instrumented: Boolean(raw.memory?.instrumented), bytes: raw.memory?.bytes, files: null, bounded: false },
    validation: { status: 'not-run', detail: 'Validation is explicit and runs through the Pacify-X CLI.' },
    catalogSource: 'runtime.dashboard_api', provenance: raw.provenance || {}
  };
}

class PxBridge {
  constructor({ pythonPath = 'python', engineRoot, projectRoot, workspaceRoot, cacheTtlMs = DEFAULT_SNAPSHOT_TTL_MS, governor, capture = captureJson, now = Date.now, cacheStore = null, approvalKeyProvider = null, approvalRecoveryProvider = null } = {}) {
    this.pythonPath = pythonPath; this.engineRoot = engineRoot; this.projectRoot = projectRoot; this.workspaceRoot = workspaceRoot;
    this.cacheTtlMs = Math.max(5000, Math.min(5 * 60_000, Number(cacheTtlMs) || DEFAULT_SNAPSHOT_TTL_MS));
    this.capture = capture; this.now = now;
    this.governor = governor || new WorkGovernor(); this.ownsGovernor = !governor;
    this.revisions = new RevisionStore({ now });
    this.metadataCache = new MetadataCache({ store: cacheStore, now, maximumEntries: 16 });
    this.approvalKeyProvider = approvalKeyProvider;
    this.approvalRecoveryProvider = approvalRecoveryProvider;
    this.requestCache = new Map();
    this.requestCacheMetrics = { hits: 0, misses: 0, evictions: 0 };
    this.fingerprintMemo = { watchStamp: null, value: null };
    this.fingerprintMetrics = { watchScans: 0, completeScans: 0, guardedReuses: 0 };
    this.lastSnapshot = null; this.lastSnapshotAt = 0; this.lastFingerprint = null; this.lastInvalidationReason = 'cold-start';
  }

  update(options) {
    const before = [this.pythonPath, this.engineRoot, this.projectRoot, this.workspaceRoot].join('\0');
    Object.assign(this, options);
    const after = [this.pythonPath, this.engineRoot, this.projectRoot, this.workspaceRoot].join('\0');
    if (before !== after) this.invalidate('bridge-configuration-changed', 'repositories');
  }

  invalidate(reason = 'explicit-invalidation', domain = 'dashboard') {
    this.lastSnapshotAt = 0;
    this.lastFingerprint = null;
    this.lastInvalidationReason = String(reason).slice(0, 160);
    this.revisions.invalidate(domain, reason);
    this.requestCache.clear();
    this.fingerprintMemo = { watchStamp: null, value: null };
  }

  _sourceFingerprint() {
    const watchStamp = snapshotSourceWatchStamp(this.engineRoot, this.projectRoot, this.workspaceRoot);
    this.fingerprintMetrics.watchScans += 1;
    if (this.fingerprintMemo.value && this.fingerprintMemo.watchStamp === watchStamp) {
      this.fingerprintMetrics.guardedReuses += 1;
      return this.fingerprintMemo.value;
    }
    const value = snapshotSourceFingerprint(this.engineRoot, this.projectRoot, this.workspaceRoot);
    this.fingerprintMetrics.completeScans += 1;
    this.fingerprintMemo = { watchStamp, value };
    return value;
  }

  _cached(status, fingerprint, reason, refreshPending = false) {
    const value = clone(this.lastSnapshot);
    value.cache = {
      schema_version: 'px.dashboard-cache/1.0', status,
      age_ms: Math.max(0, this.now() - this.lastSnapshotAt), ttl_ms: this.cacheTtlMs,
      source_fingerprint: fingerprint, invalidation_reason: reason,
      refresh_pending: refreshPending
    };
    return value;
  }

  async _refreshSnapshot(fingerprint, reason) {
    const args = ['-m', 'runtime.dashboard_api', 'snapshot', '--source-root', this.engineRoot];
    if (this.projectRoot) args.push('--project', this.projectRoot);
    if (this.workspaceRoot) args.push('--workspace-root', this.workspaceRoot);
    const raw = await this.governor.run(`dashboard-snapshot:${fingerprint}`, signal => this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 30_000, signal }), {
      pool: 'background', priority: 3, reason,
      supersessionKey: 'dashboard-snapshot', circuitKey: 'dashboard-api', circuitThreshold: 3, circuitCooldownMs: 30_000
    });
    this.lastSnapshot = normalizeSnapshot(raw);
    this.lastSnapshotAt = this.now();
    this.lastFingerprint = fingerprint;
    this.lastInvalidationReason = reason;
    await this.metadataCache.set(this._snapshotCacheKey(), this.lastSnapshot, {
      fingerprint,
      dependencyFingerprints: { dashboard: this.revisions.fingerprint(['dashboard', 'coordination', 'git', 'environment']) },
      freshnessClass: 'dynamic', invalidationReason: reason
    });
    return this._cached('miss', fingerprint, reason);
  }

  _snapshotCacheKey() { return `dashboard:${this.engineRoot || ''}:${this.projectRoot || ''}:${this.workspaceRoot || ''}`; }

  async _request(key, producer, options = {}, ttlMs = 30_000) {
    const cached = this.requestCache.get(key);
    if (cached && this.now() - cached.createdAt < ttlMs) {
      this.requestCacheMetrics.hits += 1;
      return clone(cached.value);
    }
    this.requestCacheMetrics.misses += 1;
    const value = await this.governor.run(key, producer, options);
    this.requestCache.set(key, { createdAt: this.now(), value: clone(value) });
    while (this.requestCache.size > 128) { this.requestCache.delete(this.requestCache.keys().next().value); this.requestCacheMetrics.evictions += 1; }
    return value;
  }

  async snapshot({ force = false, reason = force ? 'explicit-refresh' : 'periodic-fallback' } = {}) {
    if (!isEngineRoot(this.engineRoot)) return disconnected('Set pacifyX.engineRoot to a Pacify-X source tree containing runtime/dashboard_api.py.');
    const fingerprint = this._sourceFingerprint();
    if (!force && !this.lastSnapshot) {
      const restored = await this.metadataCache.get(this._snapshotCacheKey(), { fingerprint, maxAgeMs: 24 * 60 * 60_000 });
      if (restored) {
        this.lastSnapshot = restored.value;
        this.lastSnapshotAt = this.now() - restored.age_ms;
        this.lastFingerprint = fingerprint;
        this.lastInvalidationReason = 'persistent-cache-restored';
        return this._cached('persistent-hit', fingerprint, 'source-fingerprint-verified');
      }
    }
    const sameSource = this.lastSnapshot && fingerprint === this.lastFingerprint;
    const age = this.now() - this.lastSnapshotAt;
    if (!force && sameSource && age < this.cacheTtlMs) return this._cached('hit', fingerprint, 'source-unchanged');
    if (!force && sameSource) {
      void this._refreshSnapshot(fingerprint, 'ttl-expired').catch(() => {});
      return this._cached('stale-hit', fingerprint, 'ttl-expired', true);
    }
    return this._refreshSnapshot(fingerprint, force ? reason : this.lastSnapshot ? 'source-fingerprint-changed' : 'cold-start');
  }

  async catalog(input) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const kind = String(input.kind || '');
    if (!['skills', 'preserved-skills', 'microsoft-skills', 'tools', 'agents', 'workflows', 'graph', 'enterprise-skills', 'enterprise-agents', 'enterprise-workflows', 'enterprise-integrations', 'enterprise-models'].includes(kind)) throw new Error('Unsupported catalog kind.');
    const requestedOffset = Math.max(0, Number(input.offset || 0));
    const requestedLimit = Math.max(1, Math.min(100, Number(input.limit || 50)));
    let authenticatedStatuses = {};
    if (this.projectRoot && ['agents', 'workflows', 'skills'].includes(kind)) {
      const projectionKey = `studio-lifecycle:${kind}:${this._sourceFingerprint()}`;
      try {
        const projection = await this._request(projectionKey, signal => this.capture(this.pythonPath, ['-m', 'runtime.studio_catalog_status', '--root', this.projectRoot, '--kind', kind], { cwd: this.engineRoot, timeoutMs: 15_000, signal }), { pool: 'interactive', priority: 1, reason: 'studio-lifecycle-projection', circuitKey: 'studio-catalog-status', timeoutMs: 15_000 });
        authenticatedStatuses = projection?.records && typeof projection.records === 'object' ? projection.records : {};
      } catch {
        authenticatedStatuses = {};
      }
    }
    const studio = collectStudioCatalog(this.projectRoot, kind, authenticatedStatuses);
    const studioItems = filterStudioItems(studio.items, input);
    const studioSlice = requestedOffset < studioItems.length ? studioItems.slice(requestedOffset, requestedOffset + requestedLimit) : [];
    const remaining = requestedLimit - studioSlice.length;
    const backendOffset = requestedOffset < studioItems.length ? 0 : requestedOffset - studioItems.length;
    const backendLimit = Math.max(1, remaining);
    const args = ['-m', 'runtime.dashboard_api', 'catalog', '--source-root', this.engineRoot, '--kind', kind,
      '--query', String(input.query || '').slice(0, 500), '--status', String(input.status || '').slice(0, 100),
      '--offset', String(backendOffset), '--limit', String(backendLimit),
      '--sort', ['id', 'label', 'status', 'kind'].includes(input.sort) ? input.sort : 'label'];
    const dependency = kind.includes('enterprise') ? 'providers' : kind === 'skills' || kind.includes('skills') ? 'skills' : kind;
    const source = this._sourceFingerprint();
    const key = `catalog:${this.revisions.fingerprint([dependency])}:${source}:${studio.fingerprint}:${crypto.createHash('sha256').update(JSON.stringify(args)).digest('hex')}`;
    const base = normalizeSkillCatalogPage(await this._request(key, signal => this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 30_000, signal }), { pool: 'interactive', priority: 1, reason: 'catalog-query', circuitKey: 'dashboard-api', timeoutMs: 30_000 }), kind);
    const baseItems = remaining > 0 ? (base.items || []).slice(0, remaining) : [];
    const items = [...studioSlice, ...baseItems];
    const filtered = Number(base.filtered || 0) + studioItems.length;
    return {
      ...base,
      offset: requestedOffset,
      limit: requestedLimit,
      total: Number(base.total || 0) + studio.items.length,
      filtered,
      items,
      has_more: requestedOffset + items.length < filtered,
      project_studio_revisions: studio.items.length,
      project_studio_refused: studio.refused,
      source: studio.items.length ? `${base.source}+project-studio` : base.source
    };
  }

  async operationalCards(input = {}) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const args = ['-m', 'runtime.dashboard_api', 'operational-cards', '--source-root', this.engineRoot,
      '--query', String(input.query || '').slice(0, 500), '--state', String(input.state || '').slice(0, 40),
      '--severity', String(input.severity || '').slice(0, 20), '--surface', String(input.surface || '').slice(0, 160),
      '--owner', String(input.owner || '').slice(0, 160), '--offset', String(Math.max(0, Number(input.offset || 0))),
      '--limit', String(Math.max(1, Math.min(100, Number(input.limit || 50))))];
    if (input.evidenceGap === true) args.push('--evidence-gap');
    return this.governor.run(`operational-cards:${input.requestId || this.now()}`, signal => this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 15_000, signal }), { pool: 'interactive', priority: 1, reason: 'operational-card-query', circuitKey: 'dashboard-api', timeoutMs: 15_000 });
  }

  async operationalCard(input = {}) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const gapId = String(input.gapId || '').trim();
    if (!/^PX-(?:OS|GAP)-[0-9]{3,}$/.test(gapId)) throw new Error('Operational gap ID is invalid.');
    const args = ['-m', 'runtime.dashboard_api', 'operational-card', '--source-root', this.engineRoot, '--gap-id', gapId];
    return this.governor.run(`operational-card:${gapId}`, signal => this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 15_000, signal }), { pool: 'interactive', priority: 1, reason: 'operational-card-detail', circuitKey: 'dashboard-api', timeoutMs: 15_000 });
  }

  async operationalInventory(input = {}) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const surfaceId = String(input.surfaceId || '').trim().slice(0, 160);
    const args = ['-m', 'runtime.dashboard_api', 'operational-inventory', '--source-root', this.engineRoot];
    if (surfaceId) args.push('--surface-id', surfaceId);
    return this.governor.run(`operational-inventory:${surfaceId || 'overview'}`, signal => this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 15_000, signal }), { pool: 'interactive', priority: 1, reason: 'operational-inventory-query', circuitKey: 'dashboard-api', timeoutMs: 15_000 });
  }

  async skillQuery(input) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const goal = String(input.goal || '').trim().slice(0, 1000);
    const domains = ['px-standard', 'microsoft-vendor', 'enterprise-restricted', 'user-preserved'];
    const domain = domains.includes(input.domain) ? input.domain : 'px-standard';
    if (!goal) throw new Error('Semantic skill query requires a goal.');
    const grants = {
      'microsoft-vendor': ['allow-microsoft-vendor', 'allow-unadmitted-skill-metadata'],
      'enterprise-restricted': ['allow-enterprise-restricted', 'allow-unadmitted-skill-metadata'],
      'user-preserved': ['allow-user-preserved', 'allow-unadmitted-skill-metadata']
    }[domain] || [];
    const args = ['-m', 'runtime.cli', '--root', this.engineRoot, 'skill-query', '--goal', goal, '--domain', domain, '--limit', '3'];
    for (const grant of grants) args.push('--grant', grant);
    return this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 30_000 });
  }

  async skillHydrate(input) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const skill = String(input.skill || '').trim().slice(0, 200);
    const domains = ['px-standard', 'microsoft-vendor', 'enterprise-restricted', 'user-preserved'];
    const domain = domains.includes(input.domain) ? input.domain : 'px-standard';
    if (!skill) throw new Error('Skill hydration requires an exact candidate ID.');
    const grants = {
      'microsoft-vendor': ['allow-microsoft-vendor', 'allow-unadmitted-skill-metadata'],
      'enterprise-restricted': ['allow-enterprise-restricted', 'allow-unadmitted-skill-metadata'],
      'user-preserved': ['allow-user-preserved', 'allow-unadmitted-skill-metadata']
    }[domain] || [];
    const args = ['-m', 'runtime.cli', '--root', this.engineRoot, 'skill-hydrate', '--skill', skill, '--domain', domain];
    for (const grant of grants) args.push('--grant', grant);
    return this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 30_000 });
  }

  async skillCompare(input) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const skill = String(input.skill || '').trim().slice(0, 128);
    if (!/^[a-z0-9][a-z0-9._:-]{1,127}$/.test(skill)) throw new Error('Skill comparison requires an exact PX-standard skill ID.');
    const args = ['-m', 'runtime.cli', '--root', this.engineRoot, 'skill-compare', '--skill', skill];
    return this.governor.run(`skill-compare:${skill}`, signal => this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 30_000, signal }), { pool: 'interactive', priority: 1, reason: 'skill-original-comparison', circuitKey: 'native-skills', timeoutMs: 30_000 });
  }

  async memory(input) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    if (!this.workspaceRoot) throw new Error('Canonical workspace root is not configured.');
    const args = ['-m', 'runtime.dashboard_api', 'memory', '--source-root', this.engineRoot, '--workspace-root', this.workspaceRoot,
      '--query', String(input.query || '').slice(0, 500), '--offset', String(Math.max(0, Math.min(10_000, Number(input.offset || 0)))),
      '--limit', String(Math.max(1, Math.min(100, Number(input.limit || 60)))), '--status', String(input.status || '').slice(0, 100),
      '--project-id', String(input.projectId || '').slice(0, 160), '--source', String(input.source || '').slice(0, 500)];
    const source = this._sourceFingerprint();
    const key = `canonical-memory:${this.revisions.fingerprint(['memory'])}:${source}:${crypto.createHash('sha256').update(JSON.stringify(args)).digest('hex')}`;
    return this._request(key, signal => this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 30_000, signal }), { pool: 'interactive', priority: 1, reason: 'canonical-memory-query', circuitKey: 'dashboard-api', timeoutMs: 30_000 }, 5000);
  }

  async initializeWorkspace(target, { apply = false } = {}) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const args = ['-m', 'runtime.cli', 'workspace', 'init', '--workspace', path.resolve(target)];
    if (apply) args.push('--apply');
    return this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 60_000 });
  }

  async discoverWorkspaceProjects(target, { apply = false } = {}) {
    const args = ['-m', 'runtime.cli', 'workspace', 'discover', '--workspace', path.resolve(target)];
    if (apply) args.push('--apply');
    return this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 60_000 });
  }

  async createWorkspaceProject(target, name) {
    return this.capture(this.pythonPath, ['-m', 'runtime.cli', 'workspace', 'create-project', '--workspace', path.resolve(target), '--name', String(name).slice(0, 120), '--apply'], { cwd: this.engineRoot, timeoutMs: 60_000 });
  }

  async listWorkspaceProjects(target) {
    return this.capture(this.pythonPath, ['-m', 'runtime.cli', 'project', 'list', '--workspace', path.resolve(target)], { cwd: this.engineRoot, timeoutMs: 30_000 });
  }

  async currentWorkspaceProject(target) {
    return this.capture(this.pythonPath, ['-m', 'runtime.cli', 'project', 'current', '--workspace', path.resolve(target), '--session-id', 'vscode-dashboard'], { cwd: this.engineRoot, timeoutMs: 30_000 });
  }

  async renewWorkspaceProject(target, minutes = 120) {
    const boundedMinutes = Math.max(15, Math.min(420, Math.trunc(Number(minutes) || 120)));
    return this.capture(this.pythonPath, ['-m', 'runtime.cli', 'project', 'renew', '--workspace', path.resolve(target), '--session-id', 'vscode-dashboard', '--minutes', String(boundedMinutes)], { cwd: this.engineRoot, timeoutMs: 30_000 });
  }

  async activateWorkspaceProject(target, projectId) {
    const workspace = path.resolve(target);
    const sessionId = 'vscode-dashboard';
    const activation = await this.capture(this.pythonPath, ['-m', 'runtime.cli', 'project', 'activate', '--workspace', workspace, '--project-id', String(projectId), '--agent-id', 'human-local-user', '--session-id', sessionId, '--context-reset-confirmed'], { cwd: this.engineRoot, timeoutMs: 30_000 });
    if (!activation?.activated && !activation?.already_active) return activation;
    const renewal = await this.renewWorkspaceProject(workspace, 120);
    return { ...activation, bounded_lease_extension: renewal };
  }

  async ensureWorkspaceProjectLease(target, { projectRoot = this.projectRoot, renewWithinMs = 30 * 60_000 } = {}) {
    if (!isEngineRoot(this.engineRoot)) return { state: 'detached', changed: false, reason: 'engine-root-unavailable' };
    const workspace = path.resolve(String(target || ''));
    if (!target || !fs.existsSync(path.join(workspace, 'engineering-workspace.toml'))) {
      return { state: 'detached', changed: false, reason: 'canonical-workspace-not-configured' };
    }
    const current = await this.currentWorkspaceProject(workspace);
    const active = current?.active;
    if (current?.lease_state === 'current' && active) {
      const remainingMs = Date.parse(String(active.expires_utc || '')) - Date.now();
      if (Number.isFinite(remainingMs) && remainingMs > Math.max(5 * 60_000, renewWithinMs)) {
        return { state: 'attached', changed: false, project_id: active.project_id, expires_utc: active.expires_utc, reason: 'lease-current' };
      }
      try {
        const renewal = await this.renewWorkspaceProject(workspace, 120);
        return { state: 'attached', changed: true, project_id: renewal.project_id, expires_utc: renewal.expires_utc, reason: 'lease-renewed', renewal };
      } catch (error) {
        return { state: 'degraded', changed: false, project_id: active.project_id, expires_utc: active.expires_utc, reason: `lease-renewal-failed:${error.message}` };
      }
    }
    const listed = await this.listWorkspaceProjects(workspace);
    const projects = Array.isArray(listed?.projects) ? listed.projects : [];
    const projectName = projectRoot ? path.basename(path.resolve(projectRoot)).toLowerCase() : '';
    const eligible = projects.filter(project => ['registered', 'active'].includes(String(project.state || '').toLowerCase()));
    const activeCandidates = eligible.filter(project => String(project.state).toLowerCase() === 'active');
    const nameCandidates = eligible.filter(project => String(project.name || '').toLowerCase() === projectName);
    const candidates = activeCandidates.length === 1 ? activeCandidates : nameCandidates.length === 1 ? nameCandidates : eligible.length === 1 ? eligible : [];
    if (candidates.length !== 1) {
      return { state: 'detached', changed: false, reason: eligible.length ? 'canonical-project-selection-ambiguous' : 'no-registered-canonical-project', eligible_project_ids: eligible.map(project => project.project_id).slice(0, 20) };
    }
    const activation = await this.activateWorkspaceProject(workspace, candidates[0].project_id);
    const session = activation?.session || {};
    return { state: activation?.valid ? 'attached' : 'degraded', changed: Boolean(activation?.activated || activation?.bounded_lease_extension?.renewed), project_id: candidates[0].project_id, expires_utc: activation?.bounded_lease_extension?.expires_utc || session.expires_utc || null, reason: activation?.already_active ? 'lease-renewed' : activation?.activated ? 'lease-activated' : 'lease-activation-declined', activation };
  }

  async createStudioDraft(kind, payload) {
    return this.studioOperation(kind, 'create', payload);
  }

  async nextStudioVersion(kind, identity, sourceVersion, sourceScope, sourceRevisionSha256, sourceContentSha256) {
    const scope = sourceScope == null ? 'studio-physical' : String(sourceScope);
    if (!['studio-physical', 'external-authenticated'].includes(scope)) throw new Error('Unsupported Studio version source scope.');
    if (scope === 'external-authenticated' && kind !== 'skill') throw new Error('External authenticated Studio version sources are skill-only.');
    const payload = {
      identity: String(identity || ''),
      source_version: String(sourceVersion || '')
    };
    if (scope === 'external-authenticated') Object.assign(payload, {
      source_scope: scope,
      source_revision_sha256: String(sourceRevisionSha256 || ''),
      source_content_sha256: String(sourceContentSha256 || '')
    });
    return this.studioOperation(kind, 'next-version', payload);
  }

  async studioIdentityAbsence(kind, identity) {
    return this.studioOperation(kind, 'identity-absence', { identity: String(identity || '') });
  }

  async studioOperation(kind, operation, payload) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    if (!Object.hasOwn(STUDIO_PROTOCOL.kinds, kind)) throw new Error('Unsupported studio kind.');
    if (!STUDIO_PROTOCOL.kinds[kind].includes(operation)) throw new Error('Unsupported studio operation.');
    let transmitted = payload;
    const proof = payload?.approval_capability;
    if (proof && typeof proof.payload_json === 'string') {
      const unsigned = Object.fromEntries(Object.entries(payload).filter(([key]) => !['approval_capability', 'approved', 'approved_by'].includes(key)));
      if (approvalPayloadJson(unsigned) !== proof.payload_json) throw new Error('Studio approval does not match the exact payload bytes.');
      transmitted = { approval_capability: proof };
    }
    const body = Buffer.from(JSON.stringify(transmitted), 'utf8');
    if (body.length > 528 * 1024) throw new Error('Studio request envelope exceeds the 528 KiB bound.');
    if (!this.projectRoot) throw new Error('Studio requires an explicit project workspace; the Pacify-X engine source is never a project-state fallback.');
    const args = ['-m', 'runtime.studio_api', '--root', this.projectRoot, '--kind', kind, '--operation', operation, '--payload-stdin'];
    const key = `studio:${kind}:${operation}:${crypto.createHash('sha256').update(body).digest('hex')}:${crypto.randomUUID()}`;
    const timeoutMs = ['run', 'start', 'resume', 'recover', 'reconcile'].includes(operation) ? 120_000 : 30_000;
    const result = await this.governor.run(key, signal => this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs, signal, input: body }), { pool: 'interactive', priority: 1, reason: `studio-${operation}`, circuitKey: 'studio-api', timeoutMs });
    if (!STUDIO_READ_ONLY_OPERATIONS.has(`${kind}:${operation}`)) {
      const domain = kind === 'skill' ? 'skills' : kind === 'knowledge' ? 'knowledge' : kind;
      this.invalidate(`studio-${kind}-${operation}-committed`, domain);
    }
    return result;
  }

  async _studioApprovalSigningContext() {
    if (typeof this.approvalKeyProvider !== 'function') throw new Error('Studio approval requires the authenticated VS Code host signing key.');
    const descriptor = await this.capture(this.pythonPath, ['-m', 'runtime.studio_approval', '--root', this.projectRoot, '--describe-verifier'], { cwd: this.engineRoot, timeoutMs: 30_000 });
    const projectIdentity = String(descriptor?.project_identity || '');
    const keyRoot = path.resolve(String(descriptor?.key_root || ''));
    const recordPath = path.resolve(String(descriptor?.record_path || ''));
    const expectedPath = path.resolve(keyRoot, 'approval-verifiers', `${projectIdentity}.json`);
    if (!projectIdentity.startsWith('px-project-') || recordPath !== expectedPath || pathWithin(keyRoot, this.projectRoot) || pathWithin(recordPath, this.projectRoot)) {
      throw new Error('Studio approval verifier location is outside the admitted host boundary.');
    }
    const ring = await this.approvalKeyProvider({ action: 'get', projectIdentity });
    const material = ring?.active;
    if (!validMaterial(material)) throw new Error('Studio approval signing identity is unavailable.');
    let current = null;
    try { current = JSON.parse(fs.readFileSync(recordPath, 'utf8')); }
    catch (error) { if (error?.code !== 'ENOENT') throw error; }
    let rotation = { mode: 'initial-host-enrollment', previous_key_id: null, authorization_signature: null };
    if (current && current.key_id !== material.keyId) {
      const previous = await this.approvalKeyProvider({ action: 'find', keyId: current.key_id, projectIdentity });
      if (previous && validMaterial(previous)) {
        const transition = { schema_version: 'px.studio-approval-key-transition/1.0', project_identity: projectIdentity, previous_key_id: current.key_id, next_key_id: material.keyId };
        rotation = { mode: 'old-key-proof', previous_key_id: current.key_id, authorization_signature: signClaim(previous, transition) };
      } else {
        const recovered = typeof this.approvalRecoveryProvider === 'function' && await this.approvalRecoveryProvider({ projectIdentity, previousKeyId: current.key_id, nextKeyId: material.keyId });
        if (!recovered) throw new Error('Studio approval signing identity changed; explicit host recovery is required.');
        const backup = path.join(path.dirname(recordPath), 'recovery-backups', `${projectIdentity}-${Date.now()}-${String(current.key_id || 'unknown').slice(0, 16)}.json`);
        fs.mkdirSync(path.dirname(backup), { recursive: true, mode: 0o700 });
        fs.copyFileSync(recordPath, backup, fs.constants.COPYFILE_EXCL);
        rotation = { mode: 'explicit-human-recovery', previous_key_id: String(current.key_id || ''), authorization_signature: null };
      }
    }
    const record = {
      schema_version: 'px.studio-host-approval-verifier/2.0', project_identity: projectIdentity,
      host_surface: 'vscode-extension-host', approved_by: 'human:vscode-local-user',
      key_id: material.keyId, public_key_jwk: material.publicKeyJwk,
      created_utc: current?.created_utc || new Date().toISOString(),
      revision: Math.max(1, Number(current?.revision || 0) + (current?.key_id === material.keyId ? 0 : 1)), rotation
    };
    fs.mkdirSync(path.dirname(recordPath), { recursive: true, mode: 0o700 });
    if (!current || current.key_id !== material.keyId) {
      const prepared = `${recordPath}.${crypto.randomUUID()}.prepared`;
      fs.writeFileSync(prepared, `${JSON.stringify(record, null, 2)}\n`, { encoding: 'utf8', flag: 'wx', mode: 0o600 });
      fs.renameSync(prepared, recordPath);
    }
    try { fs.chmodSync(recordPath, 0o600); } catch {}
    return { material, projectIdentity };
  }

  async rotateStudioApprovalIdentity() {
    if (typeof this.approvalKeyProvider !== 'function') throw new Error('Studio approval key provider is unavailable.');
    await this.approvalKeyProvider({ action: 'rotate' });
    const context = await this._studioApprovalSigningContext();
    return { rotated: true, key_id: context.material.keyId, project_identity: context.projectIdentity };
  }

  async issueStudioApproval(kind, operation, payload, { approvedBy = 'human:vscode-local-user' } = {}) {
    if (!isEngineRoot(this.engineRoot) || !this.projectRoot) throw new Error('Studio approval requires explicit engine and project roots.');
    if (!Object.hasOwn(STUDIO_PROTOCOL.kinds, kind) || !STUDIO_PROTOCOL.kinds[kind].includes(operation)) throw new Error('Unsupported Studio approval scope.');
    const payloadJson = approvalPayloadJson(payload);
    const body = Buffer.from(payloadJson, 'utf8');
    if (body.length > 256 * 1024) throw new Error('Studio approval payload exceeds the 256 KiB bound.');
    const { material, projectIdentity } = await this._studioApprovalSigningContext();
    const issued = new Date(); const expires = new Date(issued.getTime() + 120_000);
    const claim = {
      schema_version: 'px.studio-host-approval/2.1', project_identity: projectIdentity,
      kind, operation, payload_sha256: crypto.createHash('sha256').update(body).digest('hex'),
      approved_by: String(approvedBy), issued_utc: issued.toISOString(), expires_utc: expires.toISOString(),
      nonce: crypto.randomBytes(24).toString('hex'), key_id: material.keyId
    };
    return { approval_capability: { claim, payload_json: payloadJson, signature: signClaim(material, claim) }, approved_by: claim.approved_by };
  }

  async graph(input = {}) {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    const direction = ['incoming', 'outgoing', 'both'].includes(input.direction) ? input.direction : 'both';
    const modes = new Set(['full', 'overview', 'neighborhood', 'path', 'impact', 'dependencies', 'dependents', 'hubs', 'orphans', 'provenance']);
    const mode = modes.has(input.mode) ? input.mode : 'neighborhood';
    const args = ['-m', 'runtime.dashboard_api', 'graph', '--source-root', this.engineRoot,
      '--view', input.view === 'repository' ? 'repository' : 'capabilities',
      '--node', String(input.node || '').slice(0, 500), '--query', String(input.query || '').slice(0, 500),
      '--target', String(input.target || '').slice(0, 500),
      '--relation', String(input.relation || '').slice(0, 160), '--direction', direction,
      '--mode', mode, '--cluster', String(input.cluster || '').slice(0, 160),
      '--kind', String(input.kind || '').slice(0, 120), '--status', String(input.status || '').slice(0, 120),
      '--offset', String(Math.max(0, Math.min(10_000_000, Number(input.offset || 0)))),
      '--edge-offset', String(Math.max(0, Math.min(10_000_000, Number(input.edgeOffset || 0)))),
      '--depth', String(Math.max(1, Math.min(6, Number(input.depth || 1)))),
      '--max-nodes', String(Math.max(2, Math.min(500, Number(input.maxNodes || 24)))),
      '--max-edges', String(Math.max(1, Math.min(1000, Number(input.maxEdges || 48))))];
    if (this.projectRoot) args.push('--project', this.projectRoot);
    const source = this._sourceFingerprint();
    const key = `graph:${this.revisions.fingerprint(['workflows', 'agents', 'repositories'])}:${source}:${crypto.createHash('sha256').update(JSON.stringify(args)).digest('hex')}`;
    return this._request(key, signal => this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 30_000, signal }), { pool: 'interactive', priority: 1, reason: 'graph-query', supersessionKey: 'graph-query', circuitKey: 'dashboard-api', timeoutMs: 30_000 });
  }

  async buildProjectMap() {
    if (!isEngineRoot(this.engineRoot)) throw new Error('Pacify-X engine root unavailable.');
    if (!this.projectRoot) throw new Error('Repository graph build requires an explicit project workspace.');
    const args = ['-m', 'runtime.cli', 'project-map', 'build', '--project', this.projectRoot];
    return this.governor.run(`project-map-build:${crypto.randomUUID()}`, signal => this.capture(this.pythonPath, args, { cwd: this.engineRoot, timeoutMs: 120_000, signal }), { pool: 'background', priority: 1, reason: 'project-map-build', circuitKey: 'project-map', timeoutMs: 120_000 });
  }

  diagnostics() {
    return {
      schema_version: 'px.bridge-efficiency/1.0',
      cache: { present: Boolean(this.lastSnapshot), age_ms: this.lastSnapshot ? Math.max(0, this.now() - this.lastSnapshotAt) : null, ttl_ms: this.cacheTtlMs, source_fingerprint: this.lastFingerprint, last_invalidation_reason: this.lastInvalidationReason },
      governor: this.governor.snapshot(),
      dependency_revisions: this.revisions.snapshot(),
      persistent_metadata: this.metadataCache.snapshot(),
      source_fingerprint: { ...this.fingerprintMetrics, watch_guard: 'bounded-stat-tree-no-content-reads' },
      request_cache: { entries: this.requestCache.size, maximum_entries: 128, metrics: { ...this.requestCacheMetrics } }
    };
  }

  dispose() { if (this.ownsGovernor) this.governor.dispose(); }
}

module.exports = { DEFAULT_SNAPSHOT_TTL_MS, SNAPSHOT_FINGERPRINT_PATHS, STUDIO_VERSION_CONFLICT_REASONS, snapshotSourceFingerprint, snapshotSourceWatchStamp, isEngineRoot, findEngineRoot, captureJson, exactStudioVersionConflictEnvelope, exactStudioVersionConflictError, studioProcessError, normalizeSnapshot, disconnected, authorityMap, pathWithin, PxBridge };
