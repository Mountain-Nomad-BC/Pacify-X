'use strict';

const crypto = require('node:crypto');

const PROVIDER_POLICY_VIOLATION_IDS = Object.freeze([
  'PX-PROVIDER-SCHEMA',
  'PX-PROVIDER-POLICY-HASH',
  'PX-PROVIDER-PLAN-BINDING',
  'PX-PROVIDER-MODEL-BINDING',
  'PX-PROVIDER-AUTHORITY',
  'PX-PROVIDER-EGRESS',
  'PX-PROVIDER-COST',
  'PX-PROVIDER-FALLBACK',
  'PX-PROVIDER-RECEIPT'
]);

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}

function digest(value) { return crypto.createHash('sha256').update(canonical(value)).digest('hex'); }
function sha(value) { return typeof value === 'string' && /^[a-f0-9]{64}$/.test(value); }

function buildProviderExecutionPolicy(values) {
  const base = { schema_version: 'px.provider-execution-policy/1.0', ...values };
  delete base.policy_sha256;
  return { ...base, policy_sha256: digest(base) };
}

function providerExecutionPolicyReport(policy, request) {
  const violations = [];
  if (policy?.schema_version !== 'px.provider-execution-policy/1.0') violations.push(PROVIDER_POLICY_VIOLATION_IDS[0]);
  const unsigned = Object.fromEntries(Object.entries(policy || {}).filter(([key]) => key !== 'policy_sha256'));
  if (policy?.policy_sha256 !== digest(unsigned)) violations.push(PROVIDER_POLICY_VIOLATION_IDS[1]);
  if (!sha(policy?.task_plan_sha256) || policy.task_plan_sha256 !== request?.task_plan_sha256) violations.push(PROVIDER_POLICY_VIOLATION_IDS[2]);
  const model = policy?.model;
  const modelIdentity = ['provider_id', 'adapter_id', 'model_id', 'model_revision'].every(field => typeof model?.[field] === 'string' && model[field].length > 0)
    && sha(model?.attachment_sha256)
    && [['adapter_id', 'adapter_id'], ['model_id', 'model_id'], ['model_revision', 'model_revision'], ['attachment_sha256', 'model_attachment_sha256']].every(([field, requested]) => model[field] === request?.[requested]);
  if (!modelIdentity) violations.push(PROVIDER_POLICY_VIOLATION_IDS[3]);
  const authority = policy?.authority;
  if (!sha(authority?.revision) || authority.revision !== request?.authority_revision || authority.provider_effect !== true) violations.push(PROVIDER_POLICY_VIOLATION_IDS[4]);
  const egress = policy?.egress;
  const destinations = Array.isArray(egress?.allowed_destinations) ? egress.allowed_destinations : [];
  const egressValid = (egress?.mode === 'deny' && request?.requested_egress === 'deny')
    || (egress?.mode === 'loopback_only' && request?.requested_egress === 'loopback')
    || (egress?.mode === 'allowlist' && destinations.includes(request?.requested_egress));
  if (!egressValid) violations.push(PROVIDER_POLICY_VIOLATION_IDS[5]);
  const cost = policy?.cost;
  if (!Number.isSafeInteger(cost?.max_charge_microunits) || cost.max_charge_microunits < 0 || cost.budget_id !== request?.budget_id || !Number.isSafeInteger(request?.expected_charge_microunits) || request.expected_charge_microunits > cost.max_charge_microunits) violations.push(PROVIDER_POLICY_VIOLATION_IDS[6]);
  const privacy = { policy_gated: 0, isolated: 1, local: 2 };
  const authorityLevels = { contained: 0, installed_host: 1, external_authority: 2 };
  let fallbackValid = Boolean(model);
  for (const fallback of policy?.fallbacks || []) {
    if (!fallback || !['provider_id', 'adapter_id', 'model_id', 'model_revision'].every(field => typeof fallback[field] === 'string' && fallback[field].length > 0) || !sha(fallback.artifact_sha256)
      || (privacy[fallback.privacy] ?? -1) < (privacy[model?.privacy] ?? -1)
      || (authorityLevels[fallback.authority_class] ?? -1) < (authorityLevels[model?.authority_class] ?? -1)) fallbackValid = false;
  }
  if (!fallbackValid) violations.push(PROVIDER_POLICY_VIOLATION_IDS[7]);
  if (policy?.exact_receipt_required !== true) violations.push(PROVIDER_POLICY_VIOLATION_IDS[8]);
  const ordered = PROVIDER_POLICY_VIOLATION_IDS.filter(id => violations.includes(id));
  return { schema_version: 'px.provider-execution-policy-conformance/1.0', valid: ordered.length === 0, violation_ids: ordered };
}

module.exports = { PROVIDER_POLICY_VIOLATION_IDS, buildProviderExecutionPolicy, providerExecutionPolicyReport };
