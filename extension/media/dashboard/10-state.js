'use strict';

(() => {
  const dashboard = globalThis.PXDashboard;
  if (!dashboard) throw new Error('PXDashboard foundation must load before state.');

  const text = (value, fallback = '', maximum = 240) => {
    const candidate = typeof value === 'string' ? value.trim() : '';
    return candidate && candidate.length <= maximum ? candidate : fallback;
  };
  const oneOf = (value, allowed, fallback) => allowed.includes(value) ? value : fallback;
  const integer = (value, minimum, maximum, fallback) => {
    const candidate = Number(value);
    return Number.isSafeInteger(candidate) ? Math.max(minimum, Math.min(maximum, candidate)) : fallback;
  };
  const boundedArray = (value, limit, maximumBytes) => {
    if (!Array.isArray(value)) return [];
    try {
      const encoded = JSON.stringify(value.slice(0, limit));
      if (new TextEncoder().encode(encoded).byteLength > maximumBytes) return [];
      const parsed = JSON.parse(encoded);
      return Array.isArray(parsed) ? parsed : [];
    } catch { return []; }
  };
  const GRAPH_SAVED_VIEW_KEYS = Object.freeze(['community', 'depth', 'direction', 'kind', 'layout', 'mode', 'name', 'query', 'relation', 'status', 'target', 'view']);
  const graphSavedViews = value => {
    if (!Array.isArray(value)) return [];
    const result = [];
    for (const candidate of value.slice(0, 12)) {
      if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) continue;
      if (Object.keys(candidate).sort().join('\0') !== GRAPH_SAVED_VIEW_KEYS.join('\0')) continue;
      const name = text(candidate.name, '', 80);
      if (!name || candidate.name !== name) continue;
      const normalized = {
        name,
        view: oneOf(candidate.view, ['capabilities', 'repository'], 'capabilities'),
        mode: oneOf(candidate.mode, ['full', 'overview', 'neighborhood', 'path', 'impact', 'dependencies', 'dependents', 'hubs', 'orphans', 'provenance'], 'full'),
        target: text(candidate.target, '', 500),
        query: text(candidate.query, '', 500),
        relation: text(candidate.relation, '', 160),
        direction: oneOf(candidate.direction, ['both', 'outgoing', 'incoming'], 'both'),
        depth: integer(candidate.depth, 1, 6, 1),
        layout: oneOf(candidate.layout, ['community', 'orbit', 'flow'], 'community'),
        kind: text(candidate.kind, '', 120),
        status: text(candidate.status, '', 120),
        community: text(candidate.community, '', 160)
      };
      if (GRAPH_SAVED_VIEW_KEYS.some(key => candidate[key] !== normalized[key])) continue;
      result.push(normalized);
    }
    return boundedArray(result, 12, 262144);
  };
  const containsForbiddenDraftKey = value => {
    if (!value || typeof value !== 'object') return false;
    if (Array.isArray(value)) return value.some(containsForbiddenDraftKey);
    return Object.entries(value).some(([key, item]) =>
      /^(?:token|proof|requestId|request_id|approvalIdentity|approval_identity|credentialValue|credential_value|secret)$/i.test(key)
      || containsForbiddenDraftKey(item)
    );
  };
  const SHA256_PATTERN = /^[a-f0-9]{64}$/;
  const STUDIO_IDENTITY_PATTERN = /^[a-z0-9][a-z0-9._:-]{0,199}$/;
  const STUDIO_VERSION_PATTERN = /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9a-z.-]+)?(?:\+[0-9a-z.-]+)?$/;
  const SOURCE_BINDING_KEYS = Object.freeze([
    'identity', 'source_content_sha256', 'source_revision_sha256',
    'source_scope', 'source_version'
  ]);
  const sourceBinding = (value, kind, draft) => {
    if (value === null || value === undefined) return null;
    if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
    if (Object.keys(value).sort().join('\0') !== [...SOURCE_BINDING_KEYS].sort().join('\0')) return undefined;
    const identityKey = kind === 'agent' ? 'agent_id' : kind === 'workflow' ? 'workflow_id' : 'skill_id';
    const identity = typeof value.identity === 'string' ? value.identity.trim().toLowerCase() : '';
    const sourceVersion = typeof value.source_version === 'string' ? value.source_version.trim().toLowerCase() : '';
    const draftIdentity = typeof draft?.[identityKey] === 'string' ? draft[identityKey].trim().toLowerCase() : '';
    const draftVersion = typeof draft?.version === 'string' ? draft.version.trim().toLowerCase() : '';
    if (value.identity !== identity || value.source_version !== sourceVersion) return undefined;
    if (!STUDIO_IDENTITY_PATTERN.test(identity) || !STUDIO_VERSION_PATTERN.test(sourceVersion) || !STUDIO_VERSION_PATTERN.test(draftVersion)) return undefined;
    if (draftIdentity !== identity || draft?.[identityKey] !== draftIdentity || draft?.version !== draftVersion) return undefined;
    if (!['studio-physical', 'external-authenticated'].includes(value.source_scope)) return undefined;
    if (value.source_scope === 'external-authenticated' && kind !== 'skill') return undefined;
    if (!SHA256_PATTERN.test(value.source_revision_sha256) || !SHA256_PATTERN.test(value.source_content_sha256)) return undefined;
    return {
      source_scope: value.source_scope,
      identity,
      source_version: sourceVersion,
      source_revision_sha256: value.source_revision_sha256,
      source_content_sha256: value.source_content_sha256
    };
  };
  const workingStudioDrafts = value => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    const result = {}; let totalBytes = 0;
    for (const kind of ['agent', 'workflow', 'skill']) {
      let envelope = value[kind];
      if (typeof envelope === 'string') {
        try {
          if (new TextEncoder().encode(envelope).byteLength > 524288) continue;
          envelope = JSON.parse(envelope);
        } catch { continue; }
      }
      if (!envelope || envelope.schema_version !== 'px.studio-working-draft/1.0' || envelope.kind !== kind || !envelope.draft || typeof envelope.draft !== 'object' || Array.isArray(envelope.draft)) continue;
      if (containsForbiddenDraftKey(envelope)) continue;
      const binding = sourceBinding(envelope.source_binding, kind, envelope.draft);
      if (binding === undefined) continue;
      try {
        const normalized = { ...envelope, source_binding: binding };
        const encoded = JSON.stringify(normalized);
        const bytes = new TextEncoder().encode(encoded).byteLength;
        if (bytes > 524288 || totalBytes + bytes > 1048576) continue;
        const parsed = JSON.parse(encoded);
        result[kind] = parsed; totalBytes += bytes;
      } catch { /* malformed or cyclic draft is not persisted */ }
    }
    return result;
  };
  const persistedWorkingStudioDrafts = value => {
    const normalized = workingStudioDrafts(value);
    const result = {}; let totalBytes = 0;
    for (const kind of ['agent', 'workflow', 'skill']) {
      if (!normalized[kind]) continue;
      try {
        const encoded = JSON.stringify(normalized[kind]);
        const bytes = new TextEncoder().encode(encoded).byteLength;
        if (bytes > 524288 || totalBytes + bytes > 1048576) continue;
        result[kind] = encoded; totalBytes += bytes;
      } catch { /* validated drafts should remain serializable */ }
    }
    return result;
  };

  const ACTIVE_SURFACES = [
    'dashboard', 'projects', 'agents', 'knowledgeGraph', 'skillsTools', 'workflows',
    'agent-studio', 'workflow-studio', 'skill-studio', 'studio-lifecycle',
    'plugins', 'memory', 'activity', 'diagnostics', 'assurance', 'settings',
    'knowledgeCore', 'runtimeCore'
  ];

  dashboard.define('state', {
    createInitial(persisted = {}, previewAdvanced = false) {
      return {
        active: oneOf(persisted.active, ACTIVE_SURFACES, 'dashboard'),
        advancedOpen: persisted.advancedOpen !== false,
        capabilityKind: oneOf(persisted.capabilityKind, ['skills', 'preserved-skills', 'microsoft-skills', 'enterprise-skills', 'tools'], 'skills'),
        snapshot: null,
        coordination: null,
        agentScope: oneOf(persisted.agentScope, ['core', 'enterprise'], 'core'),
        workflowScope: oneOf(persisted.workflowScope, ['core', 'enterprise'], 'core'),
        environmentScope: text(persisted.environmentScope, 'graph', 64),
        graphView: text(persisted.graphView, 'capabilities', 64),
        graphMode: text(persisted.graphMode, 'full', 64),
        graphTarget: text(persisted.graphTarget, '', 1000),
        graphData: null,
        graphPending: false,
        graphRequestId: null,
        graphError: null,
        graphLayout: text(persisted.graphLayout, 'community', 64),
        graphInspectorOpen: persisted.graphInspectorOpen !== false,
        graphLoadAll: false,
        graphDepth: integer(persisted.graphDepth, 1, 6, 1),
        graphFocusMode: false,
        graphBackStack: [],
        graphKind: text(persisted.graphKind, '', 120),
        graphStatus: text(persisted.graphStatus, '', 120),
        graphCommunity: text(persisted.graphCommunity, '', 240),
        graphRelation: text(persisted.graphRelation, '', 160),
        graphSavedViews: graphSavedViews(persisted.graphSavedViews),
        studioHistory: boundedArray(persisted.studioHistory, 30, 262144),
        workingStudioDrafts: workingStudioDrafts(persisted.workingStudioDrafts),
        memoryData: null,
        memoryPending: false,
        memoryRequestId: null,
        memoryQuery: '',
        memoryOffset: 0,
        memoryStatus: '',
        memoryProject: '',
        memorySource: '',
        knowledgeData: null,
        knowledgePending: false,
        knowledgeQuery: '',
        activityData: null,
        activityPending: false,
        activityRequestId: null,
        activityQuery: '',
        activityCategory: '',
        activityStatus: '',
        operationalCardsData: null,
        operationalCardsRequest: { query: '', state: '', severity: '', surface: '', owner: '', evidenceGap: false, offset: 0, limit: 50 },
        operationalCardsRequestId: null,
        settings: { showAdvancedSurfaces: Boolean(previewAdvanced), glassIntensity: 0.66 },
        catalogs: {},
        catalogRequests: {},
        environmentData: {},
        environmentPending: {},
        operation: null,
        clientActor: null
      };
    },
    persistedView(state) {
      return {
        active: oneOf(state.active, ACTIVE_SURFACES, 'dashboard'),
        advancedOpen: state.advancedOpen !== false,
        capabilityKind: oneOf(state.capabilityKind, ['skills', 'preserved-skills', 'microsoft-skills', 'enterprise-skills', 'tools'], 'skills'),
        agentScope: oneOf(state.agentScope, ['core', 'enterprise'], 'core'),
        workflowScope: oneOf(state.workflowScope, ['core', 'enterprise'], 'core'),
        environmentScope: text(state.environmentScope, 'graph', 64),
        graphView: text(state.graphView, 'capabilities', 64),
        graphMode: text(state.graphMode, 'full', 64),
        graphTarget: text(state.graphTarget, '', 1000),
        graphLayout: text(state.graphLayout, 'community', 64),
        graphInspectorOpen: state.graphInspectorOpen,
        graphDepth: integer(state.graphDepth, 1, 6, 1),
        graphKind: text(state.graphKind, '', 120),
        graphStatus: text(state.graphStatus, '', 120),
        graphCommunity: text(state.graphCommunity, '', 240),
        graphRelation: text(state.graphRelation, '', 160),
        graphSavedViews: graphSavedViews(state.graphSavedViews),
        studioHistory: boundedArray(state.studioHistory, 30, 262144),
        workingStudioDrafts: persistedWorkingStudioDrafts(state.workingStudioDrafts)
      };
    },
    graphSavedViews,
    workingStudioDrafts,
    persistedWorkingStudioDrafts
  });
})();
