'use strict';

const { EventEmitter } = require('node:events');
const { newId, nowIso } = require('./ids');
const { PxEvent, parse } = require('./contracts');
const { validateExecutionContextForRun } = require('./executionContext');

class CanonicalEventBus {
  constructor(options = {}) {
    this.maxEvents = Math.max(50, Math.min(5000, Number(options.maxEvents || 800)));
    this.events = [];
    this.sequence = 0;
    this.executionContexts = new Map();
    this.emitter = new EventEmitter();
    this.emitter.setMaxListeners(100);
  }

  emit(type, input = {}) {
    const context = this.executionContexts.get(input.branchId ? `${input.runId}\0${input.branchId}` : input.runId);
    const event = parse(PxEvent, {
      schemaVersion: 'px.agent-event/1.0',
      eventId: newId('evt'), sequence: this.sequence++, type,
      emittedAt: nowIso(), taskId: input.taskId || null, runId: input.runId || null,
      turnId: input.turnId || null, roundId: input.roundId || null,
      actor: input.actor || 'px-harness', workerId: input.workerId || null,
      executionId: context?.execution_id || null, traceRootId: context?.trace_root_id || null,
      executionContextSha256: context?.context_sha256 || null,
      generationVectorSha256: context?.generation_vector_sha256 || null,
      parentEventId: input.parentEventId || null, status: input.status || 'info',
      summary: String(input.summary || '').slice(0, 1000), payload: input.payload || {}
    }, 'agent-event');
    this.events.push(event);
    if (this.events.length > this.maxEvents) this.events.splice(0, this.events.length - this.maxEvents);
    this.emitter.emit('event', event);
    return event;
  }

  subscribe(listener) { this.emitter.on('event', listener); return { dispose: () => this.emitter.off('event', listener) }; }
  setExecutionContext(runId, context, { branchId = null } = {}) {
    if (context.root_execution_id !== runId || context.cancellation_scope_id !== runId || context.authority_granted !== false) throw new Error('event-execution-context-owner-mismatch');
    validateExecutionContextForRun(context, runId);
    if (branchId !== null && (typeof branchId !== 'string' || !branchId || branchId.length > 256 || /[\x00-\x1f]/.test(branchId))) throw new Error('event-branch-owner-invalid');
    if (branchId !== null && context.session_id !== `${runId}:${branchId}`) throw new Error('event-branch-session-owner-mismatch');
    this.executionContexts.set(branchId ? `${runId}\0${branchId}` : runId, context);
  }
  clearExecutionContext(runId, { branchId = null } = {}) { this.executionContexts.delete(branchId ? `${runId}\0${branchId}` : runId); }
  snapshot(options = {}) {
    const taskId = options.taskId || null; const runId = options.runId || null;
    return this.events.filter(e => (!taskId || e.taskId === taskId) && (!runId || e.runId === runId)).slice(-(options.limit || 200));
  }
  dispose() { this.emitter.removeAllListeners(); this.events.length = 0; this.executionContexts.clear(); }
}

module.exports = { CanonicalEventBus };
