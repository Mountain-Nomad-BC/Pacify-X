'use strict';

function evaluateCompletion(task, evidence = []) {
  const rows = task.completionContract.map(requirement => {
    const matching = evidence.filter(item => requirement.evidenceTypes.includes(item.type) && item.status === 'pass');
    return { requirementId: requirement.id, label: requirement.label, required: requirement.required, satisfied: matching.length > 0, evidenceIds: matching.map(item => item.evidenceId) };
  });
  const required = rows.filter(r => r.required);
  const complete = required.every(r => r.satisfied);
  return { schemaVersion: 'px.completion-verdict/1.0', taskId: task.taskId, complete, satisfiedRequired: required.filter(r => r.satisfied).length, totalRequired: required.length, requirements: rows };
}

module.exports = { evaluateCompletion };
