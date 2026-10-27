'use strict';

const { EFFECT_ORDER } = require('./taskStore');
const { PxToolRequest, PxToolResult, parse } = require('./contracts');
const { nowIso } = require('./ids');

class ToolBroker {
  constructor(options = {}) { this.tools = new Map(); this.taskStore = options.taskStore || null; this.approvalProvider = options.approvalProvider || null; this.eventBus = options.eventBus || null; }

  register(tool) {
    if (!tool?.toolId || !tool?.effectClass || typeof tool.execute !== 'function') throw new Error('tool-registration-invalid');
    if (this.tools.has(tool.toolId)) throw new Error(`tool-already-registered:${tool.toolId}`);
    const registration = Object.freeze({ ...tool }); this.tools.set(tool.toolId, registration); return { dispose: () => { if (this.tools.get(tool.toolId) === registration) this.tools.delete(tool.toolId); } };
  }

  list() { return [...this.tools.values()].map(({ execute, ...rest }) => rest); }

  async execute(input, task) {
    const request = immutableRequest(parse(PxToolRequest, input, 'tool-request'));
    try { await this.taskStore?.flush(); } catch { return this._result(request, 'blocked', 'Task policy persistence failed.', null, []); }
    const authority = this._authority(request, task);
    if (!authority) return this._result(request, 'blocked', 'Current task/run/worker authority is unavailable.', null, []);
    task = authority.task;
    const tool = this.tools.get(request.toolId);
    if (!tool) return this._result(request, 'blocked', 'Unknown tool.', null, []);
    if (tool.effectClass !== request.effectClass) return this._result(request, 'blocked', 'Tool effect class does not match registered authority.', null, []);
    if (EFFECT_ORDER.indexOf(request.effectClass) > EFFECT_ORDER.indexOf(task.constraints.maxEffectClass)) return this._result(request, 'blocked', 'Task stage/effect policy blocks this tool.', null, []);
    const needsApproval = tool.requireApproval === true || ['MUTATING', 'HIGH_RISK'].includes(request.effectClass);
    if (needsApproval) {
      this.eventBus?.emit('tool.approval.required', { taskId: request.taskId, runId: request.runId, workerId: request.workerId, status: 'blocked', summary: `${request.toolId} requires approval.`, payload: { requestId: request.requestId, toolId: request.toolId, effectClass: request.effectClass } });
      const approved = this.approvalProvider ? await this.approvalProvider({ request, tool, task }) : false;
      if (approved !== true) return this._result(request, 'blocked', 'User/PX approval not granted.', null, []);
    }
    try { await this.taskStore.flush(); } catch { return this._result(request, 'blocked', 'Task policy persistence failed.', null, []); }
    if (!this._authority(request, task, authority.snapshot) || this.tools.get(request.toolId) !== tool) return this._result(request, 'blocked', 'Tool authority changed before dispatch.', null, []);
    this.eventBus?.emit('tool.started', { taskId: request.taskId, runId: request.runId, workerId: request.workerId, status: 'started', summary: request.toolId, payload: { requestId: request.requestId, effectClass: request.effectClass } });
    try {
      const value = await tool.execute({ request, task });
      if (!this._authority(request, task, authority.snapshot)) throw new Error('tool-authority-changed-during-execution');
      if (value?.evidence?.some(row => row.taskId !== request.taskId || row.runId !== request.runId)) throw new Error('tool-evidence-owner-mismatch');
      const result = this._result(request, 'succeeded', value?.summary || `${request.toolId} completed.`, value?.output ?? value ?? null, value?.evidence || []);
      this.eventBus?.emit('tool.completed', { taskId: request.taskId, runId: request.runId, workerId: request.workerId, status: 'succeeded', summary: result.summary, payload: { requestId: request.requestId, toolId: request.toolId, evidenceCount: result.evidence.length } });
      return result;
    } catch (error) {
      const result = this._result(request, 'failed', String(error?.message || error).slice(0, 1000), null, []);
      this.eventBus?.emit('tool.failed', { taskId: request.taskId, runId: request.runId, workerId: request.workerId, status: 'failed', summary: result.summary, payload: { requestId: request.requestId, toolId: request.toolId } });
      return result;
    }
  }

  _authority(request, suppliedTask, expectedSnapshot = null) {
    try {
      if (!this.taskStore || suppliedTask?.taskId !== request.taskId) return null;
      const task = this.taskStore.requireTask(request.taskId); const run = this.taskStore.requireRun(request.runId);
      if (task.status !== 'active' || run.status !== 'running' || run.taskId !== task.taskId || run.activeWorkerId !== request.workerId || this.taskStore.requiresRecovery(run.runId)) return null;
      const snapshot = JSON.stringify([task, run]);
      return expectedSnapshot !== null && snapshot !== expectedSnapshot ? null : { task, snapshot };
    } catch { return null; }
  }

  _result(request, status, summary, output, evidence) { return parse(PxToolResult, { requestId: request.requestId, toolId: request.toolId, status, summary, output, evidence, completedAt: nowIso() }, 'tool-result'); }
}

function immutableRequest(value) {
  const encoded = JSON.stringify(value, (_key, item) => {
    if (typeof item === 'number' && !Number.isFinite(item) || ['undefined', 'function', 'symbol', 'bigint'].includes(typeof item)) throw new Error('tool-request-not-json');
    return item;
  });
  if (Buffer.byteLength(encoded, 'utf8') > 1024 * 1024) throw new Error('tool-request-too-large');
  const freeze = item => { if (item && typeof item === 'object') { for (const child of Object.values(item)) freeze(child); Object.freeze(item); } return item; };
  return freeze(JSON.parse(encoded));
}

module.exports = { ToolBroker };
