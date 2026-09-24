'use strict';

const { newId } = require('./ids');
const { chooseWorker } = require('./router');
const { evaluateCompletion } = require('./completionEvaluator');

class HarnessController {
  constructor(deps) {
    Object.assign(this, deps); this.evidence = new Map(); this.active = new Map(); this.lastLibrarian = new Map(); this.lastContext = new Map(); this.lastRoute = new Map();
  }

  createTask(input) {
    const task = this.taskStore.createTask(input); this.eventBus.emit('task.created', { taskId: task.taskId, status: 'succeeded', summary: task.goal, payload: { mode: task.mode } }); return task;
  }

  async sendTurn(input) {
    let task = input.taskId ? this.taskStore.requireTask(input.taskId) : this.createTask(input);
    let run = input.runId ? this.taskStore.requireRun(input.runId) : this.taskStore.createRun(task.taskId);
    const turnId = newId('turn'); const roundId = newId('round'); const abort = new AbortController(); this.active.set(run.runId, { abort, workerId: null });
    this.eventBus.emit('turn.started', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'started', summary: String(input.message || '').slice(0, 500) });
    try {
      task = this.taskStore.updateTask(task.taskId, { stage: 'CLASSIFY' });
      this.eventBus.emit('librarian.classification.started', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'started', summary: 'Classifying intent, domain, skills and retrieval need.' });
      const librarian = await this.tinyLibrarian.classify(task, input.message); this.lastLibrarian.set(task.taskId, librarian);
      task = this.taskStore.updateTask(task.taskId, { stage: librarian.stage, activeSkills: librarian.skillCandidates, confidence: librarian.confidence });
      this.eventBus.emit('librarian.classification.completed', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'succeeded', summary: `${librarian.intent} · ${librarian.domains.join(', ')}`, payload: librarian });

      const contextPack = await this.contextCompiler.compile({ task, librarian, explicitRefs: input.explicitRefs || [] }); this.lastContext.set(task.taskId, contextPack);
      this.eventBus.emit('context.compiled', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'succeeded', summary: `${contextPack.selectedCount}/${contextPack.consideredCount} refs · ${contextPack.suppliedTokens}/${contextPack.budgetTokens} tokens`, payload: { contextId: contextPack.contextId, consideredCount: contextPack.consideredCount, selectedCount: contextPack.selectedCount, suppliedTokens: contextPack.suppliedTokens, budgetTokens: contextPack.budgetTokens, refs: contextPack.refs.map(r => ({ refId: r.refId, kind: r.kind, label: r.label, source: r.source, tokenEstimate: r.tokenEstimate, authority: r.authority, freshAt: r.freshAt, sha256: r.sha256 })) } });

      const route = chooseWorker(this.workerRegistry, { task, contextTokens: contextPack.suppliedTokens, budgetLedger: this.budgetLedger, requiredToolUse: input.requiredToolUse === true, requestedWorkerId: input.workerId || 'auto', projectedChargeUsd: input.projectedChargeUsd || {}, failureCounts: input.failureCounts || {} }); this.lastRoute.set(task.taskId, route);
      this.eventBus.emit('worker.route.evaluated', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: route.selected ? 'succeeded' : 'blocked', summary: route.reason,
        payload: { selectedWorkerId: route.selected?.workerId || null, evaluated: route.evaluated.map(r => ({ workerId: r.worker.workerId, displayName: r.worker.displayName, admitted: r.admitted, reasons: r.reasons, score: r.score, costClass: r.worker.costClass })) } });
      if (!route.selected) { this.taskStore.updateRun(run.runId, { status: 'blocked', lastError: route.reason }); return { task, run: this.taskStore.requireRun(run.runId), blocked: true, reason: route.reason }; }

      run = this.taskStore.selectWorker(run.runId, route.selected.workerId, route.reason); this.active.get(run.runId).workerId = route.selected.workerId;
      this.eventBus.emit('worker.selected', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'succeeded', summary: route.selected.displayName, payload: { providerId: route.selected.providerId, modelId: route.selected.modelId, costClass: route.selected.costClass } });
      const adapter = this.workerRegistry.adapter(route.selected.workerId); if (!adapter) throw new Error('selected-worker-adapter-missing');
      this.eventBus.emit('worker.started', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'started', summary: route.selected.displayName });
      const onEvent = event => this.eventBus.emit(event.type, { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: event.status || 'info', summary: event.summary || '', payload: event.payload || {} });
      const result = await adapter.runTurn({ task, run, message: String(input.message || ''), contextPack, signal: abort.signal, onEvent, toolBroker: this.toolBroker });
      if (result?.sessionRef) this.taskStore.updateRun(run.runId, { providerSessionRef: String(result.sessionRef) });
      if (result?.usage) this.budgetLedger.record({ workerId: route.selected.workerId, providerId: route.selected.providerId, costClass: route.selected.costClass,
        inputTokens: result.usage.inputTokens ?? null, outputTokens: result.usage.outputTokens ?? null, totalTokens: result.usage.totalTokens ?? null,
        actualChargeUsd: result.usage.actualChargeUsd ?? null, projectedChargeUsd: result.usage.projectedChargeUsd ?? null, billingIdentityKnown: Boolean(result.usage.billingIdentityKnown), quotaRemaining: result.usage.quotaRemaining ?? null });
      this.eventBus.emit('worker.completed', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'succeeded', summary: 'Worker turn completed.', payload: { text: String(result?.text || '').slice(0, 120000) } });
      run = this.taskStore.updateRun(run.runId, { status: 'complete', round: run.round + 1 });
      const verdict = evaluateCompletion(this.taskStore.requireTask(task.taskId), this.evidence.get(task.taskId) || []);
      this.eventBus.emit('verification.completed', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: verdict.complete ? 'succeeded' : 'info', summary: verdict.complete ? 'Completion contract satisfied.' : 'Worker turn finished; completion contract still has open requirements.', payload: verdict });
      return { task: this.taskStore.requireTask(task.taskId), run, text: result?.text || '', librarian, contextPack, route, verdict };
    } catch (error) {
      const aborted = error?.name === 'AbortError' || abort.signal.aborted; run = this.taskStore.updateRun(run.runId, { status: aborted ? 'cancelled' : 'failed', lastError: String(error?.message || error).slice(0, 1000) });
      this.eventBus.emit(aborted ? 'run.cancelled' : 'run.failed', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: this.active.get(run.runId)?.workerId || null, status: aborted ? 'cancelled' : 'failed', summary: run.lastError || 'run failed' });
      throw error;
    } finally { this.active.delete(run.runId); }
  }

  async cancelRun(runId) { const active = this.active.get(runId); if (!active) return false; active.abort.abort(); const adapter = active.workerId ? this.workerRegistry.adapter(active.workerId) : null; try { await adapter?.interrupt?.(); } catch {} return true; }

  project(taskId = null) {
    const tasks = taskId ? [this.taskStore.requireTask(taskId)] : this.taskStore.listTasks(); const activeTask = tasks.at(-1) || null;
    const runs = activeTask ? this.taskStore.listRuns(activeTask.taskId) : []; const run = runs.at(-1) || null;
    return { schemaVersion: 'px.agent-console-state/1.0', activeTask, activeRun: run, workers: this.workerRegistry.list().map(w => ({ ...w, health: this.workerRegistry.getHealth(w.workerId) })),
      librarian: activeTask ? this.lastLibrarian.get(activeTask.taskId) || null : null, context: activeTask ? this.lastContext.get(activeTask.taskId) || null : null,
      route: activeTask ? this.lastRoute.get(activeTask.taskId) || null : null, budget: this.budgetLedger.summary(), evidence: activeTask ? this.evidence.get(activeTask.taskId) || [] : [],
      events: activeTask ? this.eventBus.snapshot({ taskId: activeTask.taskId, limit: 240 }) : this.eventBus.snapshot({ limit: 120 }) };
  }

  dispose() { for (const { abort } of this.active.values()) abort.abort(); this.active.clear(); this.eventBus.dispose(); }
}

module.exports = { HarnessController };
