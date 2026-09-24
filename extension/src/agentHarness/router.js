'use strict';

const { EFFECT_ORDER } = require('./taskStore');

const MODE_CAPABILITY = Object.freeze({ ASK: 'planning', PLAN: 'planning', DIAGNOSE: 'review', IMPLEMENT: 'coding', REVIEW: 'review', CAMPAIGN: 'coding' });
const LATENCY_SCORE = Object.freeze({ fast: 1, medium: 0.65, slow: 0.3, unknown: 0.45 });

function effectAllows(workerClass, requiredClass) { return EFFECT_ORDER.indexOf(workerClass) >= EFFECT_ORDER.indexOf(requiredClass); }

function admitWorker(worker, context) {
  const reasons = [];
  if (!worker.enabled) reasons.push('disabled');
  const health = context.registry.getHealth(worker.workerId);
  if (health.status === 'unavailable') reasons.push('unavailable');
  if (worker.contextLimit != null && context.contextTokens > worker.contextLimit) reasons.push('context-limit');
  if (!effectAllows(worker.supportedEffectClass, context.task.constraints.maxEffectClass)) reasons.push('effect-class');
  const budget = context.budgetLedger.canAdmit(worker, context.task, context.projectedChargeUsd?.[worker.workerId] ?? null);
  if (!budget.allowed) reasons.push(budget.reason);
  if (context.requiredToolUse && !worker.capabilities.toolUse) reasons.push('tool-use-required');
  return { admitted: reasons.length === 0, reasons };
}

function scoreWorker(worker, context) {
  const capability = MODE_CAPABILITY[context.task.mode] || 'planning';
  const fit = Number(worker.capabilities[capability] || 0);
  const local = worker.locality === 'local' ? 1 : worker.locality === 'hybrid' ? 0.6 : 0;
  const localityWeight = context.task.constraints.localFirst ? 0.15 : 0.03;
  const reliability = worker.reliability;
  const latency = LATENCY_SCORE[worker.latencyClass] ?? 0.45;
  const headroom = worker.contextLimit ? Math.max(0, Math.min(1, (worker.contextLimit - context.contextTokens) / worker.contextLimit)) : 0.5;
  const failurePenalty = Math.min(0.35, Number(context.failureCounts?.[worker.workerId] || 0) * 0.08);
  const costPreference = worker.costClass === 'local' ? 1 : worker.costClass === 'free-quota' ? 0.9 : worker.costClass === 'subscription' ? 0.7 : worker.costClass === 'enterprise-budget' ? 0.6 : worker.costClass === 'billable-api' ? 0.35 : 0.45;
  return (fit * 0.42) + (local * localityWeight) + (reliability * 0.18) + (latency * 0.08) + (headroom * 0.07) + (costPreference * 0.10) - failurePenalty;
}

function chooseWorker(registry, context) {
  const evaluated = registry.list().map(worker => {
    const admission = admitWorker(worker, { ...context, registry });
    return { worker, ...admission, score: admission.admitted ? scoreWorker(worker, context) : null };
  });
  const requested = context.requestedWorkerId;
  if (requested && requested !== 'auto') {
    const row = evaluated.find(item => item.worker.workerId === requested);
    if (!row) return { selected: null, evaluated, reason: 'requested-worker-not-found' };
    if (!row.admitted) return { selected: null, evaluated, reason: `requested-worker-rejected:${row.reasons.join('|')}` };
    return { selected: row.worker, evaluated, reason: 'explicit-worker' };
  }
  const admitted = evaluated.filter(r => r.admitted).sort((a, b) => b.score - a.score || a.worker.workerId.localeCompare(b.worker.workerId));
  return { selected: admitted[0]?.worker || null, evaluated, reason: admitted[0] ? 'highest-admitted-score' : 'no-admitted-worker' };
}

module.exports = { admitWorker, scoreWorker, chooseWorker, effectAllows };
