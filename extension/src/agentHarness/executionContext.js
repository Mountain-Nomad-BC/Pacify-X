'use strict';
const { sha256, newId } = require('./ids');

const CONTEXT_FIELDS = Object.freeze([
  'actor_id', 'authority_granted', 'authority_reference_sha256', 'cancellation_scope_id',
  'context_sha256', 'contract_set_revision', 'deadline_utc', 'effect_budget_sha256',
  'effect_intent_id', 'epoch', 'execution_id', 'generation_vector_sha256', 'gremlin_revision',
  'lease_id', 'model_execution_group_revision', 'network_policy_revision', 'parent_execution_id',
  'project_id', 'provider_id', 'revision', 'root_execution_id', 'schema_version', 'session_id',
  'trace_root_id', 'workflow_adapter_revision'
]);

function digest(value) {
  // Native bounded_canonical_json_bytes uses sorted UTF-8 JSON plus one newline.
  const ordered = {};
  for (const key of Object.keys(value).sort()) ordered[key] = value[key];
  return sha256(`${JSON.stringify(ordered)}\n`);
}

function createExecutionContext({ run, projectId, sessionId, providerId, authoritySha256, effectBudgetSha256, deadlineMs = 300000, generationSha256 = null }) {
  if (!Number.isSafeInteger(deadlineMs) || deadlineMs < 1 || deadlineMs > 1800000) throw new Error('execution-deadline-budget-invalid');
  for (const value of [authoritySha256, effectBudgetSha256]) if (!/^[0-9a-f]{64}$/.test(value)) throw new Error('execution-reference-invalid');
  const body = { schema_version: 'px.execution-context/1.0', execution_id: newId('invocation'),
    parent_execution_id: run.runId, root_execution_id: run.runId, project_id: projectId,
    session_id: sessionId, revision: run.revision, epoch: run.epoch,
    generation_vector_sha256: generationSha256, authority_reference_sha256: authoritySha256,
    effect_budget_sha256: effectBudgetSha256, cancellation_scope_id: run.runId,
    deadline_utc: new Date(Date.now() + deadlineMs).toISOString(), actor_id: 'pacify-x-vscode',
    provider_id: providerId, trace_root_id: run.runId,
    model_execution_group_revision: null, contract_set_revision: null, gremlin_revision: null,
    network_policy_revision: null, workflow_adapter_revision: null, lease_id: null, effect_intent_id: null,
    authority_granted: false };
  return Object.freeze({ ...body, context_sha256: digest(body) });
}

function validateExecutionContextForRun(context, runId) {
  if (!context || typeof context !== 'object' || Array.isArray(context) ||
      context.schema_version !== 'px.execution-context/1.0' || context.authority_granted !== false) {
    throw new Error('execution-context-contract-invalid');
  }
  if (Object.keys(context).sort().join('\0') !== [...CONTEXT_FIELDS].sort().join('\0')) {
    throw new Error('execution-context-fields-invalid');
  }
  if (typeof runId !== 'string' || !runId ||
      context.root_execution_id !== runId || context.cancellation_scope_id !== runId) {
    throw new Error('execution-context-run-owner-mismatch');
  }
  const { context_sha256: suppliedDigest, ...body } = context;
  if (typeof suppliedDigest !== 'string' || !/^[0-9a-f]{64}$/.test(suppliedDigest) || digest(body) !== suppliedDigest) {
    throw new Error('execution-context-digest-mismatch');
  }
  const deadline = Date.parse(context.deadline_utc);
  if (!Number.isFinite(deadline) || deadline <= Date.now()) throw new Error('execution-context-deadline-expired');
  return context;
}

module.exports = { createExecutionContext, digest, validateExecutionContextForRun };
