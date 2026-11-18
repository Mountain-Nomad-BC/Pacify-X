'use strict';

const { newId, sha256 } = require('./ids');
const { chooseWorker } = require('./router');
const { evaluateCompletion } = require('./completionEvaluator');
const { verifiedReceipt } = require('./adapters/pxProviderGateway');
const { createExecutionContext } = require('./executionContext');
const { EFFECT_ORDER } = require('./taskStore');
const { isCapacityError } = require('./adapters/base');

const DEFAULT_OUTPUT_TOKEN_LIMIT = 1024;
const WORKER_INTERRUPT_TIMEOUT_MS = 5000;

function providerOutputTokenLimit(worker) {
  const configured = worker.bridge?.maxOutputTokens ?? worker.maxOutputTokens;
  if (configured == null) return null;
  if (!Number.isSafeInteger(configured) || configured < 1) throw new Error('worker-output-token-budget-invalid');
  return configured;
}

function providerOutputLimitForInvocation(worker) {
  return providerOutputTokenLimit(worker) ?? DEFAULT_OUTPUT_TOKEN_LIMIT;
}

function selectionAllowsWorker(worker, selection = {}) {
  return (!selection.serviceId || selection.serviceId === 'auto' || worker.providerId === selection.serviceId)
    && (!selection.modelId || selection.modelId === 'auto' || worker.modelId === selection.modelId)
    && (!selection.workerId || selection.workerId === 'auto' || worker.workerId === selection.workerId);
}

function providerRequestReserveTokens(message, workers, selection = {}) {
  const outputs = workers.filter(worker => worker.enabled && worker.bridge?.available !== false && selectionAllowsWorker(worker, selection))
    .map(providerOutputTokenLimit).filter(Number.isSafeInteger);
  const outputTokens = outputs.length ? Math.max(...outputs) : 0;
  return Math.ceil(String(message || '').length / 4) + outputTokens + 128;
}

// Native personal retrieval is not a provider-use grant. Until the explicit
// host custody/revalidation transport is commissioned, deny these copies before
// caching or adapter dispatch, including refs normalized by ContextCompiler.
function assertPersonalContextDispatchUnavailable(contextPack) {
  for (const ref of contextPack?.refs || []) {
    let provenance = null;
    if (typeof ref.content === 'string') {
      try { provenance = JSON.parse(ref.content); } catch { /* ordinary text */ }
    }
    if (ref.kind === 'personal-use-context' || String(ref.source || '').startsWith('personal-store:') ||
        provenance?.copy_kind === 'ephemeral-personal-context' ||
        provenance?.requires_current_native_use_before_provider_dispatch === true) {
      throw new Error('personal-context-provider-transport-not-commissioned');
    }
  }
}

class HarnessController {
  constructor(deps) {
    Object.assign(this, deps); this.evidence = new Map(); this.active = new Map(); this.lastLibrarian = new Map(); this.lastContext = new Map(); this.lastRoute = new Map();
  }

  createTask(input) {
    this._prepareTaskState();
    const task = this.taskStore.createTask(input); this.budgetLedger.registerCreatedTask?.(task); this.eventBus.emit('task.created', { taskId: task.taskId, status: 'succeeded', summary: task.goal, payload: { mode: task.mode } }); return task;
  }

  _prepareTaskState() {
    this.taskStore.prepare?.();
    if (this.budgetLedger.prepare) this.budgetLedger.prepare();
    else if (this.taskStore.preexistingTaskIds) this.budgetLedger.reconcilePreexistingTasks(this.taskStore.preexistingTaskIds);
    if (this.taskStore.projectId) this.projectId = this.taskStore.projectId;
  }

  async sendTurn(input) {
    this._prepareTaskState();
    await this.refreshWorkers?.();
    this.taskStore.assertCurrent?.();
    let task = input.taskId ? this.taskStore.requireTask(input.taskId) : this.createTask(input);
    if ([...this.active.values()].some(value => value.taskId === task.taskId)) throw new Error('task-already-executing');
    if (this.taskStore.requiresTaskRecovery(task.taskId)) throw new Error('task-recovery-required');
    let run = input.runId ? this.taskStore.requireRun(input.runId) : this.taskStore.createRun(task.taskId);
    if (run.taskId !== task.taskId) throw new Error('run-task-owner-mismatch');
    if (this.taskStore.requiresRecovery(run.runId)) throw new Error('run-recovery-required');
    if (run.dispatchMode !== 'single') throw new Error('run-dispatch-mode-mismatch');
    if (this.active.has(run.runId)) throw new Error('run-already-executing');
    if (['complete', 'failed', 'cancelled'].includes(run.status)) throw new Error('terminal-run-requires-new-run');
    if (run.status === 'waiting') {
      if (input.resume !== true) throw new Error('run-explicit-resume-required');
      run = this.taskStore.updateRun(run.runId, { status: 'running' });
    }
    const turnId = newId('turn'); const roundId = newId('round'); const abort = new AbortController(); this.active.set(run.runId, { abort, workerId: null, taskId: task.taskId });
    this.eventBus.emit('turn.started', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'started', summary: String(input.message || '').slice(0, 500) });
    try {
      await this.taskStore.flush();
      task = this.taskStore.updateTask(task.taskId, { stage: 'CLASSIFY' });
      this.eventBus.emit('librarian.classification.started', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'started', summary: 'Classifying intent, domain, skills and retrieval need.' });
      const librarian = await this.tinyLibrarian.classify(task, input.message); this.lastLibrarian.set(task.taskId, librarian);
      task = this.taskStore.updateTask(task.taskId, { stage: librarian.stage, activeSkills: librarian.skillCandidates, confidence: librarian.confidence });
      this.eventBus.emit('librarian.classification.completed', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'succeeded', summary: `${librarian.intent} Â· ${librarian.domains.join(', ')}`, payload: librarian });

      const experienceRefs = typeof this.tinyLibrarian.recall === 'function' ? await this.tinyLibrarian.recall(task) : [];
      const workers = this.workerRegistry.list();
      const requestedWorkerId = input.workerId || 'auto';
      const resolveSelection = (value, field) => {
        if (value == null || value === '' || value === 'auto') return undefined;
        if (typeof value !== 'string' || value.length > 256 || /[\x00-\x1f]/.test(value)) throw new Error(`worker-${field}-selection-invalid`);
        return value;
      };
      let checkedServiceId, checkedModelId;
      try {
        checkedServiceId = resolveSelection(input.serviceId, 'service');
        checkedModelId = resolveSelection(input.modelId, 'model');
      } catch (error) {
        this.taskStore.updateRun(run.runId, { status: 'blocked', lastError: String(error.message).slice(0, 1000) });
        await this.taskStore.flush();
        return { task, run: this.taskStore.requireRun(run.runId), blocked: true, reason: error.message };
      }
      const requestReserveTokens = providerRequestReserveTokens(input.message, workers, { serviceId: checkedServiceId, modelId: checkedModelId, workerId: requestedWorkerId });
      const contextPack = await this.contextCompiler.compile({ task, librarian, explicitRefs: input.explicitRefs || [], experienceRefs, requestReserveTokens, signal: abort.signal });
      assertPersonalContextDispatchUnavailable(contextPack);
      this.lastContext.set(task.taskId, contextPack);
      this.eventBus.emit('context.compiled', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'succeeded', summary: `${contextPack.selectedCount}/${contextPack.consideredCount} refs Â· ${contextPack.suppliedTokens}/${contextPack.budgetTokens} tokens`, payload: { contextId: contextPack.contextId, consideredCount: contextPack.consideredCount, selectedCount: contextPack.selectedCount, suppliedTokens: contextPack.suppliedTokens, budgetTokens: contextPack.budgetTokens, refs: contextPack.refs.map(r => ({ refId: r.refId, kind: r.kind, label: r.label, source: r.source, tokenEstimate: r.tokenEstimate, authority: r.authority, freshAt: r.freshAt, sha256: r.sha256 })) } });

      const attempted = []; let result; let route;
      const automaticModel = (!input.workerId || input.workerId === 'auto') && (!input.modelId || input.modelId === 'auto');
      const attemptLimit = Math.min(12, Math.max(1, workers.length));
      for (let attempt = 0; attempt < attemptLimit; attempt++) {
        if (abort.signal.aborted) throw Object.assign(new Error('turn-aborted'), { name: 'AbortError' });
        route = chooseWorker(this.workerRegistry, { task, contextTokens: contextPack.suppliedTokens + requestReserveTokens, budgetLedger: this.budgetLedger, requiredToolUse: input.requiredToolUse === true, requestedWorkerId, requestedServiceId: checkedServiceId || 'auto', requestedModelId: checkedModelId || 'auto', excludeWorkerIds: attempted, projectedChargeUsd: input.projectedChargeUsd || {}, failureCounts: input.failureCounts || {} }); this.lastRoute.set(task.taskId, route);
        this.eventBus.emit('worker.route.evaluated', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: route.selected ? 'succeeded' : 'blocked', summary: route.reason, payload: { selectedWorkerId: route.selected?.workerId || null, evaluated: route.evaluated.map(r => ({ workerId: r.workerId, displayName: r.worker.displayName, admitted: r.admitted, reasons: r.reasons, score: r.score, costClass: r.worker.costClass })) } });
        if (!route.selected) { this.taskStore.updateRun(run.runId, { status: 'blocked', lastError: route.reason }); await this.taskStore.flush(); return { task, run: this.taskStore.requireRun(run.runId), blocked: true, reason: route.reason }; }
        run = this.taskStore.selectWorker(run.runId, route.selected.workerId, route.reason); this.active.get(run.runId).workerId = route.selected.workerId;
        this.eventBus.emit('worker.selected', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'succeeded', summary: route.selected.displayName, payload: { providerId: route.selected.providerId, modelId: route.selected.modelId, costClass: route.selected.costClass } });
        const adapter = this.workerRegistry.adapter(route.selected.workerId); if (!adapter) throw new Error('selected-worker-adapter-missing');
        await this.taskStore.flush();
        if (abort.signal.aborted) throw Object.assign(new Error('turn-aborted'), { name: 'AbortError' });
        const executionContext = createExecutionContext({ run, projectId: this.projectId || 'workspace', sessionId: run.runId, providerId: route.selected.providerId,
          authoritySha256: sha256(task.constraints), effectBudgetSha256: sha256({ maxEffectClass: task.constraints.maxEffectClass }), deadlineMs: task.deadlineMs || 300000 });
        await this._reserveUsage(route.selected, task, run, executionContext, input.projectedChargeUsd?.[route.selected.workerId] ?? null);
        this.eventBus.setExecutionContext(run.runId, executionContext);
        if (abort.signal.aborted) throw Object.assign(new Error('turn-aborted'), { name: 'AbortError' });
        this.eventBus.emit('worker.started', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'started', summary: route.selected.displayName });
        let executionStarted = route.selected.supportedEffectClass !== 'READ_ONLY';
        let attemptActive = true;
        const onEvent = event => {
          if (!attemptActive || abort.signal.aborted) return;
          if (event.type === 'worker.stream.delta' || event.type.startsWith('tool.') || event.type.startsWith('effect.') || event.type === 'worker.execution.started') executionStarted = true;
          return this.eventBus.emit(event.type, { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: event.status || 'info', summary: event.summary || '', payload: event.payload || {} });
        };
        try {
          const toolBroker = this.toolBroker ? new Proxy(this.toolBroker, { get: (target, name) => {
            if (name === 'execute') return (...args) => {
              if (!attemptActive) throw new Error('worker-attempt-closed');
              if (abort.signal.aborted) throw Object.assign(new Error('turn-aborted'), { name: 'AbortError' });
              executionStarted = true; return target.execute(args[0], args[1], executionContext);
            };
            const value = Reflect.get(target, name); return typeof value === 'function' ? value.bind(target) : value;
          } }) : null;
          assertPersonalContextDispatchUnavailable(contextPack);
          this.taskStore.assertCurrent?.();
          result = await adapter.runTurn({ task, run, message: String(input.message || ''), contextPack, executionContext,
            maxOutputTokens: providerOutputLimitForInvocation(route.selected), signal: abort.signal, onEvent, toolBroker });
          await this._recordUsage(route.selected, task, run, executionContext, result);
          if (abort.signal.aborted) throw Object.assign(new Error('turn-aborted'), { name: 'AbortError' });
          if (result?.providerStatus && result.providerStatus !== 'completed') throw new Error(`provider-turn-${result.providerStatus}`);
        } catch (error) {
          if (!automaticModel || executionStarted || abort.signal.aborted || !isCapacityError(error) || attempt + 1 >= attemptLimit) throw error;
          attempted.push(route.selected.workerId);
          run = this.taskStore.updateRun(run.runId, { providerSessionRef: null });
          this.eventBus.emit('route.changed', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'info', summary: 'Provider capacity exhausted; selecting another admitted model.', payload: { errorCode: error.code || 'http-429', attemptedWorkerIds: [...attempted], serviceId: checkedServiceId || 'auto' } });
          continue;
        } finally { attemptActive = false; }
        break;
      }
      if (result?.sessionRef) this.taskStore.updateRun(run.runId, { providerSessionRef: String(result.sessionRef) });
      this.eventBus.emit('worker.completed', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'succeeded', summary: 'Worker turn completed.', payload: { text: String(result?.text || '').slice(0, 120000) } });
      run = this.taskStore.updateRun(run.runId, { status: 'complete', round: run.round + 1 });
      await this.taskStore.flush();
      const verdict = evaluateCompletion(this.taskStore.requireTask(task.taskId), this.evidence.get(task.taskId) || [], run);
      this.eventBus.emit('verification.completed', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: verdict.complete ? 'succeeded' : 'info', summary: verdict.complete ? 'Completion contract satisfied.' : 'Worker turn finished; completion contract still has open requirements.', payload: verdict });
      return { task: this.taskStore.requireTask(task.taskId), run, text: result?.text || '', conclusionSha256: sha256(String(result?.text || '')), librarian, contextPack, route, verdict };
    } catch (error) {
      const aborted = error?.name === 'AbortError' || abort.signal.aborted;
      try {
        const current = this.taskStore.requireRun(run.runId);
        if (!['complete', 'failed', 'cancelled'].includes(current.status)) {
          run = this.taskStore.updateRun(run.runId, { status: aborted ? 'cancelled' : 'failed', lastError: String(error?.message || error).slice(0, 1000) });
          await this.taskStore.flush();
        }
      } catch (persistenceError) {
        this.eventBus.emit('run.persistence.failed', { taskId: task.taskId, runId: run.runId, status: 'failed', summary: String(persistenceError?.message || persistenceError).slice(0, 1000) });
      }
      this.eventBus.emit(aborted ? 'run.cancelled' : 'run.failed', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: this.active.get(run.runId)?.workerId || null, status: aborted ? 'cancelled' : 'failed', summary: run.lastError || 'run failed' });
      throw error;
    } finally { this.eventBus.clearExecutionContext(run.runId); this.active.delete(run.runId); }
  }

  async _reserveUsage(worker, task, run, context, estimate) {
    this.budgetLedger.reserve({ worker, task, runId: run.runId, executionId: context.execution_id, projectedChargeUsd: estimate });
    await this.budgetLedger.flush();
  }

  async _recordUsage(worker, task, run, context, result) {
    if (worker.costClass === 'billable-api' && result?.usage) {
      const native = verifiedReceipt(result.exactReceipt, worker, { task, executionContext: context });
      if (result.settlementId !== native.budget_receipt_sha256) throw new Error('usage-settlement-owner-mismatch');
      const actual = ['actual', 'local_non_billable'].includes(native.billing_state) ? native.charge_microunits / 1e6 : null;
      if (result.usage.actualChargeUsd !== actual) throw new Error('usage-settlement-amount-mismatch');
    }
    if (!result?.usage) return;
    this.budgetLedger.record({ taskId: task.taskId, runId: run.runId, executionId: context.execution_id,
      settlementId: result.settlementId ?? null, workerId: worker.workerId, providerId: worker.providerId, costClass: worker.costClass,
      inputTokens: result.usage.inputTokens ?? null, outputTokens: result.usage.outputTokens ?? null, totalTokens: result.usage.totalTokens ?? null,
      actualChargeUsd: result.usage.actualChargeUsd ?? null, projectedChargeUsd: result.usage.projectedChargeUsd ?? null,
      billingIdentityKnown: result.usage.billingIdentityKnown === true, quotaRemaining: result.usage.quotaRemaining ?? null });
    await this.budgetLedger.flush();
  }

  async _runMeshBranch({ task, run, meshId, branchIndex, branchRequest, contextPack, requestReserveTokens, message }) {
    const branchId = `${meshId}:branch-${branchIndex}`;
    const generationId = newId('gen');
    const controller = this.active.get(run.runId).controllers.get(branchIndex);
    const attempted = [];
    const automaticModel = (!branchRequest.workerId || branchRequest.workerId === 'auto')
      && (!branchRequest.modelId || branchRequest.modelId === 'auto');
    const attemptLimit = Math.min(12, Math.max(1, this.workerRegistry.list().length));
    try {
      let route = null;
      for (let attempt = 0; attempt < attemptLimit; attempt += 1) {
        if (controller.signal.aborted) throw Object.assign(new Error('branch-aborted'), { name: 'AbortError' });
        route = chooseWorker(this.workerRegistry, { task, contextTokens: contextPack.suppliedTokens + requestReserveTokens, budgetLedger: this.budgetLedger,
          requiredToolUse: false, requestedWorkerId: branchRequest.workerId || 'auto', requestedServiceId: branchRequest.serviceId || 'auto',
          requestedModelId: branchRequest.modelId || 'auto', excludeWorkerIds: attempted, projectedChargeUsd: {}, failureCounts: {} });
        if (!route.selected) throw new Error('mesh-branch-no-admitted-worker');
        if (route.selected.supportedEffectClass !== 'READ_ONLY') throw new Error('mesh-read-only-worker-required');
        this.active.get(run.runId)?.branchWorkerIds?.set(branchIndex, route.selected.workerId);
        const adapter = this.workerRegistry.adapter(route.selected.workerId);
        if (!adapter) throw new Error('mesh-branch-adapter-missing');
        const executionContext = createExecutionContext({ run, projectId: this.projectId || 'workspace', sessionId: `${run.runId}:${branchId}`,
          providerId: route.selected.providerId, authoritySha256: sha256(task.constraints),
          effectBudgetSha256: sha256({ maxEffectClass: task.constraints.maxEffectClass }), deadlineMs: task.deadlineMs || 300000 });
        await this._reserveUsage(route.selected, task, run, executionContext, null);
        this.eventBus.setExecutionContext(run.runId, executionContext, { branchId });
        let executionStarted = false;
        let attemptActive = true;
        try {
          assertPersonalContextDispatchUnavailable(contextPack);
          this.taskStore.assertCurrent?.();
          const result = await adapter.runTurn({ task, run, message, contextPack, executionContext,
            maxOutputTokens: providerOutputTokenLimit(route.selected), signal: controller.signal,
            onEvent: ev => {
              if (!attemptActive || controller.signal.aborted) return;
              if (ev.type === 'worker.stream.delta' || ev.type.startsWith('tool.') || ev.type.startsWith('effect.') || ev.type === 'worker.execution.started') executionStarted = true;
              this.eventBus.emit(ev.type, { taskId: task.taskId, runId: run.runId, branchId, generationId, workerId: route.selected.workerId, status: ev.status || 'info', summary: ev.summary || '', payload: ev.payload || {} });
            }, toolBroker: null });
          await this._recordUsage(route.selected, task, run, executionContext, result);
          if (controller.signal.aborted) throw Object.assign(new Error('branch-aborted'), { name: 'AbortError' });
          if (result?.providerStatus && result.providerStatus !== 'completed') throw new Error(`provider-turn-${result.providerStatus}`);
          const text = String(result?.text || '');
          return { branchId, branchIndex, generationId, workerId: route.selected.workerId, state: 'completed', conclusion: text, conclusionSha256: sha256(text), text };
        } catch (error) {
          if (!automaticModel || executionStarted || controller.signal.aborted || !isCapacityError(error) || attempt + 1 >= attemptLimit) throw error;
          attempted.push(route.selected.workerId);
        } finally { attemptActive = false; this.eventBus.clearExecutionContext(run.runId, { branchId }); }
      }
      throw new Error('mesh-branch-attempt-limit');
    } catch (error) {
      const cancelled = controller.signal.aborted || error?.name === 'AbortError';
      return { branchId, branchIndex, generationId, workerId: null, state: cancelled ? 'cancelled' : 'failed', conclusion: '', conclusionSha256: null, failure: String(error?.message || error).slice(0, 500) };
    } finally { this.eventBus.clearExecutionContext(run.runId, { branchId }); }
  }

  async sendMeshTurn(input) {
    this._prepareTaskState();
    await this.refreshWorkers?.();
    this.taskStore.assertCurrent?.();
    const branchRequests = Array.isArray(input.branches) ? input.branches : [];
    if (branchRequests.length < 1 || branchRequests.length > 12) throw new Error('mesh-requires-1..12-branches');
    const task = input.taskId ? this.taskStore.requireTask(input.taskId) : this.createTask(input);
    if ([...this.active.values()].some(value => value.taskId === task.taskId)) throw new Error('task-already-executing');
    if (this.taskStore.requiresTaskRecovery(task.taskId)) throw new Error('task-recovery-required');
    if (EFFECT_ORDER.indexOf(task.constraints.maxEffectClass) !== 0) throw new Error('mesh-read-only-task-required');
    let run = input.runId ? this.taskStore.requireRun(input.runId) : this.taskStore.createRun(task.taskId, { dispatchMode: 'mesh' });
    if (run.taskId !== task.taskId) throw new Error('run-task-owner-mismatch');
    if (this.taskStore.requiresRecovery(run.runId)) throw new Error('run-recovery-required');
    if (run.dispatchMode !== 'mesh') throw new Error('run-dispatch-mode-mismatch');
    if (this.active.has(run.runId)) throw new Error('run-already-executing');
    if (['complete', 'failed', 'cancelled'].includes(run.status)) throw new Error('terminal-run-requires-new-run');
    if (run.status === 'waiting') {
      if (input.resume !== true) throw new Error('run-explicit-resume-required');
      run = this.taskStore.updateRun(run.runId, { status: 'running' });
    }
    const meshId = newId('mesh'); const controllers = new Map();
    for (let i = 0; i < branchRequests.length; i++) controllers.set(i, new AbortController());
    this.active.set(run.runId, { mesh: true, controllers, branchWorkerIds: new Map(), taskId: task.taskId });
    this.eventBus.emit('mesh.started', { taskId: task.taskId, runId: run.runId, status: 'started', summary: `N-way mesh with ${branchRequests.length} branches`, payload: { meshId, branchCount: branchRequests.length } });
    try {
      await this.taskStore.flush();
      const librarian = await this.tinyLibrarian.classify(task, input.message);
      const experienceRefs = typeof this.tinyLibrarian.recall === 'function' ? await this.tinyLibrarian.recall(task) : [];
      const workers = this.workerRegistry.list();
      const eligibleWorkers = workers.filter(worker => branchRequests.some(selection => selectionAllowsWorker(worker, selection)));
      const requestReserveTokens = providerRequestReserveTokens(input.message, eligibleWorkers);
      const contextPack = await this.contextCompiler.compile({ task, librarian, explicitRefs: input.explicitRefs || [], experienceRefs, requestReserveTokens, signal: controllers.get(0).signal });
      assertPersonalContextDispatchUnavailable(contextPack);
      run = this.taskStore.beginMeshDispatch(run.runId);
      await this.taskStore.flush();
      const branchResults = await Promise.all(branchRequests.map((branchRequest, index) => this._runMeshBranch({ task, run, meshId, branchIndex: index, branchRequest, contextPack, requestReserveTokens, message: String(input.message || '') })));
      run = this.taskStore.settleMeshDispatch(run.runId);
      const completed = branchResults.filter(b => b.state === 'completed'); const failed = branchResults.filter(b => b.state === 'failed'); const cancelled = branchResults.filter(b => b.state === 'cancelled');
      const conclusions = new Map();
      for (const branch of completed) { const key = String(branch.conclusion || ''); if (!conclusions.has(key)) conclusions.set(key, []); conclusions.get(key).push(branch.branchId); }
      let leading = null, leadingSupport = 0;
      for (const [conclusion, ids] of conclusions) if (ids.length > leadingSupport) { leading = conclusion; leadingSupport = ids.length; }
      const cancellationRequested = this.taskStore.requireRun(run.runId).status === 'cancelled';
      // A mesh completes only when every requested branch succeeds. Partial
      // answers remain visible, but cannot settle the run as successful.
      const quorumMet = completed.length === branchResults.length;
      const outcome = cancellationRequested || cancelled.length === branchResults.length ? 'cancelled'
        : quorumMet ? 'complete' : completed.length ? 'partial' : 'failed';
      const wholeMeshSupport = leadingSupport / branchResults.length;
      const convergence = { schemaVersion: 'px.js-mesh-convergence/1.0', meshId, branchCount: branchResults.length, completedCount: completed.length, failedCount: failed.length, cancelledCount: cancelled.length, conclusion: leading, supportCount: leadingSupport, supportRatio: wholeMeshSupport, wholeMeshSupport, agreementAmongCompleted: completed.length ? leadingSupport / completed.length : 0, minimumSuccessfulBranches: branchResults.length, quorumMet, outcome, branches: branchResults.map(b => ({ branchId: b.branchId, index: b.branchIndex, workerId: b.workerId, state: b.state, conclusionSha256: b.conclusionSha256 })), authorityGranted: false };
      this.eventBus.emit(outcome === 'complete' ? 'mesh.completed' : outcome === 'cancelled' ? 'mesh.cancelled' : 'mesh.failed', { taskId: task.taskId, runId: run.runId, status: outcome === 'complete' ? 'succeeded' : outcome === 'cancelled' ? 'cancelled' : 'failed', summary: `${outcome}: ${completed.length}/${branchResults.length} branches completed`, payload: convergence });
      run = cancellationRequested ? this.taskStore.requireRun(run.runId) : this.taskStore.updateRun(run.runId, { status: outcome === 'complete' ? 'complete' : outcome === 'cancelled' ? 'cancelled' : 'failed', round: run.round + 1 });
      await this.taskStore.flush();
      return { task: this.taskStore.requireTask(task.taskId), run, meshId, branchResults, convergence, librarian, contextPack };
    } catch (error) {
      const aborted = error?.name === 'AbortError' || [...controllers.values()].some(controller => controller.signal.aborted);
      try { run = this.taskStore.requireRun(run.runId); if (!['complete','failed','cancelled'].includes(run.status)) run = this.taskStore.updateRun(run.runId,{status:aborted?'cancelled':'failed',lastError:String(error?.message||error).slice(0,1000)}); await this.taskStore.flush(); } catch {}
      this.eventBus.emit(aborted ? 'mesh.cancelled' : 'mesh.failed', { taskId: task.taskId, runId: run.runId, status: aborted ? 'cancelled' : 'failed', summary: String(error?.message || error).slice(0,1000) }); throw error;
    } finally { this.active.delete(run.runId); }
  }

  async cancelRun(runId) {
    const active = this.active.get(runId); if (!active) return false;
    if (active.mesh) {
      const current = this.taskStore.requireRun(runId); if (['complete','failed','cancelled'].includes(current.status)) return false;
      this.taskStore.updateRun(runId, { status: 'cancelled', lastError: 'Cancellation requested by operator.' });
      for (const controller of active.controllers.values()) controller.abort(); await this.taskStore.flush();
      const workerIds = new Set(active.branchWorkerIds.values());
      const requested = this.cancelInterruptTimeoutMs ?? 1000;
      const timeout = Number.isSafeInteger(requested) && requested >= 10 && requested <= 10000 ? requested : 1000;
      await Promise.all([...workerIds].map(async workerId => {
        const adapter = this.workerRegistry.adapter(workerId);
        let timer;
        try {
          const outcome = await Promise.race([
            Promise.resolve().then(() => typeof adapter?.interrupt === 'function' ? adapter.interrupt() : false)
              .then(value => value === false ? 'unsupported' : 'acknowledged', () => 'failed'),
            new Promise(resolve => { timer = setTimeout(() => resolve('timeout'), timeout); })
          ]);
          if (outcome !== 'acknowledged') this.eventBus.emit('worker.interrupt.unsettled', {
            taskId: active.taskId, runId, workerId, status: 'blocked',
            summary: 'Cancellation requested; adapter closure remains unverified.', payload: { outcome, timeoutMs: timeout }
          });
        } finally { clearTimeout(timer); }
      }));
      return true;
    }
    active.abort.abort();
    const adapter = active.workerId ? this.workerRegistry.adapter(active.workerId) : null;
    const requested = this.cancelInterruptTimeoutMs ?? 1000;
    const timeout = Number.isSafeInteger(requested) && requested >= 10 && requested <= 10000 ? requested : 1000;
    let timer;
    try {
      const outcome = await Promise.race([
        Promise.resolve().then(() => adapter?.interrupt?.()).then(value => value === false ? 'unsupported' : 'acknowledged', () => 'failed'),
        new Promise(resolve => { timer = setTimeout(() => resolve('timeout'), timeout); })
      ]);
      if (outcome !== 'acknowledged') this.eventBus.emit('worker.interrupt.unsettled', { taskId: active.taskId, runId, workerId: active.workerId, status: 'blocked', summary: 'Cancellation requested; adapter closure remains unverified.', payload: { outcome, timeoutMs: timeout } });
      return true;
    } finally { clearTimeout(timer); }
  }

  project(taskId = null) {
    const tasks = taskId ? [this.taskStore.requireTask(taskId)] : this.taskStore.listTasks(); const activeTask = tasks.at(-1) || null;
    const runs = activeTask ? this.taskStore.listRuns(activeTask.taskId) : []; const run = runs.at(-1) || null;
    return { schemaVersion: 'px.agent-console-state/1.0', activeTask, activeRun: run, workers: this.workerRegistry.list().map(w => ({ ...w, health: this.workerRegistry.getHealth(w.workerId) })),
      librarian: activeTask ? this.lastLibrarian.get(activeTask.taskId) || null : null, context: activeTask ? this.lastContext.get(activeTask.taskId) || null : null, route: activeTask ? this.lastRoute.get(activeTask.taskId) || null : null, budget: this.budgetLedger.summary(), evidence: activeTask ? this.evidence.get(activeTask.taskId) || [] : [], events: activeTask ? this.eventBus.snapshot({ taskId: activeTask.taskId, limit: 240 }) : this.eventBus.snapshot({ limit: 120 }) };
  }

  dispose() { for (const active of this.active.values()) { active.abort?.abort(); for (const controller of active.controllers?.values() || []) controller.abort(); } this.active.clear(); this.eventBus.dispose(); }
}

module.exports = { HarnessController, providerOutputTokenLimit, providerRequestReserveTokens, selectionAllowsWorker, assertPersonalContextDispatchUnavailable };
