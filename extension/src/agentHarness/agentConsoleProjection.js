'use strict';

function safeContext(context) {
  if (!context) return null;
  return { contextId: context.contextId, budgetTokens: context.budgetTokens, suppliedTokens: context.suppliedTokens, consideredCount: context.consideredCount, selectedCount: context.selectedCount,
    refs: (context.refs || []).map(r => ({ refId: r.refId, kind: r.kind, label: r.label, source: r.source, tokenEstimate: r.tokenEstimate, authority: r.authority, freshAt: r.freshAt, sha256: r.sha256 })) };
}

function buildAgentConsoleProjection(state) {
  return {
    schemaVersion: 'px.agent-console-projection/1.0', generatedAt: new Date().toISOString(),
    task: state.activeTask, run: state.activeRun,
    workers: (state.workers || []).map(w => ({ workerId: w.workerId, providerId: w.providerId, modelId: w.modelId, displayName: w.displayName, costClass: w.costClass, locality: w.locality, capabilities: w.capabilities, enabled: w.enabled, health: w.health })),
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
