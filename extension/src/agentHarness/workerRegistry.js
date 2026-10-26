'use strict';

const { WorkerDescriptor, parse } = require('./contracts');

class WorkerRegistry {
  constructor() { this.workers = new Map(); this.adapters = new Map(); this.health = new Map(); this.registrations = new Map(); }

  register(descriptor, adapter) {
    const worker = parse(WorkerDescriptor, descriptor, 'worker-descriptor');
    if (!adapter || typeof adapter.runTurn !== 'function') throw new Error('worker-adapter-invalid');
    const registration = {};
    this.registrations.set(worker.workerId, registration);
    this.workers.set(worker.workerId, worker); this.adapters.set(worker.workerId, adapter); this.health.delete(worker.workerId);
    return { dispose: () => {
      if (this.registrations.get(worker.workerId) !== registration) return;
      this.registrations.delete(worker.workerId); this.workers.delete(worker.workerId); this.adapters.delete(worker.workerId); this.health.delete(worker.workerId);
    } };
  }

  list() { return [...this.workers.values()]; }
  get(workerId) { return this.workers.get(workerId) || null; }
  adapter(workerId) { return this.adapters.get(workerId) || null; }
  setHealth(workerId, health) { if (this.workers.has(workerId)) this.health.set(workerId, { ...health, capturedAt: new Date().toISOString() }); }
  getHealth(workerId) { return this.health.get(workerId) || { status: 'unknown', capturedAt: null }; }
  async refreshHealth() {
    const results = [];
    for (const worker of this.list()) {
      const registration = this.registrations.get(worker.workerId), adapter = this.adapter(worker.workerId);
      try { const value = await adapter?.health?.(); const h = value || { status: 'unknown', detail: 'No worker health observation was supplied.' }; if (this.registrations.get(worker.workerId) !== registration) continue; this.setHealth(worker.workerId, h); results.push({ workerId: worker.workerId, ...h }); }
      catch (error) { if (this.registrations.get(worker.workerId) !== registration) continue; const h = { status: 'unavailable', detail: String(error?.message || error).slice(0, 500) }; this.setHealth(worker.workerId, h); results.push({ workerId: worker.workerId, ...h }); }
    }
    return results;
  }
}

module.exports = { WorkerRegistry };
