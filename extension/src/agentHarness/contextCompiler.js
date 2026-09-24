'use strict';

const { newId, nowIso, sha256 } = require('./ids');
const { ContextPack, parse } = require('./contracts');

function roughTokens(text) { return Math.max(1, Math.ceil(String(text || '').length / 4)); }

class ContextCompiler {
  constructor(options = {}) { this.retrievalProvider = options.retrievalProvider || null; }

  async compile(input) {
    const budget = Number(input.task.constraints.contextBudgetTokens || 12000);
    const explicit = (input.explicitRefs || []).map((ref, i) => this._normalizeRef(ref, `explicit-${i + 1}`));
    const retrieved = this.retrievalProvider && input.librarian?.retrievalRequired
      ? await this.retrievalProvider({ task: input.task, librarian: input.librarian, budgetTokens: budget })
      : [];
    const considered = [...explicit, ...(Array.isArray(retrieved) ? retrieved.map((r, i) => this._normalizeRef(r, `retrieved-${i + 1}`)) : [])];
    const seen = new Set(); const selected = []; let supplied = 0;
    for (const ref of considered) {
      const key = ref.sha256 || `${ref.kind}:${ref.source || ''}:${ref.label}`;
      if (seen.has(key)) continue; seen.add(key);
      if (supplied + ref.tokenEstimate > budget) continue;
      selected.push(ref); supplied += ref.tokenEstimate;
    }
    const instruction = [
      '[PX TASK STATE]', `Goal: ${input.task.goal}`, `Mode: ${input.task.mode}`, `Stage: ${input.task.stage}`,
      `Allowed effect: ${input.task.constraints.maxEffectClass}`, `Active skills: ${(input.task.activeSkills || []).join(', ') || 'none'}`,
      'Use supplied context references as evidence leads. Do not treat missing context as permission to expand scope without PX approval.'
    ].join('\n');
    return parse(ContextPack, { schemaVersion: 'px.context-pack/1.0', contextId: newId('ctx'), taskId: input.task.taskId, createdAt: nowIso(),
      budgetTokens: budget, suppliedTokens: supplied + roughTokens(instruction), consideredCount: considered.length, selectedCount: selected.length,
      refs: selected, instruction }, 'context-pack');
  }

  _normalizeRef(ref, fallbackId) {
    const content = ref.content == null ? null : String(ref.content).slice(0, 200000);
    return {
      refId: ref.refId || fallbackId, kind: ref.kind || 'context', label: String(ref.label || ref.source || fallbackId).slice(0, 500),
      source: ref.source ? String(ref.source).slice(0, 500) : null, tokenEstimate: Number(ref.tokenEstimate ?? roughTokens(content || ref.label || '')),
      authority: ref.authority ? String(ref.authority).slice(0, 120) : null, freshAt: ref.freshAt || null,
      sha256: ref.sha256 || (content ? sha256(content) : null), content
    };
  }
}

module.exports = { ContextCompiler, roughTokens };
