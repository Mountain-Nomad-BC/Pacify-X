'use strict';

function safeContext(context) {
  if (!context) return null;
  return { contextId: context.contextId, budgetTokens: context.budgetTokens, suppliedTokens: context.suppliedTokens, consideredCount: context.consideredCount, selectedCount: context.selectedCount,
    refs: (context.refs || []).map(r => ({ refId: r.refId, kind: r.kind, label: r.label, source: r.source, tokenEstimate: r.tokenEstimate, authority: r.authority, freshAt: r.freshAt, sha256: r.sha256 })) };
}

function buildAgentConsoleProjection(state, options = {}) {
  const catalog = options.modelCatalog || null;
  const workers = (state.workers || []).map(w => ({ workerId: w.workerId, providerId: w.providerId, modelId: w.modelId, profileId: w.profileId || null, displayName: w.displayName, costClass: w.costClass, locality: w.locality, contextLimit: w.contextLimit, capabilities: w.capabilities, supportedEffectClass: w.supportedEffectClass, enabled: w.enabled, health: w.health, bridge: w.bridge || null }));
  return {
    schemaVersion: 'px.agent-console-projection/1.0', generatedAt: new Date().toISOString(),
    task: state.activeTask, run: state.activeRun,
    workers,
    modelCatalog: catalog ? { state: catalog.state, detail: catalog.detail, source: catalog.source, updatedAt: catalog.updatedAt } : { state: 'unknown', detail: 'Model catalog provenance was not reported by the host.', source: 'unknown', updatedAt: null },
    librarian: state.librarian,
    context: safeContext(state.context),
    route: state.route ? { reason: state.route.reason, selectedWorkerId: state.route.selected?.workerId || null, evaluated: (state.route.evaluated || []).map(r => ({ workerId: r.worker.workerId, displayName: r.worker.displayName, costClass: r.worker.costClass, admitted: r.admitted, reasons: r.reasons, score: r.score })) } : null,
    budget: state.budget,
    evidence: state.evidence || [],
    events: (state.events || []).map(event => ({ ...event, payload: redactEventPayload(event) }))
  };
}

function redactEventPayload(event) {
  const payload = { ...(event.payload || {}) };
  if (event.type === 'worker.completed' && typeof payload.text === 'string') payload.text = payload.text.slice(0, 120000);
  for (const key of Object.keys(payload)) if (/secret|api.?key|authorization|credential/i.test(key)) payload[key] = '[redacted]';
  return payload;
}

module.exports = { buildAgentConsoleProjection };
