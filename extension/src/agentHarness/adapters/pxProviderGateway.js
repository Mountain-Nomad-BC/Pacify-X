'use strict';

const { ExecutionAdapter } = require('./base');
const { sha256 } = require('../ids');

function canonical(value, depth = 0) {
  if (depth > 16) throw new Error('px-provider-receipt-depth');
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isSafeInteger(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(item => canonical(item, depth + 1)).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key], depth + 1)}`).join(',')}}`;
  throw new Error('px-provider-receipt-json-invalid');
}

function receiptDigest(receipt, field) {
  const body = { ...receipt }; delete body[field];
  const raw = canonical(body);
  if (Buffer.byteLength(raw, 'utf8') > 64 * 1024) throw new Error('px-provider-receipt-size');
  return sha256(raw);
}

function verifiedReceipt(value, worker, input) {
  const hex = item => typeof item === 'string' && /^[a-f0-9]{64}$/.test(item);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('px-provider-settlement-invalid');
  let receipt = value;
  if (value.schema_version === 'px.provider-execution-outcome/1.0') {
    if (value.exact_receipt !== true || !hex(value.outcome_sha256) || receiptDigest(value, 'outcome_sha256') !== value.outcome_sha256) throw new Error('px-provider-receipt-integrity');
    for (const key of ['policy_sha256', 'task_plan_sha256', 'model_attachment_sha256']) if (!hex(value[key])) throw new Error('px-provider-receipt-policy-binding');
    receipt = value.provider_receipt;
  } else if (value.schema_version !== 'px.provider-stream-receipt/1.0') throw new Error('px-provider-receipt-schema');
  if (!receipt || !['px.provider-stream-receipt/1.0', 'px.provider-invocation-receipt/1.0'].includes(receipt.schema_version)) throw new Error('px-provider-receipt-schema');
  if (receipt.schema_version === 'px.provider-stream-receipt/1.0' && (!hex(receipt.receipt_sha256) || receiptDigest(receipt, 'receipt_sha256') !== receipt.receipt_sha256)) throw new Error('px-provider-receipt-integrity');
  for (const key of ['input_sha256', 'output_sha256', 'budget_receipt_sha256', 'budget_reservation_receipt_sha256']) if (!hex(receipt[key])) throw new Error('px-provider-receipt-binding');
  for (const key of ['invocation_id', 'correlation_id', 'adapter_id', 'provider_id', 'model_id']) if (typeof receipt[key] !== 'string' || !receipt[key] || receipt[key].length > 512) throw new Error('px-provider-receipt-identity');
  if (receipt.provider_id !== worker.providerId || receipt.model_id !== worker.modelId ||
      (input.executionContext && receipt.invocation_id !== input.executionContext.execution_id) ||
      (input.task?.taskId && receipt.correlation_id !== `corr-${input.task.taskId}`)) throw new Error('px-provider-receipt-owner-mismatch');
  if (!Number.isSafeInteger(receipt.started_revision) || receipt.started_revision < 1 ||
      !Number.isSafeInteger(receipt.completed_revision) || receipt.completed_revision <= receipt.started_revision ||
      receipt.failed === true || receipt.exact_receipt === false || ['failed', 'cancelled', 'failure'].includes(receipt.status)) throw new Error('px-provider-settlement-not-completed');
  if (!['actual', 'estimated', 'local_non_billable', 'unknown'].includes(receipt.billing_state) || receipt.currency !== 'USD') throw new Error('px-provider-settlement-billing-invalid');
  for (const key of ['input_tokens', 'output_tokens', 'charge_microunits']) if (receipt[key] !== null && (!Number.isSafeInteger(receipt[key]) || receipt[key] < 0)) throw new Error('px-provider-settlement-number-invalid');
  if (worker.costClass === 'local' && (receipt.billing_state !== 'local_non_billable' || receipt.charge_microunits !== 0)) throw new Error('px-provider-settlement-local-charge');
  return receipt;
}

// Preferred production boundary for providers already admitted by PX.
// The callback must invoke PX's canonical provider gateway / exact execution
// policy and return an authoritative receipt. This adapter intentionally does
// not implement its own networking, credential handling, or pricing logic.
class PxProviderGatewayAdapter extends ExecutionAdapter {
  constructor(options = {}) {
    super(options);
    if (typeof options.invokeProvider !== 'function') throw new Error('px-provider-gateway-invoker-required');
    this.invokeProvider = options.invokeProvider;
    this.worker = options.worker;
  }

  async health() {
    if (typeof this.options.healthProvider !== 'function') return { status: 'unknown', detail: 'PX gateway health provider not connected' };
    return this.options.healthProvider(this.worker);
  }

  async runTurn(input) {
    const result = await this.invokeProvider({
      worker: this.worker,
      task: input.task,
      run: input.run,
      message: input.message,
      contextPack: input.contextPack,
      executionContext: input.executionContext,
      maxOutputTokens: input.maxOutputTokens,
      signal: input.signal,
      onEvent: input.onEvent
    });
    if (!result || !result.receipt) throw new Error('px-provider-gateway-exact-receipt-missing');
    const providerReceipt = verifiedReceipt(result.receipt, this.worker, input);
    const text = typeof result.value === 'string' ? result.value : String(result.value?.text ?? result.value?.answer ?? '');
    if (text && result.streamed !== true) input.onEvent({ type: 'worker.stream.delta', status: 'progress', summary: text.slice(0, 500), payload: { delta: text, terminal: true } });
    const receipt = result.receipt;
    return {
      text,
      usage: {
        inputTokens: providerReceipt.input_tokens ?? providerReceipt.inputTokens ?? null,
        outputTokens: providerReceipt.output_tokens ?? providerReceipt.outputTokens ?? null,
        totalTokens: total(providerReceipt),
        actualChargeUsd: ['actual', 'local_non_billable'].includes(providerReceipt.billing_state) ? microunitsToUsd(providerReceipt.charge_microunits) : null,
        projectedChargeUsd: providerReceipt.billing_state === 'estimated' ? microunitsToUsd(providerReceipt.charge_microunits) : null,
        billingIdentityKnown: providerReceipt.billing_state !== 'unknown',
        quotaRemaining: null
      },
      exactReceipt: receipt,
      settlementId: providerReceipt.budget_receipt_sha256
    };
  }
}

function total(receipt) {
  const i = receipt.input_tokens ?? receipt.inputTokens; const o = receipt.output_tokens ?? receipt.outputTokens;
  return Number.isSafeInteger(i) && Number.isSafeInteger(o) && Number.isSafeInteger(i + o) ? i + o : null;
}
function microunitsToUsd(value) { return Number.isSafeInteger(value) && value >= 0 ? value / 1_000_000 : null; }

module.exports = { PxProviderGatewayAdapter, verifiedReceipt };
