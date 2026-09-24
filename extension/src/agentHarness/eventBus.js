'use strict';

const { EventEmitter } = require('node:events');
const { newId, nowIso } = require('./ids');
const { PxEvent, parse } = require('./contracts');

class CanonicalEventBus {
  constructor(options = {}) {
    this.maxEvents = Math.max(50, Math.min(5000, Number(options.maxEvents || 800)));
    this.events = [];
    this.sequence = 0;
    this.emitter = new EventEmitter();
    this.emitter.setMaxListeners(100);
  }

  emit(type, input = {}) {
    const event = parse(PxEvent, {
      schemaVersion: 'px.agent-event/1.0',
      eventId: newId('evt'), sequence: this.sequence++, type,
      emittedAt: nowIso(), taskId: input.taskId || null, runId: input.runId || null,
      turnId: input.turnId || null, roundId: input.roundId || null,
      actor: input.actor || 'px-harness', workerId: input.workerId || null,
      parentEventId: input.parentEventId || null, status: input.status || 'info',
      summary: String(input.summary || '').slice(0, 1000), payload: input.payload || {}
    }, 'agent-event');
    this.events.push(event);
    if (this.events.length > this.maxEvents) this.events.splice(0, this.events.length - this.maxEvents);
    this.emitter.emit('event', event);
    return event;
  }

  subscribe(listener) { this.emitter.on('event', listener); return { dispose: () => this.emitter.off('event', listener) }; }
  snapshot(options = {}) {
    const taskId = options.taskId || null; const runId = options.runId || null;
    return this.events.filter(e => (!taskId || e.taskId === taskId) && (!runId || e.runId === runId)).slice(-(options.limit || 200));
  }
  dispose() { this.emitter.removeAllListeners(); this.events.length = 0; }
}

module.exports = { CanonicalEventBus };
