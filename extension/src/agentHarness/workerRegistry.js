'use strict';

const { WorkerDescriptor, parse } = require('./contracts');

class WorkerRegistry {
  constructor() { this.workers = new Map(); this.adapters = new Map(); this.health = new Map(); }

  register(descriptor, adapter) {
    const worker = parse(WorkerDescriptor, descriptor, 'worker-descriptor');
    if (!adapter || typeof adapter.runTurn !== 'function') throw new Error('worker-adapter-invalid');
    this.workers.set(worker.workerId, worker); this.adapters.set(worker.workerId, adapter);
    return { dispose: () => { this.workers.delete(worker.workerId); this.adapters.delete(worker.workerId); this.health.delete(worker.workerId); } };
  }

  list() { return [...this.workers.values()]; }
  get(workerId) { return this.workers.get(workerId) || null; }
  adapter(workerId) { return this.adapters.get(workerId) || null; }
  setHealth(workerId, health) { if (this.workers.has(workerId)) this.health.set(workerId, { ...health, capturedAt: new Date().toISOString() }); }
  getHealth(workerId) { return this.health.get(workerId) || { status: 'unknown', capturedAt: null }; }
  async refreshHealth() {
    const results = [];
    for (const worker of this.list()) {
      try { const value = await this.adapter(worker.workerId).health?.(); const h = value || { status: 'healthy' }; this.setHealth(worker.workerId, h); results.push({ workerId: worker.workerId, ...h }); }
      catch (error) { const h = { status: 'unavailable', detail: String(error?.message || error).slice(0, 500) }; this.setHealth(worker.workerId, h); results.push({ workerId: worker.workerId, ...h }); }
    }
    return results;
  }
}

module.exports = { WorkerRegistry };
