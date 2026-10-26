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
  const seen = new WeakSet();
  let remaining = 65536;
  let nodes = 2048;
  function redact(value, depth) {
    if (--nodes < 0 || remaining <= 0 || depth > 12) return '[omitted]';
    if (typeof value === 'string') {
      const text = value.slice(0, Math.min(16000, remaining));
      remaining -= Buffer.byteLength(JSON.stringify(text), 'utf8');
      return text.length === value.length ? text : `${text}[omitted]`;
    }
    if (value === null || typeof value !== 'object') return value;
    if (seen.has(value)) return '[cycle omitted]';
    seen.add(value);
    const out = Array.isArray(value) ? [] : Object.create(null);
    for (const key of Object.keys(value)) {
      if (nodes <= 0 || remaining <= 0) break;
      remaining -= Buffer.byteLength(JSON.stringify(key), 'utf8');
      out[key] = /secret|api.?key|authorization|credential|password|passwd|access.?token|refresh.?token|^token$/i.test(key)
        ? '[redacted]' : redact(value[key], depth + 1);
    }
    seen.delete(value);
    return out;
  }
  return redact(event.payload || {}, 0);
}


module.exports = { buildAgentConsoleProjection, redactEventPayload };
