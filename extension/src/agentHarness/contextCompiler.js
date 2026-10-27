'use strict';

const { newId, nowIso, sha256 } = require('./ids');
const { ContextPack, parse } = require('./contracts');

function roughTokens(text) { return Math.max(1, Math.ceil(String(text || '').length / 4)); }

class ContextCompiler {
  constructor(options = {}) { this.retrievalProvider = options.retrievalProvider || null; }

  async compile(input) {
    const budget = input.task.constraints.contextBudgetTokens;
    if (!Number.isSafeInteger(budget) || budget < 1) throw new Error('context-budget-invalid');
    if (!Array.isArray(input.explicitRefs || []) || (input.explicitRefs || []).length > 256) throw new Error('context-reference-count-budget');
    const explicit = (input.explicitRefs || []).map((ref, i) => this._normalizeRef(ref, `explicit-${i + 1}`));
    const retrieved = this.retrievalProvider && input.librarian?.retrievalRequired
      ? await this.retrievalProvider({ task: input.task, librarian: input.librarian, budgetTokens: budget })
      : [];
    const instruction = [
      '[PX TASK STATE]', `Goal: ${input.task.goal}`, `Mode: ${input.task.mode}`, `Stage: ${input.task.stage}`,
      `Allowed effect: ${input.task.constraints.maxEffectClass}`, `Active skills: ${(input.task.activeSkills || []).join(', ') || 'none'}`,
      'Use supplied context references as evidence leads. Do not treat missing context as permission to expand scope without PX approval.'
    ].join('\n');
    const instructionTokens = roughTokens(instruction);
    if (instructionTokens > budget) throw new Error('context-instruction-exceeds-budget');
    if (retrieved != null && !Array.isArray(retrieved)) throw new Error('context-retrieval-array-required');
    if ((retrieved || []).length + explicit.length > 256) throw new Error('context-reference-count-budget');
    const considered = [...explicit, ...(Array.isArray(retrieved) ? retrieved.map((r, i) => this._normalizeRef(r, `retrieved-${i + 1}`)) : [])];
    const seen = new Set(); const selected = []; let supplied = instructionTokens;
    for (const ref of considered) {
      const key = ref.sha256 || `${ref.kind}:${ref.source || ''}:${ref.label}`;
      if (seen.has(key)) continue; seen.add(key);
      if (selected.length >= 120 || supplied + ref.tokenEstimate > budget) continue;
      selected.push(ref); supplied += ref.tokenEstimate;
    }

    return parse(ContextPack, { schemaVersion: 'px.context-pack/1.0', contextId: newId('ctx'), taskId: input.task.taskId, createdAt: nowIso(),
      budgetTokens: budget, suppliedTokens: supplied, consideredCount: considered.length, selectedCount: selected.length,
      refs: selected, instruction }, 'context-pack');
  }

  _normalizeRef(ref, fallbackId) {
    if (!ref || typeof ref !== 'object' || Array.isArray(ref)) throw new Error('context-reference-object-required');
    if (ref.content != null && (typeof ref.content !== 'string' || ref.content.length > 200000)) throw new Error('context-reference-content-budget');
    const content = ref.content ?? null;
    const actualDigest = content !== null ? sha256(content) : null;
    if (content !== null && ref.sha256 != null && ref.sha256 !== actualDigest) throw new Error('context-reference-digest-mismatch');
    const declared = ref.tokenEstimate ?? 0;
    if (!Number.isSafeInteger(declared) || declared < 0) throw new Error('context-token-estimate-invalid');
    const value = {
      refId: ref.refId || fallbackId, kind: ref.kind || 'context', label: String(ref.label || ref.source || fallbackId).slice(0, 500),
      source: ref.source ? String(ref.source).slice(0, 500) : null, tokenEstimate: 0,
      authority: ref.authority ? String(ref.authority).slice(0, 120) : null, freshAt: ref.freshAt || null,
      sha256: actualDigest ?? ref.sha256 ?? null, content
    };
    // Caller estimates can reserve MORE room, never discount the evidence image.
    value.tokenEstimate = Math.max(declared, roughTokens(JSON.stringify(value)) + 16);
    return value;
  }
}

module.exports = { ContextCompiler, roughTokens };
