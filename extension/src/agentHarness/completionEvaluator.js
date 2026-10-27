'use strict';

const { Evidence, PxRun } = require('./contracts');

// This enforces ownership and record shape, not authenticity. The host must
// still supply evidence through its governed receipt ingestion owner.
function currentEvidence(task, evidence, currentRun) {
  const parsedRun = PxRun.safeParse(currentRun);
  if (!parsedRun.success || parsedRun.data.taskId !== task.taskId ||
      !['running', 'complete'].includes(parsedRun.data.status) ||
      !Array.isArray(evidence) || evidence.length > 10000) return [];
  const run = parsedRun.data;
  const started = Date.parse(run.createdAt);
  const ended = run.status === 'complete' ? Math.min(Date.now(), Date.parse(run.updatedAt)) : Date.now();
  const records = new Map(); const conflicts = new Set();
  for (const value of evidence) {
    const parsed = Evidence.safeParse(value);
    if (!parsed.success) {
      if (typeof value?.evidenceId === 'string') conflicts.add(value.evidenceId);
      continue;
    }
    const item = parsed.data; const encoded = JSON.stringify(item);
    if (records.has(item.evidenceId) && records.get(item.evidenceId).encoded !== encoded) conflicts.add(item.evidenceId);
    else records.set(item.evidenceId, { item, encoded });
  }
  return [...records.values()].map(record => record.item).filter(item =>
    !conflicts.has(item.evidenceId) && item.taskId === task.taskId && item.runId === run.runId &&
    Date.parse(item.capturedAt) >= started && Date.parse(item.capturedAt) <= ended);
}

function evaluateCompletion(task, evidence = [], currentRun = null) {
  const eligible = currentEvidence(task, evidence, currentRun);
  const rows = task.completionContract.map(requirement => {
    const matching = eligible.filter(item => requirement.evidenceTypes.includes(item.type) && item.status === 'pass');
    return { requirementId: requirement.id, label: requirement.label, required: requirement.required, satisfied: matching.length > 0, evidenceIds: matching.map(item => item.evidenceId) };
  });
  const required = rows.filter(r => r.required);
  const complete = required.every(r => r.satisfied);
  return { schemaVersion: 'px.completion-verdict/1.0', taskId: task.taskId, complete, satisfiedRequired: required.filter(r => r.satisfied).length, totalRequired: required.length, requirements: rows };
}

module.exports = { evaluateCompletion };
