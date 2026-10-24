'use strict';

const { newId } = require('./ids');
const { chooseWorker } = require('./router');
const { evaluateCompletion } = require('./completionEvaluator');
const { isCapacityError } = require('./adapters/base');
const { createExecutionContext } = require('./executionContext');
const { sha256 } = require('./ids');

const DEFAULT_OUTPUT_TOKEN_LIMIT = 1024;
const WORKER_INTERRUPT_TIMEOUT_MS = 5000;

function providerOutputTokenLimit(worker) {
  const configured = worker.bridge?.maxOutputTokens;
  if (configured == null) return DEFAULT_OUTPUT_TOKEN_LIMIT;
  if (!Number.isSafeInteger(configured) || configured < 1) throw new Error('worker-output-token-budget-invalid');
  return configured;
}

function selectionAllowsWorker(worker, selection = {}) {
  return (!selection.serviceId || selection.serviceId === 'auto' || worker.providerId === selection.serviceId)
    && (!selection.modelId || selection.modelId === 'auto' || worker.modelId === selection.modelId)
    && (!selection.workerId || selection.workerId === 'auto' || worker.workerId === selection.workerId);
}

function providerRequestReserveTokens(message, workers, selection = {}) {
  const outputs = workers.filter(worker => worker.enabled && worker.bridge?.available !== false && selectionAllowsWorker(worker, selection))
    .map(providerOutputTokenLimit);
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
    const task = this.taskStore.createTask(input); this.eventBus.emit('task.created', { taskId: task.taskId, status: 'succeeded', summary: task.goal, payload: { mode: task.mode } }); return task;
  }

  async sendTurn(input) {
    let task = input.taskId ? this.taskStore.requireTask(input.taskId) : this.createTask(input);
    let run = input.runId ? this.taskStore.requireRun(input.runId) : this.taskStore.createRun(task.taskId);
    if (run.taskId !== task.taskId) throw new Error('run-task-owner-mismatch');
    if (this.active.has(run.runId)) throw new Error('run-already-executing');
    if (['complete', 'failed', 'cancelled'].includes(run.status)) throw new Error('terminal-run-requires-new-run');
    if (run.status === 'waiting') {
      if (input.resume !== true) throw new Error('run-explicit-resume-required');
      run = this.taskStore.updateRun(run.runId, { status: 'running' });
    }
    const turnId = newId('turn'); const roundId = newId('round'); const abort = new AbortController(); this.active.set(run.runId, { abort, workerId: null });
    this.eventBus.emit('turn.started', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'started', summary: String(input.message || '').slice(0, 500) });
    try {
      await this.taskStore.flush();
      task = this.taskStore.updateTask(task.taskId, { stage: 'CLASSIFY' });
      this.eventBus.emit('librarian.classification.started', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'started', summary: 'Classifying intent, domain, skills and retrieval need.' });
      const librarian = await this.tinyLibrarian.classify(task, input.message); this.lastLibrarian.set(task.taskId, librarian);
      task = this.taskStore.updateTask(task.taskId, { stage: librarian.stage, activeSkills: librarian.skillCandidates, confidence: librarian.confidence }, { epoch: task.epoch, revision: task.revision });
      this.eventBus.emit('librarian.classification.completed', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'succeeded', summary: `${librarian.intent} · ${librarian.domains.join(', ')}`, payload: librarian });

      const experienceRefs = typeof this.tinyLibrarian.recall === 'function' ? await this.tinyLibrarian.recall(task) : [];
      const workers = this.workerRegistry.list();
      const requestReserveTokens = providerRequestReserveTokens(input.message, workers, input);
      const contextPack = await this.contextCompiler.compile({ task, librarian, explicitRefs: input.explicitRefs || [], experienceRefs, requestReserveTokens, signal: abort.signal }); assertPersonalContextDispatchUnavailable(contextPack); this.lastContext.set(task.taskId, contextPack);
      this.eventBus.emit('context.compiled', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'succeeded', summary: `${contextPack.selectedCount}/${contextPack.consideredCount} refs · ${contextPack.suppliedTokens}/${contextPack.budgetTokens} tokens`, payload: { contextId: contextPack.contextId, consideredCount: contextPack.consideredCount, selectedCount: contextPack.selectedCount, suppliedTokens: contextPack.suppliedTokens, budgetTokens: contextPack.budgetTokens, refs: contextPack.refs.map(r => ({ refId: r.refId, kind: r.kind, label: r.label, source: r.source, tokenEstimate: r.tokenEstimate, authority: r.authority, freshAt: r.freshAt, sha256: r.sha256 })) } });

      const attempted = []; let result; let route;
      const automaticModel = (!input.workerId || input.workerId === 'auto') && (!input.modelId || input.modelId === 'auto');
      const attemptLimit = Math.min(12, Math.max(1, workers.length));
      for (let attempt = 0; attempt < attemptLimit; attempt++) {
      if (abort.signal.aborted) throw Object.assign(new Error('turn-aborted'), { name: 'AbortError' });
      route = chooseWorker(this.workerRegistry, { task, contextTokens: contextPack.suppliedTokens + requestReserveTokens, budgetLedger: this.budgetLedger, requiredToolUse: input.requiredToolUse === true, requestedWorkerId: input.workerId || 'auto', requestedServiceId: input.serviceId || 'auto', requestedModelId: input.modelId || 'auto', excludeWorkerIds: attempted, projectedChargeUsd: input.projectedChargeUsd || {}, failureCounts: input.failureCounts || {} }); this.lastRoute.set(task.taskId, route);
      this.eventBus.emit('worker.route.evaluated', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: route.selected ? 'succeeded' : 'blocked', summary: route.reason,
        payload: { selectedWorkerId: route.selected?.workerId || null, evaluated: route.evaluated.map(r => ({ workerId: r.worker.workerId, displayName: r.worker.displayName, admitted: r.admitted, reasons: r.reasons, score: r.score, costClass: r.worker.costClass })) } });
      if (!route.selected) { this.taskStore.updateRun(run.runId, { status: 'blocked', lastError: route.reason }); await this.taskStore.flush(); return { task, run: this.taskStore.requireRun(run.runId), blocked: true, reason: route.reason }; }

      run = this.taskStore.selectWorker(run.runId, route.selected.workerId, route.reason); this.active.get(run.runId).workerId = route.selected.workerId;
      this.eventBus.emit('worker.selected', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'succeeded', summary: route.selected.displayName, payload: { providerId: route.selected.providerId, modelId: route.selected.modelId, costClass: route.selected.costClass } });
      const adapter = this.workerRegistry.adapter(route.selected.workerId); if (!adapter) throw new Error('selected-worker-adapter-missing');
      await this.taskStore.flush();
      const executionContext = createExecutionContext({ run, projectId: this.projectId || 'workspace', sessionId: run.runId,
        providerId: route.selected.providerId, authoritySha256: sha256(task.constraints),
        effectBudgetSha256: sha256({ maxEffectClass: task.constraints.maxEffectClass }), deadlineMs: task.deadlineMs || 300000 });
      this.eventBus.setExecutionContext(run.runId, executionContext);
      this.eventBus.emit('worker.started', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'started', summary: route.selected.displayName });
      let executionStarted = route.selected.supportedEffectClass !== 'READ_ONLY';
      let attemptActive = true;
      const onEvent = event => {
        if (!attemptActive || abort.signal.aborted) return;
        if (event.type === 'worker.stream.delta' || event.type.startsWith('tool.') || event.type.startsWith('effect.') || event.type === 'worker.execution.started') executionStarted = true;
        return this.eventBus.emit(event.type, { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: event.status || 'info', summary: event.summary || '', payload: event.payload || {} }); };
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
      result = await adapter.runTurn({ task, run, message: String(input.message || ''), contextPack, executionContext,
        maxOutputTokens: providerOutputTokenLimit(route.selected), signal: abort.signal, onEvent, toolBroker });
      if (abort.signal.aborted) throw Object.assign(new Error('turn-aborted'), { name: 'AbortError' });
      if (result?.providerStatus && result.providerStatus !== 'completed') throw new Error(`provider-turn-${result.providerStatus}`);
      } catch (error) {
        if (!automaticModel || executionStarted || abort.signal.aborted || !isCapacityError(error) || attempt + 1 >= attemptLimit) throw error;
        attempted.push(route.selected.workerId);
        // Provider sessions belong to one worker; never resume them through another adapter.
        run = this.taskStore.updateRun(run.runId, { providerSessionRef: null });
        this.eventBus.emit('route.changed', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'info', summary: 'Provider capacity exhausted; selecting another admitted model.', payload: { errorCode: error.code || 'http-429', attemptedWorkerIds: [...attempted], serviceId: input.serviceId || 'auto' } });
        continue;
      } finally { attemptActive = false; }
      break;
      }
      if (result?.sessionRef) this.taskStore.updateRun(run.runId, { providerSessionRef: String(result.sessionRef) });
      if (result?.usage) this.budgetLedger.record({ workerId: route.selected.workerId, providerId: route.selected.providerId, costClass: route.selected.costClass,
        inputTokens: result.usage.inputTokens ?? null, outputTokens: result.usage.outputTokens ?? null, totalTokens: result.usage.totalTokens ?? null,
        actualChargeUsd: result.usage.actualChargeUsd ?? null, projectedChargeUsd: result.usage.projectedChargeUsd ?? null, billingIdentityKnown: Boolean(result.usage.billingIdentityKnown), quotaRemaining: result.usage.quotaRemaining ?? null });
      this.eventBus.emit('worker.completed', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: route.selected.workerId, status: 'succeeded', summary: 'Worker turn completed.', payload: { text: String(result?.text || '').slice(0, 120000) } });
      run = this.taskStore.updateRun(run.runId, { status: 'complete', round: run.round + 1 });
      await this.taskStore.flush();
      const verdict = evaluateCompletion(this.taskStore.requireTask(task.taskId), this.evidence.get(task.taskId) || []);
      if (typeof this.tinyLibrarian.observe === 'function') {
        try {
          const experience = await this.tinyLibrarian.observe(task, { runId: run.runId, workerId: route.selected.workerId, text: result?.text, verdict });
          this.eventBus.emit('librarian.experience.recorded', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'info', summary: 'PX Archivist retained task-local worker experience.', payload: { recordId: experience.recordId, validated: false, authorityGranted: false } });
        } catch (experienceError) {
          this.eventBus.emit('librarian.experience.failed', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'failed', summary: 'Worker completed; PX Archivist experience persistence failed.', payload: { reason: String(experienceError?.message || experienceError).slice(0, 1000), authorityGranted: false } });
        }
      }
      this.eventBus.emit('verification.completed', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: verdict.complete ? 'succeeded' : 'info', summary: verdict.complete ? 'Completion contract satisfied.' : 'Worker turn finished; completion contract still has open requirements.', payload: verdict });
      return { task: this.taskStore.requireTask(task.taskId), run, text: result?.text || '', librarian, contextPack, route, verdict };
    } catch (error) {
      const aborted = error?.name === 'AbortError' || abort.signal.aborted;
      try {
        run = this.taskStore.requireRun(run.runId);
        if (!['complete', 'failed', 'cancelled'].includes(run.status)) {
          run = this.taskStore.updateRun(run.runId, { status: aborted ? 'cancelled' : 'failed', lastError: String(error?.message || error).slice(0, 1000) });
        }
        await this.taskStore.flush();
      } catch (persistenceError) {
        this.eventBus.emit('run.persistence.failed', { taskId: task.taskId, runId: run.runId, turnId, roundId, status: 'failed', summary: String(persistenceError?.message || persistenceError).slice(0, 1000) });
      }
      this.eventBus.emit(aborted ? 'run.cancelled' : 'run.failed', { taskId: task.taskId, runId: run.runId, turnId, roundId, workerId: this.active.get(run.runId)?.workerId || null, status: aborted ? 'cancelled' : 'failed', summary: run.lastError || 'run failed' });
      throw error;
    } finally { this.active.delete(run.runId); this.eventBus.clearExecutionContext(run.runId); }
  }

  // N-way local mesh. Runs independent read-only branches and returns a
  // non-authoritative convergence projection; Python owns canonical group runs.
  // This is deliberately separate from sendTurn: a mesh turn is not a single
  // worker turn, and it must not inherit the single-worker route assumption.
  //
  // Requirements honoured per branch:
  //  - unique generation/session identity
  //  - exact ExecutionContext (per-branch provider identity)
  //  - independent cancellation (one abort controller per branch)
  //  - a branch may converge, fail, be cancelled, or be replaced independently
  // Convergence consumes branch results WITHOUT assuming a fixed branch count or
  // any primary/challenger positional slot.
  async sendMeshTurn(input) {
    const branchRequests = Array.isArray(input.branches) ? input.branches : [];
    if (branchRequests.length < 1 || branchRequests.length > 12) throw new Error('mesh-requires-1..12-branches');
    const task = input.taskId ? this.taskStore.requireTask(input.taskId) : this.createTask(input);
    if (task.constraints.maxEffectClass !== 'READ_ONLY') throw new Error('mesh-read-only-task-required');
    let run = input.runId ? this.taskStore.requireRun(input.runId) : this.taskStore.createRun(task.taskId);
    if (run.taskId !== task.taskId) throw new Error('run-task-owner-mismatch');
    if (this.active.has(run.runId)) throw new Error('run-already-executing');
    if (['complete', 'failed', 'cancelled'].includes(run.status)) throw new Error('terminal-run-requires-new-run');
    const meshId = newId('mesh');
    const controllers = new Map();
    for (let i = 0; i < branchRequests.length; i++) controllers.set(i, new AbortController());
    this.active.set(run.runId, { mesh: true, controllers, branchWorkerIds: new Map() });
    this.eventBus.emit('mesh.started', { taskId: task.taskId, runId: run.runId, status: 'started', summary: `N-way mesh with ${branchRequests.length} branches`, payload: { meshId, branchCount: branchRequests.length } });
    try {
      await this.taskStore.flush();
      const librarian = await this.tinyLibrarian.classify(task, input.message);
      const experienceRefs = typeof this.tinyLibrarian.recall === 'function' ? await this.tinyLibrarian.recall(task) : [];
      const requestReserveTokens = providerRequestReserveTokens(input.message, this.workerRegistry.list().filter(worker =>
        branchRequests.some(selection => selectionAllowsWorker(worker, selection))));
      const contextPack = await this.contextCompiler.compile({ task, librarian, explicitRefs: input.explicitRefs || [], experienceRefs, requestReserveTokens, signal: controllers.get(0).signal });

      const branchResults = await Promise.all(branchRequests.map((branchRequest, index) => this._runMeshBranch({
        task, run, meshId, branchIndex: index, branchRequest, contextPack,
        requestReserveTokens, message: String(input.message || '')
      })));

      // Convergence consumes every branch result without positional assumptions.
      const completed = branchResults.filter(b => b.state === 'completed');
      const failed = branchResults.filter(b => b.state === 'failed');
      const cancelled = branchResults.filter(b => b.state === 'cancelled');
      const conclusions = new Map();
      for (const branch of completed) {
        const key = String(branch.conclusion || '');
        if (!conclusions.has(key)) conclusions.set(key, []);
        conclusions.get(key).push(branch.branchId);
      }
      let leading = null, leadingSupport = 0;
      for (const [conclusion, ids] of conclusions) {
        if (ids.length > leadingSupport) { leading = conclusion; leadingSupport = ids.length; }
      }
      const convergence = {
        schemaVersion: 'px.js-mesh-convergence/1.0',
        meshId, branchCount: branchResults.length,
        completedCount: completed.length, failedCount: failed.length, cancelledCount: cancelled.length,
        conclusion: leading, supportCount: leadingSupport,
        supportRatio: completed.length ? leadingSupport / completed.length : 0,
        branches: branchResults.map(b => ({ branchId: b.branchId, index: b.branchIndex, workerId: b.workerId, state: b.state, conclusionSha256: b.conclusionSha256 })),
        authorityGranted: false
      };
      const cancellationRequested = this.taskStore.requireRun(run.runId).status === 'cancelled';
      this.eventBus.emit(cancellationRequested ? 'mesh.cancelled' : 'mesh.completed', {
        taskId: task.taskId, runId: run.runId,
        status: cancellationRequested ? 'cancelled' : failed.length === 0 && cancelled.length === 0 ? 'succeeded' : 'info',
        summary: `${completed.length}/${branchResults.length} branches completed`,
        payload: convergence
      });
      run = cancellationRequested
        ? this.taskStore.requireRun(run.runId)
        : this.taskStore.updateRun(run.runId, { status: 'complete', round: run.round + 1 });
      await this.taskStore.flush();
      return { task: this.taskStore.requireTask(task.taskId), run, meshId, branchResults, convergence, librarian, contextPack };
    } catch (error) {
      const aborted = error?.name === 'AbortError' || [...controllers.values()].some(controller => controller.signal.aborted);
      try {
        run = this.taskStore.requireRun(run.runId);
        if (!['complete', 'failed', 'cancelled'].includes(run.status)) {
          run = this.taskStore.updateRun(run.runId, { status: aborted ? 'cancelled' : 'failed', lastError: String(error?.message || error).slice(0, 1000) });
        }
        await this.taskStore.flush();
      } catch { /* persistence failure must not mask the mesh error */ }
      this.eventBus.emit(aborted ? 'mesh.cancelled' : 'mesh.failed', {
        taskId: task.taskId, runId: run.runId,
        status: aborted ? 'cancelled' : 'failed',
        summary: String(error?.message || error).slice(0, 1000)
      });
      throw error;
    } finally { this.active.delete(run.runId); }
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
      for (let attempt = 0; attempt < attemptLimit; attempt++) {
        if (controller.signal.aborted) throw Object.assign(new Error('branch-aborted'), { name: 'AbortError' });
        route = chooseWorker(this.workerRegistry, { task, contextTokens: contextPack.suppliedTokens + requestReserveTokens, budgetLedger: this.budgetLedger,
          requiredToolUse: false, requestedWorkerId: branchRequest.workerId || 'auto', requestedServiceId: branchRequest.serviceId || 'auto',
          requestedModelId: branchRequest.modelId || 'auto', excludeWorkerIds: attempted, projectedChargeUsd: {}, failureCounts: {} });
        if (!route.selected) throw new Error('mesh-branch-no-admitted-worker');
        if (route.selected.supportedEffectClass !== 'READ_ONLY') throw new Error('mesh-read-only-worker-required');
        this.active.get(run.runId)?.branchWorkerIds?.set(branchIndex, route.selected.workerId);
        const adapter = this.workerRegistry.adapter(route.selected.workerId);
        if (!adapter) throw new Error('mesh-branch-adapter-missing');
        const executionContext = createExecutionContext({ run, projectId: this.projectId || 'workspace', sessionId: `${run.runId}:${branchId}`, generationId,
          providerId: route.selected.providerId, authoritySha256: sha256(task.constraints),
          effectBudgetSha256: sha256({ maxEffectClass: task.constraints.maxEffectClass }), deadlineMs: task.deadlineMs || 300000 });
        this.eventBus.setExecutionContext(run.runId, executionContext, { branchId });
        let executionStarted = false;
        let attemptActive = true;
        try {
          assertPersonalContextDispatchUnavailable(contextPack);
          const result = await adapter.runTurn({ task, run, message, contextPack, executionContext,
            maxOutputTokens: providerOutputTokenLimit(route.selected), signal: controller.signal,
            onEvent: ev => {
              if (!attemptActive || controller.signal.aborted) return;
              if (ev.type === 'worker.stream.delta' || ev.type.startsWith('tool.') || ev.type.startsWith('effect.') || ev.type === 'worker.execution.started') executionStarted = true;
              this.eventBus.emit(ev.type, { taskId: task.taskId, runId: run.runId, branchId, generationId, workerId: route.selected.workerId, status: ev.status || 'info', summary: ev.summary || '', payload: ev.payload || {} });
            }, toolBroker: null });
          if (controller.signal.aborted) throw Object.assign(new Error('branch-aborted'), { name: 'AbortError' });
          if (result?.providerStatus && result.providerStatus !== 'completed') throw new Error(`provider-turn-${result.providerStatus}`);
          const text = String(result?.text || '');
          return { branchId, branchIndex, generationId, workerId: route.selected.workerId, state: 'completed', conclusion: text, conclusionSha256: sha256(text.slice(0, 4096)), text };
        } catch (error) {
          if (!automaticModel || executionStarted || controller.signal.aborted || !isCapacityError(error) || attempt + 1 >= attemptLimit) throw error;
          attempted.push(route.selected.workerId);
          continue;
        } finally { attemptActive = false; }
      }
      throw new Error('mesh-branch-attempt-limit');
    } catch (error) {
      const cancelled = controller.signal.aborted || error?.name === 'AbortError';
      return { branchId, branchIndex, generationId, workerId: null, state: cancelled ? 'cancelled' : 'failed', conclusion: '', conclusionSha256: null, failure: String(error?.message || error).slice(0, 500) };
    } finally { this.eventBus.clearExecutionContext(run.runId, { branchId }); }
  }

  async cancelRun(runId) {
    const active = this.active.get(runId); if (!active) return false;
    if (['complete', 'failed', 'cancelled'].includes(this.taskStore.requireRun(runId).status)) return false;
    const cancelledRun = this.taskStore.updateRun(runId, { status: 'cancelled', lastError: 'Cancellation requested by operator.' });
    active.abort?.abort();
    for (const controller of active.controllers?.values() || []) controller.abort();
    await this.taskStore.flush();
    const workerIds = new Set([
      ...(active.workerId ? [active.workerId] : []),
      ...(active.branchWorkerIds?.values() || [])
    ]);
    const interruptions = await Promise.all([...workerIds].map(async workerId => {
      let timer;
      const request = (async () => {
        try {
          const adapter = this.workerRegistry.adapter(workerId);
          if (!adapter || typeof adapter.interrupt !== 'function') return { workerId, status: 'unsupported' };
          return { workerId, status: await adapter.interrupt() === false ? 'unsupported' : 'confirmed' };
        } catch (error) {
          return { workerId, status: 'failed', reason: String(error?.message || error).slice(0, 300) };
        }
      })();
      const timeout = new Promise(resolve => {
        timer = setTimeout(() => resolve({
          workerId, status: 'timeout', reason: 'worker-interruption-timeout'
        }), WORKER_INTERRUPT_TIMEOUT_MS);
      });
      const outcome = await Promise.race([request, timeout]);
      clearTimeout(timer);
      return outcome;
    }));
    for (const interruption of interruptions) {
      if (interruption.status === 'confirmed') continue;
      this.eventBus.emit('worker.interrupt.result', {
        taskId: cancelledRun.taskId,
        runId,
        workerId: interruption.workerId,
        status: interruption.status === 'failed' ? 'failed' : 'info',
        summary: interruption.status === 'failed'
          ? 'Worker interruption failed after run cancellation.'
          : interruption.status === 'timeout'
            ? 'Worker interruption timed out after run cancellation.'
            : 'Worker adapter does not confirm interruption; cancellation signal was sent.',
        payload: { interruptStatus: interruption.status, reason: interruption.reason || null }
      });
    }
    return true;
  }

  project(taskId = null) {
    const tasks = taskId ? [this.taskStore.requireTask(taskId)] : this.taskStore.listTasks(); const activeTask = tasks.at(-1) || null;
    const runs = activeTask ? this.taskStore.listRuns(activeTask.taskId) : []; const run = runs.at(-1) || null;
    return { schemaVersion: 'px.agent-console-state/1.0', activeTask, activeRun: run, workers: this.workerRegistry.list().map(w => ({ ...w, health: this.workerRegistry.getHealth(w.workerId) })),
      librarian: activeTask ? this.lastLibrarian.get(activeTask.taskId) || null : null, context: activeTask ? this.lastContext.get(activeTask.taskId) || null : null,
      route: activeTask ? this.lastRoute.get(activeTask.taskId) || null : null, budget: this.budgetLedger.summary(), evidence: activeTask ? this.evidence.get(activeTask.taskId) || [] : [],
      events: activeTask ? this.eventBus.snapshot({ taskId: activeTask.taskId, limit: 240 }) : this.eventBus.snapshot({ limit: 120 }) };
  }

  dispose() {
    for (const active of this.active.values()) {
      active.abort?.abort();
      for (const controller of active.controllers?.values() || []) controller.abort();
    }
    this.active.clear();
    this.eventBus.dispose();
  }
}

module.exports = { HarnessController, assertPersonalContextDispatchUnavailable };
