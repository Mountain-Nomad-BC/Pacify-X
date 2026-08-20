'use strict';

const HASH_FIELDS = Object.freeze([
  'revision_sha256',
  'content_sha256',
  'definition_sha256',
  'sha256'
]);

function object(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
}

function text(value) {
  return value == null ? '' : String(value).trim();
}

function finite(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function identityPart(value, names) {
  for (const name of names) {
    const candidate = text(value?.[name]);
    if (candidate) return candidate;
  }
  return '';
}

function traceIdentity(value, fallback = {}) {
  const row = object(value) || {};
  const prior = object(fallback) || {};
  return {
    workflow_id: identityPart(row, ['workflow_id', 'subject_id']) || text(prior.workflow_id),
    version: text(row.version) || text(prior.version),
    revision_sha256: identityPart(row, HASH_FIELDS) || text(prior.revision_sha256),
    run_id: text(row.run_id) || text(prior.run_id)
  };
}

function completeIdentity(identity) {
  return Boolean(identity?.workflow_id && identity?.version && identity?.run_id);
}

function identityConflict(left, right, { includeRun = true } = {}) {
  if (!left || !right) return false;
  for (const field of ['workflow_id', 'version', 'revision_sha256']) {
    if (left[field] && right[field] && left[field] !== right[field]) return true;
  }
  return Boolean(includeRun && left.run_id && right.run_id && left.run_id !== right.run_id);
}

function sameIdentity(left, right) {
  return completeIdentity(left) && completeIdentity(right) && !identityConflict(left, right)
    && left.workflow_id === right.workflow_id
    && left.version === right.version
    && left.run_id === right.run_id;
}

function receiptFailure(receipt) {
  const failure = object(receipt.failure);
  const lastAttempt = Array.isArray(receipt.attempts) && receipt.attempts.length
    ? object(receipt.attempts[receipt.attempts.length - 1])
    : null;
  const failed = /fail|error|cancel/i.test(text(receipt.state));
  const source = failure || (failed ? lastAttempt : null) || receipt;
  const projected = {};
  for (const field of ['failure_type', 'failure_message', 'failure_correlation_id', 'correlation_id', 'code', 'message']) {
    if (source?.[field] != null && text(source[field])) projected[field] = String(source[field]);
  }
  return Object.keys(projected).length ? projected : null;
}

function projectReceipt(receipt) {
  if (!object(receipt) || !text(receipt.node_id)) return null;
  const projected = { node_id: text(receipt.node_id) };
  for (const field of ['state', 'kind', 'skip_reason']) {
    if (text(receipt[field])) projected[field] = text(receipt[field]);
  }
  if (Array.isArray(receipt.attempts)) projected.attempt_count = receipt.attempts.length;
  else if (Number.isInteger(receipt.attempt_count) && receipt.attempt_count >= 0) projected.attempt_count = receipt.attempt_count;
  if (finite(receipt.duration_ms) && receipt.duration_ms >= 0) projected.duration_ms = receipt.duration_ms;
  if (Array.isArray(receipt.disabled_required_ports)) projected.disabled_required_ports = receipt.disabled_required_ports.map(String);
  if (object(receipt.approval_execution)) projected.approval_execution = { ...receipt.approval_execution };
  if (object(receipt.recovery)) projected.recovery = { ...receipt.recovery };
  else if (typeof receipt.recovery === 'string' && receipt.recovery.trim()) projected.recovery = receipt.recovery;
  const failure = receiptFailure(receipt);
  if (failure) projected.failure = failure;
  return projected;
}

function receiptRows(value) {
  if (Array.isArray(value?.node_receipts)) return value.node_receipts;
  if (Array.isArray(value?.checkpoint?.node_receipts)) return value.checkpoint.node_receipts;
  return [];
}

function selectResult(result, currentIdentity) {
  const envelope = object(result) || {};
  const value = object(envelope.record) || envelope;
  if (!Array.isArray(value.runs)) return { value, fromList: false };
  if (!completeIdentity(currentIdentity)) return { value: null, fromList: true };
  const match = value.runs.find(row => sameIdentity(traceIdentity(row), currentIdentity));
  return { value: object(match), fromList: true };
}

function projectWorkflowTrace(result, options = {}) {
  const expectedIdentity = traceIdentity(options.expectedIdentity);
  const currentIdentity = traceIdentity(options.currentIdentity);
  const selected = selectResult(result, currentIdentity);
  if (!selected.value) {
    return { action: selected.fromList ? 'unchanged' : 'clear', reason: selected.fromList ? 'no-current-run-in-list' : 'trace-result-invalid', identity: null, nodes: {}, metadata: {} };
  }
  const explicitIdentity = traceIdentity(selected.value);
  if (identityConflict(explicitIdentity, expectedIdentity, { includeRun: false })) {
    return { action: 'clear', reason: 'editor-identity-mismatch', identity: null, nodes: {}, metadata: {} };
  }
  const identity = traceIdentity(selected.value, {
    ...expectedIdentity,
    revision_sha256: expectedIdentity.revision_sha256 || currentIdentity.revision_sha256
  });
  if (!completeIdentity(identity)) {
    return { action: 'clear', reason: 'trace-identity-incomplete', identity: null, nodes: {}, metadata: {} };
  }
  if (completeIdentity(currentIdentity) && identityConflict(identity, currentIdentity)) {
    if (options.allowNewRun !== true || identityConflict(identity, expectedIdentity, { includeRun: false })) {
      return { action: 'clear', reason: 'current-run-identity-mismatch', identity: null, nodes: {}, metadata: {} };
    }
  }
  const nodes = {};
  for (const receipt of receiptRows(selected.value)) {
    const projected = projectReceipt(receipt);
    if (projected) nodes[projected.node_id] = projected;
  }
  const checkpoint = object(selected.value.checkpoint) || {};
  const metadata = {};
  if (Array.isArray(checkpoint.ready_nodes)) metadata.ready_nodes = checkpoint.ready_nodes.map(String);
  if (Object.hasOwn(checkpoint, 'next_node')) metadata.next_node = checkpoint.next_node == null ? null : String(checkpoint.next_node);
  if (checkpoint.recovery != null) metadata.recovery = object(checkpoint.recovery) ? { ...checkpoint.recovery } : String(checkpoint.recovery);
  if (object(selected.value.failure)) metadata.failure = { ...selected.value.failure };
  if (text(selected.value.state || selected.value.run_state || selected.value.status)) metadata.run_state = text(selected.value.state || selected.value.run_state || selected.value.status);
  return { action: 'replace', reason: selected.fromList ? 'current-run-refreshed-from-list' : 'trace-projected', identity, nodes, metadata };
}

module.exports = {
  completeIdentity,
  identityConflict,
  projectReceipt,
  projectWorkflowTrace,
  sameIdentity,
  traceIdentity
};
