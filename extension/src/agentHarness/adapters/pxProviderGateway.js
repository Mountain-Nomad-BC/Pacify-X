'use strict';

const { ExecutionAdapter } = require('./base');

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
      signal: input.signal
    });
    if (!result || !result.receipt) throw new Error('px-provider-gateway-exact-receipt-missing');
    const text = typeof result.value === 'string' ? result.value : String(result.value?.text ?? result.value?.answer ?? '');
    if (text) input.onEvent({ type: 'worker.stream.delta', status: 'progress', summary: text.slice(0, 500), payload: { delta: text, terminal: true } });
    const receipt = result.receipt;
    const providerReceipt = receipt.provider_receipt || receipt.providerReceipt || {};
    return {
      text,
      usage: {
        inputTokens: providerReceipt.input_tokens ?? providerReceipt.inputTokens ?? null,
        outputTokens: providerReceipt.output_tokens ?? providerReceipt.outputTokens ?? null,
        totalTokens: total(providerReceipt),
        actualChargeUsd: microunitsToUsd(providerReceipt.charge_microunits ?? providerReceipt.chargeMicrounits),
        billingIdentityKnown: providerReceipt.billing_state !== 'unknown',
        quotaRemaining: null
      },
      exactReceipt: receipt
    };
  }
}

function total(receipt) {
  const i = receipt.input_tokens ?? receipt.inputTokens; const o = receipt.output_tokens ?? receipt.outputTokens;
  return Number.isInteger(i) && Number.isInteger(o) ? i + o : null;
}
function microunitsToUsd(value) { return Number.isInteger(value) && value >= 0 ? value / 1_000_000 : null; }

module.exports = { PxProviderGatewayAdapter };
