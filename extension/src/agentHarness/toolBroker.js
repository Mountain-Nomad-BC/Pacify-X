'use strict';

const { EFFECT_ORDER } = require('./taskStore');
const { PxToolRequest, PxToolResult, parse } = require('./contracts');
const { nowIso } = require('./ids');

class ToolBroker {
  constructor(options = {}) { this.tools = new Map(); this.approvalProvider = options.approvalProvider || null; this.eventBus = options.eventBus || null; }

  register(tool) {
    if (!tool?.toolId || !tool?.effectClass || typeof tool.execute !== 'function') throw new Error('tool-registration-invalid');
    if (this.tools.has(tool.toolId)) throw new Error(`tool-already-registered:${tool.toolId}`);
    this.tools.set(tool.toolId, { ...tool }); return { dispose: () => this.tools.delete(tool.toolId) };
  }

  list() { return [...this.tools.values()].map(({ execute, ...rest }) => rest); }

  async execute(input, task) {
    const request = parse(PxToolRequest, input, 'tool-request');
    const tool = this.tools.get(request.toolId);
    if (!tool) return this._result(request, 'blocked', 'Unknown tool.', null, []);
    if (tool.effectClass !== request.effectClass) return this._result(request, 'blocked', 'Tool effect class does not match registered authority.', null, []);
    if (EFFECT_ORDER.indexOf(request.effectClass) > EFFECT_ORDER.indexOf(task.constraints.maxEffectClass)) return this._result(request, 'blocked', 'Task stage/effect policy blocks this tool.', null, []);
    const needsApproval = tool.requireApproval === true || ['MUTATING', 'HIGH_RISK'].includes(request.effectClass);
    if (needsApproval) {
      this.eventBus?.emit('tool.approval.required', { taskId: request.taskId, runId: request.runId, workerId: request.workerId, status: 'blocked', summary: `${request.toolId} requires approval.`, payload: { requestId: request.requestId, toolId: request.toolId, effectClass: request.effectClass } });
      const approved = this.approvalProvider ? await this.approvalProvider({ request, tool, task }) : false;
      if (!approved) return this._result(request, 'blocked', 'User/PX approval not granted.', null, []);
    }
    this.eventBus?.emit('tool.started', { taskId: request.taskId, runId: request.runId, workerId: request.workerId, status: 'started', summary: request.toolId, payload: { requestId: request.requestId, effectClass: request.effectClass } });
    try {
      const value = await tool.execute({ request, task });
      const result = this._result(request, 'succeeded', value?.summary || `${request.toolId} completed.`, value?.output ?? value ?? null, value?.evidence || []);
      this.eventBus?.emit('tool.completed', { taskId: request.taskId, runId: request.runId, workerId: request.workerId, status: 'succeeded', summary: result.summary, payload: { requestId: request.requestId, toolId: request.toolId, evidenceCount: result.evidence.length } });
      return result;
    } catch (error) {
      const result = this._result(request, 'failed', String(error?.message || error).slice(0, 1000), null, []);
      this.eventBus?.emit('tool.failed', { taskId: request.taskId, runId: request.runId, workerId: request.workerId, status: 'failed', summary: result.summary, payload: { requestId: request.requestId, toolId: request.toolId } });
      return result;
    }
  }

  _result(request, status, summary, output, evidence) { return parse(PxToolResult, { requestId: request.requestId, toolId: request.toolId, status, summary, output, evidence, completedAt: nowIso() }, 'tool-result'); }
}

module.exports = { ToolBroker };
